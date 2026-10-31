// Retire only the old root navigation worker. Cached drafts/attachments and
// the native scoped worker belong to the device and are never cleared here.
export async function retireLegacyWorker(): Promise<void> {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return;
  try {
    const registrations = await navigator.serviceWorker.getRegistrations();
    await Promise.all(registrations.map(async registration => {
      const worker = registration.active || registration.waiting || registration.installing;
      if (registration.scope !== location.origin + '/' || !worker) return;
      const script = new URL(worker.scriptURL);
      if (script.origin === location.origin && script.pathname === '/sw.js') await registration.unregister();
    }));
  } catch { /* A denied worker inspection must not prevent login or startup. */ }
}
