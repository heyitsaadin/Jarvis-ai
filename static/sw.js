const CACHE = 'jarvis-v1';
const STATIC = [
  '/login',
  '/landing',
  '/signup',
  '/static/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Always fetch API calls live, never cache them
  const isApi = url.pathname.startsWith('/api/') ||
                url.pathname.startsWith('/chat') ||
                url.pathname.startsWith('/quiz') ||
                url.pathname.startsWith('/website');

  if (isApi) {
    e.respondWith(
      fetch(e.request).catch(() =>
        new Response('{"error":"offline"}', {
          headers: { 'Content-Type': 'application/json' }
        })
      )
    );
    return;
  }

  // For everything else: cache first, fall back to network
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});
