import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';
const plain=value=>JSON.parse(JSON.stringify(value));
const helper=moduleLoader()('workbench/ui/newsCreation.ts');
const slots=['writing','visual','character','layout'];
function context(){return {catalog_revision:'catalog-1',source_revision:'source-1',profile_revision:4,formats:['poster','article'],source:{id:'news-1',title:'完整新闻标题'},components:Object.fromEntries(slots.map(slot=>[slot,[{id:slot+'-1',name:slot,slot,available:true,thumbnail_url:'/api/news/creation-assets/'+slot+'-1/0'},{id:slot+'-missing',name:'缺失项',slot,available:false,reason:'文件缺失'}]])),packs:[],defaults:{}}}
const full={writing:'writing-1',visual:'visual-1',character:'character-1',layout:'layout-1'};

test('news defaults use only current available catalog IDs and never infer a style or format',()=>{
 const c=context();assert.deepEqual(plain(helper.initialCreationDraft(c,'poster')),{style:{writing:'',visual:'',character:'',layout:''},note:''});
 c.defaults.poster={...full,visual:'visual-missing',layout:'old-unknown'};
 const draft=helper.initialCreationDraft(c,'poster');assert.deepEqual(plain(draft.style),{writing:'writing-1',visual:'',character:'character-1',layout:''});
 assert.deepEqual(plain(helper.creationMissing(c,draft,'poster')),['visual','layout']);
 assert.throws(()=>helper.creationRequest(c,'produce',draft,'poster'),/完成本次/);
});

test('poster gets the existing default pack; saved defaults and explicit drafts take precedence',()=>{
 const c=context();c.packs=[{id:'editorial-poster',name:'默认',formats:['poster'],components:{...full},available:true}];
 assert.deepEqual(plain(helper.initialCreationDraft(c,'poster').style),full);
 const empty={style:{writing:'',visual:'',character:'',layout:''},note:'  保留本次原话  '};
 const fresh=helper.creationDraftWithDefault(c,'poster',empty);assert.deepEqual(plain(fresh.style),full);assert.equal(fresh.note,empty.note);
 const partial={style:{...empty.style,character:'character-1'},note:'原话'};assert.equal(helper.creationDraftWithDefault(c,'poster',partial),partial);
 assert.equal(helper.creationDraftWithDefault(c,'article',empty),empty);
 assert.equal(helper.creationPackId(c,'poster',fresh),'editorial-poster');
 c.defaults.poster={...full,visual:'visual-missing'};assert.equal(helper.initialCreationDraft(c,'poster').style.visual,'');
 delete c.defaults.poster;c.packs[0].available=false;assert.deepEqual(plain(helper.initialCreationDraft(c,'poster').style),empty.style);
});

test('article requires writing only, optional illustration style must be a valid pair',()=>{
 const c=context(),draft={style:{writing:'writing-1',visual:'',character:'',layout:''},note:'  原始要求\n保持  '};
 const request=helper.creationRequest(c,'produce',draft,'article');assert.deepEqual(plain(request),{intent:'produce',format:'article',style:{writing:'writing-1'},catalog_revision:'catalog-1',source_revision:'source-1',profile_revision:4,note:draft.note});
 draft.style.visual='visual-1';assert.deepEqual(plain(helper.creationMissing(c,draft,'article')),['character']);
 draft.style.character='character-1';assert.equal(helper.creationMissing(c,draft,'article').length,0);
 assert.deepEqual(plain(helper.creationRequest(c,'discuss',draft)),{intent:'discuss',catalog_revision:'catalog-1',source_revision:'source-1',profile_revision:4,note:draft.note});
});

test('draft identity separates news, profile and format and preview URLs stay capability scoped',()=>{
 const keys=[helper.creationDraftKey('a','p','poster'),helper.creationDraftKey('a','p','article'),helper.creationDraftKey('b','p','poster'),helper.creationDraftKey('a','q','poster')];assert.equal(new Set(keys).size,4);
 assert.equal(helper.creationThumbnail('/api/news/creation-assets/visual-1/0'),'/api/news/creation-assets/visual-1/0');
 for(const url of ['https://example.com/image.png','file:///D:/secret','/api/media/private.png','/api/news/creation-assets/a/0?path=secret'])assert.equal(helper.creationThumbnail(url),undefined);
 assert.deepEqual(plain(helper.readingParagraphs('第一段\r\n\r\n第二段\n第三段')),['第一段','第二段','第三段']);
 const c=context();c.linked_session={id:'original-chat',profile_id:'p',pendingTurnId:'already-running'};assert.equal(helper.linkedCreationSession(c,'p'),'original-chat','pending sessions must be handed to the host for navigation rather than forked');
 assert.equal(helper.linkedCreationSession(c,'different-profile'),undefined);c.linked_session.archived=true;assert.equal(helper.linkedCreationSession(c,'p'),undefined);
});

const jsx={jsx:(type,props)=>({type,props:props||{}}),jsxs:(type,props)=>({type,props:props||{}}),Fragment:'fragment'};
const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
const text=value=>Array.isArray(value)?value.map(text).join(''):value&&typeof value==='object'?text(value.props?.children):value==null?'':String(value);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(){
 const c=context(),drafts=new Map(),states=new Map(),saves=[],starts=[],reads=[];let current,index,serverRevision=c.profile_revision;
 const react={useState:initial=>{const i=index++,state=current;if(!(i in state))state[i]=typeof initial==='function'?initial():initial;return [state[i],value=>{state[i]=typeof value==='function'?value(state[i]):value}]},useRef:initial=>{const i=index++;if(!(i in current))current[i]={current:initial};return current[i]}};
 const resource={data:c,error:'',reload:async()=>{c.profile_revision=serverRevision;return c}};
 const hooks={useResource:path=>{reads.push(path);return resource},useWorkbench:()=>({service:{creatorCommand:async(...args)=>{saves.push(plain(args));return {result:{profile:{revision:++serverRevision,creation_defaults:args[1].document.creation_defaults}}}}}}),useDraft:(key,initial)=>{if(!drafts.has(key))drafts.set(key,typeof initial==='function'?initial():initial);return [drafts.get(key),patch=>drafts.set(key,{...drafts.get(key),...patch})]}};
 const load=moduleLoader({imports:{react,'react/jsx-runtime':jsx,'./hooks':hooks,'./common':{Notice:'Notice',Markdown:'Markdown'},'./ExtensionDetails':{ExtensionDetails:'ExtensionDetails'},'../../components/Drawer':'Drawer','../../components/SettingsSelect':'SettingsSelect','./news-creation.css':{}}});
 const Drawer=load('workbench/ui/NewsCreationDrawer.tsx').default;
 const props={articleId:'news-1',profileId:'profile-1',onClose(){},onStart:async(...args)=>starts.push(plain(args))};
 const render=(component=Drawer,input=props)=>{if(!states.has(component))states.set(component,[]);current=states.get(component);index=0;return component(input)};
 return {c,resource,drafts,saves,starts,reads,props,render,form(format){let tree=render();nodes(tree).find(node=>node.type==='button'&&text(node)===(format==='poster'?'贴图':'文章')).props.onClick();return ()=>{const form=nodes(render()).find(node=>typeof node.type==='function');return render(form.type,form.props)}}};
}

test('selecting a human-confirmed template uses the original select and sends its exact revision only on start',async()=>{
 const f=fixture();f.c.templates={poster:[{id:'approved-template',revision:'exact-revision',name:'人工确认的模板',format:'poster',style:{...full},available:true,source_version_id:'original'}]};
 const form=f.form('poster');let tree=form();
 const picker=nodes(tree).find(node=>node.type==='SettingsSelect'&&node.props.label==='优秀制作模板');
 assert.equal(picker.props.value,'');assert.equal(f.starts.length,0);assert.equal(f.saves.length,0);
 picker.props.onChange('approved-template');tree=form();
 nodes(tree).find(node=>node.type==='textarea').props.onChange({target:{value:'本轮新闻的新要求'}});tree=form();
 nodes(tree).find(node=>node.type==='button'&&text(node)==='开始制作贴图').props.onClick();await tick();
 assert.equal(f.starts.length,1);assert.equal(f.starts[0][1].template_id,'approved-template');assert.equal(f.starts[0][1].template_revision,'exact-revision');assert.equal(f.starts[0][1].note,'本轮新闻的新要求');
 f.c.templates.poster[0].available=false;tree=form();
 assert.equal(nodes(tree).find(node=>node.type==='button'&&text(node)==='开始制作贴图').props.disabled,true);
 assert.match(text(tree),/原模板已更新或不可用/);
 nodes(tree).find(node=>node.type==='SettingsSelect'&&node.props.label==='优秀制作模板').props.onChange('');tree=form();
 assert.equal(nodes(tree).find(node=>node.type==='button'&&text(node)==='开始制作贴图').props.disabled,false);
});

test('the selected template method is fetched only after an explicit detail opening',()=>{
 const f=fixture();f.c.templates={poster:[{id:'approved-template',revision:'exact-revision',name:'人工确认的模板',format:'poster',style:{...full},available:true,source_version_id:'original'}]};
 const form=f.form('poster');let tree=form();nodes(tree).find(node=>node.type==='SettingsSelect'&&node.props.label==='优秀制作模板').props.onChange('approved-template');tree=form();
 const detail=nodes(tree).find(node=>typeof node.type==='function'&&node.props.template);
 let preview=f.render(detail.type,detail.props);assert.equal(preview.type,'ExtensionDetails');assert.equal(f.reads.at(-1),null);
 assert.equal(f.reads.some(path=>path?.startsWith('/api/production-insights/templates/')),false);
 preview.props.onToggle({currentTarget:{open:true}});f.resource.data={...f.c.templates.poster[0],method:'人工核对后的完整制作规范',references:[]};
 preview=f.render(detail.type,detail.props);assert.equal(f.reads.at(-1),helper.productionTemplatePath('approved-template','profile-1','poster','exact-revision'));
 assert.equal(nodes(preview).find(node=>node.type==='Markdown').props.text,'人工核对后的完整制作规范');
 assert.equal(f.starts.length,0);assert.equal(f.saves.length,0);
});

test('the original Drawer never starts on mount; form selection and raw note stay local until an explicit start',async()=>{
 const f=fixture();let tree=f.render();assert.equal(tree.type,'Drawer');assert.equal(f.starts.length,0);assert.equal(f.saves.length,0);
 const form=f.form('poster');tree=form();assert.equal(nodes(tree).find(node=>node.type==='button'&&text(node)==='开始制作贴图').props.disabled,true);
 for(const slot of slots){nodes(tree).find(node=>node.type==='SettingsSelect'&&node.props.label===helper.newsSlotLabels[slot]).props.onChange(full[slot]);tree=form()}
 const raw='  用户补充\n保留原文  ';nodes(tree).find(node=>node.type==='textarea').props.onChange({target:{value:raw}});tree=form();
 const start=nodes(tree).find(node=>node.type==='button'&&text(node)==='开始制作贴图');assert.equal(start.props.disabled,false);start.props.onClick();await tick();
 assert.equal(f.starts.length,1);assert.equal(f.saves.length,0);assert.equal(f.starts[0][0],'news-1');assert.equal(f.starts[0][1].note,raw);assert.deepEqual(f.starts[0][1].style,full);
 assert.equal(f.drafts.get(helper.creationDraftKey('news-1','profile-1','poster')).note,raw);
});

test('only explicit profile-default save writes a revision; article does not require a picture and retains drafts',async()=>{
 const f=fixture(),form=f.form('article');let tree=form();assert.equal(nodes(tree).filter(node=>node.type==='SettingsSelect').length,2);
 nodes(tree).find(node=>node.type==='SettingsSelect'&&node.props.label==='写法').props.onChange('writing-1');tree=form();
 assert.equal(nodes(tree).find(node=>node.type==='button'&&text(node)==='开始写文章').props.disabled,false);
 nodes(tree).find(node=>node.type==='button'&&text(node)==='保存为画像默认').props.onClick();await tick();tree=form();
 assert.deepEqual(f.saves,[['profile-save',{profile_id:'profile-1',base_revision:4,document:{creation_defaults:{article:{writing:'writing-1'}}}}]]);
 assert.equal(f.starts.length,0);assert.equal(f.c.profile_revision,5);assert.match(text(tree),/本次尚未开始制作/);
 nodes(tree).find(node=>node.type==='button'&&text(node)==='设置配图风格').props.onClick();tree=form();assert.equal(nodes(tree).filter(node=>node.type==='SettingsSelect').length,4);
});

test('rapid explicit start clicks share one pending callback and failed acceptance retains exact local input',async()=>{
 const f=fixture();f.c.defaults.poster={...full};let finish,count=0;
 f.props.onStart=()=>{count++;return new Promise((resolve,reject)=>{finish=reject})};
 const form=f.form('poster');let tree=form();const note='原样保留的补充';nodes(tree).find(node=>node.type==='textarea').props.onChange({target:{value:note}});tree=form();
 const start=nodes(tree).find(node=>node.type==='button'&&text(node)==='开始制作贴图');start.props.onClick();start.props.onClick();assert.equal(count,1);
 finish(new Error('回执待核对，不重发'));await tick();tree=form();assert.match(text(tree),/回执待核对/);assert.equal(nodes(tree).find(node=>node.type==='textarea').props.value,note);assert.equal(f.saves.length,0);
});

test('acknowledged default revisions allow a second save and production while the background detail reload stays pending',async()=>{
 const f=fixture();f.c.defaults.poster={...full};f.resource.reload=()=>new Promise(()=>{});
 const form=f.form('poster');let tree=form();nodes(tree).find(node=>node.type==='button'&&text(node)==='保存为画像默认').props.onClick();await tick();tree=form();
 assert.match(text(tree),/已保存为画像默认/);assert.equal(nodes(tree).find(node=>node.type==='button'&&text(node)==='保存为画像默认').props.disabled,false);
 nodes(tree).find(node=>node.type==='button'&&text(node)==='保存为画像默认').props.onClick();await tick();tree=form();
 assert.deepEqual(f.saves.map(call=>call[1].base_revision),[4,5]);assert.equal(f.c.profile_revision,4,'the stale resource must not be needed to unblock the action');
 nodes(tree).find(node=>node.type==='button'&&text(node)==='开始制作贴图').props.onClick();await tick();assert.equal(f.starts.length,1);assert.equal(f.starts[0][1].profile_revision,6);
});

test('restore last loads fresh server choices only and never sends, saves or replaces this news note',async()=>{
 const f=fixture();f.c.packs=[{id:'editorial-poster',name:'默认',formats:['poster'],components:{...full},available:true}];
 let finish,calls=0;f.resource.reload=()=>{calls++;return new Promise(resolve=>finish=resolve)};
 const form=f.form('poster');let tree=form();
 nodes(tree).find(n=>n.type==='textarea').props.onChange({target:{value:'本条新闻独有要求'}});tree=form();
 const restore=nodes(tree).find(n=>n.type==='button'&&text(n)==='恢复上次贴图风格');restore.props.onClick();restore.props.onClick();assert.equal(calls,1);
 finish({...f.c,last_poster_style:{turn_id:'previous',style:{...full}}});await tick();tree=form();
 assert.equal(nodes(tree).find(n=>n.type==='textarea').props.value,'本条新闻独有要求');
 assert.deepEqual(plain(f.drafts.get(helper.creationDraftKey('news-1','profile-1','poster')).style),full);
 assert.equal(f.starts.length,0);assert.equal(f.saves.length,0);
 f.resource.reload=async()=>({...f.c,last_poster_style:null});tree=form();nodes(tree).find(n=>n.type==='button'&&text(n)==='恢复上次贴图风格').props.onClick();await tick();tree=form();
 assert.match(text(tree),/暂无可恢复/);assert.equal(f.starts.length,0);assert.equal(f.saves.length,0);
});
