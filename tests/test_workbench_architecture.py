"""Dependency guards for the private extension, with real AST negative controls.

These checks do not import application modules, create jobs, or contact models.
The TypeScript check uses the installed compiler's syntax tree, not grep.
"""
from __future__ import annotations

import ast
from functools import lru_cache
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
PRIVATE_PREFIX='easel_workbench'
FRONTEND=ROOT/'web/frontend/src'
PRIVATE_UI=FRONTEND/'workbench'
UPSTREAM_PATCH_ALLOWLIST={'easel/cli.py','web/frontend/package.json',
    # Optional host settings ports and native CLI/ACP receipt callbacks.
    'easel/harnesses/acp.py','easel/harnesses/rpc.py','easel/harnesses/openclaw.py',
    'web/frontend/src/components/SettingsPanel.tsx','web/frontend/src/components/HarnessSettings.tsx',
    'web/frontend/src/components/SettingsApi.ts','web/frontend/src/components/EnvBoard.tsx',
    # Shared accessible settings control; no private service imports.
    'web/frontend/src/components/SettingsSelect.tsx','web/frontend/src/components/SettingsSelect.css',
    'web/frontend/package-lock.json','web/frontend/tsconfig.app.json',
    # Optional generic turn receipt/frozen instruction ports; defaults remain upstream-owned.
    'easel/harnesses/base.py','easel/harnesses/codex.py','easel/harnesses/workspace.py',
    # Generic optional view ports; these files may not import private services.
    'web/frontend/src/components/ChatPage.tsx','web/frontend/src/components/MessageBubble.tsx',
    'web/frontend/src/components/Sidebar.tsx','web/frontend/src/components/SkillPage.tsx',
    'web/frontend/src/components/QuestionCards.tsx','web/frontend/src/components/SkillDrawer.tsx',
    'web/frontend/src/lib/api.ts','web/frontend/src/lib/artifacts.ts',
    # Reviewed generic feedback projection; contains no private dependencies or I/O.
    'web/frontend/src/lib/interaction.ts',
    'web/frontend/src/components/InteractionNotice.tsx',
    # Generic capability catalog and authorized artifact presentation ports.
    'web/frontend/src/components/BrushEntry.tsx','web/frontend/src/components/ArtifactGallery.tsx'}
UPSTREAM_PATCH_ALLOWLIST.update({'web/frontend/src/components/TrendsPage.tsx',
    'web/frontend/src/components/TrendsView.tsx','web/frontend/src/components/TrendSourcesDialog.tsx',
    'web/frontend/src/components/DashboardPage.tsx','web/frontend/src/styles/index.css'})
# Shared, I/O-free board presentation; private data ports stay in workbench/.
UPSTREAM_PATCH_ALLOWLIST.update({'web/frontend/src/components/IdeasPage.tsx',
    'web/frontend/src/components/IdeasView.tsx'})
# Reviewed single-source services and generic optional host ports. Each file is
# named: neighboring components and new execution modules remain protected.
UPSTREAM_PATCH_ALLOWLIST.update({
    'web/app.py', 'web/frontend/src/App.tsx',
    'easel/web_services/__init__.py', 'easel/web_services/binding.py',
    'easel/web_services/accounts.py', 'easel/web_services/settings.py',
    'easel/web_services/planning.py', 'easel/web_services/outputs.py',
    'easel/web_services/environment.py',
    'easel/web_services/analytics.py',
    'web/frontend/src/components/ThemeToggle.tsx',
    'web/frontend/src/components/OutputsPage.tsx',
    'web/frontend/src/components/ProfilePage.tsx',
    'web/frontend/src/components/BreakdownPage.tsx',
    'web/frontend/src/components/PublishingPage.tsx',
    'web/frontend/src/components/ManualPublishPage.tsx',
    'web/frontend/src/components/CopyableText.tsx',
    'web/frontend/src/components/TextArtifact.tsx',
    # Optional in-memory host cache; native account logic remains shared.
    'web/frontend/src/lib/whoami.ts',
    'web/frontend/src/styles/theme.css',
    # Restore the exact official stylesheet entry, dropping the fork-only import.
    'web/frontend/src/index.css',
    # Stable account IDs are returned once by the actual native drivers.
    'skills/shared/scripts/bili_login.py',
    'skills/shared/scripts/douyin_publish.py',
    'skills/shared/scripts/web_publisher.py',
    'skills/shared/scripts/weixin_mp_stats.py',
    'skills/shared/scripts/xhs_publish.py',
    # Generic explicit runtime root and analytics directory, with native defaults.
    'skills/shared/scripts/account_stats.py',
})
WORKBENCH_BUILTIN_IDS={'content-production','topic-research','content-writing','image-production',
    'reference-analysis','delivery-review','publication-analysis','experience-distillation'}


def allowed_upstream_patch(relative):
    if relative in UPSTREAM_PATCH_ALLOWLIST or relative.startswith('web/frontend/src/workbench/'):
        return True
    if relative=='skills/workbench-import.json' or relative.startswith('skills/shared/workbench/'):
        return True
    parts=Path(relative).parts
    return len(parts)>3 and parts[:2]==('skills','builtin') and parts[2] in WORKBENCH_BUILTIN_IDS


def python_edges(source):
    """Return real import/known module-launch edges and their function scope."""
    tree=ast.parse(source)
    result=[]
    def literal(node):
        if isinstance(node,ast.Constant) and isinstance(node.value,str):return node.value
        if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Add):
            left,right=literal(node.left),literal(node.right)
            if left is not None and right is not None:return left+right
        return None
    def visit(node,scope=''):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):scope=node.name
        if isinstance(node,ast.Import):
            result.extend((a.name,'import',scope,node.lineno) for a in node.names)
        elif isinstance(node,ast.ImportFrom):
            result.append(('.'*node.level+(node.module or ''),'import',scope,node.lineno))
            prefix='.'*node.level+((node.module+'.') if node.module else '')
            result.extend((prefix+a.name,'import',scope,node.lineno) for a in node.names if a.name!='*')
        elif isinstance(node,ast.Call):
            name=getattr(node.func,'id',None) or getattr(node.func,'attr',None)
            if name in ('__import__','import_module') and node.args:
                target=literal(node.args[0])
                if target is not None:result.append((target,'dynamic',scope,node.lineno))
        elif isinstance(node,(ast.List,ast.Tuple)):
            values=[n.value if isinstance(n,ast.Constant) and isinstance(n.value,str) else None for n in node.elts]
            for n,value in enumerate(values[:-1]):
                if value=='-m' and values[n+1]:result.append((values[n+1],'module-command',scope,node.lineno))
        for child in ast.iter_child_nodes(node):visit(child,scope)
    visit(tree)
    return result


def upstream_private_edges(source,relative):
    errors=[]
    for name,kind,scope,line in python_edges(source):
        if name!=PRIVATE_PREFIX and not name.startswith(PRIVATE_PREFIX+'.'):continue
        allowed=(relative=='easel/cli.py' and name=='easel_workbench.entry'
                 and kind=='module-command' and scope=='cmd_web')
        if not allowed:errors.append((relative,line,name,kind,scope))
    return errors


POLICY_FORBIDDEN=('runtime','easel_workbench.runtime','easel_workbench.collectors',
    'easel_workbench.application','easel_workbench.entry','easel_workbench.processes',
    'easel_workbench.supervisor','requests','httpx','urllib','http','socket','aiohttp',
    'subprocess','multiprocessing','os','sys','asyncio','importlib','openai','anthropic',
    'easel.harnesses','easel.direct_api','sqlite3','sqlalchemy')


def policy_edges(source):
    errors=[]
    for name,kind,scope,line in python_edges(source):
        normalized=name.lstrip('.')
        if any(normalized==blocked or normalized.startswith(blocked+'.') for blocked in POLICY_FORBIDDEN):
            errors.append((line,name,kind))
    return errors


@lru_cache(maxsize=1)
def node24():
    preferred=Path(os.environ.get('LOCALAPPDATA',''))/'nvm/v24.19.0/node.exe'
    path=preferred if preferred.is_file() else Path(shutil.which('node') or '')
    assert path.is_file(),'Node 24.19.0 must be installed for the TypeScript AST guard'
    assert subprocess.check_output([str(path),'--version'],text=True).strip()=='v24.19.0'
    return str(path)


TS_AST=r'''
const fs=require('node:fs');
const ts=require(process.argv[1]);
const files=JSON.parse(fs.readFileSync(0,'utf8'));
const literal=n=>ts.isStringLiteralLike(n)?n.text:
 ts.isBinaryExpression(n)&&n.operatorToken.kind===ts.SyntaxKind.PlusToken&&literal(n.left)!==null&&literal(n.right)!==null?literal(n.left)+literal(n.right):null;
const results=[];
for(const input of files){
 const source=ts.createSourceFile(input.path,input.source,ts.ScriptTarget.Latest,true,input.path.endsWith('.tsx')?ts.ScriptKind.TSX:ts.ScriptKind.TS);
 const edges=[];
 const add=(node,value,kind)=>{const specifier=literal(value);if(specifier!==null)edges.push({specifier,kind,line:source.getLineAndCharacterOfPosition(node.getStart(source)).line+1});};
 const walk=node=>{
  if((ts.isImportDeclaration(node)||ts.isExportDeclaration(node))&&node.moduleSpecifier)add(node,node.moduleSpecifier,ts.isImportDeclaration(node)?'import':'export');
  if(ts.isCallExpression(node)&&node.arguments.length&&
     (node.expression.kind===ts.SyntaxKind.ImportKeyword||ts.isIdentifier(node.expression)&&node.expression.text==='require'))add(node,node.arguments[0],'dynamic');
  ts.forEachChild(node,walk);
 };
 walk(source);results.push({path:input.path,edges});
}
process.stdout.write(JSON.stringify(results));
'''


def typescript_edges(inputs):
    compiler=ROOT/'web/frontend/node_modules/typescript/lib/typescript.js'
    assert compiler.is_file(),'Run npm ci in web/frontend before architecture checks'
    result=subprocess.run([node24(),'-e',TS_AST,str(compiler)],input=json.dumps(inputs),
        text=True,encoding='utf-8',capture_output=True,check=True,timeout=30)
    return json.loads(result.stdout)


def private_ts_edge(relative,specifier):
    if specifier.startswith('@workbench/'):return True
    if specifier.startswith('.'):
        resolved=(FRONTEND/relative).parent/specifier
        return resolved.resolve().is_relative_to(PRIVATE_UI.resolve())
    return False


def test_upstream_python_does_not_import_or_launch_private_features():
    files=[*ROOT.joinpath('easel').rglob('*.py'),ROOT/'web/app.py',*ROOT.joinpath('skills').rglob('*.py')]
    violations=[]
    for path in files:
        if '__pycache__' in path.parts:continue
        raw=path.read_bytes()
        # Parse only potential private edges; ordinary third-party Python files
        # remain upstream's responsibility, including version-specific syntax.
        if PRIVATE_PREFIX.encode('ascii') not in raw:continue
        source=raw.decode('utf-8-sig')
        violations.extend(upstream_private_edges(source,path.relative_to(ROOT).as_posix()))
    assert not violations,violations


def test_upstream_patch_surface_is_explicit_and_small():
    baseline=json.loads((ROOT/'docs/workbench/import-baseline.json').read_text(encoding='utf-8'))['easel_base']
    protected=['easel','web/app.py','web/frontend/src','web/frontend/package.json',
        'web/frontend/package-lock.json','web/frontend/tsconfig.app.json','agents','skills']
    git=shutil.which('git')
    assert git,'Git is required to verify the upstream patch surface'
    changed=subprocess.check_output([git,'diff','--name-only','-z',baseline,'--',*protected],cwd=ROOT)
    untracked=subprocess.check_output([git,'ls-files','--others','--exclude-standard','-z','--',*protected],cwd=ROOT)
    paths={p.decode('utf-8') for p in changed.split(b'\0')+untracked.split(b'\0') if p}
    unexpected=sorted(p for p in paths if not allowed_upstream_patch(p))
    assert not unexpected,('Unexpected upstream edits; review them explicitly rather than spreading private logic into upstream files',unexpected)


def test_project_skill_patch_allowlist_rejects_neighboring_upstream_and_global_sources():
    assert allowed_upstream_patch('skills/builtin/content-production/SKILL.md')
    assert allowed_upstream_patch('skills/builtin/delivery-review/scripts/check_deliverables.py')
    assert allowed_upstream_patch('skills/shared/workbench/规范/写作要求.md')
    assert allowed_upstream_patch('skills/workbench-import.json')
    assert not allowed_upstream_patch('skills/builtin/ai-image-gen/SKILL.md')
    assert not allowed_upstream_patch('skills/shared/scripts/new_executor.py')
    assert allowed_upstream_patch('skills/shared/scripts/account_stats.py')
    assert not allowed_upstream_patch('skills/shared/scripts/account_stats_private.py')
    assert not allowed_upstream_patch('skills/workbench-import-other.json')
    assert allowed_upstream_patch('web/frontend/src/App.tsx')
    assert not allowed_upstream_patch('web/frontend/src/PrivateApp.tsx')
    assert not allowed_upstream_patch('web/frontend/src/components/PrivateAccountsPage.tsx')
    assert not allowed_upstream_patch('easel/web_services/private_transport.py')
    assert not allowed_upstream_patch('easel/harnesses/new_private_runtime.py')


@pytest.mark.parametrize('source',[
    'import easel_workbench.runtime',
    'from easel_workbench import collectors',
    'import importlib\nimportlib.import_module("easel_workbench.collectors")',
    'importlib.import_module("easel_" + "workbench.collectors")',
    '__import__("easel_workbench.entry")',
    'subprocess.run(["python", "-m", "easel_workbench.entry"])',
])
def test_python_guard_rejects_actual_reverse_dependencies(source):
    assert upstream_private_edges(source,'easel/harnesses/codex.py')


def test_cli_exception_is_only_the_named_profile_module_entry():
    assert not upstream_private_edges('def cmd_web(args):\n subprocess.run(["python","-m","easel_workbench.entry"])','easel/cli.py')
    assert upstream_private_edges('def cmd_web(args):\n import easel_workbench.runtime','easel/cli.py')
    assert upstream_private_edges('def other(args):\n subprocess.run(["python","-m","easel_workbench.entry"])','easel/cli.py')


def test_original_frontend_does_not_depend_on_private_pages_or_state():
    inputs=[]
    for path in FRONTEND.rglob('*'):
        if path.suffix not in ('.ts','.tsx') or path.is_relative_to(PRIVATE_UI):continue
        inputs.append({'path':path.relative_to(FRONTEND).as_posix(),'source':path.read_text(encoding='utf-8-sig')})
    violations=[(file['path'],edge) for file in typescript_edges(inputs) for edge in file['edges']
                if private_ts_edge(file['path'],edge['specifier'])]
    assert not violations,violations


def test_typescript_guard_uses_real_import_export_dynamic_nodes():
    code='''
// import fake from '@workbench/core';
const documentation="import('@workbench/core')";
import actual from '@workbench/core';
export {EaselWorkbench} from './workbench/ui';
const lazy=()=>import('./workbench/'+'host');
'''
    edges=typescript_edges([{'path':'App.tsx','source':code}])[0]['edges']
    assert len(edges)==3
    assert all(private_ts_edge('App.tsx',edge['specifier']) for edge in edges)
    assert {edge['kind'] for edge in edges}=={'import','export','dynamic'}


@pytest.mark.parametrize('source',[
    'from easel_workbench.runtime import task_runtime',
    'from easel_workbench import runtime',
    'from . import runtime',
    'from .runtime import desk',
    'import httpx',
    'import urllib.request',
    'import subprocess',
    'import os',
    'import openai',
    '__import__("requests")',
])
def test_skill_policy_guard_rejects_io_execution_and_model_dependencies(source):
    assert policy_edges(source)


def test_skill_policy_guard_allows_data_only_contracts():
    assert not policy_edges('from dataclasses import dataclass\nfrom typing import Mapping\nimport json\n')


def test_actual_skill_policy_remains_independent_of_runtime_and_external_io():
    policy=ROOT/'easel_workbench/skills.py'
    assert policy.is_file(),'The data-only skill policy must be an explicit extension module'
    assert not policy_edges(policy.read_text(encoding='utf-8'))


def test_nine_source_identity_registries_have_not_drifted():
    canonical=json.loads((ROOT/'sources.json').read_text(encoding='utf-8'))
    compatibility=json.loads((ROOT/'easel_workbench/runtime/sources.json').read_text(encoding='utf-8'))
    configured=json.loads((ROOT/'config/workbench-trend-sources.example.json').read_text(encoding='utf-8'))
    identifiers=[row['id'] for row in configured['sources']]
    assert len(identifiers)==len(set(identifiers))==9
    assert set(identifiers)==set(canonical)==set(compatibility)
    assert canonical==compatibility,'Runtime fallback metadata must match the canonical source registry'
    assert all(row['label']==canonical[row['id']]['name'] for row in configured['sources'])
    assert configured['include_builtin'] is False
    assert all(row['type']=='python' and row['args']==['--source',row['id']] for row in configured['sources'])


CONNECTION_MODULES=('easel_accounts','easel_connection_support','easel_publish_worker')
MEDIA_EXECUTION_MODULES=('easel_workbench.runtime.easel_media_worker','easel_workbench.runtime.media_environment')


def connection_media_edges(source):
    return [(line,name,kind) for name,kind,scope,line in python_edges(source)
            if any(name==blocked or name.startswith(blocked+'.') for blocked in MEDIA_EXECUTION_MODULES)]


def test_connection_and_publisher_do_not_load_retired_media_execution_or_installation():
    errors=[]
    for name in CONNECTION_MODULES:
        path=ROOT/'easel_workbench/runtime'/f'{name}.py'
        errors.extend((name,*edge) for edge in connection_media_edges(path.read_text(encoding='utf-8')))
    assert not errors,errors


def test_connection_guard_detects_the_original_safe_env_reverse_dependency():
    assert connection_media_edges('from easel_workbench.runtime.easel_media_worker import safe_env')
    assert connection_media_edges('from easel_workbench.runtime.media_environment import Environment')
    assert connection_media_edges('from easel_workbench.runtime import easel_media_worker')
    assert connection_media_edges('importlib.import_module("easel_workbench.runtime.easel_media_worker")')
    assert not connection_media_edges('from easel_workbench.runtime.easel_connection_support import safe_env')
    # Historical read adapters remain supported; this is deliberately not a
    # global ban of easel_integration or every module with a media-related name.
    assert not connection_media_edges('from easel_workbench.runtime.easel_integration import service')


def test_connection_environment_drops_unrelated_credentials_and_isolates_host_paths(tmp_path,monkeypatch):
    from easel_workbench.runtime.easel_connection_support import safe_env
    parent={'PATH':'C:/approved/bin','SYSTEMROOT':'C:/Windows','TEMP':str(tmp_path/'temp'),
        'HTTPS_PROXY':'http://127.0.0.1:7890','OPENAI_API_KEY':'synthetic-parent-key',
        'MODEL_API_KEY':'synthetic-model-key','RANDOM_SECRET_TOKEN':'synthetic-secret',
        'HOME':'C:/other-home','USERPROFILE':'C:/other-user','EASEL_CONFIG_DIR':'C:/other-config'}
    monkeypatch.setattr(os,'environ',parent)
    directory=tmp_path/'connection-owner'
    result=safe_env({'EXPLICIT_PAYLOAD_KEY':'synthetic-explicit-value'},directory)
    assert result['PATH']==parent['PATH'] and result['HTTPS_PROXY']==parent['HTTPS_PROXY']
    assert result['EXPLICIT_PAYLOAD_KEY']=='synthetic-explicit-value'
    assert not {'OPENAI_API_KEY','MODEL_API_KEY','RANDOM_SECRET_TOKEN'}&result.keys()
    assert all(result[name]==str(directory) for name in ('HOME','USERPROFILE','EASEL_ROOT','EASEL_CONFIG_DIR'))
    assert result['PYTHONUTF8']=='1' and result['PYTHONIOENCODING']=='utf-8'


@pytest.mark.parametrize('root_value',[None,'','relative/data'])
def test_frozen_runtime_refuses_missing_or_relative_business_root_without_creating_data(tmp_path,monkeypatch,root_value):
    monkeypatch.setenv('AI_DESK_RELEASE','workbench-synthetic')
    if root_value is None:monkeypatch.delenv('AI_DESK_PROJECT_ROOT',raising=False)
    else:monkeypatch.setenv('AI_DESK_PROJECT_ROOT',root_value)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError,match='绝对路径'):
        runpy.run_path(str(ROOT/'easel_workbench/runtime/project_paths.py'))
    assert not list(tmp_path.iterdir())


def test_frozen_runtime_uses_only_explicit_absolute_root_without_writing_it(tmp_path,monkeypatch):
    selected=tmp_path/'explicit-owner'
    monkeypatch.setenv('AI_DESK_RELEASE','workbench-synthetic')
    monkeypatch.setenv('AI_DESK_PROJECT_ROOT',str(selected.resolve()))
    result=runpy.run_path(str(ROOT/'easel_workbench/runtime/project_paths.py'))
    assert result['ROOT']==selected.resolve()
    assert not selected.exists()


def test_source_development_retains_legacy_root_fallback(tmp_path,monkeypatch):
    module=ROOT/'easel_workbench/runtime/project_paths.py'
    monkeypatch.delenv('AI_DESK_RELEASE',raising=False)
    monkeypatch.delenv('AI_DESK_PROJECT_ROOT',raising=False)
    assert runpy.run_path(str(module))['ROOT']==module.parent.resolve()
    monkeypatch.chdir(tmp_path);monkeypatch.setenv('AI_DESK_PROJECT_ROOT','relative/data')
    assert runpy.run_path(str(module))['ROOT']==(tmp_path/'relative/data').resolve()
    assert not list(tmp_path.iterdir())
