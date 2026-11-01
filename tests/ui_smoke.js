// Teste de fumaça da interface: roda o script de index.html com um DOM simulado (não é um navegador de verdade).
const fs = require("fs"), vm = require("vm"), path = require("path"), assert = require("assert");
const html = fs.readFileSync(path.join(__dirname, "..", "buscaimoveis", "static", "index.html"), "utf8");
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];

// 1) todo $("#id") do script existe no HTML estático ou num modelo do próprio script
const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]));
const usados = [...new Set([...script.matchAll(/\$\("#([A-Za-z0-9_-]+)"\)/g)].map(m => m[1]))];
const faltam = usados.filter(i => !ids.has(i) && !["mc"].includes(i) && !script.includes(`id="${i}"`));
assert.deepStrictEqual(faltam, [], "ids usados no script e ausentes no HTML: " + faltam);

// 2) DOM simulado
const mk = (sel, extra = {}) => {
  const cls = new Set();
  return Object.assign({ sel, innerHTML: "", textContent: "", value: "", checked: false, hidden: false, open: false, dataset: {},
    style: {}, attrs: {}, offsetParent: {}, children: [],
    classList: { add: c => cls.add(c), remove: c => cls.delete(c), contains: c => cls.has(c), toggle(c, f) { (f === undefined ? !cls.has(c) : f) ? cls.add(c) : cls.delete(c); } },
    setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; }, getAttribute(k) { return this.attrs[k]; },
    addEventListener() {}, scrollIntoView() {}, closest() { return null; } }, extra);
};
const els = {}, el = s => (els[s] ||= mk(s));
const abas = ["r", "s", "m", "a", "c", "i", "x"].map(t => mk("[data-t]", { dataset: { t }, offsetParent: ["c", "i"].includes(t) ? null : {} }));
const fins = ["venda", "aluguel"].map(f => mk("[data-f]", { dataset: { f } }));
const gancho = {}, loc = { href: "/" }, chamadas = [], armazenamento = {}, cachesApagados = [];
const IM = [
  { id: "a1", titulo: "Apartamento 2 quartos em Água Verde", bairro: "Água Verde", cidade: "Curitiba", tipo: "apartamento", finalidade: "venda", preco: 520000, area: 65, pm: 8000, desvio: -0.1, nota: 78, quartos: 2, banheiros: 1, vagas: 1, condominio: 600, feat: ["varanda"], fonte: "Alfa", fontes: "Alfa", url: "https://s.com/i/10", suspeito: false },
  { id: "a2", titulo: "Casa no Portão", bairro: "Portão", cidade: "Curitiba", tipo: "casa", finalidade: "venda", preco: 780000, area: 150, pm: 5200, desvio: 0.2, nota: 40, quartos: 3, banheiros: 2, vagas: 2, condominio: 0, feat: [], fonte: "Beta", url: "", suspeito: true }];
let modo = "ok", NL = 2;
const BUSCAS = [{ id: "b1", nome: "Apto Batel", cidade: "Curitiba", uf: "PR", ativa: 1, ultima_exec: "2026-10-31T20:00:00", proxima: "2026-10-31T22:00", ultimo_resumo: "10 lidos · 3 casam" }];
const resp = (corpo, o = {}) => ({ ok: (o.status || 200) < 400, status: o.status || 200, headers: { get: k => (o.headers || {})[k] ?? null }, json: async () => corpo });
const fetchFalso = async (u, o = {}) => {
  chamadas.push([o.method || "GET", u]);
  if (modo == "queda") throw new TypeError("falha de rede");
  if (modo == "401") return resp({ erro: "Entre com o código de acesso." }, { status: 401 });
  const hd = modo == "offline" ? { "x-offline": "1" } : {};
  if (u.startsWith("/api/opcoes")) return resp({ cidades: ["Curitiba"], tipos: ["apartamento", "casa"], caracteristicas: ["varanda"], sites: [], total: 2, nao_lidos: 2 }, { headers: hd });
  if (u.startsWith("/api/imoveis")) return resp({ total: 2, mediana_pm: 6600, itens: IM }, { headers: hd });
  if (u.startsWith("/api/status")) return resp({ rodando: false, log: [] });
  if (u.startsWith("/api/imobiliarias")) return resp([]);
  if (u == "/api/buscas" && !o.method) return resp(BUSCAS);
  if (u.startsWith("/api/alertas?")) return resp({ nao_lidos: NL, itens: [
    { id: 1, tipo: "novo", lido: 0, busca_nome: "Apto <b>Batel</b>", criado_em: "2026-10-31T21:00:00", dados: { preco: 500000, tipo: "apartamento", bairro: "Batel", area: 60, url: "https://s.com/i/1" } },
    { id: 2, tipo: "queda", lido: 1, busca_nome: "Apto", criado_em: "2026-10-30T09:00:00", dados: { preco: 450000, preco_anterior: 500000, tipo: "casa", bairro: "Portão", url: "javascript:alert(1)" } }] });
  if (u == "/api/alertas/lidos") { NL = 0; return resp({ nao_lidos: 0 }); }
  if (u == "/api/alertas/teste") return resp({ canais: { ntfy: { ok: false, erro: "ntfy indisponível" } } });
  if (u == "/api/vigia") return resp({ ativo: true, canais: ["ntfy"], silencio: "22:00-07:00", log: [], proximas: {} });
  return resp({ ok: true });
};
const ctx = vm.createContext({
  document: { querySelector: el, querySelectorAll: s => (s == "[data-t]" ? abas : s == "[data-f]" ? fins : []) },
  fetch: fetchFalso, console, setTimeout, clearTimeout, URLSearchParams, location: loc, isSecureContext: true, Set, Promise, JSON, Math, Number, String, Array, Object, Error,
  matchMedia: () => ({ matches: false }), scrollTo() {},
  addEventListener: (n, f) => (gancho[n] = f),
  localStorage: { getItem: k => armazenamento[k] ?? null, setItem: (k, v) => (armazenamento[k] = v), removeItem: k => delete armazenamento[k] },
  caches: { keys: async () => ["imv-1.4.0"], delete: async k => cachesApagados.push(k) },
  navigator: { share: async d => (ctx.__compartilhado = d), userAgent: "Android", standalone: false },
});
const espera = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  vm.runInContext(script, ctx);
  await espera(450);
  const saida = () => el("#out").innerHTML;

  // lista de imóveis
  assert.ok(saida().includes('class="grid"') && saida().includes("Água Verde") && saida().includes("520.000"), "cartões não apareceram");
  assert.ok(saida().includes("data-share=\"https://s.com/i/10\""), "botão de compartilhar ausente");
  assert.ok(!saida().includes("data-share=\"\""), "compartilhar sem endereço");
  assert.ok(saida().includes("fora do padrão"), "aviso de preço suspeito ausente");
  assert.strictEqual(el("#fs").textContent, "Filtros");
  assert.strictEqual(el("#off").hidden, true);
  assert.ok(el("#ff").classList.contains("v"), "botão Filtros deveria aparecer na aba Imóveis");

  // contador de filtros
  el("#bairro").value = "Batel"; el("#q").value = "2";
  ctx.marca();
  assert.strictEqual(el("#fs").textContent, "Filtros (2)");
  el("#bairro").value = ""; el("#q").value = "0"; ctx.marca();

  // compartilhar
  const alvo = { dataset: { share: "https://s.com/i/10", st: "Apartamento · R$ 520.000" } };
  await el("#out").onclick({ target: { closest: s => (s == "[data-share]" ? alvo : null) } });
  assert.strictEqual(ctx.__compartilhado.url, "https://s.com/i/10");

  // selecionar e comparar
  await el("#out").onclick({ target: { closest: s => (s == "[data-id]" ? { dataset: { id: "a1" } } : null) } });
  assert.strictEqual(armazenamento.imv, '["a1"]');
  assert.strictEqual(el("#nb").textContent, " (1)");
  abas[1].onclick(); await espera(450);
  assert.ok(saida().includes("Maior nota entre os selecionados"), "comparação não apareceu");
  assert.ok(chamadas.some(c => c[1].includes("ids=a1")), "não pediu só os selecionados");
  assert.ok(!el("#ff").classList.contains("v"), "botão Filtros não deve aparecer em Comparar");

  // aba Alertas
  assert.strictEqual(el("#bd").textContent, "2", "contador de não lidos ausente");
  abas[3].onclick(); await espera(100);
  assert.ok(saida().includes("Salvar os filtros atuais"), "aba Alertas não abriu");
  assert.ok(el("#bl").innerHTML.includes("Apto Batel") && el("#bl").innerHTML.includes("próxima: 31/10 22:00"), "busca salva não listada");
  assert.ok(el("#al").innerHTML.includes("Novo por") && el("#al").innerHTML.includes("Preço caiu de"), "alertas não listados");
  assert.ok(!el("#al").innerHTML.includes("<b>Batel</b>"), "nome da busca não foi escapado");
  assert.ok(!el("#al").innerHTML.includes("javascript:"), "endereço perigoso virou link");
  assert.ok(el("#vs").textContent.includes("Vigia ligado") && el("#vs").textContent.includes("22:00-07:00"));
  el("#bn").value = "Minha busca"; el("#bc").value = "Curitiba/PR"; el("#pmax").value = "600000"; el("#q").value = "2";
  await el("#bs").onclick(); await espera(50);
  const salvou = chamadas.filter(c => c[0] == "POST" && c[1] == "/api/buscas");
  assert.strictEqual(salvou.length, 1, "busca não foi salva");
  el("#pmax").value = ""; el("#q").value = "0";
  await el("#bl").onclick({ target: { closest: s => (s == "[data-bx]" ? { dataset: { bx: "b1" } } : null) } }); await espera(50);
  assert.ok(chamadas.some(c => c[0] == "POST" && c[1] == "/api/buscas/executar"), "não pediu para rodar a busca");
  await el("#vt").onclick(); await espera(50);
  assert.ok(el("#vs").textContent.includes("falhou"), "falha do teste não apareceu");
  await el("#alr").onclick(); await espera(100);
  assert.strictEqual(el("#bd").textContent, "", "contador deveria zerar");

  // menu Mais
  abas[6].onclick(); await espera(50);
  assert.ok(saida().includes("Sair e apagar") && saida().includes("Adicionar à tela inicial") && !saida().includes('id="bi"'));
  let instalou = false;
  gancho.beforeinstallprompt({ preventDefault() {}, prompt() { instalou = true; }, userChoice: Promise.resolve({}) });
  await espera(50);
  assert.ok(saida().includes('id="bi"'), "botão Instalar app não apareceu");
  await el("#bi").onclick(); assert.ok(instalou);
  // "Coletar" fica escondido no celular: a aba Mais é que deve ficar marcada
  await el("#out").onclick({ target: { closest: s => (s == "[data-go]" ? { dataset: { go: "c" } } : null) } });
  await espera(50);
  assert.ok(saida().includes("sites.yaml") && abas[6].classList.contains("on") && !abas[4].classList.contains("on"));
  abas[0].onclick(); await espera(450);

  // sem conexão com o servidor
  modo = "queda"; el("#bairro").value = "x"; vm.runInContext("busca()", ctx); await espera(450);
  assert.strictEqual(el("#off").hidden, false, "aviso offline não apareceu");
  assert.ok(saida().includes("Sem conexão"));
  modo = "ok"; vm.runInContext("busca()", ctx); await espera(450);
  assert.strictEqual(el("#off").hidden, true, "aviso offline não sumiu");

  // resposta vinda do cache do aparelho
  modo = "offline"; vm.runInContext("busca()", ctx); await espera(450);
  assert.strictEqual(el("#off").hidden, false, "resposta do cache deveria mostrar o aviso");
  assert.ok(saida().includes("Água Verde"), "o cache deveria continuar mostrando os imóveis");
  modo = "ok";

  // sessão expirada
  modo = "401"; vm.runInContext("busca()", ctx); await espera(450);
  assert.strictEqual(loc.href, "/entrar"); modo = "ok"; loc.href = "/";

  // sair
  await ctx.sair();
  assert.ok(chamadas.some(c => c[0] == "POST" && c[1] == "/api/sair"));
  assert.deepStrictEqual(cachesApagados, ["imv-1.4.0"]);
  assert.strictEqual(armazenamento.imv, undefined);
  assert.strictEqual(loc.href, "/entrar");
  console.log("interface: todas as verificações passaram");
})().catch(e => { console.error("FALHOU:", e.message); process.exit(1); });
