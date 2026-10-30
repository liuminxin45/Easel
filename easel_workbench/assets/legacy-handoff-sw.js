// Retire the old root worker without touching drafts, attachments, or receipts.
'use strict';
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET' || request.mode !== 'navigate') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  const oldEntry = url.pathname === '/' || /^\/(?:toolbox|chat|news|posters|articles|works|settings|messages|account|workbench|apps|wiki)(?:\/|$)/.test(url.pathname);
  if (!oldEntry) return;
  const target = new URL('/native/', self.location.origin);
  if (url.pathname !== '/' || url.search) target.searchParams.set('path', url.pathname + url.search);
  event.respondWith(Promise.resolve(Response.redirect(target.href, 303)));
});
