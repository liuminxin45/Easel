import {NativeTrends} from './nativePages';
export default function NativeNews({onUseTopic}:{id?:string;search:URLSearchParams;onUseTopic:(title:string)=>void}){
 return <NativeTrends onUseTopic={onUseTopic}/>;
}
