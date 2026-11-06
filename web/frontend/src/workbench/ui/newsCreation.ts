export type NewsFormat='poster'|'article';
/** New creation uses an explicit format; accepted historical turns keep their frozen skill. */
export function creationSkillId(format:unknown):'oil-pig-poster'|'oil-pig-article' {
 if(format==='poster')return 'oil-pig-poster';
 if(format==='article')return 'oil-pig-article';
 throw Error('请明确选择贴图或文章，原材料已保留。');
}
/** Only a new draft's retired/default selection is migrated, never an accepted turn. */
export function creationDraftSkillId(format:unknown,selected?:string):string {
 return !selected||selected==='content-production'?creationSkillId(format):selected;
}
export type NewsSlot='writing'|'visual'|'character'|'layout';
export type NewsStyle=Partial<Record<NewsSlot,string>>;
export interface NewsComponent {id:string;name:string;slot:NewsSlot;available:boolean;reason?:string;thumbnail_url?:string}
export interface ProductionTemplate {id:string;revision:string;name:string;style:NewsStyle;available:boolean;reason?:string;format:NewsFormat;source_version_id:string}
export interface NewsCreationRequest {auxiliary_skills?:Record<string,string>;auxiliary_revision?:string;intent:'discuss'|'produce';format?:NewsFormat;style?:NewsStyle;catalog_revision:string;source_revision:string;profile_revision:number;note:string;template_id?:string;template_revision?:string}
export interface NewsCreationContext {
 catalog_revision:string;source_revision:string;profile_revision:number;
 formats:NewsFormat[];components:Record<NewsSlot,NewsComponent[]>;
 packs:{id:string;name:string;formats:NewsFormat[];components:NewsStyle;available?:boolean}[];
 defaults:Partial<Record<NewsFormat,Partial<NewsStyle>>>;
 last_poster_style?:{turn_id:string;style:NewsStyle}|null;
 templates?:Partial<Record<NewsFormat,ProductionTemplate[]>>;
 source:{id:string;title:string;reading_summary?:string;publisher?:string;published_at?:string;url?:string};
 linked_session?:{id:string;profile_id:string;archived?:boolean;deleted_at?:string;pendingTurnId?:string;pendingSubmissionId?:string}|null;
}
export interface NewsCreationDraft {auxiliary_skills?:Record<string,string>;auxiliary_revision?:string;style:Record<NewsSlot,string>;note:string;template_id?:string;template_revision?:string}
export const newsSlots:NewsSlot[]=['writing','visual','character','layout'];
export const newsSlotLabels:Record<NewsSlot,string>={writing:'写法',visual:'画面风格',character:'角色呈现',layout:'画面与结构'};
export const newsFormatLabel=(format:NewsFormat)=>format==='poster'?'贴图':'文章';
export const creationContextPath=(articleId:string,profileId:string)=>'/api/news/'+encodeURIComponent(articleId)+'/creation-context?profile_id='+encodeURIComponent(profileId);
export const productionTemplatePath=(id:string,profileId:string,format:NewsFormat,revision:string)=>'/api/production-insights/templates/'+encodeURIComponent(id)+'?'+new URLSearchParams({profile_id:profileId,format,revision}).toString();
export const creationDraftKey=(articleId:string,profileId:string,format:NewsFormat)=>'news:creation:'+encodeURIComponent(articleId)+':'+encodeURIComponent(profileId)+':'+format;
export function initialCreationDraft(context:NewsCreationContext,format:NewsFormat):NewsCreationDraft {
 const defaults=context.defaults[format]??(format==='poster'?context.packs.find(pack=>pack.id==='editorial-poster'&&pack.formats.includes(format)&&pack.available!==false)?.components:undefined)??{};
 return {style:Object.fromEntries(newsSlots.map(slot=>[slot,context.components[slot]?.some(item=>item.id===defaults[slot]&&item.available)?defaults[slot]:''])) as Record<NewsSlot,string>,note:''};
}
/** Older empty drafts get the default; explicit partial choices and notes win. */
export function creationDraftWithDefault(context:NewsCreationContext,format:NewsFormat,draft:NewsCreationDraft):NewsCreationDraft {
 return format==='poster'&&!newsSlots.some(slot=>draft.style[slot])?{...draft,...initialCreationDraft(context,format),note:draft.note}:draft;
}
export function creationPackId(context:NewsCreationContext,format:NewsFormat,draft:NewsCreationDraft):string {
 return context.packs.find(pack=>pack.formats.includes(format)&&pack.available!==false&&newsSlots.every(slot=>(pack.components[slot]??'')===draft.style[slot]))?.id??'';
}
export function creationMissing(context:NewsCreationContext,draft:NewsCreationDraft,format:NewsFormat='poster'):NewsSlot[]{
 const slots:NewsSlot[]=format==='poster'?newsSlots:['writing',...(draft.style.visual||draft.style.character?['visual','character'] as NewsSlot[]:[]),...(draft.style.layout?['layout'] as NewsSlot[]:[])];
 return slots.filter(slot=>!context.components[slot]?.some(item=>item.id===draft.style[slot]&&item.available));
}
export function creationRequest(context:NewsCreationContext,intent:'discuss'|'produce',draft:NewsCreationDraft,format?:NewsFormat):NewsCreationRequest {
 if(intent==='produce'&&(!format||!context.formats.includes(format)||creationMissing(context,draft,format).length))throw Error('请完成本次创作选项。');
 const template=intent==='produce'&&draft.template_id?context.templates?.[format!]?.find(item=>item.id===draft.template_id&&item.revision===draft.template_revision&&item.available&&item.format===format):undefined;
 if(intent==='produce'&&draft.template_id&&!template)throw Error('所选优秀模板当前不可用，请重新选择；本次要求已保留。');
 return {intent,...(intent==='produce'?{...(Object.keys(draft.auxiliary_skills||{}).length?{auxiliary_skills:draft.auxiliary_skills,auxiliary_revision:draft.auxiliary_revision}:{}),format,style:Object.fromEntries(Object.entries(draft.style).filter(([,value])=>value)),...(template?{template_id:template.id,template_revision:template.revision}:{})}:{}),catalog_revision:context.catalog_revision,source_revision:context.source_revision,profile_revision:context.profile_revision,note:draft.note};
}
export function creationWithTemplate(context:NewsCreationContext,format:NewsFormat,draft:NewsCreationDraft,id:string):NewsCreationDraft {
 if(!id)return {...draft,template_id:undefined,template_revision:undefined};
 const template=context.templates?.[format]?.find(item=>item.id===id&&item.available&&item.format===format);
 if(!template)throw Error('优秀模板当前不可用，原有选择已保留。');
 return {...draft,template_id:template.id,template_revision:template.revision,style:{writing:'',visual:'',character:'',layout:'',...template.style}};
}
/** Only catalog-served image capabilities may be rendered; never arbitrary paths. */
export function creationThumbnail(value?:string):string|undefined {
 return value&&/^\/api\/news\/creation-assets\/[^/?#]+\/\d+$/.test(value)?value:undefined;
}
export function linkedCreationSession(context:NewsCreationContext,profileId:string):string|undefined {
 const linked=context.linked_session;
 return linked&&linked.profile_id===profileId&&!linked.archived&&!linked.deleted_at?linked.id:undefined;
}
export function acknowledgedCreationContext(value:unknown,context:NewsCreationContext):NewsCreationContext {
 const envelope=value as {result?:{profile?:{revision?:unknown;creation_defaults?:NewsCreationContext['defaults']}};profile?:{revision?:unknown;creation_defaults?:NewsCreationContext['defaults']}};
 const profile=envelope?.result?.profile??envelope?.profile;
 if(!profile||typeof profile.revision!=='number'||!Number.isInteger(profile.revision)||profile.revision<=context.profile_revision||!profile.creation_defaults)throw Error('保存回执缺少画像修订，请重新读取设置核对，当前选择已保留。');
 return {...context,profile_revision:profile.revision,defaults:profile.creation_defaults};
}
export function readingParagraphs(body:string):string[]{return body.replace(/\r\n/g,'\n').split(/\n\s*\n|\n/).map(value=>value.trim()).filter(Boolean)}
