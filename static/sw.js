const CACHE = 'comprasnet-v5';

self.addEventListener('install', e => {
  e.waitUntil(self.skipWaiting());
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
  // Icons and manifest: always network — never cache so regen takes effect immediately
  if (url.pathname.match(/\.(png|ico)$/) || url.pathname === '/manifest.json') {
    return; // let browser handle normally
  }
  // Navigation: network first, no fallback needed for a LAN app
  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).catch(() => caches.match('/dashboard')));
  }
});
