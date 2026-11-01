import React, {type ReactNode} from 'react';

export function DetailChevron() {
 return <svg className="ew-detail-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>;
}

/** Private business details keep native keyboard semantics and upstream tokens. */
export function ExtensionDetails({title,children,className='',...props}:Omit<React.DetailsHTMLAttributes<HTMLDetailsElement>,'title'>&{title:ReactNode}) {
 return <details {...props} className={'ew-disclosure '+className}>
  <summary className="ew-disclosure-trigger"><span>{title}</span><DetailChevron/></summary>
  <div className="ew-disclosure-body">{children}</div>
 </details>;
}
