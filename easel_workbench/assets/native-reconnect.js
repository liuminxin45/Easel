// Recovery reads the protected shell only. It never submits or replays a task.
let connecting=false,attempts=0,timer;
async function reconnect(){
 if(connecting||document.hidden)return;connecting=true;clearTimeout(timer);
 const button=document.getElementById('reconnect'),status=document.getElementById('connection-status');
 if(button)button.disabled=true;if(status)status.textContent='正在重新连接…';
 try{
  const probe=new URL(location.href);probe.searchParams.set('reconnect','1');
  const response=await fetch(probe,{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(5000)});
  if(response.ok){location.reload();return}
 }catch{}
 finally{connecting=false;if(button)button.disabled=false}
 if(status)status.textContent='连接尚未恢复，原字草稿仍保留。';
 if(++attempts<6)timer=setTimeout(()=>void reconnect(),10000);
}
document.getElementById('reconnect')?.addEventListener('click',()=>{attempts=0;void reconnect()});
window.addEventListener('online',()=>{attempts=0;void reconnect()});
window.addEventListener('focus',()=>void reconnect());
void reconnect();
