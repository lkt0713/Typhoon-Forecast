
const VER = '9884c794';
const SHELL = 'tc-shell-' + VER;
const ASSETS = 'tc-assets';
const MAX_ASSETS = 400;
const ASSET_HOSTS = ['fonts.googleapis.com', 'fonts.gstatic.com', 'cdn.jsdelivr.net', 'unpkg.com'];
self.addEventListener('install', e => {
    e.waitUntil(caches.open(SHELL).then(c => c.addAll(['./', 'site.css?v=' + VER, 'site.js?v=' + VER]).catch(() => null)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
    e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k.startsWith('tc-shell-') && k !== SHELL).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
async function trim(name, max) {
    const c = await caches.open(name), keys = await c.keys();
    for (let i = 0; i < keys.length - max; i++) await c.delete(keys[i]);
}
async function networkFirst(req, cacheName) {
    const c = await caches.open(cacheName);
    try {
        const r = await fetch(req);
        if (r.ok) c.put(req, r.clone());
        return r;
    } catch (e) {
        const hit = await c.match(req, { ignoreSearch: req.mode === 'navigate' });
        if (hit) return hit;
        if (req.mode === 'navigate') { const idx = await c.match('./'); if (idx) return idx; }
        throw e;
    }
}
async function staleWhileRevalidate(req) {
    const c = await caches.open(ASSETS);
    const hit = await c.match(req);
    const fetching = fetch(req).then(r => { if (r.ok || r.type === 'opaque') { c.put(req, r.clone()); trim(ASSETS, MAX_ASSETS); } return r; }).catch(() => null);
    return hit || (await fetching) || Response.error();
}
self.addEventListener('fetch', e => {
    const req = e.request;
    if (req.method !== 'GET') return;
    const url = new URL(req.url);
    const same = url.origin === self.location.origin;
    if (same && /status\.json$/.test(url.pathname)) return;                         // 頁面輪詢更新用，不快取
    if (req.mode === 'navigate') { e.respondWith(networkFirst(req, SHELL)); return; }
    if (same && /\.(html|json|geojson|csv)$/.test(url.pathname)) { e.respondWith(networkFirst(req, SHELL)); return; }
    if (same && /\.(css|js)$/.test(url.pathname)) { e.respondWith(networkFirst(req, SHELL)); return; }
    if (same && /\.(png|webp|jpg|jpeg|gif|svg|woff2?)$/.test(url.pathname)) { e.respondWith(staleWhileRevalidate(req)); return; }
    if (!same && ASSET_HOSTS.includes(url.hostname)) { e.respondWith(staleWhileRevalidate(req)); return; }
});
