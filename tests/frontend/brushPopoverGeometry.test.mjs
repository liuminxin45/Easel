import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const source=readFileSync(new URL('../../web/frontend/src/components/useBrushPopover.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
function load(globals={}){const exports={};runInNewContext(compiled,{exports,require:()=>({useLayoutEffect:()=>{}}),...globals});return exports;}
const {brushPopoverPlacement:place}=load(),rect=(left,top,width,height)=>({left,top,width,height});
function bounded(viewport,result,width,height){assert.ok(result);assert.ok(result.left>=viewport.left+8);assert.ok(result.top>=viewport.top+8);assert.ok(result.left+Math.min(width,result.maxWidth)<=viewport.left+viewport.width-8);assert.ok(result.top+Math.min(height,result.maxHeight)<=viewport.top+viewport.height-8);}

test('authored popovers inside the viewport retain their exact default placement',()=>{
 assert.equal(place(rect(0,0,1280,900),rect(460,700,540,100),rect(460,350,540,330)),null);
 assert.equal(place(rect(0,0,320,844),rect(12,624,296,200),rect(12,192,288,420)),null);
});

test('landscape slash and brush overflow fit without requiring space above the composer',()=>{
 const viewport=rect(0,0,844,390);
 for(const panel of [rect(12,-69,540,229),rect(24,-47,540,230)]){
  const result=place(viewport,rect(12,172,820,200),panel);bounded(viewport,result,panel.width,panel.height);
  assert.equal(result.top,8);assert.equal(result.maxHeight,panel.height);
 }
});

test('a lower placement is used when it fits and upper space is insufficient',()=>{
 const result=place(rect(0,0,320,844),rect(12,48,46,46),rect(12,-254,288,290));
 assert.equal(result.top,106);bounded(rect(0,0,320,844),result,288,290);
});

test('viewport offsets, an oversized panel, and tablet sidebars are bounded independently',()=>{
 const viewport=rect(15,200,320,240),panel=rect(0,-20,540,420),result=place(viewport,rect(30,340,288,180),panel);
 bounded(viewport,result,panel.width,panel.height);assert.equal(result.maxWidth,304);assert.equal(result.maxHeight,224);
 const tablet=place(rect(0,0,768,1024),rect(291,850,460,160),rect(291,418,540,420));bounded(rect(0,0,768,1024),tablet,540,420);
 assert.equal(tablet.left,220);assert.equal(tablet.maxHeight,420);
});

test('an IME-height viewport scrolls the whole existing panel when header and tabs crowd out the first row',()=>{
 const viewport=rect(0,120,320,240),panel=rect(12,132,288,80),result=place(viewport,rect(12,260,288,100),panel,164);
 assert.equal(result.wholePanelScroll,true);assert.equal(result.maxHeight,224);bounded(viewport,result,288,224);
 const short=place(rect(0,0,320,180),rect(12,130,288,40),rect(12,-100,288,120),164);
 assert.equal(short.wholePanelScroll,true);assert.equal(short.maxHeight,164);bounded(rect(0,0,320,180),short,288,164);
});

test('shared positioning converts to the offset parent, ignores list scroll, switches a cramped IME panel and restores every style',()=>{
 const events=new Map(),viewportEvents=new Map(),frames=new Map();let serial=0,measures=0,disconnected=0,cancelled=0,cleanup,headerHeight=90;
 class Node{}
 const original=new Map([['left','11px']]),style={getPropertyValue:name=>original.get(name)||'',getPropertyPriority:()=>'',setProperty:(name,value)=>original.set(name,value),removeProperty:name=>original.delete(name)};
 const viewport={offsetLeft:0,offsetTop:0,width:844,height:390,addEventListener:(name,fn)=>viewportEvents.set(name,fn),removeEventListener:(name,fn)=>{assert.equal(viewportEvents.get(name),fn);viewportEvents.delete(name)}};
 const win={Node,visualViewport:viewport,innerWidth:844,innerHeight:390,addEventListener:(name,fn)=>events.set(name,fn),removeEventListener:(name,fn)=>{assert.equal(events.get(name),fn);events.delete(name)},requestAnimationFrame:fn=>{const id=++serial;frames.set(id,fn);return id},cancelAnimationFrame:id=>{frames.delete(id);cancelled++}};
 const parent={getBoundingClientRect:()=>rect(100,160,600,200),clientLeft:2,clientTop:3,scrollLeft:9,scrollTop:7,offsetWidth:600,offsetHeight:200};
 const bodyStyles=new Map([['overflow-y','auto']]),bodyStyle={getPropertyValue:name=>bodyStyles.get(name)||'',getPropertyPriority:()=>'',setProperty:(name,value)=>bodyStyles.set(name,value),removeProperty:name=>bodyStyles.delete(name)};
 const body={style:bodyStyle},header={getBoundingClientRect:()=>rect(112,8,540,headerHeight),get scrollHeight(){return headerHeight}};
 const child=new Node(),anchor={getBoundingClientRect:()=>rect(112,172,580,200)},panel={style,ownerDocument:{defaultView:win},offsetParent:parent,children:[header,body],querySelector:()=>body,contains:target=>target===child,getBoundingClientRect:()=>{measures++;return rect(112,-69,540,229)}};
 const observed=[];class ResizeObserver{constructor(fn){this.callback=fn}observe(node){observed.push(node)}disconnect(){disconnected++}}
 const module=load({ResizeObserver,require:()=>({useLayoutEffect:fn=>{cleanup=fn()}})});
 module.useBrushPopover(true,{current:anchor},{current:panel},'all');
 assert.equal(original.get('top'),'-148px');assert.equal(original.get('left'),'19px');assert.equal(original.get('bottom'),'auto');
 assert.equal(original.get('max-block-size'),'229px');assert.deepEqual(observed,[anchor,parent]);
 const afterInitial=measures;events.get('scroll')({target:child});assert.equal(frames.size,0);assert.equal(measures,afterInitial);
 viewport.height=240;headerHeight=190;viewportEvents.get('resize')();events.get('resize')();assert.equal(frames.size,1);
 for(const [id,fn] of [...frames]){frames.delete(id);fn()}
 assert.ok(measures>afterInitial);assert.equal(original.get('overflow-y'),'auto');assert.equal(original.get('display'),'block');assert.equal(bodyStyles.get('overflow-y'),'visible');assert.equal(bodyStyles.get('max-block-size'),'none');
 events.get('scroll')({target:child});assert.equal(frames.size,0);
 viewport.height=390;headerHeight=90;viewportEvents.get('resize')();for(const [id,fn] of [...frames]){frames.delete(id);fn()}
 assert.equal(original.has('display'),false);assert.equal(original.has('overflow-y'),false);assert.deepEqual([...bodyStyles],[['overflow-y','auto']]);
 viewportEvents.get('scroll')();assert.equal(frames.size,1);
 cleanup();assert.equal(disconnected,1);assert.equal(cancelled,1);assert.equal(events.size,0);assert.equal(viewportEvents.size,0);assert.equal(frames.size,0);
 assert.deepEqual([...original],[['left','11px']]);
 assert.deepEqual([...bodyStyles],[['overflow-y','auto']]);
});
