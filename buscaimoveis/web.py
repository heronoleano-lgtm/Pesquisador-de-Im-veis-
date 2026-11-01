"""Interface web (Flask): funciona no computador e, pela rede Wi-Fi, no celular."""
import json
import os
import socket
import tempfile
import threading
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, redirect, request, send_from_directory, session

from . import acesso, analise, banco, coleta, descoberta, mapeamento, notifica, vigia as vigia_mod
from .cli import _busca_e_salva
from .config import carregar_config, novo_coletor
from .normaliza import TIPOS

STATIC = Path(__file__).parent / "static"
PUBLICAS = {"/entrar", "/saude", "/sw.js", "/manifest.webmanifest", "/icone.svg", "/icone-192.png",
            "/icone-512.png", "/icone-maskable-512.png", "/apple-touch-icon.png"}
TIPOS_ARQ = {".webmanifest": "application/manifest+json", ".svg": "image/svg+xml", ".png": "image/png",
             ".js": "text/javascript; charset=utf-8"}

PAGINA_ENTRAR = """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#1D5A57"><link rel="icon" href="/icone.svg"><link rel="manifest" href="/manifest.webmanifest">
<title>Entrar</title><style>
:root{--bg:#F1F3EF;--sf:#FBFCFA;--ink:#17262B;--mut:#5B6B6E;--ln:#D6DCD6;--ac:#1D5A57;--acx:#fff;--bad:#A8432E;color-scheme:light}
@media(prefers-color-scheme:dark){:root{--bg:#101A1D;--sf:#17252A;--ink:#E6ECE9;--mut:#93A5A6;--ln:#2A3C41;--ac:#5FB8B1;--acx:#0E1A1C;--bad:#E08A72;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif;padding:16px}
main{width:100%;max-width:360px;background:var(--sf);border:1px solid var(--ln);border-radius:12px;padding:24px}
img{width:56px;height:56px;border-radius:14px}h1{font-size:22px;margin:12px 0 4px}p{margin:0 0 16px;color:var(--mut);font-size:14px}
label{display:block;font-weight:600;font-size:14px;margin-bottom:4px}
input{width:100%;font:inherit;padding:12px;border:1px solid var(--ln);border-radius:8px;background:var(--bg);color:var(--ink)}
button{width:100%;margin-top:14px;font:inherit;font-weight:600;padding:12px;border:0;border-radius:8px;background:var(--ac);color:var(--acx)}
.erro{color:var(--bad);margin:10px 0 0;font-size:14px}:focus-visible{outline:2px solid var(--ac);outline-offset:2px}
</style></head><body><main><img src="/icone-192.png" alt=""><h1>Buscador de imóveis</h1><p>Digite o código de acesso.</p>
<form method="post" action="/entrar"><label for="s">Código ou senha</label>
<input id="s" name="senha" type="password" autocomplete="current-password" autocapitalize="none" required autofocus>
<button type="submit">Entrar</button>__ERRO__</form></main></body></html>"""


def ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "IP-DO-COMPUTADOR"


def _lista(v):
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _base():
    return analise.analisar(banco.carregar())


def _mesmo_host(origem):
    h = urlparse(origem).hostname or ""
    nome = lambda hp: (urlparse("//" + hp.strip()).hostname or "").lower()   # entende também [::1]:8000
    aceitos = {nome(request.host or "")}
    fwd = request.headers.get("X-Forwarded-Host")
    if fwd:
        aceitos.add(nome(fwd.split(",")[0]))
    return h.lower() in aceitos


def criar_app(protegido=False, vigia=None):
    """protegido=True exige o código de acesso (use sempre que outros aparelhos puderem abrir a interface)."""
    app = Flask(__name__, static_folder=None)
    app.secret_key = acesso.segredo_da_sessao()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_SECURE=os.environ.get("BUSCAIMOVEIS_HTTPS") == "1",
                      PERMANENT_SESSION_LIFETIME=timedelta(days=30))
    if os.environ.get("BUSCAIMOVEIS_PROXY") == "1":  # atrás de um proxy HTTPS (túnel, nuvem)
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    estado = {"rodando": False, "log": []}
    trava = threading.Lock()
    limitador = acesso.Limitador()

    @app.before_request
    def proteger():
        if request.method in ("POST", "PUT", "DELETE") and request.headers.get("Origin") \
                and not _mesmo_host(request.headers["Origin"]):
            return jsonify(erro="Origem não permitida."), 403
        if not protegido or request.path in PUBLICAS or session.get("ok"):
            return None
        if request.path.startswith("/api/"):
            return jsonify(erro="Entre com o código de acesso."), 401
        return redirect("/entrar")

    @app.after_request
    def cabecalhos(r):
        r.headers.setdefault("X-Content-Type-Options", "nosniff")
        r.headers.setdefault("X-Frame-Options", "DENY")
        r.headers.setdefault("Referrer-Policy", "no-referrer")
        return r

    @app.get("/saude")
    def saude():
        return "ok"

    @app.route("/entrar", methods=["GET", "POST"])
    def entrar():
        if not protegido or session.get("ok"):
            return redirect("/")
        if request.method == "GET":
            return PAGINA_ENTRAR.replace("__ERRO__", "")
        quem = request.remote_addr or "?"
        espera = limitador.segundos_bloqueado(quem)
        if espera:
            msg = f'<p class="erro" role="alert">Muitas tentativas. Aguarde {espera // 60 + 1} min.</p>'
            return PAGINA_ENTRAR.replace("__ERRO__", msg), 429
        if acesso.conferir(request.form.get("senha", "")):
            limitador.acertou(quem)
            session.clear()
            session.permanent, session["ok"] = True, True
            return redirect("/")
        limitador.falhou(quem)
        return PAGINA_ENTRAR.replace("__ERRO__", '<p class="erro" role="alert">Código incorreto.</p>'), 401

    @app.post("/api/sair")
    def sair():
        session.clear()
        return jsonify(ok=True)

    def rodar(fn):
        """Executa uma tarefa longa em segundo plano, com o andamento visível em /api/status."""
        with trava:
            if estado["rodando"]:
                return jsonify(erro="Já existe uma tarefa em andamento."), 409
            estado.update(rodando=True, log=[])

        def tarefa():
            try:
                if vigia_mod.TRAVA.locked():
                    estado["log"].append("Aguardando a coleta automática terminar…")
                with vigia_mod.TRAVA:
                    fn(estado["log"].append)
            except Exception as e:  # mostra o erro na tela em vez de travar
                estado["log"].append(f"Erro: {e}")
            finally:
                estado["rodando"] = False
        threading.Thread(target=tarefa, daemon=True).start()
        return jsonify(ok=True)

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/<path:arq>")
    def estatico(arq):
        if "/" + arq not in PUBLICAS:
            return ("", 404)
        r = send_from_directory(STATIC, arq)
        r.headers["Content-Type"] = TIPOS_ARQ.get(Path(arq).suffix, r.headers["Content-Type"])
        if arq == "sw.js":
            r.headers["Cache-Control"] = "no-cache"
            r.headers["Service-Worker-Allowed"] = "/"
        return r

    @app.get("/api/opcoes")
    def opcoes():
        df = _base()
        return jsonify(cidades=sorted(set(df.cidade)) if len(df) else [],
                       tipos=sorted(set(TIPOS) | (set(df.tipo) if len(df) else set())),
                       caracteristicas=sorted({f for l in df.feat for f in l}) if len(df) else [],
                       sites=[{"nome": n, "ativo": c.get("ativo", True)} for n, c in carregar_config()["sites"].items()],
                       total=len(df), nao_lidos=banco.contar_nao_lidos())

    @app.get("/api/imoveis")
    def imoveis():
        q, n = request.args, lambda k: float(request.args.get(k) or 0)
        df = analise.filtrar(_base(), q.get("fin") or None, _lista(q.get("cidades")), _lista(q.get("tipos")),
                             q.get("bairro", ""), n("pmin"), n("pmax"), n("amin"), int(n("q")), int(n("b")),
                             int(n("v")), n("cmax"), _lista(q.get("req")), q.get("limpo") == "1", _lista(q.get("ids")))
        pesos = (n("w1"), n("w2"), n("w3")) if q.get("w1") else (3, 2, 1)
        df = analise.ordenar(analise.pontuar(df, _lista(q.get("des")), _lista(q.get("bp")), pesos), q.get("ordem", "nota"))
        out = df.head(int(q.get("limite") or 60)).drop(columns=["caracteristicas"], errors="ignore")
        return jsonify(total=len(df), mediana_pm=None if df.empty else round(float(df.pm.median())),
                       itens=json.loads(out.to_json(orient="records", force_ascii=False)))

    @app.post("/api/buscar")
    def buscar():
        d = request.get_json(force=True) or {}
        return rodar(lambda log: _busca_e_salva(d.get("cidades") or [], d.get("finalidades") or ["venda"],
                                                d.get("tipos") or [], int(d.get("paginas") or 3), d.get("sites") or None, log=log))

    @app.get("/api/status")
    def status():
        return jsonify(rodando=estado["rodando"], log=estado["log"][-40:])

    # ---------- imobiliárias: descobrir, mapear, consultar ----------

    @app.get("/api/imobiliarias")
    def imobiliarias():
        return jsonify(banco.listar_imobiliarias(request.args.get("cidade") or None))

    @app.post("/api/imobiliarias/descobrir")
    def imob_descobrir():
        cidade = (request.get_json(force=True) or {}).get("cidade", "").strip()
        if not cidade:
            return jsonify(erro="Informe a cidade, ex.: Curitiba/PR."), 400

        def tarefa(log):
            achadas = descoberta.descobrir(cidade, progresso=log)
            log(f"{len(achadas)} imobiliárias encontradas; {banco.salvar_imobiliarias(achadas)} novas.")
        return rodar(tarefa)

    @app.post("/api/imobiliarias/adicionar")
    def imob_adicionar():
        d = request.get_json(force=True) or {}
        cidade, uf = coleta.separa_cidade(d.get("cidade", ""))
        site = descoberta.normaliza_site(d.get("site"))
        if not (d.get("nome") and site and cidade):
            return jsonify(erro="Informe nome, site válido e cidade (ex.: Curitiba/PR)."), 400
        banco.salvar_imobiliarias([{"nome": d["nome"], "site": site, "cidade": cidade, "uf": uf.upper(), "origem": "manual"}])
        return jsonify(ok=True)

    @app.post("/api/imobiliarias/selecao")
    def imob_selecao():
        d = request.get_json(force=True) or {}
        banco.definir_selecao(d.get("ids") or [], bool(d.get("valor")))
        return jsonify(ok=True)

    @app.post("/api/imobiliarias/mapear")
    def imob_mapear():
        cidade = (request.get_json(force=True) or {}).get("cidade") or None
        return rodar(lambda log: mapeamento.mapear_selecionadas(novo_coletor(True), cidade, True, log))

    @app.post("/api/imobiliarias/consultar")
    def imob_consultar():
        d = request.get_json(force=True) or {}
        cidade = (d.get("cidade") or "").split("/")[0].strip() or None
        return rodar(lambda log: mapeamento.consultar_todas(novo_coletor(True), d, cidade, int(d.get("paginas") or 3), log))

    @app.post("/api/imobiliarias/explorar")
    def imob_explorar():
        d = request.get_json(force=True) or {}
        if not d.get("cidade_uf"):
            return jsonify(erro="Informe a cidade, ex.: Curitiba/PR."), 400
        return rodar(lambda log: mapeamento.explorar(novo_coletor(True), d["cidade_uf"], d, int(d.get("paginas") or 3), progresso=log))

    # ---------- buscas salvas e alertas ----------

    def filtros_ok(d):
        """Só aceita os campos e tipos esperados (os filtros ficam gravados e são usados depois, sem a tela)."""
        d = d if isinstance(d, dict) else {}
        num = lambda k: max(0.0, float(d.get(k) or 0)) if str(d.get(k) or 0).replace(".", "", 1).isdigit() else 0.0
        lista = lambda k: [str(x)[:60] for x in (d.get(k) or []) if isinstance(x, str)][:30]
        return {"finalidade": "aluguel" if d.get("finalidade") == "aluguel" else "venda", "tipos": lista("tipos"),
                "bairro": str(d.get("bairro") or "")[:80], "pmin": num("pmin"), "pmax": num("pmax"), "amin": num("amin"),
                "cmax": num("cmax"), "quartos": int(num("quartos")), "banheiros": int(num("banheiros")),
                "vagas": int(num("vagas")), "req": lista("req"), "sem_suspeitos": bool(d.get("sem_suspeitos"))}

    @app.get("/api/buscas")
    def buscas_lista():
        cfg, v = carregar_config(), vigia or vigia_mod.Vigia()
        lista = banco.listar_buscas()
        for b in lista:
            b["proxima"] = v.proxima_de(b, cfg).isoformat(timespec="minutes") if b["ativa"] else ""
        return jsonify(lista)

    @app.post("/api/buscas")
    def buscas_criar():
        d = request.get_json(force=True) or {}
        nome, cidade, uf = str(d.get("nome") or "").strip()[:80], *coleta.separa_cidade(str(d.get("cidade_uf") or ""))
        if not nome or not cidade:
            return jsonify(erro="Informe o nome da busca e a cidade (ex.: Curitiba/PR)."), 400
        if len(banco.listar_buscas()) >= 20:
            return jsonify(erro="Limite de 20 buscas salvas: exclua alguma antes."), 400
        try:
            intervalo = int(d["intervalo_min"]) if d.get("intervalo_min") else None
            paginas = min(10, max(1, int(d.get("paginas") or 2)))
        except (TypeError, ValueError):
            return jsonify(erro="Intervalo e páginas precisam ser números."), 400
        return jsonify(id=banco.salvar_busca(nome, cidade, uf, filtros_ok(d.get("filtros")), intervalo, paginas))

    @app.post("/api/buscas/ativa")
    def buscas_ativa():
        d = request.get_json(force=True) or {}
        banco.definir_busca_ativa(str(d.get("id") or ""), bool(d.get("valor")))
        return jsonify(ok=True)

    @app.post("/api/buscas/remover")
    def buscas_remover():
        return jsonify(removida=bool(banco.remover_busca(str((request.get_json(force=True) or {}).get("id") or ""))))

    @app.post("/api/buscas/executar")
    def buscas_executar():
        id_ = str((request.get_json(force=True) or {}).get("id") or "")
        alvo = [banco.obter_busca(id_)] if id_ else banco.listar_buscas(so_ativas=True)
        alvo = [b for b in alvo if b]
        if not alvo:
            return jsonify(erro="Nenhuma busca para rodar."), 400

        def tarefa(log):
            cfg = carregar_config()
            for b in alvo:
                vigia_mod.executar_busca(b, cfg, novo_coletor(True), log)
            vigia_mod.enviar_pendentes(cfg, progresso=log)
        return rodar(tarefa)

    @app.get("/api/alertas")
    def alertas_lista():
        itens = banco.listar_alertas(request.args.get("nao_lidos") == "1", min(200, int(request.args.get("limite") or 50)))
        return jsonify(itens=itens, nao_lidos=banco.contar_nao_lidos())

    @app.post("/api/alertas/lidos")
    def alertas_lidos():
        ids = (request.get_json(force=True) or {}).get("ids")
        banco.marcar_lidos([int(i) for i in ids] if isinstance(ids, list) else None)
        return jsonify(nao_lidos=banco.contar_nao_lidos())

    @app.post("/api/alertas/teste")
    def alertas_teste():
        ac = carregar_config()["alertas"]
        if not notifica.configurados(ac):
            return jsonify(erro="Nenhum canal configurado: edite alertas.notificar no sites.yaml (termux, ntfy ou telegram)."), 400
        res = notifica.enviar(ac, "Teste do Buscador de imóveis", "Se você viu isto, as notificações funcionam.",
                              ac.get("link") or request.host_url)
        return jsonify(canais={c: {"ok": ok, "erro": msg} for c, (ok, msg) in res.items()})

    @app.get("/api/vigia")
    def vigia_status():
        if vigia:
            return jsonify(vigia.status())
        ac = carregar_config()["alertas"]
        return jsonify(ativo=False, canais=notifica.configurados(ac), silencio=ac.get("silencio") or "", log=[], proximas={})

    # ---------- importar / exportar ----------

    @app.post("/api/importar")
    def importar():
        d = request.get_json(force=True) or {}
        texto = (d.get("texto") or "").strip()
        if not texto:
            return jsonify(erro="Cole o conteúdo do arquivo."), 400
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / ("a.json" if texto[0] in "[{" else "a.csv")
            p.write_text(texto, encoding="utf-8")
            try:
                regs = coleta.importar_arquivo(p, {})
            except Exception as e:
                return jsonify(erro=f"Não consegui ler: {e}"), 400
        return jsonify(lidos=len(regs), novos=banco.salvar(regs)[0])

    @app.get("/api/exportar.csv")
    def exportar():
        df = analise.pontuar(_base()).drop(columns=["feat"], errors="ignore")
        return Response(df.to_csv(index=False, sep=";"), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=imoveis.csv"})

    return app
