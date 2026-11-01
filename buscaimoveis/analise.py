"""Análise com pandas: duplicados, mediana por região/tipo, anúncios suspeitos, filtros e pontuação."""
import numpy as np
import pandas as pd

CHAVE_DUP = ["cidade", "bairro", "tipo", "finalidade", "preco", "area", "quartos"]
GRUPO = ["cidade", "finalidade", "tipo"]


def analisar(df):
    """Prepara a base: remove duplicados entre sites e calcula R$/m² frente à mediana."""
    if df.empty:
        return df.assign(feat=[], pm=[], mediana_pm=[], desvio=[], suspeito=[], fontes=[])
    df = df.copy()
    for c in ("cidade", "bairro", "tipo", "finalidade", "fonte", "caracteristicas"):
        df[c] = df[c].fillna("")
    fontes = df.groupby(CHAVE_DUP)["fonte"].agg(lambda s: ", ".join(sorted(set(s)))).rename("fontes").reset_index()
    df = df.drop_duplicates(CHAVE_DUP).merge(fontes, on=CHAVE_DUP, how="left")
    df["feat"] = df.caracteristicas.map(lambda x: [f for f in x.split("|") if f])
    df["pm"] = df.preco / df.area.replace(0, np.nan)
    g = df.groupby(GRUPO).pm
    n, med = g.transform("count"), g.transform("median")
    fallback = df.groupby(["cidade", "finalidade"]).pm.transform("median")
    df["mediana_pm"] = np.where(n >= 3, med, fallback)
    df["desvio"] = df.pm / df.mediana_pm - 1
    q1, q3 = g.transform(lambda s: s.quantile(.25)), g.transform(lambda s: s.quantile(.75))
    iqr = q3 - q1
    df["suspeito"] = (n >= 5) & ((df.pm < q1 - 1.5 * iqr) | (df.pm > q3 + 1.5 * iqr))
    return df


def filtrar(df, finalidade=None, cidades=(), tipos=(), bairro="", pmin=0, pmax=0, amin=0, qmin=0,
            bmin=0, vmin=0, cmax=0, obrigatorias=(), sem_suspeitos=False, ids=()):
    if df.empty:
        return df
    m = pd.Series(True, index=df.index)
    if finalidade:
        m &= df.finalidade == finalidade
    if cidades:
        m &= df.cidade.isin(cidades)
    if tipos:
        m &= df.tipo.isin(tipos)
    if bairro:
        m &= df.bairro.str.lower().str.contains(bairro.lower(), regex=False)
    if pmin:
        m &= df.preco >= pmin
    if pmax:
        m &= df.preco <= pmax
    if amin:
        m &= df.area >= amin
    m &= (df.quartos >= qmin) & (df.banheiros >= bmin) & (df.vagas >= vmin)
    if cmax:
        m &= df.condominio <= cmax
    for f in obrigatorias:
        m &= df.feat.map(lambda x, f=f: f in x)
    if sem_suspeitos:
        m &= ~df.suspeito
    if ids:
        m = df.id.isin(ids)
    return df[m]


def pontuar(df, desejaveis=(), bairros=(), pesos=(3, 2, 1)):
    """Nota de 0 a 100: preço frente à mediana, características desejadas e bairros preferidos."""
    if df.empty:
        return df.assign(nota=[])
    df = df.copy()
    sp = (50 - df.desvio.fillna(0) * 150).clip(0, 100)
    d = set(desejaveis)
    sd = df.feat.map(lambda f: len(d & set(f)) / len(d) * 100) if d else pd.Series(50.0, index=df.index)
    bs = [b.lower() for b in bairros]
    sb = df.bairro.str.lower().map(lambda x: 100 if any(b in x for b in bs) else 20) if bs else pd.Series(50.0, index=df.index)
    w = np.array(pesos, dtype=float)
    df["nota"] = ((w[0] * sp + w[1] * sd + w[2] * sb) / (w.sum() or 1)).round().astype(int)
    return df


ORDENS = {"nota": ("nota", False), "preco": ("preco", True), "preco_desc": ("preco", False),
          "pm": ("pm", True), "area": ("area", False)}


def ordenar(df, ordem="nota"):
    col, asc = ORDENS.get(ordem, ORDENS["nota"])
    return df.sort_values(col, ascending=asc) if col in df else df
