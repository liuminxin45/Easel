import assert from 'node:assert/strict';
import {test} from 'node:test';
import {inspectOfficialPresentation,inspectOfficialListStyles} from '../../scripts/audit_easel_base.mjs';

test('real service and business content slots preserve the official shell contract',()=>{
 const source='const page=<><SkillDrawer services={service} extension={<ProjectVersion/>}/><ChatPage composer={composer} emptyState={{icon:<img src={assetUrl}/>}}/><OnboardingWizard services={profiles}/><Drawer title="版本"><ProjectVersion/></Drawer></>';
 assert.deepEqual(inspectOfficialPresentation(source),[]);
});
test('negative controls reject hidden skill configuration, redirected execution and a private modal',()=>{
 for(const property of ['canConfigure={false}','onUse={redirect}','useActions={actions}','useDisabled={true}','useNotice="跳转对话"']){
  assert.ok(inspectOfficialPresentation('<SkillDrawer '+property+'/>').some(value=>value.rule==='official-skill-area-cannot-be-replaced'),property);
 }
 for(const source of ['<Modal/>','<dialog className="ew-dialog"/>','<div className="drawer-overlay"/>','<ChatPage emptyState={{brand:"私有",suggestions:[]}}/>','<SkillPage subtitle="私有文案"/>'])assert.ok(inspectOfficialPresentation(source).length,source);
});
test('negative list-style control rejects a private limit in official global styles',()=>{
 assert.ok(inspectOfficialListStyles('.trend-list{max-height:540px;overflow-y:auto}').length);
 assert.deepEqual(inspectOfficialListStyles('.trend-list{padding:4px}.ew-record{max-height:540px}'),[]);
});
