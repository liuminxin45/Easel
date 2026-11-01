import React, {type ReactNode} from 'react';

/** A task's historical state belongs beside its own message or version. */
export function TaskStatus({title,description,label,children}:{title:string;description:string;label?:string;children?:ReactNode}) {
 return <section className="ew-task-status" role="status" aria-label={label||title}>
  <div className="ew-task-status-copy"><strong>{title}</strong><p>{description}</p></div>
  {children&&<div className="ew-task-status-actions">{children}</div>}
 </section>;
}
