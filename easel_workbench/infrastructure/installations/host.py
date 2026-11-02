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

class InstallationHost:
    def __init__(self,*,store,root,directory,run):
        self.store,self.root,self.directory=store,root,directory
        self.run=run

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
        from easel_workbench.infrastructure.processes import process_identity
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
            result = self.run([node, '--version'])
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
                    result = self.run([self.python, '-c', 'import importlib.metadata as m,importlib.util as u;print(m.version(' + repr(recipe['packages'][0].split('==')[0]) + ')) if u.find_spec(' + repr(recipe['module']) + ') else exit(1)'])
                    if result.returncode == 0:
                        state, version = 'ok', result.stdout.strip()
                    if key=='markdown' and version!='3.11.2':state='missing'
                    if key=='browser' and state=='ok':
                        qr=self.run([self.python,'-c',"import cv2,numpy;assert callable(cv2.QRCodeDetector);assert numpy.zeros((4,4),dtype=numpy.uint8).shape==(4,4)"])
                        if qr.returncode:state='missing'
                        binary=self.run([self.python,'-c',"from playwright.sync_api import sync_playwright;import os; p=sync_playwright().start();print(p.chromium.executable_path);exit(0 if os.path.isfile(p.chromium.executable_path) else 1)"])
                        if binary.returncode:state='missing'
                    if key=='ffmpeg' and state=='ok':
                        result=self.run([self.python,'-c',"import imageio_ffmpeg,subprocess; p=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-version'],capture_output=True);assert p.returncode==0"])
                        if result.returncode:state='missing'
                    if key=='pylibs' and state=='ok':
                        result=self.run([self.python,'-c','import PIL,edge_tts,pdfplumber,requests'])
                        if result.returncode:state='missing'
                except (OSError, subprocess.TimeoutExpired):
                    pass
            tools.append({'id': key, 'name': recipe['name'], 'group': recipe['group'], 'state': state, 'version': version,
                          'installable': state!='no_dir', 'packages': recipe['packages'], 'target': str(self.directory)})
        with self.store.connect() as c:
            jobs = [json.loads(r['document']) for r in c.execute('SELECT document FROM media_install_jobs ORDER BY rowid DESC LIMIT 30')]
        # A restart cannot leave a permanent running lock. Wait while either
        # the owner or its child is alive; after both exit, only re-check files.
        from easel_workbench.infrastructure.processes import process_identity
        for job in jobs:
            if job['state'] not in ('queued','running') or not job.get('owner_identity'):continue
            live=process_identity(job.get('owner_pid'))==job['owner_identity'] or bool(job.get('child_identity') and process_identity(job.get('child_pid'))==job['child_identity'])
            if not live:
                tool=next((t for t in tools if t['id']==job['recipe']), None)
                if tool is None:continue
                job.update(state='ok' if tool['state']=='ok' else 'fail',finished_at=stamp(),recovered_by='read_only_dependency_check',error=None if tool['state']=='ok' else '安装进程已结束；依赖复测未通过，可明确发起新安装')
                with self.store.connect() as c:c.execute('UPDATE media_install_jobs SET document=? WHERE id=?',(pack(job),job['id']))
        return {'host': platform.node(), 'system': platform.system(), 'tools': tools, 'jobs': [j for j in jobs if j['recipe'] in RECIPES], 'scope': 'project_local', 'checked_at': stamp()}
