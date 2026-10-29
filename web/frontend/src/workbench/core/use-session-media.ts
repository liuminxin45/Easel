import {useCallback,useEffect,useRef,useState} from 'react';
import {useWorkbench} from './react';
import {fileUrl,type Artifact} from './models';
import {mediaDescriptorPath,MediaSessionExpired,sessionMediaCache,type MediaLease} from './session-media';

export function useSessionMediaImage(file:Artifact,compact=false,retry=0){
 const {client,ready,expired}=useWorkbench(),path=mediaDescriptorPath(file,compact),key=path||fileUrl(file),generation=sessionMediaCache.generation,[visible,setVisible]=useState(!compact),observer=useRef<IntersectionObserver|null>(null),[state,setState]=useState<{key:string;generation:number;src:string;error:string}>({key:'',generation,src:'',error:''});
 const ref=useCallback((element:HTMLElement|null)=>{observer.current?.disconnect();if(!element||!compact)return;if(typeof IntersectionObserver==='undefined'){setVisible(true);return}observer.current=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting)){setVisible(true);observer.current?.disconnect()}},{rootMargin:'160px'});observer.current.observe(element)},[compact]);
 useEffect(()=>{let live=true,lease:MediaLease|undefined;const epoch=sessionMediaCache.generation;if(!ready||expired||compact&&!visible){setState({key,generation:epoch,src:'',error:''});return}if(!path){setState({key,generation:epoch,src:key,error:''});return}if(retry)sessionMediaCache.dropUnused(path);setState({key,generation:epoch,src:'',error:''});void sessionMediaCache.acquire(path,compact?undefined:file.size).then(value=>{if(!live||epoch!==sessionMediaCache.generation){value.release();return}lease=value;setState({key,generation:epoch,src:value.url,error:''})}).catch(error=>{if(error instanceof MediaSessionExpired)client.expireSession();if(live&&epoch===sessionMediaCache.generation)setState({key,generation:epoch,src:'',error:error instanceof Error?error.message:'图片暂未读取'})});return()=>{live=false;lease?.release()}},[client,ready,expired,key,path,file.size,compact,retry,visible]);
 return {ref,src:ready&&!expired&&state.key===key&&state.generation===generation?state.src:'',error:state.key===key?state.error:'',loading:ready&&!expired&&state.key===key&&!state.src&&!state.error};
}
