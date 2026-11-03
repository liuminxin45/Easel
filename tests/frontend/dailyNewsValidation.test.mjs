import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';

const {parseTrends}=moduleLoader()('lib/trendValidation.ts');
const plain=value=>JSON.parse(JSON.stringify(value));
const items=Array.from({length:1100},(_,i)=>({id:'article-'+i,title:'当天条目 '+i,url:'https://example.test/'+i}));
const response={version:1,trends:[{platform:'source',label:'Source',ok:true,status:'fresh',stale:false,items}],updated:1,warnings:[]};

test('private daily results retain their date and do not truncate the list to official thirty',()=>{
 const value=plain(parseTrends({...response,day:'2026-11-03',timezone:'Asia/Shanghai'}));
 assert.equal(value.day,'2026-11-03');assert.equal(value.timezone,'Asia/Shanghai');
 assert.equal(value.trends[0].items.length,1000);
 assert.equal(value.trends[0].items[34].id,'article-34');
});

test('official responses retain their default shape and thirty-item bound',()=>{
 const value=plain(parseTrends(response));
 assert.equal(value.trends[0].items.length,30);
 assert.ok(!Object.hasOwn(value,'day'));assert.ok(!Object.hasOwn(value,'timezone'));
});

test('empty daily results remain an empty list without generated placeholder or warning',()=>{
 const value=plain(parseTrends({...response,day:'2026-11-03',timezone:'Asia/Shanghai',trends:[]}));
 assert.deepEqual(value.trends,[]);assert.deepEqual(value.warnings,[]);
});
