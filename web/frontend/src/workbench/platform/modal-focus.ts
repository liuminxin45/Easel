/** Native-host keyboard isolation for upstream div modals. No gesture handling. */
const MOBILE_MODAL = '(max-width: 900px), (max-width: 1100px) and (max-height: 500px)';
const OVERLAYS = '.native-host .overlay, .native-host .drawer-overlay';
const TABBABLE = 'a[href],button,input,select,textarea,summary,[contenteditable="true"],[tabindex]';
type SavedAttribute = {present:boolean;value:string|null};
type Modal = {overlay:HTMLElement;panel:HTMLElement;returnTo:HTMLElement|null;tabIndex:SavedAttribute;popups:Set<HTMLElement>};

export function bindNativeModalFocus():()=>void {
 const media=window.matchMedia(MOBILE_MODAL),savedInert=new Map<HTMLElement,SavedAttribute>();
 const origins=new WeakMap<HTMLElement,HTMLElement|null>();
 let current:Modal|null=null,frame=0,stopped=false,lastOutside=document.activeElement instanceof HTMLElement?document.activeElement:null;
 let branchParents=new Set<Element>();
 const visible=(element:HTMLElement)=>element.getClientRects().length>0&&getComputedStyle(element).visibility!=='hidden';
 const restoreAttribute=(element:HTMLElement,name:string,value:SavedAttribute)=>{
  if(value.present)element.setAttribute(name,value.value??'');else element.removeAttribute(name);
 };
 const restoreInert=()=>{for(const [element,value] of savedInert)restoreAttribute(element,'inert',value);savedInert.clear();branchParents.clear()};
 const nativeDialog=()=>!!document.querySelector('dialog[open]');
 const inside=(element:Element|null)=>!!element&&!!current&&(current.overlay.contains(element)||[...current.popups].some(popup=>popup.contains(element)));
 const controls=()=>current?[...current.panel.querySelectorAll<HTMLElement>(TABBABLE)].filter(element=>element.tabIndex>=0&&!element.matches(':disabled')&&!element.closest('[inert]')&&visible(element)):[];
 const focusPanel=()=>{
  if(!current||nativeDialog())return;
  const target=controls()[0];
  if(target){target.focus({preventScroll:true});return}
  current.panel.tabIndex=-1;current.panel.focus({preventScroll:true});
 };
 const release=(restoreFocus:boolean)=>{
  const previous=current;current=null;restoreInert();
  if(previous){restoreAttribute(previous.panel,'tabindex',previous.tabIndex);if(restoreFocus&&previous.returnTo?.isConnected&&!nativeDialog())previous.returnTo.focus({preventScroll:true})}
 };
 const syncInert=()=>{
  if(!current)return;
  for(const popup of current.popups)if(!popup.isConnected||!visible(popup))current.popups.delete(popup);
  for(const trigger of current.panel.querySelectorAll<HTMLElement>('[aria-controls][aria-expanded="true"]')){
   for(const id of (trigger.getAttribute('aria-controls')||'').split(/\s+/)){
    const popup=document.getElementById(id);if(popup instanceof HTMLElement&&popup.isConnected)current.popups.add(popup);
   }
  }
  const allowed=[current.overlay,...current.popups,...document.querySelectorAll<HTMLElement>('dialog[open]')],desired=new Set<HTMLElement>();
  branchParents=new Set<Element>();
  for(let branch:HTMLElement|null=current.overlay;branch?.parentElement;branch=branch.parentElement){
   const container:HTMLElement=branch.parentElement;branchParents.add(container);
   for(const sibling of container.children)if(sibling instanceof HTMLElement&&sibling!==branch&&!allowed.some(element=>sibling===element||sibling.contains(element)))desired.add(sibling);
   if(container===document.body)break;
  }
  for(const [element,value] of savedInert)if(!desired.has(element)){restoreAttribute(element,'inert',value);savedInert.delete(element)}
  for(const element of desired)if(!savedInert.has(element)){savedInert.set(element,{present:element.hasAttribute('inert'),value:element.getAttribute('inert')});element.inert=true}
 };
 const reconcile=()=>{
  frame=0;if(stopped)return;
  try{
   const otherOwner=[...document.querySelectorAll<HTMLElement>('.native-host .settings-panel[aria-modal="true"],.native-host .sidebar-panel[aria-modal="true"]')].some(visible);
   const candidates=media.matches&&!otherOwner?[...document.querySelectorAll<HTMLElement>(OVERLAYS)].filter(element=>!element.closest('dialog[open]')&&element.querySelector(':scope > .modal, :scope > .drawer')&&visible(element)):[];
   candidates.sort((a,b)=>(Number(getComputedStyle(a).zIndex)||0)-(Number(getComputedStyle(b).zIndex)||0));
   const overlay=candidates.at(-1)||null;
   if(overlay!==current?.overlay){
    const previous=current;
    release(!overlay&&!otherOwner);
    if(overlay){
     const panel=overlay.querySelector<HTMLElement>(':scope > .modal, :scope > .drawer')!;
     if(!origins.has(overlay))origins.set(overlay,document.activeElement instanceof HTMLElement&&!overlay.contains(document.activeElement)?document.activeElement:previous?.returnTo||lastOutside);
     current={overlay,panel,returnTo:origins.get(overlay)||null,tabIndex:{present:panel.hasAttribute('tabindex'),value:panel.getAttribute('tabindex')},popups:new Set()};
     syncInert();
     if(previous?.returnTo&&overlay.contains(previous.returnTo))previous.returnTo.focus({preventScroll:true});
     else if(!inside(document.activeElement))focusPanel();
    }
   }else if(current)syncInert();
  }catch{release(false)}
 };
 const schedule=()=>{if(!stopped&&!frame)frame=requestAnimationFrame(reconcile)};
 const modalNode=(node:Node)=>node instanceof Element&&(node.matches('.overlay,.drawer-overlay,.settings-overlay,.sidebar-panel,.model-dd,[popover]')||!!node.querySelector('.overlay,.drawer-overlay,.settings-overlay,.sidebar-panel'));
 const observer=new MutationObserver(records=>{
  // Streaming text inside a page or drawer needs no rescan or layout. Only
  // overlay topology and direct background siblings can change isolation.
  if(current&&!current.overlay.isConnected){schedule();return}
  if(current&&inside(document.activeElement))for(const record of records)for(const node of record.addedNodes){
   if(node instanceof HTMLElement&&!node.hidden&&node.getAttribute('aria-hidden')!=='true'&&node.matches('.model-dd[role="listbox"],[popover]'))current.popups.add(node);
  }
  if(records.some(record=>record.type==='attributes'
   ? record.target instanceof Element&&(record.target.matches('.overlay,.drawer-overlay,.settings-panel,.sidebar-panel')||record.attributeName==='aria-expanded'&&!!current?.panel.contains(record.target)&&record.target.hasAttribute('aria-controls'))
   : branchParents.has(record.target as Element)||[...record.addedNodes,...record.removedNodes].some(modalNode)))schedule();
 });
 const onFocus=(event:FocusEvent)=>{
  const target=event.target;if(!(target instanceof HTMLElement))return;
  if(target.closest('.native-host .settings-panel[aria-modal="true"],.native-host .sidebar-panel[aria-modal="true"]')){schedule();return}
  if(!target.closest('.overlay,.drawer-overlay,.model-dd,[popover]'))lastOutside=target;
  if(!current||nativeDialog()||inside(target))return;
  // OptionsDropdown may portal to body without an id. It can only be opened
  // from the active modal because every background control is inert.
  const popup=target.closest<HTMLElement>('.model-dd[role="listbox"],[popover]');
  if(popup){current.popups.add(popup);schedule();return}
  focusPanel();
 };
 const onKey=(event:KeyboardEvent)=>{
  if(event.key!=='Tab'||event.defaultPrevented||event.isComposing||!current||nativeDialog())return;
  // Shared dropdowns manage their own option navigation and Tab dismissal.
  if([...current.popups].some(popup=>popup.contains(document.activeElement)))return;
  const items=controls(),first=items[0],last=items.at(-1);
  if(!first){event.preventDefault();focusPanel();return}
  if(event.shiftKey&&(document.activeElement===first||!inside(document.activeElement))){event.preventDefault();last?.focus()}
  else if(!event.shiftKey&&(document.activeElement===last||!inside(document.activeElement))){event.preventDefault();first.focus()}
 };
 const onToggle=(event:Event)=>{const popup=event.target;if(current&&popup instanceof HTMLElement&&popup.hasAttribute('popover')&&inside(document.activeElement)){current.popups.add(popup);schedule()}};
 observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['class','style','hidden','aria-hidden','aria-expanded','aria-modal']});
 media.addEventListener('change',schedule);document.addEventListener('focusin',onFocus);document.addEventListener('keydown',onKey);
 document.addEventListener('toggle',onToggle,true);
 reconcile();
 return()=>{stopped=true;cancelAnimationFrame(frame);observer.disconnect();media.removeEventListener('change',schedule);document.removeEventListener('focusin',onFocus);document.removeEventListener('keydown',onKey);document.removeEventListener('toggle',onToggle,true);release(true)};
}
