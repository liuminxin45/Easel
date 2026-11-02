import {safePath,type NavigationService} from './navigation';
import {COMPACT_LAYOUT_QUERY} from './profile';
export function authenticationUrl(navigation:Pick<NavigationService,'publicUrl'>,next:string):string{
 const target=navigation.publicUrl(safePath(next)||'/toolbox');return (target.startsWith('/native/')?'/native/login':'/login')+'?'+new URLSearchParams({next:target});
}
/** Classify documents without turning external URLs into application routes. */
export function mobileDocumentLink(href:string,origin:string):boolean {
 try{const url=new URL(href,origin);return /^https?:$/.test(url.protocol)&&(url.origin!==origin||/^\/(?:api\/(?:files|media|outputs|chat\/products)(?:\/|$)|media\/)/.test(url.pathname))}catch{return false}
}
export interface ImageLink {url:string;name:string;downloadUrl?:string;kind?:'image'|'file'}
export function bindNavigationLinks(navigation:NavigationService,openImage?:(image:ImageLink)=>void):()=>void {
 const adapt=()=>{for(const anchor of document.querySelectorAll<HTMLAnchorElement>('#root a[href]')){
  const raw=anchor.getAttribute('href');delete anchor.dataset.nativePath;if(!raw||raw.startsWith('#/outputs/')||anchor.hasAttribute('download'))continue;
  try{const url=new URL(raw,location.href);if(url.origin!==location.origin)continue;if(url.pathname==='/login'&&navigation.publicUrl('/toolbox').startsWith('/native/')){delete anchor.dataset.nativePath;anchor.setAttribute('href',authenticationUrl(navigation,url.searchParams.get('next')||navigation.snapshot().path));continue}const path=safePath(url.pathname+url.search,location.origin);if(!path)continue;anchor.dataset.nativePath=path;const actual=navigation.publicUrl(path);if(raw!==actual)anchor.setAttribute('href',actual)}catch{/* External and non-HTTP links keep their platform behavior. */}
 }};
 const click=(event:MouseEvent)=>{
  if(event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
  const anchor=event.target instanceof Element?event.target.closest<HTMLAnchorElement>('#root a[href]'):null;
  if(!anchor||anchor.hasAttribute('download')||anchor.target&&!['_self','_blank'].includes(anchor.target))return;
   const compact=matchMedia(COMPACT_LAYOUT_QUERY).matches;
  const image=anchor.querySelector<HTMLImageElement>('img')||anchor.closest('.artifact-gallery')?.querySelector<HTMLImageElement>('.artifact-image-link img');
  if(openImage&&image&&image.src===anchor.href&&new URL(anchor.href).origin===location.origin){
   const download=anchor.closest('.artifact-gallery')?.querySelector<HTMLAnchorElement>('a[download]');
   const downloadUrl=download?.href&&new URL(download.href).origin===location.origin?download.href:undefined;
   event.preventDefault();event.stopPropagation();openImage({url:anchor.href,name:image.alt||'图片',downloadUrl});return;
  }
  const path=anchor.dataset.nativePath;
  if(path&&(!anchor.target||anchor.target==='_self'||compact)){event.preventDefault();event.stopPropagation();navigation.navigate(path);return}
  if(compact&&mobileDocumentLink(anchor.href,location.origin)){
   const target=new URL(anchor.href,location.origin);
   if(target.origin===location.origin&&openImage){
    const name=anchor.closest('.artifact-gallery')?.querySelector('.artifact-name')?.textContent?.trim()||anchor.textContent?.trim()||decodeURIComponent(target.pathname.split('/').at(-1)||'文档');
    event.preventDefault();event.stopPropagation();openImage({url:anchor.href,name,kind:'file'});return;
   }
   // Keep the workbench alive. Let the browser/WebView open a separate context
   // instead of unconditionally replacing this document with location.assign.
   anchor.target='_blank';anchor.rel='noopener noreferrer';
  }
 };
 const observer=new MutationObserver(adapt);observer.observe(document.getElementById('root')||document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['href']});adapt();document.addEventListener('click',click,true);return()=>{observer.disconnect();document.removeEventListener('click',click,true)};
}
