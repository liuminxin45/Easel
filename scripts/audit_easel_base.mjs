import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {execFileSync,spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const require=createRequire(path.join(root,'web/frontend/package.json'));
const ts=require('typescript'),postcss=require('postcss');
export const OFFICIAL_BASELINE='5a597e5f3ef5b01098b53f36caf719dd9a32b7bf';
const hostWrappers=new Set(['ew-page','ew-app','ew-main','ew-settings-host']);
const protectedClasses=new Set(['nav-item','persona-select','theme-toggle','accounts-page','accounts-grid']);

export function inspectSource(source,file='view.tsx'){
 const ast=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 const imports=[],elements=[],functions=[],violations=[];
 const visit=node=>{
  if(ts.isImportDeclaration(node)&&ts.isStringLiteral(node.moduleSpecifier))imports.push({
   path:node.moduleSpecifier.text,name:node.importClause?.name?.text,
   typeOnly:node.importClause?.isTypeOnly===true});
  if(ts.isFunctionDeclaration(node)&&node.name)functions.push({name:node.name.text,node});
  if(ts.isJsxOpeningElement(node)||ts.isJsxSelfClosingElement(node)){
   const attribute=node.attributes.properties.find(value=>ts.isJsxAttribute(value)&&value.name.getText(ast)==='className');
   const classes=attribute?.initializer&&ts.isStringLiteral(attribute.initializer)?attribute.initializer.text.split(/\s+/):[];
   elements.push({name:node.tagName.getText(ast),classes,line:ast.getLineAndCharacterOfPosition(node.getStart(ast)).line+1});
  }
  ts.forEachChild(node,visit);
 };
 visit(ast);
 return {ast,imports,elements,functions,violations};
}

export function inspectNativeUse(source,component,importPath,file){
 const facts=inspectSource(source,file),violations=[];
 const binding=facts.imports.find(value=>value.path===importPath&&!value.typeOnly)?.name;
 if(!binding||!facts.elements.some(value=>value.name===binding))violations.push({file,rule:'native-component-must-be-rendered',component});
 if(component==='AccountsPage'){
  for(const element of facts.elements){
   if(element.name!==binding)violations.push({file,line:element.line,rule:'account-ui-must-remain-native',element:element.name});
  }
  for(const value of facts.functions){
   if(['AccountCard','ConnectionEnvironment'].includes(value.name))violations.push({file,rule:'parallel-account-component',component:value.name});
  }
 }
 if(component==='App'&&facts.elements.some(value=>value.name==='Sidebar'||value.classes.includes('app-layout')))
  violations.push({file,rule:'host-cannot-rebuild-native-frame'});
 return violations;
}

export function inspectFrame(source,file='web/frontend/src/App.tsx'){
 const facts=inspectSource(source,file),violations=[];
 if(facts.elements.filter(value=>value.classes.includes('app-layout')).length!==1)violations.push({file,rule:'one-native-application-frame'});
 const app=facts.functions.find(value=>value.name==='App'),native=facts.functions.find(value=>value.name==='NativeApp');
 if(!app||!native||!facts.functions.some(value=>value.name==='ApplicationFrame'))violations.push({file,rule:'native-default-app-must-remain'});
 else {
  const inspectBody=node=>inspectSource(node.body?.getText(facts.ast)||'',file);
  if(!inspectBody(app.node).elements.some(value=>value.name==='NativeApp'))violations.push({file,rule:'native-default-app-must-remain'});
  if(!inspectBody(native.node).elements.some(value=>value.name==='ApplicationFrame'))violations.push({file,rule:'native-default-must-use-shared-frame'});
 }
 return violations;
}

function splitSelectors(selector){
 const values=[];let depth=0,start=0;
 for(let i=0;i<selector.length;i++){
  if(selector[i]==='('||selector[i]==='[')depth++;
  if(selector[i]===')'||selector[i]===']')depth--;
  if(selector[i]===','&&depth===0){values.push(selector.slice(start,i).trim());start=i+1;}
 }
 values.push(selector.slice(start).trim());return values;
}

export function inspectExtensionCss(source,file='workbench.css'){
 const violations=[];const sheet=postcss.parse(source,{from:file});
 sheet.walkRules(rule=>{
  let parent=rule.parent;while(parent){if(parent.type==='atrule'&&/keyframes$/i.test(parent.name))return;parent=parent.parent;}
  for(const selector of splitSelectors(rule.selector)){
   const classes=[...selector.matchAll(/\.([_a-zA-Z][\w-]*)/g)].map(value=>value[1]);
   const anchor=selector.match(/^(?:[_a-zA-Z][\w-]*)?\.(ew-[\w-]+)/)?.[1];
   if(!anchor||hostWrappers.has(anchor))violations.push({file,line:rule.source.start.line,rule:'extension-selector-must-be-owned',selector});
   if(classes.some(value=>protectedClasses.has(value)||value==='sidebar'||value.startsWith('sidebar-')||value.startsWith('account-')))violations.push({file,line:rule.source.start.line,rule:'common-component-style-override',selector});
  }
 });
 return violations;
}

export function inspectHostCss(source,file='host.css'){
 const violations=[];const sheet=postcss.parse(source,{from:file});
 const viewportProperties=new Set(['height','width','min-height','max-height','min-width','max-width','overflow','overflow-x','overflow-y']);
 sheet.walkRules(rule=>{
  if(!splitSelectors(rule.selector).some(selector=>/^(?::root|body|html|#root)(?:$|[\s:.#>+~])/.test(selector)))return;
  rule.walkDecls(declaration=>{
   if(viewportProperties.has(declaration.prop)||declaration.prop.startsWith('--native-'))return;
   violations.push({file,line:declaration.source.start.line,rule:'global-host-styles-must-be-viewport-only',selector:rule.selector,property:declaration.prop});
  });
 });
 sheet.walkDecls(declaration=>{
  if(!/^(?:font(?:-|$)|line-height|letter-spacing)/.test(declaration.prop))return;
  const selector=declaration.parent.selector||'';
  if(splitSelectors(selector).every(value=>/^\.native-host-notice(?:\s|$|[:.])/.test(value)))return;
  violations.push({file,line:declaration.source.start.line,rule:'host-must-not-set-common-typography',selector,property:declaration.prop});
 });return violations;
}

// The native host may adapt geometry to a small viewport without restyling
// shared Easel components. Keep that exception explicit and mechanically bounded.
export function inspectMobileCss(source,file='mobile.css'){
 const violations=[],sheet=postcss.parse(source,{from:file});
 const geometry=new Set(['display','flex','flex-direction','flex-wrap','flex-shrink','flex-basis','align-items','align-content','justify-content','gap',
  'position','grid-template-columns','grid-column','inline-size','block-size','min-inline-size','min-block-size','max-inline-size','max-block-size',
  'padding','padding-inline','padding-block-end','padding-inline-end','margin-inline-start','margin-block-end','border-inline-end-width',
  'overflow','overflow-x','overflow-y','overscroll-behavior-y','overflow-wrap','white-space','opacity']);
 const viewport=/^\(max-width: (?:480|760|900|1100)px\)(?:, \(max-width: 1100px\) and \(max-height: 500px\))?$|^\(max-width: 1100px\) and \(max-height: 500px\)$/;
 const report=(node,rule,extra={})=>violations.push({file,line:node.source.start.line,rule,...extra});
 sheet.walkAtRules(node=>{if(node.name!=='media')report(node,'mobile-adapter-must-use-viewport-media');});
 sheet.walkRules(node=>{
  if(!splitSelectors(node.selector).every(selector=>selector.startsWith('html[data-native-platform] ')))report(node,'mobile-adapter-must-be-host-scoped');
  if(node.parent.type!=='atrule'||node.parent.name!=='media'||!viewport.test(node.parent.params))report(node,'mobile-adapter-viewport-unreviewed');
  node.walkDecls(decl=>{
   if(!geometry.has(decl.prop)||decl.important)report(decl,'mobile-adapter-must-preserve-appearance',{property:decl.prop});
   if((decl.prop==='overflow'||decl.prop==='overflow-x')&&/hidden|clip/.test(decl.value))report(decl,'mobile-adapter-must-not-conceal-overflow');
   if(decl.prop==='display'&&decl.value==='none'){
    const selectors=splitSelectors(node.selector);
    const pairedTabs=selectors.every(selector=>{
     if(!/^html\[data-native-platform\] \.ew-work-(?:preview|chat|records):not\(\.ew-selected\)$/.test(selector))return false;
     let shown=false;const active=selector.replace(':not(.ew-selected)','.ew-selected');
     sheet.walkRules(peer=>{if(peer.parent.type==='atrule'&&peer.parent.params===node.parent.params&&splitSelectors(peer.selector).includes(active))peer.walkDecls('display',value=>{if(value.value==='block')shown=true;});});
     return shown;
    });
    if(!pairedTabs)report(decl,'mobile-adapter-must-not-hide-controls');
   }
   if(decl.prop==='opacity'&&decl.value!=='1')report(decl,'mobile-adapter-must-not-hide-controls');
  });
 });return violations;
}

export function auditEaselBase(base=root){
 const read=file=>fs.readFileSync(path.join(base,file),'utf8');const violations=[];
 const nativeUse=[['web/frontend/src/workbench/ui/index.tsx','App','../../App'],
  ['web/frontend/src/workbench/ui/PlatformAccounts.tsx','AccountsPage','../../components/AccountsPage'],
  ...['DashboardPage','OutputsPage','IdeasPage','TrendsPage','CalendarPage','BreakdownPage'].map(name=>
   ['web/frontend/src/workbench/ui/nativePages.tsx',name,'../../components/'+name]),
  ['web/frontend/src/workbench/ui/nativeProfiles.tsx','ProfilePage','../../components/ProfilePage'],
  ['web/frontend/src/workbench/ui/publishing.tsx','PublishingPage','../../components/PublishingPage'],
  ['web/frontend/src/workbench/ui/ChatSessionView.tsx','ChatPage','../../components/ChatPage'],
  ['web/frontend/src/workbench/ui/NativeSkills.tsx','SkillPage','../../components/SkillPage'],
  ['web/frontend/src/workbench/ui/NativeSkills.tsx','SkillDrawer','../../components/SkillDrawer'],
  ['web/frontend/src/workbench/ui/system.tsx','SettingsPanel','../../components/SettingsPanel']];
 for(const [file,component,target] of nativeUse)violations.push(...inspectNativeUse(read(file),component,target,file));
 violations.push(...inspectFrame(read('web/frontend/src/App.tsx')));
 violations.push(...inspectExtensionCss(read('web/frontend/src/workbench/ui/styles/workbench.css')));
 violations.push(...inspectHostCss(read('web/frontend/src/workbench/host.css')));
 const mobile='web/frontend/src/workbench/ui/styles/mobile.css';
 if(fs.existsSync(path.join(base,mobile)))violations.push(...inspectMobileCss(read(mobile),mobile));
 for(const name of ['index','theme']){
  const file=`web/frontend/src/workbench/ui/styles/${name}.css`;
  if(fs.existsSync(path.join(base,file))){
   const sheet=postcss.parse(read(file));
   if(sheet.nodes.some(node=>node.type!=='comment'&&!(node.type==='atrule'&&node.name==='import')))violations.push({file,rule:'parallel-native-stylesheet'});
  }
 }
 for(const file of ['easel_workbench/runtime/settings_upstream.py','scripts/extract_workbench_settings.py']){
  if(fs.existsSync(path.join(base,file)))violations.push({file,rule:'generated-native-source-copy'});
 }
 const manifestFile='docs/workbench/upstream-base.json';let manifest;
 try{manifest=JSON.parse(read(manifestFile));if(manifest.upstream_commit!==OFFICIAL_BASELINE)violations.push({file:manifestFile,rule:'official-baseline-mismatch'});}
 catch{violations.push({file:manifestFile,rule:'tracked-upstream-manifest-required'});}
 const ancestry=spawnSync('git',['merge-base','--is-ancestor',OFFICIAL_BASELINE,'HEAD'],{cwd:base,encoding:'utf8'});
 if(ancestry.status!==0)violations.push({rule:'official-baseline-must-be-ancestor'});
 const officialStyles=spawnSync('git',['show',`${OFFICIAL_BASELINE}:web/frontend/src/index.css`],{cwd:base,encoding:'utf8'});
 if(officialStyles.status!==0||officialStyles.stdout.replaceAll('\r\n','\n')!==read('web/frontend/src/index.css').replaceAll('\r\n','\n'))
  violations.push({file:'web/frontend/src/index.css',rule:'native-style-entry-must-match-official'});
 const packageJson=JSON.parse(read('web/frontend/package.json'));
 if(packageJson.scripts.build!=='tsc -b && vite build')violations.push({file:'web/frontend/package.json',rule:'standalone-native-build-must-remain-independent'});
 const main=inspectSource(read('web/frontend/src/main.tsx'),'main.tsx');
 if(!main.imports.some(value=>value.path==='./App.tsx'))violations.push({file:'web/frontend/src/main.tsx',rule:'standalone-native-entry-required'});
 return {passed:violations.length===0,upstream_commit:OFFICIAL_BASELINE,
  head:execFileSync('git',['rev-parse','HEAD'],{cwd:base,encoding:'utf8'}).trim(),violations};
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 if(process.version!=='v24.19.0')throw Error('Node 24.19.0 required');
 const report=auditEaselBase(),out=process.argv.indexOf('--out');
 if(out>=0)fs.writeFileSync(process.argv[out+1],JSON.stringify(report,null,2));
 console.log(JSON.stringify(report,null,2));if(!report.passed)process.exitCode=1;
}
