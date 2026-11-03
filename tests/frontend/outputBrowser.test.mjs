import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';
const {OutputsBrowser}=moduleLoader()('lib/outputBrowser.ts');
const node=(path,type='dir')=>({path,type,name:path.split('/').at(-1),...(type==='file'?{kind:'image'}:{})});
const page=(items,next_cursor=null,revision='r1',extra={})=>({items,next_cursor,revision,...extra});
const held=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}};
const paths=browser=>Array.from(browser.snapshot().items,row=>row.path);

test('bounded library reads participate in the existing output invalidation and native snapshot policy',()=>{
 const cache=moduleLoader()('workbench/core/resource-cache.ts');
 for(const path of ['/api/library/items?limit=50','/api/library/resolve?path=project']){assert.equal(cache.nativeResourceCacheable(path),true);assert.deepEqual(Array.from(cache.resourceTags(path)),['outputs','works','library']);}
 const changed=cache.mutationTags('/api/chat',{},{});assert.ok(changed.includes('outputs'));assert.ok(cache.resourceTags('/api/library/items').some(tag=>changed.includes(tag)));
});

test('root listing reads one summary page and does not resolve or descend into unvisited directories',async()=>{
 const calls=[],browser=new OutputsBrowser({list:async input=>{calls.push(input);return page([node('work-a'),node('work-b')],'next')},resolve:()=>assert.fail('Root listing must not resolve children')});
 await browser.select({});assert.equal(calls.length,1);assert.equal(calls[0].parent,undefined);assert.deepEqual(paths(browser),['work-a','work-b']);assert.equal(browser.snapshot().next_cursor,'next');
});

test('opening a directory lists only its immediate children and replaces parent summary with exact full metadata',async()=>{
 const full={...node('work-a'),meta:{title:'Exact project',deliverablePaths:['work-a/version/final.png']}};
 const calls=[],browser=new OutputsBrowser({list:async input=>{calls.push(input);return input.parent?page([node('work-a/version')],null,'r1',{parent:full}):page([node('work-a')])},resolve:()=>assert.fail('Already visited parent should not need path resolution')});
 await browser.select({});await browser.select({parent:'work-a'},['work-a']);assert.deepEqual(paths(browser),['work-a/version']);assert.equal(calls.length,2);assert.equal(calls[1].parent,'work-a');
 assert.deepEqual(Array.from(browser.directoryNodes(['work-a'])[0].meta.deliverablePaths),['work-a/version/final.png']);
});

test('pagination merges by declared path, deduplicates overlaps and coalesces rapid load-more clicks',async()=>{
 const second=held();let reads=0;const browser=new OutputsBrowser({list:input=>{reads++;return input.cursor?second.promise:Promise.resolve(page([node('a'),node('b')],'cursor'))},resolve:()=>assert.fail('No resolve')});
 await browser.select({});const first=browser.more(),same=browser.more();assert.equal(first,same);assert.equal(reads,2);
 second.resolve(page([node('b'),node('c')]));await first;assert.deepEqual(paths(browser),['a','b','c']);assert.equal(browser.snapshot().next_cursor,null);
});

test('late data from a prior directory and old search cannot replace the active selection',async()=>{
 const a=held(),b=held(),browser=new OutputsBrowser({list:input=>input.query==='old'?a.promise:b.promise,resolve:async()=>({nodes:[]})});
 const old=browser.select({query:'old'}),current=browser.select({query:'new'});b.resolve(page([node('new')]));await current;a.resolve(page([node('old')]));await old;assert.deepEqual(paths(browser),['new']);
});

test('a late pagination page cannot append to a newly selected directory',async()=>{
 const more=held(),browser=new OutputsBrowser({list:input=>input.parent?Promise.resolve(page([node('folder/current')])):input.cursor?more.promise:Promise.resolve(page([node('folder')],'next')),resolve:async()=>({nodes:[node('folder')]})});
 await browser.select({});const old=browser.more();await browser.select({parent:'folder'},['folder']);more.resolve(page([node('old-root-extra')]));await old;assert.deepEqual(paths(browser),['folder/current']);
});

test('returning to an already paginated folder retains its loaded rows and cursor',async()=>{
 const browser=new OutputsBrowser({list:async input=>input.parent?page([node('a/file','file')]):input.cursor?page([node('b')],'last'):page([node('a')],'next'),resolve:async()=>({nodes:[node('a')]})});
 await browser.select({});await browser.more();await browser.select({parent:'a'},['a']);await browser.select({});assert.deepEqual(paths(browser),['a','b']);assert.equal(browser.snapshot().next_cursor,'last');
});

test('a stale cursor restarts the first page with the new revision instead of appending incompatible rows',async()=>{
 let root=0;const calls=[],browser=new OutputsBrowser({list:async input=>{calls.push(input);if(input.cursor)throw Object.assign(Error('library_cursor_stale'),{status:409});root++;return root===1?page([node('old')],'stale','r1'):page([node('new')],null,'r2')},resolve:async()=>({nodes:[]})});
 await browser.select({});await browser.more();assert.deepEqual(paths(browser),['new']);assert.equal(browser.snapshot().revision,'r2');assert.equal(calls.length,3);assert.equal(calls[2].force,true);
});

test('a revision restart restores only the prior visible page count, without deadlocking the original more request',async()=>{
 let revision='r1';const browser=new OutputsBrowser({list:async input=>input.cursor?(revision==='r1'?page([node('b')],'last','r1'):input.cursor==='next'?page([node('new-b')],null,'r2'):Promise.reject(Object.assign(Error('library_cursor_stale'),{status:409}))):page([node(revision==='r1'?'a':'new-a')],'next',revision),resolve:async()=>({nodes:[]})});
 await browser.select({});await browser.more();assert.equal(browser.snapshot().items.length,2);revision='r2';await browser.more();assert.deepEqual(paths(browser),['new-a','new-b']);
});

test('cancelled ownership cannot publish a late page, and cold indexing remains explicitly incomplete',async()=>{
 const deferred=held(),browser=new OutputsBrowser({list:()=>deferred.promise,resolve:async()=>({nodes:[]})});const pending=browser.select({});browser.cancel();deferred.resolve(page([node('late')]));await pending;assert.deepEqual(paths(browser),[]);
 const indexing=new OutputsBrowser({list:async()=>page([],null,'building',{indexing:true}),resolve:async()=>({nodes:[]})});await indexing.select({});assert.equal(indexing.snapshot().indexing,true);assert.equal(indexing.snapshot().error,'');
});

test('metadata retention is bounded to cached pages, current ancestors and the last resolved chain',async()=>{
 const browser=new OutputsBrowser({list:async input=>page(Array.from({length:50},(_,i)=>node(input.parent+'/file-'+i,'file')),null,'r1',{parent:node(input.parent)}),resolve:async path=>({nodes:[node(path)]})});
 for(let i=0;i<100;i++)await browser.select({parent:'folder-'+i},['folder-'+i]);assert.equal(browser.cacheSizes().pages,32);assert.ok(browser.cacheSizes().nodes<=32*51+1);assert.equal(browser.directoryNodes(['folder-0']).length,0);assert.equal(browser.directoryNodes(['folder-99']).length,1);
});

test('the centralized host port uses bounded routes and separates caches across authentication epochs',async()=>{
 const {libraryDataSource}=moduleLoader()('workbench/core/library.ts'),reads=[],client={authenticationEpoch:1,read:async(path,force)=>{reads.push({path,force});return page([])},peek:()=>undefined};
 const source=libraryDataSource(client);await source.list({parent:'exact/version',cursor:'opaque',query:'主题',kind:'image',force:true});const url=new URL(reads[0].path,'https://example.test');
 assert.equal(url.pathname,'/api/library/items');assert.equal(url.searchParams.get('limit'),'50');assert.equal(url.searchParams.get('parent'),'exact/version');assert.equal(url.searchParams.get('query'),'主题');assert.equal(reads[0].force,true);
 assert.equal(libraryDataSource(client),source);client.authenticationEpoch=2;assert.notEqual(libraryDataSource(client),source);
});
