/** The native output-directory protocol, shared by both application hosts. */
export function bindOutputNavigation(open:(path:string)=>void):()=>void {
 const decode=(hash:string)=>{const match=hash.match(/^#\/outputs\/(.+)$/);if(!match)return;try{return decodeURIComponent(match[1])}catch{return match[1]}};
 const hash=()=>{const path=decode(location.hash);if(!path)return;history.replaceState(history.state,'',location.pathname+location.search);open(path)};
 const click=(event:MouseEvent)=>{if(event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
  const anchor=event.target instanceof Element?event.target.closest<HTMLAnchorElement>('a[href]'):null;
  if(!anchor||anchor.hasAttribute('download')||anchor.target&&!['_self','_blank'].includes(anchor.target))return;
  const raw=anchor.getAttribute('href')||'';if(!raw.startsWith('#/outputs/'))return;const path=decode(raw);if(!path)return;
  event.preventDefault();event.stopPropagation();open(path);
 };
 window.addEventListener('hashchange',hash);document.addEventListener('click',click,true);hash();
 return()=>{window.removeEventListener('hashchange',hash);document.removeEventListener('click',click,true)};
}
