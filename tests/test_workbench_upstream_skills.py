"""Official discovery parity and historical upstream snapshot reads, TEMP only."""
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


def test_official_catalog_discovers_project_and_official_skills_without_private_registry(library,monkeypatch):
    from easel_workbench.runtime.native_skills import service
    b=library;native=service(b.box,b.chat)
    before={p:p.read_bytes() for p in (b.root/'skills/builtin').glob('*/SKILL.md')}
    monkeypatch.setattr(b.creator,'detail',lambda *a,**k:pytest.fail('native menu must not load a private skill release'))
    rows=native.items()
    # The old combined skill remains readable for frozen historical requests,
    # while all new selections use the two independent Oil Pig workflows.
    from easel_workbench.runtime.native_skills import RETIRED_PRIVATE_SKILLS
    assert {row['name'] for row in rows}=={p.parent.name for p in before}-RETIRED_PRIVATE_SKILLS
    assert {'card-quote','ai-image-gen','oil-pig-poster','oil-pig-article'}<={row['name'] for row in rows}
    assert 'content-production' not in {row['name'] for row in rows}
    assert all('version' not in row and 'origin' not in row and 'launch_actions' not in row for row in rows)
    assert all(p.read_bytes()==raw for p,raw in before.items())
    assert 'experience-distillation' not in {row['name'] for row in rows}
    assert native.context().get_skills.__code__.co_filename.replace('\\','/').endswith('easel/web_services/skills.py')


@pytest.mark.parametrize('sid',['card-quote','content-production'])
def test_all_skill_details_have_identical_official_shape_and_read_current_source(library,sid,monkeypatch):
    from easel_workbench.runtime.native_skills import service
    b=library;native=service(b.box,b.chat)
    monkeypatch.setattr(b.upstream,'release',lambda *a,**k:pytest.fail('display must not construct private execution bundles'))
    item=asyncio.run(native.detail(sid))
    assert set(item)=={'name','layer','description','body','needsApi','apiConfigured','apiSpec','configuration_revision'}
    assert isinstance(item['configuration_revision'],int)
    assert item['name']==sid and 'resources' not in item
    source=b.root/'skills/builtin'/sid/'SKILL.md';source.write_bytes(source.read_bytes()+b'\nTEMP current file addition\n')
    current=asyncio.run(native.detail(sid))
    assert 'TEMP current file addition' in current['body']
    with b.store.connect() as c:
        assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0]==0


def test_ordinary_native_skill_message_uses_original_exact_input_and_api_only_guard(library,monkeypatch):
    from easel_workbench.runtime.native_skills import service
    from fastapi import HTTPException
    native=service(library.box,library.chat);raw=' 第一行\n\n 第二行 '
    message=native.prepare_message('card-quote',raw,'oil-pig')
    assert message.endswith('请执行 /card-quote，内容如下：\n\n'+raw)
    monkeypatch.setattr(library.chat.settings,'current',lambda *a,**k:{'runtime':'api'})
    from types import SimpleNamespace
    with pytest.raises(HTTPException) as error:
        asyncio.run(native.context().api_skill(SimpleNamespace(skill='card-quote',input=raw,persona=None)))
    assert error.value.status_code==409


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
