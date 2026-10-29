"""Small server-owned planning records for the Easel presentation.

Plans are human reminders, never distribution authority or scheduler jobs.
All production, version, feedback and delivery commands use existing services.
"""
import copy
import datetime as dt
import hashlib
import json
from easel_workbench.runtime.desk import stamp
from easel_workbench.runtime.toolbox_store import ident,pack,text


class FrontendConflict(ValueError):pass


class EaselFrontend:
    def __init__(self,box):
        self.box,self.store=box,box.store
        with self.store.connect() as c:
            for sql in ('CREATE TABLE IF NOT EXISTS easel_plans(id TEXT PRIMARY KEY,document TEXT NOT NULL)',
                        'CREATE TABLE IF NOT EXISTS easel_plan_history(id TEXT NOT NULL,revision INTEGER NOT NULL,document TEXT NOT NULL,PRIMARY KEY(id,revision))',
                        'CREATE TABLE IF NOT EXISTS easel_ui_operations(id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL)'):
                c.execute(sql)

    def plans(self):
        with self.store.connect() as c:return {'items':[json.loads(r['document']) for r in c.execute('SELECT document FROM easel_plans ORDER BY rowid DESC')],'automatic_publication':False}

    def command(self,value):
        value=copy.deepcopy(value);operation=ident(value.get('id'));signature=hashlib.sha256(pack(value).encode()).hexdigest()
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT signature,result FROM easel_ui_operations WHERE id=?',(operation,)).fetchone()
            if old:
                if old['signature']!=signature:raise FrontendConflict('同一排期操作不能改变内容')
                return json.loads(old['result'])
            if value.get('action')!='plan-save':raise ValueError('不支持的排期操作')
            key=ident(value.get('plan_id') or 'plan-'+hashlib.sha256(operation.encode()).hexdigest()[:24])
            row=c.execute('SELECT document FROM easel_plans WHERE id=?',(key,)).fetchone();previous=json.loads(row['document']) if row else None
            if value.get('base_revision')!=(previous['revision'] if previous else 0):raise FrontendConflict('排期已修改，请核对最新记录')
            wid=ident(value.get('work_id'));work=c.execute('SELECT id,title FROM toolbox_works WHERE id=?',(wid,)).fetchone()
            if not work:raise ValueError('请先保存准确作品或选题')
            version=value.get('version_id') or None
            if version and not c.execute('SELECT 1 FROM toolbox_jobs WHERE id=? AND work_id=?',(ident(version),wid)).fetchone():raise ValueError('排期版本不属于此作品')
            when=text(value.get('scheduled_at',''),100,True)
            try:
                parsed=dt.datetime.fromisoformat(when.replace('Z','+00:00'))
                if parsed.tzinfo is None:raise ValueError()
            except ValueError:raise ValueError('请选择带时区的完整排期时间') from None
            status=value.get('status','planned')
            if status not in ('planned','done','cancelled'):raise ValueError('排期状态无效')
            document={'id':key,'revision':(previous['revision'] if previous else 0)+1,'work_id':wid,'version_id':version,'title':work['title'],
                      'scheduled_at':parsed.isoformat(),'status':status,'note':text(value.get('note',''),5000),'created_at':previous['created_at'] if previous else stamp(),'updated_at':stamp(),'automatic_publication':False}
            c.execute('INSERT INTO easel_plans VALUES(?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',(key,pack(document)))
            c.execute('INSERT INTO easel_plan_history VALUES(?,?,?)',(key,document['revision'],pack(document)))
            result={'id':operation,'status':'completed','result':{'plan':document},'cache_invalidation':{'tags':['easel-plans','studio']}}
            c.execute('INSERT INTO easel_ui_operations VALUES(?,?,?)',(operation,signature,pack(result)))
            return result


def service(box):
    if not getattr(box,'easel_frontend',None):box.easel_frontend=EaselFrontend(box)
    return box.easel_frontend
