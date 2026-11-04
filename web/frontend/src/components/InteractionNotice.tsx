import {useCallback,useState,type ReactNode} from 'react';
import {interactionFeedback,interactionState,type InteractionFeedback,type InteractionSource} from '../lib/interaction';
import {IconChat} from './icons';

/** A shared shell for host feedback and the session-opening state. */
export function StatusCard({title,children,tone='status',icon,className='',label}:{title?:ReactNode;children?:ReactNode;tone?:'status'|'error'|'warning'|'ready';icon?:ReactNode;className?:string;label?:string}){
 return <section className={'ew-status-card card '+className+' is-'+tone} role={tone==='error'?'alert':'status'} aria-label={label} aria-live={tone==='error'?'assertive':'polite'}>
  {icon&&<div className="ew-status-card-icon" aria-hidden="true">{icon}</div>}
  <div className="ew-status-card-content">{title&&<div className="ew-status-card-title">{title}</div>}{children}</div>
 </section>;
}

export function InteractionNotice({message,sources=[]}:{message?:string;sources?:InteractionSource[]}){
 const feedback=interactionState(sources,message);if(!feedback)return null;
 return <StatusCard tone={feedback.kind} className="ew-status-card-compact" icon={<IconChat size={18}/>}>{feedback.message}</StatusCard>;
}

/** Existing views can retain field errors while sharing transient feedback. */
export function useFeedbackChannel(){
 const [feedback,setFeedback]=useState<InteractionFeedback|undefined>();
 const clear=useCallback(()=>setFeedback(undefined),[]);
 const report=useCallback((error:unknown)=>{const value=interactionFeedback(error);setFeedback(value);return value?.kind==='error'?value.message:''},[]);
 return {feedback,clear,report};
}

export function useFeedbackMessage(){
 const [feedback,setFeedback]=useState<InteractionFeedback|undefined>();
 const setMessage=useCallback((message:string,kind:'status'|'error'='status')=>setFeedback(message?{kind,message}:undefined),[]);
 const report=useCallback((error:unknown)=>setFeedback(interactionFeedback(error)),[]);
 return [feedback,setMessage,report] as const;
}
