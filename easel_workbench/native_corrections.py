"""One already-authorized correction, executed by the same Easel chat service.

This is a durable consumer for an existing delivery-review authorization. It
does not create initial productions, learn on a timer, own a model transport,
or replay accepted/unknown turns.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from pathlib import Path
import time

from .chat import ChatConflict
from .paths import owned_output_path
from .runtime.desk import stamp


def packed(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def sha(value):return hashlib.sha256(value if isinstance(value,bytes) else value.encode()).hexdigest()


def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS easel_native_corrections(job_id TEXT PRIMARY KEY,session_id TEXT NOT NULL,status TEXT NOT NULL,document TEXT NOT NULL)')


def admitted(root):
    state=Path(root)/'.local/workbench-deployment'
    if (state/'paused').exists():return False
    try:return json.loads((state/'admission.json').read_text(encoding='utf-8')).get('workers') is True
    except (OSError,ValueError,AttributeError):return False


def _parent(c,jid):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='easel_chat_turns'").fetchone():return None
    rows=c.execute("SELECT rowid,document FROM easel_chat_turns WHERE json_extract(document,'$.work.version_id')=?",(jid,)).fetchall()
    if not rows:return None
    if len(rows)!=1:raise ValueError('内部修正的父原生回合不唯一')
    turn=json.loads(rows[0]['document'])
    if turn.get('runner')!='easel.harnesses.codex.CodexAdapter' or turn.get('status')!='completed' or not turn.get('native_id') or not turn.get('native_turn_id'):
        raise ValueError('内部修正须有准确完成的 Easel 原生父回合')
    if sha(turn.get('actual_prompt',''))!=turn.get('actual_prompt_sha256') or sha(turn.get('frozen_instructions',''))!=turn.get('instructions_sha256'):
        raise ValueError('内部修正父回合的冻结字节已变化')
    from .runtime.task_runtime import validated_snapshot
    validated_snapshot(turn.get('snapshot'),(turn.get('snapshot') or {}).get('task'))
    turn['_rowid']=rows[0]['rowid']
    return turn


def _changed_user_input(c,document):
    parent=document['parent_job_id'];child=document['job_id'];wid=document['work']['work_id']
    if c.execute('SELECT 1 FROM toolbox_jobs WHERE work_id=? AND id!=? AND rowid>(SELECT rowid FROM toolbox_jobs WHERE id=?) LIMIT 1',(wid,child,parent)).fetchone():return True
    if c.execute('SELECT 1 FROM easel_chat_turns WHERE session_id=? AND id!=? AND rowid>? LIMIT 1',(document['session_id'],child,document['parent_turn_rowid'])).fetchone():return True
    fence=document.get('user_input_fence')
    if fence is not None:
        if c.execute('SELECT 1 FROM toolbox_review_events WHERE work_id=? AND seq>? LIMIT 1',(wid,fence['review_seq'])).fetchone():return True
        if c.execute('SELECT 1 FROM toolbox_article_draft_ops WHERE work_id=? AND rowid>? LIMIT 1',(wid,fence['draft_rowid'])).fetchone():return True
    else:
        # Older native receipts have no cross-table sequence fence. Fail closed
        # for the same millisecond rather than missing a later user edit.
        for table in ('toolbox_review_events','toolbox_article_draft_ops'):
            if c.execute('SELECT 1 FROM '+table+' WHERE work_id=? AND julianday(created_at)>=julianday(?) LIMIT 1',(wid,document['parent_created_at'])).fetchone():return True
    return False


def _artifacts(box,c,jid):
    root=(box.root/'data/artifacts').resolve();result=[]
    for row in c.execute('SELECT id,name,path,mime FROM artifacts WHERE task_id=? ORDER BY rowid',(jid,)):
        path=Path(row['path']).resolve()
        if not path.is_relative_to(root) or not path.is_file():raise ValueError('内部修正的父版原件不可用')
        result.append({**dict(row),'path':str(path),'sha256':sha(path.read_bytes())})
    return result


def _anchored(box,c,job,quality):
    from .runtime.learning_execution import verify_anchor
    artifacts=_artifacts(box,c,job['id']);names={}
    for item in artifacts:names.setdefault(item['name'],[]).append(item)
    source=c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?',(job['id'],)).fetchone()
    review=json.loads(source[0]) if source else {}
    required={r['id'] for r in review.get('learning_snapshot',{}).get('required_evidence',[])}
    requested={r['id'] for r in quality.get('subjective_disagreements',[])};result=[]
    for check in quality.get('checks',[]):
        if check.get('checker')!='independent_ai' or check.get('id')!='independent_review':continue
        evidence=check.get('evidence') or {}
        for finding in evidence.get('findings',[]):
            if finding.get('status')!='issue' or finding.get('basis_id') not in requested or finding.get('basis_id') not in required:continue
            matches=names.get(finding.get('artifact_name'),[])
            if len(matches)!=1 or matches[0]['sha256']!=finding.get('sha256'):raise ValueError('内部修正证据与准确父版文件不一致')
            actual=matches[0];anchor=verify_anchor(finding,actual)
            result.append({**copy.deepcopy(finding),'anchor':anchor,'artifact_id':actual['id']})
    if not result:raise ValueError('没有可核对到准确父版原件的内部修正位置')
    return result,artifacts


def enqueue(service,c,job,quality):
    """Return None only for legacy work; native work can never fall back."""
    parent=_parent(c,job['id'])
    if parent is None:
        owner=c.execute('SELECT origin FROM toolbox_execution WHERE job_id=?',(job['id'],)).fetchone() if c.execute("SELECT 1 FROM sqlite_master WHERE name='toolbox_execution'").fetchone() else None
        if owner and owner['origin'].startswith('easel_native_'):raise ValueError('原生作品缺少准确父回合，不转交旧制作器')
        return None
    initialize(c)
    if (parent.get('work') or {}).get('internal_correction'):
        return {'attempt':1,'status':'limit_reached','job_id':parent['id']}
    child='learning-fix-'+sha(job['id'])[:32]
    issues,artifacts=_anchored(service.box,c,job,quality)
    original=parent.get('actual_prompt','')
    if sha(original)!=parent.get('actual_prompt_sha256'):raise ValueError('父版实际制作输入指纹不符')
    instructions=parent.get('frozen_instructions','')
    if sha(instructions)!=parent.get('instructions_sha256'):raise ValueError('父版原生会话约定指纹不符')
    from .runtime.task_runtime import validated_snapshot
    snapshot=validated_snapshot(parent['snapshot'],parent['snapshot']['task'])
    if any('change' not in s['tasks'] for s in snapshot['skills']):raise ValueError('父版冻结技能不支持内部修改')
    snapshot['task']='change';snapshot.pop('snapshot_sha256',None);snapshot['snapshot_sha256']=sha(packed(snapshot))
    from .runtime.article_drafts import job_work
    options=service.box.options(job['work_id'],c)
    article_mode=job_work(options,job['id'],c).get('article_mode','auto')
    if article_mode not in ('auto','product') or parent['work'].get('article_mode',article_mode)!=article_mode:
        raise ValueError('父版文章模式与准确冻结输入不一致')
    work={'work_id':job['work_id'],'version_id':child,'parent_version_id':job['id'],
          'format':options['format'],'article_mode':article_mode,'kind':'change',
          'internal_correction':{'root_job_id':job['id'],'parent_turn_id':parent['id'],'attempt':1}}
    marker='## 本轮冻结输入\n';prefix,separator,tail=original.partition(marker)
    if not separator:raise ValueError('父版缺少可准确派生的本轮冻结输入')
    leading=len(tail)-len(tail.lstrip());payload,end=json.JSONDecoder().raw_decode(tail,leading)
    if not isinstance(payload,dict) or payload.get('work',{}).get('version_id')!=job['id']:raise ValueError('父版冻结输入与作品版本不一致')
    before={k:copy.deepcopy(payload.get(k)) for k in ('session_task','work','output_directory')}
    output=owned_output_path(service.box.root,Path('outputs')/parent['session_id']/child/'products')
    payload.update(session_task='change',work=work,output_directory=str(output))
    message='交付前内部修正（本次唯一一次）。保留父版，只修已核验到原件位置的问题；不混入后来用户输入。'
    correction={'root_job_id':job['id'],'parent_job_id':job['id'],'attempt':1,'issues':issues,
                'parent_artifacts':artifacts,'authorization':'用户已授权同一冻结依据下的一次有据内部修正'}
    body=prefix+marker+packed(payload)+tail[end:]+'\n\n## 已授权的一次内部修正\n'+message+'\n'+packed(correction)
    document={'schema_version':1,'job_id':child,'parent_job_id':job['id'],'parent_turn_id':parent['id'],
              'parent_turn_rowid':parent['_rowid'],'parent_created_at':parent['created_at'],'session_id':parent['session_id'],
              'user_input_fence':copy.deepcopy(parent.get('user_input_fence')),
              'work':work,'snapshot':snapshot,'actual_prompt':body,'actual_prompt_sha256':sha(body),
              'frozen_instructions':instructions,'instructions_sha256':sha(instructions),
              'origin_prompt_sha256':parent['actual_prompt_sha256'],'origin_snapshot_sha256':parent['snapshot']['snapshot_sha256'],
              'diff':{'changed_input_fields':{key:{'before':before[key],'after':payload[key]} for key in before},'methods_unchanged':True,
                      'preserved_prefix_sha256':sha(prefix),'added_correction':correction},'created_at':stamp(),
              'request':{'id':child,'turnId':child,'sessionId':parent['session_id'],'message':message,
                         'context':{'profile_id':snapshot['profile']['id'],'trial':bool(snapshot.get('trial'))},
                         'attachments':copy.deepcopy(parent.get('attachments',[]))}}
    if _changed_user_input(c,document):return {'attempt':0,'status':'superseded_by_user'}
    document['sha256']=sha(packed(document))
    now=stamp();files=[fid for fid in json.loads(job.get('files') or '[]') if not fid.startswith('review-')]
    c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,candidate_id,scope,files,signature,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
              (child,job['work_id'],'change',message,job['id'],'[]',packed(files),packed({'native_internal_correction':document['sha256']}),'queued',now))
    c.execute('INSERT INTO learning_correction_links VALUES(?,?,?)',(job['id'],child,now))
    from .runtime.local_operations import mark_execution
    from .runtime.task_runtime import clone_correction,read_run,_put_run
    from .runtime.learning_execution import snapshot as review_snapshot
    from .runtime.work_review import attach_document
    mark_execution(c,child,'observed','easel_native_correction')
    c.execute('INSERT OR IGNORE INTO toolbox_article_inputs SELECT ?,revision,document FROM toolbox_article_inputs WHERE job_id=?',(child,job['id']))
    frozen,_=review_snapshot(c,job['id']);frozen=copy.deepcopy(frozen or {})
    frozen.update(candidate_id=job['id'],creator_snapshot=snapshot,creation_instructions=body,internal_correction=correction)
    frozen['execution_prompt']={**frozen.get('execution_prompt',{}),'body':body,'sha256':sha(body),'creator_snapshot':snapshot,
                                'origin_prompt_sha256':parent['actual_prompt_sha256'],'internal_correction':correction,'approval_scope':correction['authorization']}
    frozen['execution_prompt'].pop('approved_preview_id',None)
    attach_document(service.box,c,job['work_id'],child,frozen)
    clone_correction(c,job['id'],child)
    run=read_run(c,child)
    if run:
        run.update(snapshot=snapshot,engine='easel.harnesses.codex',session_id=parent['session_id']);_put_run(c,run)
    service.clone_run(c,job['id'],child)
    c.execute('INSERT INTO easel_native_corrections VALUES(?,?,?,?)',(child,parent['session_id'],'queued',packed(document)))
    c.execute('UPDATE toolbox_works SET updated_at=? WHERE id=?',(now,job['work_id']))
    return {'attempt':1,'status':'queued','job_id':child,'execution_mode':'easel_native_correction'}


def _verify(box,c,document):
    if sha(packed({k:v for k,v in document.items() if k!='sha256'}))!=document.get('sha256'):raise ValueError('内部修正冻结记录指纹不符')
    parent=_parent(c,document['parent_job_id'])
    if not parent or parent['id']!=document['parent_turn_id'] or parent['session_id']!=document['session_id'] or parent['actual_prompt_sha256']!=document['origin_prompt_sha256'] or parent['snapshot']['snapshot_sha256']!=document['origin_snapshot_sha256']:
        raise ValueError('内部修正的父回合依据不一致')
    if parent['frozen_instructions']!=document['frozen_instructions']:raise ValueError('内部修正未沿用准确父版会话约定')
    from easel.harnesses import store as harness_store
    binding=harness_store.binding(Path(box.root)/'outputs/_sessions',document['session_id'])
    if not binding or binding.get('runtime')!='codex' or binding.get('native_id')!=parent['native_id']:
        raise ValueError('内部修正的原生会话绑定已变化')
    if _changed_user_input(c,document):raise ChatConflict('后到用户输入已接管，内部修正尚未发送')
    if _artifacts(box,c,document['parent_job_id'])!=document['diff']['added_correction']['parent_artifacts']:raise ValueError('内部修正父版原件已变化')
    # Material paths in the original frozen payload, unlike current uploads,
    # are immutable copies already accepted with the parent turn.
    _,_,tail=document['actual_prompt'].partition('## 本轮冻结输入\n')
    payload,_=json.JSONDecoder().raw_decode(tail,len(tail)-len(tail.lstrip()))
    for field,folder in (('attachments','materials'),('frozen_skill_files','skill-inputs')):
        for item in payload.get(field,[]):
            raw_path=Path(item['path'])
            try:path=owned_output_path(box.root,raw_path.relative_to(box.root))
            except ValueError:raise ValueError('内部修正的冻结素材路径无效') from None
            if not path.is_relative_to((box.root/'outputs/_sessions'/folder).resolve()) or not path.is_file() or sha(path.read_bytes())!=item['sha256']:
                raise ValueError('内部修正的冻结原始素材或技能资源不可用')


def supersede_queued_user(c,session_id):
    """New user acceptance wins over an unsent internal continuation."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='easel_native_corrections'").fetchone():return
    for row in c.execute("SELECT job_id FROM easel_native_corrections WHERE session_id=? AND status='queued'",(session_id,)).fetchall():
        jid=row['job_id']
        job=c.execute('SELECT dispatch_started,queue_id,turn_id,status FROM toolbox_jobs WHERE id=?',(jid,)).fetchone()
        if not job or job['status']!='queued' or job['dispatch_started'] or job['queue_id'] or job['turn_id'] or c.execute('SELECT 1 FROM easel_chat_turns WHERE id=?',(jid,)).fetchone():continue
        c.execute("UPDATE easel_native_corrections SET status='superseded_by_user' WHERE job_id=?",(jid,))
        c.execute("UPDATE toolbox_jobs SET status='cancelled',finished_at=?,error=? WHERE id=?",(stamp(),'后到用户输入已接管，内部修正未发送。',jid))


def accept(business,c,turn):
    """Trusted server work kwarg only; joined to ChatService BEGIN IMMEDIATE."""
    row=c.execute('SELECT status,document FROM easel_native_corrections WHERE job_id=?',(turn['id'],)).fetchone()
    if not row or row['status']!='queued':raise ChatConflict('本次内部修正已受理或不可再次发送')
    document=json.loads(row['document']);_verify(business.box,c,document)
    if not admitted(business.root):raise ChatConflict('服务尚未允许执行内部修正')
    if turn['work']!=document['work'] or turn['session_id']!=document['session_id'] or turn['snapshot']!=document['snapshot'] or turn['actual_prompt_sha256']!=document['actual_prompt_sha256'] or turn['instructions_sha256']!=document['instructions_sha256']:
        raise ValueError('内部修正与冻结授权不一致')
    link=c.execute('SELECT root_job_id FROM learning_correction_links WHERE child_job_id=?',(turn['id'],)).fetchone()
    if not link or link['root_job_id']!=document['parent_job_id']:raise ValueError('内部修正一次授权绑定不一致')
    job=c.execute('SELECT status,dispatch_started,queue_id,turn_id,kind,candidate_id,work_id FROM toolbox_jobs WHERE id=?',(turn['id'],)).fetchone()
    if job and (job['kind']!='change' or job['candidate_id']!=document['parent_job_id'] or job['work_id']!=document['work']['work_id']):raise ValueError('内部修正作品版本绑定不一致')
    if not job or job['status']!='queued' or job['dispatch_started'] or job['queue_id'] or job['turn_id']:raise ChatConflict('内部修正已经开始或回执未知，不会重发')
    c.execute("UPDATE easel_native_corrections SET status='accepted' WHERE job_id=?",(turn['id'],))


class NativeCorrections:
    def __init__(self,chat,business):
        self.chat,self.business,self.box=chat,business,business.box
        self._reader=None;self._closed=False;self._last_error=0.0
        with self.box.store.connect() as c:initialize(c)

    async def start(self):
        if self._reader is None:self._reader=asyncio.create_task(self._run())

    async def close(self):
        # Only stop polling. An accepted model turn belongs to ChatService.
        self._closed=True
        if self._reader:await self._reader

    def _cancel_unsent(self,c,document,status):
        row=c.execute('SELECT status FROM easel_native_corrections WHERE job_id=?',(document['job_id'],)).fetchone()
        if not row or row['status']!='queued' or c.execute('SELECT 1 FROM easel_chat_turns WHERE id=?',(document['job_id'],)).fetchone():return
        c.execute('UPDATE easel_native_corrections SET status=? WHERE job_id=? AND status=\'queued\'',(status,document['job_id']))
        c.execute("UPDATE toolbox_jobs SET status='cancelled',finished_at=?,error=? WHERE id=? AND status='queued' AND dispatch_started=0 AND queue_id IS NULL AND turn_id IS NULL",
                  (stamp(),'后到用户输入已接管，内部修正未发送。' if status=='superseded_by_user' else '内部修正冻结证据待核对，未发送。',document['job_id']))

    async def tick(self):
        if self._closed or not admitted(self.business.root):return {'status':'paused'}
        with self.box.store.connect() as c:
            row=c.execute("SELECT document FROM easel_native_corrections WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
            if not row:return {'status':'idle'}
            document=json.loads(row[0])
            if _changed_user_input(c,document):
                self._cancel_unsent(c,document,'superseded_by_user');return {'status':'superseded_by_user'}
            session=self.chat._session(c,document['session_id'])
            if session.get('pendingTurnId'):return {'status':'waiting_session'}
        try:
            receipt=await self.chat.submit(document['request'],snapshot=document['snapshot'],actual_prompt=document['actual_prompt'],
                                           work=document['work'],frozen_instructions=document['frozen_instructions'])
            return {'status':'accepted','job_id':document['job_id'],'turn_id':receipt['id']}
        except ChatConflict:
            with self.box.store.connect() as c:
                if _changed_user_input(c,document):self._cancel_unsent(c,document,'superseded_by_user')
            return {'status':'waiting_or_superseded'}
        except (ValueError,OSError,KeyError,TypeError) as error:
            with self.box.store.connect() as c:
                if c.execute('SELECT 1 FROM easel_chat_turns WHERE id=?',(document['job_id'],)).fetchone():
                    return {'status':'accepted','job_id':document['job_id'],'turn_id':document['job_id']}
                self._cancel_unsent(c,document,'blocked')
            from .runtime import server_logging as journal
            journal.exception('native_correction_accept_failed',error,operation_ref=journal.reference(document['job_id']))
            return {'status':'blocked'}

    async def _run(self):
        while not self._closed:
            try:await self.tick()
            except Exception as error:
                # No implicit model retry. The queue keeps the original receipt.
                if time.monotonic()-self._last_error>=30:
                    from .runtime import server_logging as journal
                    journal.exception('native_correction_poll_failed',error)
                    self._last_error=time.monotonic()
            if not self._closed:await asyncio.sleep(.5)
