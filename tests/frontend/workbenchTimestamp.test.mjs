import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {test} from 'node:test';

const loader=new URL('./helpers/modules.mjs',import.meta.url).href;
function inZone(zone,body){
 const script=`import {moduleLoader} from ${JSON.stringify(loader)};
 const fields=moduleLoader({imports:{'./common':{Field:()=>null}}})('workbench/ui/TimestampField.tsx');
 const {timestampToLocalMinute:show,localMinuteToTimestamp:save,TimestampField}=fields;
 ${body}`;
 return JSON.parse(execFileSync(process.execPath,['--input-type=module','-e',script],{env:{...process.env,TZ:zone},encoding:'utf8'}));
}

test('timestamp fields display and save in the actual device timezone across calendar days',()=>{
 assert.deepEqual(inZone('Asia/Shanghai',`console.log(JSON.stringify({display:show('2026-11-01T20:30:40.987Z'),save:save('2026-11-02T13:20')}));`),{
  display:'2026-11-02T04:30',save:'2026-11-02T05:20:00.000Z',
 });
 assert.deepEqual(inZone('America/New_York',`console.log(JSON.stringify({display:show('2026-11-01T00:30:00+08:00'),save:save('2026-11-02T13:20')}));`),{
  display:'2026-10-31T12:30',save:'2026-11-02T18:20:00.000Z',
 });
});

test('empty timestamps remain empty while ambiguous historical text is never interpreted',()=>{
 const result=inZone('Asia/Shanghai',`console.log(JSON.stringify({empty:show(null),saveEmpty:save(''),naive:show('2026-11-01T13:20'),bad:show('not a date'),impossible:show('2026-02-30T12:00:00Z'),compactOffset:show('2026-11-01T13:20:45+0800')}));`);
 assert.deepEqual(result,{empty:'',saveEmpty:'',naive:'',bad:'',impossible:'',compactOffset:'2026-11-01T13:20'});
});

test('invalid local dates and DST gaps cannot silently change the selected instant',()=>{
 assert.deepEqual(inZone('America/New_York',`console.log(JSON.stringify([save('2026-03-08T02:30'),save('2026-02-30T12:00'),save('2026-11-01T25:00'),save('0000-01-01T00:00'),save('not a date')]));`),[null,null,null,null,null]);
});

test('mount and unchanged native selections preserve the original ISO, seconds, offset and later DST instant',()=>{
 const result=inZone('America/New_York',`
 const original='2026-11-01T01:30:45.678-05:00',changes=[];
 const view=TimestampField({label:'发布时间',value:original,onChange:value=>changes.push(value)});
 const input=view.props.children.find(child=>child?.type==='input');
 input.props.onChange({currentTarget:{value:input.props.value,validity:{badInput:false},setCustomValidity(){},reportValidity(){}}});
 console.log(JSON.stringify({label:view.props.label,type:input.props.type,step:input.props.step,shown:input.props.value,changes,original}));`);
 assert.deepEqual(result,{label:'发布时间',type:'datetime-local',step:60,shown:'2026-11-01T01:30',changes:[],original:'2026-11-01T01:30:45.678-05:00'});
});

test('only completed edits change the payload; clearing and invalid partial input keep their distinct meanings',()=>{
 const result=inZone('Asia/Shanghai',`
 const changes=[],errors=[];let reported=0;
 const view=TimestampField({label:'观察时间',value:'2026-11-01T05:06:07.123Z',onChange:value=>changes.push(value)});
 const input=view.props.children.find(child=>child?.type==='input');
 const change=(value,badInput=false)=>input.props.onChange({currentTarget:{value,validity:{badInput},setCustomValidity:message=>errors.push(message),reportValidity(){reported++;}}});
 change('',true);change('2026-11-02T13:20');change('');change('2026-02-30T12:00');change(input.props.value);
 console.log(JSON.stringify({changes,errors,reported}));`);
 assert.deepEqual(result.changes,['2026-11-02T05:20:00.000Z','']);
 assert.equal(result.reported,1);assert.ok(result.errors.includes('这个本地时间无效，请重新选择。'));assert.equal(result.errors.at(-1),'');
});

test('unparseable history remains visible and untouched until the user chooses a replacement',()=>{
 const result=inZone('Asia/Shanghai',`
 const changes=[],original='2026-11-01T13:20';
 const view=TimestampField({label:'发布时间',value:original,onChange:value=>changes.push(value)});
 const [input,note]=view.props.children;
 console.log(JSON.stringify({value:input.props.value,note:note.props.children.at(-1),changes}));`);
 assert.deepEqual(result,{value:'',note:'2026-11-01T13:20',changes:[]});
});
