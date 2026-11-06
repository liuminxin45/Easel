import {test} from 'node:test';
import assert from 'node:assert/strict';
import {moduleLoader} from './helpers/modules.mjs';
const load=moduleLoader(),native=load('lib/store.ts').generateSessionTitle,title=load('workbench/ui/lib/sessionTitle.ts').generateSessionTitle;
test('ordinary messages keep the exact native title',()=>{
 for(const input of ['请修复移动端侧边栏无法收起的问题','分析项目功能 https://github.com/a/b','', '这个'])assert.equal(title(input),native(input));
});
test('pure URLs have deterministic private fallbacks without network or secret parameters',()=>{
 assert.equal(title('https://github.com/liuminxin45/ai-engineering-radar'),'liuminxin45/ai-engineering-radar');
 assert.equal(title('https://mp.weixin.qq.com/s/opaque'),'微信公众号文章');
 assert.equal(title('https://user:password@example.com/story?token=SECRET#secret'),'example.com · story');
 assert.equal(title('https://example.com/abcdefghijklmnopqrstuvwxyz'),'example.com');
 assert.equal(title('<https://github.com/a/b>'),'a/b');
 assert.equal(title('https://example.com/%ZZ'),'新对话');
 assert.equal(title('https://example.com/\nhttps://another.test/'),'example.com');
});
