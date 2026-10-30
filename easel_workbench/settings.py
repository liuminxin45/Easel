"""Owner-scoped, revisioned settings around Easel's settings implementation."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

from fastapi import HTTPException
from pydantic import ValidationError
from easel import harnesses
from easel.direct_api import api_config, read_settings, DirectAPIError
from easel.harnesses import store as harness_store
from easel.harnesses.base import RunRequest, HarnessError
from easel.runtime_env import proxy_environment, web_environment
from .runtime.toolbox_store import ident, pack


class SettingsConflict(ValueError):
    pass


def signature(value):
    return hashlib.sha256(pack(value).encode()).hexdigest()


class SettingsService:
    def __init__(self, box, *, vault=None):
        from .runtime.distribution_runtime import DPAPIVault
        self.box, self.store, self.root = box, box.store, Path(box.root).resolve()
        self.vault = vault or DPAPIVault(self.root / 'data/workbench-settings')
        self.lock = threading.RLock()
        with self.store.connect() as c:
            c.executescript('''
CREATE TABLE IF NOT EXISTS workbench_settings_versions(revision INTEGER PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workbench_settings_operations(id TEXT PRIMARY KEY,signature TEXT NOT NULL,state TEXT NOT NULL,result TEXT);
''')
        scripts = str(Path(__file__).resolve().parents[1] / 'skills/shared/scripts')
        if scripts not in sys.path:
            sys.path.insert(0, scripts)

    def current(self, revision=None):
        with self.store.connect() as c:
            row = c.execute('SELECT document FROM workbench_settings_versions ORDER BY revision DESC LIMIT 1' if revision is None else
                            'SELECT document FROM workbench_settings_versions WHERE revision=?', () if revision is None else (revision,)).fetchone()
        if row:
            return json.loads(row[0])
        if revision not in (None, 0):
            raise SettingsConflict('准确的运行配置版本不存在')
        original = harness_store.settings(self.root / 'outputs', {'EASEL_AGENT_RUNTIME': 'codex'})
        return {'revision': 0, 'runtime': 'codex', 'models': original['models'],
                'sandbox': 'workspace-write', 'codex_auto_approve': False, 'secret_ref': None}

    def environment(self, revision=None):
        document = self.current(revision)
        return self.vault.get(document['secret_ref'], 'workbench-settings') if document.get('secret_ref') else read_settings(self.root / '.env')

    def capture(self):
        """Persist the initial configuration once, before a session transaction."""
        with self.lock:
            state = self.current()
            if not state['revision']:
                state['secret_ref'] = self.vault.put('workbench-settings', read_settings(self.root / '.env'))
                state['revision'] = 1
                with self.store.connect() as c:
                    c.execute('INSERT OR IGNORE INTO workbench_settings_versions VALUES(?,?)', (1, pack(state)))
                state = self.current()
            return {key: copy.deepcopy(state[key]) for key in ('revision', 'runtime', 'models', 'sandbox', 'codex_auto_approve')}

    def public(self):
        state = self.current()
        return {**{key: value for key, value in state.items() if not key.endswith('_ref')},
                'locked': 'EASEL_AGENT_RUNTIME' in os.environ,
                'agents': [harnesses.describe(runtime) for runtime in harness_store.IDS]}

    def execution_environment(self, settings):
        state = self.current(settings['revision'])
        if any(state[key] != settings[key] for key in ('runtime', 'models', 'sandbox', 'codex_auto_approve')):
            raise SettingsConflict('会话运行配置与准确版本不一致')
        environment = proxy_environment(web_environment(self.environment(state['revision'])), 'localhost,127.0.0.1,::1')
        environment.update(EASEL_AGENT_RUNTIME=settings['runtime'], EASEL_ROOT=str(self.root))
        # Optional dependencies are visible only to this project's child processes.
        from .runtime.connection_environment import service as environment_service
        environment.update(environment_service(self.box).child_environment())
        return environment

    def openclaw_environment(self, settings):
        state = self.current(settings['revision'])
        directory = self.root / '.runtime/openclaw' / ('revision-' + str(state['revision']))
        if not directory.resolve().is_relative_to(self.root) or directory.is_symlink():
            raise SettingsConflict('OpenClaw 配置目录不属于本项目')
        directory.mkdir(parents=True, exist_ok=True)
        document = self.vault.get(state['openclaw_ref'], 'workbench-openclaw') if state.get('openclaw_ref') else {}
        defaults = document.setdefault('agents', {}).setdefault('defaults', {})
        defaults['workspace'] = str(self.root)
        if state['models'].get('openclaw'):
            defaults['model'] = {'primary': state['models']['openclaw']}
        path = directory / 'openclaw.json'
        if not path.exists():
            harness_store.write_json(path, document)
            from .runtime.distribution_runtime import _private_acl
            _private_acl(directory, True)
            _private_acl(path)
        elif json.loads(path.read_text(encoding='utf-8')) != document:
            raise SettingsConflict('准确的 OpenClaw 配置版本已变化，未执行')
        return {'OPENCLAW_STATE_DIR': str(directory), 'OPENCLAW_CONFIG_PATH': str(path),
                'EASEL_OPENCLAW_STATE_DIR': str(directory)}

    def operation(self, operation):
        with self.store.connect() as c:
            row = c.execute('SELECT state,result FROM workbench_settings_operations WHERE id=?', (ident(operation),)).fetchone()
        return {'state': row['state'], 'result': json.loads(row['result']) if row['result'] else None} if row else {'state': 'not_found'}

    def _module(self, directory, environment, state):
        spec = importlib.util.spec_from_file_location('easel_workbench_settings_projection', Path(__file__).parent / 'runtime/settings_upstream.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        config = Path(directory) / 'openclaw.json'
        config.write_text(pack({'agents': {'defaults': {'workspace': str(self.root)}}, 'models': {'providers': {}}}), encoding='utf-8')
        if state.get('openclaw_ref'):
            config.write_text(pack(self.vault.get(state['openclaw_ref'], 'workbench-openclaw')), encoding='utf-8')
        module.PROJECT_ROOT, module.OUTPUTS_DIR, module.ENV_FILE = self.root, self.root / 'outputs', self.root / '.env'
        module._read_env = lambda: dict(environment)
        module.read_settings = lambda *args, **kwargs: dict(environment)
        module._harness_settings = lambda: dict(state)
        module._oc_config_path = lambda: config
        module._write_env_direct = lambda updates: environment.update({key: value for key, value in updates.items() if value.strip()})
        module._warn_http_transport_unavailable = lambda *args: None
        return module, config

    async def channels(self, runtime=None):
        if runtime not in (None, 'api', 'openclaw'):
            raise ValueError('仅聊天和 OpenClaw 才有 API 供应商配置')
        state = self.current()
        with tempfile.TemporaryDirectory(prefix='easel-settings-read-') as directory:
            module, _ = self._module(directory, self.environment(), state)
            result = module._model_channels(runtime)
        return {**result, 'revision': state['revision']}

    async def status(self):
        state = self.current()
        runtime = state['runtime']
        installed, error, gateway = False, '', False
        try:
            installed = harnesses.describe(runtime)['installed']
            if runtime == 'api':
                api_config(self.environment())
                gateway = True
            elif runtime == 'openclaw':
                gateway = installed
            else:
                gateway = installed
        except DirectAPIError:
            error = 'API 配置不完整'
        except Exception:
            error = '运行环境检测未完成'
        return {'runtime': runtime, 'transport': 'openclaw-cli' if runtime=='openclaw' else runtime, 'gateway': gateway, 'installed': installed,
                'authVerified': False, 'error': error, 'revision': state['revision'],
                'routeDetail': 'CLI 已安装仅代表找到可执行程序；登录与模型可用性需实际对话验证。',
                'modelConfigured': gateway, 'gatewayUp': gateway, 'installWarnings': []}

    async def native_models(self, runtime):
        if runtime not in ('codex', 'opencode'):
            raise ValueError('此底座不支持原生模型列表')
        from easel.harnesses.models import available_models
        environment = proxy_environment(web_environment(self.environment()), 'localhost,127.0.0.1,::1')
        environment.update(EASEL_ROOT=str(self.root), EASEL_AGENT_RUNTIME=runtime)
        models = await asyncio.wait_for(available_models(runtime, RunRequest('', self.root, environment)), 25)
        return {'runtime': runtime, 'models': models}

    async def command(self, path, value):
        operation = ident(value.get('id'))
        request = {key: val for key, val in value.items() if key != 'id'}
        digest = signature({'path': path, 'request': request})
        # Durable reservation precedes every possible provider request. Lost
        # read/selftest receipts can be inspected, never automatically reissued.
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM workbench_settings_operations WHERE id=?', (operation,)).fetchone()
            if old:
                if old['signature'] != digest:
                    raise SettingsConflict('同一设置操作不能更改内容')
                if old['state'] == 'completed':
                    return json.loads(old['result'])
                raise SettingsConflict('原操作回执待核对，没有重复执行')
            c.execute('INSERT INTO workbench_settings_operations VALUES(?,?,?,NULL)', (operation, digest, 'pending'))
        try:
            async with self._async_guard():
                result = await self._execute(path, request, operation_id=operation)
            with self.store.connect() as c:
                c.execute("UPDATE workbench_settings_operations SET state='completed',result=? WHERE id=?", (pack(result), operation))
            return result
        except (ValueError, HTTPException, ValidationError, HarnessError, asyncio.TimeoutError) as error:
            detail = '字段格式无效，请核对输入' if isinstance(error, ValidationError) else self.scrub(str(getattr(error, 'detail', error)))
            with self.store.connect() as c:
                c.execute("UPDATE workbench_settings_operations SET state='rejected',result=? WHERE id=?", (pack({'error': detail}), operation))
            raise

    def _async_guard(self):
        if not hasattr(self, '_guard'):
            self._guard = asyncio.Lock()
        return self._guard

    def scrub(self, text):
        result = str(text)
        for key, value in self.environment().items():
            if any(word in key.upper() for word in ('KEY', 'SECRET', 'TOKEN', 'PASSWORD')) and len(value) >= 4:
                result = result.replace(value, '***')
        return result[:300]

    async def _execute(self, path, request, *, operation_id=None):
        state = self.current()
        if path == '/api/env/install':
            from .runtime.connection_environment import install_port
            return await asyncio.to_thread(install_port, self.box, {**request,'id':operation_id})
        writing = path in ('/api/settings/harness', '/api/settings/models/save', '/api/settings/local-agents/enable')
        if writing and (type(request.get('expected_revision')) is not int or request['expected_revision'] != state['revision']):
            raise SettingsConflict('配置已有新版本，请重新读取后保存')
        if path.startswith('/api/settings/harness/models/'):
            return await self.native_models(path.rsplit('/', 1)[-1])
        if path == '/api/settings/harness':
            if 'EASEL_AGENT_RUNTIME' in os.environ:
                raise SettingsConflict('启动环境固定了执行引擎，请修改启动环境后重启')
            runtime = request.get('runtime')
            if runtime not in harness_store.IDS or not harnesses.describe(runtime)['installed']:
                raise ValueError('请选择已经安装或配置的执行引擎')
            model = request.get('model', '')
            if not isinstance(model, str) or len(model) > 240 or any(ord(ch) < 32 for ch in model):
                raise ValueError('模型覆盖格式无效')
            if request.get('sandbox') not in ('read-only', 'workspace-write') or type(request.get('codex_auto_approve', False)) is not bool:
                raise ValueError('权限设置无效')
            if not state['revision']:
                self.capture()
                state = self.current()
            state.update(runtime=runtime, sandbox=request['sandbox'], codex_auto_approve=request.get('codex_auto_approve', state['codex_auto_approve']))
            state['models'] = {**state['models'], runtime: model}
            if not state.get('secret_ref'):
                state['secret_ref'] = self.vault.put('workbench-settings', self.environment())
            state['revision'] += 1
            with self.store.connect() as c:
                c.execute('INSERT INTO workbench_settings_versions VALUES(?,?)', (state['revision'], pack(state)))
            return self.public()
        environment = self.environment()
        with tempfile.TemporaryDirectory(prefix='easel-settings-operation-') as directory:
            module, config = self._module(directory, environment, state)
            handlers = {
                '/api/settings/models/save': (module.api_settings_models_save, module.ModelSaveRequest),
                '/api/settings/models/available': (module.api_models_available, module.ModelsFetchRequest),
                '/api/settings/models/selftest': (module.api_models_selftest, module.SelftestRequest),
                '/api/settings/local-agents/enable': (module.api_local_agent_enable, module.LocalAgentEnableRequest),
            }
            if path not in handlers:
                raise ValueError('未知设置操作')
            handler, schema = handlers[path]
            if path == '/api/settings/local-agents/enable':
                request = {**request, 'id': request.get('agent_id')}
            result = await handler(schema.model_validate(request))
            if writing:
                if not state['revision']:
                    self.capture()
                    state = self.current()
                state['secret_ref'] = self.vault.put('workbench-settings', environment)
                if config.is_file():
                    state['openclaw_ref'] = self.vault.put('workbench-openclaw', json.loads(config.read_text(encoding='utf-8')))
                state['revision'] += 1
                with self.store.connect() as c:
                    c.execute('INSERT INTO workbench_settings_versions VALUES(?,?)', (state['revision'], pack(state)))
                result['revision'] = state['revision']
        return result


def service(box):
    if not getattr(box, 'settings_service', None):
        box.settings_service = SettingsService(box)
    return box.settings_service


async def handle(settings, path, request, value=None):
    from .chat_api import response
    if not (path in ('/api/status',) or path.startswith(('/api/settings/', '/api/env/'))):
        return None
    try:
        if request.method in ('GET', 'HEAD'):
            if path == '/api/env/tools':
                from .runtime.connection_environment import tools
                return response(await asyncio.to_thread(tools, settings.box))
            if path.startswith('/api/env/job/'):
                from .runtime.connection_environment import job_port
                return response(await asyncio.to_thread(job_port, settings.box, path.rsplit('/', 1)[-1]))
            if path in ('/api/status', '/api/settings/bootstrap'):
                return response(await settings.status())
            if path == '/api/settings/harness':
                return response(await asyncio.to_thread(settings.public))
            if path == '/api/settings/models':
                return response(await settings.channels(request.query_params.get('runtime')))
            if path.startswith('/api/settings/operations/'):
                return response(settings.operation(path.rsplit('/', 1)[-1]))
            if path == '/api/settings/local-agents':
                with tempfile.TemporaryDirectory() as directory:
                    module, _ = settings._module(directory, settings.environment(), settings.current())
                    return response(await module.api_local_agents())
        if request.method == 'POST':
            return response(await settings.command(path, value))
        return response({'error': '未知设置接口'}, 404)
    except HTTPException as error:
        return response({'error': settings.scrub(error.detail)}, error.status_code)
    except (ValueError, ValidationError, HarnessError, asyncio.TimeoutError) as error:
        return response({'error': '字段格式无效，请核对输入' if isinstance(error,ValidationError) else settings.scrub(str(error))}, 409 if isinstance(error, (SettingsConflict, HarnessError)) else 400)
