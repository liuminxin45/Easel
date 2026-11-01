import {useState, type AnchorHTMLAttributes} from 'react';
import {downloads} from '../lib/download';
import {InteractionNotice} from './InteractionNotice';

/** Shared progress/error presentation, preserving the native anchor semantics. */
export default function DownloadLink({href,download,children,onClick,...props}:
  Omit<AnchorHTMLAttributes<HTMLAnchorElement>,'href'|'download'> & {href:string;download:string}) {
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  return <><a {...props} href={href} download={download} aria-disabled={busy||undefined} aria-busy={busy||undefined}
    onClick={event=>{
      event.preventDefault();onClick?.(event);
      if(busy)return;
      setBusy(true);setError('');
      void downloads.download(href,download).catch(reason=>setError(reason instanceof Error?reason.message:'下载失败，请重试')).finally(()=>setBusy(false));
    }}>{busy?'正在准备下载…':children}</a><InteractionNotice sources={[{error}]}/></>;
}
