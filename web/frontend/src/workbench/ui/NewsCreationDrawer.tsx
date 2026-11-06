import {AuxiliarySkills} from './LocalSkillLibrary';
import {useRef,useState} from 'react';
import Drawer from '../../components/Drawer';
import SettingsSelect from '../../components/SettingsSelect';
import {useDraft,useResource,useWorkbench} from './hooks';
import {Markdown,Notice} from './common';
import {ExtensionDetails} from './ExtensionDetails';
import {StatusCard} from '../../components/InteractionNotice';
import {acknowledgedCreationContext,creationContextPath,creationDraftKey,creationDraftWithDefault,creationPackId,creationMissing,creationRequest,creationThumbnail,creationWithTemplate,initialCreationDraft,linkedCreationSession,newsFormatLabel,newsSlotLabels,newsSlots,productionTemplatePath,type ProductionTemplate,type NewsCreationContext,type NewsCreationDraft,type NewsCreationRequest,type NewsFormat} from './newsCreation';
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
 const vm=useWorkbench(),[stored,patch]=useDraft<NewsCreationDraft>(creationDraftKey(props.articleId,props.profileId,format),()=>initialCreationDraft(context,format));
 const draft=creationDraftWithDefault(context,format,stored);
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[saved,setSaved]=useState(false),[illustrations,setIllustrations]=useState(!!(draft.style.visual||draft.style.character)),lock=useRef(false);
 const missing=creationMissing(context,draft,format),packs=context.packs.filter(pack=>pack.formats.includes(format)&&pack.available!==false);
 const templates=context.templates?.[format]??[],selectedTemplate=templates.find(item=>item.id===draft.template_id),invalidTemplate=!!draft.template_id&&(!selectedTemplate?.available||selectedTemplate.revision!==draft.template_revision);
 const applyStyle=(style:NewsCreationDraft['style'])=>{patch({style});setIllustrations(!!(style.visual||style.character));setSaved(false);setError('')};
 const restoreLast=async()=>{
  if(lock.current)return;lock.current=true;setBusy(true);setError('');
  try{
   const fresh=await reload();
   if(!fresh)throw Error('未能读取最近的贴图风格，当前选择已保留。');
   const last=fresh.last_poster_style;
   if(!last)throw Error('暂无可恢复的已完成贴图风格记录。');
   const style={writing:'',visual:'',character:'',layout:'',...last.style};
   if(creationMissing(fresh,{style,note:draft.note},'poster').length)throw Error('上次风格当前不可用，当前选择已保留。');
   applyStyle(style);
  }catch(reason){setError(reason instanceof Error?reason.message:'读取未完成，当前选择已保留。')}
  finally{lock.current=false;setBusy(false)}
 };
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
  <AuxiliarySkills value={draft.auxiliary_skills||{}} format={format} disabled={busy} onChange={(auxiliary_skills,auxiliary_revision)=>patch({auxiliary_skills,auxiliary_revision})}/>
  {(templates.length>0||draft.template_id)&&<label className="ew-news-field">优秀制作模板<SettingsSelect label="优秀制作模板" value={draft.template_id??''} disabled={busy} options={[{value:'',label:'不使用优秀模板'},...templates.filter(template=>template.available&&!(invalidTemplate&&template.id===draft.template_id)).map(template=>({value:template.id,label:template.name})),...(invalidTemplate?[{value:draft.template_id!,label:(selectedTemplate?.name??'原模板')+' · 请重新核对'}]:[])]} onChange={id=>{try{const next=creationWithTemplate(context,format,draft,id);patch(next);setIllustrations(!!(next.style.visual||next.style.character));setSaved(false);setError('')}catch(reason){setError(reason instanceof Error?reason.message:'模板不可用')}}}/><span className="ew-news-muted">仅使用你已确认的制作方法和规范，本轮仍可调整风格与要求。</span></label>}
  {invalidTemplate&&<StatusCard className="ew-status-card-compact" tone="warning">{selectedTemplate?.reason||'原模板已更新或不可用，请重新选择模板，或选择不使用优秀模板。本次要求已保留。'}</StatusCard>}
  {selectedTemplate&&!invalidTemplate&&<TemplateDetails key={selectedTemplate.id+':'+selectedTemplate.revision} template={selectedTemplate} profileId={props.profileId}/>}
  {packs.length>0&&<label className="ew-news-field">已确认的风格组合<SettingsSelect label="已确认的风格组合" value={creationPackId(context,format,draft)} disabled={busy} options={[{value:'',label:'选择风格组合'},...packs.map(pack=>({value:pack.id,label:pack.name}))]} onChange={id=>{const pack=packs.find(item=>item.id===id);if(pack)applyStyle({writing:'',visual:'',character:'',layout:'',...pack.components})}}/></label>}
  {format==='poster'&&<div className="ew-news-preset-actions"><button type="button" className="btn" disabled={busy} onClick={()=>applyStyle(initialCreationDraft(context,'poster').style)}>恢复默认预设</button><button type="button" className="btn" disabled={busy} onClick={()=>void restoreLast()}>恢复上次贴图风格</button></div>}
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
  <div className="ew-news-creation-actions"><button type="button" className="btn btn-primary" disabled={busy||missing.length>0||invalidTemplate} onClick={()=>void run()}>{busy?'正在处理…':format==='article'?'开始写文章':'开始制作贴图'}</button>
   <button type="button" className="btn" disabled={busy||missing.length>0||invalidTemplate} onClick={()=>void run(true)}>保存为画像默认</button></div>
 </div>;
}

/** The full method is requested only when this selected template is opened. */
function TemplateDetails({template,profileId}:{template:ProductionTemplate;profileId:string}){
 const [open,setOpen]=useState(false),resource=useResource<ProductionTemplate&{method:string;references:{id:string;name:string;sha256:string}[]}>(open?productionTemplatePath(template.id,profileId,template.format,template.revision):null);
 return <ExtensionDetails title="模板方法与参考" onToggle={event=>setOpen(event.currentTarget.open)}>{open&&<><Notice sources={[resource]}/>{resource.data?<><Markdown text={resource.data.method}/>{resource.data.references.length>0&&<ul>{resource.data.references.map(reference=><li key={reference.id}>{reference.name} · {reference.sha256.slice(0,12)}</li>)}</ul>}<p className="ew-news-muted">参考来源版本：{resource.data.source_version_id}。只沿用制作方法与规范，不自动复用旧新闻。</p></>:!resource.error&&<StatusCard className="ew-status-card-compact">正在读取模板方法…</StatusCard>}</>}</ExtensionDetails>;
}
