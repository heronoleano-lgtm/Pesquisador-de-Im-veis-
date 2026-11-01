import json, os, re, shutil, struct, subprocess, tempfile, unittest
from pathlib import Path

os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()

from buscaimoveis import acesso, coleta  # noqa: E402
from buscaimoveis.web import criar_app  # noqa: E402


class Senha(unittest.TestCase):
    def setUp(self):
        os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()
        os.environ.pop("BUSCAIMOVEIS_SENHA", None)

    def test_senha_escolhida_vale_so_como_digitada(self):
        self.assertFalse(acesso.senha_configurada())
        acesso.definir_senha("MinhaSenha123")
        self.assertTrue(acesso.senha_configurada())
        self.assertTrue(acesso.conferir("MinhaSenha123"))
        self.assertFalse(acesso.conferir("minhasenha123"))
        self.assertFalse(acesso.conferir(""))

    def test_codigo_gerado_aceita_hifen_e_minusculas(self):
        mostrado, guardado = acesso.gerar_codigo()
        self.assertRegex(mostrado, r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
        acesso.definir_senha(guardado)
        for digitado in (mostrado, mostrado.lower(), guardado, " " + mostrado + " "):
            self.assertTrue(acesso.conferir(digitado.strip() if digitado.startswith(" ") else digitado), digitado)
        self.assertFalse(acesso.conferir(mostrado[:-1] + ("A" if mostrado[-1] != "A" else "B")))

    def test_senha_por_variavel_de_ambiente(self):
        os.environ["BUSCAIMOVEIS_SENHA"] = "da-nuvem-123"
        try:
            self.assertTrue(acesso.senha_configurada())
            self.assertTrue(acesso.conferir("da-nuvem-123"))
            self.assertFalse(acesso.conferir("outra"))
        finally:
            os.environ.pop("BUSCAIMOVEIS_SENHA")

    def test_limitador(self):
        l = acesso.Limitador()
        for _ in range(acesso.MAX_FALHAS):
            self.assertEqual(l.segundos_bloqueado("a"), 0)
            l.falhou("a")
        self.assertGreater(l.segundos_bloqueado("a"), 0)
        self.assertEqual(l.segundos_bloqueado("b"), 0)


class AppProtegido(unittest.TestCase):
    def setUp(self):
        os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()
        os.environ.pop("BUSCAIMOVEIS_SENHA", None)
        acesso.definir_senha("SenhaForte99")
        self.c = criar_app(protegido=True).test_client()

    def entrar(self, senha="SenhaForte99"):
        return self.c.post("/entrar", data={"senha": senha})

    def test_bloqueia_sem_login(self):
        r = self.c.get("/")
        self.assertEqual((r.status_code, r.headers["Location"]), (302, "/entrar"))
        self.assertEqual(self.c.get("/api/opcoes").status_code, 401)
        self.assertEqual(self.c.get("/api/exportar.csv").status_code, 401)
        self.assertEqual(self.c.post("/api/buscar", json={}).status_code, 401)

    def test_arquivos_do_app_sao_publicos(self):
        for caminho, tipo in (("/manifest.webmanifest", "application/manifest+json"), ("/sw.js", "text/javascript"),
                              ("/icone-192.png", "image/png"), ("/icone-maskable-512.png", "image/png"),
                              ("/apple-touch-icon.png", "image/png"), ("/icone.svg", "image/svg+xml"), ("/saude", "text/html")):
            r = self.c.get(caminho)
            self.assertEqual(r.status_code, 200, caminho)
            self.assertIn(tipo, r.headers["Content-Type"], caminho)
        self.assertEqual(self.c.get("/sw.js").headers["Service-Worker-Allowed"], "/")
        self.assertEqual(self.c.get("/entrar").status_code, 200)
        self.assertEqual(self.c.get("/index.html").status_code, 302)  # sem login: vai para a tela de entrada
        self.entrar()
        self.assertEqual(self.c.get("/index.html").status_code, 404)  # com login, só o que está na lista é servido

    def test_senha_errada_e_bloqueio(self):
        self.assertEqual(self.entrar("errada").status_code, 401)
        self.assertEqual(self.c.get("/api/opcoes").status_code, 401)
        for _ in range(acesso.MAX_FALHAS - 1):
            self.entrar("errada")
        r = self.entrar("SenhaForte99")  # mesmo certa, está bloqueado
        self.assertEqual(r.status_code, 429)
        self.assertIn("Aguarde", r.get_data(as_text=True))

    def test_login_logout(self):
        r = self.entrar()
        self.assertEqual((r.status_code, r.headers["Location"]), (302, "/"))
        self.assertEqual(self.c.get("/api/opcoes").status_code, 200)
        self.assertEqual(self.c.get("/").status_code, 200)
        self.assertIn("HttpOnly", r.headers["Set-Cookie"])
        self.assertIn("SameSite=Lax", r.headers["Set-Cookie"])
        self.assertEqual(self.c.post("/api/sair").status_code, 200)
        self.assertEqual(self.c.get("/api/opcoes").status_code, 401)

    def test_origem_estranha_e_recusada(self):
        self.entrar()
        r = self.c.post("/api/imobiliarias/selecao", json={"ids": [], "valor": True}, headers={"Origin": "https://site-malicioso.com"})
        self.assertEqual(r.status_code, 403)
        r = self.c.post("/api/imobiliarias/selecao", json={"ids": [], "valor": True}, headers={"Origin": "http://localhost"})
        self.assertEqual(r.status_code, 200)
        r = self.c.post("/api/imobiliarias/selecao", json={"ids": [], "valor": True},
                        headers={"Origin": "https://meu.tailnet.ts.net", "X-Forwarded-Host": "meu.tailnet.ts.net"})
        self.assertEqual(r.status_code, 200)

    def test_cookie_seguro_em_https(self):
        os.environ["BUSCAIMOVEIS_HTTPS"] = "1"
        try:
            c = criar_app(protegido=True).test_client()
            r = c.post("/entrar", data={"senha": "SenhaForte99"})
            self.assertIn("Secure", r.headers["Set-Cookie"])
        finally:
            os.environ.pop("BUSCAIMOVEIS_HTTPS")

    def test_sem_protecao_tudo_abre(self):
        c = criar_app().test_client()
        self.assertEqual(c.get("/api/opcoes").status_code, 200)
        self.assertEqual(c.get("/entrar").status_code, 302)


class EnderecosInternos(unittest.TestCase):
    def test_deteccao(self):
        for u in ("http://127.0.0.1/", "http://192.168.0.1/admin", "http://10.0.0.5/", "http://169.254.169.254/latest/", "http://[::1]/"):
            self.assertTrue(coleta.endereco_interno(u), u)
        self.assertFalse(coleta.endereco_interno("http://8.8.8.8/"))

    def test_coletor_recusa(self):
        class Falso:
            def get(self, *a, **k):
                raise AssertionError("não devia chegar à rede")
        col = coleta.Coletor(atraso=0, cliente=Falso(), bloquear_internos=True)
        with self.assertRaises(coleta.PermissaoNegada):
            col.baixar("http://169.254.169.254/latest/meta-data/")


RAIZ = Path(__file__).resolve().parent.parent
STATIC = RAIZ / "buscaimoveis" / "static"


def tamanho_png(caminho):
    d = caminho.read_bytes()
    assert d[:8] == b"\x89PNG\r\n\x1a\n", caminho
    return struct.unpack(">II", d[16:24])


class PacoteDoApp(unittest.TestCase):
    def test_manifesto_aponta_para_arquivos_reais_do_tamanho_certo(self):
        m = json.loads((STATIC / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual((m["display"], m["start_url"], m["lang"]), ("standalone", "/", "pt-BR"))
        usos = set()
        for ic in m["icons"]:
            arq = STATIC / ic["src"].lstrip("/")
            self.assertTrue(arq.exists(), ic["src"])
            l, a = map(int, ic["sizes"].split("x"))
            self.assertEqual(tamanho_png(arq), (l, a), ic["src"])
            usos.add(ic["purpose"])
        self.assertEqual(usos, {"any", "maskable"})
        self.assertEqual(tamanho_png(STATIC / "apple-touch-icon.png"), (180, 180))

    def test_service_worker_so_guarda_arquivos_que_existem(self):
        sw = (STATIC / "sw.js").read_text(encoding="utf-8")
        fixos = re.search(r"FIXOS = \[(.*?)\]", sw, re.S).group(1)
        for f in re.findall(r'"(/[^"]+)"', fixos):
            self.assertTrue((STATIC / f.lstrip("/")).exists(), f)
        self.assertIn('"/api/imoveis"', sw)
        self.assertNotIn('"/api/buscar"', sw)  # ações nunca vão para o cache

    def test_pagina_principal_liga_manifesto_e_icones(self):
        h = (STATIC / "index.html").read_text(encoding="utf-8")
        for trecho in ('rel="manifest"', 'rel="apple-touch-icon"', "viewport-fit=cover", "/sw.js"):
            self.assertIn(trecho, h)

    def test_arquivos_do_app_entram_no_pacote_instalavel(self):
        t = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"static/*"', t)
        self.assertIn("waitress", t)

    def test_sem_lxml_usa_analisador_do_python(self):
        import importlib, sys
        import buscaimoveis.sopa as m
        env = os.environ.pop("BUSCAIMOVEIS_PARSER", None)
        antigo = sys.modules.get("lxml", False)
        sys.modules["lxml"] = None  # faz "import lxml" falhar
        try:
            importlib.reload(m)
            self.assertEqual(m.PARSER, "html.parser")
            self.assertEqual(m.sopa("<p>oi <b>x</b>").b.text, "x")
        finally:
            if antigo is False:
                sys.modules.pop("lxml", None)
            else:
                sys.modules["lxml"] = antigo
            if env is not None:
                os.environ["BUSCAIMOVEIS_PARSER"] = env
            importlib.reload(m)

    def test_scripts_do_termux(self):
        scripts = sorted((RAIZ / "termux").glob("*.sh"))
        self.assertEqual([x.name for x in scripts], ["boot-termux.sh", "iniciar-termux.sh", "instalar-termux.sh"])
        for x in scripts:
            self.assertTrue(x.read_text(encoding="utf-8").startswith("#!/data/data/com.termux/files/usr/bin/sh"), x.name)
            r = subprocess.run(["sh", "-n", str(x)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, x.name + r.stderr)
        inst = (RAIZ / "termux" / "instalar-termux.sh").read_text(encoding="utf-8")
        self.assertIn("python-numpy python-pandas", inst)
        self.assertIn("termux-api", inst)
        self.assertIn("--no-deps", inst)  # o pandas vem do pkg; o pip não pode tentar compilá-lo

    def test_abrir_usa_o_navegador_do_android_no_termux(self):
        from unittest import mock
        from buscaimoveis import cli
        with mock.patch("shutil.which", return_value="/usr/bin/termux-open-url"), mock.patch("subprocess.run") as run:
            cli._abrir_no_navegador("http://localhost:8000")
        run.assert_called_once_with(["termux-open-url", "http://localhost:8000"], check=False)
        with mock.patch("shutil.which", return_value=None), mock.patch("webbrowser.open") as web:
            cli._abrir_no_navegador("http://localhost:8000")
        web.assert_called_once_with("http://localhost:8000")

    @unittest.skipUnless(shutil.which("node"), "Node.js não encontrado")
    def test_interface_executa_sem_erros(self):
        r = subprocess.run(["node", str(RAIZ / "tests" / "ui_smoke.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
