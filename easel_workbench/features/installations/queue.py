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

from .recipes import RECIPES,BASE_PACKAGES

class InstallationQueue:
    def __init__(self,*,store,root,directory,recipes=RECIPES,base_packages=BASE_PACKAGES,conflict=IntegrationConflict,digest_fn=digest):
        self.store,self.root,self.directory=store,root,directory
        self.recipes,self.base_packages,self.conflict,self.digest=recipes,base_packages,conflict,digest_fn

    def enqueue(self, value):
        operation = ident(value.get('id'))
        recipe = value.get('recipe')
        if recipe not in self.recipes:
            raise ValueError('此运行时由项目固定管理，请选择已注册依赖')
        if self.recipes[recipe].get('needs_dir') and not (self.root/'skills/builtin/video-production/vendor/video-pipeline-sdk/deps/remotion/package-lock.json').is_file():
            raise ValueError('需要项目内 Remotion 工程目录及准确 lockfile')
        jid = 'install-' + self.digest(operation)[:24]
        created = False
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT recipe,document FROM media_install_jobs WHERE id=?', (jid,)).fetchone()
            if old:
                if old['recipe'] != recipe:
                    raise self.conflict('同一安装操作不能更换依赖')
                return json.loads(old['document']),False
            busy = c.execute("SELECT document FROM media_install_jobs WHERE json_extract(document,'$.state') IN ('queued','running') LIMIT 1").fetchone()
            if busy:
                raise self.conflict('当前运行目录已有安装任务，请先核对其结果')
            from easel_workbench.runtime.distribution_runtime import process_identity
            job = {'id': jid, 'recipe': recipe, 'state': 'queued', 'host': platform.node(), 'owner_pid':os.getpid(),'owner_identity':process_identity(os.getpid()),'target': str(self.directory), 'packages': list(dict.fromkeys([*self.base_packages,*self.recipes[recipe]['packages']])), 'created_at': stamp(), 'lines': []}
            c.execute('INSERT INTO media_install_jobs VALUES(?,?,?)', (jid, recipe, pack(job)))
            created = True
        return job,created
