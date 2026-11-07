/* Clasvanta 2.8.3 — public assets only. NEVER cache attendance or private pages. */
'use strict';
const CACHE_NAME = 'clasvanta-static-v2.8.3';
const CACHE_PREFIX = 'clasvanta-static-';
const OFFLINE = '/offline/';
const PRECACHE = [
  OFFLINE, '/static/pwa/icon-192.png', '/static/pwa/icon-512.png',
  '/static/pwa/icon-maskable-512.png', '/static/pwa/apple-touch-icon.png',
  '/static/pwa/pwa.css'
];
self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    await Promise.allSettled(PRECACHE.map(url => cache.add(url)));
    await self.skipWaiting();
  })());
});
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(name => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME).map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});
self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (req.mode === 'navigate') {
    event.respondWith((async () => {
      try { return await fetch(req); }
      catch (_) {
        return (await caches.match(OFFLINE)) || new Response(
          '<!doctype html><title>Offline</title><h1>Connection unavailable</h1><p>Reconnect to continue using Clasvanta.</p>',
          {status: 503, headers: {'Content-Type': 'text/html; charset=utf-8'}}
        );
      }
    })());
    return;
  }
  if (url.pathname.startsWith('/static/')) {
    event.respondWith((async () => {
      try {
        const response = await fetch(req);
        if (response.ok && response.type === 'basic') {
          const cache = await caches.open(CACHE_NAME);
          await cache.put(req, response.clone());
        }
        return response;
      } catch (_) {
        return (await caches.match(req)) || Response.error();
      }
    })());
  }
});
