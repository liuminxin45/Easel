"""Bounded local-v2 read-only calls through Easel's actual Codex adapter.

Historical snapshots and injected legacy runners retain codex exec. New calls
use an isolated temporary native home, the existing account, no MCP inventory,
read-only sandbox, exact image bytes/schema/effort and one execution attempt.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import uuid

from easel import harnesses
from easel.harnesses.base import HarnessError, RunRequest
from easel.harnesses.commands import base_command
from easel.harnesses.rpc import connection, close_sessions
from easel.runtime_env import proxy_environment, web_environment
from easel_workbench.runtime.readonly_codex import DISABLED


class ReadonlyExecutionUnknown(ConnectionError):
    def __init__(self, receipt):
        self.receipt = copy.deepcopy(receipt)
        super().__init__('只读模型调用回执未知；未自动重试。')


class ReadonlyOutputInvalid(ValueError):
    def __init__(self, receipt):
        self.receipt = copy.deepcopy(receipt)
        super().__init__('原生模型已完成但结果未通过结构校验；实际输出已保存，未重跑模型。')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def project_snapshot(snapshot):
    rows = snapshot.get('skills') if isinstance(snapshot, dict) else None
    return bool(rows) and all(isinstance(row, dict) and str(row.get('entry', '')).startswith('skills/builtin/')
                              and type(row.get('version')) is int and row['version'] >= 2 for row in rows)


def option(arguments, name):
    values = [arguments[index + 1] for index, item in enumerate(arguments[:-1]) if item == name]
    if len(values) > 1:
        raise ValueError('Ambiguous read-only execution option')
    return values[0] if values else None


def external_auth(environment):
    native = Path(environment.get('CODEX_HOME') or Path.home() / '.codex') / 'auth.json'
    if not native.is_file() or native.is_symlink() or not 0 < native.stat().st_size <= 1024 * 1024:
        raise ValueError('只读执行缺少有界的现有原生登录；未启动模型。')
    raw = native.read_bytes(); document = json.loads(raw); tokens = document.get('tokens') or {}
    access, account = tokens.get('access_token'), tokens.get('account_id')
    if not isinstance(access, str) or not access or not isinstance(account, str) or not account:
        raise ValueError('只读执行需要现有ChatGPT账号的准确访问令牌；未启动模型或新登录。')
    return {'type': 'chatgptAuthTokens', 'accessToken': access, 'chatgptAccountId': account}, native, sha(raw)


def access_expiry(access):
    """Read only the JWT expiry hint; native auth still verifies the credential."""
    try:
        parts = access.split('.')
        if len(parts) != 3 or not parts[1] or len(parts[1]) > 32768:
            return None
        claims = json.loads(base64.b64decode(parts[1] + '=' * (-len(parts[1]) % 4), altchars=b'-_', validate=True))
        expiry = claims.get('exp') if isinstance(claims, dict) else None
        return expiry if type(expiry) in (int, float) and math.isfinite(expiry) and expiry > 0 else None
    except (ValueError, TypeError, UnicodeError, OverflowError):
        return None


async def prepare_external_auth(environment, cwd, timeout, receipt, persist, existing):
    """Refresh near-expiry managed auth natively, never copy or write refresh tokens."""
    auth, source, before_sha = existing
    expiry = access_expiry(auth['accessToken'])
    receipt['native_auth_refresh'] = {'requested': False, 'expiry_known': expiry is not None,
        'source_before_sha256': before_sha}
    if expiry is None or expiry > time.time() + 300:
        persist()
        return auth, before_sha
    refresh = receipt['native_auth_refresh']
    refresh.update(requested=True, reason='access_expired_or_within_300_seconds', previous_expiry=expiry)
    persist()
    session_key = 'readonly-auth-refresh-' + uuid.uuid4().hex
    normal_env = proxy_environment(web_environment(environment), 'localhost,127.0.0.1,::1')
    # Explicitly retain the managed home; this is not the isolated external-auth server.
    normal_env['CODEX_HOME'] = str(source.parent)
    request = RunRequest('', Path(cwd), normal_env, session_key=session_key, sandbox='read-only', frozen_instructions='')
    command = base_command('codex') + ['app-server']
    async def reject(*args):
        raise HarnessError('原生登录续期不接受额外权限或新登录')
    async def refresh_once():
        async with connection(request, command, lambda *args: None, reject) as rpc:
            if rpc.initialized is None:
                rpc.initialized = await rpc.call('initialize', {'clientInfo': {'name': 'easel-readonly-auth', 'version': '1'},
                    'capabilities': {'experimentalApi': True}})
                await rpc.send({'method': 'initialized'})
            account = await rpc.call('account/read', {'refreshToken': True})
            if (account.get('account') or {}).get('type') != 'chatgpt':
                raise ValueError('原生续期未返回既有ChatGPT登录')
    try:
        await asyncio.wait_for(refresh_once(), min(timeout, 30))
        renewed, renewed_source, renewed_sha = external_auth(environment)
        renewed_expiry = access_expiry(renewed['accessToken'])
        if renewed_source != source or renewed['chatgptAccountId'] != auth['chatgptAccountId']:
            raise ValueError('原生续期账号发生变化')
        if renewed_expiry is None or renewed_expiry <= time.time() + 300:
            raise ValueError('原生续期后访问令牌仍不可确认有效期')
        refresh.update(completed=True, renewed_expiry=renewed_expiry, source_after_sha256=renewed_sha,
                       source_auth_changed=renewed_sha != before_sha)
        persist()
        return renewed, renewed_sha
    except Exception as error:
        refresh.update(completed=False, error_type=type(error).__name__)
        persist()
        raise ValueError('现有原生登录续期未通过；未启动模型，请核对Codex登录。') from None
    finally:
        await close_sessions(session_key)


def save_receipt(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix('.json.new')
    with pending.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.flush(); os.fsync(stream.fileno())
    os.replace(pending, path)


async def prepare_connection(request, command, receipt, persist, auth):
    async def reject(*args):
        raise HarnessError('后台只读任务不接受额外权限或人工问题')
    async with connection(request, command, lambda *args: None, reject) as rpc:
        if rpc.initialized is None:
            rpc.initialized = await rpc.call('initialize', {'clientInfo': {'name': 'easel-readonly', 'version': '1'},
                'capabilities': {'experimentalApi': True}})
            await rpc.send({'method': 'initialized'})
        await rpc.call('account/login/start', auth)
        account = await rpc.call('account/read', {'refreshToken': False})
        if (account.get('account') or {}).get('type') != 'chatgpt':
            raise ValueError('临时只读原生连接未核对原有登录；未启动模型。')
        inventory = await rpc.call('mcpServerStatus/list', {'limit': 100, 'detail': 'toolsAndAuthOnly'})
        features = await rpc.call('experimentalFeature/list', {'limit': 200})
        enabled = {row['name'] for row in features.get('data', []) if row.get('enabled')}
        critical = {'shell_tool', 'apps', 'plugins', 'hooks', 'image_generation', 'code_mode_host',
                    'browser_use', 'browser_use_external', 'computer_use', 'multi_agent', 'memories'}
        if inventory.get('data') or inventory.get('nextCursor') or features.get('nextCursor') or enabled & critical:
            raise ValueError('原生只读隔离未通过；未启动模型。')
        receipt['isolation'] = {'mcp_server_count': 0, 'critical_features_enabled': [],
            'unified_exec_engine_flag': 'unified_exec' in enabled, 'sandbox': 'read-only',
            'auth_mode': 'existing_access_token_only', 'refresh_token_supplied': False}
        user_agent = (rpc.initialized or {}).get('userAgent')
        if isinstance(user_agent, str):receipt['native_user_agent'] = user_agent[:240]
        receipt['preflight_methods'] = ['initialize', 'account/login/start', 'account/read',
                                         'mcpServerStatus/list', 'experimentalFeature/list']
        persist()


async def invoke(request, command, receipt, persist, *, adapter=None, preflight=True, auth=None):
    """A single upstream adapter call; it never retries or changes models."""
    output = []
    output_bytes = 0
    messages = {}
    message_bytes = 0
    started = asyncio.get_running_loop().time()

    def preserve_output():
        raw_stream = ''.join(output)
        receipt.update(raw_stream_sha256=sha(raw_stream.encode('utf-8')), raw_stream_text=raw_stream,
                       native_agent_messages=list(messages.values()))

    async def reject(*args):
        raise HarnessError('后台只读任务不接受额外权限或人工问题')

    try:
        if preflight:
            await asyncio.wait_for(prepare_connection(request, command, receipt, persist, auth), request.timeout)
        def emit(kind, text):
            nonlocal output_bytes
            if kind == 'token':
                output.append(text)
                output_bytes += len(text.encode('utf-8'))
                if output_bytes > 1_000_000:
                    raise ValueError('只读模型回执超过已批准字节上限')
        def bind(native_id):
            receipt['native_thread_id'] = native_id; persist()
        def accepted(native_id, turn_id):
            receipt.update(native_thread_id=native_id, native_turn_id=turn_id, status='accepted')
            persist()
        def agent_message(native_id, turn_id, item):
            nonlocal message_bytes
            if native_id != receipt.get('native_thread_id') or turn_id != receipt.get('native_turn_id'):
                raise ValueError('只读完整消息不属于已确认原生回合')
            identity, text, phase = item.get('id'), item.get('text'), item.get('phase')
            if not isinstance(identity, str) or not identity or not isinstance(text, str) or phase not in (None, 'commentary', 'partial_answer', 'final_answer'):
                raise ValueError('只读完整消息缺少准确身份、文字或阶段')
            row = {'id': identity, 'text': text, 'phase': phase}
            previous = messages.get(identity)
            message_bytes += len(text.encode('utf-8')) - (len(previous['text'].encode('utf-8')) if previous else 0)
            if message_bytes > 1_000_000:
                raise ValueError('只读完整消息超过已批准字节上限')
            messages[identity] = row
        request = RunRequest(**{**request.__dict__, 'on_native_turn': accepted, 'on_agent_message': agent_message})
        remaining = request.timeout - (asyncio.get_running_loop().time() - started)
        if remaining <= 0:raise asyncio.TimeoutError()
        await asyncio.wait_for((adapter or harnesses.adapter('codex')).run(request, emit, reject, bind), remaining)
        receipt['completion_received'] = True
        preserve_output()
        # The complete native item, rather than token concatenation, has the
        # same final-message boundary as legacy --output-last-message. Some
        # providers omit phase; retain compatibility for that last whole item.
        candidates = [item for item in messages.values() if item['phase'] == 'final_answer']
        if not candidates and messages:
            last = next(reversed(messages.values()))
            if last['phase'] is None:
                candidates = [last]
        if not candidates:
            persist()
            raise ValueError('原生模型完成但没有可确认的最终完整消息')
        selected = candidates[-1]
        raw = selected['text']
        receipt.update(model_output_item_id=selected['id'], model_output_phase=selected['phase'],
                       model_output_selection='final_answer' if selected['phase'] else 'last_complete_unphased_message')
        receipt.update(model_output_sha256=sha(raw.encode('utf-8')), model_output_text=raw)
        persist()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('只读模型未返回结构化对象')
        receipt.update(status='completed', model_output_sha256=sha(raw.encode('utf-8')), model_output_text=raw)
        persist()
        return value, raw
    except (asyncio.TimeoutError, HarnessError, ConnectionError) as error:
        preserve_output()
        receipt.update(status='unknown', error_type=type(error).__name__)
        with contextlib.suppress(OSError):persist()
        raise ReadonlyExecutionUnknown(receipt) from None
    except BaseException as error:
        preserve_output()
        receipt.update(status='failed' if receipt.get('completion_received') else 'unknown' if receipt.get('native_turn_id') else 'not_started', error_type=type(error).__name__)
        with contextlib.suppress(OSError):persist()
        if receipt.get('native_turn_id') and not receipt.get('completion_received'):
            raise ReadonlyExecutionUnknown(receipt) from None
        if receipt.get('completion_received'):
            raise ReadonlyOutputInvalid(receipt) from None
        raise
    finally:
        await close_sessions(request.session_key)


def run(snapshot, arguments, *, input, cwd, timeout, runner=None, runtime_root=None, task_id=None, **kwargs):
    if runner is not None or not project_snapshot(snapshot):
        return (runner or subprocess.run)(arguments, input=input, cwd=cwd, timeout=timeout, **kwargs)
    folder = Path(cwd).resolve(); prompt = input.decode('utf-8') if isinstance(input, bytes) else input
    if not isinstance(prompt, str):
        raise ValueError('只读调用需要准确UTF-8输入')
    output = Path(option(arguments, '--output-last-message') or folder / 'answer.json').resolve()
    schema_path = Path(option(arguments, '--output-schema') or folder / 'schema.json').resolve()
    if not output.is_relative_to(folder) or not schema_path.is_relative_to(folder) or output.exists():
        raise ValueError('只读调用结果或合同路径不属于本次临时目录')
    schema_raw = schema_path.read_bytes(); schema = json.loads(schema_raw)
    images = tuple(str(Path(arguments[index + 1]).resolve()) for index, value in enumerate(arguments[:-1]) if value == '--image')
    descriptors = [{'path': path, 'sha256': sha(Path(path).read_bytes())} for path in images]
    effort = None
    for index, value in enumerate(arguments[:-1]):
        if value == '-c' and arguments[index + 1].startswith('model_reasoning_effort='):
            effort = json.loads(arguments[index + 1].split('=', 1)[1])
    identity = uuid.uuid4().hex
    selected_root = runtime_root if isinstance(runtime_root, (str, os.PathLike)) else getattr(runtime_root, 'root', None)
    root = Path(selected_root or folder).resolve()
    receipt_path = root / 'data/readonly-receipts' / (identity + '.json')
    receipt = {'id': identity, 'task_id': task_id, 'runner': 'easel.harnesses.codex.CodexAdapter',
        'status': 'preparing', 'prompt_sha256': sha(prompt.encode('utf-8')), 'schema_sha256': sha(schema_raw),
        'requested_model': option(arguments, '--model') or '', 'actual_model': None, 'reasoning_effort': effort,
        'images': descriptors, 'ephemeral': True, 'sandbox': 'read-only', 'attempts': 1, 'timeout_seconds': timeout,
        'skill_refs': [{key: row[key] for key in ('id', 'version', 'sha256') if key in row} for row in snapshot['skills']],
        'receipt_path': str(receipt_path), 'notice': '程序记录原生ACK和实际提交参数；不把请求模型当作已核实实际模型。'}
    persist = lambda: save_receipt(receipt_path, receipt)
    persist()
    auth_source = None
    prepared_auth_sha256 = None
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix='easel-readonly-native-home-') as directory:
            home = Path(directory)
            environment = {key: value for key, value in (kwargs.get('env') or os.environ).items() if key.upper() not in ('OPENAI_API_KEY', 'CODEX_API_KEY')}
            existing = external_auth(environment)
            _, auth_source, auth_sha256 = existing
            auth, prepared_auth_sha256 = asyncio.run(prepare_external_auth(environment, folder, timeout, receipt, persist, existing))
            environment = proxy_environment(web_environment(environment), 'localhost,127.0.0.1,::1')
            environment['CODEX_HOME'] = str(home)
            command = base_command('codex') + ['app-server']
            for feature in DISABLED:
                command.extend(['--disable', feature])
            receipt['command'] = command
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise ValueError('原生认证准备超过本次时限；未启动模型。')
            request = RunRequest(prompt, folder, environment, model=receipt['requested_model'], sandbox='read-only',
                timeout=remaining, command=tuple(command), session_key='readonly-' + identity, frozen_instructions='',
                input_images=images, reasoning_effort=effort, output_schema=schema, ephemeral=True)
            value, raw = asyncio.run(invoke(request, command, receipt, persist, auth=auth))
            output.write_text(raw, encoding='utf-8')
    except BaseException as error:
        if receipt['status'] == 'preparing':receipt.update(status='not_started', error_type=type(error).__name__)
        with contextlib.suppress(OSError):persist()
        raise
    finally:
        if auth_source is not None:
            try:
                final_sha = sha(auth_source.read_bytes())
                receipt['source_auth_unchanged'] = final_sha == auth_sha256
                receipt['source_auth_unchanged_during_isolated_execution'] = (
                    final_sha == prepared_auth_sha256 if prepared_auth_sha256 is not None else None)
            except OSError:
                receipt['source_auth_unchanged'] = False
                receipt['source_auth_unchanged_during_isolated_execution'] = False
            with contextlib.suppress(OSError):persist()
    return SimpleNamespace(returncode=0, stdout='', stderr='', execution_receipt=copy.deepcopy(receipt))


def recorded_output(process, result):
    receipt = getattr(process, 'execution_receipt', None)
    return {'model_output': result, 'execution_receipt': receipt} if receipt else result
