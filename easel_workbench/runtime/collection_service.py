"""Project-owned collection plans and durable receipts. No network or AI here."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

from easel_workbench.runtime.project_paths import ROOT

TZ=dt.timezone(dt.timedelta(hours=8))
ACTIVE=('queued','running')
TERMINAL=('completed','partial','failed','blocked','skipped','cancelled')
COUNTERS=('fetched','selected','inserted','duplicates')


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
        period=schedule['minutes']*60;offset=schedule['offset_minutes']*60
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
    if value['kind']=='interval':return '每'+str(value['minutes'])+'分钟'
    label='、'.join(value['times'])
    return ('每天 ' if value['kind']=='daily' else '每周'+''.join('一二三四五六日'[i] for i in value['weekdays'])+' ')+label


class LeaseLost(RuntimeError):pass


class CollectionService:
    def __init__(self,store,root=ROOT,clock=None):
        self.store=store;self.root=Path(root);self.clock=clock or (lambda:dt.datetime.now(TZ))
        self.state=self.root/'data/collection';self.state.mkdir(parents=True,exist_ok=True)
        with store.connect() as c:
            c.executescript('''
CREATE TABLE IF NOT EXISTS collection_operations(id TEXT PRIMARY KEY,signature TEXT NOT NULL,run_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS collection_runs(id TEXT PRIMARY KEY,trigger TEXT NOT NULL,scope TEXT NOT NULL,created_at TEXT NOT NULL,retry_of TEXT);
CREATE TABLE IF NOT EXISTS collection_tasks(id TEXT PRIMARY KEY,source_id TEXT NOT NULL,status TEXT NOT NULL,phase TEXT NOT NULL,created_at TEXT NOT NULL,started_at TEXT,finished_at TEXT,force INTEGER NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,owner TEXT,owner_pid INTEGER,owner_creation TEXT,lease_token TEXT,lease_until REAL,heartbeat TEXT,fetched INTEGER NOT NULL DEFAULT 0,selected INTEGER NOT NULL DEFAULT 0,inserted INTEGER NOT NULL DEFAULT 0,duplicates INTEGER NOT NULL DEFAULT 0,error TEXT,message TEXT NOT NULL DEFAULT '',warnings TEXT NOT NULL DEFAULT '[]',retry_of TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS collection_source_active ON collection_tasks(source_id) WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS collection_run_tasks(run_id TEXT NOT NULL,task_id TEXT NOT NULL,PRIMARY KEY(run_id,task_id));
CREATE INDEX IF NOT EXISTS collection_tasks_created ON collection_tasks(created_at);
CREATE TABLE IF NOT EXISTS collection_schedule_state(source_id TEXT PRIMARY KEY,next_run_at TEXT NOT NULL,last_slot TEXT,schedule_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS collection_slots(source_id TEXT NOT NULL,scheduled_for TEXT NOT NULL,task_id TEXT NOT NULL,PRIMARY KEY(source_id,scheduled_for));
''')
            if 'resume_from' not in {row[1] for row in c.execute('PRAGMA table_info(collection_tasks)')}:c.execute('ALTER TABLE collection_tasks ADD COLUMN resume_from TEXT')

    def configuration(self):
        path=self.root/'data/collection-config.json'
        try:value=json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:value={}
        if not isinstance(value,dict) or type(value.get('enabled',False)) is not bool:raise ValueError('采集服务配置无效')
        return value

    def definitions(self):
        registry_path=self.root/'sources.json';plan_path=self.root/'collection_schedules.json'
        registry=json.loads((registry_path if registry_path.exists() else ROOT/'sources.json').read_text(encoding='utf-8'))
        plans=json.loads((plan_path if plan_path.exists() else Path(__file__).with_name('collection_schedules.json')).read_text(encoding='utf-8'))
        if plans.get('schema_version')!=1 or plans.get('timezone')!='Asia/Shanghai':raise ValueError('采集计划版本或时区无效')
        config=self.configuration();overrides=config.get('sources',{})
        if not isinstance(overrides,dict):raise ValueError('来源设置无效')
        result={}
        for source,meta in registry.items():
            if source not in plans['sources']:continue
            override=overrides.get(source,{})
            if not isinstance(override,dict):raise ValueError('来源设置无效')
            result[source]={'id':source,'name':meta['name'],'enabled':override.get('enabled',True) is True,
                            'schedule':validate_schedule(override.get('schedule',plans['sources'][source])),'internal':False}
        if config.get('internal_jobs') not in (None,[]):raise ValueError('采集只支持当前九个来源，不支持内部或历史回填计划')
        return result

    def _sources(self,value,definitions):
        scope=value.get('scope','all_enabled')
        if scope=='all_enabled':return [key for key,row in definitions.items() if row['enabled'] and not row['internal']]
        source=value.get('source') if scope=='source' else scope
        if source not in definitions or not definitions[source]['enabled'] or definitions[source]['internal']:raise ValueError('采集来源不可用')
        return [source]

    def _enqueue(self,c,jid,sources,signature,trigger,force=False,retry_of=None,warnings=None,scope='normal',resume_from=None):
        old=c.execute('SELECT * FROM collection_operations WHERE id=?',(jid,)).fetchone()
        if old:
            if old['signature']!=signature:raise ValueError('同一采集操作标识不能用于不同内容')
            return old['run_id'],True
        active={row['source_id']:row['id'] for row in c.execute("SELECT id,source_id FROM collection_tasks WHERE status IN ('queued','running')")}
        # Another tab may already own exactly this work. Persist this operation's
        # receipt, but share that batch instead of creating duplicate cards/work.
        if all(source in active for source in sources):
            wanted=set(active[source] for source in sources)
            placeholders=','.join('?' for _ in wanted)
            row=c.execute('SELECT r.id FROM collection_runs r JOIN collection_run_tasks l ON l.run_id=r.id WHERE r.scope=? GROUP BY r.id HAVING count(*)=? AND sum(CASE WHEN l.task_id IN ('+placeholders+') THEN 1 ELSE 0 END)=? ORDER BY r.rowid DESC LIMIT 1',
                          (scope,len(wanted),*sorted(wanted),len(wanted))).fetchone()
            if row:
                c.execute('INSERT INTO collection_operations VALUES(?,?,?)',(jid,signature,row['id']))
                return row['id'],True
        now=timestamp(self.clock());c.execute('INSERT INTO collection_runs VALUES(?,?,?,?,?)',(jid,trigger,scope,now,retry_of))
        for source in sources:
            task=active.get(source)
            if not task:
                task=uuid.uuid4().hex
                c.execute('INSERT INTO collection_tasks(id,source_id,status,phase,created_at,force,warnings,retry_of,resume_from) VALUES(?,?,?,?,?,?,?,?,?)',
                          (task,source,'queued','queued',now,int(force),packed(warnings or []),retry_of,(resume_from or {}).get(source)))
            c.execute('INSERT INTO collection_run_tasks VALUES(?,?)',(jid,task))
        c.execute('INSERT INTO collection_operations VALUES(?,?,?)',(jid,signature,jid))
        return jid,False

    def enqueue(self,value):
        if not isinstance(value,dict):raise ValueError('采集请求无效')
        jid=identity(value.get('id'));signature=packed(value)
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT signature,run_id FROM collection_operations WHERE id=?',(jid,)).fetchone()
            if old:
                if old['signature']!=signature:raise ValueError('同一采集操作标识不能用于不同内容')
                run_id,reused=old['run_id'],True
            else:
                if not self.configuration().get('enabled',False):raise ValueError('采集服务尚未启用')
                sources=self._sources(value,self.definitions())
                if not sources:raise ValueError('当前没有启用的采集来源')
                run_id,reused=self._enqueue(c,jid,sources,signature,'manual',True)
        return {**self.get(run_id),'reused':reused}

    def _task(self,row,definitions):
        value=dict(row);meta=definitions.get(value['source_id'],{})
        return {key:value[key] for key in ('id','source_id','status','phase','created_at','started_at','finished_at','heartbeat','attempts','fetched','selected','inserted','duplicates','error','message','retry_of','resume_from')}|{'name':meta.get('name',value['source_id']),'warnings':json.loads(value['warnings'])}

    def _get(self,c,jid,definitions):
        row=c.execute('SELECT * FROM collection_runs WHERE id=?',(jid,)).fetchone()
        if not row:raise ValueError('采集记录不存在')
        tasks=[self._task(item,definitions) for item in c.execute('SELECT t.* FROM collection_tasks t JOIN collection_run_tasks r ON r.task_id=t.id WHERE r.run_id=? ORDER BY t.rowid',(jid,))]
        statuses=[task['status'] for task in tasks];done=sum(status in TERMINAL for status in statuses)
        if any(status=='running' for status in statuses):status='running'
        elif any(status=='queued' for status in statuses):status='queued' if not done else 'running'
        elif all(status in ('completed','skipped') for status in statuses):status='completed'
        elif any(status in ('completed','partial') for status in statuses):status='partial'
        elif any(status=='failed' for status in statuses):status='failed'
        else:status='blocked'
        started=[task['started_at'] for task in tasks if task['started_at']]
        finished=[task['finished_at'] for task in tasks if task['finished_at']]
        return {'id':row['id'],'trigger':row['trigger'],'scope':row['scope'],'status':status,'created_at':row['created_at'],
                'started_at':min(started) if started else None,'finished_at':max(finished) if done==len(tasks) and finished else None,
                'total':len(tasks),'completed':done,'failed':statuses.count('failed')+statuses.count('partial'),'blocked':statuses.count('blocked'),
                **{key:sum(task[key] for task in tasks) for key in COUNTERS},'retry_of':row['retry_of'],'tasks':tasks}

    def get(self,run_id):
        identity(run_id)
        # A damaged live configuration must not hide an already-durable receipt.
        # Only display labels degrade; enqueue/claim continue to require config.
        try:definitions=self.definitions()
        except (OSError,ValueError,TypeError,KeyError):definitions={}
        with self.store.connect() as c:return self._get(c,run_id,definitions)

    def status(self):
        definitions=self.definitions();config=self.configuration()
        try:heartbeat=json.loads((self.state/'heartbeat.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):heartbeat=None
        with self.store.connect() as c:
            runs=[self._get(c,row['id'],definitions) for row in c.execute("SELECT id FROM collection_runs WHERE scope='normal' ORDER BY rowid DESC LIMIT 30")]
            active=[self._get(c,row['id'],definitions) for row in c.execute("SELECT r.id FROM collection_runs r WHERE r.scope='normal' AND EXISTS (SELECT 1 FROM collection_run_tasks l JOIN collection_tasks t ON t.id=l.task_id WHERE l.run_id=r.id AND t.status IN ('queued','running')) ORDER BY r.rowid DESC")]
            sources=[]
            for source,meta in definitions.items():
                if meta['internal']:continue
                last=c.execute('SELECT * FROM collection_tasks WHERE source_id=? ORDER BY rowid DESC LIMIT 1',(source,)).fetchone()
                success=c.execute("SELECT finished_at FROM collection_tasks WHERE source_id=? AND status='completed' ORDER BY rowid DESC LIMIT 1",(source,)).fetchone()
                next_at=c.execute('SELECT next_run_at FROM collection_schedule_state WHERE source_id=?',(source,)).fetchone()
                sources.append({'id':source,'name':meta['name'],'enabled':meta['enabled'],'schedule':schedule_label(meta['schedule']),
                                'last_task':self._task(last,definitions) if last else None,'last_success_at':success[0] if success else None,
                                'next_run_at':next_at[0] if next_at else timestamp(slot(meta['schedule'],self.clock()))})
        return {'enabled':config.get('enabled',False),'heartbeat':heartbeat,'active_runs':active,
                'latest_run':runs[0] if runs else None,'recent_runs':[run for run in runs if run['status'] not in ACTIVE][:10],'sources':sources}

    def retry(self,run_id,value):
        identity(run_id);jid=identity(value.get('id'));signature=packed({'retry_of':run_id,'request':value})
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM collection_operations WHERE id=?',(jid,)).fetchone()
            if old:
                if old['signature']!=signature:raise ValueError('同一采集操作标识不能用于不同内容')
                selected,reused=old['run_id'],True
            else:
                if not self.configuration().get('enabled',False):raise ValueError('采集服务尚未启用')
                definitions=self.definitions();run=self._get(c,run_id,definitions)
                if run['status'] in ACTIVE:raise ValueError('本轮采集尚未结束，请先查看原进度')
                sources=[task['source_id'] for task in run['tasks'] if task['status'] in ('failed','blocked','partial') and definitions.get(task['source_id'],{}).get('enabled')]
                if not sources:raise ValueError('本轮没有需要重试的来源')
                resume={task['source_id']:task['id'] for task in run['tasks'] if task['source_id'] in sources}
                selected,reused=self._enqueue(c,jid,sources,signature,'retry',False,run_id,scope=run['scope'],resume_from=resume)
        return {**self.get(selected),'reused':reused}

    def schedule_due(self):
        if not self.configuration().get('enabled',False):return []
        now=self.clock().astimezone(TZ);definitions=self.definitions();result=[]
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            for source,meta in definitions.items():
                if not meta['enabled']:continue
                plan=meta['schedule'];plan_hash=hashlib.sha256(packed(plan).encode()).hexdigest()
                state=c.execute('SELECT * FROM collection_schedule_state WHERE source_id=?',(source,)).fetchone()
                if not state or state['schedule_hash']!=plan_hash:
                    c.execute('INSERT OR REPLACE INTO collection_schedule_state VALUES(?,?,?,?)',(source,timestamp(slot(plan,now)),state['last_slot'] if state else None,plan_hash))
                    continue
                expected=_time(state['next_run_at'])
                if expected>now:continue
                current=slot(plan,now,-1);current_text=timestamp(current)
                warnings=[]
                if current>expected:warnings=['错过的多个计划已合并为本次最新窗口检查；未声称补齐全部历史。']
                prior=c.execute('SELECT task_id FROM collection_slots WHERE source_id=? AND scheduled_for=?',(source,current_text)).fetchone()
                if not prior:
                    jid='scheduled-'+hashlib.sha256((source+'\0'+current_text).encode()).hexdigest()[:40]
                    run_id,_=self._enqueue(c,jid,[source],packed({'source':source,'scheduled_for':current_text}),'scheduled',warnings=warnings)
                    task=c.execute('SELECT task_id FROM collection_run_tasks WHERE run_id=?',(run_id,)).fetchone()[0]
                    c.execute('INSERT INTO collection_slots VALUES(?,?,?)',(source,current_text,task));result.append(run_id)
                c.execute('UPDATE collection_schedule_state SET next_run_at=?,last_slot=? WHERE source_id=?',(timestamp(slot(plan,now)),current_text,source))
        return result

    def claim(self,owner,owner_pid=None,owner_creation=None,lease_seconds=90):
        if not self.configuration().get('enabled',False):return None
        enabled=[source for source,meta in self.definitions().items() if meta['enabled']]
        if not enabled:return None
        now=self.clock();seconds=now.timestamp()
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute("SELECT * FROM collection_tasks WHERE status='queued' AND next_attempt<=? AND source_id IN ("+','.join('?' for _ in enabled)+") ORDER BY rowid LIMIT 1",(seconds,*enabled)).fetchone()
            if not row:return None
            token=uuid.uuid4().hex
            c.execute("UPDATE collection_tasks SET status='running',phase='fetching',started_at=coalesce(started_at,?),attempts=attempts+1,owner=?,owner_pid=?,owner_creation=?,lease_token=?,lease_until=?,heartbeat=? WHERE id=? AND status='queued'",
                      (timestamp(now),owner,owner_pid or os.getpid(),str(owner_creation) if owner_creation is not None else None,token,seconds+lease_seconds,timestamp(now),row['id']))
            return dict(c.execute('SELECT * FROM collection_tasks WHERE id=?',(row['id'],)).fetchone())

    def progress(self,task_id,token,phase=None,counters=None):
        now=self.clock();values={'heartbeat':timestamp(now),'lease_until':now.timestamp()+90}
        if phase:
            if phase not in ('fetching','screening','persisting'):raise ValueError('采集阶段无效')
            values['phase']=phase
        for key,value in (counters or {}).items():
            if key in COUNTERS and type(value) is int and 0<=value<=1000000:values[key]=value
        with self.store.connect() as c:
            count=c.execute("UPDATE collection_tasks SET "+','.join(key+'=?' for key in values)+" WHERE id=? AND lease_token=? AND status='running'",(*values.values(),task_id,token)).rowcount
            if count!=1:raise LeaseLost('原采集执行权已变化，停止写入')

    def finish(self,task_id,token,result):
        status=result.get('status')
        if status not in TERMINAL:raise ValueError('采集器未返回有效终态')
        warnings=result.get('warnings') or []
        if not isinstance(warnings,list):raise ValueError('采集告警格式无效')
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            prior=c.execute("SELECT * FROM collection_tasks WHERE id=? AND lease_token=? AND status='running'",(task_id,token)).fetchone()
            if not prior:raise LeaseLost('原采集执行权已变化，未覆盖新回执')
            values={key:result.get(key,prior[key]) for key in COUNTERS}
            if any(type(value) is not int or not 0<=value<=1000000 for value in values.values()):raise ValueError('采集数量无效')
            values.update(status=status,phase='finished' if status in ('completed','skipped') else prior['phase'],finished_at=timestamp(self.clock()),lease_until=None,
                          error=str(result.get('error') or '')[:1000] or None,message=str(result.get('message') or ('已检查，无新增' if status=='completed' and not values['inserted'] else ''))[:1000],
                          warnings=packed(list(dict.fromkeys([*json.loads(prior['warnings']),*[str(value)[:500] for value in warnings[:20]]]))))
            c.execute('UPDATE collection_tasks SET '+','.join(key+'=?' for key in values)+' WHERE id=? AND lease_token=?',(*values.values(),task_id,token))

    def recover(self,owner_is_gone):
        """An expired lease alone never authorizes replay of a live process."""
        recovered=[]
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            for row in c.execute("SELECT * FROM collection_tasks WHERE status='running'").fetchall():
                value=dict(row)
                if not owner_is_gone(value):continue
                status='queued' if row['attempts']<3 else 'failed'
                c.execute('UPDATE collection_tasks SET status=?,phase=?,lease_token=NULL,lease_until=NULL,owner=NULL,owner_pid=NULL,owner_creation=NULL,error=?,finished_at=? WHERE id=? AND lease_token=?',
                          (status,'queued' if status=='queued' else 'finished','上次采集进程已退出，保留阶段后继续。' if status=='queued' else '采集连续中断三次，请查看原因后重试。',None if status=='queued' else timestamp(self.clock()),row['id'],row['lease_token']))
                recovered.append(row['id'])
        return recovered
