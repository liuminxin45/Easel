"""Project-only source publication outbox; historical releases stay immutable."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import shutil
import subprocess
from types import SimpleNamespace

import pytest
import yaml

_spec=importlib.util.spec_from_file_location('sync_fixtures',Path(__file__).with_name('test_workbench_skill_policy.py'))
_fixtures=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixtures)
runtime=_fixtures.runtime

from easel_workbench import project_skill_sync as sync
from easel_workbench.runtime.creator_runtime import packed
from easel_workbench.features.skills.retirement import SkillFeatureRetired


@pytest.fixture
def project(runtime):
    sid='topic-research'
    resource={'path':'skills/shared/workbench/topic.txt','kind':'reference','required':True,'scope':'on-demand'}
    path=runtime.project/resource['path'];path.parent.mkdir(parents=True);path.write_bytes(b'Original reference')
    with runtime.store.connect() as c:
        release=runtime._skill(c,sid,1,False)
        for key in ('history','published_version','is_current'):release.pop(key,None)
        raw={key:copy.deepcopy(release.get(key)) for key in ('id','tasks','executor','input_contract','output_contract','acceptance_cases')}
        raw.update(schema_version=1,display_name=release['name'],resources=[resource])
        header={'name':sid,'description':release['description'],'layer':'discover','metadata':{'openclaw':{'workbench':raw}}}
        prompt='---\n'+yaml.safe_dump(header,allow_unicode=True,sort_keys=False)+'---\nOriginal project method.\n'
        release.update(entry='skills/builtin/'+sid+'/SKILL.md',layer='discover',version=2,base_version=1,
                       prompt=prompt,resources=[runtime._resource(c,resource)],status='published')
        release['sha256']=runtime._release_hash(release)
        c.execute('INSERT INTO creator_skill_versions VALUES(?,?,?)',(sid,2,packed(release)))
        c.execute('UPDATE creator_skill_pointers SET version=2 WHERE skill_id=?',(sid,))
        file=runtime.project/release['entry'];file.parent.mkdir(parents=True);file.write_bytes(prompt.encode())
    return runtime,sid,file,path


def draft(project,prompt=None,resources=None):
    runtime,sid,file,_=project
    before=runtime.detail('skill',sid)
    value={'id':'draft-three','action':'skill-draft','skill_id':sid,'base_version':2,
           'prompt':prompt or before['prompt']+'\nApproved new method.','reason':'TEMP review'}
    if resources is not None:value['resources']=resources
    with runtime.store.connect() as c:
        return runtime.propose(c,sid,2,value['prompt'],value['reason'],operation_id=value['id'],resources=resources)


def publish(runtime,sid):
    """Construct an already-admitted historical publication, not a new public command."""
    value={'id':'publish-three','action':'skill-publish','skill_id':sid,'version':3,
           'expected_published_version':2,'confirm':True}
    with runtime.store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT 1 FROM creator_operations WHERE id=?',(value['id'],)).fetchone()
        if old:
            c.rollback()
            return runtime.command(value)
        result=runtime._publish(c,value)
        response={'id':value['id'],'status':'completed','execution':'script','result':result}
        from easel_workbench.features.skills.records import digest
        c.execute('INSERT INTO creator_operations VALUES(?,?,?,?)',(value['id'],digest(packed(value)),packed(response),'historical-time'))
        return sync.finish_response(runtime,c,response)


def admission_module():
    spec=importlib.util.spec_from_file_location('published_skill_admission',Path(__file__).resolve().parents[1]/'scripts/workbench_release.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def freeze_reference(project,raw):
    """Create a TEMP release containing real LF or mixed-EOL resource bytes."""
    runtime,sid,_,path=project;path.write_bytes(raw)
    with runtime.store.connect() as c:
        release=json.loads(c.execute('SELECT document FROM creator_skill_versions WHERE skill_id=? AND version=2',(sid,)).fetchone()[0])
        release['resources']=[runtime._resource(c,{k:v for k,v in release['resources'][0].items() if k in sync.FIELDS})]
        release['sha256']=runtime._release_hash(release)
        c.execute('UPDATE creator_skill_versions SET document=? WHERE skill_id=? AND version=2',(packed(release),sid))
    return release


@pytest.mark.parametrize('raw',[b'Original reference\nsecond line\n',b'Original reference\r\nsecond line\n'])
def test_line_ending_drift_blocks_admission_and_exact_restoration_preserves_history(project,raw):
    runtime,sid,_,path=project;release=freeze_reference(project,raw);gate=admission_module()
    with runtime.store.connect() as c:
        before=c.execute('SELECT document FROM creator_skill_versions WHERE skill_id=? AND version=2',(sid,)).fetchone()[0]
    assert gate.validate_published_skills(runtime.root,source_root=runtime.project)['checked']==1
    path.write_bytes(raw.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n'))
    assert not sync.matches_source(runtime,release)
    with pytest.raises(ValueError,match='topic-research@2'):
        gate.validate_published_skills(runtime.root,source_root=runtime.project)
    path.write_bytes(raw)
    assert gate.validate_published_skills(runtime.root,source_root=runtime.project)['skills']==[{'id':sid,'version':2,'available':True}]
    with runtime.store.connect() as c:
        assert c.execute('SELECT document FROM creator_skill_versions WHERE skill_id=? AND version=2',(sid,)).fetchone()[0]==before
        assert not c.execute("SELECT name FROM sqlite_master WHERE name='creator_skill_source_outbox'").fetchone()


@pytest.mark.parametrize('mutation',['content','missing','pending'])
def test_admission_keeps_real_resource_and_publication_failures_closed(project,mutation):
    runtime,_,_,path=project;gate=admission_module()
    if mutation=='content':path.write_bytes(b'Unapproved new instruction')
    elif mutation=='missing':path.unlink()
    else:
        with runtime.store.connect() as c:
            sync.initialize(c)
            c.execute('INSERT INTO creator_skill_source_outbox VALUES(?,?,?,?)',('pending','topic-research',2,packed({'status':'pending'})))
    with pytest.raises(ValueError,match='not callable'):
        gate.validate_published_skills(runtime.root,source_root=runtime.project)


def test_admission_checks_frozen_sources_against_same_actual_database(project,tmp_path):
    runtime,_,_,path=project;gate=admission_module();frozen=tmp_path/'frozen'
    shutil.copytree(runtime.project/'skills',frozen/'skills')
    assert gate.validate_published_skills(runtime.root,source_root=frozen)['checked']==1
    (frozen/path.relative_to(runtime.project)).write_bytes(b'wrong frozen candidate')
    assert gate.validate_published_skills(runtime.root,source_root=runtime.project)['checked']==1
    with pytest.raises(ValueError,match='not callable'):
        gate.validate_published_skills(runtime.root,source_root=frozen)


@pytest.mark.parametrize('raw',[b'LF first\nLF second\n',b'mixed first\r\nLF second\n'])
def test_private_skill_bytes_survive_real_git_checkout_with_autocrlf_true(tmp_path,raw):
    source=tmp_path/'source';source.mkdir();checkout=tmp_path/'checkout'
    relative=Path('skills/shared/workbench/byte-fixture.md')
    resource=source/relative;resource.parent.mkdir(parents=True);resource.write_bytes(raw)
    (source/'.gitattributes').write_bytes((Path(__file__).resolve().parents[1]/'.gitattributes').read_bytes())
    def git(cwd,*args):return subprocess.check_output(['git',*args],cwd=cwd,stderr=subprocess.STDOUT)
    git(source,'init','-q');git(source,'config','core.autocrlf','true')
    git(source,'add','.gitattributes',relative.as_posix())
    git(source,'-c','core.hooksPath=NUL','-c','user.name=TEMP','-c','user.email=temp@example.invalid','-c','commit.gpgsign=false','commit','-qm','TEMP byte preservation')
    git(tmp_path,'clone','--quiet','--no-checkout',str(source),str(checkout))
    git(checkout,'config','core.autocrlf','true');git(checkout,'checkout','--quiet','HEAD')
    assert (checkout/relative).read_bytes()==raw
    assert sync.digest((checkout/relative).read_bytes())==sync.digest(raw)
    assert git(checkout,'check-attr','text','--',relative.as_posix()).decode().strip().endswith(': unset')


def test_initial_admission_does_not_create_database(tmp_path):
    assert admission_module().validate_published_skills(tmp_path)['checked']==0
    assert not (tmp_path/'data').exists()


def test_historical_outbox_fixture_preserves_original_versions(project):
    runtime,sid,file,resource=project;original=file.read_bytes()
    with runtime.store.connect() as c:old=c.execute('SELECT document FROM creator_skill_versions WHERE skill_id=? AND version=2',(sid,)).fetchone()[0]
    candidate=draft(project);assert file.read_bytes()==original
    assert sync.matches_source(runtime,runtime.detail('skill',sid))
    response=publish(runtime,sid);receipt=response['result']['source_sync']
    assert receipt['status']=='applied' and file.read_bytes()==candidate['prompt'].encode()
    assert sync.matches_source(runtime,runtime.detail('skill',sid))
    backup=runtime.root/'data/creator-source-sync'/receipt['id']/'originals'/candidate['entry']
    assert backup.read_bytes()==original
    with runtime.store.connect() as c:
        assert c.execute('SELECT document FROM creator_skill_versions WHERE skill_id=? AND version=2',(sid,)).fetchone()[0]==old
        assert not c.execute("SELECT name FROM sqlite_master WHERE name='creator_model_calls'").fetchone()
    assert resource.read_bytes()==b'Original reference'


def test_partial_historical_write_stays_closed_and_public_receipt_does_not_restart_it(project,monkeypatch):
    runtime,sid,file,resource=project
    before=runtime.detail('skill',sid);original=resource.read_bytes()
    resource.write_bytes(b'New frozen reference')
    draft(project,resources=[{key:value for key,value in before['resources'][0].items() if key in sync.FIELDS}])
    resource.write_bytes(original)
    atomic=sync._atomic
    def fail_entry(path,raw):
        if path==file:raise OSError('Synthetic power loss before SKILL entry')
        return atomic(path,raw)
    monkeypatch.setattr(sync,'_atomic',fail_entry)
    first=publish(runtime,sid)
    assert first['result']['source_sync']['status']=='blocked'
    assert resource.read_bytes()==b'New frozen reference' and 'Approved new method' not in file.read_text(encoding='utf-8')
    assert not sync.matches_source(runtime,runtime.detail('skill',sid))
    monkeypatch.setattr(sync,'_atomic',atomic)
    second=publish(runtime,sid)
    assert second['result']['source_sync']['id']==first['result']['source_sync']['id']
    assert second==first and second['result']['source_sync']['status']=='blocked'
    assert not sync.matches_source(runtime,runtime.detail('skill',sid))
    with runtime.store.connect() as c:
        assert c.execute("SELECT count(*) FROM creator_skill_events WHERE skill_id=? AND action='publish'",(sid,)).fetchone()[0]==1


@pytest.mark.parametrize('field,value',[('tasks',['poster']),('executor','workflow'),('composition',{'requires':['image-production']})])
def test_raw_metadata_cannot_change_database_capability_scope(project,field,value):
    runtime,sid,file,_=project;original=file.read_bytes();release=runtime.detail('skill',sid)
    header,body=sync.parse_skill(release['prompt']);header['metadata']['openclaw']['workbench'][field]=value
    draft(project,prompt='---\n'+yaml.safe_dump(header,allow_unicode=True,sort_keys=False)+'---\n'+body)
    with pytest.raises(ValueError,match='不能通过原始技能头部'):publish(runtime,sid)
    assert runtime.detail('skill',sid)['published_version']==2 and file.read_bytes()==original
    with runtime.store.connect() as c:
        assert not c.execute("SELECT name FROM sqlite_master WHERE name='creator_skill_source_outbox'").fetchone()


def test_completed_publish_receipt_cannot_overwrite_later_manual_source_edits(project):
    runtime,sid,file,_=project;original=file.read_bytes()
    draft(project);publish(runtime,sid)
    file.write_bytes(original)  # even a known old release is now an external edit
    response=publish(runtime,sid)
    assert response['result']['source_sync']['status']=='applied' and file.read_bytes()==original
    assert not sync.matches_source(runtime,runtime.detail('skill',sid))






def test_frozen_derived_baseline_is_retained_without_becoming_writable_source(project):
    runtime,sid,file,_=project
    original_bytes=b'{"confirmed_style":"Preserve historical human confirmation exactly."}'
    old_path='.agents/skills/old-author/references/confirmed-baseline.json'
    with runtime.store.connect() as c:
        row=c.execute('SELECT document FROM creator_skill_versions WHERE skill_id=? AND version=2',(sid,)).fetchone()
        release=json.loads(row[0]);digest=hashlib.sha256(original_bytes).hexdigest()
        release['resources'].append({'path':old_path,'kind':'contract','scope':'on-demand','required':False,
                                     'available':True,'derived':True,'sha256':digest,'size':len(original_bytes)})
        release['sha256']=runtime._release_hash(release)
        original_document=packed(release)
        c.execute('UPDATE creator_skill_versions SET document=? WHERE skill_id=? AND version=2',(original_document,sid))
        c.execute('INSERT INTO creator_skill_blobs VALUES(?,?)',(digest,original_bytes))
    assert not (runtime.project/old_path).exists()
    draft(project);response=publish(runtime,sid)
    assert response['result']['source_sync']['status']=='applied'
    assert sync.matches_source(runtime,runtime.detail('skill',sid))
    assert not (runtime.project/old_path).exists()
    with runtime.store.connect() as c:
        assert c.execute('SELECT document FROM creator_skill_versions WHERE skill_id=? AND version=2',(sid,)).fetchone()[0]==original_document
        assert bytes(c.execute('SELECT bytes FROM creator_skill_blobs WHERE sha256=?',(digest,)).fetchone()[0])==original_bytes
        plan=json.loads(c.execute('SELECT document FROM creator_skill_source_outbox').fetchone()[0])
        assert old_path not in {item['path'] for item in plan['files']}


@pytest.mark.parametrize('version',[1,2])
def test_new_revert_is_retired_and_cannot_overwrite_historical_source_or_pointer(project,version):
    runtime,sid,file,_=project;original=file.read_bytes()
    with runtime.store.connect() as c:
        before=[tuple(r) for r in c.execute('SELECT * FROM creator_skill_pointers')]
        versions=[tuple(r) for r in c.execute('SELECT * FROM creator_skill_versions')]
    with pytest.raises(SkillFeatureRetired):runtime.command({'id':'new-revert','action':'skill-revert',
        'skill_id':sid,'version':version,'expected_published_version':2,'confirm':True})
    assert file.read_bytes()==original
    with runtime.store.connect() as c:
        assert [tuple(r) for r in c.execute('SELECT * FROM creator_skill_pointers')]==before
        assert [tuple(r) for r in c.execute('SELECT * FROM creator_skill_versions')]==versions


def test_native_admission_uses_current_sources_without_requiring_private_database_releases(tmp_path):
    root=Path(__file__).resolve().parents[1]
    from easel_workbench.skill_catalog import ProjectSkillCatalog
    entries=ProjectSkillCatalog(root).entries()
    before={root/e['entry']:(root/e['entry']).read_bytes() for e in entries}
    result=admission_module().validate_published_skills(tmp_path,source_root=root)
    assert {entry['id'] for entry in entries}=={'oil-pig-poster','oil-pig-article','oil-pig-learn-poster','oil-pig-learn-article'}
    assert result['mode']=='easel-native' and result['checked']==len(entries)==4
    assert {row['id'] for row in result['skills']}=={e['id'] for e in entries}
    assert all(row['source']=='SKILL.md' and 'version' not in row for row in result['skills'])
    assert not (tmp_path/'data/desk.sqlite').exists()
    assert all(path.read_bytes()==raw for path,raw in before.items())
