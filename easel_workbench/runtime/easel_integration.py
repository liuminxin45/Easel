"""Easel tools behind the workbench's owner, work, version and receipt boundaries.

No Easel service/database is opened. Reads never start jobs. Commands are durable
and idempotent; a dispatched job is never automatically replayed after a crash.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import mimetypes
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import threading
import uuid

from easel_workbench.runtime.desk import stamp
from easel_workbench.runtime.toolbox_store import ident, pack, text

SOURCE = pathlib.Path(__file__).resolve().parent / 'vendor/easel'
CHANNELS = {'transcribe': '语音转写', 'speech': '配音', 'image': '生图', 'video': '视频', 'music': '音乐'}
FORMATS = {'audio': '配音', 'video': '视频', 'music': '音乐', 'image': '图片', 'transcript': '转写'}
SKILLS = {'speech': 'easel-voiceover', 'image': 'easel-image', 'video': 'easel-video', 'music': 'easel-music', 'transcribe': 'easel-transcribe', 'compose': 'easel-compose'}
TERMINAL = {'completed', 'failed', 'unknown', 'cancelled'}


class IntegrationConflict(ValueError):
    pass


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else pack(value).encode()).hexdigest()


def load_catalog():
    spec = importlib.util.spec_from_file_location('easel_model_catalog', SOURCE / 'scripts/model_registry.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = copy.deepcopy(module.MODEL_GROUPS)
    result['transcribe'] = {'label': '语音转写', 'providers': [
        {'id': 'local', 'name': '本机 Whisper', 'keys': [{'env': 'WHISPER_MODEL', 'label': '模型目录或名称', 'secret': False, 'required': True}]},
        {'id': 'openai', 'name': 'OpenAI 兼容转写', 'keys': [
            {'env': 'TRANSCRIBE_BASE_URL', 'label': 'API 根地址', 'secret': False, 'required': True},
            {'env': 'TRANSCRIBE_API_KEY', 'label': 'API Key', 'secret': True, 'required': True},
            {'env': 'TRANSCRIBE_MODEL', 'label': '模型', 'secret': False, 'required': True}]}]}
    return {k: result['voice' if k == 'speech' and 'voice' in result else k] for k in CHANNELS}


def initialize(c):
    c.executescript('''
CREATE TABLE IF NOT EXISTS media_configs(id TEXT NOT NULL,revision INTEGER NOT NULL,document TEXT NOT NULL,secret_ref TEXT NOT NULL,PRIMARY KEY(id,revision));
CREATE TABLE IF NOT EXISTS media_plans(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS media_jobs(id TEXT PRIMARY KEY,work_id TEXT,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS media_artifacts(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS media_operations(id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS media_imports(source_id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS media_account_sessions(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS media_job_work ON media_jobs(work_id);
''')


class EaselIntegration:
    def __init__(self, box, *, autostart=True, vault=None, runner=None):
        from easel_workbench.runtime.distribution_runtime import DPAPIVault
        self.box, self.store, self.root = box, box.store, pathlib.Path(box.root).resolve()
        self.autostart, self.runner = autostart, runner
        self.vault = vault or DPAPIVault(self.root / 'data/media-vault')
        self.catalog = load_catalog()
        self._threads = {}
        self._guard = threading.RLock()
        with self.store.connect() as c:
            initialize(c)

    def _records(self, c, table):
        assert table in ('media_jobs', 'media_plans', 'media_account_sessions')
        return [json.loads(r['document']) for r in c.execute('SELECT document FROM ' + table + ' ORDER BY rowid DESC LIMIT 500')]

    def accepts_new(self,stage):
        path=self.root/'data/easel-runtime.json'
        if not path.exists():return True
        try:
            flags=json.loads(path.read_text(encoding='utf-8'))
            return flags.get('accept_new_tasks',True) is True and (flags.get('stages') is None or stage in flags['stages'])
        except (OSError,ValueError,TypeError):return False

    def transcript(self,jid):
        job=self.job(jid)
        if job['stage']!='transcribe' or job['status']!='completed':raise ValueError('请选择已完成的转写版本')
        artifact=next((a for a in job['artifacts'] if a['mime'].startswith('text/')),None)
        if not artifact:raise ValueError('转写文本尚未交付')
        _,path=self.box.file(artifact['id']);raw=path.read_bytes()
        if len(raw)>2*1024*1024 or digest(raw)!=artifact['sha256']:raise IntegrationConflict('转写文本字节变化或超过可编辑材料上限')
        return {'text':raw.decode('utf-8-sig'),'artifact_id':artifact['id'],'sha256':artifact['sha256'],'version_id':jid,'automatic_send':False}

    def _job(self, c, key):
        row = c.execute('SELECT document FROM media_jobs WHERE id=?', (ident(key),)).fetchone()
        if not row:
            raise ValueError('媒体任务不存在')
        return json.loads(row['document'])

    def _put_job(self, c, job):
        c.execute('INSERT INTO media_jobs VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document', (job['id'], job.get('work_id'), pack(job)))

    def _public_job(self, job):
        return {k: copy.deepcopy(v) for k, v in job.items() if not k.startswith('_')}

    def config(self, c, key, revision=None):
        row = c.execute('SELECT * FROM media_configs WHERE id=?' + (' AND revision=?' if revision is not None else '') + ' ORDER BY revision DESC LIMIT 1', (ident(key), revision) if revision is not None else (ident(key),)).fetchone()
        if not row:
            raise ValueError('尚未配置此媒体能力')
        return {**json.loads(row['document']), '_secret_ref': row['secret_ref']}

    def bootstrap(self):
        with self.store.connect() as c:
            configs = [json.loads(r['document']) for r in c.execute('SELECT a.document FROM media_configs a WHERE revision=(SELECT max(revision) FROM media_configs b WHERE a.id=b.id) ORDER BY a.id')]
            jobs = [self._public_job(j) for j in self._records(c, 'media_jobs')]
            for config in configs:
                actual=next((j for j in jobs if (j.get('config') or {}).get('id')==config['id'] and (j.get('config') or {}).get('revision')==config['revision'] and j['status']=='completed' and j.get('execution_mode')=='model'),None)
                if actual:config.update(verification='artifact_verified',verification_job_id=actual['id'])
        return {'schema_version': 1, 'channels': CHANNELS, 'catalog': self.catalog, 'configs': configs, 'jobs': jobs,
                'source': json.loads((SOURCE / 'SOURCE.json').read_text(encoding='utf-8')),
                'execution_host': {'name': platform.node(), 'system': platform.system(), 'python': sys.version.split()[0]},
                'formats': FORMATS, 'learning': {'mode': 'manual', 'profile': '身份、读者与已确认偏好', 'skill': '制作方法与检查标准', 'feedback': '具体作品版本的原话与证据'}}

    def _save_config(self, c, value):
        channel = value.get('channel')
        if channel not in CHANNELS:
            raise ValueError('媒体通道无效')
        key = ident(value.get('config_id') or channel)
        row = c.execute('SELECT max(revision) FROM media_configs WHERE id=?', (key,)).fetchone()
        revision = row[0] or 0
        if value.get('base_revision') != revision:
            raise IntegrationConflict('媒体配置已变化，请核对后保存')
        provider = next((p for p in self.catalog[channel]['providers'] if p['id'] == value.get('provider')), None)
        if not provider:
            raise ValueError('媒体提供方无效')
        fields = provider['keys'] + self.catalog[channel].get('settings', [])
        allowed = {f['env']: f for f in fields}
        inputs = value.get('values', {})
        if not isinstance(inputs, dict) or set(inputs) - set(allowed):
            raise ValueError('配置包含未注册字段')
        old = self.config(c, key) if revision else None
        secrets = self.vault.get(old['_secret_ref'], key) if old else {}
        if old and old['provider'] != provider['id']:
            secrets = {}
        for name, val in inputs.items():
            val = text(val, 4000)
            if val or value.get('clear_keys', False):
                secrets[name] = val
        missing = [f['label'] for f in fields if f.get('required', True) and not secrets.get(f['env'])]
        public = {f['env']: secrets.get(f['env'], '') for f in fields if not f.get('secret', True)}
        for name, val in public.items():
            if ('BASE' in name or 'URL' in name) and val:
                from urllib.parse import urlsplit
                url = urlsplit(val)
                if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise ValueError('请输入不含凭据或参数的 API 根地址')
        ref = self.vault.put(key, secrets)
        doc = {'id': key, 'revision': revision + 1, 'channel': channel, 'provider': provider['id'], 'values': public,
               'configured': not missing, 'missing': missing, 'secret_configured': any(secrets.get(f['env']) for f in fields if f.get('secret', True)),
               'verification': 'not_tested', 'updated_at': stamp()}
        c.execute('INSERT INTO media_configs VALUES(?,?,?,?)', (key, doc['revision'], pack(doc), ref))
        return {'config': doc}

    def preview(self, value, c=None):
        if c is None:
            with self.store.connect() as connection:
                return self.preview(value, connection)
        prompt = text(value.get('prompt', ''), 100000, True)
        stage = value.get('stage')
        if stage not in SKILLS:
            raise ValueError('请选择制作或处理方式')
        source_ids = value.get('files', [])
        if not isinstance(source_ids, list) or len(source_ids) > 12:
            raise ValueError('素材最多12份')
        sources = []
        for fid in source_ids:
            row, path = self.box.file(fid)
            sources.append({'id': row['id'], 'name': row['name'], 'mime': row['mime'], 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        work_id = value.get('work_id')
        parent = None
        if work_id:
            parent = self._job(c, value.get('parent_version'))
            if parent.get('work_id') != work_id or parent['status'] != 'completed':
                raise ValueError('修改须绑定本作品已完成的准确父版')
            snapshot = copy.deepcopy(parent['creator'])
            if stage != parent['stage']:
                raise ValueError('换制作类型请创建关联作品')
            config = copy.deepcopy(parent.get('config'))
            # A modification follows the parent's exact method and settings.
            if value.get('config_id') and value['config_id'] != (config or {}).get('id'):
                raise ValueError('修改沿用父版配置；换配置请创建关联作品')
        else:
            selection = value.get('creator') or {}
            refs = selection.get('skills') or [{'id': SKILLS[stage], 'version': 1}]
            snapshot = self.box.creator.resolve(selection.get('profile_id', 'oil-pig'), 'media', refs, selection.get('trial') is True, selection.get('profile_revision'), c)
            config = self.config(c, value.get('config_id') or stage) if stage != 'compose' else None
        if config and not config['configured']:
            raise ValueError('媒体配置缺少：' + '、'.join(config['missing']))
        if stage in ('transcribe', 'compose') and not sources:
            raise ValueError('请先选择音视频或图片素材')
        if not any(s['id'] == SKILLS[stage] for s in snapshot['skills']):
            raise ValueError('本阶段须绑定对应媒体技能')
        options = copy.deepcopy(value.get('options') or {})
        allowed = {'duration', 'size', 'voice_id', 'mode', 'width', 'height', 'fps'}
        if not isinstance(options, dict) or set(options) - allowed:
            raise ValueError('媒体参数无效')
        for key, minimum, maximum in [('duration', 1, 600), ('width', 128, 3840), ('height', 128, 3840), ('fps', 1, 60)]:
            if key in options and (type(options[key]) not in (int, float) or not minimum <= options[key] <= maximum):
                raise ValueError('媒体参数超出范围：' + key)
        owner = snapshot['profile']
        original_feedback = []
        if work_id:
            original_feedback = [dict(r) for r in c.execute("SELECT id,candidate_id,kind,text,scope FROM toolbox_jobs WHERE work_id=? AND kind IN ('feedback','reject','accept') ORDER BY rowid", (work_id,))]
        body = snapshot['prompt_text'] + '\n\n## 本次目标\n' + prompt
        if original_feedback:
            body += '\n\n## 本作品版本链原始意见（尚未提炼）\n' + pack(original_feedback)
        override = value.get('instruction')
        if override is not None:
            body = text(override, 160000, True)
        plan = {'schema_version': 1, 'title': text(value.get('title') or prompt[:80], 500, True), 'stage': stage,
                'format': 'video' if stage == 'compose' else 'audio' if stage == 'speech' else 'transcript' if stage == 'transcribe' else stage,
                'prompt': prompt, 'instruction': body, 'creator': snapshot, 'config': config, 'files': sources, 'options': options,
                'work_id': work_id, 'parent_version': parent['id'] if parent else None, 'related_work_id': value.get('related_work_id'),
                'source_snapshot': copy.deepcopy(value.get('source_snapshot') or {}), 'source_release': json.loads((SOURCE / 'SOURCE.json').read_text())['source_tree_sha256']}
        if plan['related_work_id']:
            ident(plan['related_work_id'])
            if not c.execute('SELECT 1 FROM toolbox_works WHERE id=?', (plan['related_work_id'],)).fetchone():
                raise ValueError('关联作品不存在')
            completed=c.execute("SELECT id FROM toolbox_jobs WHERE work_id=? AND kind IN ('create','change') AND status='completed' ORDER BY rowid DESC LIMIT 1",(plan['related_work_id'],)).fetchone()
            if completed:
                from easel_workbench.runtime.content_studio import source as source_version
                source,artifacts=source_version(self.box,c,plan['related_work_id'],completed['id'])
                context={'work_id':plan['related_work_id'],'version_id':completed['id'],'title':source['title'],'body':source['body'],'source_token':source['token'],
                         'artifacts':[{'id':a['id'],'name':a['name'],'mime':a['mime']} for a in artifacts]}
            else:
                from easel_workbench.runtime.work_discussions import freeze as freeze_discussion
                from easel_workbench.runtime.article_drafts import read as read_draft
                context={'work_id':plan['related_work_id'],'draft':read_draft(self.box,plan['related_work_id'],c), 'discussion':freeze_discussion(c,plan['related_work_id'],None,bounded=False)}
            plan['source_snapshot']=context
            if override is None:plan['instruction']+='\n\n## 本次明确引用的关联作品（保持其原身份，不继承其画像偏好）\n'+pack(context)
            if len(plan['instruction'])>160000:raise ValueError('关联材料超过本轮可读指令上限，请缩小引用范围；原文未截断')
        plan['fingerprint'] = digest(plan)
        # secret references are opaque, but do not expose them to the browser.
        if config:
            plan['config'] = {k: v for k, v in config.items() if not k.startswith('_')}
            plan['fingerprint'] = digest({k: v for k, v in plan.items() if k != 'fingerprint'})
        return plan

    def _create_job(self, c, value):
        plan = self.preview(value, c)
        if value.get('fingerprint') != plan['fingerprint']:
            raise IntegrationConflict('画像、技能、配置、反馈或素材已变化，请重新核对制作方案')
        jid = 'media-' + digest(value['id'])[:28]
        wid = plan['work_id'] or 'work-' + digest(value['id'])[:28]
        now = stamp()
        if not plan['work_id']:
            c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)', (wid, None, plan['title'], plan['prompt'], now, now))
            c.execute('INSERT INTO toolbox_work_options VALUES(?,?,?)', (wid, plan['format'], 'auto'))
            self.box.creator.bind_work(c, wid, {'profile_id': plan['creator']['profile']['id'], 'profile_revision': plan['creator']['profile']['revision']})
            from easel_workbench.runtime.local_operations import reserve_work
            reserve_work(c,wid,plan['title'])
        job = {**plan, 'id': jid, 'work_id': wid, 'status': 'queued', 'created_at': now, 'artifacts': [],
               'execution_mode': 'script' if plan['stage'] == 'compose' else 'model', 'actual_input': plan['instruction'],
               'context_id': wid + ':' + plan['creator']['profile']['id'], 'send_state': 'not_sent', 'upstream_task_id': None,
               'usage': None, 'usage_status': 'not_obtained'}
        # Local media processes cannot enter the Codex production worker queue.
        c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,candidate_id,scope,signature,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                  (jid, wid, 'change' if plan['parent_version'] else 'create', plan['prompt'], plan['parent_version'], '[]', plan['fingerprint'], 'media_wait', now))
        c.execute('UPDATE toolbox_jobs SET files=? WHERE id=?',(pack([s['id'] for s in plan['files']]),jid))
        frozen_document=pack({'schema_version':3,'work_id':wid,'creator_snapshot':plan['creator'],
            'execution_prompt':{'body':plan['instruction'],'sha256':digest(plan['instruction'].encode())},'media_plan':plan})
        frozen_id='media-plan-'+digest(frozen_document.encode())[:28]
        frozen_path=self.root/'data/toolbox/files'/frozen_id/'制作方案.json'
        frozen_path.parent.mkdir(parents=True,exist_ok=True)
        if not frozen_path.exists():frozen_path.write_bytes(frozen_document.encode())
        if digest(frozen_path.read_bytes())!=digest(frozen_document.encode()):raise IntegrationConflict('冻结制作方案字节变化')
        c.execute('INSERT OR IGNORE INTO toolbox_files VALUES(?,?,?,?,?,?)',(frozen_id,'制作方案.json',str(frozen_path),'application/json',len(frozen_document.encode()),digest(frozen_document.encode())))
        c.execute('INSERT INTO toolbox_review_inputs VALUES(?,?,?)',(jid,frozen_id,frozen_document))
        self._put_job(c, job)
        from easel_workbench.runtime.task_runtime import initialize as initialize_trace
        initialize_trace(c)
        run={'schema_version':1,'id':jid,'work_id':wid,'snapshot':copy.deepcopy(plan['creator']),'status':'queued','created_at':now,
             'workflow':{'id':'media-stage-v1','source':'frozen_media_plan','execution':'sequential_receipts'},
             'steps':[{'id':'freeze','name':'冻结制作方案','executor':'program','status':'completed'},
                      {'id':'production','name':CHANNELS.get(plan['stage'],'视频合成'),'executor':job['execution_mode'],'status':'queued'},
                      {'id':'delivery','name':'核对交付文件','executor':'program','status':'waiting'}]}
        c.execute('INSERT INTO creator_task_runs VALUES(?,?,?,?)',(jid,wid,pack(run),now))
        c.execute('UPDATE toolbox_works SET updated_at=? WHERE id=?', (now, wid))
        return {'job': self._public_job(job), 'work_id': wid}

    def command(self, value):
        value = copy.deepcopy(value)
        operation = ident(value.get('id') or value.get('operation_id'))
        value['id'] = operation
        # Never persist plaintext configuration values in operation receipts.
        signature = digest(value)
        launch = None
        reconcile_launch=False
        if value.get('action')=='accept':
            from easel_workbench.runtime.completion_service import service as completion_service
            completion_service(self.box)
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM media_operations WHERE id=?', (operation,)).fetchone()
            if old:
                if old['signature'] != signature:
                    raise IntegrationConflict('同一操作标识不能提交不同内容')
                return json.loads(old['result'])
            action = value.get('action')
            if action == 'config-save':
                result = self._save_config(c, value)
            elif action == 'produce':
                if not self.accepts_new(value.get('stage')):raise IntegrationConflict('此媒体阶段暂未开放新任务；原作品与回执仍可核对')
                result = self._create_job(c, value)
                launch = result['job']['id']
            elif action == 'cancel':
                job = self._job(c, value.get('job_id'))
                if job['send_state'] != 'not_sent' or job['status'] != 'queued':
                    raise IntegrationConflict('任务已开始，请先核对原任务，不能当作尚未发送取消')
                job['status'] = 'cancelled'
                self._put_job(c, job)
                result = {'job': self._public_job(job)}
            elif action=='retry':
                job=self._job(c,value.get('job_id'))
                if not self.accepts_new(job['stage']):raise IntegrationConflict('此媒体阶段暂不启动新执行，请保留原任务')
                if job['send_state']!='not_sent' or job['status'] not in ('queued','failed') or job.get('attempt_count',0)>=4:
                    raise IntegrationConflict('仅明证尚未发出的任务可沿冻结输入继续；未知回执不重放')
                job.update(status='queued',error=None);self._put_job(c,job);launch=job['id']
                result={'job':self._public_job(job),'work_id':job['work_id']}
            elif action == 'reconcile':
                job = self._job(c, value.get('job_id'))
                thread=self._threads.get(job['id'])
                alive=bool(thread and thread.is_alive()) or self._worker_alive(job)
                if not alive:self._recover_outputs(c, job)
                if job['status']=='unknown' and not alive:launch=job['id'];reconcile_launch=True
                result = {'job': self._public_job(job)}
            elif action in ('accept', 'reject', 'feedback'):
                result = self._decision(c, value)
            else:
                raise ValueError('不支持的媒体操作')
            response = {'id': operation, 'status': 'accepted' if launch else 'completed', 'result': result}
            c.execute('INSERT INTO media_operations VALUES(?,?,?)', (operation, signature, pack(response)))
        if launch and self.autostart:
            self.start(launch,reconcile_launch)
        return response

    def _decision(self, c, value):
        job = self._job(c, value.get('version_id'))
        if job['work_id'] != value.get('work_id') or job['status'] != 'completed':
            raise ValueError('请选择本作品已完成的准确版本')
        action = value['action']
        if action == 'accept':
            if not job['artifacts']:
                raise ValueError('本版缺少实际成品')
            for a in job['artifacts']:
                _, path = self.box.file(a['id'])
                if digest(path.read_bytes()) != a['sha256']:
                    raise IntegrationConflict('成品字节变化，请重新核对')
        note = text(value.get('text', ''), 24000, action == 'feedback')
        if action=='accept':
            from easel_workbench.runtime.completion_service import service as completion_service
            completion_service(self.box).freeze(c,{'id':value['id'],'work_id':job['work_id'],'candidate_id':job['id'],'kind':'accept','scope':pack(['media']),'text':note,'signature':digest(value),'created_at':stamp()},None)
        c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,candidate_id,scope,signature,status,created_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                  (value['id'], job['work_id'], action, note, job['id'], pack(['media']) if action == 'accept' else '[]', digest(value), 'completed', stamp(), stamp()))
        c.execute('UPDATE toolbox_works SET updated_at=? WHERE id=?', (stamp(), job['work_id']))
        from easel_workbench.runtime.local_operations import queue_action
        queue_action(c,dict(c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(value['id'],)).fetchone()))
        return {'work_id': job['work_id'], 'version_id': job['id'], 'decision': action, 'execution_mode': 'local', 'delivery_created': False}

    def _directory(self, job):
        base=self.root/'data/media-jobs'/job['id']
        return base/('attempt-'+str(job['attempt_count'])) if job.get('attempt_count') else base

    def _worker_alive(self,job):
        path=self._directory(job)/'receipt.json'
        try:
            receipt=json.loads(path.read_text(encoding='utf-8'))
            from easel_workbench.runtime.distribution_runtime import process_identity
            return bool(receipt.get('worker_identity') and process_identity(receipt.get('worker_pid'))==receipt['worker_identity'])
        except (ValueError,OSError,TypeError):return False

    def start(self, jid, reconcile=False):
        with self._guard:
            if jid in self._threads and self._threads[jid].is_alive():return
            thread=threading.Thread(target=self.run_reconcile if reconcile else self.run_job,args=(jid,),name='media-'+jid,daemon=True)
            self._threads[jid]=thread;thread.start()

    def _payload(self,job):
        directory=self._directory(job);directory.mkdir(parents=True,exist_ok=True)
        payload=copy.deepcopy(job)
        payload.update(directory=str(directory),tool_bin=str(self.root/'.runtime/media-tools/bin'),source_paths=[str(self.box.file(row['id'])[1]) for row in job['files']])
        if job['stage']=='image':
            with self.store.connect() as c:
                resources=self.box.creator.materialize(job['creator'],self.root/'data/creator-inputs'/job['creator']['snapshot_sha256'],c=c)
            payload['reference_paths']=[r['path'] for r in resources if pathlib.Path(r['path']).suffix.lower() in ('.png','.jpg','.jpeg','.webp')]
            payload['reference_descriptors']=[{'sha256':r['sha256'],'source':r['original_path']} for r in resources if r['path'] in payload['reference_paths']]
        if job.get('config'):
            with self.store.connect() as c:config=self.config(c,job['config']['id'],job['config']['revision'])
            payload['env']=self.vault.get(config['_secret_ref'],config['id'])
        else:payload['env']={}
        from easel_workbench.runtime.media_environment import service as environment_service
        environment=environment_service(self.box)
        return payload,environment.python if environment.python.is_file() else pathlib.Path(sys.executable)

    def _invoke_worker(self,payload,python):
        if self.runner:return self.runner(payload)
        result=subprocess.run([str(python),str(pathlib.Path(__file__).with_name('easel_media_worker.py'))],input=pack(payload),capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=3600,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if result.returncode:raise RuntimeError('媒体进程未取得完整回执')
        return result

    def run_job(self,jid):
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE');job=self._job(c,jid)
            if job['status']!='queued' or job['send_state']!='not_sent':return
            attempt=job.get('attempt_count',0)+1
            if attempt>4:return
            job.update(status='running',started_at=stamp(),attempt_count=attempt)
            self._put_job(c,job)
        call_id=None
        try:
            payload,python=self._payload(job)
            if job['execution_mode']=='model':
                from easel_workbench.runtime.task_runtime import begin_call
                actual={'stage':job['stage'],'text':job['prompt'] if job['stage']=='speech' else job['instruction'],'files':job['files'],
                        'references':payload.get('reference_descriptors',[]),'options':job['options'],'config':job['config']}
                call_id=begin_call(self.box,'media',actual,actual['text'],operation_id=jid+'-provider-'+str(attempt),snapshot=job['creator'],task_id=jid)
            with self.store.connect() as c:
                job=self._job(c,jid);job.update(send_state='unknown',model_call_id=call_id);self._put_job(c,job)
                from easel_workbench.runtime.task_runtime import step
                step(c,jid,'production','running',call_id=call_id)
            self._invoke_worker(payload,python)
        except Exception:
            with self.store.connect() as c:
                job=self._job(c,jid)
                known=job['send_state']=='not_sent'
                job.update(status='failed' if known else 'unknown',error='发送前准备未完成，可在补齐依赖后继续原任务' if known else '执行结果待核对；保留原任务，不自动重发',finished_at=stamp())
                self._put_job(c,job)
                from easel_workbench.runtime.task_runtime import step
                step(c,jid,'production',job['status'],error=job['error'])
            if call_id:
                from easel_workbench.runtime.task_runtime import finish_call
                finish_call(self.box,call_id,'not_started' if known else 'unknown',error=job['error'])
            return
        try:
            with self.store.connect() as c:
                c.execute('BEGIN IMMEDIATE');self._recover_outputs(c,self._job(c,jid))
        except Exception:
            with self.store.connect() as c:
                job=self._job(c,jid);job.update(status='unknown',error='交付回执或文件校验未通过，请核对原任务；不会重新制作');self._put_job(c,job)

    def run_reconcile(self,jid):
        with self.store.connect() as c:job=self._job(c,jid)
        if job['status']!='unknown' or self._worker_alive(job):return
        try:
            payload,python=self._payload(job);payload['mode']='reconcile'
            self._invoke_worker(payload,python)
            with self.store.connect() as c:
                c.execute('BEGIN IMMEDIATE');self._recover_outputs(c,self._job(c,jid))
        except Exception:
            # Reconciliation is read-only at the provider and never calls a
            # generation endpoint, even if a status/download request fails.
            return

    def _recover_outputs(self, c, job):
        directory = self._directory(job)
        receipt_file = directory / 'receipt.json'
        if not receipt_file.is_file():
            if job['send_state'] != 'not_sent':
                job.update(status='unknown', error='尚未取得完整交付回执；继续核对原任务')
            self._put_job(c, job)
            return
        receipt = json.loads(receipt_file.read_text(encoding='utf-8'))
        if receipt.get('job_id') != job['id'] or receipt.get('fingerprint') != job['fingerprint']:
            raise IntegrationConflict('媒体回执与冻结任务不符')
        job.update(upstream_task_id=receipt.get('upstream_task_id'), tool_events=receipt.get('tool_events', []),
                   usage=receipt.get('usage'), usage_status='obtained' if receipt.get('usage') else 'not_obtained')
        outputs = receipt.get('outputs', [])
        if receipt.get('status') != 'completed' or not outputs:
            job.update(status=receipt.get('status') if receipt.get('status') in ('failed', 'unknown') else 'unknown', error=receipt.get('error', '交付不完整'), send_state=receipt.get('send_state', 'unknown'))
            self._put_job(c, job)
            from easel_workbench.runtime.task_runtime import step
            step(c,job['id'],'production',job['status'])
            call=c.execute('SELECT document FROM creator_model_calls WHERE id=?',(job.get('model_call_id') or job['id']+'-provider',)).fetchone()
            if call:
                record=json.loads(call['document']);record.update(status=job['status'],finished_at=stamp(),error=job['error'])
                c.execute('UPDATE creator_model_calls SET document=?,updated_at=? WHERE id=?',(pack(record),stamp(),record['id']))
            return
        artifacts = []
        destination = self.root / 'data/artifacts' / job['id']
        destination.mkdir(parents=True, exist_ok=True)
        for index, output in enumerate(outputs):
            source = (directory / output['path']).resolve()
            if not source.is_relative_to(directory.resolve()) or source.is_symlink() or not source.is_file() or source.stat().st_size > 512 * 1024 * 1024:
                raise ValueError('媒体交付文件无效')
            sha = digest(source.read_bytes())
            if sha != output['sha256']:
                raise IntegrationConflict('媒体交付字节不符')
            aid = 'artifact-' + digest([job['id'], index, sha])[:28]
            target = destination / (str(index) + '-' + source.name)
            if target.exists() and digest(target.read_bytes()) != sha:
                raise IntegrationConflict('不可变成品不能覆盖')
            if not target.exists():
                shutil.copyfile(source, target)
            mime = mimetypes.guess_type(source.name)[0] or 'application/octet-stream'
            c.execute('INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?,?)', (aid, job['id'], source.name, str(target), mime))
            meta = {'id': aid, 'name': source.name, 'mime': mime, 'size': target.stat().st_size, 'sha256': sha,
                    'role': output.get('role', 'final'), 'duration_ms': output.get('duration_ms'), 'derived_from': [s['id'] for s in job['files']], 'url': '/api/files/' + aid}
            c.execute('INSERT OR IGNORE INTO media_artifacts VALUES(?,?)', (aid, pack(meta)))
            artifacts.append(meta)
            from easel_workbench.runtime.local_operations import product_origin
            product_origin(c,aid,job['id'],target,sha)
        job.update(status='completed', send_state='submitted', artifacts=artifacts, finished_at=stamp(), error=None,
                   actual_output={'artifacts': artifacts, 'receipt_sha256': digest(receipt_file.read_bytes())})
        self._put_job(c, job)
        c.execute("UPDATE toolbox_jobs SET status='completed',finished_at=?,reply=? WHERE id=?", (stamp(), '媒体阶段已交付；实际字节与执行回执已绑定。', job['id']))
        from easel_workbench.runtime.task_runtime import step
        step(c,job['id'],'production','completed',receipt_kind='media_tool_events',artifacts=artifacts)
        step(c,job['id'],'delivery','completed',checks=['receipt_identity','file_bytes','sha256'],notice='程序核验，不代表审美或人工认可')
        call=c.execute('SELECT document FROM creator_model_calls WHERE id=?',(job.get('model_call_id') or job['id']+'-provider',)).fetchone()
        if call:
            record=json.loads(call['document']);record.update(status='completed',finished_at=stamp(),output=job['actual_output'],output_sha256=digest(job['actual_output']),token_usage=job['usage'])
            c.execute('UPDATE creator_model_calls SET document=?,updated_at=? WHERE id=?',(pack(record),stamp(),record['id']))
        c.execute('UPDATE toolbox_works SET updated_at=? WHERE id=?', (stamp(), job['work_id']))

    def job(self, jid):
        with self.store.connect() as c:
            return self._public_job(self._job(c, jid))

    def work(self, wid, c, summary=False):
        jobs = [json.loads(r['document']) for r in c.execute('SELECT document FROM media_jobs WHERE work_id=? ORDER BY rowid', (wid,))]
        if not jobs:
            return None
        work = dict(c.execute('SELECT * FROM toolbox_works WHERE id=?', (wid,)).fetchone())
        decisions = [dict(r) for r in c.execute("SELECT id,kind,candidate_id,created_at,status,text FROM toolbox_jobs WHERE work_id=? AND kind IN ('accept','reject','feedback') ORDER BY rowid", (wid,))]
        versions = [{**self._public_job(j), 'label': 'v' + str(i + 1).zfill(2), 'decisions': [d for d in decisions if d['candidate_id'] == j['id']]} for i, j in enumerate(jobs)]
        latest = next((j for j in reversed(jobs) if j['status'] == 'completed'), None)
        decision = next((d for d in reversed(decisions) if d['kind'] in ('accept', 'reject')), None)
        pending = [{'id': j['id'], 'kind': j['stage'], 'status': j['status']} for j in jobs if j['status'] in ('queued', 'running')]
        state = 'working' if pending else 'accepted' if decision and decision['kind'] == 'accept' else 'rejected' if decision else 'review' if latest else jobs[-1]['status']
        work.update(format=jobs[0]['format'], creator={k: jobs[0]['creator']['profile'][k] for k in ('id', 'name', 'revision')},
                    versions=versions, latest_version=latest['id'] if latest else None, latest_version_label=next((v['label'] for v in versions if latest and v['id'] == latest['id']), None),
                    state=state, pending=pending, decision=decision, review_needed=bool(latest and (not decision or decision['candidate_id'] != latest['id'])),
                    thumbnail=next((a for a in (latest or {}).get('artifacts', []) if a['mime'].startswith('image/')), None),
                    history=decisions, discussions=[], draft={}, retryable=[], production_issue=None, recovery=None,
                    media=True, related_work_id=jobs[0].get('related_work_id'))
        return {k: v for k, v in work.items() if k not in ('versions', 'history', 'material', 'discussions', 'draft', 'retryable')} if summary else work


def service(box):
    instance = getattr(box, 'easel', None)
    if instance is None:
        instance = EaselIntegration(box)
        box.easel = instance
    return instance
