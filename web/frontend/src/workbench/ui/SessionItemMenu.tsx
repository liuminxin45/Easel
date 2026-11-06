import {useCallback,useEffect,useRef,useState} from 'react';
import type {SidebarProps,SessionItemActions,SessionItemPresentation} from '../../components/Sidebar';
import type {ChatSession} from '../../lib/store';
import {IconEdit,IconArchive,IconUnarchive,IconTrash} from '../../components/icons';
import {COMPACT_LAYOUT_QUERY} from '../platform/profile';
import {Drawer} from './common';
import {SessionPress} from './sessionPress';

type Selection={session:ChatSession;actions:SessionItemActions};
const touchLayout=()=>typeof window!=='undefined'&&window.matchMedia(COMPACT_LAYOUT_QUERY).matches&&window.matchMedia('(pointer: coarse)').matches;

/** Only the private host opts into touch presentation; actions still belong to Sidebar. */
export function useSessionItemMenu(sessions:ChatSession[],path:string){
 const [enabled,setEnabled]=useState(touchLayout),[selection,setSelection]=useState<Selection|null>(null),press=useRef<SessionPress|null>(null);
 if(!press.current)press.current=new SessionPress();
 const close=useCallback(()=>setSelection(null),[]);
 const onPanelVisibilityChange=useCallback((visible:boolean)=>{if(!visible){press.current?.cancel();close()}},[close]);
 useEffect(()=>{
  const queries=[window.matchMedia(COMPACT_LAYOUT_QUERY),window.matchMedia('(pointer: coarse)')],update=()=>setEnabled(touchLayout());
  queries.forEach(query=>query.addEventListener('change',update));update();
  return()=>queries.forEach(query=>query.removeEventListener('change',update));
 },[]);
 useEffect(()=>{press.current?.cancel();close()},[enabled,path,close]);
 const selected=selection&&sessions.find(session=>session.id===selection.session.id);
 const revision=(selected as ChatSession&{revision?:number}|undefined)?.revision;
 useEffect(()=>{if(selection&&(!selected||selected.title!==selection.session.title||selected.archived!==selection.session.archived||revision!==(selection.session as ChatSession&{revision?:number}).revision))close()},[selected?.id,selected?.title,selected?.archived,revision,selection,close]);
 useEffect(()=>{
  if(!enabled)return;
  const gesture=press.current!;
  const down=()=>gesture.nextPointer();
  const move=(event:PointerEvent)=>gesture.move(event.pointerId,event.clientX,event.clientY);
  const end=(event:PointerEvent)=>gesture.end(event.pointerId);
  const cancel=()=>gesture.cancel();
  const mouseDown=(event:MouseEvent)=>{if(gesture.blocksClick()){event.preventDefault();event.stopImmediatePropagation()}};
  const click=(event:MouseEvent)=>{if(event.detail>0&&gesture.consumeClick('pointerId' in event?(event as PointerEvent).pointerId:undefined)){event.preventDefault();event.stopImmediatePropagation()}};
  document.addEventListener('pointerdown',down,true);document.addEventListener('pointermove',move,true);document.addEventListener('pointerup',end,true);document.addEventListener('pointercancel',cancel,true);document.addEventListener('scroll',cancel,true);document.addEventListener('mousedown',mouseDown,true);document.addEventListener('click',click,true);
  return()=>{gesture.cancel();document.removeEventListener('pointerdown',down,true);document.removeEventListener('pointermove',move,true);document.removeEventListener('pointerup',end,true);document.removeEventListener('pointercancel',cancel,true);document.removeEventListener('scroll',cancel,true);document.removeEventListener('mousedown',mouseDown,true);document.removeEventListener('click',click,true)};
 },[enabled]);
 const show=(session:ChatSession,actions:SessionItemActions,target:HTMLElement)=>{target.focus({preventScroll:true});setSelection({session,actions})};
 const presentation:SidebarProps['sessionItemPresentation']=(session,actions):SessionItemPresentation=>!enabled?{}:{
  itemProps:{className:'ew-session-touch',tabIndex:-1,
   onPointerDown:event=>{if(!event.isPrimary||event.button!==0||!['touch','pen'].includes(event.pointerType)||(event.target as Element).closest('button,input'))return;const target=event.currentTarget;press.current!.begin(event.pointerId,event.clientX,event.clientY,()=>show(session,actions,target))},
   onContextMenu:event=>{event.preventDefault();press.current!.cancel();show(session,actions,event.currentTarget)},
   onKeyDown:event=>{if(event.key==='ContextMenu'||event.shiftKey&&event.key==='F10'){event.preventDefault();event.stopPropagation();show(session,actions,event.currentTarget)}}},
  actions:<button type="button" className="btn btn-sm ew-session-menu-trigger" aria-label={'会话操作：'+session.title} aria-haspopup="dialog" aria-expanded={selection?.session.id===session.id} onClick={event=>{event.stopPropagation();show(session,actions,event.currentTarget)}}>会话操作</button>,
 };
 const run=(action:()=>void)=>{close();queueMicrotask(()=>requestAnimationFrame(()=>requestAnimationFrame(action)))};
 return {presentation,onPanelVisibilityChange,overlay:selection&&<Drawer open title="会话操作" onClose={close}>
  <p className="ew-session-menu-title">{selection.session.title}</p>
  <div className="ew-session-menu-actions">
   <button className="btn btn-ghost ew-session-menu-action" onClick={()=>run(selection.actions.rename)}><IconEdit size={18}/>重命名</button>
   <button className="btn btn-ghost ew-session-menu-action" onClick={()=>run(selection.actions.archive)}>{selection.session.archived?<IconUnarchive size={18}/>:<IconArchive size={18}/>} {selection.session.archived?'取消归档':'归档'}</button>
   {selection.actions.delete&&<button className="btn btn-ghost ew-session-menu-action ew-session-menu-danger" onClick={()=>run(selection.actions.delete!)}><IconTrash size={18}/>删除</button>}
  </div>
 </Drawer>};
}
