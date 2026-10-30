"""Full upstream discovery and explicit native invocation, TEMP only."""
import asyncio
import importlib.util
import json
from pathlib import Path
import shutil

import pytest
from easel import harnesses

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('upstream_business_fixtures',Path(__file__).with_name('test_workbench_chat_business.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
business=fixtures.business


@pytest.fixture
def library(business):
    b=business
    for sid in ('card-quote','ai-image-gen','asset-manager'):
        shutil.copytree(ROOT/'skills/builtin'/sid,b.root/'skills/builtin'/sid)
    shutil.copytree(ROOT/'skills/shared/scripts',b.root/'skills/shared/scripts',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    return b


def test_native_catalog_is_complete_without_editing_upstream_skill_sources(library):
    b=library;before={p:p.read_bytes() for p in (b.root/'skills/builtin').glob('*/SKILL.md')}
    rows=b.skills();native=[row for row in rows if row.get('origin')=='easel']
    assert {row['id'] for row in native}=={'card-quote','ai-image-gen','asset-manager'}
    assert all(row['launch_actions'][0]['task']=='native' for row in native)
    assert len([row for row in rows if row.get('origin')=='workbench'])==8
    assert b.skill('card-quote')['body'] in b.skill('card-quote')['prompt']
    assert all(path.read_bytes()==raw for path,raw in before.items())
    with b.store.connect() as c:assert not c.execute("SELECT 1 FROM creator_skills WHERE id='card-quote'").fetchone()


def test_native_prepare_freezes_selected_method_and_is_read_only(library):
    b=library;value={'sessionId':'test-chat','turnId':'native-one','message':'做一张具体金句卡',
        'attachments':[],'context':{'profile_id':'oil-pig','skill_id':'card-quote','version':1,'action_id':'native','skill_revision':b.upstream.release('card-quote')['source_revision']}}
    prepared=b.prepare(value);snapshot=prepared['snapshot']
    assert snapshot['task']=='native' and snapshot['active_skill_ids']==['card-quote']
    assert prepared['work'] is None and 'card-quote Skill' not in snapshot['prompt_text']
    assert b.skill('card-quote')['prompt'] in prepared['actual_prompt']
    assert any(resource['path'].endswith('model_registry.py') for resource in snapshot['skills'][0]['resources'])
    assert not (b.root/'outputs/_sessions/skill-inputs').exists()
    with b.store.connect() as c:assert c.execute('SELECT count(*) FROM easel_chat_turns').fetchone()[0]==0


def test_actual_native_turn_registers_version_blob_files_and_gallery_once(library,monkeypatch):
    async def scenario():
        b=library;requests=[]
        class FakeNative:
            async def run(self,request,emit,ask,bind):
                requests.append(request);bind('native-real-shape');request.on_native_turn('native-real-shape','native-turn-real-shape')
                payload=json.JSONDecoder().raw_decode(request.prompt.split('## 本轮冻结输入\n')[-1])[0]
                assert len(payload['frozen_skill_files'])==1
                manifest=Path(payload['frozen_skill_library']['manifest'])
                assert manifest.is_file()
                from easel_workbench.runtime.creator_runtime import digest
                assert digest(manifest.read_bytes())==payload['frozen_skill_library']['sha256']
                assert any(file['original_path'].endswith('model_registry.py') for file in json.loads(manifest.read_text(encoding='utf-8')))
                folder=Path(payload['output_directory'])/'products';folder.mkdir(parents=True)
                (folder/'成品.html').write_text('<h1>Actual TEMP file</h1>',encoding='utf-8')
                emit('token','已生成本轮文件。')
        monkeypatch.setattr(harnesses,'adapter',lambda name:FakeNative())
        value={'sessionId':'test-chat','turnId':'native-one','message':'做金句卡','attachments':[],
               'context':{'profile_id':'oil-pig','skill_id':'card-quote','version':1,'action_id':'native','skill_revision':b.upstream.release('card-quote')['source_revision']}}
        turn=await b.chat.submit(value,**b.prepare(value));await b.chat._tasks[turn['id']]
        assert len(requests)==1 and b.chat.get_turn(turn['id'])['status']=='completed'
        with b.store.connect() as c:
            assert c.execute("SELECT count(*) FROM creator_skill_versions WHERE skill_id='card-quote'").fetchone()[0]==1
            assert c.execute('SELECT count(*) FROM artifacts WHERE task_id=?',(turn['id'],)).fetchone()[0]==1
            call=json.loads(c.execute('SELECT document FROM creator_model_calls WHERE task_id=?',(turn['id'],)).fetchone()[0])
        assert call['active_skills'][0]['id']=='card-quote' and call['active_skills'][0]['version']==1
        assert b.upstream.library()['items'][0]['files'][0]['name']=='成品.html'
        path=b.root/'skills/builtin/card-quote/SKILL.md';path.write_text(path.read_text(encoding='utf-8')+'\nFuture upstream update',encoding='utf-8')
        original=b.chat.get_turn(turn['id'],private=True)['actual_prompt']
        assert b.prepare(value)['receipt']['id']==turn['id'] and len(requests)==1
        assert b.chat.get_turn(turn['id'],private=True)['actual_prompt']==original
        assert b.upstream.release('card-quote')['version']==2
        assert b.upstream.release('card-quote',1)['version']==1
        await b.chat.close()
    asyncio.run(scenario())


def test_changed_source_between_compile_and_accept_does_not_start_a_model(library,monkeypatch):
    async def scenario():
        b=library;value={'sessionId':'test-chat','turnId':'native-change','message':'做卡片','attachments':[],
                         'context':{'profile_id':'oil-pig','skill_id':'card-quote','version':1,'action_id':'native','skill_revision':b.upstream.release('card-quote')['source_revision']}}
        prepared=b.prepare(value);path=b.root/'skills/shared/scripts/model_registry.py';path.write_bytes(path.read_bytes()+b'\n# changed\n')
        with pytest.raises(ValueError,match='变化'):await b.chat.submit(value,**prepared)
        with b.store.connect() as c:assert c.execute('SELECT count(*) FROM easel_chat_turns').fetchone()[0]==0
        await b.chat.close()
    asyncio.run(scenario())


def test_immutable_release_source_is_independent_of_new_working_checkout_edits(library):
    from easel_workbench.upstream_skills import UpstreamSkills
    b=library;source=b.root/'workbench-releases/approved';shutil.copytree(b.root/'skills',source/'skills')
    native=UpstreamSkills(b.root,b.creator,source)
    before=native.release('card-quote')
    path=b.root/'skills/builtin/card-quote/SKILL.md';path.write_bytes(path.read_bytes()+b'\nUnreviewed checkout edit\n')
    assert native.release('card-quote')['source_revision']==before['source_revision']
    assert 'Unreviewed checkout edit' not in native.detail('card-quote')['body']


def test_full_actual_library_and_frontmatter_alias_are_discovered_without_global_install(library):
    from easel_workbench.upstream_skills import UpstreamSkills
    native=UpstreamSkills(ROOT,library.creator)
    rows=native.items()
    actual={p.parent.name for p in (ROOT/'skills/builtin').glob('*/SKILL.md')}
    own={row['id'] for row in library.catalog.entries()}
    assert {row['id'] for row in rows}==actual-own
    assert native.detail('skill-xhs-analyzer')['meta']['name']=='redbook'
    assert all(row['validation_state']=='not_tested' for row in rows)


def test_provider_badges_are_configuration_only_and_never_return_credentials(library):
    b=library;b.upstream.environment=lambda:{'IMG_API_KEY':'fixture-secret-do-not-expose','IMG_BASE_URL':'https://example.invalid/v1'}
    rows=b.upstream.items();image=next(row for row in rows if row['id']=='ai-image-gen')
    assert image['needsApi'] and image['apiConfigured'] and image['validation_state']=='not_tested'
    assert 'fixture-secret-do-not-expose' not in json.dumps(rows)
    b.upstream.environment=lambda:{}
    assert not next(row for row in b.upstream.items() if row['id']=='ai-image-gen')['apiConfigured']


def test_native_source_revision_from_the_menu_cannot_be_silently_reinterpreted(library):
    b=library;revision=b.upstream.release('card-quote')['source_revision']
    source=b.root/'skills/builtin/card-quote/SKILL.md';source.write_bytes(source.read_bytes()+b'\nLater source edit\n')
    with pytest.raises(ValueError,match='修订'):
        b.prepare({'sessionId':'test-chat','turnId':'stale-menu','message':'做卡片','attachments':[],
                   'context':{'profile_id':'oil-pig','skill_id':'card-quote','version':1,'action_id':'native','skill_revision':revision}})
