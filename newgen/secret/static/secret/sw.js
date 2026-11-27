/*
 * anylink service worker.
 *
 * Chrome only offers "Install app" when a page has a manifest and a service
 * worker with a fetch handler, so this one exists mostly to satisfy that. It
 * deliberately caches nothing: a support chat must never show a stale screen
 * or an old stylesheet, and every page needs the server anyway.
 */
self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  event.respondWith(fetch(event.request));
});
