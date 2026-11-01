"""Coleta: baixa páginas de resultados (com educação) e extrai anúncios."""
import ipaddress
import json
import re
import socket
import time
from pathlib import Path
from urllib import robotparser
from urllib.parse import quote, urljoin, urlparse


from . import normaliza as N
from .sopa import sopa

UA = "buscaimoveis/1.0 (uso pessoal)"


class ErroColeta(Exception):
    pass


class PermissaoNegada(ErroColeta):
    pass


def endereco_interno(url):
    """True se o endereço aponta para a própria máquina ou para a rede local (loopback, 192.168.x.x, nuvem...)."""
    host = urlparse(url).hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False  # não resolveu: a requisição falha por conta própria
    for i in infos:
        ip = ipaddress.ip_address(i[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return True
    return False


class Coletor:
    """Cliente HTTP com espera entre pedidos, tentativas e respeito ao robots.txt."""

    def __init__(self, atraso=3.0, respeitar_robots=True, timeout=25, tentativas=3,
                 user_agent=UA, cliente=None, bloquear_internos=False):
        self.bloquear_internos = bloquear_internos
        if cliente is None:
            import httpx
            ganchos = {"request": [self._checa]} if bloquear_internos else {}
            cliente = httpx.Client(headers={"User-Agent": user_agent, "Accept-Language": "pt-BR,pt;q=0.9"},
                                   timeout=timeout, follow_redirects=True, event_hooks=ganchos)
        self.cli, self.atraso, self.robots = cliente, atraso, respeitar_robots
        self.tentativas, self.ua = tentativas, user_agent
        self._rb, self._ultimo = {}, {}

    def _checa(self, request):
        """Roda a cada pedido, inclusive nos redirecionamentos."""
        if endereco_interno(str(request.url)):
            raise PermissaoNegada(f"endereço da rede interna bloqueado: {request.url.host}")

    def permitido(self, url):
        if not self.robots:
            return True
        u = urlparse(url)
        base = f"{u.scheme}://{u.netloc}"
        if base not in self._rb:
            rp = robotparser.RobotFileParser()
            try:
                r = self.cli.get(base + "/robots.txt")
                if r.status_code >= 500:
                    rp.disallow_all = True
                elif r.status_code >= 400:
                    rp.allow_all = True
                else:
                    rp.parse(r.text.splitlines())
                    rp.modified()
            except Exception:
                rp.allow_all = True
            self._rb[base] = rp
        return self._rb[base].can_fetch(self.ua, url)

    def baixar(self, url, dados=None, metodo="GET", render=False):
        if self.bloquear_internos and endereco_interno(url):
            raise PermissaoNegada(f"endereço da rede interna bloqueado: {urlparse(url).hostname}")
        if not self.permitido(url):
            raise PermissaoNegada(f"o robots.txt do site não permite acessar {url}")
        host = urlparse(url).netloc
        erro = "sem resposta"
        for t in range(self.tentativas):
            espera = self.atraso - (time.monotonic() - self._ultimo.get(host, 0))
            if espera > 0:
                time.sleep(espera)
            self._ultimo[host] = time.monotonic()
            try:
                if render:
                    return _baixar_navegador(url, self.ua)
                r = self.cli.post(url, data=dados) if metodo == "POST" else (self.cli.get(url, params=dados) if dados else self.cli.get(url))
                if r.status_code in (429, 503):
                    erro = f"o site pediu para reduzir o ritmo (código {r.status_code})"
                    time.sleep(5 * (t + 1))
                    continue
                r.raise_for_status()
                return r.text
            except ErroColeta:
                raise
            except Exception as e:
                erro = str(e)
                time.sleep(2 * (t + 1))
        raise ErroColeta(f"{url}: {erro}")


def _baixar_json(self, url, metodo="GET", params=None, corpo=None, cabecalhos=None):
    """Pede um JSON a uma API (mesma espera, tentativas e bloqueio de rede interna). Mensagens de erro nunca
    incluem o endereço completo, para não vazar chaves que vão na URL."""
    if self.bloquear_internos and endereco_interno(url):
        raise PermissaoNegada(f"endereço da rede interna bloqueado: {urlparse(url).hostname}")
    host, erro = urlparse(url).netloc, "sem resposta"
    for t in range(self.tentativas):
        espera = self.atraso - (time.monotonic() - self._ultimo.get(host, 0))
        if espera > 0:
            time.sleep(espera)
        self._ultimo[host] = time.monotonic()
        try:
            r = self.cli.request(metodo, url, params=params or None, json=corpo, headers=cabecalhos or None)
            if r.status_code in (429, 503):
                erro = f"a API pediu para reduzir o ritmo (código {r.status_code})"
                time.sleep(5 * (t + 1))
                continue
            if r.status_code in (401, 403):
                raise ErroColeta(f"a API recusou a chave (código {r.status_code})")
            if r.status_code == 402:
                raise ErroColeta("a API informou falta de créditos (código 402)")
            if r.status_code >= 400:
                raise ErroColeta(f"a API respondeu com erro (código {r.status_code})")
            return r.json()
        except ErroColeta:
            raise
        except Exception as e:
            erro = f"falha na chamada ({type(e).__name__})"
            time.sleep(2 * (t + 1))
    raise ErroColeta(f"{host}: {erro}")


Coletor.baixar_json = _baixar_json


def _baixar_navegador(url, ua):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ErroColeta("para sites que exigem navegador: pip install playwright && playwright install chromium")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(user_agent=ua)
        pg.goto(url, wait_until="networkidle")
        html = pg.content()
        b.close()
        return html


# ---------- extração ----------

def _percorrer(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _percorrer(v)
    elif isinstance(o, list):
        for v in o:
            yield from _percorrer(v)


def _valor(x):
    return (x.get("value") or x.get("name") or x.get("@value")) if isinstance(x, dict) else x


def de_jsonld(soup, base_url, ctx):
    """Lê dados estruturados (schema.org) — o método mais estável quando o site os oferece."""
    achados = {}
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            dados = json.loads(s.string or s.get_text())
        except ValueError:
            continue
        for o in _percorrer(dados):
            of = o.get("offers")
            of = of[0] if isinstance(of, list) and of else of
            if not (o.get("name") and isinstance(of, dict)):
                continue
            preco = of.get("price") or of.get("lowPrice")
            if not preco:
                continue
            end = o.get("address") or {}
            end = {"streetAddress": end} if isinstance(end, str) else end
            texto = " ".join(str(x) for x in (o.get("name"), o.get("description")) if x)
            ext = N.extrair_texto(texto)
            url = urljoin(base_url, o.get("url") or of.get("url") or "")
            achados[url or o["name"]] = dict(
                ctx, titulo=o["name"], url=url, preco=preco,
                tipo=N.tipo_de(o["name"]) or ctx.get("tipo"),
                area=_valor(o.get("floorSize")) or ext["area"],
                quartos=o.get("numberOfBedrooms") or o.get("numberOfRooms") or ext["quartos"],
                banheiros=o.get("numberOfBathroomsTotal") or o.get("numberOfBathrooms") or ext["banheiros"],
                vagas=ext["vagas"], condominio=ext["condominio"],
                bairro=end.get("addressNeighborhood") or ctx.get("bairro"),
                caracteristicas=N.caracteristicas_de(texto))
    return list(achados.values())


_BLOCOS = ["article", "li", "div", "section"]


def de_cartoes(soup, base_url, ctx, sel=None):
    """Acha cartões de anúncio: pelos seletores do sites.yaml ou por detecção (R$ + m² + link)."""
    sel = sel or {}
    if sel.get("cartao"):
        cartoes = soup.select(sel["cartao"])
    else:
        cand = [e for e in soup.find_all(_BLOCOS) if e.find("a", href=True)
                and "R$" in e.get_text(" ") and re.search(r"m[²2]", e.get_text(" "))
                and len(e.get_text(" ")) < 1200]
        ids = {id(e) for e in cand}
        cartoes = [e for e in cand if not any(id(d) in ids for d in e.find_all(_BLOCOS))]
    saida = []
    for c in cartoes:
        def pegar(k):
            el = c.select_one(sel[k]) if sel.get(k) else None
            return el.get_text(" ", strip=True) if el else None
        txt = c.get_text(" ", strip=True)
        a = c.select_one(sel["link"]) if sel.get("link") else c.find("a", href=True)
        url = urljoin(base_url, a["href"]) if a is not None and a.get("href") else ""
        titulo = pegar("titulo") or (a.get("title") if a is not None else None) \
            or (a.get_text(" ", strip=True) if a is not None else "") or txt[:80]
        ext = N.extrair_texto(txt)
        p, ar = pegar("preco"), pegar("area")
        if p:
            ext["preco"] = N.extrair_texto(p)["preco"] or N.num(p) or ext["preco"]
        if ar:
            ext["area"] = N.num(ar) or ext["area"]
        if ext["preco"] > 0:
            saida.append(dict(ctx, titulo=titulo, url=url, tipo=N.tipo_de(titulo) or ctx.get("tipo"),
                              bairro=pegar("bairro") or ctx.get("bairro"),
                              caracteristicas=N.caracteristicas_de(txt), **ext))
    return saida


def extrair(html, url, ctx, sel=None):
    """Devolve (anúncios, método). Tenta dados estruturados e, se rendem pouco, os cartões."""
    soup = sopa(html)
    itens, metodo = de_jsonld(soup, url, ctx), "dados estruturados"
    if len(itens) < 3 or sel:
        cart = de_cartoes(soup, url, ctx, sel)
        if len(cart) > len(itens) or (sel and cart):
            itens, metodo = cart, "cartões da página"
    regs = [r for r in (N.registro(**d) for d in itens) if N.valido(r)]
    return regs, metodo


# ---------- busca nos sites configurados ----------

def separa_cidade(txt):
    nome, _, uf = txt.partition("/")
    return nome.strip(), uf.strip()


def montar_url(cfg, cidade, uf, fin, tipo, pagina):
    mapa = lambda tab, k: (cfg.get(tab) or {}).get(k, k)
    try:
        return cfg["url"].format(cidade=N.slug(cidade), cidade_nome=quote(cidade), uf=uf.lower(), UF=uf.upper(),
                                 finalidade=mapa("finalidades", fin), tipo=mapa("tipos", tipo), pagina=pagina)
    except KeyError as e:
        raise ErroColeta(f"marcador desconhecido na url do site: {e}")


def buscar(config, cidades, finalidades=("venda",), tipos=(), max_paginas=None, sites=None,
           progresso=print, coletor=None, filtros=None):
    """Percorre sites e APIs ativos × cidades × finalidades × tipos × páginas e devolve a lista de anúncios."""
    from . import conectores
    escolhidos = {n: c for n, c in config["sites"].items() if (not sites or n in sites) and c.get("ativo", True)}
    apis = conectores.escolher(config, sites)
    if not escolhidos and not apis:
        progresso("Nenhum site ou API ativo. Edite o arquivo sites.yaml (comando: buscaimoveis config).")
        return []
    col = coletor or Coletor(atraso=config["coleta"].get("atraso", 3.0),
                             respeitar_robots=config["coleta"].get("respeitar_robots", True),
                             user_agent=config["coleta"].get("user_agent", UA))
    todos = {}
    for nome, cfg in escolhidos.items():
        url_t = cfg.get("url", "")
        fins = finalidades if "{finalidade}" in url_t else [None]
        tps = (tipos or [None]) if "{tipo}" in url_t else [None]
        for cid in cidades:
            cnome, uf = separa_cidade(cid)
            for fin in fins:
                for tp in tps:
                    vistos = set()
                    for pg in range(1, (max_paginas or cfg.get("max_paginas", 3)) + 1):
                        try:
                            url = montar_url(cfg, cnome, uf, fin or "venda", tp or "", pg)
                            html = col.baixar(url, render=cfg.get("render", False))
                        except ErroColeta as e:
                            progresso(f"[{nome}] {cid}: {e}")
                            break
                        ctx = {"cidade": cnome, "uf": uf.upper(), "fonte": nome, "finalidade": fin, "tipo": tp}
                        regs, metodo = extrair(html, url, ctx, cfg.get("seletores"))
                        novos = [r for r in regs if r["id"] not in vistos]
                        vistos.update(r["id"] for r in novos)
                        progresso(f"[{nome}] {cid} {fin or ''} {tp or ''} pág. {pg}: {len(novos)} anúncios ({metodo})")
                        for r in novos:
                            todos[r["id"]] = r
                        if not novos:
                            break
    if apis:
        for r in conectores.buscar_apis(config, cidades, finalidades, tipos, filtros, max_paginas, sites, progresso, col):
            todos[r["id"]] = r
    return list(todos.values())


# ---------- importação de arquivos ----------

def importar_arquivo(caminho, ctx=None):
    """Lê CSV, JSON ou uma página HTML salva do navegador."""
    p, ctx = Path(caminho), ctx or {}
    s = p.suffix.lower()
    if s in (".html", ".htm"):
        regs, _ = extrair(p.read_text(encoding="utf-8", errors="ignore"), p.resolve().as_uri(),
                          dict(ctx, fonte=ctx.get("fonte") or p.stem))
        return regs
    if s == ".json":
        dados = json.loads(p.read_text(encoding="utf-8"))
        linhas = dados if isinstance(dados, list) else [dados]
    else:
        import pandas as pd
        linhas = pd.read_csv(p, sep=None, engine="python", dtype=str).fillna("").to_dict("records")
    regs = [N.registro(**N.chaves(l, dict({"fonte": "importado"}, **ctx))) for l in linhas]
    return [r for r in regs if N.valido(r)]
