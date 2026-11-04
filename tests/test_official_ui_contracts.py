"""Real TEMP official UI contracts: one rule table, atomic profile, versioned keys."""
import ast
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest
from starlette.requests import Request

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('official_ui_fixtures',Path(__file__).with_name('test_workbench_skill_commands.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
runtime,commands=fixtures.runtime,fixtures.commands

from easel.web_services import skills as shared_skills
from easel.web_services.profiles import baseline_profile_files
from easel_workbench.runtime.native_api import NativeApi,handle
from easel_workbench.settings import SettingsService,SettingsConflict

class Vault:
    def __init__(self):self.values={}
    def put(self,owner,value):
        key=str(len(self.values));self.values[key]=(owner,copy.deepcopy(value));return key
    def get(self,key,owner):
        actual,value=self.values[key];assert actual==owner;return copy.deepcopy(value)

def test_skill_rules_and_parsers_are_moved_from_official_without_duplicate_bodies():
    official=ast.parse(subprocess.check_output(['git','show','0f43dc9:web/app.py'],cwd=ROOT,text=True,encoding='utf-8'))
    shared=ast.parse((ROOT/'easel/web_services/skills.py').read_text(encoding='utf-8'))
    current=ast.parse((ROOT/'web/app.py').read_text(encoding='utf-8'))
    for name in ('_model_spec','_short_drama_spec','_mask','_key_configured','_skill_api_configured','_api_spec_status'):
        before=next(n for n in official.body if isinstance(n,ast.FunctionDef) and n.name==name)
        after=next(n for n in shared.body if isinstance(n,ast.FunctionDef) and n.name==name)
        assert ast.dump(before,include_attributes=False)==ast.dump(after,include_attributes=False),name
        assert not any(isinstance(n,ast.FunctionDef) and n.name==name for n in current.body),name
    before=next(n for n in official.body if isinstance(n,ast.FunctionDef) and n.name=='_parse_skill_md')
    parser=next(n for n in shared.body if isinstance(n,ast.FunctionDef) and n.name=='parse_skill_text')
    # The original parser body is unchanged except that the host supplies text.
    expected=copy.deepcopy(before);expected.name=parser.name;expected.args=copy.deepcopy(parser.args)
    del expected.body[1]  # text = path.read_text(encoding='utf-8')
    assert ast.dump(expected,include_attributes=False)==ast.dump(parser,include_attributes=False)
    wrapper=next(n for n in shared.body if isinstance(n,ast.FunctionDef) and n.name=='_parse_skill_md')
    assert ast.dump(wrapper.body[0],include_attributes=False)==ast.dump(ast.parse("return parse_skill_text(path.read_text(encoding='utf-8'))").body[0],include_attributes=False)
    assert len(wrapper.body)==1
    assert not any(isinstance(n,ast.FunctionDef) and n.name=='_parse_skill_md' for n in current.body)
    def table(tree):return next(n for n in tree.body if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id=='SKILL_API_REQUIREMENTS')
    assert ast.dump(table(official),include_attributes=False)==ast.dump(table(shared),include_attributes=False)
    assert not any(isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id=='SKILL_API_REQUIREMENTS' for n in current.body)


OFFICIAL_SKILL_PATHS=[name for name in subprocess.check_output(
    ['git','ls-tree','-r','--name-only','0f43dc9','--','skills/builtin'],cwd=ROOT,text=True,encoding='utf-8').splitlines()
    if name.endswith('/SKILL.md')]


@pytest.fixture(scope='module')
def official_skill_parser():
    source=subprocess.check_output(['git','show','0f43dc9:web/app.py'],cwd=ROOT,text=True,encoding='utf-8')
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='_parse_skill_md')
    namespace={'Path':Path};exec(compile(ast.Module(body=[node],type_ignores=[]),'official-parser','exec'),namespace)
    return namespace['_parse_skill_md']


@pytest.mark.parametrize('relative',OFFICIAL_SKILL_PATHS)
def test_each_official_skill_uses_the_original_text_parser_without_rewriting_sources(relative,official_skill_parser):
    path=ROOT/relative;original=path.read_bytes()
    expected=official_skill_parser(path)
    assert shared_skills.parse_skill_text(path.read_text(encoding='utf-8'))==expected
    assert shared_skills._parse_skill_md(path)==expected
    assert path.read_bytes()==original


def test_upstream_entries_and_historical_detail_share_display_parsing_without_mutating_releases(monkeypatch):
    from easel_workbench.upstream_skills import UpstreamSkills
    library=UpstreamSkills.__new__(UpstreamSkills);library.root=library.source=ROOT
    entries={item['entry']:item for item in library.entries()}
    assert len(OFFICIAL_SKILL_PATHS)==115
    for relative in OFFICIAL_SKILL_PATHS:
        item=entries[relative];raw=(ROOT/relative).read_bytes()
        description,layer,body=shared_skills._parse_skill_md(ROOT/relative)
        assert (item['description'],item['layer'],item['body'])==(description,layer,body)
        assert item['prompt'].encode('utf-8')==raw
    release={'id':'original-id','name':'original-alias','version':8,'sha256':'frozen-historical-sha',
             'source_revision':'frozen-source','description':'old YAML display','layer':'old-layer',
             'prompt':'---\nname: original-alias\ndescription: |\n  Original first line\n  Original second line\nlayer: produce\n---\n\n# Frozen original body\n'}
    preserved=copy.deepcopy(release)
    monkeypatch.setattr(library,'release',lambda sid:release)
    detail=library.detail('original-id')
    assert (detail['description'],detail['layer'],detail['body'])==shared_skills.parse_skill_text(release['prompt'])
    assert detail['raw']==detail['prompt']==preserved['prompt']
    for field in ('id','version','sha256','source_revision'):assert detail[field]==preserved[field]
    assert release==preserved

def test_all_seven_official_skills_have_exact_configuration_shape_and_masking():
    assert len(shared_skills.SKILL_API_REQUIREMENTS)==7
    assert shared_skills.skill_status('paper-explainer',{})['needsApi'] is True
    assert shared_skills.skill_status('paper-explainer',{})['apiConfigured'] is True
    assert shared_skills.skill_status('ai-image-gen',{})['apiConfigured'] is False
    secret='complete-original-secret-123456789'
    for name in shared_skills.SKILL_API_REQUIREMENTS:
        value=shared_skills.skill_status(name,{'IMG_API_KEY':secret,'OPENAI_API_KEY':secret})
        assert set(value)=={'needsApi','apiConfigured','apiSpec'}
        assert value['apiSpec']['providers']
        assert secret not in json.dumps(value)

def test_original_six_profile_documents_are_identical_to_the_official_writer(tmp_path):
    source=subprocess.check_output(['git','show','0f43dc9:web/app.py'],cwd=ROOT,text=True,encoding='utf-8')
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='_write_baseline_profile')
    namespace={'PROFILES_DIR':tmp_path}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'official-baseline','exec'),namespace)
    form={'name':'TEMP','platforms':['公众号','小红书'],'links':{'公众号':'https://example.test/home'},'accountStage':'已有账号',
          'direction':' 原始方向 ','reason':'原始区别','goal':'目标','formats':'图文','likes':'原始对标','tone':'简洁','avoid':'原始边界'}
    namespace['_write_baseline_profile']('TEMP',form)
    assert baseline_profile_files('TEMP',form)=={p.name:p.read_text(encoding='utf-8') for p in (tmp_path/'TEMP').iterdir()}

def profile_request():
    return Request({'type':'http','method':'POST','path':'/api/profile/build','query_string':b'',
                    'headers':[(b'x-operation-id',b'original-profile-once')],'scheme':'https','server':('native.test',443)})

def test_original_wizard_protocol_persists_stable_identity_and_original_form_once(commands,monkeypatch):
    from easel.web_services import profiles
    jobs=[];start=profiles.start_profile_enhancement
    monkeypatch.setattr(profiles,'start_profile_enhancement',lambda *args,**options:start(*args,**options,background=jobs.append))
    api=NativeApi(commands);commands._native_api=api
    form={'name':'TEMP-original','direction':'准确原始方向','platforms':['公众号'],'links':{'公众号':'https://example.test/original'},'accountStage':'已有账号','avoid':'不变的原话'}
    async def run():
        first=await handle(commands,'/api/profile/build',profile_request(),{'name':'TEMP-original','form':form})
        second=await handle(commands,'/api/profile/build',profile_request(),{'name':'TEMP-original','form':form})
        return first,second
    first,second=asyncio.run(run());assert first.status_code==second.status_code==200
    result=json.loads(first.body);assert result==json.loads(second.body) and result['created'] and result['async'] is True
    assert len(jobs)==1 and api._profile_build_status(result['name'])['state']=='running'
    assert result['name'].startswith('profile-') and result['name']!='TEMP-original'
    profile=commands.creator.detail('profile',result['name'])
    assert profile['identity']==baseline_profile_files('TEMP-original',form)['identity.md']
    with commands.store.connect() as c:
        rows=c.execute('SELECT filename,content FROM native_profile_documents WHERE profile_id=?',(result['name'],)).fetchall()
        assert len(rows)==3
        assert json.loads(next(row['content'] for row in rows if row['filename']=='onboarding.json'))==form
        assert c.execute("SELECT COUNT(*) FROM creator_operations WHERE id='native-profile-original-profile-once'").fetchone()[0]==1

def test_failed_original_document_write_rolls_back_profile_and_operation(commands):
    api=NativeApi(commands);api._operation='fail-baseline'
    with commands.store.connect() as c:
        before=c.execute('SELECT COUNT(*) FROM creator_profiles').fetchone()[0]
        c.execute("CREATE TRIGGER reject_original BEFORE INSERT ON native_profile_documents BEGIN SELECT RAISE(ABORT,'TEMP document failure'); END")
    with pytest.raises(sqlite3.IntegrityError):api._build_profile({'name':'TEMP-rollback','form':{'direction':'原话'}})
    with commands.store.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM creator_profiles').fetchone()[0]==before
        assert not c.execute("SELECT 1 FROM creator_operations WHERE id='native-profile-fail-baseline'").fetchone()

def test_official_env_save_uses_same_revision_and_secret_store_without_rewriting_env(commands):
    settings=SettingsService(commands,vault=Vault());before=settings.environment();settings.capture();old=settings.current()['revision']
    env_file=commands.root/'.env';raw=env_file.read_bytes() if env_file.exists() else None
    request={'id':'official-env-once','expected_revision':old,'updates':{'IMG_API_KEY':'new-official-ui-secret','IMG_BASE_URL':'https://example.test/v1'}}
    result=asyncio.run(settings.command('/api/env',request));assert result['ok'] and result['skills']['ai-image-gen']
    assert result==asyncio.run(settings.command('/api/env',request))
    assert settings.current()['revision']==old+1
    assert settings.environment(old)==before
    assert settings.environment()['IMG_API_KEY']=='new-official-ui-secret'
    assert 'new-official-ui-secret' not in json.dumps(result)
    assert (env_file.read_bytes() if env_file.exists() else None)==raw
    with pytest.raises(SettingsConflict):asyncio.run(settings.command('/api/env',{**request,'id':'stale-env'}))


def test_skill_detail_captures_the_exact_viewed_configuration_parent(commands,monkeypatch):
    from easel_workbench.upstream_skills import UpstreamSkills
    settings=SettingsService(commands,vault=Vault())
    library=UpstreamSkills(commands.root,commands.creator)
    monkeypatch.setattr(library,'release',lambda name:{'prompt':'---\nname: ai-image-gen\n---\n# Original skill\n'})
    library.configuration=settings.skill_configuration
    original=library.detail('ai-image-gen');assert original['configuration_revision']==0
    newer={'id':'newer-config','expected_revision':0,'updates':{'IMG_API_KEY':'newer-key','IMG_BASE_URL':'https://example.test/v1'}}
    asyncio.run(settings.command('/api/env',newer))
    current=library.detail('ai-image-gen');assert current['configuration_revision']==settings.current()['revision']
    assert not original['apiConfigured'] and current['apiConfigured']
    with pytest.raises(SettingsConflict):
        asyncio.run(settings.command('/api/env',{'id':'stale-view','expected_revision':original['configuration_revision'],'updates':{'IMG_API_KEY':'older-form-key'}}))
    assert settings.environment()['IMG_API_KEY']=='newer-key'
