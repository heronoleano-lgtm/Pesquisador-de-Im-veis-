"""Motor de automação: roda as buscas salvas de tempos em tempos, descobre imóveis novos e quedas de preço
e avisa por notificação. A primeira execução de cada busca só registra o que já existe (não avisa tudo de uma vez)."""
import collections
import datetime as dt
import re
import threading

from . import analise, banco, coleta, mapeamento, notifica
from .config import carregar_config, novo_coletor

TRAVA = threading.Lock()   # uma coleta por vez (a automática e as pedidas pela interface não se cruzam)
MINIMO_MIN = 30            # intervalo mínimo entre coletas de uma mesma busca (educação com os sites)


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def brl(v):
    return "R$ " + f"{v:,.0f}".replace(",", ".")


def casar(df, b):
    """Imóveis da base que atendem à busca salva (cidade e filtros)."""
    if df.empty:
        return df
    f = b["filtros"]
    d = df[df.cidade.str.lower() == b["cidade"].lower()]
    return analise.filtrar(d, f.get("finalidade") or "venda", (), f.get("tipos") or [], f.get("bairro") or "",
                           _num(f.get("pmin")), _num(f.get("pmax")), _num(f.get("amin")), int(_num(f.get("quartos"))),
                           int(_num(f.get("banheiros"))), int(_num(f.get("vagas"))), _num(f.get("cmax")),
                           f.get("req") or [], bool(f.get("sem_suspeitos")))


def _dados(r):
    return {"titulo": r.get("titulo") or r.get("tipo"), "bairro": r.get("bairro"), "cidade": r.get("cidade"),
            "tipo": r.get("tipo"), "finalidade": r.get("finalidade"), "preco": _num(r.get("preco")),
            "area": _num(r.get("area")), "pm": round(_num(r.get("pm"))), "quartos": int(_num(r.get("quartos"))),
            "url": r.get("url") or "", "fonte": r.get("fontes") or r.get("fonte") or ""}


def avaliar(b, df, queda_min=0.03):
    """Compara o que casa com a busca contra o que já foi visto. Grava e devolve os alertas novos:
    [(tipo, imovel_id, dados, chave)]. Preço de referência: só sobe, ou cai quando avisamos a queda."""
    vistos, saida = banco.vistos_da_busca(b["id"]), []
    primeira = not b["baseline"]
    for r in df.to_dict("records"):
        id_, preco = r["id"], _num(r["preco"])
        ant, tipo, atualiza = vistos.get(id_), None, False
        if ant is None:
            atualiza, tipo = True, (None if primeira else "novo")
        elif ant > 0 and preco <= ant * (1 - queda_min):
            atualiza, tipo = True, "queda"
        elif preco > ant + 0.5:
            atualiza = True
        if tipo:
            d = _dados(r)
            if tipo == "queda":
                d["preco_anterior"] = ant
            chave = f"{b['id']}|{id_}|{tipo}|{int(preco)}"
            if banco.registrar_alerta(b["id"], id_, tipo, d, chave):
                saida.append((tipo, id_, d, chave))
        if atualiza:
            banco.gravar_visto(b["id"], id_, preco)
    return saida


def executar_busca(b, cfg=None, col=None, progresso=print):
    """Coleta (imobiliárias mapeadas, sites e APIs) e avalia os alertas de uma busca salva."""
    cfg = cfg or carregar_config()
    f = b["filtros"]
    pag = int(b.get("paginas") or 2)
    queda = _num(cfg["alertas"].get("queda_minima_pct", 3)) / 100
    cidade_uf = f"{b['cidade']}/{b['uf']}" if b["uf"] else b["cidade"]
    col = col or novo_coletor()
    lidos, erro = 0, ""
    try:
        if any(i["status"] == "ok" for i in banco.listar_imobiliarias(b["cidade"], True)):
            lidos += len(mapeamento.consultar_todas(col, dict(f, cidade=b["cidade"]), b["cidade"], pag, progresso))
        regs = coleta.buscar(cfg, [cidade_uf], [f.get("finalidade") or "venda"], list(f.get("tipos") or []), pag, None,
                             progresso, col, f)
        banco.salvar(regs)
        lidos += len(regs)
    except Exception as e:
        erro = f"{type(e).__name__}: {e}"[:200]
    df = analise.analisar(banco.carregar())
    casam = casar(df, b)
    novos = avaliar(b, casam, queda) if not erro else []
    n_novo, n_queda = sum(1 for a in novos if a[0] == "novo"), sum(1 for a in novos if a[0] == "queda")
    ok = not erro and (lidos > 0 or len(casam) > 0)
    resumo = erro or (f"{lidos} lidos · {len(casam)} casam · {n_novo} novos · {n_queda} quedas de preço"
                      + ("" if b["baseline"] or not ok else " (primeira vez: só registrei o que já existe)"))
    banco.gravar_execucao(b["id"], "ok" if ok else ("erro" if erro else "sem_dados"), resumo, baseline=ok)
    progresso(f"[{b['nome']}] {resumo}")
    return {"lidos": lidos, "casam": len(casam), "novos": n_novo, "quedas": n_queda, "erro": erro}


def em_silencio(janela, agora):
    """True se `agora` cai na janela 'HH:MM-HH:MM' (aceita virar a meia-noite)."""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", janela or "")
    if not m:
        return False
    a, z, n = int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4]), agora.hour * 60 + agora.minute
    if a == z:
        return False
    return a <= n < z if a < z else (n >= a or n < z)


def montar_mensagem(nome, alertas, link_padrao):
    """Título, corpo e link de uma notificação que resume os alertas de uma busca."""
    nv = [a for a in alertas if a["tipo"] == "novo"]
    qd = [a for a in alertas if a["tipo"] == "queda"]
    partes = []
    if nv:
        partes.append(f"{len(nv)} novo" + ("s" if len(nv) > 1 else ""))
    if qd:
        partes.append(f"{len(qd)} queda" + ("s" if len(qd) > 1 else "") + " de preço")
    linhas = []
    for a in alertas[:5]:
        d = a["dados"]
        if a["tipo"] == "queda":
            ant = _num(d.get("preco_anterior"))
            pct = round((1 - d["preco"] / ant) * 100) if ant else 0
            linhas.append(f"{d.get('bairro') or d.get('tipo')}: {brl(ant)} → {brl(d['preco'])} (-{pct}%)")
        else:
            area = f" · {d['area']:g} m²" if d.get("area") else ""
            linhas.append(f"{(d.get('tipo') or 'imóvel').capitalize()} · {d.get('bairro') or d.get('cidade')} · {brl(d['preco'])}{area}")
    if len(alertas) > 5:
        linhas.append(f"e mais {len(alertas) - 5}")
    url = alertas[0]["dados"].get("url", "") if len(alertas) == 1 else ""
    link = url if url.startswith(("http://", "https://")) else (link_padrao or "http://localhost:8000")
    return f"{' e '.join(partes)} · {nome or 'Imóveis'}", "\n".join(linhas), link


def enviar_pendentes(cfg, agora=None, cliente=None, progresso=print):
    """Envia os alertas ainda não notificados, uma mensagem por busca. Respeita o horário de silêncio."""
    pend = banco.pendentes_envio()
    if not pend:
        return 0
    ac = cfg["alertas"]
    if not notifica.configurados(ac):
        banco.marcar_envio([p["id"] for p in pend], True)   # só na interface, não há para onde enviar
        return 0
    if em_silencio(ac.get("silencio"), agora or dt.datetime.now()):
        return 0
    por_busca = collections.OrderedDict()
    for p in pend:
        por_busca.setdefault(p["busca_id"], []).append(p)
    enviados = 0
    for bid, lista in por_busca.items():
        titulo, corpo, link = montar_mensagem(lista[0]["busca_nome"], lista, ac.get("link"))
        res = notifica.enviar(ac, titulo, corpo, link, ident=int(bid[:6], 16) % 100000, cliente=cliente)
        ok = any(v[0] for v in res.values())
        banco.marcar_envio([p["id"] for p in lista], ok)
        enviados += len(lista) if ok else 0
        for canal, (o, msg) in res.items():
            if not o:
                progresso(f"Não consegui notificar por {canal}: {msg}")
    return enviados


class Vigia:
    """Agendador: a cada minuto vê quais buscas salvas estão na hora de rodar e as executa."""

    def __init__(self, intervalo_min=None, minimo_min=MINIMO_MIN, relogio=dt.datetime.now, cliente=None, coletor=None):
        self.intervalo_fixo, self.minimo, self.agora = intervalo_min, minimo_min, relogio
        self.cliente, self.coletor = cliente, coletor
        self.log = collections.deque(maxlen=100)
        self._parar, self._thread = threading.Event(), None

    def _registra(self, msg):
        self.log.append(f"{self.agora():%d/%m %H:%M} {msg}")
        print(msg, flush=True)

    def intervalo_de(self, b, cfg):
        base = b.get("intervalo_min") or self.intervalo_fixo or cfg["alertas"].get("intervalo_min") or 120
        return max(self.minimo, _num(base))

    def proxima_de(self, b, cfg):
        if not b.get("ultima_exec"):
            return self.agora()
        return dt.datetime.fromisoformat(b["ultima_exec"]) + dt.timedelta(minutes=self.intervalo_de(b, cfg))

    def devidas(self, cfg=None):
        cfg = cfg or carregar_config()
        return [b for b in banco.listar_buscas(so_ativas=True) if self.proxima_de(b, cfg) <= self.agora()]

    def tick(self):
        """Executa o que estiver na hora e envia as notificações pendentes. Devolve quantas buscas rodaram."""
        cfg = carregar_config()
        rodadas = 0
        with TRAVA:
            for b in self.devidas(cfg):
                if self._parar.is_set():
                    break
                try:
                    executar_busca(b, cfg, self.coletor, self._registra)
                except Exception as e:  # uma busca com defeito não derruba o agendador
                    banco.gravar_execucao(b["id"], "erro", f"{type(e).__name__}: {e}"[:200])
                    self._registra(f"[{b['nome']}] erro inesperado: {type(e).__name__}")
                rodadas += 1
            enviar_pendentes(cfg, self.agora(), self.cliente, self._registra)
        return rodadas

    def _loop(self):
        while not self._parar.is_set():
            try:
                self.tick()
            except Exception as e:
                self._registra(f"erro no agendador: {type(e).__name__}")
            self._parar.wait(60)

    def iniciar(self):
        if self._thread is None or not self._thread.is_alive():
            self._parar.clear()
            self._thread = threading.Thread(target=self._loop, name="vigia", daemon=True)
            self._thread.start()
        return self

    def parar(self):
        self._parar.set()

    @property
    def ativo(self):
        return bool(self._thread and self._thread.is_alive())

    def status(self):
        cfg = carregar_config()
        return {"ativo": self.ativo, "canais": notifica.configurados(cfg["alertas"]),
                "silencio": cfg["alertas"].get("silencio") or "", "log": list(self.log)[-30:],
                "proximas": {b["id"]: self.proxima_de(b, cfg).isoformat(timespec="minutes")
                             for b in banco.listar_buscas(so_ativas=True)}}
