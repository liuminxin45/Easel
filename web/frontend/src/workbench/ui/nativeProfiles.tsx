import {useMemo,useState} from 'react';
import ProfilePage,{type ProfilePageDraft} from '../../components/ProfilePage';
import {useWorkbench,useResource,useDraft,useAsyncAction,creatorAssetInputs,array,record,string,number,type CreatorBootstrap,type CreatorProfile,type DraftAttachment} from '@workbench/core';
import {ActionButton,Field,Panel,Notice,Pending,resultDocument} from './common';

export function NativeProfiles({search,profileId=''}:{search:URLSearchParams;profileId?:string}){
 const vm=useWorkbench(),resource=useResource<CreatorBootstrap>('/api/creator/bootstrap');
 const draftStore=useMemo(()=>({
  read:(id:string)=>vm.client.drafts.get<ProfilePageDraft>('easel:profile-files:'+id),
  write:(id:string,draft:ProfilePageDraft)=>{vm.client.drafts.set('easel:profile-files:'+id,draft)},
  remove:(id:string)=>vm.client.drafts.remove('easel:profile-files:'+id),
 }),[vm.client]);
 const item=search.get('item')||'';
 if(item==='new')return <CreateProfile/>;
 const profile=resource.data?.profiles.find(value=>value.id===(item||profileId));
 return <><Notice sources={[resource]}/><ProfilePage key={item||profileId||'profiles'} persona={profile?.id||item||profileId}
  personaLabel={id=>resource.data?.profiles.find(value=>value.id===id)?.name||id}
  onUsePersona={id=>vm.navigate('/chat?fresh=1&profile='+encodeURIComponent(id))}
  onNewProfile={()=>vm.navigate('/toolbox?section=profiles&item=new')}
  onDeleted={()=>{void resource.reload();vm.replace('/toolbox?section=profiles')}}
  allowAccountImport={false} allowDelete={false} onFileSaved={()=>void resource.reload()}
  draftStore={draftStore}
  renderDetailExtension={id=>{const current=resource.data?.profiles.find(value=>value.id===id);return current&&resource.data?<ProfileBindings key={id} profile={current} data={resource.data} reload={resource.reload}/>:null}}/>
 </>;
}

function CreateProfile(){
 const vm=useWorkbench(),action=useAsyncAction(),[draft,patch]=useDraft('creator:profile:new',{name:'',identity:'',audience:'',voice:'',boundaries:''});
 const save=()=>void action.run(async()=>{
  const result=await vm.service.creatorCommand('profile-save',{base_revision:0,document:{...draft,asset_refs:[]}});
  const profile=record(resultDocument(result).profile);vm.replace('/toolbox?section=profiles&item='+encodeURIComponent(string(profile.id)));
 });
 return <div className="profile-page"><div className="profile-head"><h1 className="page-title">新建画像</h1></div>
  <section className="panel workbench-extension">{[['name','名称'],['identity','身份定位'],['audience','目标受众'],['voice','内容风格'],['boundaries','偏好与红线']].map(([key,label])=><Field key={key} label={label!}>
   {key==='name'?<input className="field" value={draft.name} onChange={event=>patch({name:event.target.value})}/>:<textarea className="field" rows={4} value={draft[key as 'identity']} onChange={event=>patch({[key!]:event.target.value})}/>}
  </Field>)}<ActionButton action={action} className="btn btn-primary" disabled={action.busy||!draft.name.trim()} onClick={save}>创建画像</ActionButton>
   <Notice sources={[action]}/><Pending scope="creator:profile-save:"/>
  </section></div>;
}

function ProfileBindings({profile,data,reload}:{profile:CreatorProfile;data:CreatorBootstrap;reload:()=>Promise<CreatorBootstrap|null>}){
 const vm=useWorkbench(),action=useAsyncAction(),[open,setOpen]=useState(false);
 const [draft,patch]=useDraft('creator:profile-bindings:'+profile.id,{asset_refs:creatorAssetInputs(profile.asset_refs),files:[] as DraftAttachment[],base_revision:profile.revision,default_skills:profile.default_skills||data.task_defaults});
 const changedRevision=draft.base_revision!==profile.revision;
 const save=()=>void action.run(async()=>{
  if(changedRevision)throw Error('画像已有新修订，请先核对；当前绑定输入仍保留。');
  const uploaded=await vm.service.uploadFiles(draft.files);
  const result=await vm.service.creatorCommand('profile-save',{profile_id:profile.id,base_revision:draft.base_revision,document:{name:profile.name,identity:profile.identity,audience:profile.audience,voice:profile.voice,boundaries:profile.boundaries,
   asset_refs:[...draft.asset_refs,...uploaded.map(file=>({file_id:file.id,label:file.name,role:'reference',required:true}))],default_skills:draft.default_skills}});
  const saved=record(resultDocument(result).profile);patch({files:[],base_revision:number(saved.revision),asset_refs:creatorAssetInputs(saved.asset_refs)});void reload();
 });
 return <details className="workbench-extension" open={open} onToggle={event=>setOpen(event.currentTarget.open)}><summary>工作台扩展 · 素材、执行技能与账号绑定</summary>
  <Panel title="角色与品牌参考">{draft.asset_refs.map((asset,index)=><div className="ew-row" key={index}><span>{string(asset.label)||string(asset.path)}</span><button className="btn btn-ghost" onClick={()=>patch({asset_refs:draft.asset_refs.filter((_,position)=>position!==index)})}>移除绑定</button></div>)}
   {draft.files.map(file=><p key={file.id}>{file.name}</p>)}<label className="btn ew-file-pick">添加参考图<input type="file" accept="image/png,image/jpeg,image/webp" multiple onChange={event=>{if(event.target.files)void action.run(async()=>patch({files:await vm.service.attach(event.target.files!,draft.files)}))}}/></label>
  </Panel>
  <Panel title="默认执行技能">{[['poster','贴图'],['article','文章'],['research','选题研究']].map(([task,label])=><details key={task}><summary>{label}</summary>
   {data.skills.filter(skill=>skill.published_version&&array<string>(skill.tasks).includes(task!)).map(skill=><label className="ew-check" key={skill.id}><input type="checkbox" checked={(draft.default_skills[task!]||[]).includes(skill.id)} onChange={event=>patch({default_skills:{...draft.default_skills,[task!]:event.target.checked?[...(draft.default_skills[task!]||[]),skill.id]:(draft.default_skills[task!]||[]).filter(id=>id!==skill.id)}})}/>{skill.name} · {skill.published_version}</label>)}
  </details>)}</Panel>
  <ActionButton action={action} className="btn btn-primary" disabled={action.busy||changedRevision} onClick={save}>保存绑定与默认技能</ActionButton>
  {changedRevision&&<p role="status">画像已有新修订。<button className="btn" onClick={()=>patch({base_revision:profile.revision})}>已核对当前画像，保留这些绑定修改</button></p>}
  <Panel title="关联平台账号">{data.accounts.map(account=><div className="ew-row" key={account.id}><span>{account.label||account.account||account.platform}</span><ActionButton action={action} className="btn" disabled={action.busy} onClick={()=>void action.run(async()=>{
   const result=await vm.service.creatorCommand(profile.account_ids.includes(account.id)?'unbind-account':'bind-account',{profile_id:profile.id,connection_id:account.id,base_revision:profile.revision});patch({base_revision:number(record(resultDocument(result).profile).revision)});void reload();
  })}>{profile.account_ids.includes(account.id)?'解绑':'绑定'}</ActionButton></div>)}</Panel>
  <Notice sources={[action]}/><Pending scope={'creator:profile-save:'+profile.id}/>
 </details>;
}
