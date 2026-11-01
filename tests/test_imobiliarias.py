import os, tempfile, time, unittest
from unittest import mock
from urllib.parse import urlencode

os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()

from buscaimoveis import banco, coleta, descoberta, mapeamento  # noqa: E402


class Resp:
    def __init__(s, txt="", js=None, status=200):
        s.text, s._js, s.status_code = txt, js, status

    def json(s):
        return s._js

    def raise_for_status(s):
        if s.status_code >= 400:
            raise RuntimeError(s.status_code)


class Rede:
    """Cliente HTTP falso: devolve a página cuja chave for a mais longa contida na URL pedida."""
    def __init__(s, rotas):
        s.rotas, s.pedidos = rotas, []

    def _resp(s, url):
        s.pedidos.append(url)
        if url.endswith("/robots.txt"):
            return Resp("User-agent: *\nAllow: /")
        for k in sorted(s.rotas, key=len, reverse=True):
            if k in url:
                v = s.rotas[k]
                return Resp(js=v) if isinstance(v, (dict, list)) else Resp(v)
        return Resp("<html></html>")

    def get(s, url, params=None, **kw):
        return s._resp(url + (("&" if "?" in url else "?") + urlencode(params) if params else ""))

    def post(s, url, data=None, json=None, **kw):
        return s._resp(url)


FORM = """<html><body>
<form action="/newsletter" method="post"><input name="email" type="email"><button>Assinar</button></form>
<form action="/imoveis" method="get"><input type="hidden" name="origem" value="home">
<select name="negocio"><option value="comprar">Comprar</option><option value="alugar">Alugar</option></select>
<select name="tipo_imovel"><option value="">Todos</option><option value="apartamento">Apartamentos</option><option value="casa">Casas</option></select>
<select name="cidade"><option value="">Escolha</option><option value="curitiba">Curitiba</option><option value="sjp">São José dos Pinhais</option></select>
<input type="text" name="bairro"><input name="preco_min" type="number"><button>Buscar</button></form></body></html>"""
P1 = ("""<html><body><ul>
<li><a href="/i/10">Apartamento 2 quartos em Água Verde</a><span>R$ 520.000</span><span>65 m²</span></li>
<li><a href="/i/11">Apartamento no Batel</a><span>R$ 850.000</span><span>85 m²</span></li></ul>
<a rel="next" href="/imoveis?pagina=2">Próxima</a></body></html>""")
P2 = '<html><body><li><a href="/i/20">Apartamento no Centro</a><span>R$ 700.000</span><span>70 m²</span></li></body></html>'
LINKS = '<html><body><a href="/comprar/apartamentos">Comprar</a><a href="/alugar">Alugar</a><a href="/blog">Blog</a></body></html>'
IMOB = {"nome": "Alfa", "site": "https://s.com/", "cidade": "Curitiba", "uf": "PR"}
nada = lambda m: None


class Descoberta(unittest.TestCase):
    def test_site(self):
        self.assertEqual(descoberta.normaliza_site("Alfa.com.br/imoveis?x=1"), "https://alfa.com.br/")
        self.assertEqual(descoberta.normaliza_site("semponto"), "")

    def test_osm(self):
        rede = Rede({"nominatim": [{"osm_type": "node", "osm_id": 1}, {"osm_type": "relation", "osm_id": 297514}],
                     "overpass": {"elements": [
                         {"tags": {"name": "Imob Alfa", "website": "alfa.com.br/imoveis"}},
                         {"tags": {"name": "Imob Beta"}},
                         {"tags": {"name": "Rede social", "website": "https://facebook.com/x"}},
                         {"tags": {"name": "Alfa Filial", "website": "https://www.alfa.com.br/"}}]}})
        r = descoberta.descobrir("Curitiba/PR", cliente=rede, espera=0, progresso=nada)
        self.assertEqual([(x["nome"], x["site"]) for x in r], [("Imob Alfa", "https://alfa.com.br/"), ("Imob Beta", "")])
        self.assertTrue(any("3600297514" in p for p in rede.pedidos))

    def test_places(self):
        rede = Rede({"places.googleapis.com": {"places": [{"displayName": {"text": "Gama Imóveis"},
                                                           "websiteUri": "https://gama.com.br/", "formattedAddress": "Rua X"}]}})
        r = descoberta.descobrir("Curitiba/PR", cliente=rede, chave="k", osm=False, progresso=nada)
        self.assertEqual((r[0]["nome"], r[0]["site"], r[0]["origem"]), ("Gama Imóveis", "https://gama.com.br/", "Google Places"))


class Mapeamento(unittest.TestCase):
    def col(self, rotas):
        self.rede = Rede(rotas)
        return coleta.Coletor(atraso=0, cliente=self.rede)

    def test_formulario_e_consulta_com_filtros(self):
        col = self.col({"s.com/imoveis?pagina=2": P2, "s.com/imoveis": P1, "s.com": FORM})
        st, perfil = mapeamento.mapear(col, IMOB, nada)
        self.assertEqual((st, perfil["metodo"]), ("ok", "formulário"))
        self.assertEqual({c["papel"] for c in perfil["form"]["campos"]}, {"finalidade", "tipo", "cidade", "bairro", "pmin"})
        filtros = {"finalidade": "aluguel", "tipos": ["apartamento"], "bairro": "Batel", "pmin": 300000.0}
        regs = mapeamento.consultar(col, IMOB, perfil, filtros, 3, nada)
        self.assertEqual(len(regs), 3)  # 2 da página 1 + 1 da página 2 (seguiu o link "Próxima")
        q = [p for p in self.rede.pedidos if "negocio=alugar" in p][0]
        for trecho in ("tipo_imovel=apartamento", "cidade=curitiba", "bairro=Batel", "preco_min=300000", "origem=home"):
            self.assertIn(trecho, q)
        self.assertTrue(all(r["finalidade"] == "aluguel" and r["fonte"] == "Alfa" for r in regs))

    def test_cidade_fora_do_formulario(self):
        col = self.col({"s.com/imoveis": P1, "s.com": FORM})
        _, perfil = mapeamento.mapear(col, IMOB, nada)
        longe = dict(IMOB, cidade="Manaus")
        self.assertEqual(mapeamento.consultar(col, longe, perfil, {}, 2, nada), [])

    def test_links_de_listagem(self):
        col = self.col({"s.com/comprar": P1, "s.com/alugar": P2, "s.com": LINKS})
        st, perfil = mapeamento.mapear(col, IMOB, nada)
        self.assertEqual((st, perfil["metodo"], len(perfil["listagens"])), ("ok", "links", 2))
        regs = mapeamento.consultar(col, IMOB, perfil, {"finalidade": "aluguel"}, 2, nada)
        self.assertEqual([r["url"] for r in regs], ["https://s.com/i/20"])

    def test_sem_busca_e_nao_lido(self):
        st, _ = mapeamento.mapear(self.col({"s.com": "<html><p>Olá</p></html>"}), IMOB, nada)
        self.assertEqual(st, "sem_busca")
        st, perfil = mapeamento.mapear(self.col({"s.com/imoveis": "<html></html>", "s.com": FORM}), IMOB, nada)
        self.assertEqual(st, "nao_lido")
        self.assertIn("JavaScript", perfil["detalhe"])

    def test_papeis(self):
        p = mapeamento.papel
        self.assertEqual([p("tipo_negocio"), p("tipoImovel"), p("valor_max"), p("codigo_imovel"), p("q"), p("xyz")],
                         ["finalidade", "tipo", "pmax", "busca", "busca", None])


class Persistencia(unittest.TestCase):
    def setUp(self):
        os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()

    def test_imobiliarias(self):
        l = [dict(IMOB, origem="OpenStreetMap"), {"nome": "Sem site", "site": "", "cidade": "Curitiba", "uf": "PR"}]
        self.assertEqual(banco.salvar_imobiliarias(l), 2)
        self.assertEqual(banco.salvar_imobiliarias(l), 0)
        a, b = banco.listar_imobiliarias("curitiba")
        self.assertEqual((a["nome"], a["selecionada"], b["status"], b["selecionada"]), ("Alfa", True, "sem_site", False))
        banco.gravar_perfil(a["id"], "ok", {"metodo": "links"})
        banco.definir_selecao([a["id"]], False)
        a = banco.listar_imobiliarias(so_selecionadas=False)[0]
        self.assertEqual((a["status"], a["perfil"]["metodo"], a["selecionada"]), ("ok", "links", False))

    def test_fluxo_completo(self):
        rede = Rede({"nominatim": [{"osm_type": "relation", "osm_id": 1}],
                     "overpass": {"elements": [{"tags": {"name": "Alfa", "website": "https://s.com/"}}]},
                     "s.com/imoveis?pagina=2": P2, "s.com/imoveis": P1, "s.com": FORM})
        col = coleta.Coletor(atraso=0, cliente=rede)
        with mock.patch("time.sleep"):
            regs = mapeamento.explorar(col, "Curitiba/PR", {"finalidade": "venda", "tipos": ["apartamento"]}, 3,
                                       cliente_api=rede, progresso=nada)
        self.assertEqual(len(regs), 3)
        self.assertEqual(len(banco.carregar()), 3)


class WebImobiliarias(unittest.TestCase):
    def setUp(self):
        os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()
        from buscaimoveis.web import criar_app
        self.c = criar_app().test_client()

    def espera(self):
        for _ in range(100):
            s = self.c.get("/api/status").json
            if not s["rodando"]:
                return s
            time.sleep(0.05)
        self.fail("tarefa não terminou")

    def test_api(self):
        self.assertEqual(self.c.post("/api/imobiliarias/adicionar", json={"nome": "X", "site": "x", "cidade": "A"}).status_code, 400)
        self.assertEqual(self.c.post("/api/imobiliarias/adicionar", json={"nome": "Delta", "site": "delta.com.br", "cidade": "Recife/PE"}).status_code, 200)
        i = self.c.get("/api/imobiliarias?cidade=Recife").json[0]
        self.assertEqual((i["nome"], i["site"]), ("Delta", "https://delta.com.br/"))
        self.c.post("/api/imobiliarias/selecao", json={"ids": [i["id"]], "valor": False})
        self.assertFalse(self.c.get("/api/imobiliarias").json[0]["selecionada"])
        achada = [{"nome": "Eta", "site": "https://eta.com.br/", "cidade": "Recife", "uf": "PE", "origem": "teste"}]
        with mock.patch("buscaimoveis.descoberta.descobrir", return_value=achada):
            self.assertEqual(self.c.post("/api/imobiliarias/descobrir", json={"cidade": "Recife/PE"}).status_code, 200)
            log = self.espera()["log"]
        self.assertIn("1 imobiliárias encontradas", log[-1])
        self.assertEqual(len(self.c.get("/api/imobiliarias").json), 2)
        self.assertIn("casa", self.c.get("/api/opcoes").json["tipos"])


if __name__ == "__main__":
    unittest.main()
