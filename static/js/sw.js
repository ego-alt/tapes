// Offline support for Tapes.
//
// One cache, "shell": the page, our static files (fonts included), covers and the JSON
// lists (shelves, tapes, albums, artists, shows, episodes). Pages and JSON are
// network-first (fresh online, last copy offline); static files are
// stale-while-revalidate. Audio is never cached here: streams use Range
// requests and can be huge. Offline listening is a roadmap item.
//
// Served from the app root (see routes/pwa.py), so the scope is the whole
// mount: "/" standalone, "/music/" behind the dashboard proxy.

const SHELL_CACHE = 'tapes-shell-v14';
const ROOT = new URL(self.registration.scope).pathname;   // always ends in "/"

// Never touched: audio, the live rip stream, auth, health and the worker.
const PASSTHROUGH = ['stream/', 'podcast/stream/', 'api/downloads', 'auth/', 'login', 'logout',
                     'healthz', 'sw.js'];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(SHELL_CACHE)
            .then((cache) => Promise.all([ROOT, `${ROOT}manifest.webmanifest`]
                .map((url) => cache.add(url).catch(() => {}))))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(keys.filter((k) => k !== SHELL_CACHE).map((k) => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (event) => {
    const request = event.request;
    if (request.method !== 'GET' || request.headers.has('range')) return;
    const url = new URL(request.url);

    if (url.origin !== self.location.origin || !url.pathname.startsWith(ROOT)) return;
    const path = url.pathname.slice(ROOT.length);
    if (PASSTHROUGH.some((p) => path.startsWith(p))) return;

    if (request.mode === 'navigate') {
        event.respondWith(networkFirst(request, ROOT));
    } else if (path.startsWith('api/')) {
        event.respondWith(networkFirst(request));
    } else if (path.startsWith('static/') || path.startsWith('cover/') || path.startsWith('podcast/cover/')
               || path === 'manifest.webmanifest' || path === 'favicon.ico') {
        event.respondWith(staleWhileRevalidate(request));
    }
});

// Fresh from the network; the cached copy only when the network fails.
// Non-OK replies (e.g. the dashboard asking you to sign in) pass through.
async function networkFirst(request, fallbackUrl) {
    const cache = await caches.open(SHELL_CACHE);
    try {
        const response = await fetch(request);
        if (response.ok) cache.put(request, response.clone());
        return response;
    } catch (err) {
        const cached = await cache.match(request) || (fallbackUrl && await cache.match(fallbackUrl));
        if (cached) return cached;
        throw err;
    }
}

async function staleWhileRevalidate(request) {
    const cache = await caches.open(SHELL_CACHE);
    const cached = await cache.match(request);
    const network = fetch(request).then((response) => {
        if (response.ok) cache.put(request, response.clone());
        return response;
    }).catch(() => cached);
    return cached || network;
}
