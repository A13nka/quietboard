// Network-first; bei Netzausfall den letzten Stand aus dem Cache zeigen.
// '/' und /api/state erst nach erfolgreichem Laden cachen – ohne Anmeldung ist '/' eine Weiterleitung zum Login.
// Antworten aus dem Cache tragen X-QB-Offline: 1 – die Oberfläche zeigt dann „offline – Stand vom …“.
const CACHE = 'status-v4';
const SHELL = ['/manifest.webmanifest', '/static/icon.svg', '/static/icon-192.png', '/static/i18n.js'];
const RUNTIME = ['/', '/api/state'];
self.addEventListener('install', e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener('activate', e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;
  e.respondWith(fetch(req).then(res => {
    const path = new URL(req.url).pathname;
    if (res.ok && !res.redirected && (RUNTIME.includes(path) || SHELL.includes(path))) {
      const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy));
    }
    return res;
  }).catch(() => caches.match(req).then(res => {
    if (!res) return Response.error();
    const h = new Headers(res.headers); h.set('X-QB-Offline', '1');
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers: h });
  })));
});
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { title: e.data ? e.data.text() : '' }; }
  e.waitUntil(self.registration.showNotification(d.title || 'QuietBoard', {
    body: d.body || '', tag: d.tag || undefined, data: { url: d.url || '/' },
    icon: '/static/icon-192.png', badge: '/static/icon-192.png' }));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(ws => {
    for (const w of ws) if ('focus' in w) return w.focus().then(c => (c && c.navigate) ? c.navigate(url) : c);
    return self.clients.openWindow(url);
  }));
});
