import React, {useEffect,useRef,useState,type ReactNode} from 'react';
import {ResourceVisibility} from './hooks/visibility';

export function DetailChevron() {
 return <svg className="ew-detail-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>;
}

/** Private business details keep native keyboard semantics and upstream tokens. */
export function ExtensionDetails({title,children,className='',open:requestedOpen,onToggle,...props}:Omit<React.DetailsHTMLAttributes<HTMLDetailsElement>,'title'>&{title:ReactNode}) {
 const [open,setOpen]=useState(requestedOpen===true),mounted=useRef(open);
 if(open)mounted.current=true;
 useEffect(()=>{if(requestedOpen!==undefined)setOpen(requestedOpen)},[requestedOpen]);
 return <details {...props} open={open} onToggle={event=>{setOpen(event.currentTarget.open);onToggle?.(event)}} className={'ew-disclosure '+className}>
  <summary className="ew-disclosure-trigger"><span>{title}</span><DetailChevron/></summary>
  {mounted.current&&<ResourceVisibility visible={open}><div className="ew-disclosure-body">{children}</div></ResourceVisibility>}
 </details>;
}
