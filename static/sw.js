const CACHE = 'comprasnet-v3';
const PRECACHE = [
  '/icon-192.png',
  '/icon-512.png', 
  '/icon-maskable-192.png',
  '/icon-maskable-512.png',
  '/favicon.ico',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c =>
      Promise.allSettled(PRECACHE.map(url => c.add(url).catch(()=>null)))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => clients.claim())
  );
});

self.addEventListener('message', e => {
  if (e.data && e.data.action === 'clearCache') {
    caches.keys().then(keys => keys.forEach(k => caches.delete(k)));
  }
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // Serve icons from cache
  if (url.pathname.match(/\.(png|ico)$/)) {
    e.respondWith(
      caches.match(e.request).then(cached =>
        cached || fetch(e.request).then(resp => {
          if (resp.ok) {
            caches.open(CACHE).then(c => c.put(e.request, resp.clone()));
          }
          return resp;
        })
      )
    );
    return;
  }
  // For navigation: network first
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).catch(() => caches.match('/dashboard'))
    );
  }
});
