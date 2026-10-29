import type {ActivityDelegate} from './models';
export interface AuthOptions {fetcher?:typeof fetch;activities?:ActivityDelegate;origin?:string}
const safeNext=(next:string):string=>{try{const decoded=decodeURIComponent(next);return next.startsWith('/')&&!decoded.startsWith('//')&&!/[\\#\r\n\u0000-\u001f]/.test(decoded)&&!/^\/(login|logout|logout-all)(\?|$)/.test(decoded)?next:'/toolbox'}catch{return'/toolbox'}};
/** Fetched forms stay inert; a fresh response's nonce never enters the live page. */
export function parseAuthSnapshot(html:string):DocumentFragment{const template=document.createElement('template');template.innerHTML=html;return template.content}
export class AuthService {
  private sending=false;private fetcher:typeof fetch;
  constructor(private options:AuthOptions={}){this.fetcher=options.fetcher??((...args)=>globalThis.fetch(...args))}
  async login(code:string,next='/toolbox'):Promise<string>{
    if(this.sending)throw Error('登录请求正在处理中。');if(!/^\d{6}$/.test(code))throw Error('请输入6位验证码。');this.sending=true;
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000),release=this.options.activities?.begin('write');
    try{
      const target=safeNext(next),options:RequestInit={credentials:'same-origin',cache:'no-store',signal:controller.signal};
      const challenge=await this.fetcher('/login?'+new URLSearchParams({next:target}),options);if(!challenge.ok)throw Error('登录校验暂时无法更新，请稍后重试。');
      const origin=this.options.origin??location.origin,already=new URL(challenge.url||'/login',origin);
      if(challenge.redirected&&already.origin===origin&&already.pathname!=='/login')return already.pathname+already.search;
      const csrf=parseAuthSnapshot(await challenge.text()).querySelector<HTMLInputElement>('input[name="csrf"]')?.value;if(!csrf)throw Error('登录校验未能更新，请刷新后重试。');
      const response=await this.fetcher('/login',{...options,method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({csrf,next:target,code})});
      const url=new URL(response.url||'/login',origin);
      if(response.ok&&response.redirected&&url.origin===origin&&url.pathname!=='/login')return url.pathname+url.search;
      const detail=parseAuthSnapshot(await response.text()).querySelector('[role="alert"]')?.textContent?.trim();
      throw Error(detail||(response.status===429?'尝试过多，请稍后重试。':response.status===403?'登录校验未通过，请刷新后重试。':'登录未完成，请核对验证码。'));
    }catch(error){if(error instanceof Error&&error.name==='AbortError')throw Error('登录响应超时，验证码没有自动重发。');if(error instanceof TypeError)throw Error('连接失败，请检查网络后重试。');throw error}
    finally{clearTimeout(timer);release?.();this.sending=false}
  }
  async logout(csrf:string,allSessions=false):Promise<string>{
    const response=await this.fetcher(allSessions?'/logout-all':'/logout',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({csrf})});
    const origin=this.options.origin??location.origin,url=new URL(response.url||'/login',origin);if(!response.ok||url.origin!==origin)throw Error('退出未完成，请重试。');return url.pathname+url.search;
  }
}
