import json, os, tempfile, unittest
from unittest import mock

os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()

from buscaimoveis import banco, cli, vigia  # noqa: E402
from buscaimoveis.web import criar_app  # noqa: E402


def post(c, url, corpo=None):
    return c.post(url, data=json.dumps(corpo or {}), content_type="application/json")


class AlertasWeb(unittest.TestCase):
    def setUp(self):
        os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()
        os.environ.pop("BUSCAIMOVEIS_SENHA", None)
        self.c = criar_app().test_client()

    def nova(self, **k):
        d = {"nome": "Apto", "cidade_uf": "Curitiba/PR", "filtros": {"finalidade": "venda", "tipos": ["apartamento"], "pmax": 600000}}
        d.update(k)
        return post(self.c, "/api/buscas", d)

    def test_criar_listar_pausar_remover(self):
        r = self.nova()
        self.assertEqual(r.status_code, 200)
        id_ = r.get_json()["id"]
        lista = self.c.get("/api/buscas").get_json()
        self.assertEqual(len(lista), 1)
        self.assertEqual(lista[0]["filtros"]["pmax"], 600000)
        self.assertTrue(lista[0]["proxima"])
        post(self.c, "/api/buscas/ativa", {"id": id_, "valor": False})
        self.assertFalse(self.c.get("/api/buscas").get_json()[0]["ativa"])
        self.assertTrue(post(self.c, "/api/buscas/remover", {"id": id_}).get_json()["removida"])
        self.assertEqual(self.c.get("/api/buscas").get_json(), [])

    def test_validacao(self):
        self.assertEqual(self.nova(nome="").status_code, 400)
        self.assertEqual(self.nova(cidade_uf="").status_code, 400)
        self.assertEqual(self.nova(intervalo_min="abc").status_code, 400)

    def test_filtros_sao_saneados(self):
        self.nova(filtros={"pmax": "<script>", "tipos": ["casa", 5, {"x": 1}], "evil": "x", "quartos": -3, "finalidade": "troca"})
        f = self.c.get("/api/buscas").get_json()[0]["filtros"]
        self.assertEqual((f["pmax"], f["quartos"], f["finalidade"], f["tipos"]), (0.0, 0, "venda", ["casa"]))
        self.assertNotIn("evil", f)

    def test_limite_de_buscas(self):
        for i in range(20):
            self.assertEqual(self.nova(nome=f"b{i}").status_code, 200)
        self.assertEqual(self.nova(nome="extra").status_code, 400)

    def test_alertas_e_lidos(self):
        id_ = self.nova().get_json()["id"]
        banco.registrar_alerta(id_, "x1", "novo", {"preco": 1, "url": "https://a.com"}, "k1")
        banco.registrar_alerta(id_, "x2", "queda", {"preco": 1, "preco_anterior": 2}, "k2")
        r = self.c.get("/api/alertas").get_json()
        self.assertEqual((len(r["itens"]), r["nao_lidos"]), (2, 2))
        self.assertEqual(self.c.get("/api/opcoes").get_json()["nao_lidos"], 2)
        post(self.c, "/api/alertas/lidos", {"ids": [r["itens"][0]["id"]]})
        self.assertEqual(self.c.get("/api/alertas?nao_lidos=1").get_json()["nao_lidos"], 1)
        post(self.c, "/api/alertas/lidos", {})
        self.assertEqual(self.c.get("/api/alertas").get_json()["nao_lidos"], 0)

    def test_teste_de_notificacao(self):
        self.assertEqual(post(self.c, "/api/alertas/teste").status_code, 400)
        cfg = {"alertas": {"notificar": ["ntfy"], "ntfy": {"topico": "t"}}}
        from buscaimoveis.config import carregar_config as real
        def falso(*a, **k):
            c = real(*a, **k)
            c["alertas"].update(cfg["alertas"])
            return c
        with mock.patch("buscaimoveis.web.carregar_config", falso), \
                mock.patch("buscaimoveis.notifica.enviar", return_value={"ntfy": (False, "ntfy indisponível")}):
            r = post(self.c, "/api/alertas/teste").get_json()
        self.assertEqual(r["canais"]["ntfy"], {"ok": False, "erro": "ntfy indisponível"})

    def test_executar_roda_sob_a_trava_e_chama_o_motor(self):
        id_ = self.nova().get_json()["id"]
        chamadas = []

        def falso(b, cfg, col, progresso=print):
            chamadas.append((b["id"], vigia.TRAVA.locked()))
            return {}
        with mock.patch("buscaimoveis.vigia.executar_busca", falso), mock.patch("buscaimoveis.vigia.enviar_pendentes", return_value=0), \
                mock.patch("buscaimoveis.web.novo_coletor"):
            self.assertEqual(post(self.c, "/api/buscas/executar", {"id": id_}).status_code, 200)
            import time
            for _ in range(50):
                if not self.c.get("/api/status").get_json()["rodando"]:
                    break
                time.sleep(0.05)
        self.assertEqual(chamadas, [(id_, True)])
        self.assertEqual(post(self.c, "/api/buscas/executar", {"id": "nao-existe"}).status_code, 400)

    def test_status_do_vigia_sem_agendador(self):
        r = self.c.get("/api/vigia").get_json()
        self.assertFalse(r["ativo"])


class Protegido(unittest.TestCase):
    def test_endpoints_novos_exigem_login(self):
        from buscaimoveis import acesso
        os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()
        os.environ.pop("BUSCAIMOVEIS_SENHA", None)
        acesso.definir_senha("SenhaForte99")
        c = criar_app(protegido=True).test_client()
        for u in ("/api/buscas", "/api/alertas", "/api/vigia"):
            self.assertEqual(c.get(u).status_code, 401, u)
        for u in ("/api/buscas", "/api/buscas/executar", "/api/alertas/teste", "/api/alertas/lidos"):
            self.assertIn(c.post(u, data="{}", content_type="application/json").status_code, (401, 403), u)


class Cli(unittest.TestCase):
    def setUp(self):
        os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()

    def rodar(self, *args):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                cli.main(list(args))
            except SystemExit as e:
                if e.code not in (0, None):
                    buf.write(str(e.code))
        return buf.getvalue()

    def test_ciclo_de_buscas(self):
        out = self.rodar("salvar-busca", "Minha", "--cidade", "Curitiba/PR", "--tipos", "casa", "--pmax", "700000")
        self.assertIn("Busca salva", out)
        b = banco.listar_buscas()[0]
        self.assertEqual((b["cidade"], b["uf"], b["filtros"]["pmax"]), ("Curitiba", "PR", 700000))
        self.assertIn("Minha", self.rodar("buscas"))
        self.rodar("pausar-busca", b["id"])
        self.assertFalse(banco.obter_busca(b["id"])["ativa"])
        self.rodar("retomar-busca", b["id"])
        self.assertTrue(banco.obter_busca(b["id"])["ativa"])
        self.assertIn("Removida", self.rodar("remover-busca", b["id"]))
        self.assertIn("não encontrado", self.rodar("remover-busca", b["id"]))

    def test_alertas_e_marcar_lidos(self):
        id_ = banco.salvar_busca("X", "Curitiba", "PR", {}, None, 2)
        banco.registrar_alerta(id_, "i1", "queda", {"preco": 400000, "preco_anterior": 500000, "bairro": "Batel", "tipo": "casa", "url": "https://a.com/1"}, "k")
        out = self.rodar("alertas", "--marcar-lidos")
        self.assertIn("R$ 500.000 → R$ 400.000", out)
        self.assertEqual(banco.contar_nao_lidos(), 0)

    def test_topico_e_testar_alerta_sem_canal(self):
        self.assertIn("buscaimoveis-", self.rodar("topico"))
        self.assertIn("Nenhum canal", self.rodar("testar-alerta"))

    def test_chave_nao_aparece_na_tela(self):
        with mock.patch("getpass.getpass", return_value="segredo-xyz"):
            out = self.rodar("chave", "MINHA_CHAVE")
        self.assertNotIn("segredo-xyz", out)
        from buscaimoveis import segredos
        self.assertEqual(segredos.valor("MINHA_CHAVE"), "segredo-xyz")
        self.assertIn("MAIÚSCULAS", self.rodar("chave", "minha"))  # recusa antes de pedir o valor

    def test_executar_busca_chama_o_motor(self):
        id_ = banco.salvar_busca("X", "Curitiba", "PR", {}, None, 2)
        with mock.patch("buscaimoveis.vigia.executar_busca") as ex, mock.patch("buscaimoveis.vigia.enviar_pendentes"), \
                mock.patch("buscaimoveis.cli.novo_coletor"):
            self.rodar("executar-busca", id_)
        self.assertEqual(ex.call_count, 1)

    def test_vigiar_uma_vez(self):
        banco.salvar_busca("X", "Curitiba", "PR", {}, None, 2)
        with mock.patch("buscaimoveis.vigia.executar_busca", return_value={}), mock.patch("buscaimoveis.vigia.enviar_pendentes"):
            self.assertIn("1 busca(s) executada(s)", self.rodar("vigiar", "--uma-vez"))


if __name__ == "__main__":
    unittest.main()
