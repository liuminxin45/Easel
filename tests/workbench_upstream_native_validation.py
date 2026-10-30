"""Opt-in 0-model checks using Easel's actual upstream command and RPC pool."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def probe(root):
    from easel.direct_api import read_settings
    from easel.harnesses.base import HarnessError, RunRequest
    from easel.harnesses.commands import base_command
    from easel.harnesses.rpc import connection, close_sessions
    from easel.runtime_env import proxy_environment, web_environment
    from easel_workbench.skill_catalog import ProjectSkillCatalog

    environment = proxy_environment(web_environment(read_settings(root / '.env')), 'localhost,127.0.0.1,::1')
    command = base_command('codex')
    version = subprocess.check_output([*command, '--version'], text=True, encoding='utf-8').strip()
    schemas = {}
    with tempfile.TemporaryDirectory(prefix='easel-upstream-native-schema-') as directory:
        subprocess.run([*command, 'app-server', 'generate-json-schema', '--experimental', '--out', directory],
                       check=True, capture_output=True, timeout=30)
        for name in ('GetAccountParams.json', 'ModelListParams.json', 'SkillsListParams.json', 'ThreadReadParams.json'):
            paths = list(Path(directory).rglob(name))
            if paths:
                schema = json.loads(paths[0].read_text(encoding='utf-8'))
                schemas[name] = {'sha256': digest(paths[0]), 'properties': sorted(schema.get('properties', {}))}
        assert 'refreshToken' in schemas['GetAccountParams.json']['properties']
        assert 'includeTurns' in schemas['ThreadReadParams.json']['properties']
    allowed = {'initialize', 'initialized', 'account/read', 'model/list', 'thread/start',
               'thread/read', 'thread/loaded/list', 'skills/list', 'experimentalFeature/list'}
    methods, notifications, reverse = [], [], []
    request = RunRequest('', root, environment, session_key='zero-probe-' + uuid.uuid4().hex)
    report = {'command': command + ['app-server'], 'cli_version': version, 'cwd': str(root),
              'runner': 'easel.harnesses.rpc.connection', 'model_calls': 0, 'queue_writes': 0,
              'production_database_writes': 0, 'business_session_binding_writes': 0, 'schemas': schemas}

    async def reject(method, params):
        reverse.append(method)
        raise HarnessError('Zero-model probe never approves reverse requests')

    def notify(method, params):
        notifications.append(method)

    try:
        async with connection(request, command + ['app-server'], notify, reject) as rpc:
            original_send = rpc.send

            async def safe_send(message):
                method = message.get('method')
                if method is not None:
                    assert method in allowed, 'Forbidden model/queue method in native validation'
                    methods.append(method)
                return await original_send(message)

            rpc.send = safe_send
            await rpc.call('initialize', {'clientInfo': {'name': 'easel-zero-model-probe', 'version': '1'},
                                          'capabilities': {'experimentalApi': True}})
            await rpc.send({'method': 'initialized'})
            account = await rpc.call('account/read', {'refreshToken': False})
            value = account.get('account')
            report['account'] = {'read_succeeded': True, 'type': value.get('type') if isinstance(value, dict) else None,
                                 'requires_openai_auth': account.get('requiresOpenaiAuth'),
                                 'needs_auth_derived': bool(account.get('requiresOpenaiAuth') and value is None)}
            models = await rpc.call('model/list', {'limit': 100, 'includeHidden': False})
            report['model_catalog'] = {'read_succeeded': True, 'visible_count': len(models.get('data') or []),
                                       'default_present': any(item.get('isDefault') for item in models.get('data') or []),
                                       'not_an_inference_entitlement_test': True}
            result = await rpc.call('thread/start', {'cwd': str(root), 'ephemeral': False})
            thread = result.get('thread') or {}; identity = thread['id']
            assert Path(thread['cwd']).resolve() == root and not thread.get('turns')
            report['thread_id'] = identity
            report['same_connection_loaded'] = identity in (await rpc.call('thread/loaded/list', {})).get('data', [])
            read = (await rpc.call('thread/read', {'threadId': identity, 'includeTurns': False}))['thread']
            assert read['id'] == identity and not read.get('turns')
            report['thread_read_without_turns_succeeded'] = True
            # Save the exact known protocol limitation as a diagnostic. It is
            # a read request, never an attempted model execution.
            try:
                await rpc.call('thread/read', {'threadId': identity, 'includeTurns': True})
                report['history_enumeration'] = {'supported': True}
            except HarnessError as error:
                report['history_enumeration'] = {'supported': False, 'error_type': type(error).__name__,
                    'known_list_turns_not_supported': 'list_turns is not supported' in str(error)}
            try:
                params = {'cwds': [str(root)]} if 'cwds' in schemas.get('SkillsListParams.json', {}).get('properties', []) else {}
                skills = await rpc.call('skills/list', params)
                groups = skills.get('data') or []
                flattened = [item for group in groups for item in group.get('skills', [])]
                report['native_skills'] = {'read_succeeded': True, 'group_count': len(groups), 'count': len(flattened),
                    'project_builtin_count': sum(Path(item.get('path', '')).resolve().is_relative_to(root / 'skills/builtin')
                                                 for item in flattened if item.get('path')),
                    'discovery_error_count': sum(len(group.get('errors') or []) for group in groups)}
            except HarnessError as error:
                report['native_skills'] = {'read_succeeded': False, 'error_type': type(error).__name__}
            features = await rpc.call('experimentalFeature/list', {'threadId': identity, 'limit': 200})
            report['tool_features'] = [{key: item.get(key) for key in ('name', 'enabled', 'stage')}
                for item in features.get('data') or [] if item.get('name') in ('image_generation', 'view_image', 'shell_tool', 'unified_exec', 'code_mode_host')]
            process = rpc.process
            first = rpc
        # Real upstream pool ownership keeps the same empty native process
        # available between calls; this does not bind a business session.
        async with connection(request, command + ['app-server'], notify, reject) as rpc:
            report['reused_same_rpc'] = rpc is first
            report['pool_connection_still_alive'] = rpc.process.returncode is None
            report['reused_connection_loaded'] = identity in (await rpc.call('thread/loaded/list', {})).get('data', [])
        report['easel_project_builtin_catalog_count'] = len(ProjectSkillCatalog(root).entries())
        report['limitations'] = ['No model turn, image generation, local tool execution or deliverable was attempted.',
                                 'Native skills/list and Easel project builtin filesystem catalog are different discovery mechanisms.']
        report['passed'] = bool(report['same_connection_loaded'] and report['thread_read_without_turns_succeeded']
                                 and report['reused_same_rpc'] and report['reused_connection_loaded']
                                 and not report['account']['needs_auth_derived'] and report['model_catalog']['visible_count'])
    finally:
        await close_sessions(request.session_key)
        report['probe_session_pool_closed'] = True
    report['process_closed'] = process.returncode is not None
    report['methods'] = methods
    report['notification_methods'] = sorted(set(notifications))
    report['reverse_request_methods'] = sorted(set(reverse))
    assert all(not method.startswith(('turn/', 'thread/queue/')) for method in methods)
    report['source_sha256'] = {name: digest(root / name) for name in ('easel/harnesses/base.py',
        'easel/harnesses/commands.py', 'easel/harnesses/rpc.py', 'easel/harnesses/workspace.py')}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--backend',type=Path)
    options = parser.parse_args(); root = options.root.resolve(); sys.path.insert(0, str(root))
    backend=options.backend.resolve() if options.backend else None
    if backend:
        package=json.loads((backend/'workbench-release.json').read_text(encoding='utf-8'))
        assert all(digest(backend/name)==expected for name,expected in package['files'].items())
        sys.path.insert(0,str(backend))
    result = asyncio.run(probe(root)); result['harness_sha256'] = digest(Path(__file__).resolve())
    if backend:
        from easel.harnesses import codex,rpc,workspace
        assert all(Path(module.__file__).resolve().is_relative_to(backend) for module in (codex,rpc,workspace))
        result['backend']={'release':package['release'],'manifest_sha256':digest(backend/'workbench-release.json')}
        assert all(digest(backend/name)==expected for name,expected in package['files'].items())
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('passed', 'command', 'cli_version', 'account', 'model_catalog',
        'same_connection_loaded', 'reused_same_rpc', 'process_closed', 'tool_features', 'native_skills')}, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
