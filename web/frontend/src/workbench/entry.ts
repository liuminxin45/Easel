// Keep startup recovery independent of React and the application's large chunks.
export {};
// Retired root-scope workers still intercept navigation with the old recovery
// shell. Remove only that registration, retaining drafts and caches.
if (typeof navigator !== 'undefined' && 'serviceWorker' in navigator) {
  void navigator.serviceWorker.getRegistrations().then(registrations => Promise.all(
    registrations.filter(registration => {
      const worker = registration.active || registration.waiting || registration.installing;
      return registration.scope === location.origin + '/' && worker
        && new URL(worker.scriptURL).pathname === '/sw.js';
    }).map(registration => registration.unregister()),
  )).catch(() => { /* Startup remains available when worker inspection is denied. */ });
}
const getBootStatus = () => document.getElementById('native-boot-status');
const timer = setTimeout(() => {
  const node = getBootStatus();
  if (node) node.textContent = '工作台启动资源加载较慢，请检查连接后重新打开。草稿仍保留在此设备上。';
}, 15000);
void import('./main').then(() => clearTimeout(timer), () => {
  clearTimeout(timer);
  const node = getBootStatus();
  if (node) node.textContent = '工作台启动资源加载失败，请检查网络后重新打开；登录失效时可重新登录。草稿仍保留在此设备上。';
});
