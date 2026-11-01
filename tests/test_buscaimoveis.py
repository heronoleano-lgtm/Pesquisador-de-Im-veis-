import os, tempfile, unittest
from pathlib import Path

os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()

from buscaimoveis import analise, banco, coleta, normaliza as N  # noqa: E402

JSONLD = """<html><script type="application/ld+json">{"@context":"https://schema.org","@graph":[
{"@type":"Apartment","name":"Apartamento 3 quartos em Batel","url":"/imovel/1","description":"Com varanda e piscina, 2 vagas",
 "floorSize":{"value":"90"},"numberOfBedrooms":3,"numberOfBathroomsTotal":2,"address":{"addressNeighborhood":"Batel"},
 "offers":{"price":"900000"}},
{"@type":"House","name":"Casa em Portão","url":"/imovel/2","floorSize":{"value":"150"},"offers":{"price":"780000"}}]}</script></html>"""

CARTOES = """<html><body><ul>
<li><a href="/i/10">Apartamento 2 quartos em Água Verde</a><span>R$ 520.000</span><span>Cond. R$ 600</span><span>65 m²</span><span>2 quartos 1 vaga</span></li>
<li><a href="/i/11">Casa com churrasqueira no Cabral</a><span>R$ 1.250.000,00</span><span>210 m²</span><span>4 quartos 3 banheiros 2 vagas</span></li>
<li><a href="/i/12">Sem preço aqui</a><span>45 m²</span></li></ul></body></html>"""

CTX = {"cidade": "Curitiba", "uf": "PR", "fonte": "teste", "finalidade": "venda"}


class Falso:
    def __init__(self, paginas, robots="User-agent: *\nAllow: /"):
        self.paginas, self.robots, self.pedidos = paginas, robots, []

    def get(self, url):
        self.pedidos.append(url)
        txt = self.robots if url.endswith("/robots.txt") else self.paginas.pop(0) if self.paginas else "<html></html>"
        return type("R", (), {"status_code": 200, "text": txt, "raise_for_status": lambda s: None})()


class Normaliza(unittest.TestCase):
    def test_numeros(self):
        self.assertEqual(N.num("R$ 1.200.000,50"), 1200000.5)
        self.assertEqual(N.num("850.000"), 850000)
        self.assertEqual(N.num("85.5"), 85.5)
        self.assertEqual(N.num(None), 0)

    def test_texto(self):
        e = N.extrair_texto("Apto 2 quartos 1 vaga 65 m² Cond. R$ 600 R$ 520.000 IPTU R$ 90")
        self.assertEqual((e["preco"], e["condominio"], e["area"], e["quartos"], e["vagas"]), (520000, 600, 65, 2, 1))

    def test_tipo_e_caracteristicas(self):
        self.assertEqual(N.tipo_de("Cobertura duplex"), "cobertura")
        self.assertEqual(N.tipo_de("Sobrado novo"), "casa")
        self.assertEqual(N.caracteristicas_de("Tem piscina, não aceita pet"), ["piscina"])

    def test_id_estavel_com_url(self):
        a = N.registro(url="http://x/1", preco=100, area=10, cidade="A", tipo="casa")
        b = N.registro(url="http://x/1", preco=999, area=10, cidade="A", tipo="casa")
        self.assertEqual(a["id"], b["id"])


class Extracao(unittest.TestCase):
    def test_jsonld(self):
        regs, m = coleta.extrair(JSONLD, "https://s.com/busca", CTX)
        self.assertEqual(len(regs), 2)
        r = {x["tipo"]: x for x in regs}["apartamento"]
        self.assertEqual((r["preco"], r["area"], r["quartos"], r["bairro"]), (900000, 90, 3, "Batel"))
        self.assertIn("piscina", r["caracteristicas"])
        self.assertEqual(r["url"], "https://s.com/imovel/1")

    def test_cartoes_e_descarta_sem_preco(self):
        regs, m = coleta.extrair(CARTOES, "https://s.com/", CTX)
        self.assertEqual(m, "cartões da página")
        self.assertEqual(len(regs), 2)
        ap = [r for r in regs if r["tipo"] == "apartamento"][0]
        self.assertEqual((ap["preco"], ap["condominio"], ap["area"], ap["bairro"]), (520000, 600, 65, "Água Verde"))

    def test_seletores(self):
        html = '<div class="x"><a href="/a">Casa em Centro</a><b class="p">R$ 300.000</b><i class="m">120 m²</i></div>'
        regs, _ = coleta.extrair(html, "https://s.com/", CTX, {"cartao": ".x", "preco": ".p", "area": ".m"})
        self.assertEqual((regs[0]["preco"], regs[0]["area"]), (300000, 120))


class Coleta(unittest.TestCase):
    cfg = {"coleta": {}, "sites": {"s": {"url": "https://s.com/{finalidade}/{tipo}/{cidade}-{uf}?p={pagina}",
                                         "finalidades": {"venda": "comprar"}, "tipos": {"apartamento": "aptos"}, "max_paginas": 5}}}

    def test_paginacao_para_quando_acaba(self):
        f = Falso([CARTOES, CARTOES])  # a 2ª página repete os mesmos anúncios: deve parar
        col = coleta.Coletor(atraso=0, cliente=f)
        regs = coleta.buscar(self.cfg, ["Curitiba/PR"], ["venda"], ["apartamento"], progresso=lambda m: None, coletor=col)
        self.assertEqual(len(regs), 2)
        self.assertIn("https://s.com/comprar/aptos/curitiba-pr?p=1", f.pedidos)
        self.assertEqual(sum(1 for p in f.pedidos if "?p=" in p), 2)  # 2ª página sem novidades: para

    def test_robots_bloqueia(self):
        f = Falso([CARTOES], robots="User-agent: *\nDisallow: /")
        col = coleta.Coletor(atraso=0, cliente=f)
        msgs = []
        regs = coleta.buscar(self.cfg, ["Curitiba/PR"], ["venda"], ["apartamento"], progresso=msgs.append, coletor=col)
        self.assertEqual(regs, [])
        self.assertTrue(any("robots" in m for m in msgs))


class BancoEAnalise(unittest.TestCase):
    def setUp(self):
        os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()

    def regs(self, preco2=500000):
        mk = lambda i, p, a=80, b="Centro": N.registro(url=f"http://x/{i}", cidade="Curitiba", bairro=b, tipo="apartamento",
                                                       finalidade="venda", preco=p, area=a, quartos=2, fonte="s",
                                                       caracteristicas="piscina" if i % 2 else "")
        return [mk(1, 400000), mk(2, preco2), mk(3, 600000), mk(4, 560000), mk(5, 520000), mk(6, 10000)]

    def test_historico_e_inativos(self):
        banco.salvar(self.regs())
        novos, alt = banco.salvar(self.regs(preco2=450000))
        self.assertEqual((novos, alt), (0, 1))
        df = banco.carregar()
        self.assertAlmostEqual(df[df.url == "http://x/2"].variacao.iloc[0], -0.1, places=3)
        self.assertEqual(banco.desativar_antigos("s", "Curitiba", "9999"), len(df))
        self.assertEqual(len(banco.carregar()), 0)

    def test_filtros_pontuacao_suspeitos(self):
        banco.salvar(self.regs())
        df = analise.analisar(banco.carregar())
        self.assertTrue(df[df.preco == 10000].suspeito.iloc[0])
        f = analise.filtrar(df, "venda", ["Curitiba"], ["apartamento"], obrigatorias=["piscina"], sem_suspeitos=True)
        self.assertTrue(len(f) and all("piscina" in x for x in f.feat) and not f.suspeito.any())
        p = analise.pontuar(df, desejaveis=["piscina"], bairros=["centro"])
        self.assertTrue(p.nota.between(0, 100).all())
        barato = analise.ordenar(p[~p.suspeito], "nota").iloc[0]
        self.assertEqual(barato.preco, 400000)

    def test_duplicado_entre_sites(self):
        a = N.registro(url="http://a/1", cidade="X", bairro="B", tipo="casa", finalidade="venda", preco=1, area=1, quartos=1, fonte="a")
        b = N.registro(url="http://b/9", cidade="X", bairro="B", tipo="casa", finalidade="venda", preco=1, area=1, quartos=1, fonte="b")
        banco.salvar([a, b])
        df = analise.analisar(banco.carregar())
        self.assertEqual(df[df.cidade == "X"].fontes.iloc[0], "a, b")
        self.assertEqual(len(df[df.cidade == "X"]), 1)


class Web(unittest.TestCase):
    def setUp(self):
        os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()

    def test_api(self):
        from buscaimoveis.web import criar_app
        c = criar_app().test_client()
        banco.salvar([N.registro(url="http://w/1", cidade="Recife", bairro="Boa Viagem", tipo="apartamento", finalidade="venda",
                                 preco=700000, area=70, quartos=2, fonte="w")])
        self.assertEqual(c.get("/").status_code, 200)
        self.assertIn("Recife", c.get("/api/opcoes").json["cidades"])
        j = c.get("/api/imoveis?fin=venda&cidades=Recife&q=2").json
        self.assertEqual((j["total"], j["itens"][0]["pm"]), (1, 10000))
        r = c.post("/api/importar", json={"texto": "cidade;tipo;finalidade;preco;area\nRecife;casa;aluguel;3.500;100"})
        self.assertEqual(r.json["lidos"], 1)
        self.assertEqual(c.get("/manifest.webmanifest").status_code, 200)
        self.assertIn("preco", c.get("/api/exportar.csv").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
