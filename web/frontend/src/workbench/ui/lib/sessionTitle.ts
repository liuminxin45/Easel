import {generateSessionTitle as nativeTitle} from '../../../lib/store';

/** Preserve native naming; only fill its pure-URL placeholder in the private host. */
export function generateSessionTitle(message:string):string{
 const title=nativeTitle(message);if(title!=='新对话'&&!/^[<>()[\]\s]+$/.test(title))return title;
 const urls=message.match(/https?:\/\/[^\s<>]+/g)||[];
 if(!urls.length||message.replace(/https?:\/\/[^\s<>]+/g,'').replace(/[\s<>()[\]，。；,;]+/g,''))return title;
 try{
  const url=new URL(urls[0]!.replace(/[，。；,;)]+$/g,''));
  const host=url.hostname.toLowerCase();
  const parts=url.pathname.split('/').filter(Boolean).map(part=>decodeURIComponent(part));
  let value=host==='github.com'&&parts.length>=2?parts.slice(0,2).join('/'):host==='mp.weixin.qq.com'?'微信公众号文章':host;
  if(host!=='github.com'&&host!=='mp.weixin.qq.com'){
   const last=parts.at(-1)||'';
   if(last&&!/^[a-zA-Z0-9_-]{16,}$/.test(last))value+=' · '+last;
  }
  value=value.replace(/[\u0000-\u001f\u007f]/g,'').trim();
  const chars=Array.from(value);return chars.length>40?chars.slice(0,40).join('')+'…':value||title;
 }catch{return title}
}
