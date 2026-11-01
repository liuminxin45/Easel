import React from 'react';
import {Field} from './common';

const pad=(value:number)=>String(value).padStart(2,'0');
function localMinute(date:Date):string {
 return String(date.getFullYear()).padStart(4,'0')+'-'+pad(date.getMonth()+1)+'-'+pad(date.getDate())+'T'+pad(date.getHours())+':'+pad(date.getMinutes());
}

/** Show only timestamps with an explicit offset; older ambiguous text stays intact. */
export function timestampToLocalMinute(value:string|null|undefined):string {
 if(!value)return '';
 const parts=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})$/i.exec(value);
 if(!parts)return '';
 const [year,month,day,hour,minute,second]=parts.slice(1).map(Number);
 const calendar=new Date(0);
 calendar.setUTCFullYear(year!,month!-1,day!);calendar.setUTCHours(hour!,minute!,second||0,0);
 if(year!<1||calendar.getUTCFullYear()!==year||calendar.getUTCMonth()!==month!-1||calendar.getUTCDate()!==day||calendar.getUTCHours()!==hour||calendar.getUTCMinutes()!==minute||calendar.getUTCSeconds()!==(second||0))return '';
 const date=new Date(value);
 return Number.isFinite(date.getTime())?localMinute(date):'';
}

/** Empty means unknown; null rejects malformed or nonexistent local wall times. */
export function localMinuteToTimestamp(value:string):string|null {
 if(!value)return '';
 if(!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value))return null;
 const date=new Date(value);
 return Number.isFinite(date.getTime())&&date.getFullYear()>0&&localMinute(date)===value?date.toISOString():null;
}

export function TimestampField({label,value,onChange,disabled=false}:{label:string;value:string|null|undefined;onChange:(value:string)=>void;disabled?:boolean}) {
 const shown=timestampToLocalMinute(value);
 return <Field label={label}><input className="field" type="datetime-local" step={60} value={shown} disabled={disabled} onChange={event=>{
  const input=event.currentTarget;
  if(input.validity.badInput)return;
  const changed=input.value;
  input.setCustomValidity('');
  if(changed===shown)return;
  const next=localMinuteToTimestamp(changed);
  input.setCustomValidity(next===null?'这个本地时间无效，请重新选择。':'');
  if(next===null){input.reportValidity();return;}
  onChange(next);
 }}/>{!!value&&!shown&&<small className="ew-muted">原时间记录已保留；重新选择后才会替换：{value}</small>}</Field>;
}
