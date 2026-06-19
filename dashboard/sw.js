/* ============================================================
   QuantTradingSystem — Service Worker v1.0
   策略：Cache-First for static assets, Network-First for API calls
   ============================================================ */

const CACHE_NAME = 'quant-dashboard-v1';
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/favicon.svg',
  '/manifest.json',
  '/design-tokens.css',
  '/style.css',
  '/app.js',
  '/app.spa.js',
  '/js/index-ws.js',
  '/js/index-particle.js',
  'https://cdn.jsdelivr.net/npm/vue@3.3.4/dist/vue.global.prod.js',
  'https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js'
];

// ─── Install: precache static shell ───
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(STATIC_ASSETS);
    }).then(() => self.skipWaiting())
  );
});

// ─── Activate: cleanup old caches ───
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      );
    }).then(() => self.clients.claim())
  );
});

// ─── Fetch: cache-first for static, network-first for API ───
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // API calls → Network First
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // CDN resources → Cache First (immutable)
  if (url.hostname === 'cdn.jsdelivr.net') {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  // Local assets (js, css, png, svg, etc.) → Cache First
  if (url.origin === self.location.origin &&
      !url.pathname.startsWith('/api/')) {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  // Everything else → Network First
  event.respondWith(networkFirst(event.request));
});

// ─── Strategies ───

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    return new Response('Offline', { status: 503 });
  }
}

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) return cached;
    // Offline fallback for navigation requests
    if (request.mode === 'navigate') {
      return caches.match('/');
    }
    return new Response(JSON.stringify({ error: 'offline' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}
