import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';

function fixture(hidden=false){
 let now=0,id=0;const timers=new Map(),listeners=new Set(),document={hidden,addEventListener:(_,fn)=>listeners.add(fn),removeEventListener:(_,fn)=>listeners.delete(fn)};
 const load=moduleLoader({globals:{document,setTimeout:(fn,ms)=>{timers.set(++id,{fn,at:now+ms});return id},clearTimeout:id=>timers.delete(id)}});
 const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve()};
 const advance=async(ms)=>{const end=now+ms;await flush();for(let n=0;n<100;n++){const next=[...timers].sort((a,b)=>a[1].at-b[1].at)[0];if(!next||next[1].at>end)break;now=next[1].at;timers.delete(next[0]);next[1].fn();await flush()}now=end;await flush()};
 return {visiblePoll:load('lib/visiblePoll.ts').visiblePoll,document,timers,listeners,advance,flush,visible(value){document.hidden=!value;for(const fn of [...listeners])fn()}};
}

test('a hidden login/job subscription stays idle and foreground reads only the original task',async()=>{
 const f=fixture(true),reads=[];const poll=f.visiblePoll(async()=>{reads.push('GET original-job')},{interval:1000});
 await f.advance(10000);assert.equal(reads.length,0);assert.equal(f.timers.size,0);
 f.visible(true);await f.flush();assert.deepEqual(reads,['GET original-job']);
 f.visible(false);await f.advance(10000);assert.equal(reads.length,1);
 f.visible(true);await f.flush();assert.equal(reads.length,2);
 poll.stop();await poll.done;assert.equal(f.listeners.size,0);assert.equal(f.timers.size,0);
});

test('slow status reads never overlap even after repeated foreground events',async()=>{
 const f=fixture();let complete,reads=0;
 const poll=f.visiblePoll(()=>{reads++;return new Promise(resolve=>{complete=resolve})},{interval:1500});
 await f.advance(1500);assert.equal(reads,1);
 await f.advance(60000);f.visible(true);f.visible(true);poll.refresh();await f.flush();assert.equal(reads,1);
 complete(true);await f.flush();await f.advance(1499);assert.equal(reads,1);
 await f.advance(1);assert.equal(reads,2);complete(false);await f.flush();await poll.done;
 assert.equal(f.listeners.size,0);assert.equal(f.timers.size,0);
});

test('read failures back off, terminate explicitly, and do not restart actions',async()=>{
 const f=fixture(),failures=[];let reads=0;
 const poll=f.visiblePoll(async()=>{reads++;throw Error('offline')},{interval:1000,maxDelay:5000,onError:(_,n)=>{failures.push(n);return n<3}});
 await f.advance(1000);assert.equal(reads,1);
 await f.advance(1999);assert.equal(reads,1);await f.advance(1);assert.equal(reads,2);
 await f.advance(3999);assert.equal(reads,2);await f.advance(1);await poll.done;
 assert.equal(reads,3);assert.deepEqual(failures,[1,2,3]);assert.equal(f.listeners.size,0);
});

test('closing while a read is in flight settles subscription without another timer',async()=>{
 const f=fixture();let complete,reads=0;
 const poll=f.visiblePoll(()=>{reads++;return new Promise(resolve=>{complete=resolve})},{interval:1000});
 await f.advance(1000);poll.stop();await poll.done;complete(true);await f.flush();
 f.visible(true);await f.advance(10000);assert.equal(reads,1);assert.equal(f.timers.size,0);assert.equal(f.listeners.size,0);
});
