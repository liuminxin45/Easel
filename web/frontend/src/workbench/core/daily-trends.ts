import {record,string} from './models';

const DAY_MS=86_400_000,BEIJING_OFFSET_MS=8*60*60*1000;
export const dailyTrendsPath=(path:string):boolean=>new URL(path,'https://workbench.invalid').pathname==='/api/trends';
export const beijingDay=(now:number):string=>new Date(now+BEIJING_OFFSET_MS).toISOString().slice(0,10);
export const nextBeijingDayDelay=(now:number):number=>DAY_MS-((now+BEIJING_OFFSET_MS)%DAY_MS+DAY_MS)%DAY_MS;
export function dailyTrendsDay(value:unknown):string|undefined{
 const row=record(value),day=string(row.day);
 return row.version===1&&row.timezone==='Asia/Shanghai'&&/^\d{4}-\d{2}-\d{2}$/.test(day)&&Array.isArray(row.trends)?day:undefined;
}
export const emptyDailyTrends=(now:number)=>({version:1,day:beijingDay(now),timezone:'Asia/Shanghai',trends:[],updated:Math.floor(now/1000),warnings:[]});
