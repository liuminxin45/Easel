// Keep startup recovery independent of React and the application's large chunks.
import {retireLegacyWorker} from './retireLegacyWorker';
const boot=(window as Window & {__wbBoot?:{entry?:number;module?:number}}).__wbBoot;
if(boot)boot.entry=performance.now();
void retireLegacyWorker();
const getBootStatus = () => document.getElementById('native-boot-status');
const timer = setTimeout(() => {
  const node = getBootStatus();
  if (node) node.textContent = '工作台启动资源加载较慢，请检查连接后重新打开。草稿仍保留在此设备上。';
}, 15000);
void import('./main').then(() => {if(boot)boot.module=performance.now();clearTimeout(timer)}, () => {
  clearTimeout(timer);
  try{const details=window.__wbBoot;if(details)details.failed=true;sessionStorage.setItem('workbench:performance:unfinished',JSON.stringify({at:Date.now(),release:details?.release||'',trace:details?.trace||'',hidden:!!details?.hidden,outcome:'failed',duration_ms:Math.round(performance.now())}))}catch{}
  const node = getBootStatus();
  if (node) node.textContent = '工作台启动资源加载失败，请检查网络后重新打开；登录失效时可重新登录。草稿仍保留在此设备上。';
});
