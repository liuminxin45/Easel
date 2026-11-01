import {useLayoutEffect,type RefObject} from 'react';

interface Bounds {left:number;top:number;width:number;height:number}

/** Keep the authored placement unless it would leave the visible viewport. */
export function brushPopoverPlacement(viewport:Bounds,anchor:Bounds,panel:Bounds,chromeHeight=0){
 const left=viewport.left+8,top=viewport.top+8,width=Math.max(1,viewport.width-16),height=Math.max(1,viewport.height-16),right=left+width,bottom=top+height;
 const wholePanelScroll=chromeHeight>0&&(panel.height+1<chromeHeight+44||height+1<chromeHeight+44);
 if(!wholePanelScroll&&panel.left>=left&&panel.top>=top&&panel.left+panel.width<=right&&panel.top+panel.height<=bottom)return null;
 const panelWidth=Math.min(panel.width,width),panelHeight=wholePanelScroll?height:Math.min(panel.height,height),above=anchor.top-12-panelHeight,below=anchor.top+anchor.height+12;
 const y=above>=top?above:below+panelHeight<=bottom?below:Math.max(top,Math.min(above,bottom-panelHeight));
 return {left:Math.max(left,Math.min(panel.left,right-panelWidth)),top:y,maxWidth:panelWidth,maxHeight:panelHeight,wholePanelScroll};
}

/** Both brush and slash panels share one viewport-aware positioning seam. */
export function useBrushPopover(open:boolean,anchorRef:RefObject<HTMLElement|null>,panelRef:RefObject<HTMLElement|null>,contentKey:string){
 useLayoutEffect(()=>{
  const anchor=anchorRef.current,panel=panelRef.current;if(!open||!anchor||!panel)return;
  const win=panel.ownerDocument.defaultView;if(!win)return;
  const body=panel.querySelector<HTMLElement>('.brush-body');
  const properties=['left','top','right','bottom','max-inline-size','max-block-size','transform','animation','display','overflow-x','overflow-y'];
  const original=properties.map(name=>[name,panel.style.getPropertyValue(name),panel.style.getPropertyPriority(name)]);
  const bodyOriginal=body?['flex','min-block-size','max-block-size','overflow-x','overflow-y'].map(name=>[name,body.style.getPropertyValue(name),body.style.getPropertyPriority(name)]):[];
  const restore=()=>{for(const [name,value,priority] of original){if(value)panel.style.setProperty(name,value,priority);else panel.style.removeProperty(name)}if(body)for(const [name,value,priority] of bodyOriginal){if(value)body.style.setProperty(name,value,priority);else body.style.removeProperty(name)}};
  const chromeHeight=()=>body?Array.from(panel.children).filter(child=>child!==body).reduce((sum,child)=>sum+Math.max(child.getBoundingClientRect().height,child.scrollHeight),2):0;
  let adjusted=false,frame:number|undefined,disposed=false;
  const measure=()=>{
   if(disposed)return;if(adjusted){restore();adjusted=false}
   const viewport=win.visualViewport,bounds={left:viewport?.offsetLeft||0,top:viewport?.offsetTop||0,width:viewport?.width||win.innerWidth,height:viewport?.height||win.innerHeight};
   if(!brushPopoverPlacement(bounds,anchor.getBoundingClientRect(),panel.getBoundingClientRect(),chromeHeight()))return;
   // Overflow correction uses the final box, rather than the pop-in animation.
   panel.style.setProperty('transform','none');panel.style.setProperty('animation','none');adjusted=true;
   const placement=brushPopoverPlacement(bounds,anchor.getBoundingClientRect(),panel.getBoundingClientRect(),chromeHeight());
   if(!placement){restore();adjusted=false;return}
   const parent=panel.offsetParent as HTMLElement|null,parentBox=parent?.getBoundingClientRect(),scaleX=parent&&parentBox&&parent.offsetWidth?parentBox.width/parent.offsetWidth||1:1,scaleY=parent&&parentBox&&parent.offsetHeight?parentBox.height/parent.offsetHeight||1:1;
   const originLeft=parentBox?parentBox.left+(parent!.clientLeft-parent!.scrollLeft)*scaleX:0,originTop=parentBox?parentBox.top+(parent!.clientTop-parent!.scrollTop)*scaleY:0;
   panel.style.setProperty('max-inline-size',placement.maxWidth/scaleX+'px');panel.style.setProperty('max-block-size',placement.maxHeight/scaleY+'px');
   panel.style.setProperty('left',(placement.left-originLeft)/scaleX+'px');panel.style.setProperty('top',(placement.top-originTop)/scaleY+'px');
   panel.style.setProperty('right','auto');panel.style.setProperty('bottom','auto');
   if(placement.wholePanelScroll&&body){
    // An IME can leave less room than the header and tabs. Keep every control
    // reachable by scrolling the existing panel, without shrinking typography.
    panel.style.setProperty('display','block');panel.style.setProperty('overflow-y','auto');panel.style.setProperty('overflow-x','hidden');
    body.style.setProperty('flex','0 0 auto');body.style.setProperty('min-block-size','0');body.style.setProperty('max-block-size','none');body.style.setProperty('overflow-y','visible');body.style.setProperty('overflow-x','visible');
   }
  };
  const schedule=()=>{if(frame!==undefined||disposed)return;frame=win.requestAnimationFrame(()=>{frame=undefined;measure()})};
  const scroll=(event:Event)=>{if(event.target instanceof win.Node&&panel.contains(event.target))return;schedule()};
  measure();
  const observer=typeof ResizeObserver==='undefined'?null:new ResizeObserver(schedule);observer?.observe(anchor);
  if(panel.offsetParent&&panel.offsetParent!==anchor)observer?.observe(panel.offsetParent);
  win.addEventListener('resize',schedule);win.addEventListener('scroll',scroll,true);
  win.visualViewport?.addEventListener('resize',schedule);win.visualViewport?.addEventListener('scroll',schedule);
  return()=>{disposed=true;if(frame!==undefined)win.cancelAnimationFrame(frame);observer?.disconnect();win.removeEventListener('resize',schedule);win.removeEventListener('scroll',scroll,true);win.visualViewport?.removeEventListener('resize',schedule);win.visualViewport?.removeEventListener('scroll',schedule);if(adjusted)restore()};
 },[open,anchorRef,panelRef,contentKey]);
}
