// Only an empty legacy startup shell can leave automatically. Existing input
// stays on screen until its owner chooses the new entry.
'use strict';
(() => {
  if (location.pathname === '/native' || location.pathname.startsWith('/native/')) return;
  const target = new URL('/native/', location.origin);
  if (location.pathname !== '/' || location.search) target.searchParams.set('path', location.pathname + location.search);
  target.hash = location.hash;
  if ('serviceWorker' in navigator) {
    void navigator.serviceWorker.getRegistration('/').then(registration => {
      const worker = registration?.active || registration?.waiting || registration?.installing;
      if (worker && new URL(worker.scriptURL).pathname === '/sw.js') return registration.update();
    }).catch(() => {});
  }
  const root = document.getElementById('root');
  const placeholder = root && (root.childNodes.length === 0 ||
    (root.childElementCount === 1 && root.firstElementChild.matches('[data-toolbox-boot-status]')));
  const hasEditor = document.querySelector('input, textarea, select, [contenteditable]:not([contenteditable="false"])');
  if (placeholder && !hasEditor) {
    location.replace(target.href);
    return;
  }
  if (document.querySelector('[data-legacy-handoff]')) return;
  const notice = document.createElement('p');
  notice.dataset.legacyHandoff = '';
  notice.setAttribute('role', 'status');
  notice.append('工作台已更新。请先保留当前输入，再打开新版。草稿和附件仍保留在此设备上。 ');
  const link = document.createElement('a');
  link.href = target.href;
  link.textContent = '打开新版工作台';
  notice.append(link);
  document.body.append(notice);
})();
