"""TEMP-only template approval, isolation, identity and frozen-input contracts."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from easel_workbench.features.production_insights.templates import Service
from easel_workbench.features.skills.records import CreatorConflict

spec = importlib.util.spec_from_file_location('template_news_fixture', Path(__file__).with_name('test_workbench_news_creation.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
news = fixture.news


@pytest.fixture
def templates(news):
    path = news.root / 'skills/builtin/oil-pig-poster/SKILL.md'
    path.parent.mkdir(parents=True)
    path.write_text('---\nname: oil-pig-poster\ndescription: TEMP\n---\n本技能规则', encoding='utf-8')
    # Native delivery captures actual bytes into the original artifact store.
    product = news.root / 'data/artifacts/image/reference.png'
    product.parent.mkdir(parents=True)
    product.write_bytes(b'EXACT TEMP REFERENCE')
    digest = hashlib.sha256(product.read_bytes()).hexdigest()
    receipt = {'work_id': 'work', 'version_id': 'version', 'status': 'completed', 'whole_ready': True,
               'skill_id': 'oil-pig-poster', 'format': 'poster', 'profile_id': 'p'}
    with news.box.store.connect() as connection:
        connection.execute('CREATE TABLE toolbox_meta(key TEXT PRIMARY KEY,value TEXT)')
        connection.execute('CREATE TABLE artifacts(id TEXT PRIMARY KEY,task_id TEXT,name TEXT,path TEXT,mime TEXT)')
        connection.execute('CREATE TABLE easel_chat_turns(id TEXT PRIMARY KEY,document TEXT)')
        connection.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)', ('image', 'version', 'reference.png', str(product), 'image/png'))
        connection.execute('INSERT INTO toolbox_meta VALUES(?,?)', ('native-review:version', json.dumps({
            'receipt': receipt, 'files': [{'path': str(product), 'sha256': digest}]})))
        connection.execute('INSERT INTO easel_chat_turns VALUES(?,?)', ('version', json.dumps({
            'status': 'completed', 'native_turn_id': 'actual-native-turn', 'context': {'creation': {
                'style': {slot: slot for slot in ('writing', 'visual', 'character', 'layout')}, 'note': '旧新闻与一次性要求不要复制'}}})))
    return Service(news.box), news, product


def confirmation(**changes):
    return {'operation_id': 'confirm-one', 'name': '解释清楚的模板', 'method': '先明确一个主线，再逐图展开；保持手机字号清晰。',
            'reference_ids': ['image'], 'confirmed': True} | changes


def test_only_human_confirmed_complete_products_can_become_templates(templates):
    service, news, product = templates
    assert service.list('p', 'poster') == []
    for value in (confirmation(confirmed=False), confirmation(confirmed='true'), confirmation(name=''), confirmation(reference_ids=['other']), confirmation(reference_ids=['image'] * 5)):
        with pytest.raises(ValueError):
            service.create('work', 'version', value)
    with pytest.raises(ValueError):
        service.create('another-work', 'version', confirmation())
    with news.box.store.connect() as connection:
        row = json.loads(connection.execute('SELECT value FROM toolbox_meta').fetchone()[0])
        row['receipt']['whole_ready'] = False
        connection.execute('UPDATE toolbox_meta SET value=?', (json.dumps(row),))
    with pytest.raises(ValueError, match='完整交付'):
        service.create('work', 'version', confirmation())


def test_approval_is_idempotent_and_profile_format_isolation_is_enforced(templates):
    service, news, product = templates
    result = service.create('work', 'version', confirmation())
    assert result == service.create('work', 'version', confirmation())
    assert result == service.operation_result('confirm-one')
    assert result['available'] and len(result['revision']) == 64
    assert result['source_version_id'] == 'version'
    assert service.list('other-profile', 'poster') == []
    assert service.list('p', 'article') == []
    for profile, format in (('other-profile', 'poster'), ('p', 'article')):
        with pytest.raises(ValueError):
            service.get(result['id'], profile, format, result['revision'])
    with pytest.raises(CreatorConflict):
        service.create('work', 'version', confirmation(method='另一个方法'))
    with pytest.raises(CreatorConflict):
        service.get(result['id'], 'p', 'poster', 'a' * 64)
    encoded = json.dumps(result, ensure_ascii=False)
    assert '旧新闻' not in encoded and '一次性要求' not in encoded and str(news.root) not in encoded
    assert 'method' not in service.list('p', 'poster')[0]


def test_template_freezes_references_and_disables_if_current_skill_changes(templates):
    service, news, product = templates
    result = service.create('work', 'version', confirmation())
    # The selected template is not dependent on a mutable old product path.
    product.write_bytes(b'OLD PRODUCT HAS CHANGED')
    summary, materials = service.materials(result['id'], 'p', 'poster', result['revision'])
    assert materials[-1][1] == b'EXACT TEMP REFERENCE'
    assert summary['source_version_id'] == 'version'
    (news.root / 'skills/builtin/oil-pig-poster/SKILL.md').write_text('---\nname: oil-pig-poster\ndescription: changed\n---\n改变规则', encoding='utf-8')
    assert not service.list('p', 'poster')[0]['available']
    with pytest.raises(CreatorConflict, match='技能已更新'):
        service.materials(result['id'], 'p', 'poster', result['revision'])


def test_original_product_tamper_rejects_confirmation(templates):
    service, news, product = templates
    product.write_bytes(b'CHANGED BEFORE CONFIRMATION')
    with pytest.raises(CreatorConflict, match='原件已变化'):
        service.create('work', 'version', confirmation())


def test_news_creation_uses_exact_template_but_explicit_news_and_note_win(templates):
    service, news, product = templates
    result = service.create('work', 'version', confirmation())
    context = news.context('news-one', 'p')
    assert context['templates']['poster'][0]['id'] == result['id']
    request = fixture.creation(news, template_id=result['id'], template_revision=result['revision'], note='本轮新原话')
    frozen = news.prepare(request, 'p', 'news-one', 'new-version')
    assert frozen['creation']['template']['revision'] == result['revision']
    assert '本轮新原话' in frozen['input_text'] and '不复用历史新闻事实' in frozen['input_text']
    assert {item['role'] for item in frozen['material_manifest']['files']} >= {'template', 'template-reference', 'source', 'style'}
    # No retries resolve the mutable template, profile, catalog or old artifacts again.
    (news.root / 'skills/builtin/oil-pig-poster/SKILL.md').unlink()
    (news.root / fixture.CATALOG).unlink()
    with news.box.store.connect() as connection:
        connection.execute('DELETE FROM production_templates')
        connection.execute('DELETE FROM articles')
    assert news.prepare(request, 'p', 'news-one', 'new-version') == frozen
    with pytest.raises(CreatorConflict):
        news.prepare(request | {'template_revision': 'b' * 64}, 'p', 'news-one', 'new-version')


def test_template_has_no_authority_to_make_a_discussion_produce(templates):
    service, news, product = templates
    result = service.create('work', 'version', confirmation())
    with pytest.raises(ValueError, match='明确制作'):
        news.prepare(fixture.creation(news, intent='discuss', template_id=result['id'], template_revision=result['revision']), 'p', 'news-one', 'discussion')
    assert not (news.root / 'outputs/_sessions/inputs/discussion').exists()


def test_required_skill_resources_are_part_of_compatibility(templates):
    service, news, product = templates
    skill = news.root / 'skills/builtin/oil-pig-poster/SKILL.md'
    required = skill.parent / 'required.md'
    required.write_text('必要图片规范', encoding='utf-8')
    skill.write_text('---\nname: oil-pig-poster\ndescription: TEMP\nmetadata:\n  openclaw:\n    workbench:\n      resources:\n        - path: skills/builtin/oil-pig-poster/required.md\n          required: true\n---\n规则', encoding='utf-8')
    result = service.create('work', 'version', confirmation())
    assert result['available']
    required.write_text('必要图片规范发生变化', encoding='utf-8')
    assert not service.list('p', 'poster')[0]['available']
    required.unlink()
    assert not service.list('p', 'poster')[0]['available']


def test_template_can_only_reference_this_versions_approved_review_items(templates, monkeypatch):
    service, news, product = templates
    from easel_workbench.features.production_insights.reviews import Service as Reviews
    monkeypatch.setattr(Reviews, 'view', lambda self, wid, vid: {'work_id': wid, 'version_id': vid, 'items': [
        {'id': 'approved-item', 'status': 'approved'}, {'id': 'pending-item', 'status': 'pending'}]})
    for ids in (['pending-item'], ['other-item']):
        with pytest.raises(ValueError, match='已同意'):
            service.create('work', 'version', confirmation(review_item_ids=ids))
    result = service.create('work', 'version', confirmation(review_item_ids=['approved-item']))
    assert result['review_item_ids'] == ['approved-item']
    assert service.get(result['id'], 'p', 'poster')['review_item_ids'] == ['approved-item']
    assert service.materials(result['id'], 'p', 'poster', result['revision'])[0]['review_item_ids'] == ['approved-item']


def test_template_lists_never_read_reference_bytes_and_cache_skill_hash_per_list(templates, monkeypatch):
    service, news, product = templates
    first = service.create('work', 'version', confirmation())
    service.create('work', 'version', confirmation(operation_id='confirm-two', name='第二个优秀模板'))
    original_read, original_skill = Path.read_bytes, service._skill_sha
    calls = []
    def read(path):
        if path.is_relative_to(news.root / 'data/production-insights/templates'):
            pytest.fail('Lightweight list must not read any template reference bytes')
        return original_read(path)
    def skill(skill_id):
        calls.append(skill_id)
        return original_skill(skill_id)
    monkeypatch.setattr(Path, 'read_bytes', read)
    monkeypatch.setattr(service, '_skill_sha', skill)
    assert all(item['available'] for item in service.list('p', 'poster'))
    assert calls == ['oil-pig-poster']
    # Missing files are detected by cheap metadata even in the summary list.
    document = service._document(first['id'], 'p', 'poster')
    service._path(document['references'][0]['path']).unlink()
    assert not next(item for item in service.list('p', 'poster') if item['id'] == first['id'])['available']


def test_same_size_reference_tampering_is_rejected_on_detail_and_freeze(templates):
    service, news, product = templates
    template = service.create('work', 'version', confirmation())
    document = service._document(template['id'], 'p', 'poster')
    reference = service._path(document['references'][0]['path'])
    reference.write_bytes(b'X' * reference.stat().st_size)
    # A summary is deliberately metadata-only; selection/details are strict.
    assert service.list('p', 'poster')[0]['available']
    with pytest.raises(CreatorConflict, match='参考'):
        service.get(template['id'], 'p', 'poster', template['revision'])
    with pytest.raises(CreatorConflict, match='参考'):
        service.materials(template['id'], 'p', 'poster', template['revision'])
