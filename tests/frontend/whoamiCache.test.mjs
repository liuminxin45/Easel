import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/lib/whoami.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
});
const settle = () => new Promise(resolve => setImmediate(resolve));
const storageFor=map=>({getItem:key=>map.get(key)??null,setItem:(key,value)=>map.set(key,value),removeItem:key=>map.delete(key)});

function setup() {
  const entries = new Map();
  const pending = [];
  const exports = {};
  runInNewContext(outputText, {
    exports, Date,
    require: () => ({
      accountWhoami: platform => new Promise(resolve => pending.push({ platform, resolve })),
    }),
    localStorage: {
      getItem: key => entries.get(key) ?? null,
      setItem: (key, value) => entries.set(key, String(value)),
    },
  });
  return { exports, pending, entries };
}

test('a host can disable automatic account verification without requests, callbacks or cached observations',async()=>{
 const view=setup(),entries=new Map(),updates=[];
 const release=view.exports.bindWhoamiStorage(storageFor(entries),{automaticVerification:false});
 try{
  view.exports.verifyStale(['xiaohongshu','wechat-oa'],{onUpdate:(...args)=>updates.push(args)});
  await settle();
  assert.equal(view.pending.length,0);
  assert.equal(updates.length,0);
  assert.equal(entries.size,0);
  assert.equal(view.entries.size,0);
 }finally{release()}
});

test('a host retains the official automatic verification default when no policy is provided',async()=>{
 const view=setup(),entries=new Map();
 const release=view.exports.bindWhoamiStorage(storageFor(entries));
 try{
  view.exports.verifyStale(['xiaohongshu']);
  assert.equal(view.pending.length,1);
  view.pending[0].resolve({loggedIn:true,name:'Official default',avatar:''});
  await settle();
  assert.equal(JSON.parse(entries.get('easel_whoami_v4')).xiaohongshu.name,'Official default');
 }finally{release()}
});

test('explicit force verification remains available when the host disables automatic checks',async()=>{
 const view=setup(),entries=new Map(),updates=[];
 const release=view.exports.bindWhoamiStorage(storageFor(entries),{automaticVerification:false});
 try{
  view.exports.verifyStale(['wechat-oa'],{force:true,onUpdate:(...args)=>updates.push(args)});
  assert.equal(view.pending.length,1);
  view.pending[0].resolve({loggedIn:true,name:'Explicit check',avatar:''});
  await settle();
  assert.equal(JSON.parse(entries.get('easel_whoami_v4'))['wechat-oa'].name,'Explicit check');
  assert.equal(updates.length,1);
  assert.equal(view.entries.size,0,'explicit host observations must remain in its ephemeral cache');
 }finally{release()}
});

test('releasing an old binding cannot re-enable automatic verification on a newer binding',()=>{
 const view=setup(),storage=storageFor(new Map());
 const releaseOld=view.exports.bindWhoamiStorage(storage);
 const releaseCurrent=view.exports.bindWhoamiStorage(storage,{automaticVerification:false});
 releaseOld();view.exports.verifyStale(['wechat-oa']);assert.equal(view.pending.length,0);
 releaseCurrent();view.exports.verifyStale(['wechat-oa']);assert.equal(view.pending.length,1);
});

test('verification from an old host cannot populate the next authentication cache',async()=>{
 const view=setup(),first=new Map(),second=new Map();
 const store=map=>({getItem:key=>map.get(key)??null,setItem:(key,value)=>map.set(key,value),removeItem:key=>map.delete(key)});
 const release=view.exports.bindWhoamiStorage(store(first));
 view.exports.verifyStale(['xiaohongshu']);
 release();const releaseNext=view.exports.bindWhoamiStorage(store(second));
 view.pending[0].resolve({loggedIn:true,name:'old account',avatar:''});
 await settle();assert.equal(second.size,0);assert.equal(first.size,0);releaseNext();
});

test('legacy and previously incorrect account identity caches are ignored', () => {
  const view = setup();
  view.entries.set('easel_whoami', JSON.stringify({
    xiaohongshu: { loggedIn: true, name: 'Wrong feed author', avatar: '', ts: Date.now() },
  }));
  view.entries.set('easel_whoami_v2', view.entries.get('easel_whoami'));
  view.entries.set('easel_whoami_v3', view.entries.get('easel_whoami'));
  assert.equal(view.exports.getWhoamiCache().xiaohongshu, undefined);
  view.exports.setWhoamiCache('xiaohongshu', { loggedIn: true, name: 'Me', avatar: '' });
  assert.equal(JSON.parse(view.entries.get('easel_whoami_v4')).xiaohongshu.name, 'Me');
});
test('a verification started before login cannot overwrite the new login cache', async () => {
  const view = setup();
  const updates = [];
  view.exports.verifyStale(['xiaohongshu'], { onUpdate: (...args) => updates.push(args) });
  view.exports.setWhoamiCache('xiaohongshu', { loggedIn: true, name: '已登录', avatar: '' });
  view.pending[0].resolve({ loggedIn: false, name: '', avatar: '' });
  await settle();
  assert.equal(view.exports.getWhoamiCache().xiaohongshu.loggedIn, true);
  assert.equal(updates.length, 0);
});

test('invalidating login cache discards a previously running background verification', async () => {
  const view = setup();
  const updates = [];
  view.exports.verifyStale(['xiaohongshu'], { onUpdate: (...args) => updates.push(args) });
  view.exports.setWhoamiCache('xiaohongshu', null);
  view.pending[0].resolve({ loggedIn: false, name: '', avatar: '' });
  await settle();
  assert.equal(view.exports.getWhoamiCache().xiaohongshu, undefined);
  assert.equal(updates.length, 0);
});

test('fresh verification still updates and caches the actual account result', async () => {
  const view = setup();
  const updates = [];
  view.exports.verifyStale(['xiaohongshu'], { onUpdate: (...args) => updates.push(args) });
  view.pending[0].resolve({ loggedIn: true, name: '账号', avatar: '' });
  await settle();
  assert.equal(view.exports.getWhoamiCache().xiaohongshu.loggedIn, true);
  assert.equal(updates.length, 1);
});

test('incomplete account identity is refreshed after one minute instead of ten', () => {
  const view = setup();
  view.entries.set('easel_whoami_v4', JSON.stringify({
    xiaohongshu: { loggedIn: true, name: '', avatar: '', ts: Date.now() - 61_000 },
    zhihu: { loggedIn: true, name: 'Me', avatar: 'https://self.test/avatar', ts: Date.now() - 61_000 },
  }));
  view.exports.verifyStale(['xiaohongshu', 'zhihu']);
  assert.equal(view.pending.length, 1);
  assert.equal(view.pending[0].platform, 'xiaohongshu');
});
