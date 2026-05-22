// MVBC Library card — service worker.
//
// Cache-first for the patron's own card page so it works at the kiosk
// even if the church wifi drops. The page is fully self-contained
// (inline CSS + base64 QR), so caching the HTML is enough — no
// additional asset URLs to enumerate.

const CACHE = 'mvbc-card-v1';

self.addEventListener('install', (e) => {
  // Activate immediately so the first load (which registered us) starts
  // benefiting from the cache on its next visit.
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;

  e.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req).then((resp) => {
        // Only cache successful same-origin responses.
        if (resp && resp.ok && new URL(req.url).origin === self.location.origin) {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return resp;
      }).catch(() => cached);
    })
  );
});
