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
from easel_workbench.contracts.values import ident, pack
from easel_workbench.runtime.easel_connection_support import ConnectionConflict as IntegrationConflict, digest



from easel_workbench.features.installations.recipes import RECIPES,BASE_PACKAGES
from easel_workbench.features.installations.queue import InstallationQueue
from easel_workbench.infrastructure.installations.host import InstallationHost

class ConnectionEnvironment:
    def __init__(self, box):
        self.box, self.store, self.root = box, box.store, pathlib.Path(box.root).resolve()
        self.directory = self.root / '.runtime/media-tools'
        self._lock = threading.RLock()
        with self.store.connect() as c:
            c.executescript('CREATE TABLE IF NOT EXISTS media_install_jobs(id TEXT PRIMARY KEY,recipe TEXT NOT NULL,document TEXT NOT NULL);')
        self.host=InstallationHost(store=self.store,root=self.root,directory=self.directory,run=lambda *a,**k:self._run(*a,**k))
        self.queue=InstallationQueue(store=self.store,root=self.root,directory=self.directory)

    @property
    def python(self):
        return self.host.python

    @property
    def remotion(self):
        return self.host.remotion

    def child_environment(self):
        return self.host.child_environment()

    def _run(self, args, timeout=30):
        return self.host._run(args,timeout)

    def _install_run(self,job,args,timeout=30):
        return self.host._install_run(job,args,timeout)

    def check(self):
        return self.host.check()

    def install(self,value):
        self.check()
        job,created=self.queue.enqueue(value)
        if created:
            threading.Thread(target=self.run,args=(job["id"],),name=job["id"],daemon=True).start()
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
