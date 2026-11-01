/* Service worker: deixa o app abrir sem internet e mostrar a última busca salva no aparelho. */
const VERSAO = "imv-1.4.0";
const FIXOS = ["/manifest.webmanifest", "/icone.svg", "/icone-192.png", "/icone-512.png", "/apple-touch-icon.png"];
const API_COM_CACHE = ["/api/imoveis", "/api/opcoes", "/api/imobiliarias", "/api/buscas", "/api/alertas"];
const ULTIMA = "/__ultima_busca__";

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSAO).then(c => c.addAll(FIXOS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VERSAO).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

// A página manda "limpar" ao sair da conta, para não deixar anúncios guardados no aparelho.
self.addEventListener("message", e => {
  if (e.data === "limpar") e.waitUntil(caches.keys().then(ks => Promise.all(ks.map(k => caches.delete(k)))));
});

function marcaOffline(resp) {
  const h = new Headers(resp.headers);
  h.set("x-offline", "1");
  return resp.clone().blob().then(b => new Response(b, {status: resp.status, statusText: resp.statusText, headers: h}));
}

self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;

  // Páginas: rede primeiro; guarda a última resposta boa de "/" para abrir sem internet.
  if (req.mode === "navigate") {
    e.respondWith((async () => {
      try {
        const r = await fetch(req);
        if (url.pathname === "/" && r.ok && !r.redirected) (await caches.open(VERSAO)).put("/", r.clone());
        return r;
      } catch (_) {
        const c = url.pathname === "/" ? await caches.match("/") : null;
        return c || new Response("Sem conexão. Abra o app quando estiver online.", {status: 503, headers: {"content-type": "text/plain; charset=utf-8"}});
      }
    })());
    return;
  }

  // Dados: rede primeiro; sem internet, devolve a mesma consulta ou a última busca salva.
  if (API_COM_CACHE.includes(url.pathname)) {
    e.respondWith((async () => {
      const cache = await caches.open(VERSAO);
      try {
        const r = await fetch(req);
        if (r.ok) {
          cache.put(req, r.clone());
          if (url.pathname === "/api/imoveis") cache.put(ULTIMA, r.clone());
        }
        return r;
      } catch (_) {
        const c = await cache.match(req) || (url.pathname === "/api/imoveis" ? await cache.match(ULTIMA) : null);
        if (c) return marcaOffline(c);
        return new Response(JSON.stringify({erro: "Sem conexão e sem dados salvos."}), {status: 503, headers: {"content-type": "application/json"}});
      }
    })());
    return;
  }

  // Ícones e manifesto: cache primeiro.
  if (FIXOS.includes(url.pathname)) {
    e.respondWith(caches.match(req).then(c => c || fetch(req)));
  }
});
