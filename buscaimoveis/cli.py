"""Linha de comando do buscador de imóveis (use: buscaimoveis --help)."""
import argparse
import shutil
import subprocess
import sys
import threading
import webbrowser

import pandas as pd

from . import acesso, analise, banco, coleta, mapeamento, notifica, segredos, vigia
from .config import caminho, carregar_config, novo_coletor


def _abrir_no_navegador(url):
    """No Termux usa o navegador do Android; no computador, o padrão do sistema."""
    if shutil.which("termux-open-url"):
        subprocess.run(["termux-open-url", url], check=False)
    else:
        webbrowser.open(url)


def _busca_e_salva(cidades, fins, tipos, paginas, sites, log=print):
    regs = coleta.buscar(carregar_config(), cidades, fins, tipos, paginas, sites, progresso=log)
    novos, alt = banco.salvar(regs)
    log(f"Concluído: {len(regs)} anúncios lidos, {novos} novos, {alt} com preço alterado.")
    return novos


def _tabela(df, n):
    cols = ["nota", "cidade", "bairro", "tipo", "finalidade", "preco", "area", "pm", "quartos", "vagas", "fontes"]
    d = df[[c for c in cols if c in df]].head(n).copy()
    for c in ("preco", "pm"):
        d[c] = d[c].round(0).astype("Int64")
    print(d.to_string(index=False) if len(d) else "Nenhum imóvel com esses filtros.")


def _args_filtros(p):
    p.add_argument("--finalidade", choices=["venda", "aluguel"], default="venda")
    p.add_argument("--tipos", nargs="*", default=[])
    p.add_argument("--bairro", default="")
    p.add_argument("--pmin", type=float, default=0)
    p.add_argument("--pmax", type=float, default=0)
    p.add_argument("--amin", type=float, default=0)
    p.add_argument("--quartos", type=int, default=0)
    p.add_argument("--banheiros", type=int, default=0)
    p.add_argument("--vagas", type=int, default=0)
    p.add_argument("--condominio-max", type=float, default=0)
    p.add_argument("--obrigatorias", nargs="*", default=[])
    p.add_argument("--desejaveis", nargs="*", default=[])
    p.add_argument("--bairros-preferidos", nargs="*", default=[])
    p.add_argument("--sem-suspeitos", action="store_true")
    p.add_argument("--ordem", default="nota", choices=list(analise.ORDENS))
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--csv", help="salva o resultado completo neste arquivo")


def _filtros_busca(a):
    """Filtros no formato guardado nas buscas salvas."""
    return {"finalidade": a.finalidade, "tipos": a.tipos, "bairro": a.bairro, "pmin": a.pmin, "pmax": a.pmax, "amin": a.amin,
            "quartos": a.quartos, "banheiros": a.banheiros, "vagas": a.vagas, "cmax": a.condominio_max,
            "req": a.obrigatorias, "sem_suspeitos": a.sem_suspeitos}


def _mostrar_alertas(lista):
    if not lista:
        print("Nenhum alerta.")
    for x in lista:
        d = x["dados"]
        if x["tipo"] == "queda":
            q = f"preço caiu {vigia.brl(d.get('preco_anterior', 0))} → {vigia.brl(d['preco'])}"
        else:
            q = f"novo por {vigia.brl(d['preco'])}"
        print(f"{'  ' if x['lido'] else '* '}{x['criado_em'][5:16].replace('T', ' ')}  [{x['busca_nome']}] "
              f"{(d.get('tipo') or '').capitalize()} em {d.get('bairro') or d.get('cidade')}: {q}  {d.get('url') or ''}")


def _filtros_de(a):
    return {"finalidade": a.finalidade, "tipos": a.tipos, "bairro": a.bairro, "pmin": a.pmin, "pmax": a.pmax,
            "amin": a.amin, "quartos": a.quartos, "banheiros": a.banheiros, "vagas": a.vagas}


def _mostrar(a, cidades):
    df = analise.analisar(banco.carregar())
    df = analise.filtrar(df, a.finalidade, cidades, a.tipos, a.bairro, a.pmin, a.pmax, a.amin, a.quartos,
                         a.banheiros, a.vagas, a.condominio_max, a.obrigatorias, a.sem_suspeitos)
    df = analise.ordenar(analise.pontuar(df, a.desejaveis, a.bairros_preferidos), a.ordem)
    _tabela(df, a.top)
    if len(df):
        print(f"\n{len(df)} imóveis. Mediana: R$ {df.pm.median():,.0f}/m²")
    if a.csv:
        df.drop(columns=["feat"], errors="ignore").to_csv(a.csv, index=False, sep=";", encoding="utf-8-sig")
        print("Salvo em", a.csv)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="buscaimoveis", description=__doc__)
    sp = ap.add_subparsers(dest="cmd", required=True)

    d = sp.add_parser("descobrir", help="acha as imobiliárias de uma cidade (OpenStreetMap e, com chave, Google Places)")
    d.add_argument("cidade", help='ex.: "Curitiba/PR"')
    d.add_argument("--google-chave", help="chave da API Google Places (ou variável GOOGLE_PLACES_KEY)")
    d.add_argument("--sem-osm", action="store_true")

    im = sp.add_parser("imobiliarias", help="lista as imobiliárias descobertas e o estado do mapeamento")
    im.add_argument("--cidade")

    ad = sp.add_parser("adicionar-site", help="cadastra uma imobiliária à mão")
    ad.add_argument("nome")
    ad.add_argument("site")
    ad.add_argument("cidade", help='ex.: "Curitiba/PR"')

    mp = sp.add_parser("mapear", help="acha e testa o mecanismo de busca de cada imobiliária selecionada")
    mp.add_argument("--cidade")
    mp.add_argument("--refazer", action="store_true", help="mapeia de novo também as que já estavam ok")

    co = sp.add_parser("consultar", help="consulta as imobiliárias mapeadas aplicando os filtros")
    co.add_argument("--cidade", required=True)
    co.add_argument("--paginas", type=int, default=3)
    _args_filtros(co)

    ex = sp.add_parser("explorar", help="descobre, mapeia e consulta de uma vez")
    ex.add_argument("--cidade", required=True, help='ex.: "Curitiba/PR"')
    ex.add_argument("--paginas", type=int, default=3)
    ex.add_argument("--google-chave")
    _args_filtros(ex)

    b = sp.add_parser("buscar", help="coleta anúncios dos sites ativos em sites.yaml")
    b.add_argument("--cidades", nargs="+", required=True, help='ex.: "Curitiba/PR" "Florianópolis/SC"')
    b.add_argument("--finalidade", nargs="+", default=["venda"], choices=["venda", "aluguel"])
    b.add_argument("--tipos", nargs="*", default=[])
    b.add_argument("--paginas", type=int)
    b.add_argument("--sites", nargs="*")

    i = sp.add_parser("importar", help="importa CSV, JSON ou HTML salvo")
    i.add_argument("arquivo")
    i.add_argument("--cidade", help='obrigatória para HTML, ex.: "Curitiba/PR"')

    ls = sp.add_parser("listar", help="lista e pontua o que já foi coletado")
    ls.add_argument("--cidades", nargs="*", default=[])
    _args_filtros(ls)

    t = sp.add_parser("testar-url", help="mostra o que o programa lê de uma página de resultados")
    t.add_argument("url")
    t.add_argument("--render", action="store_true")

    s = sp.add_parser("servir", help="abre a interface web (computador e celular)")
    s.add_argument("--porta", type=int, default=8000)
    s.add_argument("--celular", action="store_true", help="aceita acesso do celular na mesma rede Wi-Fi")
    s.add_argument("--abrir", action="store_true", help="abre o navegador quando o servidor subir")
    s.add_argument("--sem-vigia", action="store_true", help="não roda as buscas salvas automaticamente")

    sb = sp.add_parser("salvar-busca", help="salva uma busca que roda sozinha e avisa de novidades")
    sb.add_argument("nome")
    sb.add_argument("--cidade", required=True, help='ex.: "Curitiba/PR"')
    sb.add_argument("--intervalo", type=int, help="minutos entre execuções (mínimo 30; padrão: alertas.intervalo_min)")
    sb.add_argument("--paginas", type=int, default=2)
    _args_filtros(sb)
    sp.add_parser("buscas", help="lista as buscas salvas")
    for nome, ajuda in (("remover-busca", "apaga uma busca salva"), ("pausar-busca", "pausa uma busca salva"),
                        ("retomar-busca", "retoma uma busca pausada")):
        sp.add_parser(nome, help=ajuda).add_argument("id")
    eb = sp.add_parser("executar-busca", help="roda agora uma busca salva (ou todas as ativas)")
    eb.add_argument("id", nargs="?")
    al = sp.add_parser("alertas", help="mostra os alertas (imóveis novos e quedas de preço)")
    al.add_argument("--todos", action="store_true", help="inclui os já lidos")
    al.add_argument("--marcar-lidos", action="store_true")
    vg = sp.add_parser("vigiar", help="roda as buscas salvas de tempos em tempos (deixe aberto)")
    vg.add_argument("--uma-vez", action="store_true", help="roda o que estiver na hora e sai (para cron ou agendador)")
    sp.add_parser("testar-alerta", help="envia uma notificação de teste pelos canais de alertas.notificar")
    sp.add_parser("topico", help="gera um tópico aleatório para o ntfy")
    ch = sp.add_parser("chave", help="guarda uma chave de API (digitada sem aparecer na tela)")
    ch.add_argument("nome", help="ex.: GECKOAPI_CHAVE")
    sp.add_parser("apis", help="lista as APIs configuradas, o uso de hoje e se a chave está guardada")
    sp.add_parser("senha", help="define a senha de acesso da interface (usada no celular)")
    sp.add_parser("config", help="mostra onde fica o sites.yaml")
    sp.add_parser("sites", help="lista os sites configurados")
    a = ap.parse_args(argv)

    if a.cmd == "descobrir":
        from . import descoberta
        achadas = descoberta.descobrir(a.cidade, chave=a.google_chave, osm=not a.sem_osm)
        print(f"{len(achadas)} imobiliárias; {banco.salvar_imobiliarias(achadas)} novas na base.")
        for x in achadas:
            print(f"  {x['nome']}  {x['site'] or '(sem site)'}  [{x['origem']}]")
    elif a.cmd == "imobiliarias":
        for x in banco.listar_imobiliarias(a.cidade.split("/")[0] if a.cidade else None):
            print(f"{'[x]' if x['selecionada'] else '[ ]'} {x['status']:9} {x['nome']}  {x['site'] or '(sem site)'}"
                  + (f"  - {x['perfil'].get('detalhe')}" if x["perfil"].get("detalhe") else ""))
    elif a.cmd == "adicionar-site":
        c, uf = coleta.separa_cidade(a.cidade)
        banco.salvar_imobiliarias([{"nome": a.nome, "site": a.site, "cidade": c, "uf": uf.upper(), "origem": "manual"}])
        print("Cadastrada.")
    elif a.cmd == "mapear":
        mapeamento.mapear_selecionadas(novo_coletor(), a.cidade.split("/")[0] if a.cidade else None, a.refazer)
    elif a.cmd == "consultar":
        cid = coleta.separa_cidade(a.cidade)[0]
        mapeamento.consultar_todas(novo_coletor(), _filtros_de(a), cid, a.paginas)
        _mostrar(a, [cid])
    elif a.cmd == "explorar":
        cid = coleta.separa_cidade(a.cidade)[0]
        mapeamento.explorar(novo_coletor(), a.cidade, _filtros_de(a), a.paginas, a.google_chave)
        _mostrar(a, [cid])
    elif a.cmd == "buscar":
        _busca_e_salva(a.cidades, a.finalidade, a.tipos, a.paginas, a.sites)
    elif a.cmd == "importar":
        ctx = {}
        if a.cidade:
            ctx["cidade"], ctx["uf"] = coleta.separa_cidade(a.cidade)
        regs = coleta.importar_arquivo(a.arquivo, ctx)
        print(f"{len(regs)} anúncios válidos. Novos: {banco.salvar(regs)[0]}.")
    elif a.cmd == "listar":
        _mostrar(a, a.cidades)
    elif a.cmd == "testar-url":
        regs, metodo = coleta.extrair(novo_coletor().baixar(a.url, render=a.render), a.url, {"cidade": "teste", "fonte": "teste"})
        print(f"{len(regs)} anúncios lidos pelo método: {metodo}")
        if regs:
            print(pd.DataFrame(regs)[["titulo", "preco", "area", "quartos", "bairro"]].head(8).to_string(index=False))
        else:
            print("Nada reconhecido. Possíveis causas: página montada por JavaScript (tente --render) ou "
                  "layout sem preço/área no mesmo bloco (use 'seletores' no sites.yaml).")
    elif a.cmd == "servir":
        from .web import criar_app, ip_local
        codigo = None
        if a.celular and not acesso.senha_configurada():
            codigo, guardar = acesso.gerar_codigo()
            acesso.definir_senha(guardar)
        protegido = a.celular or acesso.senha_configurada()
        vg = None if a.sem_vigia else vigia.Vigia()
        app = criar_app(protegido, vg)
        if vg:
            vg.iniciar()
            print(f"Vigia ligado: as buscas salvas rodam sozinhas (a cada {carregar_config()['alertas']['intervalo_min']} min, no mínimo {vigia.MINIMO_MIN}).")
        print(f"\nNo computador: http://localhost:{a.porta}")
        if a.celular:
            print(f"No celular (mesmo Wi-Fi): http://{ip_local()}:{a.porta}")
            if codigo:
                print(f"\nCódigo de acesso (digite no celular): {codigo}")
                print("Ele só aparece agora. Para trocar por uma senha sua: buscaimoveis senha")
            else:
                print("Entre com a senha que você definiu (para trocar: buscaimoveis senha).")
        if a.abrir:
            threading.Timer(2.5, _abrir_no_navegador, [f"http://localhost:{a.porta}"]).start()
        try:
            from waitress import serve
            print("(servidor waitress)\n")
            serve(app, host="0.0.0.0" if a.celular else "127.0.0.1", port=a.porta, threads=8)
        except ImportError:
            app.run(host="0.0.0.0" if a.celular else "127.0.0.1", port=a.porta, threaded=True)
    elif a.cmd == "senha":
        import getpass
        s1 = getpass.getpass("Nova senha (mínimo 8 caracteres): ")
        if len(s1) < 8:
            sys.exit("Senha curta demais.")
        if s1 != getpass.getpass("Repita a senha: "):
            sys.exit("As senhas não conferem.")
        acesso.definir_senha(s1)
        print("Senha salva. Vale na próxima vez que você iniciar o servidor.")
    elif a.cmd == "salvar-busca":
        c, uf = coleta.separa_cidade(a.cidade)
        id_ = banco.salvar_busca(a.nome, c, uf, _filtros_busca(a), a.intervalo, a.paginas)
        print(f"Busca salva (id {id_}). Ela roda na próxima vez que o servidor ou o `buscaimoveis vigiar` estiver ligado; "
              "a primeira execução só registra o que já existe.")
    elif a.cmd == "buscas":
        for b in banco.listar_buscas():
            print(f"{b['id']}  {'ativa ' if b['ativa'] else 'pausada'}  {b['nome']}  ({b['cidade']}/{b['uf']})  "
                  f"{b['ultima_exec'] or 'nunca rodou'}  {b['ultimo_resumo'] or ''}")
    elif a.cmd == "remover-busca":
        print("Removida." if banco.remover_busca(a.id) else "Id não encontrado.")
    elif a.cmd in ("pausar-busca", "retomar-busca"):
        if banco.obter_busca(a.id):
            banco.definir_busca_ativa(a.id, a.cmd == "retomar-busca")
            print("Ok.")
        else:
            print("Id não encontrado.")
    elif a.cmd == "executar-busca":
        cfg = carregar_config()
        alvo = [banco.obter_busca(a.id)] if a.id else banco.listar_buscas(so_ativas=True)
        if not alvo or alvo[0] is None:
            sys.exit("Nenhuma busca para rodar. Veja: buscaimoveis buscas")
        with vigia.TRAVA:
            for b in alvo:
                vigia.executar_busca(b, cfg, novo_coletor())
            vigia.enviar_pendentes(cfg)
        _mostrar_alertas(banco.listar_alertas(so_nao_lidos=True, limite=20))
    elif a.cmd == "alertas":
        _mostrar_alertas(banco.listar_alertas(so_nao_lidos=not a.todos, limite=50))
        if a.marcar_lidos:
            banco.marcar_lidos()
            print("Todos marcados como lidos.")
    elif a.cmd == "vigiar":
        v = vigia.Vigia()
        if a.uma_vez:
            print(f"{v.tick()} busca(s) executada(s).")
        else:
            print("Vigiando as buscas salvas. Ctrl+C para parar.")
            v.iniciar()
            try:
                while v.ativo:
                    v._thread.join(1)
            except KeyboardInterrupt:
                v.parar()
    elif a.cmd == "testar-alerta":
        ac = carregar_config()["alertas"]
        if not notifica.configurados(ac):
            sys.exit("Nenhum canal em alertas.notificar. Edite o sites.yaml (buscaimoveis config) e use termux, ntfy ou telegram.")
        for canal, (ok, msg) in notifica.enviar(ac, "Teste do Buscador de imóveis", "Se você viu isto, as notificações funcionam.",
                                                 ac.get("link") or "http://localhost:8000").items():
            print(f"{canal}: {'enviado' if ok else 'FALHOU - ' + msg}")
    elif a.cmd == "topico":
        print(notifica.novo_topico())
        print("Use como alertas.ntfy.topico e assine o mesmo nome no app ntfy. Quem souber o nome consegue ler os avisos: não divulgue.")
    elif a.cmd == "chave":
        import getpass
        if not segredos._NOME.fullmatch(a.nome):
            sys.exit("Use um nome em MAIÚSCULAS, números e _, por exemplo GECKOAPI_CHAVE")
        valor = getpass.getpass(f"Valor de {a.nome} (não aparece na tela): ").strip()
        if not valor:
            sys.exit("Nada digitado.")
        try:
            segredos.guardar(a.nome, valor)
        except ValueError as e:
            sys.exit(str(e))
        print(f"Guardada em {banco.casa() / 'chaves.json'}. No sites.yaml use ${{{a.nome}}}.")
    elif a.cmd == "apis":
        cfg = carregar_config()
        for n, c in cfg["apis"].items():
            falta = segredos.faltando(c)
            print(f"{'ativa  ' if c.get('ativo') is True else 'inativa'} {n}  hoje: {banco.uso_api_hoje(n)}/{c.get('limite_diario') or 30} chamadas"
                  + (f"  FALTA A CHAVE {falta[0]} (buscaimoveis chave {falta[0]})" if falta else ""))
        if not cfg["apis"]:
            print("Nenhuma API configurada. Veja a seção `apis:` do sites.yaml (buscaimoveis config).")
    elif a.cmd == "config":
        print(caminho())
    elif a.cmd == "sites":
        for n, c in carregar_config()["sites"].items():
            print(("ativo   " if c.get("ativo", True) else "inativo ") + n)


if __name__ == "__main__":
    sys.exit(main())
