import type {OutputsDataSource,OutputsListInput,OutputsListPage} from '../../lib/outputBrowser';
import type {WorkbenchClient} from './client';

function listPath(input:OutputsListInput){const params=new URLSearchParams({limit:'50'});for(const key of ['parent','cursor','query','kind'] as const)if(input[key])params.set(key,input[key]!);return '/api/library/items?'+params;}
const sources=new WeakMap<WorkbenchClient,{epoch:number;source:OutputsDataSource}>();
/** Library metadata uses the host's existing authenticated read/cache owner. */
export function libraryDataSource(client:WorkbenchClient):OutputsDataSource{
 const saved=sources.get(client);if(saved?.epoch===client.authenticationEpoch)return saved.source;
 async function read<T>(path:string,force=false):Promise<T>{const value=await client.read<T>(path,force);if(value!==null)return value;const error=client.resource(path).getState().error||'内容读取失败，请重试。';throw Object.assign(new Error(error),error.includes('library_cursor_stale')?{code:'library_cursor_stale'}:{});}
 const source:OutputsDataSource={list:input=>read<OutputsListPage>(listPath(input),input.force),peek:input=>client.peek<OutputsListPage>(listPath(input)),resolve:path=>read('/api/library/resolve?'+new URLSearchParams({path}))};sources.set(client,{epoch:client.authenticationEpoch,source});return source;
}
