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
                        'CREATE TABLE IF NOT EXISTS easel_topics(id TEXT PRIMARY KEY,document TEXT NOT NULL)',
                        'CREATE TABLE IF NOT EXISTS easel_topic_history(id TEXT NOT NULL,revision INTEGER NOT NULL,document TEXT NOT NULL,PRIMARY KEY(id,revision))',
                        'CREATE TABLE IF NOT EXISTS easel_ui_operations(id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL)'):
                c.execute(sql)

    def plans(self):
        with self.store.connect() as c:return {'items':[json.loads(r['document']) for r in c.execute('SELECT document FROM easel_plans ORDER BY rowid DESC')],'automatic_publication':False}

    def topics(self):
        # Existing work drafts remain available; board changes never alter a
        # frozen work version or imply production, adoption or publication.
        drafts=[work for work in self.box.works()['items'] if work['state'] in ('draft','discussing')]
        with self.store.connect() as c:
            saved={row['id']:json.loads(row['document']) for row in c.execute('SELECT * FROM easel_topics ORDER BY rowid DESC')}
        bound={value.get('work_id') for value in saved.values()}
        for work in drafts:
            if work['id'] in bound:continue
            saved.setdefault(work['id'],{'id':work['id'],'work_id':work['id'],'title':work['title'],'note':'','source':'','status':'pending','revision':0})
        return {'items':[value for value in saved.values() if not value.get('deleted')]}

    def _topic(self,c,value,operation):
        key=ident(value.get('topic_id') or 'topic-'+hashlib.sha256(operation.encode()).hexdigest()[:24])
        row=c.execute('SELECT document FROM easel_topics WHERE id=?',(key,)).fetchone()
        previous=json.loads(row['document']) if row else None
        if value.get('base_revision')!=(previous['revision'] if previous else 0):raise FrontendConflict('选题已修改，请核对最新记录')
        work=c.execute('SELECT id,title FROM toolbox_works WHERE id=?',(key,)).fetchone()
        if value.get('topic_id') and not previous and not work:raise ValueError('选题不存在')
        if previous and previous.get('deleted'):raise FrontendConflict('选题已删除')
        work_id=value.get('work_id') or (previous or {}).get('work_id') or (work['id'] if work else None)
        if work_id:
            ident(work_id)
            if not c.execute('SELECT 1 FROM toolbox_works WHERE id=?',(work_id,)).fetchone():raise ValueError('选题作品不存在')
            if previous and previous.get('work_id') and previous['work_id']!=work_id:raise FrontendConflict('不能替换选题已关联的作品')
        status=value.get('status','pending')
        if status not in ('pending','doing','done'):raise ValueError('选题状态无效')
        title=text(value.get('title',''),500,True)
        if not title.strip():raise ValueError('请填写选题')
        document={'id':key,'revision':(previous['revision'] if previous else 0)+1,'title':title,
                  'note':text(value.get('note',''),10000),'source':text(value.get('source',''),1000),'status':status,
                  'deleted':value['action']=='topic-delete','created_at':previous['created_at'] if previous else stamp(),'updated_at':stamp(),
                  **({'work_id':work_id} if work_id else {})}
        c.execute('INSERT INTO easel_topics VALUES(?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',(key,pack(document)))
        c.execute('INSERT INTO easel_topic_history VALUES(?,?,?)',(key,document['revision'],pack(document)))
        return {'id':operation,'status':'completed','result':{'topic':document},'cache_invalidation':{'tags':['easel-plans','studio']}}

    def command(self,value):
        value=copy.deepcopy(value);operation=ident(value.get('id'));signature=hashlib.sha256(pack(value).encode()).hexdigest()
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT signature,result FROM easel_ui_operations WHERE id=?',(operation,)).fetchone()
            if old:
                if old['signature']!=signature:raise FrontendConflict('同一排期操作不能改变内容')
                return json.loads(old['result'])
            if value.get('action') in ('topic-save','topic-delete'):
                result=self._topic(c,value,operation)
                c.execute('INSERT INTO easel_ui_operations VALUES(?,?,?)',(operation,signature,pack(result)))
                return result
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
