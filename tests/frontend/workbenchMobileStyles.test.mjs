import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {test} from 'node:test';
import {inspectMobileCss} from '../../scripts/audit_easel_base.mjs';

const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url));
const postcss=require('postcss');
const css=readFileSync(new URL('../../web/frontend/src/workbench/ui/styles/mobile.css',import.meta.url),'utf8');
const source=readFileSync(new URL('../../web/frontend/src/workbench/ui/index.tsx',import.meta.url),'utf8');
const inspect=inspectMobileCss;

function value(selector,property){
 const values=[];postcss.parse(css).walkRules(rule=>{if(rule.selectors.includes('html[data-native-platform] '+selector))rule.walkDecls(property,decl=>values.push(decl.value));});return values.at(-1);
}

test('all mobile geometry is host-scoped and viewport-limited, preserving native appearance',()=>{
 assert.deepEqual(inspect(css),[]);
 assert.equal((source.match(/import '\.\/styles\/mobile\.css';/g)||[]).length,1);
 assert.ok(source.indexOf("import './styles/mobile.css'")>source.indexOf("import './styles/workbench.css'"));
});

test('negative controls reject unscoped portals, desktop restyling, hidden overflow and hidden controls',()=>{
 for(const bad of ['@media (max-width: 760px){.model-dd{width:100%}}',
  'html[data-native-platform] .btn{color:red}',
  '@media (max-width: 760px){html[data-native-platform] .page-scroll{overflow-x:hidden}}',
  '@media (max-width: 760px){html[data-native-platform] .btn{display:none}}'])assert.ok(inspect(bad).length,bad);
});

test('only paired private work panes may use the existing narrow tab visibility policy',()=>{
 const idle='html[data-native-platform] .ew-work-chat:not(.ew-selected)',active='html[data-native-platform] .ew-work-chat.ew-selected';
 assert.deepEqual(inspect(`@media (max-width: 900px){${idle}{display:none}${active}{display:block}}`),[]);
 assert.ok(inspect(`@media (max-width: 900px){${idle}{display:none}}`).length);
 assert.ok(inspect(`@media (max-width: 900px){${idle} button{display:none}${active}{display:block}}`).length);
});

test('bounded feed lists hand boundary touch back to the page while modal bodies contain it',()=>{
 for(const selector of ['.trend-list','.dash-card-list']){
  assert.equal(value(selector,'overscroll-behavior-y'),'auto');
  assert.equal(value(selector,'max-block-size'),undefined);
  assert.equal(value(selector,'max-height'),undefined);
 }
 for(const selector of ['.ew-dialog[open] > .drawer-body','.overlay > .modal','.drawer','.settings-main'])assert.equal(value(selector,'overscroll-behavior-y'),'contain');
});

test('fixed publishing, library and settings columns actually reflow instead of clipping',()=>{
 assert.equal(value('.publish-editor','min-inline-size'),'0');
 assert.equal(value('.outputs-tree','min-inline-size'),'0');
 assert.equal(value('.outputs-page','flex-direction'),'column');
 assert.equal(value('.kanban','grid-template-columns'),'minmax(0, 1fr)');
 assert.equal(value('.settings-overlay .prow','grid-template-columns'),'32px minmax(0, 1fr)');
 assert.equal(value('.settings-overlay .la-act','flex'),'1 1 100%');
 assert.equal(value('.settings-overlay .grid','grid-template-columns'),'minmax(0, 1fr)');
 assert.equal(value('.page-host:has(> .publishing-workspace) > .workbench-extension','flex'),'0 0 auto');
});

test('nested private dialogs have the same constrained width and one scrollable body',()=>{
 assert.equal(value('.ew-dialog .ew-dialog[open]','inline-size'),'calc(100vw - 16px)');
 assert.equal(value('.ew-dialog[open] > .drawer-body','max-block-size'),'none');
 assert.equal(value('.ew-dialog[open] > .drawer-body','min-block-size'),'0');
 assert.equal(value('.ew-dialog[open] > .drawer-body','overflow-y'),'auto');
});

test('short landscape and persistence notices keep navigation/footer and fallback reachable',()=>{
 assert.equal(value('.native-host > .native-host-notice','flex'),'0 0 auto');
 assert.equal(value('.native-host > .app-layout','block-size'),'auto');
 assert.equal(value('.native-host > .app-layout','min-block-size'),'0');
 assert.equal(value('.native-boot-failure','overflow-y'),'auto');
 assert.equal(value('.sidebar','overflow-y'),'auto');
 assert.match(css,/max-width: 1100px\) and \(max-height: 500px/);
});
