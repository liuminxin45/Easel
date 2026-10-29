import {useEffect,useRef,useState} from 'react';
import {useDraft,useResource,useWorkbench} from './react';
import {blankCompletion,completionOptionsPath,completionPlanInput,initialCompletionSelection,type CompletionOptions,type CompletionPlan,type CompletionPreview} from './completion';

export function useCompletionPlan(workId:string,versionId:string,opened:boolean){
 const {service}=useWorkbench(),options=useResource<CompletionOptions>(opened?completionOptionsPath(workId,versionId):null),[input,patch,reset]=useDraft<{scope:string[];plan:CompletionPlan;initialized:boolean}>('completion:'+workId+':'+versionId,{scope:[],plan:blankCompletion,initialized:false}),[preview,setPreview]=useState<CompletionPreview|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false),sequence=useRef(0);
 useEffect(()=>{if(!options.data||input.initialized)return;patch({...initialCompletionSelection(options.data),initialized:true})},[options.data,input.initialized]);
 const plan=completionPlanInput(input.plan),fingerprint=JSON.stringify({scope:input.scope,plan}),whole=!!options.data?.whole_ready&&options.data.required_scopes.length>0&&options.data.required_scopes.every(scope=>input.scope.includes(scope)),needsScopeReview=!!options.data&&input.scope.some(scope=>!options.data!.available_scopes.includes(scope));
 useEffect(()=>{if(!opened||!options.data||!input.initialized)return;const current=++sequence.current;setPreview(null);setLoading(true);setError('');const timer=setTimeout(()=>void service.completionPreview(workId,versionId,input.scope,plan).then(value=>{if(current===sequence.current)setPreview(value)}).catch(error=>{if(current===sequence.current)setError(error instanceof Error?error.message:'交付方案未能核对')}).finally(()=>{if(current===sequence.current)setLoading(false)}),220);return()=>{clearTimeout(timer);sequence.current++}},[opened,options.data,workId,versionId,fingerprint,input.initialized]);
 const change=(next:Partial<CompletionPlan>)=>patch({plan:{...input.plan,...next}});
 const setScope=(scope:string[])=>patch({scope,plan:options.data?.required_scopes.every(item=>scope.includes(item))?input.plan:{...blankCompletion}});
 const recheckScope=()=>{if(options.data)patch({...initialCompletionSelection(options.data),initialized:true})};
 return {options,input,plan,preview,error,loading,whole,change,setScope,reset,needsScopeReview,recheckScope,canSubmit:!!preview?.plan_hash&&!loading&&!error&&!needsScopeReview&&input.scope.length>0};
}
