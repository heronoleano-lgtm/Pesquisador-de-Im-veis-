"""Descobre as imobiliárias de uma cidade em fontes abertas (OpenStreetMap) e, se houver chave, no Google Places."""
import os
import re
import time
from urllib.parse import urlparse

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"
PLACES = "https://places.googleapis.com/v1/places:searchText"
UA = "buscaimoveis/1.1 (uso pessoal)"
# Redes sociais e portais agregadores não são sites de imobiliária (e têm termos de uso restritivos).
IGNORAR = ("facebook.", "instagram.", "linkedin.", "google.", "wa.me", "whatsapp.", "youtube.", "twitter.",
           "tiktok.", "wikipedia.", "olx.", "zapimoveis.", "vivareal.", "quintoandar.", "imovelweb.", "chavesnamao.")


def normaliza_site(url):
    """Guarda só a página inicial (https://dominio/). Devolve '' se não for um endereço válido."""
    url = (url or "").strip()
    if not url:
        return ""
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url
    p = urlparse(url)
    return f"{p.scheme.lower()}://{p.netloc.lower()}/" if "." in p.netloc else ""


def _host(site):
    h = urlparse(site).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _get_json(cli, url, params=None, headers=None):
    r = cli.get(url, params=params, headers=headers)
    r.raise_for_status()
    return r.json()


def por_osm(cli, cidade, uf, espera=1.1):
    """Imobiliárias cadastradas no OpenStreetMap dentro dos limites da cidade."""
    q = f"{cidade}, {uf}, Brasil" if uf else f"{cidade}, Brasil"
    achados = _get_json(cli, NOMINATIM, {"q": q, "format": "jsonv2", "limit": 5}, {"User-Agent": UA})
    rel = next((x for x in achados if x.get("osm_type") == "relation"), None)
    if not rel:
        return []
    time.sleep(espera)
    consulta = f'[out:json][timeout:60];area({3600000000 + int(rel["osm_id"])})->.a;nwr["office"="estate_agent"](area.a);out tags;'
    out = []
    for e in _get_json(cli, OVERPASS, {"data": consulta}, {"User-Agent": UA}).get("elements", []):
        t = e.get("tags", {})
        if t.get("name"):
            out.append({"nome": t["name"], "origem": "OpenStreetMap",
                        "site": normaliza_site(t.get("website") or t.get("contact:website") or t.get("url")),
                        "endereco": " ".join(filter(None, [t.get("addr:street"), t.get("addr:housenumber"), t.get("addr:suburb")]))})
    return out


def por_places(cli, cidade, uf, chave, consultas=("imobiliária", "corretora de imóveis")):
    """Google Places (Text Search). Exige chave de API própria e é cobrado pelo Google."""
    out = []
    for c in consultas:
        token = None
        for _ in range(3):
            corpo = {"textQuery": f"{c} em {cidade} {uf}".strip(), "languageCode": "pt-BR", "pageSize": 20}
            if token:
                corpo["pageToken"] = token
            r = cli.post(PLACES, json=corpo, headers={
                "X-Goog-Api-Key": chave, "Content-Type": "application/json",
                "X-Goog-FieldMask": "places.displayName,places.websiteUri,places.formattedAddress,nextPageToken"})
            r.raise_for_status()
            d = r.json()
            for p in d.get("places", []):
                nome = (p.get("displayName") or {}).get("text")
                if nome:
                    out.append({"nome": nome, "origem": "Google Places", "site": normaliza_site(p.get("websiteUri")),
                                "endereco": p.get("formattedAddress", "")})
            token = d.get("nextPageToken")
            if not token:
                break
    return out


def descobrir(cidade_uf, cliente=None, chave=None, osm=True, espera=1.1, progresso=print):
    cidade, _, uf = cidade_uf.partition("/")
    cidade, uf = cidade.strip(), uf.strip().upper()
    cli = cliente
    if cli is None:
        import httpx
        cli = httpx.Client(timeout=60, follow_redirects=True)
    brutos = []
    if osm:
        try:
            brutos += por_osm(cli, cidade, uf, espera)
        except Exception as e:
            progresso(f"OpenStreetMap indisponível: {e}")
    chave = chave or os.environ.get("GOOGLE_PLACES_KEY")
    if chave:
        try:
            brutos += por_places(cli, cidade, uf, chave)
        except Exception as e:
            progresso(f"Google Places indisponível: {e}")
    vistos, saida = set(), []
    for b in brutos:
        if b["site"] and any(i in b["site"] for i in IGNORAR):
            continue
        chave_u = _host(b["site"]) if b["site"] else "nome:" + b["nome"].lower()
        if chave_u in vistos:
            continue
        vistos.add(chave_u)
        saida.append(dict(b, cidade=cidade, uf=uf))
    if not saida:
        progresso("Nenhuma imobiliária encontrada nas fontes consultadas. Adicione os sites manualmente.")
    return saida
