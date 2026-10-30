"""TEMP-only checks for single-source native services and isolated host context."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from easel.web_services import accounts, settings


def test_hosts_reuse_native_code_without_sharing_configuration(tmp_path):
    one = settings.create_settings_context(tmp_path / 'one', {'OPENAI_API_KEY': 'one'},
                                          {'runtime': 'api'}, tmp_path / 'one.json')
    two = settings.create_settings_context(tmp_path / 'two', {'OPENAI_API_KEY': 'two'},
                                          {'runtime': 'codex'}, tmp_path / 'two.json')
    assert one.api_settings_models_save.__code__ is settings.api_settings_models_save.__code__
    assert two.api_settings_models_save.__code__ is one.api_settings_models_save.__code__
    assert one.api_settings_models_save.__globals__ is not two.api_settings_models_save.__globals__
    assert one.namespace['_read_env']()['OPENAI_API_KEY'] == 'one'
    assert two.namespace['_read_env']()['OPENAI_API_KEY'] == 'two'
    assert one.namespace['_harness_settings']()['runtime'] == 'api'
    assert two.namespace['_harness_settings']()['runtime'] == 'codex'


def test_native_aliases_keep_the_original_host_namespace():
    namespace = {'_read_env': lambda: {}, '_harness_settings': lambda: {'runtime': 'api'}}
    bound = settings.bind(into=namespace)
    assert bound._direct_api_enabled.__globals__ is namespace
    assert bound._direct_api_enabled()
    namespace['_harness_settings'] = lambda: {'runtime': 'codex'}
    assert not bound._direct_api_enabled()


def account_context(tmp_path, *, platform='wechat-oa', process_run=None):
    calls = []
    process = SimpleNamespace(poll=lambda: None, terminate=lambda: None)
    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        return process
    context = accounts.create_accounts_context(
        tmp_path, python=tmp_path / 'isolated-python.exe',
        scripts=tmp_path / 'frozen/skills/shared/scripts',
        environment={'PLAYWRIGHT_BROWSERS_PATH': 'project-browsers'},
        profile_base=lambda selected: tmp_path / 'profiles' / selected,
        process_factory=spawn, process_run=process_run,
        credential_store={'_wechat_web_account': lambda: {}},
    )
    return context, calls, process


def test_mp_login_subscribes_to_one_native_process(tmp_path):
    context, calls, _ = account_context(tmp_path)
    first = asyncio.run(context.api_mp_login_start('wechat-oa'))
    second = asyncio.run(context.api_mp_login_start('wechat-oa'))
    assert first['state'] == 'starting'
    assert second['state'] == 'unknown'
    assert len(calls) == 1
    command, options = calls[0]
    assert command[0] == str(tmp_path / 'isolated-python.exe')
    assert command[1] == str(tmp_path / 'frozen/skills/shared/scripts/weixin_mp_stats.py')
    assert command[-2:] == ['--profile-base', str(tmp_path / 'profiles/wechat-oa')]
    assert options['env']['PLAYWRIGHT_BROWSERS_PATH'] == 'project-browsers'
    assert not asyncio.run(context.api_accounts())[-1]['loggedIn']


def test_native_qr_status_and_early_exit_are_terminal(tmp_path):
    context, _, process = account_context(tmp_path)
    asyncio.run(context.api_mp_login_start('wechat-oa'))
    (context.LOGIN_DIR / 'wechat-oa-mp.png').write_bytes(b'TEMP QR')
    state = context.LOGIN_DIR / 'wechat-oa-mp.json'
    state.write_text(json.dumps({'state': 'qr_ready', 'message': 'scan'}), encoding='utf-8')
    qr = asyncio.run(context.api_mp_login_status('wechat-oa'))
    assert qr['state'] == 'qr_ready' and qr['qr'].endswith('.png')
    assert not asyncio.run(context.api_accounts())[-1]['loggedIn']
    state.write_text(json.dumps({'state': 'expired', 'message': 'unscanned'}), encoding='utf-8')
    assert asyncio.run(context.api_mp_login_status('wechat-oa'))['qr'] == ''
    state.unlink()
    process.poll = lambda: 2
    assert asyncio.run(context.api_mp_login_status('wechat-oa'))['state'] == 'error'


def test_host_context_does_not_share_login_cache_or_processes(tmp_path):
    one, _, _ = account_context(tmp_path / 'one')
    two, _, _ = account_context(tmp_path / 'two')
    one.LOGIN_PROCESSES['wechat-oa-mp'] = SimpleNamespace(poll=lambda: None)
    one._WHOAMI_CACHE['wechat-oa'] = (1, {'loggedIn': True})
    assert not two.LOGIN_PROCESSES and not two._WHOAMI_CACHE
    assert one.api_mp_login_start.__code__ is accounts.api_mp_login_start.__code__


def test_credentials_never_become_host_browser_login(tmp_path):
    context = accounts.create_accounts_context(
        tmp_path, credential_store={'_wechat_web_account': lambda: {
            'app_id': 'wx_api_only', 'app_secret': 'secret', 'name': 'API'}},
        process_run=lambda *a, **k: pytest.fail('credential fallback started browser'),
    )
    account = asyncio.run(context.api_accounts())[-1]
    whoami = asyncio.run(context.api_account_whoami('wechat-oa'))
    assert not account['loggedIn'] and not whoami['loggedIn']


def test_identity_preserves_only_the_optional_stable_account_id(tmp_path):
    def run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            'loggedIn': True, 'name': 'Own account', 'avatar': 'https://example.test/a.png',
            'provider_user_id': 'stable-own-id', 'token': 'MUST NOT LEAK', 'cookies': 'PRIVATE',
        }))
    context, _, _ = account_context(tmp_path, process_run=run)
    value = asyncio.run(context.api_account_whoami('xiaohongshu', force=True))
    assert value['loggedIn'] and value['provider_user_id'] == 'stable-own-id'
    assert 'token' not in value and 'cookies' not in value


def test_settings_and_account_body_definitions_have_one_source():
    import ast
    root = Path(__file__).resolve().parents[1]
    native = ast.parse((root / 'web/app.py').read_text(encoding='utf-8'))
    definitions = {node.name for node in native.body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    assert not {'api_settings_models_save', 'api_models_available', 'api_mp_login_start',
                '_check_account_whoami', '_model_channels'} & definitions
    assert not (root / 'easel_workbench/runtime/settings_upstream.py').exists()
    assert not (root / 'scripts/extract_workbench_settings.py').exists()


def test_native_shared_constants_have_one_source_and_keep_binding_identity():
    import ast
    from easel.web_services import outputs, planning

    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / 'web/app.py').read_text(encoding='utf-8'))
    assigned = {target.id for node in tree.body
                if isinstance(node, (ast.Assign, ast.AnnAssign))
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
                if isinstance(target, ast.Name)}
    sources = {
        accounts: ('LOGIN_RUNNERS',),
        outputs: ('SYSTEM_TOPLEVEL_DIRS', 'TEXT_EXTS', 'IMAGE_EXTS', 'VIDEO_EXTS',
                  'AUDIO_EXTS', 'PROTECTED_OUTPUTS'),
        planning: ('SCHEDULE_STATUSES', 'SCHEDULE_KINDS', 'IDEA_STATUSES'),
    }
    for module, names in sources.items():
        assert not set(names) & assigned
        native_namespace = {}
        module.bind(into=native_namespace)
        for name in names:
            assert native_namespace[name] is getattr(module, name)
