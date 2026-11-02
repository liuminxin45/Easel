"""Pure collection schedules and durable state vocabulary."""
import datetime as dt
import json,re
TZ=dt.timezone(dt.timedelta(hours=8))
ACTIVE=("queued","running")
TERMINAL=("completed","partial","failed","blocked","skipped","cancelled")
COUNTERS=("fetched","selected","inserted","duplicates")

def packed(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def timestamp(value=None):return (value or dt.datetime.now(TZ)).astimezone(TZ).isoformat()


def identity(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',value):raise ValueError('采集操作标识无效')
    return value


def _time(value):
    if not isinstance(value,str):raise ValueError('采集计划时间无效')
    result=dt.datetime.fromisoformat(value)
    if result.tzinfo is None:raise ValueError('采集计划必须包含时区')
    return result.astimezone(TZ)


def validate_schedule(schedule):
    if not isinstance(schedule,dict):raise ValueError('采集计划无效')
    kind=schedule.get('kind')
    if kind=='interval':
        if 'seconds' in schedule:
            seconds=schedule['seconds']
            if type(seconds) not in (int,float) or not 1<=seconds<=86400:raise ValueError('采集间隔无效')
            return {'kind':kind,'seconds':seconds}
        minutes=schedule.get('minutes');offset=schedule.get('offset_minutes',0)
        if type(minutes) is not int or not 1<=minutes<=10080 or type(offset) is not int or not 0<=offset<minutes:raise ValueError('采集间隔无效')
        return {'kind':kind,'minutes':minutes,'offset_minutes':offset}
    if kind not in ('daily','weekly'):raise ValueError('不支持的采集计划')
    times=schedule.get('times')
    if not isinstance(times,list) or not 1<=len(times)<=48 or any(not isinstance(v,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',v) for v in times) or len(set(times))!=len(times):raise ValueError('采集时刻无效')
    days=schedule.get('weekdays',[0,1,2,3,4,5,6]) if kind=='weekly' else [0,1,2,3,4,5,6]
    if not isinstance(days,list) or not days or any(type(v) is not int or not 0<=v<=6 for v in days) or len(set(days))!=len(days):raise ValueError('采集星期无效')
    return {'kind':kind,'times':sorted(times),'weekdays':sorted(days)}


def slot(schedule,now,direction=1):
    """Next strictly-future slot, or latest slot <= now; fixed Beijing calendar."""
    schedule=validate_schedule(schedule);now=now.astimezone(TZ)
    if schedule['kind']=='interval':
        period=schedule.get('seconds') or schedule['minutes']*60;offset=schedule.get('offset_minutes',0)*60
        number=int((now.timestamp()-offset)//period)+(1 if direction>0 else 0)
        return dt.datetime.fromtimestamp(number*period+offset,TZ)
    values=[]
    for difference in range(9):
        day=now.date()+dt.timedelta(days=difference*(1 if direction>0 else -1))
        if day.weekday() not in schedule['weekdays']:continue
        for value in schedule['times']:
            hours,minutes=map(int,value.split(':'));candidate=dt.datetime.combine(day,dt.time(hours,minutes),TZ)
            if (candidate>now if direction>0 else candidate<=now):values.append(candidate)
    if not values:raise ValueError('无法计算下一次采集时间')
    return min(values) if direction>0 else max(values)


def schedule_label(value):
    value=validate_schedule(value)
    if value['kind']=='interval':return '每'+str(value['seconds'])+'秒' if 'seconds' in value else '每'+str(value['minutes'])+'分钟'
    label='、'.join(value['times'])
    return ('每天 ' if value['kind']=='daily' else '每周'+''.join('一二三四五六日'[i] for i in value['weekdays'])+' ')+label


class LeaseLost(RuntimeError):pass

