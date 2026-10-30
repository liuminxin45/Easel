export interface NewsNavigationContext {source?:string;day?:string;issue?:string;section?:string;theme?:string;sources?:string;windows?:string}
export function newsListPath(context:NewsNavigationContext):string {const query=new URLSearchParams();for(const key of ['source',context.issue?'issue':'day','section','theme','sources','windows'] as const){const value=context[key as keyof NewsNavigationContext];if(value!==undefined)query.set(key,value)}return '/news'+(query.size?'?'+query:'')}
export function newsDetailPath(id:string,context:NewsNavigationContext):string {return '/news/a/'+encodeURIComponent(id)+newsListPath(context).slice('/news'.length)}
export function navigationIdentity(path:string):string {const url=new URL(path,'https://workbench.invalid');url.searchParams.sort();return url.pathname+(url.searchParams.size?'?'+url.searchParams:'')}

/** A direct item link derives its collection window from that item, never the latest list. */
export function newsItemContext(item:{source_job?:unknown;run_at?:unknown;periodical?:unknown},selected:NewsNavigationContext={}):NewsNavigationContext {
 const source=typeof item.source_job==='string'?item.source_job:selected.source,periodical=item.periodical&&typeof item.periodical==='object'?item.periodical as Record<string,unknown>:{},issue=typeof periodical.issue_id==='string'?periodical.issue_id:undefined;
 let day:string|undefined;
 if(!issue&&typeof item.run_at==='string'){let raw=item.run_at.replace(' ','T');if(!/(Z|[+-]\d{2}:?\d{2})$/i.test(raw))raw+='Z';const instant=Date.parse(raw);if(Number.isFinite(instant))day=new Date(instant+8*3600000).toISOString().slice(0,10)}
 const compatible=(!selected.source||selected.source===source)&&(!selected.issue||selected.issue===issue)&&(!selected.day||!day||selected.day===day);
 return {source,...(issue?{issue}:{day:day||selected.day}),...(compatible&&selected.section?{section:selected.section}:{}),...(compatible&&selected.theme?{theme:selected.theme}:{}),...(selected.sources!==undefined?{sources:selected.sources}:{}),...(selected.windows?{windows:selected.windows}:{})};
}

export function newsWindows(value:string|null):Record<string,NewsNavigationContext>{
 try{const parsed:unknown=JSON.parse(value||'{}');if(!parsed||typeof parsed!=='object'||Array.isArray(parsed))return {};
 return Object.fromEntries(Object.entries(parsed).slice(0,73).filter(([id])=>/^[A-Za-z0-9_-]{1,80}$/.test(id)).map(([id,value])=>[id,Object.fromEntries(Object.entries(value&&typeof value==='object'?value:{}).filter(([key,v])=>['day','issue','section','theme'].includes(key)&&typeof v==='string'&&v.length<=300))]));}catch{return {}}
}
