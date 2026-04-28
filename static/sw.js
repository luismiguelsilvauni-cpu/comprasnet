const CACHE = 'comprasnet-v2';
const ICONS = [
  '/icon-192.png', '/icon-512.png', '/favicon.ico',
  '/static/icon-192.png', '/static/icon-512.png'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => {
      return Promise.allSettled(ICONS.map(url => 
        c.add(url).catch(() => null)
      ));
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => 
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // Cache-first for icons
  if (url.pathname.match(/\.(png|ico|svg)$/)) {
    e.respondWith(
      caches.match(e.request).then(cached => 
        cached || fetch(e.request).then(resp => {
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
          return resp;
        })
      )
    );
    return;
  }
  // Network-first for pages
  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).catch(() => caches.match('/dashboard')));
  }
});
