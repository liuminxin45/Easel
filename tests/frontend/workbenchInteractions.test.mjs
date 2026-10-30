import assert from 'node:assert/strict';
import {test} from 'node:test';
import {inspectInteractions,auditInteractions} from '../../scripts/audit_workbench_interactions.mjs';
import {moduleLoader} from './helpers/modules.mjs';
const jsx={jsx:(type,props)=>({type,props:props||{}}),jsxs:(type,props)=>({type,props:props||{}})};
const load=moduleLoader({imports:{'react/jsx-runtime':jsx}}),{interactionFeedback,refreshViews}=load('lib/interaction.ts'),{InteractionNotice}=load('components/InteractionNotice.tsx');

test('normal submission and receipt recovery are neutral, while definite errors remain alerts',()=>{
 for(const source of [{busy:true},{refreshing:true},{feedback:interactionFeedback({uncertain:true,message:'internal receipt detail'})},{feedback:interactionFeedback({unreachable:true})}]){
  const tree=InteractionNotice({sources:[source]});assert.equal(tree.props.role,'status');assert.notEqual(tree.props.className,'notice-error');
 }
 const error=InteractionNotice({sources:[{feedback:interactionFeedback(new Error('模型字段不能为空'))}]});assert.equal(error.props.role,'alert');assert.equal(error.props.children,'模型字段不能为空');
 assert.equal(InteractionNotice({sources:[{}]}),null);assert.equal(interactionFeedback({cancelled:true}),undefined);
});

test('read failure status wins over the same legacy error string and preserves the underlying message',()=>{
 const source={error:'暂时无法连接服务器。',feedback:interactionFeedback({unreachable:true})},tree=InteractionNotice({sources:[source]});assert.equal(tree.props.role,'status');
 const failure=InteractionNotice({sources:[source,{error:'输入格式无效'}]});assert.equal(failure.props.role,'alert');assert.equal(failure.props.children,'输入格式无效');
});

test('background view refresh never holds the command or leaks a rejection',async()=>{
 let entered=false,release;const waiting=new Promise(resolve=>release=resolve);const result=refreshViews(async()=>{entered=true;return waiting},async()=>{throw Error('TEMP read failure')});
 assert.equal(result,undefined);assert.equal(entered,false);await Promise.resolve();assert.equal(entered,true);release();await Promise.resolve();
});

test('the complete private view surface follows the shared interaction contract',()=>{
 const report=auditInteractions();assert.deepEqual(report.violations,[]);assert.ok(report.files>=26);assert.ok(report.counts.buttons>=45);assert.ok(report.counts.notices>=35);assert.equal(report.counts.backgroundRefreshes,2);
});

test('the audit rejects old patterns and accepts shared feedback and background refresh',()=>{
 for(const [source,rule] of [
  ['async function save(){await r.reload()}','view-refresh-blocks-action'],
  ['const x=<Notice message={action.error}/>','typed-feedback-required'],
  ['const x=<button disabled={action.busy} onClick={()=>action.run(save)}>保存</button>','shared-action-button-required'],
  ['const x=<p className="notice-error">等待</p>','error-presentation-must-be-shared'],
  ['const x=<button>核对原请求</button>','manual-receipt-step-retired'],
 ])assert.ok(inspectInteractions(source).violations.some(v=>v.rule===rule),rule);
 assert.equal(inspectInteractions('const x=<ActionButton action={action}>保存</ActionButton>;const y=<Notice sources={[action]}/>;refreshViews(()=>r.reload())').violations.length,0);
});

test('read-only POST queries retry as reads and retain CSRF without becoming uncertain writes',async()=>{
 let calls=0;const {ApiTransport}=load('workbench/core/transport.ts');const transport=new ApiTransport({retryDelay:0,fetcher:async(path,options)=>{calls++;assert.equal(options.method,'POST');assert.equal(options.headers['X-CSRF-Token'],'owner');if(calls===1)throw new TypeError('TEMP offline');return new Response('{"preview":true}') }});
 const result=await transport.query('/api/studio/context',{work_id:'work'},'owner');assert.equal(result.preview,true);assert.equal(calls,2);
});
