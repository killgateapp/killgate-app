const CACHE_PREFIX = "killgate-";
const CACHE_VERSION = "killgate-v1.2.0-play-store-visuals-5";
const APP_SHELL = [
  "/offline",
  "/manifest.webmanifest",
  "/static/app.css",
  "/static/app.js",
  "/static/icons/killgate-mark.svg",
  "/static/icons/killgate-store-512.png",
  "/static/icons/killgate-192.png",
  "/static/icons/killgate-512.png",
  "/static/icons/killgate-maskable-512.png",
  "/static/brand/hero-atmosphere.jpg",
  "/static/brand/killgate-play-store-feature.png",
  "/static/brand/offline-room.jpg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_VERSION).then((cache) => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_VERSION)
          .map((key) => caches.delete(key)),
      ))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .catch(async () => (await caches.match(request)) || (await caches.match("/offline"))),
    );
    return;
  }

  if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest") {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              event.waitUntil(
                caches
                  .open(CACHE_VERSION)
                  .then((cache) => cache.put(request, copy))
                  .catch(() => undefined),
              );
            }
            return response;
          }),
      ),
    );
  }
});
