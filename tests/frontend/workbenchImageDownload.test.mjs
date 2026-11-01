import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';

const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const root=new URL('../../web/frontend/src/workbench/',import.meta.url);
const jsx={jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})};
function load(path,imports={},globals={}){
 const exports={},source=readFileSync(new URL(path,root),'utf8');
 const output=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 runInNewContext(output,{exports,URL,URLSearchParams,...globals,require:id=>id==='react/jsx-runtime'?jsx:imports[id]||{}});
 return exports;
}
const models=load('core/models.ts');
const core={...models,array:value=>Array.isArray(value)?value:[],string:value=>typeof value==='string'?value:''};
const {productArtifacts}=load('ui/ChatTurnProducts.tsx',{'@workbench/core':core});
const file={id:'picture',name:'原图.png',mime:'image/png',url:'/api/files/picture'};
const signed='/media/images/picture/'+encodeURIComponent(file.name)+'?expires=1999999999&session='+'a'.repeat(64)+'&signature='+'b'.repeat(64);

test('chat gallery downloads use the validated image capability instead of cookie-only API',()=>{
 const [artifact]=productArtifacts([{...file,image_url:signed}]);
 assert.equal(artifact.url,file.url);
 assert.equal(artifact.downloadUrl,signed+'&download=1');
 assert.equal(artifact.name,file.name);
});

test('missing, external and mismatched capabilities keep the authenticated download fallback',()=>{
 for(const image_url of [undefined,'https://external.test'+signed,signed.replace('/picture/','/different/'),signed.replace(encodeURIComponent(file.name),'other.png')]){
  assert.equal(productArtifacts([{...file,image_url}])[0].downloadUrl,file.url+'?download=1');
 }
 assert.equal(productArtifacts([{...file,mime:'text/plain',image_url:signed}])[0].downloadUrl,file.url+'?download=1');
});

test('interrupted products preserve exact turn-scoped endpoints even if decorated with an image URL',()=>{
 const url='/api/chat/products/turn/files/'+'c'.repeat(64);
 const [artifact]=productArtifacts([{...file,url,partial:true,image_url:signed}]);
 assert.equal(artifact.url,url);
 assert.equal(artifact.downloadUrl,url+'?download=1');
});

function descendants(node){return !node?[]:Array.isArray(node)?node.flatMap(descendants):typeof node==='object'?[node,...descendants(node.props?.children)]:[]}
test('expanded image preview keeps the gallery download capability and legacy fallback',()=>{
 const {default:ImagePreview}=load('ui/ImagePreview.tsx');
 for(const downloadUrl of [signed+'&download=1',undefined]){
  const tree=ImagePreview({image:{url:file.url,name:file.name,downloadUrl},close:()=>{}});
  const link=descendants(tree).find(node=>node.props?.download===file.name);
  assert.equal(link.props.href,downloadUrl||file.url);
  assert.equal(link.props.download,file.name);
 }
});

test('opening the gallery image passes its same-origin download link to the modal',()=>{
 let click,opened,prevented=0;
 const origin='https://native.test',url=origin+file.url;
 const image={src:url,alt:file.name};
 const gallery={querySelector:()=>({href:origin+signed+'&download=1'})};
 class Element {closest(selector){return selector==='.artifact-gallery'?gallery:this}querySelector(){return image}}
 const anchor=new Element();Object.assign(anchor,{href:url,target:'_blank',hasAttribute:()=>false,dataset:{}});
 const document={querySelectorAll:()=>[],getElementById:()=>({}),addEventListener:(_,fn)=>{click=fn},removeEventListener:()=>{}};
 const {bindNavigationLinks}=load('platform/links.ts',{}, {document,location:{origin},Element,matchMedia:()=>({matches:true}),MutationObserver:class{observe(){}disconnect(){}}});
 bindNavigationLinks({},value=>{opened=value});
 click({target:anchor,button:0,preventDefault:()=>prevented++,stopPropagation:()=>{}});
 assert.equal(prevented,1);
 assert.equal(opened.url,url);
 assert.equal(opened.downloadUrl,origin+signed+'&download=1');
});
