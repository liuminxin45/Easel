/** Private event adapter around the original MessageBubble HTML. */
export function copySectionLabel(value:string):string|null {
 const name=value.trim().replace(/[：:]$/,'').trim();
 return ['标题','文章标题','贴图标题','封面标题','正文','配文'].includes(name)?name:null;
}

export async function copyLiteralText(text:string,document:Document):Promise<void>{
 const clipboard=document.defaultView?.navigator.clipboard;
 if(clipboard?.writeText){try{await clipboard.writeText(text);return}catch{/* WebViews may require the compatibility path. */}}
 const active=document.activeElement as HTMLElement|null,selection=document.getSelection(),ranges:Range[]=[];
 if(selection)for(let i=0;i<selection.rangeCount;i++)ranges.push(selection.getRangeAt(i).cloneRange());
 const input=document.createElement('textarea');input.value=text;input.readOnly=true;
 input.setAttribute('aria-hidden','true');input.style.cssText='position:fixed;inset:0 auto auto 0;width:1px;height:1px;opacity:0;pointer-events:none;font-size:16px';
 document.body.append(input);
 try{input.focus({preventScroll:true});input.select();if(!document.execCommand('copy'))throw Error('clipboard_unavailable')}
 finally{input.remove();active?.focus({preventScroll:true});if(selection){selection.removeAllRanges();for(const range of ranges)selection.addRange(range)}}
}

/** Bind per committed message update; no polling, observer or backend I/O. */
export function attachChatTextCopy(root:HTMLElement|null):()=>void {
 if(!root)return ()=>{};
 const document=root.ownerDocument,window=document.defaultView!;
 const fields:{pre:HTMLElement;heading:HTMLElement;label:string}[]=[],restore:(()=>void)[]=[],timers=new Map<HTMLElement,number>();
 let disposed=false,gesture:{field:HTMLElement;x:number;y:number;time:number;moved:boolean}|null=null;
 function attribute(node:HTMLElement,name:string,value:string){const previous=node.getAttribute(name);node.setAttribute(name,value);restore.push(()=>previous===null?node.removeAttribute(name):node.setAttribute(name,previous))}
 for(const pre of root.querySelectorAll<HTMLElement>('.message-bubble.assistant pre')){
  if(pre.closest('.message-bubble')?.querySelector('.streaming-cursor'))continue;
  const heading=pre.previousElementSibling as HTMLElement|null;
  if(!heading||!heading.matches('p,h1,h2,h3,h4,h5,h6')||heading.querySelector('a,button,input'))continue;
  const label=copySectionLabel(heading.textContent||'');if(!label||!pre.querySelector('code')?.textContent?.trim())continue;
  fields.push({pre,heading,label});
  attribute(pre,'data-ew-copy-target',label);attribute(pre,'role','button');attribute(pre,'tabindex','0');attribute(pre,'aria-label','点按复制完整'+label);attribute(pre,'title','点按复制完整'+label);
  attribute(heading,'data-ew-copy-label',label);attribute(heading,'title','点按复制完整'+label);
 }
 if(!fields.length)return ()=>{};
 const live=document.createElement('span');live.className='ew-chat-copy-announcement';live.setAttribute('role','status');live.setAttribute('aria-live','polite');root.append(live);
 const find=(target:EventTarget|null)=>target instanceof Element?fields.find(field=>field.pre.contains(target)||field.heading.contains(target)):undefined;
 const hasSelection=()=>!!document.getSelection()?.toString();
 function feedback(field:typeof fields[number],message:string,error=false){
  if(disposed)return;
  const timer=timers.get(field.heading);if(timer)window.clearTimeout(timer);
  field.heading.dataset.ewCopyFeedback=message;field.heading.dataset.ewCopyError=String(error);live.textContent=message;
  if(!error)timers.set(field.heading,window.setTimeout(()=>{field.heading.removeAttribute('data-ew-copy-feedback');field.heading.removeAttribute('data-ew-copy-error');timers.delete(field.heading)},1600));
 }
 function copy(field:typeof fields[number]){
  if(field.pre.closest('.message-bubble')?.querySelector('.streaming-cursor'))return;
  const code=field.pre.querySelector('code');if(!code)return;
  // Marked adds a terminal newline to fenced blocks; internal whitespace,
  // paragraphs, punctuation and URLs remain literal text, never Markdown/HTML.
  const text=(code.textContent||'').replace(/\n$/,'');
  void copyLiteralText(text,document).then(()=>feedback(field,'已复制'+field.label),()=>feedback(field,'复制失败，请重试',true));
 }
 const down=(event:PointerEvent)=>{const field=find(event.target);gesture=field?{field:field.pre,x:event.clientX,y:event.clientY,time:Date.now(),moved:false}:null};
 const move=(event:PointerEvent)=>{if(gesture&&Math.hypot(event.clientX-gesture.x,event.clientY-gesture.y)>8)gesture.moved=true};
 const cancel=()=>{if(gesture)gesture.moved=true};
 const click=(event:MouseEvent)=>{
  const field=find(event.target);if(!field||event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.altKey||event.shiftKey||hasSelection())return;
  if(event.detail!==0&&gesture&&(gesture.field!==field.pre||gesture.moved||Date.now()-gesture.time>550))return;
  copy(field);
 };
 const key=(event:KeyboardEvent)=>{const field=find(event.target);if(field&&event.target===field.pre&&!event.repeat&&!event.isComposing&&(event.key==='Enter'||event.key===' ')){event.preventDefault();copy(field)}};
 root.addEventListener('pointerdown',down);root.addEventListener('pointermove',move);root.addEventListener('pointercancel',cancel);root.addEventListener('scroll',cancel,true);root.addEventListener('click',click);root.addEventListener('keydown',key);
 return ()=>{
  disposed=true;for(const timer of timers.values())window.clearTimeout(timer);
  root.removeEventListener('pointerdown',down);root.removeEventListener('pointermove',move);root.removeEventListener('pointercancel',cancel);root.removeEventListener('scroll',cancel,true);root.removeEventListener('click',click);root.removeEventListener('keydown',key);
  for(const field of fields){field.heading.removeAttribute('data-ew-copy-feedback');field.heading.removeAttribute('data-ew-copy-error')}
  for(const undo of restore)undo();live.remove();
 };
}
