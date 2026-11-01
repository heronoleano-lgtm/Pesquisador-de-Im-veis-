"""Armazenamento em SQLite (arquivo na pasta do usuário) com histórico de preços."""
import datetime as dt
import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from .normaliza import COLUNAS, slug

NUMERICAS = {"preco", "area", "quartos", "banheiros", "vagas", "condominio"}


def casa():
    p = Path(os.environ.get("BUSCAIMOVEIS_HOME") or Path.home() / ".buscaimoveis")
    p.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def conexao():
    c = sqlite3.connect(casa() / "imoveis.db")
    cols = ", ".join(f"{k} {'REAL' if k in NUMERICAS else 'TEXT'}{' PRIMARY KEY' if k == 'id' else ''}" for k in COLUNAS)
    c.execute(f"CREATE TABLE IF NOT EXISTS imoveis ({cols}, primeira_vez TEXT, ultima_vez TEXT, ativo INTEGER DEFAULT 1)")
    c.execute("CREATE TABLE IF NOT EXISTS historico (id TEXT, data TEXT, preco REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS imobiliarias (id TEXT PRIMARY KEY, nome TEXT, site TEXT, endereco TEXT, "
              "cidade TEXT, uf TEXT, origem TEXT, selecionada INTEGER DEFAULT 1, status TEXT DEFAULT 'novo', "
              "perfil TEXT DEFAULT '{}', mapeado_em TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS buscas (id TEXT PRIMARY KEY, nome TEXT, cidade TEXT, uf TEXT, filtros TEXT, "
              "ativa INTEGER DEFAULT 1, criada_em TEXT, ultima_exec TEXT, ultimo_status TEXT, ultimo_resumo TEXT, "
              "intervalo_min INTEGER, paginas INTEGER DEFAULT 2, baseline INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS vistos (busca_id TEXT, imovel_id TEXT, preco REAL, PRIMARY KEY (busca_id, imovel_id))")
    c.execute("CREATE TABLE IF NOT EXISTS alertas (id INTEGER PRIMARY KEY AUTOINCREMENT, busca_id TEXT, imovel_id TEXT, "
              "tipo TEXT, chave TEXT UNIQUE, dados TEXT, criado_em TEXT, lido INTEGER DEFAULT 0, enviado INTEGER DEFAULT 0, "
              "tentativas INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS uso_api (api TEXT, dia TEXT, chamadas INTEGER DEFAULT 0, PRIMARY KEY (api, dia))")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def salvar(regs):
    """Grava anúncios. Devolve (novos, com_preco_alterado)."""
    agora = dt.datetime.now().isoformat(timespec="seconds")
    novos = alterados = 0
    with conexao() as c:
        for r in regs:
            ant = c.execute("SELECT preco FROM imoveis WHERE id=?", (r["id"],)).fetchone()
            if ant is None:
                c.execute(f"INSERT INTO imoveis ({','.join(COLUNAS)}, primeira_vez, ultima_vez, ativo) "
                          f"VALUES ({','.join('?' * len(COLUNAS))}, ?, ?, 1)", [r[k] for k in COLUNAS] + [agora, agora])
                c.execute("INSERT INTO historico VALUES (?,?,?)", (r["id"], agora, r["preco"]))
                novos += 1
            else:
                if abs((ant[0] or 0) - r["preco"]) > 0.5:
                    c.execute("INSERT INTO historico VALUES (?,?,?)", (r["id"], agora, r["preco"]))
                    alterados += 1
                sets = ", ".join(f"{k}=?" for k in COLUNAS if k != "id")
                c.execute(f"UPDATE imoveis SET {sets}, ultima_vez=?, ativo=1 WHERE id=?",
                          [r[k] for k in COLUNAS if k != "id"] + [agora, r["id"]])
    return novos, alterados


def desativar_antigos(fonte, cidade, antes):
    """Marca como fora do ar os anúncios de um site/cidade que não apareceram na coleta."""
    with conexao() as c:
        return c.execute("UPDATE imoveis SET ativo=0 WHERE fonte=? AND cidade=? AND ultima_vez<?",
                         (fonte, cidade, antes)).rowcount


def carregar(apenas_ativos=True):
    with conexao() as c:
        df = pd.read_sql_query(
            "SELECT i.*, (SELECT preco FROM historico h WHERE h.id=i.id ORDER BY data LIMIT 1) AS preco_inicial "
            "FROM imoveis i" + (" WHERE ativo=1" if apenas_ativos else ""), c)
    df[["quartos", "banheiros", "vagas"]] = df[["quartos", "banheiros", "vagas"]].fillna(0).astype(int)
    df["variacao"] = ((df.preco / df.preco_inicial) - 1).where(df.preco_inicial > 0)
    return df


# ---------- imobiliárias descobertas ----------

def _host(site):
    h = urlparse(site or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def id_imobiliaria(i):
    return hashlib.sha1(f"{_host(i.get('site')) or slug(i['nome'])}|{slug(i['cidade'])}".encode()).hexdigest()[:12]


def salvar_imobiliarias(lista):
    """Grava imobiliárias novas, sem mexer na seleção nem no mapeamento das que já existem."""
    novos = 0
    with conexao() as c:
        for i in lista:
            id_ = id_imobiliaria(i)
            if c.execute("SELECT 1 FROM imobiliarias WHERE id=?", (id_,)).fetchone():
                c.execute("UPDATE imobiliarias SET nome=?, endereco=? WHERE id=?", (i["nome"], i.get("endereco", ""), id_))
                continue
            c.execute("INSERT INTO imobiliarias (id,nome,site,endereco,cidade,uf,origem,selecionada,status) VALUES (?,?,?,?,?,?,?,?,?)",
                      (id_, i["nome"], i.get("site", ""), i.get("endereco", ""), i["cidade"], i.get("uf", ""),
                       i.get("origem", "manual"), 1 if i.get("site") else 0, "novo" if i.get("site") else "sem_site"))
            novos += 1
    return novos


def listar_imobiliarias(cidade=None, so_selecionadas=False):
    cols = ["id", "nome", "site", "endereco", "cidade", "uf", "origem", "selecionada", "status", "perfil", "mapeado_em"]
    q, args = f"SELECT {','.join(cols)} FROM imobiliarias WHERE 1=1", []
    if cidade:
        q += " AND lower(cidade)=lower(?)"
        args.append(cidade)
    if so_selecionadas:
        q += " AND selecionada=1"
    with conexao() as c:
        linhas = c.execute(q + " ORDER BY nome", args).fetchall()
    out = []
    for r in linhas:
        d = dict(zip(cols, r))
        d["perfil"], d["selecionada"] = json.loads(d["perfil"] or "{}"), bool(d["selecionada"])
        out.append(d)
    return out


def gravar_perfil(id_, status, perfil):
    with conexao() as c:
        c.execute("UPDATE imobiliarias SET status=?, perfil=?, mapeado_em=? WHERE id=?",
                  (status, json.dumps(perfil, ensure_ascii=False), dt.datetime.now().isoformat(timespec="seconds"), id_))


def definir_selecao(ids, valor):
    with conexao() as c:
        c.executemany("UPDATE imobiliarias SET selecionada=? WHERE id=?", [(1 if valor else 0, i) for i in ids])


# ---------- buscas salvas, alertas e uso de APIs ----------

def _agora():
    return dt.datetime.now().isoformat(timespec="seconds")


def salvar_busca(nome, cidade, uf, filtros, intervalo_min=None, paginas=2):
    id_ = uuid.uuid4().hex[:10]
    with conexao() as c:
        c.execute("INSERT INTO buscas (id,nome,cidade,uf,filtros,ativa,criada_em,intervalo_min,paginas) VALUES (?,?,?,?,?,1,?,?,?)",
                  (id_, nome, cidade, (uf or "").upper(), json.dumps(filtros or {}, ensure_ascii=False), _agora(),
                   intervalo_min, paginas))
    return id_


def _busca(l):
    cols = ["id", "nome", "cidade", "uf", "filtros", "ativa", "criada_em", "ultima_exec", "ultimo_status",
            "ultimo_resumo", "intervalo_min", "paginas", "baseline"]
    d = dict(zip(cols, l))
    d["filtros"], d["ativa"], d["baseline"] = json.loads(d["filtros"] or "{}"), bool(d["ativa"]), bool(d["baseline"])
    return d


_COLS_BUSCA = "id,nome,cidade,uf,filtros,ativa,criada_em,ultima_exec,ultimo_status,ultimo_resumo,intervalo_min,paginas,baseline"


def listar_buscas(so_ativas=False):
    with conexao() as c:
        linhas = c.execute(f"SELECT {_COLS_BUSCA} FROM buscas" + (" WHERE ativa=1" if so_ativas else "") + " ORDER BY criada_em").fetchall()
    return [_busca(l) for l in linhas]


def obter_busca(id_):
    with conexao() as c:
        l = c.execute(f"SELECT {_COLS_BUSCA} FROM buscas WHERE id=?", (id_,)).fetchone()
    return _busca(l) if l else None


def remover_busca(id_):
    with conexao() as c:
        c.execute("DELETE FROM vistos WHERE busca_id=?", (id_,))
        c.execute("DELETE FROM alertas WHERE busca_id=?", (id_,))
        return c.execute("DELETE FROM buscas WHERE id=?", (id_,)).rowcount


def definir_busca_ativa(id_, valor):
    with conexao() as c:
        c.execute("UPDATE buscas SET ativa=? WHERE id=?", (1 if valor else 0, id_))


def gravar_execucao(id_, status, resumo, baseline=False, quando=None):
    with conexao() as c:
        c.execute("UPDATE buscas SET ultima_exec=?, ultimo_status=?, ultimo_resumo=?, baseline=MAX(baseline, ?) WHERE id=?",
                  (quando or _agora(), status, resumo, 1 if baseline else 0, id_))


def vistos_da_busca(id_):
    with conexao() as c:
        return {i: p for i, p in c.execute("SELECT imovel_id, preco FROM vistos WHERE busca_id=?", (id_,))}


def gravar_visto(busca_id, imovel_id, preco):
    with conexao() as c:
        c.execute("INSERT INTO vistos VALUES (?,?,?) ON CONFLICT(busca_id, imovel_id) DO UPDATE SET preco=excluded.preco",
                  (busca_id, imovel_id, preco))


def registrar_alerta(busca_id, imovel_id, tipo, dados, chave):
    """Grava o alerta. Devolve o id, ou None se este mesmo alerta já existia."""
    with conexao() as c:
        cur = c.execute("INSERT OR IGNORE INTO alertas (busca_id,imovel_id,tipo,chave,dados,criado_em) VALUES (?,?,?,?,?,?)",
                        (busca_id, imovel_id, tipo, chave, json.dumps(dados, ensure_ascii=False), _agora()))
        return cur.lastrowid if cur.rowcount else None


def _alerta(l):
    d = dict(zip(["id", "busca_id", "busca_nome", "imovel_id", "tipo", "dados", "criado_em", "lido", "enviado"], l))
    d["dados"], d["lido"], d["enviado"] = json.loads(d["dados"] or "{}"), bool(d["lido"]), bool(d["enviado"])
    return d


_SEL_ALERTA = ("SELECT a.id, a.busca_id, COALESCE(b.nome,''), a.imovel_id, a.tipo, a.dados, a.criado_em, a.lido, a.enviado "
               "FROM alertas a LEFT JOIN buscas b ON b.id=a.busca_id")


def listar_alertas(so_nao_lidos=False, limite=100):
    with conexao() as c:
        linhas = c.execute(_SEL_ALERTA + (" WHERE a.lido=0" if so_nao_lidos else "") + " ORDER BY a.id DESC LIMIT ?", (limite,)).fetchall()
    return [_alerta(l) for l in linhas]


def contar_nao_lidos():
    with conexao() as c:
        return c.execute("SELECT COUNT(*) FROM alertas WHERE lido=0").fetchone()[0]


def marcar_lidos(ids=None):
    with conexao() as c:
        if ids is None:
            c.execute("UPDATE alertas SET lido=1")
        else:
            c.executemany("UPDATE alertas SET lido=1 WHERE id=?", [(i,) for i in ids])


def pendentes_envio(max_tentativas=5):
    with conexao() as c:
        linhas = c.execute(_SEL_ALERTA + " WHERE a.enviado=0 AND a.tentativas<? ORDER BY a.id", (max_tentativas,)).fetchall()
    return [_alerta(l) for l in linhas]


def marcar_envio(ids, ok):
    with conexao() as c:
        c.executemany("UPDATE alertas SET enviado=1 WHERE id=?" if ok else "UPDATE alertas SET tentativas=tentativas+1 WHERE id=?",
                      [(i,) for i in ids])


def usar_api(api, limite):
    """Conta uma chamada à API no dia de hoje. Devolve False (sem contar) se o limite diário já foi atingido."""
    dia = dt.date.today().isoformat()
    with conexao() as c:
        c.execute("INSERT OR IGNORE INTO uso_api (api,dia,chamadas) VALUES (?,?,0)", (api, dia))
        n = c.execute("SELECT chamadas FROM uso_api WHERE api=? AND dia=?", (api, dia)).fetchone()[0]
        if n >= limite:
            return False
        c.execute("UPDATE uso_api SET chamadas=chamadas+1 WHERE api=? AND dia=?", (api, dia))
        return True


def uso_api_hoje(api):
    with conexao() as c:
        l = c.execute("SELECT chamadas FROM uso_api WHERE api=? AND dia=?", (api, dt.date.today().isoformat())).fetchone()
    return l[0] if l else 0
