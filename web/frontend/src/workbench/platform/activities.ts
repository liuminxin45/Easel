export type ActivityKind='read'|'write'|'save'|'composition';
export class ActivityCoordinator {
 private counts:Record<ActivityKind,number>={read:0,write:0,save:0,composition:0};private listeners=new Set<()=>void>();
 begin=(kind:ActivityKind)=>{this.counts[kind]++;this.emit();let ended=false;return()=>{if(ended)return;ended=true;this.counts[kind]=Math.max(0,this.counts[kind]-1);this.emit()}};
 get canUpgrade(){return this.counts.write===0&&this.counts.save===0&&this.counts.composition===0}
 snapshot=()=>JSON.stringify(this.counts);subscribe=(listener:()=>void)=>{this.listeners.add(listener);return()=>{this.listeners.delete(listener)}};private emit(){for(const listener of this.listeners)listener()}
}
/** Layout-resizing hosts already consume IME height. Visual-only WebViews do not. */
export function viewportInsets(layoutHeight:number,visual?:{height:number;offsetTop:number;scale:number}):{height:number;bottom:number}{
 if(!visual||Math.abs(visual.scale-1)>.01)return {height:layoutHeight,bottom:0};
 return {height:Math.min(layoutHeight,Math.max(0,visual.height)),bottom:Math.max(0,layoutHeight-visual.height-visual.offsetTop)};
}
export function bindViewport(coordinator:ActivityCoordinator):()=>void {
 const viewport=window.visualViewport;const update=()=>{const metrics=viewportInsets(innerHeight,viewport||undefined),style=document.documentElement.style,height=metrics.height+'px',bottom=metrics.bottom+'px';if(style.getPropertyValue('--native-height')!==height)style.setProperty('--native-height',height);if(style.getPropertyValue('--native-keyboard-inset')!==bottom)style.setProperty('--native-keyboard-inset',bottom)};
 let end:undefined|(()=>void),owner:EventTarget|null=null,blurTimer:ReturnType<typeof setTimeout>|undefined;
 const finish=()=>{if(blurTimer!==undefined)clearTimeout(blurTimer);blurTimer=undefined;owner=null;end?.();end=undefined};
 const start=(event:CompositionEvent)=>{finish();owner=event.target;end=coordinator.begin('composition')};
 const focusOut=(event:FocusEvent)=>{if(!end||event.target!==owner)return;if(blurTimer!==undefined)clearTimeout(blurTimer);blurTimer=setTimeout(()=>{blurTimer=undefined;
  // A window blur/hidden page alone does not prove IME cancellation. Only an
  // actual focus departure from the composing element releases a missing end.
  if(owner instanceof Node&&owner!==document.activeElement&&!owner.contains(document.activeElement))finish();
 },0)};
 update();viewport?.addEventListener('resize',update);viewport?.addEventListener('scroll',update);window.addEventListener('resize',update);document.addEventListener('compositionstart',start);document.addEventListener('compositionend',finish);document.addEventListener('focusout',focusOut);
 return()=>{finish();viewport?.removeEventListener('resize',update);viewport?.removeEventListener('scroll',update);window.removeEventListener('resize',update);document.removeEventListener('compositionstart',start);document.removeEventListener('compositionend',finish);document.removeEventListener('focusout',focusOut)};
}
