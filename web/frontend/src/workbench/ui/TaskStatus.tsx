import React, {type ReactNode} from 'react';
import {StatusCard} from '../../components/InteractionNotice';

/** A task's historical state belongs beside its own message or version. */
export function TaskStatus({title,description,label,children}:{title:string;description:string;label?:string;children?:ReactNode}) {
 return <StatusCard className="ew-task-status" label={label||title} tone="warning">
  <div className="ew-task-status-copy"><strong>{title}</strong><p>{description}</p></div>
  {children&&<div className="ew-task-status-actions">{children}</div>}
 </StatusCard>;
}
