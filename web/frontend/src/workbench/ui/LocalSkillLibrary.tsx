import {useRef,useState} from 'react';
import type {SkillItem} from '../../lib/api';
import type {SkillPresentation} from '../../components/SkillPage';
import SettingsSelect from '../../components/SettingsSelect';
import {useWorkbench,useResource,useViewState} from './hooks';
import {record,string,type JsonRecord} from '@workbench/core';
import {localSkillIcon} from './skillIcons';
import './local-skills.css';

export interface LocalSkillInfo {id:string;repository:string;url:string;commit:string;category:string;category_label:string;original_name:string;stages:string[];tags:string[];stars:number|null;checked_at:number|null;reuse?:string}
export interface LocalSkillItem extends SkillItem {local_skill?:LocalSkillInfo}
export const localInfo=(skill:SkillItem):LocalSkillInfo|undefined=>(skill as LocalSkillItem).local_skill;
export function SourceInfo({skill,detail=false}:{skill:SkillItem;detail?:boolean}){
 const info=localInfo(skill);if(!info)return null;
 const count=typeof info.stars==='number'?info.stars.toLocaleString('en-US'):'—';
 return <div className="ew-local-skill-meta" data-local-skill={info.id}>
  <span className="badge badge-accent ew-local-skill-stars" aria-label={'来源仓库 Star '+count}>★ {count}</span>
  <span className="badge">{info.category_label}</span>
  {info.reuse&&<span className="badge">复用原生</span>}
  {detail?<><a href={'https://github.com/'+info.repository} target="_blank" rel="noreferrer">{info.repository}</a><span>仓库关注数，非单技能使用人数</span><span>核查：{info.checked_at?new Date(info.checked_at*1000).toLocaleString('zh-CN'):'尚未取得'}</span><span>原始技能：{info.original_name}</span><span>源码：{info.commit.slice(0,12)}</span><span>原件已校验；具体工具在执行前核对，安装不等于已实测生成或发布。</span></>:<span className="ew-local-skill-repository">{info.repository}</span>}
  {skill.executionBlocked&&<span className="ew-local-skill-blocked">{skill.executionBlocked}</span>}
 </div>;
}

export function useLocalSkillPresentation():SkillPresentation{
 const vm=useWorkbench(),metadata=useResource<{categories:Record<string,string>;repositories:string[]}>('/api/local-skills?view=sources');
 const defaults={source:'all',category:'all',sort:'category'},stored=useViewState('local-skill-filters',defaults),[filters,setFilters]=useState(()=>stored.read()||defaults);
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[revision,setRevision]=useState(0),icons=useRef(new Map<string,ReturnType<typeof localSkillIcon>>());
 const patch=(next:Partial<typeof defaults>)=>{const value={...filters,...next};setFilters(value);stored.write(value)};
 const refresh=async()=>{
  if(busy)return;setBusy(true);setError('');
  try{
   await vm.api.post('/api/local-skills/sources/refresh',{},vm.config?.csrf||'');
   for(let index=0;index<36;index++){
    await new Promise(resolve=>setTimeout(resolve,1500));
    const state=await vm.api.get<JsonRecord>('/api/local-skills/sources');if(!state.running){setRevision(value=>value+1);if(Number(state.retry_at)>Date.now()/1000)setError('GitHub 请求受限，保留上次核查数据；稍后再试。');else if(Number(state.failures)>0)setError('部分来源未能更新，已保留其上次核查数据。');return}
   }
   setError('仓库信息仍在后台核对，当前列表保留。');
  }catch(reason){setError(reason instanceof Error?reason.message:'仓库信息未能更新，当前列表保留。')}
  finally{setBusy(false)}
 };
 const name=(skill:SkillItem)=>skill.display_name||skill.name;
 return {revision,controls:<div className="ew-local-skill-controls">
  <label>来源<SettingsSelect label="技能来源" value={filters.source} onChange={source=>patch({source})} options={[{value:'all',label:'全部技能'},{value:'imported',label:'本次导入'},{value:'builtin',label:'Easel 原生'},{value:'oilpig',label:'油猪自有'},...(metadata.data?.repositories||[]).map(repo=>({value:repo,label:repo}))]}/></label>
  <label>细分类<SettingsSelect label="技能细分类" value={filters.category} onChange={category=>patch({category})} options={[{value:'all',label:'全部细分类'},...Object.entries(metadata.data?.categories||{}).map(([value,label])=>({value,label}))]}/></label>
  <label>排序<SettingsSelect label="技能排序" value={filters.sort} onChange={sort=>patch({sort})} options={[{value:'category',label:'按分类排列'},{value:'stars',label:'仓库 Star 从高到低'}]}/></label>
  <button className="btn" disabled={busy} onClick={()=>void refresh()}>{busy?'更新中…':'更新仓库信息'}</button>
  <small>Star 是来源仓库的关注数，核查时间见详情。</small>{error&&<span role="alert">{error}</span>}
 </div>,filter:skill=>{
  const info=localInfo(skill),source=filters.source;
  return (source==='all'||source==='imported'&&!!info||source==='builtin'&&!skill.name.startsWith('local-')&&!skill.name.startsWith('oil-pig-')||source==='oilpig'&&skill.name.startsWith('oil-pig-')||info?.repository===source)&&(filters.category==='all'||info?.category===filters.category);
 },compare:(a,b)=>{
  const left=localInfo(a),right=localInfo(b);
  if(filters.sort==='stars'){const difference=(right?.stars??-1)-(left?.stars??-1);if(difference)return difference}
  return (left?.category_label||'').localeCompare(right?.category_label||'','zh-CN')||name(a).localeCompare(name(b),'zh-CN');
 },searchText:skill=>{const info=localInfo(skill);return info?[info.repository,info.original_name,info.category_label,...info.tags].join(' '):''},
 cardMetadata:skill=><SourceInfo skill={skill}/>,detailMetadata:skill=><SourceInfo skill={skill} detail/>,icon:skill=>{
  const info=localInfo(skill);if(!info)return undefined;
  if(!icons.current.has(skill.name))icons.current.set(skill.name,localSkillIcon(skill.name,info.category));return icons.current.get(skill.name);
 }};
}

export interface LocalSkillCatalog {revision:string;skills:LocalSkillItem[];stages:Record<string,string>}
export function AuxiliarySkills({value,onChange,format,disabled}:{value:Record<string,string>;onChange:(value:Record<string,string>,revision:string)=>void;format:string;disabled:boolean}){
 const resource=useResource<LocalSkillCatalog>('/api/local-skills?view=selection');
 const stages=Object.entries(resource.data?.stages||{}).filter(([stage])=>format!=='poster'||stage!=='layout');
 if(!resource.data?.skills.length)return null;
 return <section className="ew-local-skill-selection" aria-label="辅助技能选择"><p><strong>写作与辅助技能</strong><span>可不选，默认沿用油猪流程</span></p>{stages.map(([stage,label])=>{
  const candidates=resource.data!.skills.filter(skill=>localInfo(skill)?.stages.includes(stage)&&!skill.executionBlocked);if(!candidates.length)return null;
  return <label key={stage}>{label}<SettingsSelect label={label+'技能'} disabled={disabled} value={value[stage]||''} onChange={id=>{const next={...value};if(id)next[stage]=id;else delete next[stage];onChange(next,resource.data!.revision)}} options={[{value:'',label:stage==='writing'?'沿用油猪写法':'不使用此辅助阶段'},...candidates.map(skill=>({value:skill.name,label:(skill.display_name||skill.name)+(skill.executionBlocked?' · 待配置':'')}))]}/></label>;
 })}</section>;
}
