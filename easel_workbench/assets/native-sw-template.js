async function saveShell(response){
 if(!response.ok||response.redirected)return false;
 const html=await response.clone().text();
 if(!html.includes('name="native-release" content="'+VERSION+'"'))return false;
 await (await caches.open(SHELL)).put('/native/',response.clone());return true;
}
async function warmShell(){try{return await saveShell(await fetch('/native/',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(8000)}))}catch{return false}}
async function retainedShell(){
 const names=await caches.keys(),ordered=[SHELL,...names.filter(n=>n.startsWith('native-shell-')&&n!==SHELL).reverse()];
 for(const name of ordered){if(!names.includes(name))continue;const response=await (await caches.open(name)).match('/native/');if(response)return response}
}
async function prune(){
 const names=await caches.keys(),prior=names.filter(n=>n.startsWith('native-shell-')&&n!==SHELL),keep=new Set([VERSION,...prior.slice(-2).map(n=>n.slice('native-shell-'.length))]);
 // A retained old shell still needs its own immutable scripts and styles.
 for(const name of names){const prefix=name.startsWith('native-static-')?'native-static-':name.startsWith('native-shell-')?'native-shell-':null;if(prefix&&!keep.has(name.slice(prefix.length)))await caches.delete(name)}
}
self.addEventListener('install',event=>event.waitUntil((async()=>{const cache=await caches.open(CACHE);await cache.addAll(ASSETS);await warmShell();await self.skipWaiting()})()));
self.addEventListener('activate',event=>event.waitUntil((async()=>{await warmShell();await prune();await self.clients.claim()})()));
self.addEventListener('message',event=>{if(event.data?.type==='CACHE_SHELL')event.waitUntil(warmShell())});
self.addEventListener('fetch',event=>{
 const request=event.request,url=new URL(request.url);
 if(request.method!=='GET'||url.origin!==self.location.origin||url.pathname.startsWith('/api/')||url.pathname.includes('/login'))return;
 if(ASSETS.includes(url.pathname)){
  event.respondWith((async()=>{const cache=await caches.open(CACHE),saved=await cache.match(request);if(saved)return saved;const response=await fetch(request);if(response.ok)await cache.put(request,response.clone());return response})());return;
 }
 if(request.mode==='navigate'&&(url.pathname==='/native/'||url.pathname==='/native'))event.respondWith((async()=>{
  try{const response=await fetch(request);if(response.status<500){if(response.ok&&!response.redirected)event.waitUntil(saveShell(response.clone()));return response}}catch{}
  const saved=await retainedShell();if(saved)return saved;
  return new Response('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>连接工作台</title><h1>暂时无法连接</h1><p>草稿仍保留在这台设备上。连接恢复后会自动重试。</p><p id="connection-status" role="status"></p><button id="reconnect" type="button">重新连接</button><p><a href="/native/login?next=%2Fnative%2F">从登录入口重新打开</a></p><script defer src="/native-assets/'+VERSION+'/reconnect.js"></script></html>',{status:503,headers:{'Content-Type':'text/html; charset=utf-8','Content-Security-Policy':"default-src 'none'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",'Cache-Control':'no-store'}});
 })());
});
