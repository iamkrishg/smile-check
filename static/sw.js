// Smile Check service worker: makes the site installable as an app and
// shows the page (from cache) even when the connection drops.
// Photo checks always go to the server and are never cached.
const CACHE = "smile-check-v1";
const SHELL = [
  "/", "/static/manifest.webmanifest",
  "/static/icons/icon-192.png", "/static/icons/icon-512.png",
  "/static/fonts/baloo-2-latin-700-normal.woff2", "/static/fonts/baloo-2-latin-800-normal.woff2",
  "/static/fonts/atkinson-hyperlegible-latin-400-normal.woff2", "/static/fonts/atkinson-hyperlegible-latin-700-normal.woff2"
];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/")) return; // never cache photo checks
  // network first, fall back to cache when offline
  e.respondWith(
    fetch(e.request).then(res => {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(e.request, copy));
      return res;
    }).catch(() => caches.match(e.request))
  );
});
