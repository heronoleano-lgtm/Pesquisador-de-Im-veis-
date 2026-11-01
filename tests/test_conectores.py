import os, tempfile, unittest
from unittest import mock

os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()

from buscaimoveis import banco, coleta, conectores as C, segredos  # noqa: E402

# Resposta no formato descrito na documentação do GeckoAPI para a listagem do ZAP (31/10/2026).
def pagina(itens, prox):
    return {"requestId": "x", "data": {"source": "zapimoveis.com.br", "type": "plp", "page": 1, "nextPage": prox, "items": itens}}

def item(i, preco, desc="Apartamento com varanda e piscina", area=80, quartos=2, bairro="Batel"):
    return {"id": f"z{i}", "url": f"https://www.zapimoveis.com.br/imovel/{i}", "description": desc,
            "address": {"city": "Curitiba", "state": "PR", "neighborhood": bairro},
            "prices": {"mainValue": preco, "period": "TOTAL"}, "amenities": ["POOL", "Elevador"],
            "attributes": {"usableAreas": [area], "totalAreas": [area + 10], "bedrooms": [quartos], "bathrooms": [1], "parkingSpaces": [1]}}

GECKO = {"ativo": True, "url": "https://api.geckoapi.com.br/v1/extract", "metodo": "POST",
         "cabecalhos": {"Authorization": "Bearer ${GECKOAPI_CHAVE}", "Content-Type": "application/json"},
         "corpo": {"target": "zapimoveis.com.br", "type": "plp", "city": "{cidade_nome}", "state": "{UF}",
                   "businessType": "{finalidade}", "neighborhood": "{bairro}", "priceMin": "{pmin}", "priceMax": "{pmax}",
                   "bedrooms": "{quartos_lista}", "page": "{pagina}"},
         "finalidades": {"venda": "sale", "aluguel": "rent"}, "resultados": "data.items", "proxima": "data.nextPage",
         "max_paginas": 3, "limite_diario": 5, "mapa_caracteristicas": {"pool": "piscina"},
         "campos": {"id": "id", "url": "url", "titulo": "description", "bairro": "address.neighborhood",
                    "preco": "prices.mainValue", "area": ["attributes.usableAreas.0", "attributes.totalAreas.0"],
                    "quartos": "attributes.bedrooms.0", "banheiros": "attributes.bathrooms.0",
                    "vagas": "attributes.parkingSpaces.0", "caracteristicas": "amenities"}}


class Falso:
    """Cliente HTTP falso com o método request(), como o do httpx."""
    def __init__(self, respostas, status=200):
        self.respostas, self.status, self.chamadas = list(respostas), status, []

    def request(self, metodo, url, params=None, json=None, headers=None):
        self.chamadas.append({"metodo": metodo, "url": url, "params": params, "json": json, "headers": headers})
        corpo = self.respostas.pop(0) if self.respostas else pagina([], None)
        return type("R", (), {"status_code": self.status, "json": lambda s: corpo})()


class Caminhos(unittest.TestCase):
    def test_caminho_e_alternativas(self):
        d = {"a": {"b": [{"c": 7}, {"c": 8}]}, "v": [], "z": ""}
        self.assertEqual(C.caminho(d, "a.b.1.c"), 8)
        self.assertEqual(C.caminho(d, "a.b.-1.c"), 8)
        self.assertIsNone(C.caminho(d, "a.x.1"))
        self.assertIsNone(C.caminho(d, "a.b.9.c"))
        self.assertEqual(C.primeiro(d, ["v", "z", "a.b.0.c"]), 7)

    def test_preencher_mantem_tipos_e_omite_vazios(self):
        v = {"cidade_nome": "Curitiba", "pmin": 0, "pmax": 700000, "quartos_lista": [2, 3, 4], "bairro": None, "pagina": 2}
        m = {"city": "{cidade_nome}", "priceMin": "{pmin}", "priceMax": "{pmax}", "bedrooms": "{quartos_lista}",
             "neighborhood": "{bairro}", "q": "cidade={cidade_nome}&p={pagina}", "fixo": 5, "aninhado": {"x": "{bairro}"}}
        self.assertEqual(C.preencher(m, v), {"city": "Curitiba", "priceMax": 700000, "bedrooms": [2, 3, 4],
                                             "q": "cidade=Curitiba&p=2", "fixo": 5, "aninhado": {}})

    def test_json_dentro_de_texto_nao_e_confundido_com_modelo(self):
        modelo = '{"filter":{"Cidade":"{cidade_nome}"},"paginacao":{"pagina":{pagina},"quantidade":50}}'
        r = C.preencher(modelo, {"cidade_nome": "Porto Alegre", "pagina": 3})
        self.assertEqual(r, '{"filter":{"Cidade":"Porto Alegre"},"paginacao":{"pagina":3,"quantidade":50}}')


class Segredos(unittest.TestCase):
    def setUp(self):
        os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()
        os.environ.pop("MINHA_CHAVE", None)

    def test_guardar_expandir_faltando(self):
        self.assertEqual(segredos.faltando({"h": "Bearer ${MINHA_CHAVE}"}), ["MINHA_CHAVE"])
        segredos.guardar("MINHA_CHAVE", "abc123")
        self.assertEqual(segredos.expandir({"h": ["Bearer ${MINHA_CHAVE}"]}), {"h": ["Bearer abc123"]})
        self.assertEqual(segredos.faltando({"h": "${MINHA_CHAVE}"}), [])
        self.assertEqual(oct(os.stat(os.path.join(os.environ["BUSCAIMOVEIS_HOME"], "chaves.json")).st_mode & 0o777), "0o600")
        os.environ["MINHA_CHAVE"] = "do-ambiente"
        try:
            self.assertEqual(segredos.valor("MINHA_CHAVE"), "do-ambiente")  # o ambiente tem prioridade
        finally:
            os.environ.pop("MINHA_CHAVE")

    def test_nome_invalido(self):
        with self.assertRaises(ValueError):
            segredos.guardar("minha chave", "x")


class Conector(unittest.TestCase):
    def setUp(self):
        os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()
        segredos.guardar("GECKOAPI_CHAVE", "sk-segredo")
        self.cfg = {"coleta": {}, "sites": {}, "apis": {"gecko-zap": dict(GECKO)}}
        self.log = []

    def buscar(self, falso, **kw):
        col = coleta.Coletor(atraso=0, cliente=falso)
        with mock.patch("time.sleep"):
            return coleta.buscar(self.cfg, ["Curitiba/PR"], kw.get("fins", ["venda"]), kw.get("tipos", []),
                                 kw.get("pag"), None, self.log.append, col, kw.get("filtros"))

    def test_consulta_converte_e_pagina(self):
        falso = Falso([pagina([item(1, 850000), item(2, 720000, quartos=3)], 2), pagina([item(3, 640000, area=70)], None)])
        regs = self.buscar(falso, filtros={"quartos": 2, "pmax": 900000, "bairro": "Batel"})
        self.assertEqual(sorted(r["preco"] for r in regs), [640000, 720000, 850000])
        r = [x for x in regs if x["preco"] == 850000][0]
        self.assertEqual((r["cidade"], r["uf"], r["bairro"], r["tipo"], r["finalidade"], r["area"], r["quartos"], r["vagas"]),
                         ("Curitiba", "PR", "Batel", "apartamento", "venda", 80.0, 2, 1))
        self.assertEqual((r["fonte"], r["id"], r["url"]), ("gecko-zap", "gecko-zap:z1", "https://www.zapimoveis.com.br/imovel/1"))
        self.assertIn("piscina", r["caracteristicas"])
        self.assertIn("elevador", r["caracteristicas"])
        c1, c2 = falso.chamadas
        self.assertEqual((c1["metodo"], c1["url"]), ("POST", "https://api.geckoapi.com.br/v1/extract"))
        self.assertEqual(c1["headers"]["Authorization"], "Bearer sk-segredo")
        self.assertEqual(c1["json"], {"target": "zapimoveis.com.br", "type": "plp", "city": "Curitiba", "state": "PR",
                                      "businessType": "sale", "neighborhood": "Batel", "priceMax": 900000,
                                      "bedrooms": [2, 3, 4, 5, 6], "page": 1})
        self.assertEqual(c2["json"]["page"], 2)  # seguiu a paginação
        self.assertEqual(banco.uso_api_hoje("gecko-zap"), 2)

    def test_para_quando_nextpage_e_nulo(self):
        falso = Falso([pagina([item(1, 500000)], None), pagina([item(2, 600000)], None)])
        self.assertEqual(len(self.buscar(falso)), 1)
        self.assertEqual(len(falso.chamadas), 1)

    def test_aluguel_e_finalidades(self):
        falso = Falso([pagina([item(1, 3000)], None), pagina([item(2, 400000)], None)])
        regs = self.buscar(falso, fins=["aluguel", "venda"])
        self.assertEqual([c["json"]["businessType"] for c in falso.chamadas], ["rent", "sale"])
        self.assertEqual(sorted((r["finalidade"], r["preco"]) for r in regs), [("aluguel", 3000), ("venda", 400000)])

    def test_limite_diario_protege_os_creditos(self):
        self.cfg["apis"]["gecko-zap"]["limite_diario"] = 2
        falso = Falso([pagina([item(i, 500000 + i)], i + 1) for i in range(1, 9)])
        self.buscar(falso, pag=10)
        self.assertEqual(len(falso.chamadas), 2)
        self.assertTrue(any("limite diário" in m for m in self.log))
        falso2 = Falso([pagina([item(9, 1)], None)])
        self.buscar(falso2)
        self.assertEqual(falso2.chamadas, [])  # no mesmo dia, nada mais é chamado

    def test_sem_chave_nao_chama(self):
        os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp()  # base sem a chave guardada
        falso = Falso([pagina([item(1, 1)], None)])
        self.assertEqual(self.buscar(falso), [])
        self.assertEqual(falso.chamadas, [])
        self.assertTrue(any("buscaimoveis chave GECKOAPI_CHAVE" in m for m in self.log))

    def test_so_roda_com_ativo_true(self):
        for valor in (False, None, "sim"):
            self.cfg["apis"]["gecko-zap"]["ativo"] = valor
            falso = Falso([pagina([item(1, 1)], None)])
            self.assertEqual(self.buscar(falso), [])
            self.assertEqual(falso.chamadas, [])

    def test_erros_da_api_nao_vazam_a_chave(self):
        for status, trecho in ((401, "recusou a chave"), (402, "créditos"), (500, "erro (código 500)")):
            os.environ["BUSCAIMOVEIS_HOME"] = tempfile.mkdtemp(); segredos.guardar("GECKOAPI_CHAVE", "sk-segredo")
            self.log.clear()
            self.assertEqual(self.buscar(Falso([{}], status=status)), [])
            self.assertTrue(any(trecho in m for m in self.log), (status, self.log))
            self.assertFalse(any("sk-segredo" in m for m in self.log))

    def test_excecao_de_rede_nao_vaza_a_chave(self):
        class Quebra:
            def request(self, *a, **k):
                raise RuntimeError("falha em https://x/?key=sk-segredo")
        self.buscar(Quebra())
        self.assertTrue(any("RuntimeError" in m for m in self.log))
        self.assertFalse(any("sk-segredo" in m for m in self.log))

    def test_descarta_itens_sem_tipo_preco_ou_area(self):
        ruim = [item(1, 0), item(2, 500000, desc="Imóvel lindo"), item(3, 500000, area=0), "lixo", item(4, 400000)]
        ruim[2]["attributes"] = {}
        regs = self.buscar(Falso([pagina(ruim, None)]))
        self.assertEqual([r["preco"] for r in regs], [400000])
        self.assertTrue(any("3 descartados" in m or "4 descartados" in m for m in self.log), self.log)

    def test_resposta_em_dicionario_como_a_do_vista(self):
        self.cfg["apis"] = {"vista": {"ativo": True, "url": "https://x.vistahost.com.br/imoveis/listar", "metodo": "GET",
                                      "parametros": {"key": "${GECKOAPI_CHAVE}", "pesquisa": '{"filter":{"Cidade":"{cidade_nome}"}}'},
                                      "campos": {"id": "Codigo", "titulo": "Titulo", "preco": "ValorVenda", "area": "AreaTotal",
                                                 "bairro": "Bairro", "quartos": "Dormitorio"}}}
        resp = {"1": {"Codigo": "A1", "Titulo": "Casa no Portão", "ValorVenda": "R$ 780.000", "AreaTotal": "150", "Bairro": "Portão", "Dormitorio": "3"},
                "total": 1}
        falso = Falso([resp])
        regs = self.buscar(falso)
        self.assertEqual((regs[0]["tipo"], regs[0]["preco"], regs[0]["quartos"], regs[0]["id"]), ("casa", 780000, 3, "vista:A1"))
        self.assertEqual(falso.chamadas[0]["params"]["pesquisa"], '{"filter":{"Cidade":"Curitiba"}}')
        self.assertEqual(falso.chamadas[0]["params"]["key"], "sk-segredo")

    def test_tipos_mapeados_um_pedido_por_tipo(self):
        c = self.cfg["apis"]["gecko-zap"]
        c["corpo"]["propertyType"] = "{tipo}"
        c["tipos"] = {"apartamento": "apartment", "casa": "home"}
        falso = Falso([pagina([item(1, 1000)], None), pagina([item(2, 2000, desc="Casa grande")], None)])
        regs = self.buscar(falso, tipos=["apartamento", "casa", "terreno"])
        self.assertEqual([x["json"]["propertyType"] for x in falso.chamadas], ["apartment", "home"])
        self.assertTrue(any("'terreno' sem equivalente" in m for m in self.log))
        self.assertEqual(len(regs), 2)

    def test_bloqueia_endereco_interno(self):
        self.cfg["apis"]["gecko-zap"]["url"] = "http://169.254.169.254/latest/meta-data/"
        falso = Falso([pagina([item(1, 1)], None)])
        col = coleta.Coletor(atraso=0, cliente=falso, bloquear_internos=True)
        coleta.buscar(self.cfg, ["Curitiba/PR"], ["venda"], [], 1, None, self.log.append, col)
        self.assertEqual(falso.chamadas, [])
        self.assertTrue(any("rede interna" in m for m in self.log))


class ExemploDoArquivo(unittest.TestCase):
    def test_sites_exemplo_traz_a_api_desativada(self):
        import yaml
        from pathlib import Path
        cfg = yaml.safe_load((Path(coleta.__file__).parent / "sites_exemplo.yaml").read_text(encoding="utf-8"))
        api = cfg["apis"]["geckoapi-zap"]
        self.assertIs(api["ativo"], False)
        self.assertIn("${GECKOAPI_CHAVE}", api["cabecalhos"]["Authorization"])
        self.assertEqual(C.escolher(cfg), {})


if __name__ == "__main__":
    unittest.main()
