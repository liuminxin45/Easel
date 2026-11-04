import {useRef,useState} from 'react';
import Drawer from '../../components/Drawer';
import SettingsSelect from '../../components/SettingsSelect';
import {useDraft,useResource,useWorkbench} from './hooks';
import {Notice} from './common';
import {StatusCard} from '../../components/InteractionNotice';
import {acknowledgedCreationContext,creationContextPath,creationDraftKey,creationMissing,creationRequest,creationThumbnail,initialCreationDraft,linkedCreationSession,newsFormatLabel,newsSlotLabels,newsSlots,type NewsCreationContext,type NewsCreationDraft,type NewsCreationRequest,type NewsFormat} from './newsCreation';
import './news-creation.css';

export interface NewsCreationDrawerProps {
 articleId:string;profileId:string;sessionId?:string;onClose:()=>void;
 onStart:(articleId:string,creation:NewsCreationRequest,sessionId?:string)=>Promise<void>;
}
/** One original Drawer; the host owns session acceptance and execution. */
export default function NewsCreationDrawer(props:NewsCreationDrawerProps){
 const resource=useResource<NewsCreationContext>(creationContextPath(props.articleId,props.profileId));
 const [format,setFormat]=useState<NewsFormat|undefined>();
 const [acknowledged,setAcknowledged]=useState<{articleId:string;profileId:string;context:NewsCreationContext}|null>(null);
 const current=resource.data,ack=acknowledged?.articleId===props.articleId&&acknowledged.profileId===props.profileId?acknowledged.context:null;
 const context=current&&ack&&ack.profile_revision>=current.profile_revision?{...current,profile_revision:ack.profile_revision,defaults:ack.defaults}:current;
 return <Drawer title="制作内容" onClose={props.onClose}><div className="ew-news-creation">
  <Notice sources={[resource]}/>{!resource.data&&!resource.error&&<StatusCard className="ew-status-card-compact">正在读取创作设置…</StatusCard>}
  {context&&<><p className="ew-news-context-title">{context.source.title}</p>
   <fieldset className="ew-news-format"><legend>内容形式</legend>{context.formats.map(value=><button type="button" className={'btn'+(format===value?' btn-primary':'')} aria-pressed={format===value} key={value} onClick={()=>setFormat(value)}>{newsFormatLabel(value)}</button>)}</fieldset>
   {format?<CreationForm key={props.articleId+':'+props.profileId+':'+format} {...props} context={context} format={format} reload={resource.reload} onAcknowledged={value=>setAcknowledged({articleId:props.articleId,profileId:props.profileId,context:value})}/>:<p className="ew-news-muted">请选择贴图或文章，核对本次写法和画面后开始。</p>}
  </>}
 </div></Drawer>;
}

function CreationForm({context,format,reload,onAcknowledged,...props}:NewsCreationDrawerProps&{context:NewsCreationContext;format:NewsFormat;reload:()=>Promise<NewsCreationContext|null>;onAcknowledged:(value:NewsCreationContext)=>void}){
 const vm=useWorkbench(),[draft,patch]=useDraft<NewsCreationDraft>(creationDraftKey(props.articleId,props.profileId,format),()=>initialCreationDraft(context,format));
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[saved,setSaved]=useState(false),[illustrations,setIllustrations]=useState(!!(draft.style.visual||draft.style.character)),lock=useRef(false);
 const missing=creationMissing(context,draft,format),packs=context.packs.filter(pack=>pack.formats.includes(format)&&pack.available!==false);
 const run=async(saveDefault=false)=>{
  if(lock.current)return;lock.current=true;setBusy(true);setError('');setSaved(false);
  try{
   const request=creationRequest(context,'produce',draft,format);
   if(saveDefault){
    const result=await vm.service.creatorCommand('profile-save',{profile_id:props.profileId,base_revision:context.profile_revision,document:{creation_defaults:{...context.defaults,[format]:request.style}}});
    onAcknowledged(acknowledgedCreationContext(result,context));setSaved(true);
    void reload().catch(()=>{/* The resource reports refresh errors separately from the accepted save. */});
   }else await props.onStart(props.articleId,request,props.sessionId??linkedCreationSession(context,props.profileId));
  }catch(reason){setError(reason instanceof Error?reason.message:'操作未完成，本次选择已保留。')}
  finally{lock.current=false;setBusy(false)}
 };
 return <div className="ew-news-creation-form">
  {packs.length>0&&<label className="ew-news-field">已确认的风格组合<SettingsSelect label="已确认的风格组合" value="" disabled={busy} options={[{value:'',label:'按需选择组合'},...packs.map(pack=>({value:pack.id,label:pack.name}))]} onChange={id=>{const pack=packs.find(item=>item.id===id);if(pack){patch({style:{writing:'',visual:'',character:'',layout:'',...pack.components}});setIllustrations(!!(pack.components.visual||pack.components.character));setSaved(false)}}}/></label>}
  {newsSlots.filter(slot=>format==='poster'||slot==='writing'||slot==='layout'||illustrations).map(slot=>{const selected=context.components[slot]?.find(item=>item.id===draft.style[slot]),image=selected?.available?creationThumbnail(selected.thumbnail_url):undefined;return <div className="ew-news-field" key={slot}>
   <span className="field-label">{newsSlotLabels[slot]}</span>
   <SettingsSelect label={newsSlotLabels[slot]} value={draft.style[slot]} disabled={busy} options={[{value:'',label:format==='article'&&slot==='layout'?'不指定结构':'请选择'+newsSlotLabels[slot]},...(context.components[slot]??[]).filter(item=>item.available).map(item=>({value:item.id,label:item.name}))]} onChange={value=>{patch({style:{...draft.style,[slot]:value}});setSaved(false)}}/>
   {selected&&!selected.available&&<StatusCard className="ew-status-card-compact" tone="warning">{selected.reason||'这项风格当前不可用，请重新选择。'}</StatusCard>}
   {image&&<img className="ew-news-style-preview" loading="lazy" src={image} alt={selected!.name+'参考图'}/>}
   {slot==='writing'&&format==='article'&&<button type="button" className="btn" aria-expanded={illustrations} disabled={busy} onClick={()=>{setIllustrations(!illustrations);if(illustrations)patch({style:{...draft.style,visual:'',character:''}})}}>{illustrations?'移除配图风格':'设置配图风格'}</button>}
  </div>})}
  <label className="ew-news-field">补充要求<textarea aria-label="补充要求" className="field" rows={4} maxLength={40000} value={draft.note} disabled={busy} onChange={event=>patch({note:event.target.value})} placeholder="仅用于这一次制作，例如想强调的观点、需要避开的内容"/></label>
  {missing.length>0&&<p className="ew-news-muted">还需选择：{missing.map(slot=>newsSlotLabels[slot]).join('、')}</p>}
  {error&&<StatusCard className="ew-status-card-compact" tone="error">{error}<button type="button" className="btn btn-sm" disabled={busy} onClick={()=>void reload()}>重新读取设置</button></StatusCard>}
  {saved&&<StatusCard className="ew-status-card-compact" tone="ready">已保存为画像默认，本次尚未开始制作。</StatusCard>}
  <div className="ew-news-creation-actions"><button type="button" className="btn btn-primary" disabled={busy||missing.length>0} onClick={()=>void run()}>{busy?'正在处理…':format==='article'?'开始写文章':'开始制作贴图'}</button>
   <button type="button" className="btn" disabled={busy||missing.length>0} onClick={()=>void run(true)}>保存为画像默认</button></div>
 </div>;
}
