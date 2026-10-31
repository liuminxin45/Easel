import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';

function fixture(compact=true){
 const anchors=[],listeners=new Map(),navigated=[],assigned=[],images=[];
 const location={origin:'https://owner.test',href:'https://owner.test/native/?path=%2Fchat%2Fsession',assign:url=>assigned.push(url)};
 class Element{}
 class Anchor extends Element{
  constructor(href,{target='_blank',download=false,image=null,galleryImage=null}={}){super();this.raw=href;this.target=target;this.isDownload=download;this.image=image;this.galleryImage=galleryImage;this.dataset={};anchors.push(this)}
  get href(){return new URL(this.raw,location.href).href}
  getAttribute(){return this.raw}
  setAttribute(name,value){if(name==='href')this.raw=value}
  hasAttribute(name){return name==='download'&&this.isDownload}
  querySelector(){return this.image}
  closest(selector){return selector==='#root a[href]'?this:selector==='.artifact-gallery'&&this.galleryImage?{querySelector:()=>this.galleryImage}:null}
 }
 let mutation;
 const load=moduleLoader({globals:{location,Element,matchMedia:()=>({matches:compact}),
  document:{querySelectorAll:()=>anchors,getElementById:()=>({}),addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name)},
  MutationObserver:class{constructor(fn){mutation=fn}observe(){}disconnect(){}}}});
 const {bindNavigationLinks,mobileDocumentLink}=load('workbench/platform/links.ts');
 const bind=()=>bindNavigationLinks({publicUrl:path=>'/native/?'+new URLSearchParams({path}),snapshot:()=>({path:'/chat/session'}),navigate:path=>navigated.push(path)},image=>images.push(image));
 const click=(target,changes={})=>{const event={target,button:0,defaultPrevented:false,preventDefault(){this.defaultPrevented=true},stopPropagation(){},...changes};listeners.get('click')(event);return event};
 return {Anchor,anchors,bind,click,navigated,assigned,images,mutate:()=>mutation(),mobileDocumentLink};
}

test('mobile links preserve a browser return source for external pages and opaque local files',()=>{
 const f=fixture(),external=new f.Anchor('https://source.test/article?original=1#section'),html=new f.Anchor('/api/outputs/file?path=article.html'),file=new f.Anchor('/api/chat/products/turn/files/'+'a'.repeat(64));
 f.bind();for(const anchor of [external,html,file])assert.ok(f.click(anchor).defaultPrevented);
 assert.deepEqual(f.assigned,[external.href,html.href,file.href]);assert.deepEqual(f.navigated,[]);
});

test('inline artwork and its open action share the existing modal callback without leaving the session',()=>{
 const f=fixture(),image={src:'https://owner.test/api/files/exact?token=version',alt:'准确原图.png'},inline=new f.Anchor(image.src,{image}),open=new f.Anchor(image.src,{galleryImage:image});
 f.bind();f.click(inline);f.click(open);
 assert.equal(f.images.length,2);assert.ok(f.images.every(value=>value.url===image.src&&value.name===image.alt));assert.deepEqual(f.assigned,[]);
});

test('in-app links use the navigation owner even when shared markup requests a mobile new tab',()=>{
 const f=fixture(),anchor=new f.Anchor('/works/exact-version');f.bind();f.click(anchor);
 assert.deepEqual(f.navigated,['/works/exact-version']);assert.deepEqual(f.assigned,[]);
});

test('desktop documents, downloads, custom targets, schemes and modified clicks keep native browser behavior',()=>{
 const desktop=fixture(false),external=new desktop.Anchor('https://source.test/article');desktop.bind();assert.equal(desktop.click(external).defaultPrevented,false);
 const f=fixture(),download=new f.Anchor('/api/files/exact',{download:true}),target=new f.Anchor('https://source.test',{target:'review-window'}),email=new f.Anchor('mailto:owner@example.test'),source=new f.Anchor('https://source.test');f.bind();
 for(const anchor of [download,target,email])assert.equal(f.click(anchor).defaultPrevented,false);
 for(const change of [{ctrlKey:true},{metaKey:true},{shiftKey:true},{altKey:true},{button:1},{defaultPrevented:true}])f.click(source,change);
 assert.deepEqual(f.assigned,[]);assert.deepEqual(f.images,[]);assert.deepEqual(f.navigated,[]);
});

test('a reused anchor cannot keep a stale internal destination after changing to an external or download URL',()=>{
 const f=fixture(),anchor=new f.Anchor('/works/one');f.bind();anchor.raw='https://source.test/article';f.mutate();f.click(anchor);
 assert.deepEqual(f.navigated,[]);assert.deepEqual(f.assigned,['https://source.test/article']);
});

test('document routing excludes unsafe schemes and ordinary internal navigation',()=>{
 const {mobileDocumentLink}=fixture();
 for(const path of ['javascript:alert(1)','data:text/html,x','mailto:test@example.test','tel:123','/chat/exact','/native/?path=%2Fworks'])assert.equal(mobileDocumentLink(path,'https://owner.test'),false,path);
 for(const path of ['https://source.test','/api/files/id?download=0','/api/media/path.png','/media/path.png','/api/outputs/file?path=x.html'])assert.equal(mobileDocumentLink(path,'https://owner.test'),true,path);
});
