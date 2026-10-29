import {safePath,type NavigationService} from './navigation';
export function authenticationUrl(navigation:Pick<NavigationService,'publicUrl'>,next:string):string{
 const target=navigation.publicUrl(safePath(next)||'/toolbox');return (target.startsWith('/native/')?'/native/login':'/login')+'?'+new URLSearchParams({next:target});
}
/** Keep ordinary links, modified-click and new tabs inside the candidate entry. */
export function bindNavigationLinks(navigation:NavigationService):()=>void {
 const adapt=()=>{for(const anchor of document.querySelectorAll<HTMLAnchorElement>('#root a[href]')){
  const raw=anchor.getAttribute('href');if(!raw||anchor.hasAttribute('download')||raw.startsWith('/native/'))continue;
  try{const url=new URL(raw,location.href);if(url.origin!==location.origin)continue;if(url.pathname==='/login'&&navigation.publicUrl('/toolbox').startsWith('/native/')){delete anchor.dataset.nativePath;anchor.setAttribute('href',authenticationUrl(navigation,url.searchParams.get('next')||navigation.snapshot().path));continue}const path=safePath(url.pathname+url.search,location.origin);if(!path)continue;anchor.dataset.nativePath=path;const actual=navigation.publicUrl(path);if(raw!==actual)anchor.setAttribute('href',actual)}catch{/* External and non-HTTP links keep their platform behavior. */}
 }};
 const click=(event:MouseEvent)=>{if(event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;const anchor=event.target instanceof Element?event.target.closest<HTMLAnchorElement>('a[data-native-path]'):null;if(!anchor||anchor.download||anchor.target&&anchor.target!=='_self')return;const path=anchor.dataset.nativePath;if(!path)return;event.preventDefault();event.stopPropagation();navigation.navigate(path)};
 const observer=new MutationObserver(adapt);observer.observe(document.getElementById('root')||document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['href']});adapt();document.addEventListener('click',click,true);return()=>{observer.disconnect();document.removeEventListener('click',click,true)};
}
