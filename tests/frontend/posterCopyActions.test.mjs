import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';
const jsx={jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})};
const {posterCopyParts}=moduleLoader({imports:{react:{useState:()=>[null,()=>{}]},'react/jsx-runtime':jsx,'../../components/InteractionNotice':{StatusCard:()=>null}}})('workbench/ui/PosterCopyActions.tsx');
const file={name:'标题与配文.txt',path:'__workbench__/artifact-123/标题与配文.txt'};
test('registered caption preserves content and removes just the format separator',()=>{
 assert.deepEqual({...posterCopyParts(file,'标题\r\n\r\n正文第一段\r\n\r\n第二段  ')},{title:'标题',body:'正文第一段\r\n\r\n第二段  '});
 assert.deepEqual({...posterCopyParts(file,'标题\n正文')},{title:'标题',body:'正文'});
});
test('invalid and unrelated text never receives poster copy actions',()=>{
 for(const text of ['','标题','标题\n','\n正文','标题\n\n'])assert.equal(posterCopyParts(file,text),null);
 assert.equal(posterCopyParts({...file,path:'other/标题与配文.txt'},'标题\n正文'),null);
 assert.equal(posterCopyParts({...file,name:'其他.txt'},'标题\n正文'),null);
});
