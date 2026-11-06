import DownloadLink from '../../components/DownloadLink';
import EaselDrawer from '../../components/Drawer';
import React,{useEffect,useRef,useState,type ReactNode} from 'react';
import {fileUrl,fileDownload,record,string,type Artifact,type InteractionSource} from '@workbench/core';
import {useWorkbench,useOperation,useResource,useSessionMediaImage} from './hooks';
import {renderMarkdown} from './lib/sanitize';
import {InteractionNotice,StatusCard} from '../../components/InteractionNotice';
import {DetailChevron} from './ExtensionDetails';
import {useResourceVisibility} from './hooks/visibility';

/** Host reads stay quiet; actual errors and recovery warnings use the original UI. */
export function Notice({message,sources=[]}:{message?:string;sources?:InteractionSource[]}){
 return <InteractionNotice message={message} sources={sources.map(({error,feedback})=>({error,feedback}))}/>;
}

export function ActionButton({action,children,onClick,disabled,...props}:React.ButtonHTMLAttributes<HTMLButtonElement>&{action:Pick<InteractionSource,'busy'>}){
 const [invoked,setInvoked]=useState(false),working=invoked&&!!action.busy;
 useEffect(()=>{if(invoked&&!action.busy)setInvoked(false)},[invoked,action.busy]);
 return <button {...props} disabled={disabled||action.busy} aria-busy={working||undefined} onClick={event=>{setInvoked(true);onClick?.(event)}}><span className={'ew-action-spinner'+(working?'':' is-idle')} aria-hidden="true"/>{children}</button>;
}
export function Markdown({text}:{text:string}){return <div className="markdown-body" dangerouslySetInnerHTML={{__html:renderMarkdown(text)}}/>}
export function Panel({title,children}:{title?:string;children:ReactNode}){return <section className="card ew-panel">{title&&<h2>{title}</h2>}{children}</section>}
export function Field({label,children}:{label:string;children:ReactNode}){return <label className="ew-field"><span>{label}</span>{children}</label>}
export function Pending({scope,reload}:{scope:string;reload?:()=>void}){const p=useOperation(scope),previous=useRef(p.pending?.uncertain?p.pending.id:undefined);useEffect(()=>{if(previous.current&&!p.pending)reload?.();previous.current=p.pending?.uncertain?p.pending.id:undefined},[p.pending?.id,p.pending?.uncertain,reload]);return p.pending?.uncertain&&!p.busy?<StatusCard tone="warning" className="ew-status-card-compact">{p.feedback?.message||p.error||'连接中断，正在恢复操作状态。输入已保留。'}</StatusCard>:null}
/** Only host history/focus is adapted; the visible shell is the original drawer. */
type HostDrawerProps={open:boolean;title:string;onClose:()=>void;onDismiss?:()=>void|boolean;children:ReactNode;overlayClassName?:string};
export function Drawer(props:HostDrawerProps){return props.open?<MountedDrawer {...props}/>:null}
function MountedDrawer({title,onClose,onDismiss,children,overlayClassName}:HostDrawerProps){
 const panel=useRef<HTMLDivElement>(null),{navigation}=useWorkbench(),dismiss=useRef(onDismiss||onClose),close=useRef(onClose);
 dismiss.current=onDismiss||onClose;close.current=onClose;
 const previous=useRef(typeof document!=='undefined'&&document.activeElement instanceof HTMLElement?document.activeElement:null);
 // Keep nested drawers inside their existing overlay's stacking context.
 // Capture the caller once per opening so focus inside this drawer cannot
 // accidentally make a later render portal the drawer into itself.
 const container=useRef(typeof document==='undefined'?null:previous.current?.closest('.drawer-overlay,.settings-overlay,.sidebar-panel')||document.querySelector('.native-host'));
 useEffect(()=>{
  const release=navigation.registerLayer?.(()=>dismiss.current());
  const focus=requestAnimationFrame(()=>panel.current?.querySelector<HTMLElement>('button:not(:disabled),[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled)')?.focus({preventScroll:true}));
  const key=(event:KeyboardEvent)=>{
   if(event.key!=='Escape'||event.defaultPrevented||event.isComposing||document.querySelector('dialog[open]'))return;
   const overlays=[...document.querySelectorAll<HTMLElement>('.drawer-overlay')].filter(element=>element.getClientRects().length&&getComputedStyle(element).visibility!=='hidden');
   if(overlays.at(-1)!==panel.current?.parentElement)return;
   event.preventDefault();event.stopPropagation();close.current();
  };
  document.addEventListener('keydown',key);
  return()=>{cancelAnimationFrame(focus);release?.();document.removeEventListener('keydown',key);
   // The overlay observer first restores the parent's inert state. Returning
   // focus in that same cleanup would otherwise target a still-inert control.
   queueMicrotask(()=>requestAnimationFrame(()=>{if(previous.current?.isConnected)previous.current.focus({preventScroll:true})}));
  };
 },[navigation.registerLayer]);
 return <EaselDrawer title={title} onClose={onClose} panelRef={panel} container={container.current} overlayClassName={overlayClassName}>{children}</EaselDrawer>;
}
export function ArtifactView({file}:{file:Artifact}){const image=useSessionMediaImage(file);return <figure className="ew-artifact">{file.mime.startsWith('image/')?<img src={image.src||fileUrl(file)} alt={file.name}/>:file.mime.startsWith('video/')?<video src={fileUrl(file)} controls preload="metadata"/>:file.mime.startsWith('audio/')?<audio src={fileUrl(file)} controls preload="metadata"/>:<p>{file.name}</p>}<figcaption><DownloadLink href={fileDownload(file)} download={file.name}>{file.name} · 下载原件</DownloadLink></figcaption></figure>}
function RecordDetails({title,renderContent}:{title:string;renderContent:()=>ReactNode}){const [open,setOpen]=useState(false);return <><button className="ew-record-trigger" aria-haspopup="dialog" onClick={()=>setOpen(true)}><span>{title}</span><DetailChevron/></button><Drawer open={open} title={title} onClose={()=>setOpen(false)}>{open?renderContent():null}</Drawer></>}
export function JsonDetails({value,title='详细记录'}:{value:unknown;title?:string}){return <RecordDetails title={title} renderContent={()=><pre className="ew-preserve">{JSON.stringify(value,null,2)}</pre>}/>}
export const resultDocument=(v:unknown)=>record(record(v).result??v);
export function PageHead({title,children}:{title:string;children?:ReactNode}){const {back}=useWorkbench();return <header className="ew-page-head"><div className="ew-row"><button className="btn btn-ghost" aria-label="返回" onClick={back}>←</button><h1 className="page-title">{title}</h1></div><div className="ew-row">{children}</div></header>}
export function TextRecord({title,value}:{title:string;value:unknown}){return <RecordDetails title={title} renderContent={()=><pre className="ew-preserve">{typeof value==='string'?value:JSON.stringify(value,null,2)}</pre>}/>}
/** Mounted disclosures keep their last text while closed without reformatting it. */
export function RecordBody({value}:{value:unknown}){
 const visible=useResourceVisibility(),snapshot=useRef<{value:unknown;text:string}|null>(null);
 if(visible&&(!snapshot.current||snapshot.current.value!==value))snapshot.current={value,text:typeof value==='string'?value:JSON.stringify(value,null,2)};
 return <pre className="ew-preserve">{snapshot.current?.text}</pre>;
}
/** Full receipt bodies belong to the explicit original drawer, not list reads. */
export function RemoteRecord({title,path,field}:{title:string;path:string;field?:string}){return <RecordDetails title={title} renderContent={()=><ReadRecord path={path} field={field}/>}/>}
function ReadRecord({path,field}:{path:string;field?:string}){
 const resource=useResource(path),value=field?record(resource.data)[field]:resource.data;
 return <><Notice sources={[resource]}/>{resource.error&&<button className="btn btn-sm" onClick={()=>void resource.reload()}>重新读取</button>}{resource.loading&&!resource.data?<StatusCard className="ew-status-card-compact">正在读取记录…</StatusCard>:resource.data&&<pre className="ew-preserve">{typeof value==='string'?value:JSON.stringify(value,null,2)}</pre>}</>;
}
export function SourceLink({value}:{value:unknown}){const url=string(value);return /^https?:\/\//.test(url)?<a href={url} target="_blank" rel="noreferrer">原始来源 ↗</a>:null}
