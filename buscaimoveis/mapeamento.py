"""Localiza o mecanismo de busca de cada imobiliária e consulta o site aplicando os filtros."""
import datetime as dt
import re
from urllib.parse import parse_qs, urljoin, urlparse


from . import banco, coleta, normaliza as N
from .sopa import sopa
from .coleta import ErroColeta, extrair

BUSCA_EXATA = {"q", "busca", "search", "s", "palavra", "keyword", "termo", "palavrachave", "pesquisa"}
PAPEIS = (("finalidade", ("finalidade", "negocio", "operacao", "transacao", "modalidade", "comprar", "alugar", "contrato")),
          ("tipo", ("tipo", "categoria", "imovel", "property")),
          ("bairro", ("bairro", "neighborhood", "regiao")),
          ("cidade", ("cidade", "city", "municipio", "localidade", "localizacao")),
          ("quartos", ("quarto", "dorm", "bedroom")), ("banheiros", ("banheiro", "bathroom")),
          ("vagas", ("vaga", "garagem", "parking")))
FIN = {"venda": r"compr|vend", "aluguel": r"alug|locac"}
IGNORA_LINK = re.compile(r"blog|contato|quem-somos|sobre|politica|termos|login|whatsapp|facebook|instagram|vender|anunci|\.pdf", re.I)


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", N.sem_acento(s or "").lower())


def _host(u):
    h = urlparse(u).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def papel(nome):
    """Descobre para que serve um campo de formulário pelo nome."""
    n = _norm(nome)
    if not n:
        return None
    if "codigo" in n or n.startswith("ref"):
        return "busca"
    preco = any(k in n for k in ("preco", "valor", "price"))
    if preco and "min" in n:
        return "pmin"
    if preco and ("max" in n or "ate" in n):
        return "pmax"
    if "area" in n and "min" in n:
        return "amin"
    for p, sins in PAPEIS:
        if any(s in n for s in sins):
            return p
    return "busca" if n in BUSCA_EXATA else None


def _rotulo(el, form):
    i = el.get("id")
    if i:
        l = form.find("label", attrs={"for": i})
        if l:
            return l.get_text(" ", strip=True)
    p = el.find_parent("label")
    return p.get_text(" ", strip=True) if p else str(el.get("value") or "")


def formularios(soup, base):
    """Formulários de busca de imóveis da página (ignora login, newsletter e contato)."""
    achados = []
    for f in soup.find_all("form"):
        metodo, acao = (f.get("method") or "get").upper(), f.get("action") or ""
        if metodo not in ("GET", "POST") or re.search(r"login|newsletter|cadastr|contato|assin", acao, re.I):
            continue
        if f.find("input", attrs={"type": re.compile("^(password|email)$", re.I)}):
            continue
        ocultos, campos = {}, {}
        for el in f.find_all(["input", "select"]):
            nome = el.get("name")
            if not nome:
                continue
            t = (el.get("type") or "text").lower() if el.name == "input" else "select"
            if t == "hidden":
                ocultos[nome] = el.get("value", "")
                continue
            if t in ("submit", "button", "image", "reset", "file", "tel"):
                continue
            c = campos.setdefault(nome, {"nome": nome, "tipo": t, "opcoes": []})
            if t == "select":
                c["opcoes"] += [{"valor": o.get("value", o.get_text(strip=True)), "texto": o.get_text(" ", strip=True)}
                                for o in el.find_all("option")]
            elif t in ("radio", "checkbox"):
                c["opcoes"].append({"valor": el.get("value", "on"), "texto": _rotulo(el, f)})
            if "papel" not in c:
                c["papel"] = papel(nome) or (papel(el.get("placeholder")) if t in ("text", "search") else None)
        lista = [c for c in campos.values() if c.get("papel")]
        if any(c["papel"] != "busca" for c in lista):
            achados.append({"action": urljoin(base, acao), "metodo": metodo, "ocultos": ocultos, "campos": lista})
    return achados


def melhor_formulario(forms):
    return max(forms, key=lambda f: (len({c["papel"] for c in f["campos"]}),
                                     any(c["papel"] in ("finalidade", "tipo") for c in f["campos"])), default=None)


def links_listagem(soup, base):
    """Links da página inicial que levam a listagens de venda ou aluguel."""
    achados = {}
    for a in soup.find_all("a", href=True):
        h = urljoin(base, a["href"]).split("#")[0]
        if not h.startswith("http") or _host(h) != _host(base) or IGNORA_LINK.search(h) or h.rstrip("/") == base.rstrip("/"):
            continue
        alvo = N.sem_acento(urlparse(h).path + " " + a.get_text(" ", strip=True)).lower()
        for fin, pad in FIN.items():
            if re.search(pad, alvo):
                achados.setdefault(h, {"url": h, "finalidade": fin, "tipo": N.tipo_de(alvo)})
                break
    return list(achados.values())


def _opcao(c, papel_, desejado):
    if not desejado or not c["opcoes"]:
        return None
    for o in c["opcoes"]:
        t = N.sem_acento(f'{o["texto"]} {o["valor"]}').lower()
        if papel_ == "finalidade" and re.search(FIN[desejado], t):
            return o["valor"]
        if papel_ == "tipo" and desejado in (N.tipo_de(o["texto"]), N.tipo_de(o["valor"])):
            return o["valor"]
        if papel_ in ("cidade", "bairro") and o["valor"] != "" and N.slug(desejado) in N.slug(o["texto"]):
            return o["valor"]
        if papel_ == "num":
            m = re.search(r"\d+", f'{o["texto"]} {o["valor"]}')
            if m and int(m.group()) == int(desejado):
                return o["valor"]
    return None


def montar_consulta(form, f, tipo=None):
    """Preenche o formulário com os filtros. Devolve (url, dados, método) ou None se a cidade não consta no site."""
    dados = dict(form["ocultos"])
    for c in form["campos"]:
        p, ops, v = c["papel"], c["opcoes"], None
        if p == "finalidade":
            v = _opcao(c, p, f.get("finalidade"))
        elif p == "tipo":
            v = _opcao(c, p, tipo)
        elif p == "cidade":
            if ops:
                v = _opcao(c, p, f.get("cidade"))
                if v is None:
                    return None
            else:
                v = f.get("cidade")
        elif p in ("bairro", "quartos", "banheiros", "vagas", "pmin", "pmax", "amin") and f.get(p):
            w = f[p]
            if ops:
                v = _opcao(c, "num" if p in ("quartos", "banheiros", "vagas") else p, w)
            else:
                v = int(w) if p != "bairro" and isinstance(w, (int, float)) else w
        if v not in (None, ""):
            dados[c["nome"]] = v
    return form["action"], dados, form["metodo"]


def proxima_url(soup, url, atual):
    a = soup.find("a", attrs={"rel": "next"}, href=True)
    if a:
        return urljoin(url, a["href"])
    for a in soup.find_all("a", href=True):
        t = N.sem_acento(a.get_text(" ", strip=True) + " " + (a.get("aria-label") or "")).lower().strip()
        if re.fullmatch(r"(proxima|proximo|seguinte|next|>|›|»)( pagina)?", t) or t.startswith("proxima pag"):
            return urljoin(url, a["href"])
    alvo, base = str(atual + 1), urlparse(url)
    for a in soup.find_all("a", href=True):
        h = urljoin(url, a["href"])
        u = urlparse(h)
        q = parse_qs(u.query)
        if u.path == base.path and any(q.get(k) == [alvo] for k in ("pagina", "page", "pag", "pg", "p")):
            return h
        if re.search(rf"/(pagina|page|p)/{alvo}/?$", u.path) and u.netloc == base.netloc:
            return h
    return None


def mapear(col, imob, progresso=print):
    """Acessa a página inicial, acha a busca do site e confirma que dá para ler anúncios dela.
    Devolve (status, perfil). Status: ok, nao_lido, sem_busca."""
    site = imob["site"]
    perfil = {"form": None, "listagens": [], "metodo": None, "testado": 0, "detalhe": ""}
    soup = sopa(col.baixar(site))
    perfil["form"] = form = melhor_formulario(formularios(soup, site))
    ctx = {"cidade": imob["cidade"], "uf": imob.get("uf", ""), "fonte": imob["nome"]}
    if form:
        m = montar_consulta(form, {"finalidade": "venda", "cidade": imob["cidade"]})
        if m is None:
            perfil["detalhe"] = "a cidade não consta no formulário de busca do site"
        else:
            try:
                regs, _ = extrair(col.baixar(m[0], m[1], m[2]), m[0], dict(ctx, finalidade="venda"))
                if regs:
                    perfil.update(metodo="formulário", testado=len(regs))
                    return "ok", perfil
            except ErroColeta as e:
                perfil["detalhe"] = str(e)
    links = links_listagem(soup, site)
    for l in links[:6]:
        try:
            regs, _ = extrair(col.baixar(l["url"]), l["url"], dict(ctx, finalidade=l["finalidade"]))
        except ErroColeta:
            continue
        if regs:
            perfil["listagens"].append(dict(l, testado=len(regs)))
    if perfil["listagens"]:
        perfil.update(metodo="links", testado=sum(l["testado"] for l in perfil["listagens"]))
        return "ok", perfil
    if form or links:
        perfil["detalhe"] = perfil["detalhe"] or "busca encontrada, mas nenhum anúncio foi lido (provável página montada por JavaScript)"
        return "nao_lido", perfil
    perfil["detalhe"] = "nenhum formulário de busca nem link de listagem encontrado"
    return "sem_busca", perfil


def consultar(col, imob, perfil, filtros, max_paginas=3, progresso=print):
    """Consulta uma imobiliária já mapeada com os filtros do usuário e percorre as páginas."""
    nome, fin = imob["nome"], filtros.get("finalidade") or "venda"
    tipos = list(filtros.get("tipos") or []) or [None]
    base = {"cidade": imob["cidade"], "uf": imob.get("uf", ""), "fonte": nome}
    alvos = []
    if perfil.get("metodo") == "formulário":
        for tp in tipos:
            m = montar_consulta(perfil["form"], dict(filtros, cidade=imob["cidade"], finalidade=fin), tp)
            if m is None:
                progresso(f"[{nome}] a cidade {imob['cidade']} não consta no formulário do site")
                return []
            usou = any(c["papel"] == "tipo" and c["nome"] in m[1] for c in perfil["form"]["campos"])
            alvos.append((m[0], m[1], m[2], tp if usou else None))
    else:
        ls = [l for l in perfil.get("listagens", []) if l["finalidade"] == fin]
        pedidos = [t for t in tipos if t]
        esp = [l for l in ls if l.get("tipo") in pedidos] if pedidos else []
        alvos = [(l["url"], None, "GET", l.get("tipo")) for l in (esp or ls)]
    todos = {}
    for url, dados, metodo, tp in alvos:
        vistos, visitadas = set(), set()
        for pg in range(1, max_paginas + 1):
            if not url or url in visitadas:
                break
            visitadas.add(url)
            try:
                html = col.baixar(url, dados, metodo)
            except ErroColeta as e:
                progresso(f"[{nome}] {e}")
                break
            regs, _ = extrair(html, url, dict(base, finalidade=fin, tipo=tp))
            novos = [r for r in regs if r["id"] not in vistos]
            progresso(f"[{nome}] {tp or 'todos os tipos'} pág. {pg}: {len(novos)} anúncios")
            if not novos:
                break
            vistos.update(r["id"] for r in novos)
            todos.update({r["id"]: r for r in novos})
            url, dados, metodo = proxima_url(sopa(html), url, pg), None, "GET"
    return list(todos.values())


def mapear_selecionadas(col, cidade=None, refazer=False, progresso=print):
    for im in banco.listar_imobiliarias(cidade, so_selecionadas=True):
        if not im["site"]:
            banco.gravar_perfil(im["id"], "sem_site", {"detalhe": "sem site cadastrado"})
            continue
        if im["status"] == "ok" and not refazer:
            continue
        try:
            status, perfil = mapear(col, im, progresso)
        except ErroColeta as e:
            status, perfil = "erro", {"detalhe": str(e)}
        banco.gravar_perfil(im["id"], status, perfil)
        progresso(f"[{im['nome']}] {status}" + (f": {perfil.get('detalhe')}" if perfil.get("detalhe") else
                                                f" ({perfil['metodo']}, {perfil['testado']} anúncios de teste)"))


def consultar_todas(col, filtros, cidade=None, paginas=3, progresso=print):
    regs = []
    prontas = [i for i in banco.listar_imobiliarias(cidade, so_selecionadas=True) if i["status"] == "ok"]
    if not prontas:
        progresso("Nenhuma imobiliária mapeada com busca funcionando. Rode o mapeamento primeiro.")
    for im in prontas:
        try:
            achados = consultar(col, im, im["perfil"], filtros, paginas, progresso)
        except ErroColeta as e:
            progresso(f"[{im['nome']}] {e}")
            continue
        banco.salvar(achados)
        regs += achados
    progresso(f"Concluído: {len(regs)} anúncios lidos em {len(prontas)} imobiliárias.")
    return regs


def explorar(col, cidade_uf, filtros, paginas=3, chave=None, cliente_api=None, progresso=print):
    """Fluxo completo: descobre as imobiliárias, mapeia as buscas e consulta com os filtros."""
    from . import descoberta
    cidade = coleta.separa_cidade(cidade_uf)[0]
    achadas = descoberta.descobrir(cidade_uf, cliente=cliente_api, chave=chave, progresso=progresso)
    progresso(f"{len(achadas)} imobiliárias encontradas ({banco.salvar_imobiliarias(achadas)} novas).")
    mapear_selecionadas(col, cidade, False, progresso)
    return consultar_todas(col, filtros, cidade, paginas, progresso)
