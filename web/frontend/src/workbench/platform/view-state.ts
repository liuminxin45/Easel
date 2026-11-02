/** Bounded, in-memory UI metadata. Server documents and secrets do not belong here. */
export class ViewStateRepository {
 private rows=new Map<string,{path:string;scope:string;value:unknown;size:number}>();
 private bytes=0;
 constructor(private maxEntries=256,private maxBytes=1024*1024){}
 clear(){this.rows.clear();this.bytes=0}
 read<T>(entry:string,path:string,scope:string):T|null{
  const key=entry+'\0'+scope;let row=this.rows.get(key);
  if(!row)row=[...this.rows.values()].reverse().find(value=>value.path===path&&value.scope===scope);
  if(!row)return null;
  return JSON.parse(JSON.stringify(row.value)) as T;
 }
 write<T>(entry:string,path:string,scope:string,value:T){
  let raw:string;try{raw=JSON.stringify(value)}catch{return}
  if(raw===undefined||raw.length>65536)return;
  const key=entry+'\0'+scope,old=this.rows.get(key);if(old)this.bytes-=old.size;
  this.rows.delete(key);this.rows.set(key,{path,scope,value:JSON.parse(raw),size:raw.length*2});this.bytes+=raw.length*2;
  while(this.rows.size>this.maxEntries||this.bytes>this.maxBytes){const key=this.rows.keys().next().value;if(key===undefined)break;this.bytes-=this.rows.get(key)!.size;this.rows.delete(key)}
 }
}
