import type {OutputNode} from './api';

export interface OutputsListInput {parent?:string;cursor?:string;query?:string;kind?:string;force?:boolean}
export interface OutputsListPage {items:OutputNode[];next_cursor:string|null;revision:string;parent?:OutputNode;indexing?:boolean;total?:number}
/** Optional host port; the ordinary Easel gallery still owns its original tree. */
export interface OutputsDataSource {
 list(input:OutputsListInput):Promise<OutputsListPage>;
 resolve(path:string):Promise<{nodes:OutputNode[]}>;
 peek?(input:OutputsListInput):OutputsListPage|undefined;
}
export interface OutputsBrowserState {key:string;items:OutputNode[];directories:OutputNode[];next_cursor:string|null;revision:string;loading:boolean;loadingMore:boolean;error:string;indexing:boolean}
const empty=(key=''):OutputsBrowserState=>({key,items:[],directories:[],next_cursor:null,revision:'',loading:false,loadingMore:false,error:'',indexing:false});
const keyFor=(input:OutputsListInput)=>JSON.stringify([input.parent||'',input.query||'',input.kind||'']);
const append=(first:OutputNode[],next:OutputNode[])=>{const seen=new Set(first.map(row=>row.path));return [...first,...next.filter(row=>!seen.has(row.path)&&seen.add(row.path))]};
const message=(error:unknown)=>error instanceof Error?error.message:'内容读取失败，请重试。';

/** One bounded, path-keyed browser per data source. No filesystem/model access. */
export class OutputsBrowser {
 private current=empty();private listeners=new Set<()=>void>();private pages=new Map<string,OutputsListPage>();private nodes=new Map<string,OutputNode>();private sequence=0;private selection:OutputsListInput={};private stack:string[]=[];private resolvedPaths:string[]=[];private inFlightMore?:Promise<void>;private cursorRestarts=0;
 readonly source:OutputsDataSource;
 constructor(source:OutputsDataSource){this.source=source;}
 snapshot=()=>this.current;
 directoryNodes(paths:string[]):OutputNode[]{return paths.map(path=>this.nodes.get(path)).filter((row):row is OutputNode=>!!row&&row.type==='dir')}
 subscribe=(listener:()=>void)=>{this.listeners.add(listener);return()=>{this.listeners.delete(listener)}};
 private publish(value:OutputsBrowserState){this.current=value;for(const listener of this.listeners)listener()}
 private remember(page:OutputsListPage){for(const row of page.items)this.nodes.set(row.path,row);if(page.parent)this.nodes.set(page.parent.path,page.parent);}
 private directories(){return this.stack.map(path=>this.nodes.get(path)).filter((row):row is OutputNode=>!!row&&row.type==='dir')}
 private pruneNodes(){const keep=new Set([...this.stack,...this.resolvedPaths]);for(const page of this.pages.values()){for(const node of page.items)keep.add(node.path);if(page.parent)keep.add(page.parent.path);}for(const path of this.nodes.keys())if(!keep.has(path))this.nodes.delete(path);}
 private put(key:string,page:OutputsListPage){this.pages.delete(key);this.pages.set(key,page);while(this.pages.size>32)this.pages.delete(this.pages.keys().next().value!);this.pruneNodes();}
 cacheSizes(){return {pages:this.pages.size,nodes:this.nodes.size}}
 async select(input:OutputsListInput,stack:string[]=[],force=false,fromCursor=false):Promise<void>{
  if(!fromCursor)this.cursorRestarts=0;
  const seq=++this.sequence,key=keyFor(input),old=this.pages.get(key)||this.source.peek?.(input);this.selection={...input,cursor:undefined};this.stack=[...stack];this.inFlightMore=undefined;
  if(old)this.remember(old);
  this.publish({...empty(key),...(old?{items:old.items,next_cursor:old.next_cursor,revision:old.revision,indexing:!!old.indexing}:{}),directories:this.directories(),loading:!old});
  if(stack.some(path=>!this.nodes.has(path))&&input.parent){
   void this.source.resolve(input.parent).then(result=>{if(seq!==this.sequence)return;this.resolvedPaths=result.nodes.map(node=>node.path);for(const node of result.nodes)this.nodes.set(node.path,node);this.pruneNodes();this.publish({...this.current,directories:this.directories()})}).catch(()=>{/* The visible list request owns a single actionable read error. */});
  }
  try{
   const page=await this.source.list({...input,cursor:undefined,force});if(seq!==this.sequence)return;
   this.remember(page);const combined=old&&old.revision===page.revision&&!force?{...page,items:append(page.items,old.items),next_cursor:old.next_cursor}:page;
   this.put(key,combined);this.publish({...empty(key),items:combined.items,next_cursor:combined.next_cursor,revision:combined.revision,indexing:!!combined.indexing,directories:this.directories()});
   // A changed revision restarts cursors but restores only the amount the user
   // had already opened in this directory, never the complete library tree.
   const restore=old?.items.length||0;while(seq===this.sequence&&this.current.items.length<restore&&this.current.next_cursor&&!this.current.indexing){const count=this.current.items.length,cursor=this.current.next_cursor;await this.more();if(this.current.error||this.current.items.length===count&&this.current.next_cursor===cursor)break;}
  }catch(error){if(seq===this.sequence)this.publish({...this.current,loading:false,loadingMore:false,error:message(error)})}
 }
 more():Promise<void>{
  if(this.inFlightMore)return this.inFlightMore;const cursor=this.current.next_cursor;if(!cursor||this.current.loading||this.current.indexing)return Promise.resolve();
  const seq=this.sequence,key=this.current.key,input={...this.selection,cursor};this.publish({...this.current,loadingMore:true,error:''});
  let job!:Promise<void>;job=(async()=>{try{
   const page=await this.source.list(input);if(seq!==this.sequence||key!==this.current.key)return;
   if(page.revision!==this.current.revision){if(this.cursorRestarts++>=1)throw Error('内容正在更新，请刷新后继续。');await this.select(this.selection,this.stack,true,true);return;}
   this.remember(page);const combined={...page,items:append(this.current.items,page.items)};this.put(key,combined);this.publish({...this.current,items:combined.items,next_cursor:combined.next_cursor,indexing:!!combined.indexing,directories:this.directories(),loadingMore:false});
  }catch(error){if(seq!==this.sequence)return;const detail=error as {status?:number;code?:string};if(detail.status===409||detail.code==='library_cursor_stale'||message(error).includes('library_cursor_stale')){if(this.cursorRestarts++>=1){this.publish({...this.current,loadingMore:false,error:'内容正在更新，请刷新后继续。'});return;}await this.select(this.selection,this.stack,true,true);return;}this.publish({...this.current,loadingMore:false,error:message(error)})}
  finally{if(this.inFlightMore===job)this.inFlightMore=undefined}})();this.inFlightMore=job;return job;
 }
 async resolve(path:string){const result=await this.source.resolve(path);this.resolvedPaths=result.nodes.map(row=>row.path);for(const row of result.nodes)this.nodes.set(row.path,row);this.pruneNodes();return result.nodes;}
 cancel(){this.sequence++;this.inFlightMore=undefined;}
}
const browsers=new WeakMap<OutputsDataSource,OutputsBrowser>();
export function outputsBrowser(source:OutputsDataSource){let browser=browsers.get(source);if(!browser){browser=new OutputsBrowser(source);browsers.set(source,browser)}return browser;}
