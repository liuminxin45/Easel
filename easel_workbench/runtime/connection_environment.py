"""Platform-connection dependencies with durable project-local install receipts.

Adapts Easel's check -> install -> check flow. Its global winget/choco and
automatic PATH edits are deliberately replaced with isolated recipes.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import threading

from easel_workbench.runtime.desk import stamp
from easel_workbench.runtime.toolbox_store import ident, pack
from easel_workbench.runtime.easel_connection_support import ConnectionConflict as IntegrationConflict, digest

RECIPES = {
    'browser': {'name': '平台连接专用浏览器与二维码识别', 'packages': ['playwright==1.64.1','opencv-python==4.14.0.94','numpy==2.4.6'], 'module': 'playwright', 'group': '平台连接'},
    'biliup': {'name': 'B站扫码登录依赖', 'packages': ['biliup==1.3.4','segno==1.6.6'], 'module': 'biliup', 'group': '平台连接'},
    'ffmpeg': {'name': 'ffmpeg', 'packages': ['imageio-ffmpeg==0.6.0'], 'module': 'imageio_ffmpeg', 'group': 'rm'},
    'fw': {'name': 'faster-whisper', 'packages': ['faster-whisper==1.2.1'], 'module': 'faster_whisper', 'group': 'rm'},
    'model': {'name': 'Whisper large-v3 模型', 'packages': ['huggingface-hub'], 'module': 'huggingface_hub', 'group': 'rm'},
    'rmdeps': {'name': 'Remotion 工程依赖', 'packages': [], 'module': '', 'group': 'rm', 'needs_dir': True},
    'shell': {'name': 'Chrome Headless Shell', 'packages': [], 'module': '', 'group': 'rm', 'needs_dir': True},
    'pylibs': {'name': '常用 Python 库', 'packages': ['Pillow==12.3.0','edge-tts','pdfplumber','requests==2.34.2'], 'module': 'edge_tts', 'group': 'common'},
    'markdown': {'name': '公众号 Markdown 排版', 'packages': ['Markdown==3.11.2'], 'module': 'markdown', 'group': 'common'},
}
BASE_PACKAGES=['httpx==0.28.1','Pillow==12.3.0','requests==2.34.2']


class ConnectionEnvironment:
    def __init__(self, box):
        self.box, self.store, self.root = box, box.store, pathlib.Path(box.root).resolve()
        self.directory = self.root / '.runtime/media-tools'
        self._lock = threading.RLock()
        with self.store.connect() as c:
            c.executescript('CREATE TABLE IF NOT EXISTS media_install_jobs(id TEXT PRIMARY KEY,recipe TEXT NOT NULL,document TEXT NOT NULL);')

    @property
    def python(self):
        return self.directory / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')

    @property
    def remotion(self):
        return self.directory / 'remotion'

    def child_environment(self):
        scripts = self.python.parent
        return {'PATH': str(self.directory / 'bin') + os.pathsep + str(scripts) + os.pathsep + os.environ.get('PATH', ''),
                'PLAYWRIGHT_BROWSERS_PATH': str(self.directory / 'browsers'),
                'WHISPER_MODEL': str(self.directory / 'models/whisper-large-v3'),
                'EASEL_REMOTION_DIR': str(self.remotion)}

    def _run(self, args, timeout=30):
        return subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout,
            env={**os.environ,**self.child_environment()},
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

    def _install_run(self,job,args,timeout=30):
        from easel_workbench.runtime.distribution_runtime import process_identity
        process=subprocess.Popen([str(a) for a in args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',
            env={**os.environ,**self.child_environment()},cwd=str(self.remotion) if job['recipe'] in ('rmdeps','shell') else None,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        job.update(child_pid=process.pid,child_identity=process_identity(process.pid))
        with self.store.connect() as c:c.execute('UPDATE media_install_jobs SET document=? WHERE id=?',(pack(job),job['id']))
        try:stdout,stderr=process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill();process.communicate();raise
        return subprocess.CompletedProcess(args,process.returncode,stdout,stderr)

    def check(self):
        tools = [{'id': 'python', 'name': '工作台 Python 3.14.7', 'state': 'ok' if sys.version.split()[0]=='3.14.7' else 'fail', 'version': sys.version.split()[0], 'installable': False, 'group': 'rm'}]
        node = pathlib.Path(os.environ.get('LOCALAPPDATA', '')) / 'nvm/v24.19.0/node.exe'
        if not node.is_file():
            node = pathlib.Path(shutil.which('node') or 'node')
        try:
            result = self._run([node, '--version'])
            version = result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            version = ''
        tools.append({'id': 'node', 'name': 'Node 24.19.0', 'state': 'ok' if version == 'v24.19.0' else 'missing', 'version': version or None, 'installable': False, 'group': '工作台运行时'})
        for key, recipe in RECIPES.items():
            state, version = 'missing', None
            if recipe.get('needs_dir'):
                source=self.root/'skills/builtin/video-production/vendor/video-pipeline-sdk/deps/remotion'
                if not (source/'package-lock.json').is_file():state='no_dir'
                elif key=='rmdeps' and (self.remotion/'node_modules/.package-lock.json').is_file():state,version='ok','npm ci'
                elif key=='shell' and any(self.remotion.glob('node_modules/.remotion/**/chrome-headless-shell.exe')):state,version='ok','Chrome Headless Shell'
            elif key=='model':
                model=self.directory/'models/whisper-large-v3'
                if all((model/name).is_file() for name in ('model.bin','config.json','tokenizer.json')):state,version='ok','large-v3'
            elif self.python.is_file():
                try:
                    result = self._run([self.python, '-c', 'import importlib.metadata as m,importlib.util as u;print(m.version(' + repr(recipe['packages'][0].split('==')[0]) + ')) if u.find_spec(' + repr(recipe['module']) + ') else exit(1)'])
                    if result.returncode == 0:
                        state, version = 'ok', result.stdout.strip()
                    if key=='markdown' and version!='3.11.2':state='missing'
                    if key=='browser' and state=='ok':
                        qr=self._run([self.python,'-c',"import cv2,numpy;assert callable(cv2.QRCodeDetector);assert numpy.zeros((4,4),dtype=numpy.uint8).shape==(4,4)"])
                        if qr.returncode:state='missing'
                        binary=self._run([self.python,'-c',"from playwright.sync_api import sync_playwright;import os; p=sync_playwright().start();print(p.chromium.executable_path);exit(0 if os.path.isfile(p.chromium.executable_path) else 1)"])
                        if binary.returncode:state='missing'
                    if key=='ffmpeg' and state=='ok':
                        result=self._run([self.python,'-c',"import imageio_ffmpeg,subprocess; p=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-version'],capture_output=True);assert p.returncode==0"])
                        if result.returncode:state='missing'
                    if key=='pylibs' and state=='ok':
                        result=self._run([self.python,'-c','import PIL,edge_tts,pdfplumber,requests'])
                        if result.returncode:state='missing'
                except (OSError, subprocess.TimeoutExpired):
                    pass
            tools.append({'id': key, 'name': recipe['name'], 'group': recipe['group'], 'state': state, 'version': version,
                          'installable': state!='no_dir', 'packages': recipe['packages'], 'target': str(self.directory)})
        with self.store.connect() as c:
            jobs = [json.loads(r['document']) for r in c.execute('SELECT document FROM media_install_jobs ORDER BY rowid DESC LIMIT 30')]
        # A restart cannot leave a permanent running lock. Wait while either
        # the owner or its child is alive; after both exit, only re-check files.
        from easel_workbench.runtime.distribution_runtime import process_identity
        for job in jobs:
            if job['state'] not in ('queued','running') or not job.get('owner_identity'):continue
            live=process_identity(job.get('owner_pid'))==job['owner_identity'] or bool(job.get('child_identity') and process_identity(job.get('child_pid'))==job['child_identity'])
            if not live:
                tool=next((t for t in tools if t['id']==job['recipe']), None)
                if tool is None:continue
                job.update(state='ok' if tool['state']=='ok' else 'fail',finished_at=stamp(),recovered_by='read_only_dependency_check',error=None if tool['state']=='ok' else '安装进程已结束；依赖复测未通过，可明确发起新安装')
                with self.store.connect() as c:c.execute('UPDATE media_install_jobs SET document=? WHERE id=?',(pack(job),job['id']))
        return {'host': platform.node(), 'system': platform.system(), 'tools': tools, 'jobs': [j for j in jobs if j['recipe'] in RECIPES], 'scope': 'project_local', 'checked_at': stamp()}

    def install(self, value):
        self.check()
        operation = ident(value.get('id'))
        recipe = value.get('recipe')
        if recipe not in RECIPES:
            raise ValueError('此运行时由项目固定管理，请选择已注册依赖')
        if RECIPES[recipe].get('needs_dir') and not (self.root/'skills/builtin/video-production/vendor/video-pipeline-sdk/deps/remotion/package-lock.json').is_file():
            raise ValueError('需要项目内 Remotion 工程目录及准确 lockfile')
        jid = 'install-' + digest(operation)[:24]
        created = False
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT recipe,document FROM media_install_jobs WHERE id=?', (jid,)).fetchone()
            if old:
                if old['recipe'] != recipe:
                    raise IntegrationConflict('同一安装操作不能更换依赖')
                return json.loads(old['document'])
            busy = c.execute("SELECT document FROM media_install_jobs WHERE json_extract(document,'$.state') IN ('queued','running') LIMIT 1").fetchone()
            if busy:
                raise IntegrationConflict('当前运行目录已有安装任务，请先核对其结果')
            from easel_workbench.runtime.distribution_runtime import process_identity
            job = {'id': jid, 'recipe': recipe, 'state': 'queued', 'host': platform.node(), 'owner_pid':os.getpid(),'owner_identity':process_identity(os.getpid()),'target': str(self.directory), 'packages': list(dict.fromkeys([*BASE_PACKAGES,*RECIPES[recipe]['packages']])), 'created_at': stamp(), 'lines': []}
            c.execute('INSERT INTO media_install_jobs VALUES(?,?,?)', (jid, recipe, pack(job)))
            created = True
        if created:
            threading.Thread(target=self.run, args=(jid,), name=jid, daemon=True).start()
        return job

    def run(self, jid):
        with self._lock:
            with self.store.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                row = c.execute('SELECT document FROM media_install_jobs WHERE id=?', (jid,)).fetchone()
                job = json.loads(row['document'])
                if job['state'] != 'queued':
                    return
                job.update(state='running', started_at=stamp())
                c.execute('UPDATE media_install_jobs SET document=? WHERE id=?', (pack(job), jid))
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                if not self.directory.resolve().is_relative_to(self.root) or self.directory.is_symlink():
                    raise ValueError('运行目录无效')
                if not self.python.is_file():
                    result = self._install_run(job,[sys.executable, '-m', 'venv', self.directory / 'venv'], 180)
                    if result.returncode:
                        raise ValueError('独立 Python 环境创建失败')
                recipe=job['recipe']
                if recipe in ('rmdeps','shell'):
                    source=self.root/'skills/builtin/video-production/vendor/video-pipeline-sdk/deps/remotion'
                    if not self.remotion.exists():shutil.copytree(source,self.remotion,ignore=shutil.ignore_patterns('node_modules'))
                    npm=pathlib.Path(os.environ.get('LOCALAPPDATA',''))/'nvm/v24.19.0/npm.cmd'
                    if not npm.is_file():raise ValueError('固定 Node 24.19.0 工具链不可用')
                    args=[os.environ.get('COMSPEC','cmd.exe'),'/d','/c',str(npm),'ci'] if recipe=='rmdeps' else [os.environ.get('COMSPEC','cmd.exe'),'/d','/c',str(npm),'exec','--no','--','remotion','browser','ensure']
                    result=self._install_run(job,args,1800)
                else:
                    result = self._install_run(job,[self.python, '-m', 'pip', '--isolated','install','--index-url','https://pypi.org/simple', '--disable-pip-version-check', *job['packages']], 1800)
                # Pip output contains no user/provider secrets. Keep bounded logs.
                job['lines'] = (result.stdout + '\n' + result.stderr).splitlines()[-80:]
                if result.returncode:
                    raise ValueError('依赖安装未完成')
                if recipe=='model':
                    target=self.directory/'models/whisper-large-v3'
                    result=self._install_run(job,[self.python,'-c',"from huggingface_hub import snapshot_download;import sys;snapshot_download('Systran/faster-whisper-large-v3',local_dir=sys.argv[1])",target],7200)
                    if result.returncode:raise ValueError('模型下载未完成')
                if recipe=='ffmpeg':
                    result=self._run([self.python,'-c','import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())'])
                    binary=pathlib.Path(result.stdout.strip());directory=self.directory/'bin';directory.mkdir(exist_ok=True)
                    shutil.copy2(binary,directory/('ffmpeg.exe' if os.name=='nt' else 'ffmpeg'))
                if job['recipe'] == 'browser':
                    env = {**os.environ, 'PLAYWRIGHT_BROWSERS_PATH': str(self.directory / 'browsers')}
                    result = self._install_run(job,[self.python, '-m', 'playwright', 'install', 'chromium'], 1800)
                    if result.returncode:
                        raise ValueError('浏览器下载未完成')
                check = next(t for t in self.check()['tools'] if t['id'] == job['recipe'])
                if check['state'] != 'ok':
                    raise ValueError('装后复测未通过')
                job.update(state='ok', version=check['version'], finished_at=stamp())
            except Exception:
                job.update(state='fail', error='安装或装后校验未完成，请查看此任务记录', finished_at=stamp())
            with self.store.connect() as c:
                c.execute('UPDATE media_install_jobs SET document=? WHERE id=?', (pack(job), jid))


def service(box):
    if not getattr(box, 'connection_environment', None):
        box.connection_environment = ConnectionEnvironment(box)
    return box.connection_environment


def tools(box):
    runtime=service(box);result=runtime.check();rows=[]
    for tool in result['tools']:
        row={**tool,'scope':'project_local','installKey':tool['id'],'desc':'固定版本，仅检测' if not tool['installable'] else '项目隔离安装；完成后重新校验','detail':None}
        row['group']='pub' if row['group']=='平台连接' else 'rm' if row['group']=='工作台运行时' else row['group']
        if row['id']=='browser':
            rows.extend([{**row,'id':'pw'},{**row,'id':'cft','name':'Chrome for Testing（隔离 Chromium）'}])
        else:rows.append(row)
    return {'python':str(runtime.python),'tools':rows,'jobs':result['jobs'],
            'activeJobs':[{'id':'pw' if job['recipe']=='browser' else job['recipe'],'jobId':job['id']} for job in result['jobs'] if job['state'] in ('queued','running')]}


def install_port(box,value):
    if not isinstance(value.get('tool_id'),str):raise ValueError('请选择已注册的安装依赖')
    recipe={'pw':'browser','cft':'browser'}.get(value.get('tool_id'),value.get('tool_id'))
    job=service(box).install({'id':value.get('id'),'recipe':recipe})
    return {'jobId':job['id'],'id':value['tool_id'],'state':'running'}


def job_port(box,jid):
    with box.store.connect() as c:row=c.execute('SELECT document FROM media_install_jobs WHERE id=?',(ident(jid),)).fetchone()
    if not row:raise ValueError('安装任务不存在')
    job=json.loads(row[0]);state='running' if job['state'] in ('queued','running') else job['state']
    return {'jobId':job['id'],'id':job['recipe'],'state':state,'lines':job.get('lines',[]),'result':{'detail':job.get('error')},'started':job.get('started_at'),'ended':job.get('finished_at')}
