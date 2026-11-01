import datetime as dt, os, tempfile, unittest
from unittest import mock

os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()

from buscaimoveis import analise, banco, coleta, notifica, normaliza as N, vigia  # noqa: E402

FILTROS = {"finalidade": "venda", "tipos": ["apartamento"], "pmax": 900000, "quartos": 2}


def imovel(i, preco, bairro="Batel", quartos=2, tipo="apartamento", cidade="Curitiba", area=80, url=True):
    return N.registro(url=f"https://x.com/{i}" if url else "", id=f"i{i}", cidade=cidade, uf="PR", bairro=bairro, tipo=tipo,
                      finalidade="venda", preco=preco, area=area, quartos=quartos, fonte="s", titulo=f"{tipo} {i}")


class Fakes(unittest.TestCase):
    def setUp(self):
        os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()
        self.id = banco.salvar_busca("Apto Batel", "Curitiba", "PR", FILTROS)
        self.cfg = {"alertas": {"intervalo_min": 60, "queda_minima_pct": 3, "silencio": "", "notificar": [], "link": ""},
                    "sites": {}, "apis": {}, "coleta": {}}

    def busca(self):
        return banco.obter_busca(self.id)

    def rodar(self, imoveis):
        """Simula uma coleta que traz `imoveis` e roda o motor de alertas."""
        with mock.patch.object(coleta, "buscar", return_value=imoveis):
            return vigia.executar_busca(self.busca(), self.cfg, object(), lambda m: None)

    def alertas(self):
        return [(a["tipo"], a["imovel_id"]) for a in sorted(banco.listar_alertas(), key=lambda a: a["id"])]


class Avaliacao(Fakes):
    def test_primeira_vez_so_registra(self):
        r = self.rodar([imovel(1, 800000), imovel(2, 700000)])
        self.assertEqual((r["casam"], r["novos"]), (2, 0))
        self.assertEqual(banco.listar_alertas(), [])
        self.assertTrue(self.busca()["baseline"])
        self.assertIn("primeira vez", self.busca()["ultimo_resumo"])
        self.assertEqual(banco.vistos_da_busca(self.id), {"i1": 800000, "i2": 700000})

    def test_novo_imovel_gera_alerta_uma_unica_vez(self):
        self.rodar([imovel(1, 800000)])
        self.rodar([imovel(1, 800000), imovel(2, 650000, bairro="Água Verde")])
        self.assertEqual(self.alertas(), [("novo", "i2")])
        self.rodar([imovel(1, 800000), imovel(2, 650000)])
        self.assertEqual(len(banco.listar_alertas()), 1)   # não repete
        a = banco.listar_alertas()[0]
        self.assertEqual((a["busca_nome"], a["dados"]["bairro"], a["dados"]["preco"], a["lido"], a["enviado"]),
                         ("Apto Batel", "Água Verde", 650000, False, False))

    def test_so_avisa_o_que_casa_com_os_filtros(self):
        self.rodar([imovel(1, 800000)])
        self.rodar([imovel(1, 800000), imovel(2, 950000), imovel(3, 500000, quartos=1), imovel(4, 500000, tipo="casa"),
                    imovel(5, 500000, cidade="Londrina"), imovel(6, 500000)])
        self.assertEqual(self.alertas(), [("novo", "i6")])

    def test_queda_de_preco_com_limiar(self):
        self.rodar([imovel(1, 800000)])
        self.rodar([imovel(1, 790000)])               # -1,25%: abaixo do limiar de 3%
        self.assertEqual(self.alertas(), [])
        self.rodar([imovel(1, 770000)])               # -3,75% acumulado frente a 800 mil: avisa
        self.assertEqual(self.alertas(), [("queda", "i1")])
        self.assertEqual(banco.listar_alertas()[0]["dados"]["preco_anterior"], 800000)
        self.rodar([imovel(1, 770000)])
        self.assertEqual(len(banco.listar_alertas()), 1)

    def test_subida_atualiza_referencia_e_queda_depois_avisa(self):
        self.rodar([imovel(1, 800000)])
        self.rodar([imovel(1, 850000)])
        self.assertEqual(banco.vistos_da_busca(self.id)["i1"], 850000)
        self.rodar([imovel(1, 800000)])               # caiu 5,9% frente ao último preço visto
        self.assertEqual(self.alertas(), [("queda", "i1")])

    def test_falha_na_primeira_coleta_nao_define_a_base(self):
        r = self.rodar([])
        self.assertFalse(self.busca()["baseline"])
        self.assertEqual(self.busca()["ultimo_status"], "sem_dados")
        self.rodar([imovel(1, 800000)])                # esta é a verdadeira primeira vez
        self.assertEqual(banco.listar_alertas(), [])
        self.assertTrue(self.busca()["baseline"])

    def test_erro_na_coleta_registra_e_nao_alerta(self):
        self.rodar([imovel(1, 800000)])
        with mock.patch.object(coleta, "buscar", side_effect=RuntimeError("rede caiu")):
            r = vigia.executar_busca(self.busca(), self.cfg, object(), lambda m: None)
        self.assertIn("rede caiu", r["erro"])
        self.assertEqual(self.busca()["ultimo_status"], "erro")
        self.assertTrue(self.busca()["baseline"])      # a base anterior continua valendo

    def test_usa_dados_ja_na_base_vindos_de_importacao(self):
        banco.salvar([imovel(1, 800000)])
        self.rodar([])                                 # nada novo coletado, mas há dados na base
        self.assertEqual(self.busca()["ultimo_status"], "ok")
        self.assertTrue(self.busca()["baseline"])


class Mensagens(unittest.TestCase):
    def a(self, tipo, **d):
        base = {"titulo": "x", "bairro": "Batel", "cidade": "Curitiba", "tipo": "apartamento", "preco": 850000, "area": 85, "url": ""}
        return {"tipo": tipo, "dados": {**base, **d}, "busca_nome": "Apto"}

    def test_um_novo_abre_o_anuncio(self):
        t, c, l = vigia.montar_mensagem("Apto", [self.a("novo", url="https://x.com/1")], "http://localhost:8000")
        self.assertEqual(t, "1 novo · Apto")
        self.assertEqual(c, "Apartamento · Batel · R$ 850.000 · 85 m²")
        self.assertEqual(l, "https://x.com/1")

    def test_varios_resumem_e_abrem_o_app(self):
        lista = [self.a("novo") for _ in range(6)] + [self.a("queda", preco_anterior=1000000, preco=900000)]
        t, c, l = vigia.montar_mensagem("Apto", lista, "")
        self.assertEqual(t, "6 novos e 1 queda de preço · Apto")
        self.assertEqual(len(c.splitlines()), 6)
        self.assertTrue(c.endswith("e mais 2"))
        self.assertEqual(l, "http://localhost:8000")

    def test_queda_mostra_percentual(self):
        _, c, _ = vigia.montar_mensagem("Apto", [self.a("queda", preco_anterior=1000000, preco=920000)], "")
        self.assertEqual(c, "Batel: R$ 1.000.000 → R$ 920.000 (-8%)")

    def test_silencio(self):
        h = lambda s: dt.datetime(2026, 11, 1, *map(int, s.split(":")))
        for hora, esperado in (("23:00", True), ("03:30", True), ("07:00", False), ("12:00", False), ("22:00", True), ("21:59", False)):
            self.assertEqual(vigia.em_silencio("22:00-07:00", h(hora)), esperado, hora)
        self.assertTrue(vigia.em_silencio("13:00-14:00", h("13:30")))
        self.assertFalse(vigia.em_silencio("", h("03:00")))
        self.assertFalse(vigia.em_silencio("lixo", h("03:00")))


class Envio(Fakes):
    def setUp(self):
        super().setUp()
        self.rodar([imovel(1, 800000)])
        self.rodar([imovel(1, 800000), imovel(2, 650000), imovel(3, 640000)])
        self.cfg["alertas"]["notificar"] = ["ntfy"]
        self.cfg["alertas"]["ntfy"] = {"topico": "meu-topico-longo"}

    class Cli:
        def __init__(self, status=200):
            self.chamadas, self.status = [], status

        def post(self, url, json=None, headers=None, timeout=None):
            self.chamadas.append((url, json, headers))
            return type("R", (), {"status_code": self.status})()

    def test_ntfy_json_no_formato_da_documentacao(self):
        cli = self.Cli()
        self.assertEqual(vigia.enviar_pendentes(self.cfg, dt.datetime(2026, 11, 1, 12), cli, lambda m: None), 2)
        (url, corpo, cab), = cli.chamadas        # uma única mensagem resumindo as duas
        self.assertEqual(url, "https://ntfy.sh/")
        self.assertEqual((corpo["topic"], corpo["title"]), ("meu-topico-longo", "2 novos · Apto Batel"))
        self.assertEqual(len(corpo["message"].splitlines()), 2)
        self.assertEqual(corpo["click"], "http://localhost:8000")
        self.assertEqual(banco.pendentes_envio(), [])

    def test_horario_de_silencio_guarda_para_depois(self):
        self.cfg["alertas"]["silencio"] = "22:00-07:00"
        cli = self.Cli()
        self.assertEqual(vigia.enviar_pendentes(self.cfg, dt.datetime(2026, 11, 1, 23, 0), cli, lambda m: None), 0)
        self.assertEqual(cli.chamadas, [])
        self.assertEqual(len(banco.pendentes_envio()), 2)
        self.assertEqual(vigia.enviar_pendentes(self.cfg, dt.datetime(2026, 11, 2, 7, 5), cli, lambda m: None), 2)

    def test_falha_tenta_de_novo_ate_cansar(self):
        msgs, cli = [], self.Cli(status=500)
        for _ in range(7):
            vigia.enviar_pendentes(self.cfg, dt.datetime(2026, 11, 1, 12), cli, msgs.append)
        self.assertEqual(len(cli.chamadas), 5)           # 5 tentativas e desiste
        self.assertTrue(any("ntfy recusou" in m for m in msgs))
        self.assertEqual(banco.pendentes_envio(), [])
        self.assertEqual(len(banco.listar_alertas()), 2)  # continuam visíveis no app

    def test_sem_canal_so_fica_no_app(self):
        self.cfg["alertas"]["notificar"] = []
        self.assertEqual(vigia.enviar_pendentes(self.cfg, dt.datetime(2026, 11, 1, 12), None, lambda m: None), 0)
        self.assertEqual(banco.pendentes_envio(), [])

    def test_termux_chama_o_comando_sem_shell(self):
        self.cfg["alertas"]["notificar"] = ["termux"]
        with mock.patch("shutil.which", return_value="/usr/bin/termux-notification"), \
                mock.patch("subprocess.run", return_value=type("R", (), {"returncode": 0})()) as run:
            vigia.enviar_pendentes(self.cfg, dt.datetime(2026, 11, 1, 12), None, lambda m: None)
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[0], "/usr/bin/termux-notification")
        self.assertEqual(cmd[cmd.index("--title") + 1], "2 novos · Apto Batel")
        self.assertIn("termux-open-url", cmd[cmd.index("--action") + 1])
        self.assertNotIn("shell", run.call_args[1])

    def test_termux_sem_o_app_explica_o_que_fazer(self):
        with mock.patch("shutil.which", return_value=None):
            r = notifica.enviar({"notificar": ["termux"]}, "t", "c")
        self.assertFalse(r["termux"][0])
        self.assertIn("termux-api", r["termux"][1])

    def test_telegram_e_nao_vaza_token(self):
        cfg = {"notificar": ["telegram"], "telegram": {"token": "123:SEGREDO", "chat_id": 42}}
        cli = self.Cli()
        self.assertTrue(notifica.enviar(cfg, "T", "C", "http://l", cliente=cli)["telegram"][0])
        self.assertEqual(cli.chamadas[0][0], "https://api.telegram.org/bot123:SEGREDO/sendMessage")
        self.assertEqual(cli.chamadas[0][1], {"chat_id": "42", "text": "T\nC\nhttp://l"})
        r = notifica.enviar(cfg, "T", "C", cliente=self.Cli(status=401))
        self.assertFalse(r["telegram"][0])
        self.assertNotIn("SEGREDO", r["telegram"][1])

    def test_ntfy_sem_topico(self):
        r = notifica.enviar({"notificar": ["ntfy"], "ntfy": {}}, "t", "c", cliente=self.Cli())
        self.assertIn("topico", r["ntfy"][1])

    def test_topico_aleatorio(self):
        a, b = notifica.novo_topico(), notifica.novo_topico()
        self.assertNotEqual(a, b)
        self.assertRegex(a, r"^buscaimoveis-[a-z0-9]{16}$")


class Agendador(Fakes):
    def test_so_roda_o_que_esta_na_hora(self):
        v = vigia.Vigia(minimo_min=0, relogio=lambda: dt.datetime(2026, 11, 1, 12, 0))
        with mock.patch.object(vigia, "carregar_config", return_value=self.cfg), \
                mock.patch.object(vigia, "executar_busca", return_value={}) as ex, \
                mock.patch.object(vigia, "enviar_pendentes"):
            self.assertEqual(v.tick(), 1)                    # nunca rodou: roda já
            banco.gravar_execucao(self.id, "ok", "", quando="2026-11-01T11:30:00")
            self.assertEqual(v.tick(), 0)                    # 30 min < 60 min
            banco.gravar_execucao(self.id, "ok", "", quando="2026-11-01T10:59:00")
            self.assertEqual(v.tick(), 1)                    # 61 min
        self.assertEqual(ex.call_count, 2)

    def test_intervalo_minimo_e_por_busca(self):
        v = vigia.Vigia(relogio=lambda: dt.datetime(2026, 11, 1, 12, 0))
        self.assertEqual(v.intervalo_de({"intervalo_min": 5}, self.cfg), 30)      # nunca abaixo de 30 min
        self.assertEqual(v.intervalo_de({"intervalo_min": 240}, self.cfg), 240)
        self.assertEqual(v.intervalo_de({}, self.cfg), 60)

    def test_busca_pausada_nao_roda(self):
        banco.definir_busca_ativa(self.id, False)
        v = vigia.Vigia(minimo_min=0)
        with mock.patch.object(vigia, "carregar_config", return_value=self.cfg):
            self.assertEqual(v.devidas(), [])

    def test_erro_em_uma_busca_nao_derruba_as_outras(self):
        outra = banco.salvar_busca("Outra", "Recife", "PE", {"finalidade": "venda"})
        v = vigia.Vigia(minimo_min=0)
        def falha(b, *a, **k):
            if b["id"] == self.id:
                raise RuntimeError("quebrou")
            return {}
        with mock.patch.object(vigia, "carregar_config", return_value=self.cfg), \
                mock.patch.object(vigia, "executar_busca", side_effect=falha) as ex, mock.patch.object(vigia, "enviar_pendentes"):
            self.assertEqual(v.tick(), 2)
        self.assertEqual(ex.call_count, 2)
        self.assertEqual(banco.obter_busca(self.id)["ultimo_status"], "erro")

    def test_thread_inicia_e_para(self):
        v = vigia.Vigia(minimo_min=0)
        with mock.patch.object(v, "tick") as t:
            v.iniciar()
            for _ in range(50):
                if t.called:
                    break
                import time; time.sleep(0.02)
            self.assertTrue(v.ativo and t.called)
            v.parar()
        self.assertTrue(v._parar.is_set())


class Banco(Fakes):
    def test_buscas_e_remocao_apaga_alertas(self):
        self.rodar([imovel(1, 800000)]); self.rodar([imovel(1, 800000), imovel(2, 600000)])
        self.assertEqual(len(banco.listar_buscas()), 1)
        self.assertEqual(banco.contar_nao_lidos(), 1)
        banco.marcar_lidos([banco.listar_alertas()[0]["id"]])
        self.assertEqual(banco.contar_nao_lidos(), 0)
        self.assertEqual(banco.remover_busca(self.id), 1)
        self.assertEqual((banco.listar_alertas(), banco.vistos_da_busca(self.id), banco.listar_buscas()), ([], {}, []))

    def test_marcar_todos_como_lidos(self):
        self.rodar([imovel(1, 800000)]); self.rodar([imovel(1, 800000), imovel(2, 600000), imovel(3, 590000)])
        self.assertEqual(banco.contar_nao_lidos(), 2)
        banco.marcar_lidos()
        self.assertEqual(banco.contar_nao_lidos(), 0)


if __name__ == "__main__":
    unittest.main()
