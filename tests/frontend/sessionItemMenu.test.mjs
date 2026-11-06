import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';

function gesture(){
 let now=0,id=0,opened=0;const timers=new Map();
 const {SessionPress}=moduleLoader()('workbench/ui/sessionPress.ts');
 const press=new SessionPress(()=>now,(fn,delay)=>{assert.equal(delay,450);timers.set(++id,fn);return id},key=>timers.delete(key));
 return {press,open:()=>opened++,get opened(){return opened},get pending(){return timers.size},fire:()=>{const entries=[...timers];timers.clear();for(const [,fn] of entries)fn()},advance:ms=>{now+=ms}};
}

test('quick taps and cancelled/scrolling gestures never open a menu or consume a click',()=>{
 for(const stop of [p=>p.end(1),p=>p.cancel(),p=>p.move(1,10,0),p=>p.nextPointer()]){
  const g=gesture();g.press.begin(1,0,0,g.open);stop(g.press);g.fire();assert.equal(g.opened,0);assert.equal(g.press.consumeClick(1),false);assert.equal(g.pending,0);
 }
});
test('long press opens exactly once and consumes only its original click, including a long hold',()=>{
 const g=gesture();g.press.begin(1,0,0,g.open);g.press.move(1,4,3);g.fire();g.fire();assert.equal(g.opened,1);
 g.advance(5000);assert.equal(g.press.consumeClick(2),false);g.press.end(1);assert.equal(g.press.consumeClick(1),true);assert.equal(g.press.consumeClick(1),false);
});
test('the next pointer clears old click suppression and a second touch cancels recognition',()=>{
 const g=gesture();g.press.begin(1,0,0,g.open);g.fire();g.press.nextPointer();assert.equal(g.press.consumeClick(1),false);
 g.press.begin(2,0,0,g.open);g.press.nextPointer();g.fire();assert.equal(g.opened,1);
});
test('click suppression expires after release rather than suppressing a later unrelated activation',()=>{
 const g=gesture();g.press.begin(1,0,0,g.open);g.fire();g.press.end(1);g.advance(1001);assert.equal(g.press.consumeClick(1),false);
});

const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
function sidebar(){
 const state=[];let cursor=0;const calls=[],icons=new Proxy({},{get:(_,name)=>name});
 const load=moduleLoader({imports:{react:{createElement:(type,props,...children)=>({type,props:{...props,children}}),useState:initial=>{const index=cursor++;if(!(index in state))state[index]=initial;return [state[index],value=>{state[index]=value}]}},'./SettingsSelect':{default:'SettingsSelect'},'./ThemeToggle':{default:'ThemeToggle'},'./icons':icons,'./settingsIcons':icons,'react/jsx-runtime':{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})}}});
 const Sidebar=load('components/Sidebar.tsx').default;
 const session={id:'one',title:'准确会话',messages:[{role:'user',content:'原话'}],archived:false};
 const props={sessions:[session],personas:[],currentPage:'chat',activeSessionId:'one',onSessionSelect:id=>calls.push(['open',id]),onSessionRename:(id,title)=>calls.push(['rename',id,title]),onSessionArchive:(id,value)=>calls.push(['archive',id,value]),onSessionDelete:id=>calls.push(['delete',id])};
 return {props,calls,render:()=>{cursor=0;return Sidebar(props)}};
}
test('optional presentation preserves native defaults and reuses the original rename/archive/delete handlers',()=>{
 const f=sidebar();let tree=f.render();assert.equal(nodes(tree).filter(n=>n.props?.className==='session-actions').length,1);
 let actions;f.props.sessionItemPresentation=(_session,current)=>{actions=current;return {actions:null,itemProps:{className:'host-touch'}}};
 tree=f.render();assert.equal(nodes(tree).filter(n=>n.props?.className==='session-actions').length,0);
 nodes(tree).find(n=>n.props?.className?.includes('host-touch')).props.onClick();assert.deepEqual(f.calls,[['open','one']]);
 actions.rename();let input=nodes(f.render()).find(n=>n.type==='input');assert.equal(input.props.autoFocus,true);input.props.onChange({target:{value:'新标题'}});
 input=nodes(f.render()).find(n=>n.type==='input');input.props.onKeyDown({key:'Enter'});f.render();actions.archive();actions.delete();
 assert.deepEqual(f.calls,[['open','one'],['rename','one','新标题'],['archive','one',true],['delete','one']]);
 f.props.canDeleteSession=false;f.render();assert.equal(actions.delete,undefined);
});

test('shared Drawer retains its default shell and accepts only an optional host overlay class',()=>{
 const {default:Drawer}=moduleLoader({imports:{react:{useId:()=> 'heading'},'react-dom':{createPortal:()=>assert.fail('No container means no portal')},'react/jsx-runtime':{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})}}})('components/Drawer.tsx');
 const base={title:'原抽屉',onClose(){},children:'内容'};
 assert.equal(Drawer(base).props.className,'drawer-overlay');assert.equal(Drawer({...base,overlayClassName:'host-menu'}).props.className,'drawer-overlay host-menu');
 assert.equal(nodes(Drawer(base)).find(n=>n.props.role==='dialog').props['aria-label'],'原抽屉');
});
