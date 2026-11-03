import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync,existsSync} from 'node:fs';
import {moduleLoader} from './helpers/modules.mjs';
const jsx={jsx:(type,props)=>({type,props:props||{}}),jsxs:(type,props)=>({type,props:props||{}})};

test('private skill host renders the original page with default official catalog and drawer services',()=>{
 const view={read:()=>({query:'kept query'}),write(){}},ready=()=>{},load=moduleLoader({imports:{react:{useCallback:fn=>fn},'react/jsx-runtime':jsx,'../../components/SkillPage':'OriginalSkillPage','./hooks':{useWorkbench:()=>({navigation:{entryKey:'entry',contentReady:ready}}),useViewState:()=>view}}});
 const page=load('workbench/ui/NativeSkills.tsx').NativeSkills({profileId:'author'});
 assert.equal(page.type,'OriginalSkillPage');assert.equal(page.props.persona,'author');assert.equal(page.props.viewState,view);
 for(const prop of ['headerActions','renderDrawer','catalog'])assert.equal(prop in page.props,false,prop);
 assert.equal(typeof page.props.onContentReady,'function');
});

test('retired private skill managers and execution service cannot be mounted from the skills route',()=>{
 const source=readFileSync(new URL('../../web/frontend/src/workbench/ui/index.tsx',import.meta.url),'utf8');
 assert.match(source,/q\.get\('section'\)===['"]skills['"]\)page=<NativeSkills profileId=\{profile\}\/>/);
 assert.doesNotMatch(source,/<Skills\b|pane.*experience.*<Skills/);
 const management=readFileSync(new URL('../../web/frontend/src/workbench/ui/management.tsx',import.meta.url),'utf8');
 assert.doesNotMatch(management,/export function (Skills|SkillDetail)|function (Experience|ProfileProposal)|creatorCommand|skill-publish|experience-organize/);
 assert.equal(existsSync(new URL('../../web/frontend/src/workbench/ui/skillServices.ts',import.meta.url)),false);
});

test('reference task history remains read-only without links back into retired skill managers',()=>{
 const hooks={useResource:()=>({data:{status:'completed',result:{analysis:{summary:'Exact old result',suggestions:[]},skill_id:'old',version:2}},error:''})};
 const common={Panel:'Panel',Notice:'Notice',JsonDetails:'JsonDetails'};
 const load=moduleLoader({imports:{'react/jsx-runtime':jsx,'@workbench/core':{record:v=>v||{},array:v=>Array.isArray(v)?v:[],string:v=>typeof v==='string'?v:''},'./hooks':hooks,'./common':common,'./nativeProfiles':{NativeProfiles:'Profiles'},'./PlatformAccounts':{Accounts:'Accounts'}}});
 const tree=load('workbench/ui/management.tsx').SkillTask({id:'historical-reference'});
 assert.equal(tree.type,'Panel');assert.equal(tree.props.title,'拆解完成');assert.match(JSON.stringify(tree),/Exact old result/);assert.doesNotMatch(JSON.stringify(tree),/button|creatorCommand|候选差异/);
});
