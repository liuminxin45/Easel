"""Real CLI subprocesses against TEMP fake releases; no actual desk DB access."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


TOOLS=Path('D:/Projects/neo-content/工具/内容工作流')


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')


def fixture(tmp_path):
    project=tmp_path/'neo-content';tools=project/'工具/内容工作流';tools.mkdir(parents=True)
    for name in ('toolbox_handoff.py','toolbox_review.py'):shutil.copy2(TOOLS/name,tools/name)
    old=tmp_path/'ai-news-desk';target=tmp_path/'Easel';directory=target/'workbench-releases/workbench-fixture'
    package=directory/'easel_workbench';runtime=package/'runtime';runtime.mkdir(parents=True)
    for path in (package/'__init__.py',runtime/'__init__.py'):path.write_text('',encoding='utf-8')
    for entry in ('direct_handoff','work_review'):
        (runtime/(entry+'.py')).write_text('import os,json,sys\ndef main():print(json.dumps({"entry":'+repr(entry)+',"root":os.environ["AI_DESK_PROJECT_ROOT"],"args":sys.argv[1:],"flat_desk_loaded":"desk" in sys.modules}))\n',encoding='utf-8')
    native={'release':'native-fixture','manifest_sha256':'1'*64}
    manifest={'release':'workbench-fixture','native':native,'python_executable':sys.executable,
        'files':{p.relative_to(directory).as_posix():sha(p) for p in directory.rglob('*') if p.is_file()}}
    write(directory/'workbench-release.json',manifest)
    pointer={'release':manifest['release'],'manifest_sha256':sha(directory/'workbench-release.json')}
    write(target/'data/active-workbench.json',pointer)
    write(target/'data/migration-owner.json',{'source_root':str(old),'target_root':str(target),'admitted':True,'native':native,**pointer})
    write(target/'.local/workbench-deployment/admission.json',{'workers':True})
    scripts=old/'scripts';scripts.mkdir(parents=True)
    (scripts/'__init__.py').write_text('',encoding='utf-8')
    active=old/'backend-releases/legacy';active.mkdir(parents=True)
    (scripts/'run_toolbox.py').write_text('from pathlib import Path\ndef selected():return Path('+repr(str(active))+')\n',encoding='utf-8')
    for entry in ('direct_handoff','work_review'):
        (active/(entry+'.py')).write_text('import os,json,sys\ndef main():print(json.dumps({"entry":"legacy-'+entry+'","root":os.environ["AI_DESK_PROJECT_ROOT"],"args":sys.argv[1:]}))\n',encoding='utf-8')
    return {'tools':tools,'old':old,'target':target,'directory':directory}


def run(f,name,*args):
    env=dict(os.environ)
    for key in ('PYTHONPATH','AI_NEWS_DESK_ROOT','AI_DESK_PROJECT_ROOT','AI_DESK_RELEASE','EASEL_WORKBENCH_ADMISSION'):env.pop(key,None)
    env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    return subprocess.run([sys.executable,str(f['tools']/name),*args],cwd=f['tools'],env=env,capture_output=True,text=True,encoding='utf-8',timeout=20)


@pytest.mark.parametrize('tool,entry',[('toolbox_handoff.py','direct_handoff'),('toolbox_review.py','work_review')])
@pytest.mark.parametrize('explicit',[False,True])
def test_default_and_explicit_legacy_root_follow_admitted_new_owner(tmp_path,tool,entry,explicit):
    f=fixture(tmp_path)
    command=['--desk-root',str(f['old'])] if explicit else []
    result=run(f,tool,*command,'status','--id','unchanged-operation')
    assert result.returncode==0,result.stderr
    value=json.loads(result.stdout)
    assert value['root']==str(f['target'].resolve()) and value['entry']==entry
    assert value['args']==['status','--id','unchanged-operation']
    assert not value['flat_desk_loaded']


@pytest.mark.parametrize('tool',['toolbox_handoff.py','toolbox_review.py'])
def test_no_migration_marker_keeps_original_legacy_behavior(tmp_path,tool):
    f=fixture(tmp_path);(f['target']/'data/migration-owner.json').unlink()
    result=run(f,tool,'status')
    assert result.returncode==0,result.stderr
    value=json.loads(result.stdout)
    assert value['root']==str(f['old'].resolve()) and value['entry'].startswith('legacy-')


@pytest.mark.parametrize('tool',['toolbox_handoff.py','toolbox_review.py'])
def test_tampered_manifest_fails_without_falling_back_to_old_db(tmp_path,tool):
    f=fixture(tmp_path);(f['directory']/'workbench-release.json').write_text('{}',encoding='utf-8')
    result=run(f,tool,'status')
    assert result.returncode!=0 and not result.stdout
    assert '未回退旧库' in result.stderr


@pytest.mark.parametrize('tool',['toolbox_handoff.py','toolbox_review.py'])
@pytest.mark.parametrize('blocked',['not-admitted','paused'])
def test_marker_before_admission_never_falls_back_to_old_writer(tmp_path,tool,blocked):
    f=fixture(tmp_path)
    if blocked=='not-admitted':write(f['target']/'.local/workbench-deployment/admission.json',{'workers':False})
    else:(f['target']/'.local/workbench-deployment/paused').touch()
    result=run(f,tool,'status')
    assert result.returncode!=0 and not result.stdout
    assert '未回退旧库' in result.stderr


def test_manifest_member_tamper_blocks_explicit_target_root(tmp_path):
    f=fixture(tmp_path);(f['directory']/'easel_workbench/runtime/direct_handoff.py').write_text('raise RuntimeError("should not run")',encoding='utf-8')
    result=run(f,'toolbox_handoff.py','--desk-root',str(f['target']),'status')
    assert result.returncode!=0 and not result.stdout
    assert 'should not run' not in result.stderr


@pytest.mark.parametrize('tool',['toolbox_handoff.py','toolbox_review.py'])
def test_fenced_cutover_blocks_old_cli_before_new_data_marker_exists(tmp_path,tool):
    f=fixture(tmp_path);(f['target']/'data/migration-owner.json').unlink()
    write(f['target']/'.local/workbench-deployment/cutover.json',{'source_root':str(f['old']),'target_root':str(f['target']),'phase':'fenced','candidate':{'release':'workbench-fixture'}})
    result=run(f,tool,'--desk-root',str(f['old']),'status')
    assert result.returncode!=0 and not result.stdout
    assert '未写入旧库' in result.stderr


@pytest.mark.parametrize('tool',['toolbox_handoff.py','toolbox_review.py'])
def test_unrelated_cutover_control_does_not_block_original_cli(tmp_path,tool):
    f=fixture(tmp_path);(f['target']/'data/migration-owner.json').unlink()
    write(f['target']/'.local/workbench-deployment/cutover.json',{'source_root':str(tmp_path/'another-desk'),'target_root':str(f['target']),'phase':'fenced'})
    result=run(f,tool,'status')
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['entry'].startswith('legacy-')


def test_live_cutover_uses_migration_marker_and_admission(tmp_path):
    f=fixture(tmp_path)
    write(f['target']/'.local/workbench-deployment/cutover.json',{'source_root':str(f['old']),'target_root':str(f['target']),'phase':'live'})
    result=run(f,'toolbox_handoff.py','status')
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['entry']=='direct_handoff'


def test_live_owner_control_cannot_fall_back_when_marker_is_missing(tmp_path):
    f=fixture(tmp_path);(f['target']/'data/migration-owner.json').unlink()
    write(f['target']/'.local/workbench-deployment/cutover.json',{'source_root':str(f['old']),'target_root':str(f['target']),'phase':'live'})
    result=run(f,'toolbox_handoff.py','status')
    assert result.returncode!=0 and not result.stdout and '未回退旧库' in result.stderr
