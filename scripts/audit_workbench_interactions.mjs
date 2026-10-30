import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),require=createRequire(path.join(root,'web/frontend/package.json')),ts=require('typescript');
export function inspectInteractions(source,file='view.tsx'){
 const ast=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX),violations=[],counts={buttons:0,notices:0,backgroundRefreshes:0};
 const issue=(node,rule)=>violations.push({file,line:ast.getLineAndCharacterOfPosition(node.getStart(ast)).line+1,rule});
 function visit(node){
  if(ts.isAwaitExpression(node)&&ts.isCallExpression(node.expression)&&ts.isExpressionStatement(node.parent)){
   const call=node.expression.expression;
   if(ts.isPropertyAccessExpression(call)&&['reload','refresh'].includes(call.name.text)||ts.isIdentifier(call)&&call.text==='reload')issue(node,'view-refresh-blocks-action');
  }
  if(ts.isCallExpression(node)&&node.expression.getText(ast)==='refreshViews')counts.backgroundRefreshes++;
  if(ts.isJsxOpeningElement(node)||ts.isJsxSelfClosingElement(node)){
   const name=node.tagName.getText(ast);
   if(name==='ActionButton')counts.buttons++;
   if(name==='Notice'){
    counts.notices++;
    const message=node.attributes.properties.find(p=>ts.isJsxAttribute(p)&&p.name.getText(ast)==='message');
    if(message?.initializer&&/\b\w+\.error\b/.test(message.initializer.getText(ast)))issue(message,'typed-feedback-required');
   }
   if(name==='button'){
    const disabled=node.attributes.properties.find(p=>ts.isJsxAttribute(p)&&p.name.getText(ast)==='disabled');let owner=node.parent;while(owner&&!ts.isFunctionDeclaration(owner))owner=owner.parent;
    if(disabled?.initializer&&/\b\w+\.busy\b/.test(disabled.initializer.getText(ast))&&owner?.name?.text!=='ActionButton')issue(disabled,'shared-action-button-required');
   }
   const cls=node.attributes.properties.find(p=>ts.isJsxAttribute(p)&&p.name.getText(ast)==='className');
   if(cls?.initializer&&/notice-error/.test(cls.initializer.getText(ast)))issue(cls,'error-presentation-must-be-shared');
  }
  if(ts.isJsxText(node)&&/核对原操作|核对原请求/.test(node.getText(ast)))issue(node,'manual-receipt-step-retired');
  ts.forEachChild(node,visit);
 }
 visit(ast);return {violations,counts};
}
export function auditInteractions(base=root){
 const ui=path.join(base,'web/frontend/src/workbench/ui'),files=fs.readdirSync(ui,{recursive:true}).filter(name=>/\.(ts|tsx)$/.test(name)),results=[];
 files.push(...['SettingsPanel','HarnessSettings','TrendsView','TrendSourcesDialog'].map(name=>'../../components/'+name+'.tsx'));
 for(const name of files){const file=path.join(ui,name);results.push(inspectInteractions(fs.readFileSync(file,'utf8'),path.relative(base,file).replaceAll('\\','/')))}
 const settings=fs.readFileSync(path.join(ui,'settingsApi.ts'),'utf8');
 if(/client\.drafts|client\.api\.post/.test(settings))results.push({counts:{buttons:0,notices:0,backgroundRefreshes:0},violations:[{file:'settingsApi.ts',line:1,rule:'settings-must-use-shared-command-recovery'}]});
 const violations=results.flatMap(r=>r.violations),counts=results.reduce((all,r)=>Object.fromEntries(Object.keys(all).map(k=>[k,all[k]+r.counts[k]])),{buttons:0,notices:0,backgroundRefreshes:0});
 return {passed:violations.length===0,files:files.length,counts,violations};
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const report=auditInteractions(),out=process.argv.indexOf('--out');if(out>=0)fs.writeFileSync(process.argv[out+1],JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));if(!report.passed)process.exitCode=1;
}
