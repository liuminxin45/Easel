import {useState} from 'react';

/** Generic literal-text renderer; no production, account or adoption policy. */
export default function CopyableText({label,text}:{label:string;text:string}){
  const [state,setState]=useState<'idle'|'copying'|'copied'|'error'>('idle');
  const copy=async()=>{setState('copying');try{await navigator.clipboard.writeText(text);setState('copied')}catch{setState('error')}};
  return <section className="copyable-text" aria-label={label}>
    <header className="artifact-header"><span>{label}</span><button className="btn btn-sm" type="button" disabled={state==='copying'} onClick={()=>void copy()} aria-label={'复制'+label}>{state==='copied'?'已复制':state==='copying'?'正在复制…':'复制'}</button></header>
    <pre tabIndex={0}><code>{text}</code></pre>
    <span className="copyable-text-status" role="status">{state==='error'?'复制未成功，请选择文字手动复制。':state==='copied'?'已复制'+label:''}</span>
  </section>;
}
