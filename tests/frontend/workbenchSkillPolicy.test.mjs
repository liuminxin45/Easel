import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const root = new URL('../../web/frontend/src/workbench/', import.meta.url);
const plain = value => JSON.parse(JSON.stringify(value));
const cache = new Map();
function load(file, imports = {}, suffix = '') {
  if (file.startsWith('core/') && cache.has(file)) return cache.get(file);
  const source = readFileSync(new URL(file, root), 'utf8') + suffix;
  const {outputText} = ts.transpileModule(source, {compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS,
    jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  }});
  const exports = {};
  if (file.startsWith('core/')) cache.set(file, exports);
  runInNewContext(outputText, {exports, URL, URLSearchParams, requestAnimationFrame: fn => fn(),
    require: id => {
      if(id==='./common')return {ActionButton:'button',...(imports[id]||{})};
      if (id in imports) return imports[id];
      if (file.startsWith('core/') && id.startsWith('./')) return load('core/' + id.slice(2) + '.ts');
      if (id === './ProductionParameters') return {ProductionParameters: () => {}};
      if (id === './PlatformAccounts') return {Accounts: () => {}};
      if (id === './nativeProfiles') return {NativeProfiles: () => {}};
      if (id === './nativePages') return {NativeDashboard: () => {}, NativeLibrary: () => {}, NativeTopics: () => {}, NativeTrends: () => {}, NativeCalendar: () => {}, NativeBreakdown: () => {}};
      if (id === './WorkCompletion') return {Completion: () => {}};
      if (id === './ChatTurnProducts') return {ChatTurnProducts: () => {}};
      if (id === './ChatAdapter') return load('ui/ChatAdapter.tsx', {
        react: imports.react || {}, '@workbench/core': imports['@workbench/core'],
        'react/jsx-runtime': jsx, '../../components/ChatPage': () => {}, './components/icons': {},
      });
      throw Error('Unexpected module: ' + id);
    },
  });
  return exports;
}
const models = load('core/models.ts');
const creator = load('core/creator.ts', {'./models': models});
const mainline = load('core/mainline.ts', {'./models': models});
const recovery = load('core/production-recovery.ts');
const ref = (id, version = 1) => ({id, version});
const skill = (id, tasks, version = 4) => ({id, name: id, tasks, published_version: version,
  versions: [{version: 2, status: 'published'}, {version, status: 'published'}], launch_actions: []});
const data = () => ({default_profile_id: 'p', profiles: [{id: 'p', revision: 7, active: true,
  default_skills: {poster: ['writer-new', 'checker-new'], discuss: ['research-new']},
  task_skill_versions: {poster: {'writer-new': 2, 'flow-new': 2}},
}], skills: [skill('flow-new', ['poster']), skill('writer-new', ['poster']),
  skill('checker-new', ['poster']), skill('research-new', ['discuss'])], task_defaults: {},
  task_policy: {poster: {entry_skills: ['flow-new'], required_all: ['checker-new'],
    required_any: [['writer-new', 'image-new']]},
  discuss: {entry_skills: [], required_all: ['research-new'], required_any: []}},
});

test('a new server workflow ID launches the exact selected version and profile', () => {
  const path = creator.creatorLaunchPath({id: 'new-action', label: '制作',
    path: '/articles/new?mode=research&trial=0', task: 'article'},
  {id: 'custom-flow', version: 3, status: 'candidate'}, 'profile-二');
  const url = new URL(path, 'https://workbench.invalid');
  assert.equal(url.pathname, '/articles/new');
  assert.deepEqual(Object.fromEntries(url.searchParams), {mode: 'research', trial: '1',
    profile: 'profile-二', skill: 'custom-flow', skill_version: '3'});
  assert.throws(() => creator.creatorLaunchPath({path: '//external.invalid/'},
    {id: 'x', version: 1, status: 'published'}, 'p'), /入口无效/);
  const published = creator.creatorLaunchPath({path: '/posters/new?trial=1'},
    {id: 'x', version: 2, status: 'published'}, 'p');
  assert.equal(new URL(published, 'https://workbench.invalid').searchParams.has('trial'), false);
});

test('profile pins define execution references; discovery never inserts a workflow', () => {
  assert.deepEqual(plain(creator.creatorSelection(data(), 'p', 'poster')), {
    profile_id: 'p', profile_revision: 7,
    skills: [ref('writer-new', 2), ref('checker-new', 4)],
  });
  assert.equal(creator.creatorSkillRequired(data(), 'checker-new', 'poster', {skills: []}), true);
  assert.equal(creator.creatorSkillRequired(data(), 'writer-new', 'poster',
    {skills: [ref('writer-new')]}), true);
  assert.equal(creator.creatorSkillRequired(data(), 'writer-new', 'poster',
    {skills: [ref('writer-new'), ref('image-new')]}), false);
});

test('discussion retains an explicitly tried exact skill and drops production-only refs', () => {
  const selection = {profile_id: 'p', profile_revision: 7, trial: true,
    skills: [ref('writer-new', 2), ref('research-new', 1)]};
  assert.deepEqual(plain(creator.creatorTaskSelection(data(), selection, 'discuss')), {
    ...selection, skills: [ref('research-new', 1)],
  });
  const catalog = data();
  catalog.task_policy.discuss.required_all = [];
  assert.equal(creator.creatorSkillRequired(catalog, 'research-new', 'discuss',
    {skills: [ref('research-new')]}), true);
  assert.deepEqual(plain(creator.creatorTaskSelection(catalog,
    {profile_id: 'p', skills: [ref('writer-new')]}, 'discuss').skills), [ref('research-new', 4)]);
});

test('opening a candidate over an existing input changes only its explicit skill ref', () => {
  const value = {recipe: {pack_id: 'existing', prompt_text: 'manual input'},
    creator: {profile_id: 'p', skills: [ref('writer-new', 2), ref('research-new', 4)]}};
  const result = creator.creatorTrialFromSearch(value,
    new URLSearchParams({skill: 'research-new', skill_version: '1', trial: '1'}),
    data(), 'p', 'discuss');
  assert.deepEqual(plain(result), {...value, creator: {...value.creator, trial: true,
    skills: [ref('writer-new', 2), ref('research-new', 1)]}});
  assert.equal(creator.creatorTrialFromSearch(result,
    new URLSearchParams({skill: 'research-new', skill_version: '1', trial: '1'}),
    data(), 'p', 'discuss'), result);
  assert.equal(creator.creatorTrialFromSearch(value,
    new URLSearchParams({skill: 'research-new', skill_version: '1.5', trial: '1'}),
    data(), 'p', 'discuss'), value);
});

test('nonproduction launches bind the execution candidate independently of the improvement target', () => {
  const catalog = data();
  catalog.skills.push(skill('learning-new', ['learning'], 5));
  catalog.profiles[0].default_skills.learning = ['learning-new'];
  const selection = creator.creatorLaunchSelection(catalog, 'p', 'learning',
    new URLSearchParams({skill: 'learning-new', skill_version: '2', trial: '1'}));
  assert.deepEqual(plain(selection), {profile_id: 'p', profile_revision: 7,
    skills: [ref('learning-new', 2)], trial: true});
  assert.ok(!selection.skills.some(value => value.id === 'writer-new'));
});

function nodes(value) {
  if (Array.isArray(value)) return value.flatMap(nodes);
  if (!value || typeof value !== 'object') return [];
  return [value, ...nodes(value.props?.children)];
}
const jsx = {jsx: (type, props) => ({type, props}), jsxs: (type, props) => ({type, props})};

test('actual skill detail consumes server actions for an unfamiliar skill ID', () => {
  const moves = [];
  const detail = {id: 'unfamiliar-method', name: '新方法', version: 2,
    published_version: 1, status: 'candidate', resources: [], tasks: ['poster'],
    launch_actions: [{id: 'server-entry', label: '制作测试稿', path: '/posters/new', task: 'poster'}]};
  const core = {...models, ...creator, useWorkbench: () => ({navigate: (...args) => moves.push(args)}),
    useResource: () => ({data: detail}), useDraft: () => [{prompt: 'kept'}, () => {}],
    useAsyncAction: () => ({busy: false})};
  const react = {useState: value => [value, () => {}], useEffect: () => {}};
  const {SkillDetail} = load('ui/management.tsx', {'react': react,
    'react/jsx-runtime': jsx, '@workbench/core': core, './components/icons': {}, './common': {}},
  '\nexport {SkillDetail};');
  const tree = SkillDetail({id: detail.id, version: '2', data: data(), profileId: 'p'});
  const launch = nodes(tree).find(node => node.type === 'button' &&
    node.props.children.includes?.('制作测试稿'));
  assert.ok(launch);
  launch.props.onClick();
  assert.deepEqual(plain(moves), [['/posters/new?profile=p&skill=unfamiliar-method&skill_version=2&trial=1',
    {intent: 'flow'}]]);
});

test('actual production controls show the selected pinned version, not latest publication', () => {
  const core = {...models, ...creator, useResource: () => ({data: {packs: []}}),
    selectedRecipe: () => undefined, recipeReferences: () => []};
  const {CreatorControls} = load('ui/production.tsx', {'react': {},
    'react/jsx-runtime': jsx, '@workbench/core': core, './components/icons': {}, './common': {}});
  const tree = CreatorControls({data: data(), value: {creator: {
    profile_id: 'p', skills: [ref('writer-new', 2), ref('checker-new', 4)]}},
  format: 'poster', onChange: () => {}});
  const labels = nodes(tree).filter(node => node.type === 'label');
  const text = labels.map(label => nodes(label.props.children).length &&
    plain(label.props.children).filter(value => typeof value === 'string' || typeof value === 'number').join(''));
  assert.ok(text.some(value => value === 'writer-new · 2'));
  assert.ok(!text.some(value => value === 'writer-new · 4'));
  const required = labels.find(label => label.props.children.includes('checker-new'));
  assert.equal(nodes(required).find(node => node.type === 'input').props.disabled, true);
});

test('actual new discussion submits the saved server draft revision and exact trial ref', async () => {
  const calls = [];
  const input = {title: '讨论', material: '原始材料', guidance: '', files: [], creative: {
    creator: {profile_id: 'p', profile_revision: 7, trial: true, skills: [ref('research-new', 2)]},
    recipe: {pack_id: 'editorial-poster'},
  }};
  const core = {...models, ...creator, useWorkbench: () => ({navigation: {},
    navigate: () => {}, client: {drafts: {get: () => null}}, service: {
      createWork: async () => ({work_id: 'saved-work', revision: 9}),
      discuss: async (...args) => {calls.push(args);},
    }}), useResource: path => ({data: path === '/api/creator/bootstrap' ? data() : null}),
    useDraft: () => [input, () => {}, () => {}], useOperation: () => ({}),
    useAsyncAction: () => ({busy: false, run: fn => fn()})};
  const react = {useState: value => [value, () => {}], useEffect: () => {},
    useRef: value => ({current: value})};
  const {Production} = load('ui/production.tsx', {'react': react,
    'react/jsx-runtime': jsx, '@workbench/core': core, './components/icons': {}, './common': {}});
  const tree = Production({format: 'poster', profileId: 'p', search: new URLSearchParams('mode=research')});
  const send = nodes(tree).find(node => node.type?.name === 'ChatAdapter');
  await send.props.onSend();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], 'saved-work');
  assert.equal(calls[0][1].revision, 9);
  assert.deepEqual(plain(calls[0][1].creative.creator), input.creative.creator);
});

test('same-work first production selects production pins while preserving its discussion input', async () => {
  const work = {id: 'draft-work', title: '讨论后制作', format: 'poster', creator: {id: 'p'},
    versions: [], history: [], pending: [], draft: {revision: 3, discussion_token: 'frozen-discussion',
      title: '原字标题', material: '原字材料', files: [], creative: {recipe: {pack_id: 'editorial-poster'},
        creator: {profile_id: 'p', profile_revision: 7, trial: true, skills: [ref('research-new', 2)]}}}};
  const before = JSON.stringify(work);
  const previews = [], submissions = [];
  const core = {...models, ...creator, ...mainline, ...recovery, changeCreative: () => ({}),
    useWorkbench: () => ({navigation: {}, client: {read: async () => work, drafts: {get: () => ({text:'',files:[],creative:{}})}},
      service: {prepareProduction: async (...args) => {previews.push(args); return {revision_token: 'exact-frozen-revision'};}, finalize: async (...args) => {submissions.push(args); return {id:'accepted-first-version'};}}}),
    useResource: path => ({data: path === '/api/creator/bootstrap' ? data() : null}),
    useDraft: (key, initial) => [initial, () => {}, () => {}],
    useOperation: () => ({}),
    useAsyncAction: () => ({busy: false, run: fn => fn()})};
  const react = {useState: value => [value, () => {}], useEffect: () => {}, useRef: value => ({current: value})};
  const {WorkCanvas} = load('ui/production.tsx', {'react': react,
    'react/jsx-runtime': jsx, '@workbench/core': core, './components/icons': {}, './common': {}},
  '\nexport {WorkCanvas};');
  const tree = WorkCanvas({work, search: new URLSearchParams(), reload: async () => work});
  nodes(tree).find(node => node.type === 'button' && node.props.children === '按当前草稿制作').props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(previews.length, 1);
  assert.equal(previews[0][0], 'finalize');
  assert.equal(previews[0][2], work.id);
  assert.deepEqual(plain(previews[0][1].creative.creator.skills), [ref('writer-new', 2), ref('checker-new', 4)]);
  assert.equal(previews[0][1].revision, 3);
  assert.equal(previews[0][1].discussion_token, 'frozen-discussion');
  assert.equal(submissions.length, 1);
  assert.equal(submissions[0][0], work.id);
  assert.deepEqual(plain(submissions[0][1].creative.creator.skills), [ref('writer-new', 2), ref('checker-new', 4)]);
  assert.equal(submissions[0][1].creative.context_revision, 'exact-frozen-revision');
  assert.equal(JSON.stringify(work), before);
});

test('a slow compatibility production keeps input typed after the submitted draft was frozen',async()=>{
  const creative={creator:{profile_id:'p',skills:[ref('writer-new',2),ref('checker-new',4)]}},submitted={text:'本轮原字',files:[],creative};
  const work={id:'existing-work',title:'已有版本',format:'poster',creator:{id:'p'},latest_version:'parent',versions:[{id:'parent',status:'completed',label:'v1',artifacts:[],creative}],history:[],pending:[],draft:{revision:3,creative}};
  let current=submitted,resets=0,release;const hold=new Promise(resolve=>{release=resolve}),sent=[];
  const core={...models,...creator,...mainline,...recovery,changeCreative:()=>creative,revisionCreative:value=>value,
    useWorkbench:()=>({navigation:{},client:{drafts:{get:()=>current}},service:{prepareProduction:async()=>hold,workAction:async(...args)=>{sent.push(args)}}}),
    useResource:path=>({data:path==='/api/creator/bootstrap'?data():null}),useDraft:(key,initial)=>key.startsWith('feedback:')?[submitted,()=>{},()=>{resets++}]:[initial,()=>{},()=>{}],useOperation:()=>({}),useAsyncAction:()=>({busy:false,run:fn=>fn()})};
  const react={useState:value=>[value==='discuss'?'change':value,()=>{}],useEffect:()=>{},useRef:value=>({current:value})};
  const {WorkCanvas}=load('ui/production.tsx',{react,'react/jsx-runtime':jsx,'@workbench/core':core,'./components/icons':{},'./common':{}},'\nexport {WorkCanvas};');
  const tree=WorkCanvas({work,search:new URLSearchParams('version=parent'),reload:async()=>work}),composer=nodes(tree).find(node=>node.type?.name==='ChatAdapter');
  composer.props.onSend();await new Promise(resolve=>setImmediate(resolve));current={...submitted,text:'等待时新输入，必须保留'};release({revision_token:'frozen-before-new-input'});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(sent.length,1);assert.equal(sent[0][1].text,'本轮原字');assert.equal(sent[0][1].creative.context_revision,'frozen-before-new-input');assert.equal(resets,0);assert.equal(current.text,'等待时新输入，必须保留');
});

test('private barrel retains manual bridge discovery and has no retired production hooks', () => {
  const barrel = readFileSync(new URL('core/index.ts', root), 'utf8');
  const discovery = readFileSync(new URL('core/extension-discovery.ts', root), 'utf8');
  assert.match(barrel, /export \* from '\.\/extension-discovery'/);
  assert.match(discovery, /export function readExtensionAccounts/);
  assert.match(discovery, /export async function waitForAccountCheck/);
  assert.doesNotMatch(discovery, /useAccountAutoCheck|accountAutoCheckScopes|from '\.\/auto-check'/);
  assert.doesNotMatch(barrel, /from '\.\/media'/);
});
