"""Transforma texto solto de anúncios em campos padronizados."""
import hashlib
import re
import unicodedata

COLUNAS = ["id", "cidade", "uf", "bairro", "tipo", "finalidade", "preco", "area", "quartos",
           "banheiros", "vagas", "condominio", "caracteristicas", "fonte", "titulo", "url"]

# A ordem importa: o primeiro tipo que casar vence ("cobertura" antes de "apartamento").
TIPOS = {
    "cobertura": ("cobertura",),
    "kitchenette": ("kitnet", "kitchenette", "conjugado"),
    "sala comercial": ("sala comercial", "conjunto comercial", "loja", "ponto comercial"),
    "terreno": ("terreno", "lote"),
    "casa": ("casa", "sobrado"),
    "apartamento": ("apartamento", "apto", "flat", "studio", "estudio"),
}

CARACT = {
    "piscina": ("piscina",), "varanda": ("varanda", "sacada"), "mobiliado": ("mobiliado", "mobiliada"),
    "aceita pet": ("aceita pet", "pet friendly", "aceita animais"), "elevador": ("elevador",),
    "churrasqueira": ("churrasqueira",), "academia": ("academia",),
    "portaria 24h": ("portaria 24", "portaria 24h"), "playground": ("playground",),
    "salao de festas": ("salao de festas",), "quintal": ("quintal",),
}


def sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn")


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", sem_acento(s).lower()).strip("-")


def num(v, padrao=0.0):
    """Converte '1.200.000,50', 'R$ 850.000', 85.5 ou None em float."""
    if v is None:
        return padrao
    if isinstance(v, (int, float)):
        return float(v) if v == v else padrao
    s = re.sub(r"[^\d.,]", "", str(v))
    if not s:
        return padrao
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return padrao


def tipo_de(texto):
    t = sem_acento(texto or "").lower()
    for tipo, palavras in TIPOS.items():
        if any(re.search(rf"\b{re.escape(p)}", t) for p in palavras):
            return tipo
    return ""


def finalidade_de(texto):
    return "aluguel" if re.search(r"alug|locac", sem_acento(texto or "").lower()) else "venda"


def caracteristicas_de(texto):
    t = sem_acento(texto or "").lower()
    return sorted(c for c, ps in CARACT.items()
                  if any(re.search(rf"(?<!nao )(?<!sem ){re.escape(p)}", t) for p in ps))


def bairro_de(titulo):
    m = re.search(r"\b(?:em|no|na)\s+([A-ZÀ-Ú][\wÀ-ÿ' ]{2,40}?)(?:\s*[,\-–/|]|$)", titulo or "")
    return m.group(1).strip() if m else ""


def extrair_texto(texto):
    """Lê preço, área, quartos etc. de um bloco de texto de anúncio."""
    t = " ".join(str(texto or "").split())
    preco = cond = 0.0
    for m in re.finditer(r"((?:cond\w*|iptu)[^R\d]{0,25})?R\$\s*([\d.]+(?:,\d{1,2})?)", t, re.I):
        v = num(m.group(2))
        if m.group(1) and m.group(1).lower().startswith("cond"):
            cond = cond or v
        elif not m.group(1) and not preco:
            preco = v

    def g(p):
        m = re.search(p, t, re.I)
        return num(m.group(1)) if m else 0.0

    return {"preco": preco, "condominio": cond,
            "area": g(r"(\d[\d.,]*)\s*m[²2]"),
            "quartos": g(r"(\d+)\s*(?:quartos?|dorms?\b|dormit\w*)"),
            "banheiros": g(r"(\d+)\s*(?:banheiros?|ban\b)"),
            "vagas": g(r"(\d+)\s*vagas?")}


def chaves(d, ctx=None):
    """Padroniza nomes de colunas de arquivos importados (sem acento, minúsculos)."""
    sin = {"fin": "finalidade", "link": "url"}
    o = dict(ctx or {})
    for k, v in d.items():
        k = sem_acento(str(k).strip().lower())
        k = sin.get(k, k)
        if v not in (None, ""):
            o[k] = v
    return o


def registro(**d):
    """Cria um anúncio padronizado. O id vem da URL, então sobrevive a mudanças de preço."""
    r = {c: d.get(c) for c in COLUNAS}
    for c in ("preco", "area", "quartos", "banheiros", "vagas", "condominio"):
        r[c] = num(r[c])
    for c in ("quartos", "banheiros", "vagas"):
        r[c] = int(r[c])
    for c in ("cidade", "uf", "bairro", "fonte", "titulo", "url"):
        r[c] = str(r[c] or "").strip()
    r["tipo"] = (str(r["tipo"] or "").strip().lower()) or tipo_de(r["titulo"])
    f = str(r["finalidade"] or "").strip().lower()
    r["finalidade"] = ("aluguel" if re.search(r"alug|loca", f) else "venda") if f else finalidade_de(r["url"] + " " + r["titulo"])
    r["bairro"] = r["bairro"] or bairro_de(r["titulo"])
    c = r["caracteristicas"] or ""
    c = c if isinstance(c, (list, tuple, set)) else re.split(r"[|;]", str(c))
    r["caracteristicas"] = "|".join(sorted({str(x).strip().lower() for x in c if str(x).strip()}))
    base = r["url"] or "|".join(str(r[k]) for k in ("cidade", "bairro", "tipo", "finalidade", "area", "quartos", "titulo"))
    r["id"] = str(d.get("id") or hashlib.sha1(base.encode()).hexdigest()[:16])
    return r


def valido(r):
    return bool(r["cidade"] and r["tipo"] and r["preco"] > 0 and r["area"] > 0)
