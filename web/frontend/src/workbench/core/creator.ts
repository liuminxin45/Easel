import {array,record,string,number,type CreativeOptions,type DraftAttachment,type JsonRecord,type Tool} from './models';

export interface CreatorSkillRef {id:string;version?:number}
export interface CreatorSelection {profile_id:string;profile_revision?:number;skills:CreatorSkillRef[];trial?:boolean}
export interface CreatorProfile extends JsonRecord {id:string;name:string;revision:number;identity:string;audience:string;voice:string;boundaries:string;default_skills:Record<string,string[]>;skill_versions?:Record<string,number>;task_skill_versions?:Record<string,Record<string,number>>;account_ids:string[];asset_refs:unknown[];active:boolean}
export interface CreatorSkillVersion extends JsonRecord {version:number;status:string;prompt:string;sha256?:string;reason?:string;conditions?:unknown;evidence_refs?:unknown[]}
export interface CreatorLaunchAction {id:string;label:string;path:string;task:string;format?:string;requires_context?:boolean}
export interface CreatorTaskPolicy {required_all:string[];required_any:string[][];entry_skills:string[]}
export interface CreatorSkill extends JsonRecord {id:string;name:string;description:string;published_version:number;status:string;versions:CreatorSkillVersion[];execution_kind?:string;launch_actions:CreatorLaunchAction[]}
export interface CreatorAccount extends JsonRecord {id:string;platform:string;account?:string;label?:string;status:string}
export interface CreatorBootstrap extends JsonRecord {schema_version:number;default_profile_id:string;profiles:CreatorProfile[];skills:CreatorSkill[];accounts:CreatorAccount[];task_defaults:Record<string,string[]>;task_policy:Record<string,CreatorTaskPolicy>;learning:{mode:string}}
export interface CreatorSkillDetail extends JsonRecord {id:string;name:string;description:string;version:number;published_version:number;status:string;prompt:string;resources:JsonRecord[];input_contract:unknown;output_contract:unknown;acceptance_cases:unknown[];history:JsonRecord[];launch_actions:CreatorLaunchAction[]}

export function creatorProfile(data:CreatorBootstrap|null|undefined,id?:string):CreatorProfile|undefined{return data?.profiles.find(p=>p.id===(id||data.default_profile_id))}
export function creatorSelection(data:CreatorBootstrap,profileId:string,task='poster'):CreatorSelection{
 const profile=creatorProfile(data,profileId);if(!profile)throw Error('创作画像不可用，请重新选择');
 const ids=profile.default_skills[task]||data.task_defaults[task]||[];
 return {profile_id:profile.id,profile_revision:profile.revision,skills:ids.flatMap(id=>{const skill=data.skills.find(s=>s.id===id);return skill?.published_version?[{id,version:profile.task_skill_versions?.[task]?.[id]||profile.skill_versions?.[id]||skill.published_version}]:[]})};
}
export function switchCreator(value:CreativeOptions,data:CreatorBootstrap,profileId:string,task:string):CreativeOptions{const next={...value,creator:creatorSelection(data,profileId,task),recipe:{pack_id:task==='article'?'editorial-article':'editorial-poster'}};delete next.learning;delete next.intent;delete next.values;delete next.preset_id;return next}
export function creatorSkillLabels(data:CreatorBootstrap|undefined|null,selection:CreatorSelection|undefined):string[]{return (selection?.skills||[]).map(ref=>(data?.skills.find(s=>s.id===ref.id)?.name||ref.id)+(ref.version?' · '+ref.version:''))}
export function creatorSkillRequired(data:CreatorBootstrap,id:string,task:string,selection:CreatorSelection|undefined):boolean{const policy=data.task_policy?.[task],ids=(selection?.skills||[]).map(s=>s.id);return ids.length===1&&ids[0]===id||!!policy&&(policy.required_all.includes(id)||policy.required_any.some(group=>group.includes(id)&&!group.some(other=>other!==id&&ids.includes(other))))}
export function creatorTaskSelection(data:CreatorBootstrap,selection:CreatorSelection,task:string):CreatorSelection{const defaults=creatorSelection(data,selection.profile_id,task),skills=(selection.skills||defaults.skills).filter(ref=>array<string>(data.skills.find(s=>s.id===ref.id)?.tasks).includes(task));if(!skills.length)skills.push(...defaults.skills);const ids=skills.map(s=>s.id);for(const ref of defaults.skills){const required=creatorSkillRequired(data,ref.id,task,{...selection,skills});if(required&&!ids.includes(ref.id)){skills.push(ref);ids.push(ref.id)}}return {...selection,skills}}
/** Wait only for deterministic input metadata, never for an AI assessment. */
export function creatorCreationReady(value:CreativeOptions,data:CreatorBootstrap|null|undefined,profileId:string,task:string):boolean{const profile=creatorProfile(data,profileId);return !!(data&&profile?.active&&value.creator?.profile_id===profileId&&(task==='text'||value.recipe?.pack_id))}
export function creatorCommandResult(value:unknown):JsonRecord{return record(record(value).result)}
/** Input references only: never persist the profile resource response or URLs in a browser draft. */
export function creatorAssetInputs(value:unknown):JsonRecord[]{return array<JsonRecord>(value).flatMap(ref=>{const binding=typeof ref.file_id==='string'?{file_id:ref.file_id}:typeof ref.path==='string'?{path:ref.path,...(typeof ref.sha256==='string'?{sha256:ref.sha256}:{})}:null;return binding?[{...binding,label:string(ref.label)||'角色或品牌参考',role:string(ref.role)||'reference',required:ref.required!==false}]:[]})}
export function creatorAssetResource(ref:JsonRecord,live:unknown[]):JsonRecord|undefined{return array<JsonRecord>(live).find(asset=>typeof ref.path==='string'&&ref.path.length>0&&asset.path===ref.path&&(typeof ref.sha256!=='string'||asset.sha256===ref.sha256)||typeof ref.file_id==='string'&&ref.file_id.length>0&&record(asset.provenance).file_id===ref.file_id)}
export function validateCreatorAssetFiles(files:{name:string;type:string;size:number}[],refs:unknown[],pending:DraftAttachment[],live:unknown[]=[]):void{if(refs.length+pending.length+files.length>8)throw Error('每个画像最多添加8张参考图');for(const file of files)if(!['image/png','image/jpeg','image/webp'].includes(file.type)&&!/\.(png|jpe?g|webp)$/i.test(file.name))throw Error('请选择 PNG、JPEG 或 WebP 静态图片');const existing=array<JsonRecord>(refs).reduce((total,r)=>total+number(array<JsonRecord>(live).find(a=>a.path===r.path)?.size),0),bytes=files.reduce((n,f)=>n+f.size,0)+pending.reduce((n,f)=>n+number(f.size),0)+existing;if(bytes>40*1024*1024)throw Error('一个画像的参考图合计不能超过40MB')}
export function creatorExecutionStatus(value:unknown):string{return ({waiting:'等待',pending:'等待',queued:'等待执行',running:'运行中',leased:'运行中',completed:'成功',succeeded:'成功',failed:'失败',error:'失败',blocked:'需要处理',unknown:'结果待核对',uncertain:'结果待核对',not_requested:'本轮未请求',not_started:'尚未执行',skipped:'未执行',reused:'复用已核验结果'} as Record<string,string>)[string(value)]||'状态待核对'}
export function creatorPath(section:'profiles'|'skills'|'research',item='',pane='',extra:Record<string,string>={}):string{return '/toolbox?'+new URLSearchParams({section,...(item?{item}:{}),...(pane?{pane}:{}),...extra})}
/** The server owns action destinations; the selected detail owns the exact version. */
export function creatorLaunchPath(action:CreatorLaunchAction,skill:Pick<CreatorSkillDetail,'id'|'version'|'status'>,profileId:string):string{
 if(!action.path.startsWith('/')||action.path.startsWith('//'))throw Error('技能入口无效');
 const target=new URL(action.path,'https://workbench.invalid');if(target.origin!=='https://workbench.invalid')throw Error('技能入口无效');
 target.searchParams.set('profile',profileId);target.searchParams.set('skill',skill.id);target.searchParams.set('skill_version',String(skill.version));
 if(skill.status!=='published')target.searchParams.set('trial','1');else target.searchParams.delete('trial');
 return target.pathname+target.search;
}
export function creatorNavigation(tools:Tool[]):{daily:Tool[];management:Tool[];extra:Tool[]}{const dailyIds=['workbench','research','content','publications'],managementIds=['profiles','skills','accounts'],ordered=(ids:string[])=>ids.flatMap(id=>{const tool=tools.find(t=>t.id===id);return tool?[tool]:[]}),used=new Set([...dailyIds,...managementIds]);return {daily:ordered(dailyIds),management:ordered(managementIds),extra:tools.filter(t=>!used.has(t.id)&&!['news','posters','articles','learning','foundation','insights'].includes(t.id))}}
export function creatorActive(tool:Tool,value:string):boolean{
 const u=new URL(value,'https://workbench.invalid'),s=u.searchParams.get('section')||'';
 if(tool.id==='workbench')return ['/', '/toolbox'].includes(u.pathname)&&!s;
 if(tool.id==='research')return u.pathname.startsWith('/news')||s==='research';
 if(tool.id==='content')return /^\/(posters|articles|works)(\/|$)/.test(u.pathname);
 if(tool.id==='publications')return ['publications','insights'].includes(s)||s==='distribution'&&u.searchParams.get('pane')!=='connections';
 if(tool.id==='accounts')return s==='distribution'&&u.searchParams.get('pane')==='connections';
 return s===tool.id;
}
export function creatorPromptSummary(value:unknown):{profile:string;skills:string[];trial:boolean;hasPrompt:boolean}{
 const root=record(value),prompt=record(root.execution_prompt),frozen=record(prompt.creator_snapshot||prompt.creator||root.creator_snapshot||root.creator),profile=record(frozen.profile),refs=array<JsonRecord>(frozen.skills);
 return {profile:string(profile.name)||string(frozen.profile_name),skills:refs.map(r=>(string(r.name)||string(r.id))+(r.version?' · v'+String(r.version):'')),trial:frozen.trial===true,hasPrompt:!!prompt.body};
}
export function creatorTrialFromSearch(value:CreativeOptions,search:URLSearchParams,data:CreatorBootstrap,profileId:string,task:string):CreativeOptions{
 const id=search.get('skill'),raw=search.get('skill_version'),version=Number(raw);if(!id||!raw||!Number.isSafeInteger(version)||version<1)return value;
 if(!array<string>(data.skills.find(s=>s.id===id)?.tasks).includes(task))return value;
 const base=value.creator||creatorSelection(data,profileId,task),refs=base.skills||creatorSelection(data,base.profile_id,task).skills,trial=search.get('trial')==='1';if(refs.some(s=>s.id===id&&s.version===version)&&!!base.trial===trial)return value;
 return {...value,creator:{...base,skills:refs.filter(s=>s.id!==id).concat({id,version}),trial}};
}
/** Freeze a supported exact launch ref separately from an experience's improvement target. */
export function creatorLaunchSelection(data:CreatorBootstrap,profileId:string,task:string,search:URLSearchParams):CreatorSelection{return creatorTrialFromSearch({creator:creatorSelection(data,profileId,task)},search,data,profileId,task).creator!}
