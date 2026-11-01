"""Conectores de API JSON: consultam serviços que devolvem anúncios em JSON e os convertem para o formato do
buscador. Tudo é configurado em sites.yaml (seção `apis:`), sem programar. Cada chamada pode custar dinheiro,
então há um limite diário de chamadas por API (`limite_diario`, padrão 30)."""
import json
import re

from . import banco, normaliza as N, segredos
from .coleta import ErroColeta, separa_cidade

LIMITE_DIARIO = 30
_VAZIO = object()


def caminho(obj, path):
    """'a.b.0.c' -> valor, ou None se o caminho não existir. Números indicam posição em listas."""
    for p in str(path).split("."):
        if isinstance(obj, dict):
            obj = obj.get(p)
        elif isinstance(obj, list) and re.fullmatch(r"-?\d+", p):
            i = int(p)
            obj = obj[i] if -len(obj) <= i < len(obj) else None
        else:
            return None
        if obj is None:
            return None
    return obj


def primeiro(obj, paths):
    """Primeiro caminho (de uma lista de alternativas) que tiver valor."""
    for p in ([paths] if isinstance(paths, str) else (paths or [])):
        v = caminho(obj, p)
        if v not in (None, "", []):
            return v
    return None


def preencher(modelo, variaveis):
    """Troca {nome} pelos valores. Um texto que é só {nome} mantém o tipo (número, lista); campos sem valor saem."""
    if isinstance(modelo, dict):
        saida = {}
        for k, v in modelo.items():
            r = preencher(v, variaveis)
            if r is not _VAZIO:
                saida[k] = r
        return saida
    if isinstance(modelo, list):
        return [r for r in (preencher(x, variaveis) for x in modelo) if r is not _VAZIO]
    if isinstance(modelo, str):
        m = re.fullmatch(r"\{(\w+)\}", modelo)
        if m:
            v = variaveis.get(m.group(1))
            return v if v else _VAZIO
        r = re.sub(r"\{(\w+)\}", lambda m: str(variaveis.get(m.group(1)) or ""), modelo)
        return r if r.strip() else _VAZIO
    return modelo


def _inteiro(v):
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def variaveis(cidade, uf, fin, tipo, tipos, pagina, filtros, cfg):
    f = filtros or {}
    mf, mt = cfg.get("finalidades") or {}, cfg.get("tipos") or {}
    q, b, v = (_inteiro(f.get(k)) for k in ("quartos", "banheiros", "vagas"))
    return {
        "cidade_nome": cidade, "cidade": N.slug(cidade), "uf": uf.lower(), "UF": uf.upper(),
        "finalidade": mf.get(fin, fin) if fin else None,
        "tipo": mt.get(tipo) if tipo else None,
        "tipos": [mt[t] for t in tipos if t in mt],
        "pagina": pagina, "offset": (pagina - 1) * _inteiro(cfg.get("por_pagina") or 20),
        "bairro": f.get("bairro") or None, "pmin": _inteiro(f.get("pmin")), "pmax": _inteiro(f.get("pmax")),
        "amin": _inteiro(f.get("amin")), "quartos": q, "banheiros": b, "vagas": v,
        # APIs que pedem listas: "2 quartos ou mais" vira [2, 3, 4, 5, 6]
        "quartos_lista": list(range(q, q + 5)) if q else None,
        "banheiros_lista": list(range(b, b + 4)) if b else None,
        "vagas_lista": list(range(v, v + 4)) if v else None,
    }


def _numero(v):
    if isinstance(v, list):
        v = next((x for x in v if x not in (None, "")), None)
    return N.num(v)


def converter(item, nome, cfg, ctx):
    """Um item do JSON -> anúncio padronizado (ou None se faltar cidade, tipo, preço ou área)."""
    campos = cfg.get("campos") or {}
    g = lambda k: primeiro(item, campos.get(k))
    titulo, desc = g("titulo"), g("descricao")
    texto = " ".join(str(x) for x in (titulo, desc) if x)
    mapa_t = {str(k).lower(): v for k, v in (cfg.get("mapa_tipos") or {}).items()}
    tipo_bruto = g("tipo")
    tipo = mapa_t.get(str(tipo_bruto).lower()) if tipo_bruto else None
    tipo = tipo or N.tipo_de(texto) or ctx.get("tipo")
    mapa_c = {str(k).lower(): v for k, v in (cfg.get("mapa_caracteristicas") or {}).items()}
    carac = g("caracteristicas") or []
    carac = carac if isinstance(carac, list) else re.split(r"[|;,]", str(carac))
    extras = {mapa_c.get(str(c).lower(), str(c).lower()) for c in carac if str(c).strip()}
    extras |= set(N.caracteristicas_de(texto + " " + " ".join(str(c) for c in carac)))
    bairro = g("bairro")
    ident = g("id")
    reg = N.registro(
        id=f"{nome}:{ident}" if ident else None, cidade=g("cidade") or ctx["cidade"], uf=ctx.get("uf", ""),
        bairro=bairro, tipo=tipo, finalidade=g("finalidade") or ctx.get("finalidade"),
        preco=_numero(g("preco")), area=_numero(g("area")), quartos=_numero(g("quartos")),
        banheiros=_numero(g("banheiros")), vagas=_numero(g("vagas")), condominio=_numero(g("condominio")),
        caracteristicas=sorted(extras), fonte=nome,
        titulo=((titulo or texto or "")[:120]) or f"{tipo or 'Imóvel'} em {bairro or ctx['cidade']}", url=g("url") or "")
    return reg if N.valido(reg) else None


def escolher(config, nomes=None):
    """APIs ativas. Ao contrário dos sites, só rodam com `ativo: true` explícito (podem custar dinheiro)."""
    return {n: c for n, c in (config.get("apis") or {}).items() if c.get("ativo") is True and (not nomes or n in nomes)}


def consultar_api(col, nome, cfg, cidade, uf, fin, tipo, tipos, filtros, max_paginas, progresso):
    limite = _inteiro(cfg.get("limite_diario")) or LIMITE_DIARIO
    achados, vistos, descartados = {}, set(), 0
    for pg in range(1, max_paginas + 1):
        falta = segredos.faltando(cfg)
        if falta:
            raise ErroColeta(f"falta a chave {falta[0]}: rode  buscaimoveis chave {falta[0]}")
        if not banco.usar_api(nome, limite):
            raise ErroColeta(f"limite diário de {limite} chamadas atingido (ajuste `limite_diario` no sites.yaml)")
        v = variaveis(cidade, uf, fin, tipo, tipos, pg, filtros, cfg)
        cfg_x = segredos.expandir(cfg)
        url = preencher(cfg_x["url"], v)
        if url is _VAZIO:
            raise ErroColeta("a `url` da API ficou vazia")
        dados = col.baixar_json(url, (cfg_x.get("metodo") or "GET").upper(), preencher(cfg_x.get("parametros") or {}, v),
                                preencher(cfg_x.get("corpo") or {}, v) or None, cfg_x.get("cabecalhos") or {})
        lista = caminho(dados, cfg["resultados"]) if cfg.get("resultados") else dados
        if isinstance(lista, dict):  # APIs que devolvem {"1": {...}, "2": {...}}
            lista = [x for x in lista.values() if isinstance(x, dict)]
        lista = lista if isinstance(lista, list) else []
        ctx = {"cidade": cidade, "uf": uf.upper(), "finalidade": fin, "tipo": tipo}
        novos = []
        for it in lista:
            r = converter(it, nome, cfg, ctx) if isinstance(it, dict) else None
            if r is None:
                descartados += 1
            elif r["id"] not in vistos:
                vistos.add(r["id"])
                novos.append(r)
        progresso(f"[{nome}] {cidade} {fin or ''} {tipo or ''} pág. {pg}: {len(novos)} anúncios"
                  + (f" ({descartados} descartados por falta de tipo, preço ou área)" if descartados else ""))
        achados.update({r["id"]: r for r in novos})
        prox = cfg.get("proxima")
        if not novos or (prox and caminho(dados, prox) in (None, "", 0)):
            break
    return list(achados.values())


def buscar_apis(config, cidades, finalidades=("venda",), tipos=(), filtros=None, max_paginas=None, nomes=None,
                progresso=print, coletor=None):
    """Consulta cada API ativa para cada cidade, finalidade e tipo. Erros de uma API não interrompem as outras."""
    todos = {}
    for nome, cfg in escolher(config, nomes).items():
        modelo = json.dumps([cfg.get("url"), cfg.get("parametros"), cfg.get("corpo")], ensure_ascii=False)
        fins = finalidades if "{finalidade}" in modelo else [None]
        por_tipo = "{tipo}" in modelo
        mapa = cfg.get("tipos")
        if por_tipo and mapa and tipos:
            grupos = [(t, tipos) for t in tipos if t in mapa]
            for t in tipos:
                if t not in mapa:
                    progresso(f"[{nome}] tipo '{t}' sem equivalente em `tipos:`; ignorado nesta API")
        else:
            grupos = [(t, tipos) for t in tipos] if por_tipo and tipos else [(None, tipos)]
        for cid in cidades:
            cnome, uf = separa_cidade(cid)
            for fin in fins:
                for tp, todos_tipos in grupos:
                    try:
                        regs = consultar_api(coletor, nome, cfg, cnome, uf, fin, tp, list(todos_tipos), filtros,
                                             max_paginas or _inteiro(cfg.get("max_paginas")) or 2, progresso)
                    except ErroColeta as e:
                        progresso(f"[{nome}] {cid}: {e}")
                        continue
                    todos.update({r["id"]: r for r in regs})
    return list(todos.values())
