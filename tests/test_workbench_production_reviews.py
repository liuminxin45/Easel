"""Exact delivery, durable inference and human review using TEMP SQLite/files."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('production_review_fixture', Path(__file__).with_name('test_workbench_skill_commands.py'))
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
runtime, commands = fixture.runtime, fixture.commands

from easel_workbench.features.production_insights import contracts
from easel_workbench.features.production_insights.reviews import Service, TABLE, service
from easel_workbench.runtime.feedback_ledger import atomic


def seed(box, *, skill='oil-pig-poster', vid='version-review', text='请做一张贴图', output='已交付真实文件'):
    sid = 'session-review'; wid = 'native-'+vid
    turn = {'id': vid, 'session_id': sid, 'status': 'completed', 'native_turn_id': 'native-'+vid,
            'created_at': '2026-11-06T10:00:00+08:00', 'message': text, 'actual_prompt': text+'\n准确冻结材料',
            'actual_prompt_sha256': 'a'*64, 'frozen_instructions': '只执行所选技能', 'output': output,
            'runtime': 'codex', 'model': 'gpt-6.1-sol'}
    receipt = {'status': 'completed', 'whole_ready': True, 'skill_id': skill, 'version_id': vid,
               'work_id': wid, 'session_id': sid, 'profile_id': 'oil-pig', 'profile_revision': 1,
               'format': 'article' if skill == 'oil-pig-article' else 'poster'}
    path = box.root/'data/artifacts'/vid/'标题与配文.txt'; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('准确标题\n准确正文', encoding='utf-8')
    with box.store.connect() as c:
        c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)', ('artifact-'+vid, vid, path.name, str(path), 'text/plain'))
        c.execute('CREATE TABLE IF NOT EXISTS easel_chat_turns(id TEXT PRIMARY KEY,session_id TEXT,operation_id TEXT,signature TEXT,document TEXT)')
        c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)', (vid, sid, 'operation-'+vid, 'signature', json.dumps(turn, ensure_ascii=False)))
    return turn, receipt


def answer(value, part):
    source = part['sources'][0]['source_id'] if part['sources'] else part['images'][0]['id']
    return {'summary': '这段准确材料的复盘', 'items': [{'title': '可复用制作步骤', 'lesson': '先明确主题，再输出准确配文',
            'category': 'process', 'source_ids': [source], 'basis': 'ai_suggestion'}]}


def finish(instance):
    for _ in range(30):
        if not instance.run_pending_once():
            break


@pytest.mark.parametrize('skill', ['oil-pig-poster', 'oil-pig-article'])
def test_exact_completed_product_enqueues_once_without_changing_skills(commands, skill):
    turn, receipt = seed(commands, skill=skill)
    instance = Service(commands, execute=answer)
    assert instance.enqueue(turn, {**receipt, 'whole_ready': False}) is None
    assert instance.enqueue({**turn, 'status': 'unknown'}, receipt) is None
    assert instance.enqueue(turn, {**receipt, 'skill_id': 'oil-pig-learn-poster'}) is None
    assert instance.enqueue(turn, receipt)['status'] == 'queued'
    assert instance.enqueue(turn, receipt)['status'] == 'queued'
    with pytest.raises(ValueError, match='不能替换'):
        instance.enqueue({**turn, 'output': '不同的回执'}, receipt)
    finish(instance)
    view = instance.view(receipt['work_id'], turn['id'])
    assert view['status'] == 'completed' and len(view['items']) == 1
    assert view['items'][0]['status'] == 'pending'
    assert view['parts_completed'] == view['parts_total']
    assert 'target_turn' not in view and 'parts' not in view
    assert instance.view('wrong-work', turn['id'])['status'] == 'not_requested'
    assert instance.master(skill)['text'].count('### 可复用制作步骤') == 1


def test_entire_conversation_is_segmented_without_silent_truncation(commands):
    long = '完整会话原文。'*18000
    turn, receipt = seed(commands, text=long)
    previous = {'id': 'before', 'session_id': turn['session_id'], 'message': '之前用户明确要求红围巾', 'output': '讨论稿'}
    with commands.store.connect() as c:
        # Keep the actual row order of a preceding conversation.
        c.execute('DELETE FROM easel_chat_turns')
        c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)', ('before', turn['session_id'], 'previous-op', 's', json.dumps(previous)))
        c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)', (turn['id'], turn['session_id'], 'new-op', 's', json.dumps(turn)))
        c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)', ('later', turn['session_id'], 'later-op', 's', json.dumps({**previous, 'id': 'later', 'message': '后来不相关'})))
    instance = Service(commands, execute=answer); instance.enqueue(turn, receipt)
    instance.run_pending_once()
    with commands.store.connect() as c:
        value = json.loads(c.execute('SELECT document FROM '+TABLE).fetchone()[0])
    supplied = ''.join(item['text'] for part in value['parts'] for item in instance._part_sources(value, part) if item['source_id'] == 'turn:'+turn['id']+':message')
    assert supplied == long
    assert value['coverage']['conversation_turns'] == 2 and value['parts_total'] > 4
    assert all(sum(len(item['text']) for item in instance._part_sources(value, part)) <= 48000 for part in value['parts'])
    assert len(json.dumps(value, ensure_ascii=False)) < 30000
    assert not any(source['id'].startswith('turn:later:') for source in value['sources'])


def test_human_decisions_and_raw_feedback_have_durable_per_item_receipts(commands):
    turn, receipt = seed(commands); instance = Service(commands, execute=answer)
    instance.enqueue(turn, receipt); finish(instance)
    wid, vid = receipt['work_id'], turn['id']; item = instance.view(wid, vid)['items'][0]
    result = instance.decide(wid, vid, {'id': item['id'], 'operation_id': 'approve-review', 'decision': 'approve', 'note': '这条有效，待开发落实'})
    assert result['status'] == 'approved'
    assert instance.decide(wid, vid, {'id': item['id'], 'operation_id': 'approve-review', 'decision': 'approve', 'note': '这条有效，待开发落实'}) == result
    assert Service(commands).operation_result('approve-review') == result
    with pytest.raises(ValueError, match='同一核销'):
        instance.decide(wid, vid, {'id': item['id'], 'operation_id': 'approve-review', 'decision': 'reject'})
    with pytest.raises(ValueError, match='可核验'):
        instance.decide(wid, vid, {'id': item['id'], 'operation_id': 'fake-applied', 'decision': 'applied'})
    assert instance.view(wid, vid)['items'][0]['status'] == 'approved'
    with commands.store.connect() as c:
        c.execute("INSERT INTO toolbox_jobs(id,work_id,kind,text,candidate_id,files,scope,signature,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  ('raw-feedback', wid, 'feedback', '用户原话：画面特别好，但是标题不采纳。', vid, '[]', '[]', 's', 'completed', '2026-11-06'))
    master = instance.master('oil-pig-poster')['text']
    assert '同意，待实施' in master and '画面特别好，但是标题不采纳。' in master and '这条有效，待开发落实' in master
    source = instance.view(wid, vid)['sources'][0]
    assert instance.source(wid, vid, source['id'])['text']
    with pytest.raises(ValueError):
        instance.source('wrong-work', vid, source['id'])


def test_background_feedback_projection_is_incremental_and_never_reinvokes_ai(commands):
    turn, receipt = seed(commands); instance = Service(commands, execute=answer)
    instance.enqueue(turn, receipt); finish(instance)
    instance.execute = lambda *a: pytest.fail('new feedback must not call AI')
    assert instance.refresh_feedback() == 0
    with commands.store.connect() as c:
        c.execute("INSERT INTO toolbox_jobs(id,work_id,kind,text,candidate_id,files,scope,signature,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  ('later-feedback', receipt['work_id'], 'feedback', '交付后新增的用户原文', turn['id'], '[]', '[]', 's', 'completed', '2026-11-06'))
    assert instance.refresh_feedback() == 1
    assert '交付后新增的用户原文' in (instance.directory/'oil-pig-poster.md').read_text(encoding='utf-8')
    assert instance.refresh_feedback() == 0


def test_unknown_request_is_never_replayed_and_original_completion_can_reconcile(commands):
    turn, receipt = seed(commands); calls = []
    def lost(value, part):
        calls.append(part['receipt_id']); raise ConnectionError('lost ACK')
    instance = Service(commands, execute=lost); instance.enqueue(turn, receipt)
    assert instance.run_pending_once()
    assert instance.view(receipt['work_id'], turn['id'])['status'] == 'unknown'
    assert not instance.run_pending_once() and len(calls) == 1
    with commands.store.connect() as c:
        value = json.loads(c.execute('SELECT document FROM '+TABLE).fetchone()[0])
    part = value['parts'][0]
    atomic(commands.root/'data/readonly-receipts'/(part['receipt_id']+'.json'),
           {'status': 'completed', 'model_output_text': json.dumps(answer(value, part))})
    assert instance.run_pending_once()
    assert instance.view(receipt['work_id'], turn['id'])['status'] == 'completed'
    assert len(calls) == 1


def test_crash_after_claim_before_receipt_never_creates_a_second_request(commands):
    turn, receipt = seed(commands); instance = Service(commands, execute=lambda *a: pytest.fail('must not replay'))
    instance.enqueue(turn, receipt)
    with commands.store.connect() as c:
        value = json.loads(c.execute('SELECT document FROM '+TABLE).fetchone()[0])
        value = instance._freeze(value); value['parts'][0]['status'] = 'running'; value['status'] = 'running'; instance._put(c, value)
    instance.run_pending_once()
    assert instance.view(receipt['work_id'], turn['id'])['status'] == 'unknown'


def test_fabricated_evidence_is_blocked_without_claiming_a_successful_review(commands):
    turn, receipt = seed(commands)
    def invalid(value, part):
        result = answer(value, part); result['items'][0]['source_ids'] = ['invented-source']; return result
    instance = Service(commands, execute=invalid); instance.enqueue(turn, receipt); instance.run_pending_once()
    view = instance.view(receipt['work_id'], turn['id'])
    assert view['status'] == 'blocked' and view['items'] == []
    assert '未提供的来源' in view['error']


def test_missing_product_blocks_once_and_pending_finish_hook_defers_model(commands):
    turn, receipt = seed(commands); instance = Service(commands, execute=lambda *a: pytest.fail('must defer'))
    instance.enqueue(turn, receipt)
    with commands.store.connect() as c:
        c.execute('UPDATE easel_chat_turns SET document=? WHERE id=?', (json.dumps({**turn, 'hook_status': 'running'}), turn['id']))
    assert not instance.run_pending_once()
    with commands.store.connect() as c:
        c.execute('UPDATE easel_chat_turns SET document=? WHERE id=?', (json.dumps({**turn, 'hook_status': 'completed'}), turn['id']))
        path = c.execute('SELECT path FROM artifacts WHERE task_id=?', (turn['id'],)).fetchone()[0]
    Path(path).unlink()
    assert instance.run_pending_once()
    assert instance.view(receipt['work_id'], turn['id'])['status'] == 'blocked'
    assert not instance.run_pending_once()


def test_pending_hook_does_not_block_later_complete_product_reviews(commands):
    first, receipt = seed(commands, vid='pending-hook')
    second, ready = seed(commands, vid='ready-hook')
    instance = Service(commands, execute=answer)
    instance.enqueue(first, receipt); instance.enqueue(second, ready)
    with commands.store.connect() as c:
        c.execute('UPDATE easel_chat_turns SET document=? WHERE id=?', (json.dumps({**first, 'hook_status': 'running'}), first['id']))
    assert instance.run_pending_once()
    assert instance.view(ready['work_id'], second['id'])['status'] == 'completed'
    assert instance.view(receipt['work_id'], first['id'])['status'] == 'queued'


def test_deployment_fence_prevents_new_inference_and_factory_initializes_before_txn(commands):
    turn, receipt = seed(commands); instance = service(commands)
    assert instance is service(commands)
    instance.execute = lambda *args: pytest.fail('deployment fence must prevent a call')
    instance.allowed = lambda: False
    with commands.store.connect() as c:
        c.execute('BEGIN IMMEDIATE'); instance.enqueue(turn, receipt, c=c)
    assert not instance.run_pending_once()
    assert instance.view(receipt['work_id'], turn['id'])['status'] == 'queued'


def test_gate_closing_after_claim_defers_unattempted_request(commands):
    turn, receipt = seed(commands); checks = iter([True, True, False])
    instance = Service(commands, execute=lambda *a: pytest.fail('must not start after fence'), allowed=lambda: next(checks))
    instance.enqueue(turn, receipt)
    assert not instance.run_pending_once()
    assert instance.view(receipt['work_id'], turn['id'])['status'] == 'queued'
    with commands.store.connect() as c:
        doc = json.loads(c.execute('SELECT document FROM '+TABLE).fetchone()[0])
    assert doc['parts'][0]['status'] == 'queued' and not instance._receipt(doc['parts'][0])


@pytest.mark.parametrize('runtime_name,model,settings,expected', [
    ('codex', 'gpt-5-codex', {}, 'gpt-5-codex'),
    ('api', 'different-provider-model', {'models': {'codex': 'gpt-5'}}, 'gpt-5'),
    ('api', 'different-provider-model', {}, None),
])
def test_native_readonly_transport_retains_observed_call_and_exact_receipt_identity(commands, monkeypatch, runtime_name, model, settings, expected):
    turn, receipt = seed(commands); instance = Service(commands)
    turn.update(runtime=runtime_name, model=model, execution_settings=settings)
    from easel_workbench import readonly_runner
    calls = []
    def native(binding, arguments, **kwargs):
        assert contracts.is_snapshot(binding) and binding['skills'] == []
        assert kwargs['receipt_id'] and kwargs['runtime_root'] == commands.root
        assert ('--model' in arguments) is (expected is not None)
        if expected is not None:
            assert arguments[arguments.index('--model')+1] == expected
        payload = json.loads(kwargs['input'].split('本次仅资料：\n', 1)[1])
        result = {'summary': '只读结果', 'items': [{'title': '准确建议', 'lesson': '保留原文', 'category': 'process',
                  'source_ids': [payload['sources'][0]['source_id']], 'basis': 'ai_suggestion'}]}
        Path(kwargs['cwd'], 'answer.json').write_text(json.dumps(result), encoding='utf-8')
        calls.append(kwargs['receipt_id'])
        return SimpleNamespace(execution_receipt={'id': kwargs['receipt_id'], 'status': 'completed'})
    monkeypatch.setattr(readonly_runner, 'run', native)
    instance.enqueue(turn, receipt); finish(instance)
    assert len(calls) == 1
    with commands.store.connect() as c:
        document = json.loads(c.execute('SELECT document FROM creator_model_calls WHERE id=?', ('production-review-'+calls[0],)).fetchone()[0])
    assert document['status'] == 'completed' and document['task'] == 'production_review'
    assert document['output']['execution_receipt']['id'] == calls[0]


def test_confirmed_template_is_real_per_item_application_evidence(commands):
    from easel_workbench.features.production_insights.templates import Service as Templates
    from easel_workbench.features.news_creation import CATALOG
    turn, receipt = seed(commands); instance = Service(commands, execute=answer)
    instance.enqueue(turn, receipt); finish(instance)
    wid, vid = receipt['work_id'], turn['id']; item = instance.view(wid, vid)['items'][0]
    instance.decide(wid, vid, {'item_id': item['id'], 'operation_id': 'approve-for-template', 'decision': 'approve'})
    skill = commands.root/'skills/builtin/oil-pig-poster/SKILL.md'; skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text('---\nname: oil-pig-poster\ndescription: TEMP\n---\n原生制作流程', encoding='utf-8')
    before = skill.read_bytes()
    catalog = commands.root/CATALOG; catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text(json.dumps({'schema_version': 1, 'components': [], 'packs': []}), encoding='utf-8')
    with commands.store.connect() as c:
        c.execute('INSERT INTO toolbox_meta VALUES(?,?)', ('native-review:'+vid, json.dumps({'receipt': receipt, 'files': []})))
    templates = Templates(commands)
    template = templates.create(wid, vid, {'operation_id': 'actual-template', 'name': '准确模板', 'method': '先明确主题，再输出准确配文',
                                         'reference_ids': [], 'review_item_ids': [item['id']], 'confirmed': True})
    first = instance.mark_template_applied(template)
    assert first[0]['status'] == 'applied' and instance.mark_template_applied(template) == first
    applied = instance.view(wid, vid)['items'][0]
    assert applied['applied_evidence']['template_id'] == template['id']
    assert '已落地' in instance.master('oil-pig-poster')['text']
    assert skill.read_bytes() == before
