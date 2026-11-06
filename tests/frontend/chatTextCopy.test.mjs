import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';
const {copySectionLabel,copyLiteralText,attachChatTextCopy}=moduleLoader()('workbench/ui/lib/chatTextCopy.ts');

test('only explicit title, body and caption fields become copy targets',()=>{
 for(const name of ['标题',' 正文： ','配文:','文章标题','贴图标题'])assert.ok(copySectionLabel(name));
 for(const name of ['标题与配文文件','这是一段正文说明','执行命令','配图准备','标题包含敏感词',''])assert.equal(copySectionLabel(name),null);
 assert.equal(typeof attachChatTextCopy(null),'function');
});

test('clipboard receives literal complete paragraphs and URLs without HTML conversion',async()=>{
 const copied=[],text='标题含 <字符> & 标点\n\n完整正文　保留空格\nhttps://example.test/a?x=1&y=2';
 await copyLiteralText(text,{defaultView:{navigator:{clipboard:{writeText:async value=>copied.push(value)}}}});
 assert.deepEqual(copied,[text]);
});

function compatibility({modern=false,allowed=true}={}){
 const events=[],range={cloneRange:()=>range},selection={rangeCount:1,getRangeAt:()=>range,removeAllRanges:()=>events.push('clear-selection'),addRange:r=>{assert.equal(r,range);events.push('restore-selection')}};
 const input={style:{},setAttribute:()=>{},focus:()=>events.push('focus-input'),select:()=>events.push('select-all'),remove:()=>events.push('remove-input')};
 const document={defaultView:{navigator:{...(modern?{clipboard:{writeText:async()=>{events.push('modern-denied');throw Error('permission')}}}:{})}},activeElement:{focus:options=>{assert.equal(options.preventScroll,true);events.push('restore-focus')}},getSelection:()=>selection,createElement:()=>input,body:{append:value=>{assert.equal(value,input);events.push('append-input')}},execCommand:command=>{assert.equal(command,'copy');events.push('compat-copy');return allowed}};
 return {document,input,events};
}

test('WebView compatibility path preserves full text, focus and previous selection',async()=>{
 const f=compatibility(),text='正文\n第二段\n';await copyLiteralText(text,f.document);
 assert.equal(f.input.value,text);assert.equal(f.input.readOnly,true);
 assert.deepEqual(f.events,['append-input','focus-input','select-all','compat-copy','remove-input','restore-focus','clear-selection','restore-selection']);
});

test('modern permission rejection can fall back, but a failed write never reports success',async()=>{
 const f=compatibility({modern:true});await copyLiteralText('fallback',f.document);assert.equal(f.events[0],'modern-denied');assert.ok(f.events.includes('compat-copy'));
 const failed=compatibility({modern:true,allowed:false});await assert.rejects(copyLiteralText('not copied',failed.document),/clipboard_unavailable/);
 assert.ok(failed.events.includes('remove-input')&&failed.events.includes('restore-focus'));
});
