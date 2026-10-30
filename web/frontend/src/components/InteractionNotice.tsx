import {useCallback,useState} from 'react';
import {interactionFeedback,interactionState,type InteractionFeedback,type InteractionSource} from '../lib/interaction';

export function InteractionNotice({message,sources=[]}:{message?:string;sources?:InteractionSource[]}){
 const feedback=interactionState(sources,message);if(!feedback)return null;
 return feedback.kind==='error'?<div className="notice-error" role="alert">{feedback.message}</div>:<p className="interaction-status" role="status" aria-live="polite">{feedback.message}</p>;
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
