import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';
const helper=moduleLoader()('workbench/ui/newsCreation.ts');
const slots=['writing','visual','character','layout'];
const plain=value=>JSON.parse(JSON.stringify(value));
const style=Object.fromEntries(slots.map(slot=>[slot,slot]));
function context(){return {catalog_revision:'catalog',source_revision:'news',profile_revision:1,formats:['poster','article'],defaults:{},packs:[],components:Object.fromEntries(slots.map(slot=>[slot,[{id:slot,name:slot,slot,available:true}]])),templates:{poster:[{id:'approved',revision:'sha',name:'优秀例子',format:'poster',style,available:true,source_version_id:'original'}],article:[]}}}
test('excellent templates are never auto selected; explicit selection preserves the current note',()=>{
 const c=context(),draft=helper.initialCreationDraft(c,'poster');assert.equal(draft.template_id,undefined);
 const selected=helper.creationWithTemplate(c,'poster',{...draft,note:'本轮要求'},'approved');
 assert.equal(selected.template_id,'approved');assert.equal(selected.template_revision,'sha');assert.equal(selected.note,'本轮要求');assert.deepEqual(plain(selected.style),style);
 const request=helper.creationRequest(c,'produce',selected,'poster');assert.equal(request.template_id,'approved');assert.equal(request.template_revision,'sha');
 assert.equal(helper.creationRequest(c,'discuss',selected).template_id,undefined);
 const cleared=helper.creationWithTemplate(c,'poster',selected,'');assert.equal(cleared.template_id,undefined);assert.equal(cleared.note,'本轮要求');assert.deepEqual(plain(cleared.style),style);
});
test('a changed or unavailable template cannot be sent; formats never mix',()=>{
 const c=context(),selected=helper.creationWithTemplate(c,'poster',{style,note:'不丢输入'},'approved');
 assert.throws(()=>helper.creationWithTemplate(c,'article',selected,'approved'),/当前不可用/);
 c.templates.poster[0].revision='new';assert.throws(()=>helper.creationRequest(c,'produce',selected,'poster'),/当前不可用/);
 c.templates.poster[0].revision='sha';c.templates.poster[0].available=false;
 assert.throws(()=>helper.creationRequest(c,'produce',selected,'poster'),/当前不可用/);
 assert.equal(selected.note,'不丢输入');
});
test('explicit style overrides retain the exact template method binding',()=>{
 const c=context(),selected=helper.creationWithTemplate(c,'poster',{style,note:'原话'},'approved');
 c.components.visual.push({id:'override',name:'override',slot:'visual',available:true});
 const request=helper.creationRequest(c,'produce',{...selected,style:{...selected.style,visual:'override'}},'poster');
 assert.equal(request.template_id,'approved');assert.equal(request.style.visual,'override');assert.equal(request.note,'原话');
});
test('template detail requests are exact and profile scoped',()=>{
 const path=helper.productionTemplatePath('template-one','profile with spaces','article','exact-revision');
 assert.ok(path.startsWith('/api/production-insights/templates/template-one?'));
 const url=new URL(path,'https://temp.test');assert.equal(url.searchParams.get('profile_id'),'profile with spaces');assert.equal(url.searchParams.get('format'),'article');assert.equal(url.searchParams.get('revision'),'exact-revision');
});
