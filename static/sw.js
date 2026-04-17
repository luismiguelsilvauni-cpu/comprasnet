const CACHE_NAME = 'comprasnet-v202604171551';
const OFFLINE_URLS = [
  '/mobile',
  '/static/manifest.json',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(OFFLINE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  // Network first, fallback to cache
  event.respondWith(
    fetch(event.request)
      .catch(() => caches.match(event.request))
  );
});
