"""Prove native code reuse and reject a second UI/theme/backend implementation."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import runpy
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
GUARDS=runpy.run_path(str(ROOT/'tests/test_workbench_architecture.py'))


def inspect(function,payload):
    module=(ROOT/'scripts/audit_easel_base.mjs').as_uri()
    code=(f"import * as audit from {json.dumps(module)};"
          "let input='';for await(const chunk of process.stdin)input+=chunk;"
          f"console.log(JSON.stringify(audit.{function}(...JSON.parse(input))));")
    result=subprocess.run([GUARDS['node24'](),'--input-type=module','-e',code],
                          input=json.dumps(payload),text=True,encoding='utf-8',
                          capture_output=True,check=True,cwd=ROOT,timeout=30)
    return json.loads(result.stdout)


def test_actual_native_application_is_the_only_shared_frame():
    source=(ROOT/'web/frontend/src/App.tsx').read_text(encoding='utf-8')
    assert not inspect('inspectFrame',[source])
    native=(ROOT/'web/frontend/src/workbench/ui/index.tsx').read_text(encoding='utf-8')
    assert not inspect('inspectNativeUse',[native,'App','../../App','workbench/ui/index.tsx'])


def test_frame_guard_rejects_parallel_shells_and_missing_default_native_app():
    source='''
function ApplicationFrame(){return <div className="app-layout"/>}
function NativeApp(){return <div className="app-layout"/>}
function App(){return <ApplicationFrame/>}
'''
    rules={item['rule'] for item in inspect('inspectFrame',[source])}
    assert 'one-native-application-frame' in rules
    assert 'native-default-app-must-remain' in rules
    assert 'native-default-must-use-shared-frame' in rules


def test_native_usage_guard_checks_real_import_and_jsx_nodes():
    source='''
// import AccountsPage from '../../components/AccountsPage';
const documentation="<AccountsPage/>";
export function Accounts(){return <AccountCard/>}
function AccountCard(){return <button>login</button>}
'''
    rules={item['rule'] for item in inspect('inspectNativeUse',[
        source,'AccountsPage','../../components/AccountsPage','PlatformAccounts.tsx'])}
    assert {'native-component-must-be-rendered','parallel-account-component',
            'account-ui-must-remain-native'}<=rules
    actual=(ROOT/'web/frontend/src/workbench/ui/PlatformAccounts.tsx').read_text(encoding='utf-8')
    assert not inspect('inspectNativeUse',[actual,'AccountsPage','../../components/AccountsPage','PlatformAccounts.tsx'])
    duplicate="import App from '../../App';function Host(){return <div className='app-layout'><Sidebar/><App/></div>}"
    assert any(value['rule']=='host-cannot-rebuild-native-frame' for value in
               inspect('inspectNativeUse',[duplicate,'App','../../App','host.tsx']))


@pytest.mark.parametrize('source',[
    'body{font-size:18px}',
    '.account-card{padding:30px}',
    '.ew-page .account-card{padding:30px}',
    '.ew-form,.sidebar{color:red}',
    '@media(max-width:800px){.ew-page .btn{font-size:18px}}',
    '.ew-settings-host .panel{color:red}',
    '.ew-main .card{padding:30px}',
])
def test_extension_styles_reject_common_component_overrides(source):
    assert inspect('inspectExtensionCss',[source])


def test_extension_styles_allow_only_owned_elements_and_keyframes():
    source='''.ew-work-preview{padding:12px}.ew-copy-area textarea{resize:vertical}
.ew-toolbar>.field{width:100%}.ew-work-chat .chat-page{min-height:440px}
@media(max-width:800px){.ew-work-grid{display:block}}
@keyframes private-spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}'''
    assert not inspect('inspectExtensionCss',[source])
    actual=(ROOT/'web/frontend/src/workbench/ui/styles/workbench.css').read_text(encoding='utf-8')
    assert not inspect('inspectExtensionCss',[actual])


def test_host_viewport_cannot_introduce_a_second_font_system():
    assert inspect('inspectHostCss',['body{font-family:another;font-size:18px}'])
    assert inspect('inspectHostCss',['body{color:red;background:black}'])
    assert not inspect('inspectHostCss',['body,#root{height:100dvh}.native-host-notice{font-size:14px}'])
    actual=(ROOT/'web/frontend/src/workbench/host.css').read_text(encoding='utf-8')
    assert not inspect('inspectHostCss',[actual])


def test_official_source_manifest_and_native_build_remain_verifiable():
    report=inspect('auditEaselBase',[str(ROOT)])
    assert report['passed'],report['violations']
    assert report['upstream_commit']=='5a597e5f3ef5b01098b53f36caf719dd9a32b7bf'


def test_shared_backend_has_no_private_dependencies_or_runtime_source_copies():
    forbidden=[]
    for file in (ROOT/'easel/web_services').glob('*.py'):
        source=file.read_text(encoding='utf-8')
        forbidden.extend(GUARDS['upstream_private_edges'](source,file.relative_to(ROOT).as_posix()))
        tree=ast.parse(source)
        assert not any(isinstance(node,ast.Call) and isinstance(node.func,ast.Name)
                       and node.func.id in ('exec','eval','compile') for node in ast.walk(tree)),file.name
    assert not forbidden,forbidden
    native=ast.parse((ROOT/'web/app.py').read_text(encoding='utf-8'))
    native_names={node.name for node in native.body
                  if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
    assert not {'api_mp_login_start','api_settings_models_save','api_ideas_create',
                'api_schedule_create','api_output'}&native_names


def test_neutral_modules_still_reject_reverse_dependency_injection():
    for source in ('import easel_workbench.settings',
                   'from easel_workbench.runtime import native_api',
                   'importlib.import_module("easel_workbench.chat")'):
        assert GUARDS['upstream_private_edges'](source,'easel/web_services/accounts.py')
