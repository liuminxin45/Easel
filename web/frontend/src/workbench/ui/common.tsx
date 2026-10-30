import React,{useEffect,useRef,useState,type ReactNode} from 'react';
import {useWorkbench,useOperation,useSessionMediaImage,fileUrl,fileDownload,record,string,type Artifact,type InteractionSource} from '@workbench/core';
import {renderMarkdown} from './lib/sanitize';
import {InteractionNotice} from '../../components/InteractionNotice';

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
export function Pending({scope,reload}:{scope:string;reload?:()=>void}){const p=useOperation(scope),previous=useRef(p.pending?.uncertain?p.pending.id:undefined);useEffect(()=>{if(previous.current&&!p.pending)reload?.();previous.current=p.pending?.uncertain?p.pending.id:undefined},[p.pending?.id,p.pending?.uncertain,reload]);return p.pending?.uncertain&&!p.busy?<p className="ew-muted" role="status">{p.feedback?.message||p.error||'连接中断，正在恢复操作状态。输入已保留。'}</p>:null}
export function Modal({open,title,onClose,onDismiss,children}:{open:boolean;title:string;onClose:()=>void;onDismiss?:()=>void;children:ReactNode}){const ref=useRef<HTMLDialogElement>(null),{navigation}=useWorkbench(),close=useRef(onDismiss||onClose);close.current=onDismiss||onClose;useEffect(()=>{if(!open)return;const previous=document.activeElement as HTMLElement|null,el=ref.current;if(el&&!el.open)el.showModal();const release=navigation.registerLayer?.(()=>close.current());return()=>{release?.();el?.close();previous?.focus({preventScroll:true})}},[open,navigation.registerLayer]);return open?<dialog ref={ref} className="ew-dialog" onCancel={e=>{e.preventDefault();onClose()}} aria-label={title}><div className="drawer-header"><h2>{title}</h2><button className="btn btn-ghost" aria-label="关闭" onClick={onClose}>×</button></div><div className="drawer-body">{children}</div></dialog>:null}
export function ArtifactView({file}:{file:Artifact}){const image=useSessionMediaImage(file);return <figure className="ew-artifact">{file.mime.startsWith('image/')?<img src={image.src||fileUrl(file)} alt={file.name}/>:file.mime.startsWith('video/')?<video src={fileUrl(file)} controls preload="metadata"/>:file.mime.startsWith('audio/')?<audio src={fileUrl(file)} controls preload="metadata"/>:<p>{file.name}</p>}<figcaption><a href={fileDownload(file)} download>{file.name} · 下载原件</a></figcaption></figure>}
export function JsonDetails({value,title='详细记录'}:{value:unknown;title?:string}){return <details><summary>{title}</summary><pre className="ew-json">{JSON.stringify(value,null,2)}</pre></details>}
export const resultDocument=(v:unknown)=>record(record(v).result??v);
export function PageHead({title,children}:{title:string;children?:ReactNode}){const {back}=useWorkbench();return <header className="ew-page-head"><div className="ew-row"><button className="btn btn-ghost" aria-label="返回" onClick={back}>←</button><h1 className="page-title">{title}</h1></div><div className="ew-row">{children}</div></header>}
export function TextRecord({title,value}:{title:string;value:unknown}){return <details><summary>{title}</summary><pre className="ew-preserve">{typeof value==='string'?value:JSON.stringify(value,null,2)}</pre></details>}
export function SourceLink({value}:{value:unknown}){const url=string(value);return /^https?:\/\//.test(url)?<a href={url} target="_blank" rel="noreferrer">原始来源 ↗</a>:null}
