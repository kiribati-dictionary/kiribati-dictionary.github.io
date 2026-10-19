// Service worker: makes the whole dictionary work offline after the first visit.
// scripts/build_site.py fills in VERSION (a hash of the build) and PRECACHE.
//
// - On install, saves the small pages, the search indexes and the entry bundle.
// - Serves from the cache first, then the network; pages fetched online are cached too.
// - Offline, an entry or English page that isn't cached is drawn by offline.html
//   from bundle/ or english.json.
// - A new build has a new VERSION, so the old cache is replaced.

const VERSION = "kd-__VERSION__";
const PRECACHE = __PRECACHE__;
const ROOT = self.registration.scope;

self.addEventListener("install", event => {
  event.waitUntil(caches.open(VERSION).then(c => c.addAll(PRECACHE.map(p => new URL(p, ROOT)))).then(() => self.skipWaiting()));
});

self.addEventListener("activate", event => {
  event.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k.startsWith("kd-") && k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

async function shell() {
  const res = await caches.match(new URL("offline.html", ROOT));
  if (!res) return Response.error();
  const page = (await res.text()).replace("<head>", `<head>\n<base href="${ROOT}">`);
  return new Response(page, { headers: { "Content-Type": "text/html; charset=utf-8" } });
}

self.addEventListener("fetch", event => {
  const req = event.request;
  if (req.method !== "GET" || !req.url.startsWith(ROOT)) return;
  const navigate = req.mode === "navigate";
  event.respondWith((async () => {
    const cache = await caches.open(VERSION);
    const hit = await cache.match(req, { ignoreSearch: navigate });
    if (hit) return hit;
    try {
      const res = await fetch(req);
      if (res.ok && res.type === "basic") cache.put(req, res.clone());
      return res;
    } catch (err) {
      if (navigate) return shell();
      throw err;
    }
  })());
});
