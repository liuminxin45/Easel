import {string,type JsonRecord} from './models';
export {reviewChannelOptions,reviewChannelLabel,type ReviewChannelOption} from './review-channels';
export const metricFields=[['views','阅读 / 浏览'],['likes','点赞'],['comments','评论'],['saves','收藏'],['shares','分享'],['impressions','曝光'],['clicks','点击'],['follows','新增关注']] as const;
export type MetricKey=typeof metricFields[number][0];
export type MetricValues=Record<MetricKey,number|null>;
export type MetricWindow='24h'|'7d'|'custom';
export interface MetricRow {observed_at:string;window:MetricWindow;values:MetricValues}
export interface DateTimeInput {day:string;time:string}
/** Wall-clock inputs in this workbench are China time, independent of host TZ. */
export function isoTime(value:DateTimeInput|undefined|null):string|null{
  if(!/^\d{4}-\d{2}-\d{2}$/.test(value?.day??'')||!/^([01]\d|2[0-3]):[0-5]\d$/.test(value?.time??''))return null;
  const source=value!.day+'T'+value!.time,ms=Date.parse(source+':00+08:00');if(!Number.isFinite(ms))return null;
  if(new Date(ms+8*3600000).toISOString().slice(0,16)!==source)return null;return new Date(ms).toISOString();
}
export function dateParts(value:unknown):DateTimeInput{
  const input=string(value);if(!input||Number.isNaN(Date.parse(input)))return {day:'',time:''};
  const stamp=new Date(Date.parse(input)+8*3600000).toISOString();return {day:stamp.slice(0,10),time:stamp.slice(11,16)};
}
export function parseMetricValues(values:JsonRecord):MetricValues{
  const result={} as MetricValues;for(const [key,label] of metricFields){const value=values[key];if(value===null||value===undefined||String(value).trim()===''){result[key]=null;continue}if(!/^\d+$/.test(String(value))||!Number.isSafeInteger(Number(value)))throw Error(label+'只能是非负整数，未知请留空。');result[key]=Number(value)}
  if(Object.values(result).every(value=>value===null))throw Error('至少填写一项已取得的指标，其余保持未知。');return result;
}
export function parseMetricsCSV(raw:string,columns:Partial<Record<MetricKey|'observed_at'|'window',string>>={}):MetricRow[]{
  const rows:string[][]=[];let row:string[]=[],cell='',quoted=false;
  for(let i=0;i<raw.length;i++){const char=raw[i]!;if(char==='"'){if(quoted&&raw[i+1]==='"'){cell+='"';i++}else quoted=!quoted}else if(char===','&&!quoted){row.push(cell);cell=''}else if((char==='\r'||char==='\n')&&!quoted){if(char==='\r'&&raw[i+1]==='\n')i++;row.push(cell);if(row.some(value=>value.trim()))rows.push(row);row=[];cell=''}else cell+=char}
  if(quoted)throw Error('CSV 引号未闭合。');row.push(cell);if(row.some(value=>value.trim()))rows.push(row);if(rows.length<2||rows.length>201)throw Error('CSV 需含表头和1～200行数据。');
  const mapped=Object.fromEntries(Object.entries(columns).map(([target,source])=>[source,target]));const headers=rows.shift()!.map(item=>item.replace(/^\uFEFF/,'').trim()).map(item=>mapped[item]??(item==='observedAt'?'observed_at':item));
  if(!headers.includes('observed_at')||!headers.includes('window')||new Set(headers).size!==headers.length)throw Error('CSV 需含独立 observed_at、window 表头。');
  return rows.map((cells,index)=>{if(cells.length!==headers.length)throw Error('第'+(index+2)+'行列数不一致。');const item=Object.fromEntries(headers.map((key,i)=>[key,cells[i]!.trim()]));const observed=string(item.observed_at),window=string(item.window);if(!/(Z|[+-]\d{2}:?\d{2})$/.test(observed)||Number.isNaN(Date.parse(observed)))throw Error('第'+(index+2)+'行时间需要明确时区。');if(!['24h','7d','custom'].includes(window))throw Error('第'+(index+2)+'行时间窗无效。');return {observed_at:new Date(observed).toISOString(),window:window as MetricWindow,values:parseMetricValues(item)}});
}
/** The complete source and operation IDs are persisted before a multirow import. */
export async function metricBatchIdentity(publicationId:string,rows:MetricRow[],source:JsonRecord,previous?:{signature:string;operations:string[]}):Promise<{signature:string;operations:string[]}>{
  const data=new TextEncoder().encode(JSON.stringify({publication_id:publicationId,rows,source}));const digest=await crypto.subtle.digest('SHA-256',data);const signature=Array.from(new Uint8Array(digest)).map(value=>value.toString(16).padStart(2,'0')).join('');return previous?.signature===signature&&previous.operations.length===rows.length?previous:{signature,operations:rows.map(()=>crypto.randomUUID())};
}
