import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {moduleLoader} from './helpers/modules.mjs';
const {DownloadManager}=moduleLoader()('lib/download.ts');
function fixture(fetcher,options={}){
 const saves=[],calls=[];
 const manager=new DownloadManager({origin:()=> 'https://native.test',fetcher:async(...args)=>{calls.push(args);return fetcher(...args)},save:(blob,name)=>saves.push({blob,name}),...options});
 return {manager,saves,calls};
}
test('every media type transfers authenticated bytes before saving, with no native cookie dependency',async()=>{
 for(const type of ['image/png','text/plain','text/html','application/zip','application/pdf','audio/mpeg','video/mp4']){
  const f=fixture(()=>new Response('exact bytes',{headers:{'content-type':type}}));
  await f.manager.download('/api/media/path/file','原件');
  assert.equal(await f.saves[0].blob.text(),'exact bytes');assert.equal(f.saves[0].blob.type,type);
  assert.equal(f.calls[0][1].credentials,'same-origin');assert.equal(f.calls[0][1].redirect,'error');
 }
});
test('expired signed image URLs are read with the current owner session',async()=>{
 const f=fixture(()=>new Response('image'));
 await f.manager.download('/media/images/exact-id/old.png?signature=expired','old.png');
 assert.equal(f.calls[0][0],'https://native.test/api/files/exact-id?download=1');
});
test('partial files and version packages retain exact endpoint identities',async()=>{
 for(const url of ['/api/chat/products/turn/files/'+'a'.repeat(64)+'?download=1','/api/works/work/versions/version/download']){
  const f=fixture(()=>new Response('data'));await f.manager.download(url,'file');assert.equal(f.calls[0][0],'https://native.test'+url);
 }
});
test('unsafe and cross-origin links never send requests or save data',async()=>{
 const f=fixture(()=>new Response('data'));
 for(const url of ['https://evil.test/api/file','//evil.test/api/file','javascript:alert(1)','data:text/plain,secret','/private','https://a:b@native.test/api/file','/api/\\evil'])await assert.rejects(f.manager.download(url,'file'));
 assert.equal(f.calls.length,0);assert.equal(f.saves.length,0);
});
test('HTTP errors, missing streams, transport failures and size limits never save error pages',async()=>{
 for(const code of [401,403,404,410,500]){
  const f=fixture(()=>new Response('error',{status:code}));await assert.rejects(f.manager.download('/api/files/id','file'));assert.equal(f.saves.length,0);
 }
 for(const response of [()=>new Response('large',{headers:{'content-length':'100'}}),()=>new Response('large'),()=>new Response(null),()=>{throw Error('offline')}]){
  const f=fixture(response,{limit:2});await assert.rejects(f.manager.download('/api/files/id','file'));assert.equal(f.saves.length,0);
 }
});
test('rapid clicks coalesce transfer and saving; failed attempts allow explicit retry',async()=>{
 let complete;
 const f=fixture(()=>new Promise(resolve=>complete=resolve));
 const a=f.manager.download('/api/files/id','file'),b=f.manager.download('/api/files/id','file');assert.equal(a,b);
 complete(new Response('bytes'));await Promise.all([a,b]);assert.equal(f.calls.length,1);assert.equal(f.saves.length,1);
 let fail=true;const retry=fixture(()=>{if(fail)throw Error('offline');return new Response('bytes')});
 await assert.rejects(retry.manager.download('/api/files/id','file'));fail=false;await retry.manager.download('/api/files/id','file');assert.equal(retry.saves.length,1);
});
test('native saver gets only a local Blob URL, cleaned up after the handoff even if click throws',async()=>{
 for(const throws of [false,true]){
  const events=[],timers=[];let link;
  const api=moduleLoader({globals:{location:{origin:'https://native.test'},URL:class extends URL{static createObjectURL(){events.push('create');return 'blob:local'}static revokeObjectURL(url){events.push('revoke:'+url)}},document:{createElement:()=>link={click(){events.push('click');if(throws)throw Error('save failed')},remove(){events.push('remove')}},body:{appendChild(){events.push('append')}}},setTimeout:fn=>timers.push(fn)}})('lib/download.ts');
  const manager=new api.DownloadManager({fetcher:async()=>new Response('bytes')});
  if(throws)await assert.rejects(manager.download('/api/files/id','原图.png'));else await manager.download('/api/files/id','原图.png');
  assert.equal(link.href,'blob:local');assert.equal(link.download,'原图.png');assert.deepEqual(events,['create','append','click','remove']);timers[0]();assert.equal(events.at(-1),'revoke:blob:local');
 }
});
test('all explicit download surfaces call the shared layer, with no private anchor creation',()=>{
 const root=new URL('../../web/frontend/src/',import.meta.url);
 for(const file of ['components/ArtifactGallery.tsx','components/OutputsPage.tsx','workbench/ui/ImagePreview.tsx','workbench/ui/common.tsx']){
  const source=readFileSync(new URL(file,root),'utf8');assert.match(source,/<DownloadLink/);assert.doesNotMatch(source,/<a\s[^>]*\bdownload(?:=|[\s>])/);
 }
 const manual=readFileSync(new URL('components/ManualPublishPage.tsx',root),'utf8');assert.match(manual,/await downloads.download/);assert.doesNotMatch(manual,/createElement\('a'\)/);
});

test('workbench resolver hands off a signed HTTP URL without requiring Blob support',async()=>{
 let link,seen;const events=[];
 const api=moduleLoader({globals:{location:{origin:'https://native.test'},document:{createElement:()=>link={click:()=>events.push('click'),remove:()=>events.push('remove')},body:{appendChild:()=>events.push('append')}}}})('lib/download.ts');
 const unbind=api.bindDownloadResolver(async(url,name)=>{seen={url,name};return '/media/downloads?signature=exact'});
 await new api.DownloadManager({fetcher:()=>{throw Error('Must not read a Blob in native mode')}}).download('/api/media/path/file.zip','稿件.zip');
 assert.equal(link.href,'https://native.test/media/downloads?signature=exact');assert.equal(seen.name,'稿件.zip');assert.deepEqual(events,['append','click','remove']);
 unbind();
 const release=api.bindDownloadResolver(async()=> 'https://evil.test/media/downloads');
 await assert.rejects(new api.DownloadManager().download('/api/files/id','file'));
 release();
});
