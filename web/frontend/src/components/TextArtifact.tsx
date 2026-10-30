import {useEffect,useState} from 'react';
import CopyableText from './CopyableText';

export default function TextArtifact({url,name}:{url:string;name:string}){
  const [text,setText]=useState<string|null>(null),[error,setError]=useState('');
  useEffect(()=>{const controller=new AbortController();setText(null);setError('');
    void (async()=>{const response=await fetch(url,{signal:controller.signal});if(!response.ok)throw Error('文本加载失败，可打开原文件');
      const reader=response.body?.getReader();if(!reader)throw Error('文本加载失败，可打开原文件');
      const decoder=new TextDecoder();let size=0,result='';
      try{while(true){const part=await reader.read();if(part.done)break;size+=part.value.byteLength;if(size>1024*1024)throw Error('文本较大，请打开原文件查看');result+=decoder.decode(part.value,{stream:true})}result+=decoder.decode();if(!controller.signal.aborted)setText(result)}finally{await reader.cancel()}
    })().catch(error=>{if(!controller.signal.aborted)setError(error instanceof Error?error.message:'文本加载失败，可打开原文件')});
    return()=>controller.abort();
  },[url]);
  return error?<p role="status">{error}</p>:text===null?<p role="status">正在读取文本…</p>:<CopyableText label={name} text={text}/>;
}
