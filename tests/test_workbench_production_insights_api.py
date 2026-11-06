"""Private review routes through actual authentication and delivery transactions."""
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

spec = importlib.util.spec_from_file_location('review_api_fixture', Path(__file__).with_name('test_workbench_production_reviews.py'))
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
runtime, commands, seed, answer, finish = fixture.runtime, fixture.commands, fixture.seed, fixture.answer, fixture.finish


class Auth:
    data = {'origin': 'https://temp.local', 'host': 'temp.local', 'secret': 'A'*32}
    def session(self, token):
        return {'csrf': 'fixture', 'until': 9999999999} if token == 'fixture-owner' else None


def test_actual_private_api_auth_csrf_identity_and_receipt_reuse(commands, monkeypatch):
    from easel_workbench.runtime.toolbox_server import create_app
    async def scenario():
        app = create_app(store=commands.store, auth=Auth(), box=commands, root=commands.root)
        turn, receipt = seed(commands)
        hub = app.state.production_insights; hub.reviews.execute = answer
        hub.metrics.fetch = lambda: pytest.fail('review requests must not collect statistics')
        hub.reviews.enqueue(turn, receipt); finish(hub.reviews)
        item = hub.reviews.view(receipt['work_id'], turn['id'])['items'][0]
        url = '/api/production-insights/works/'+receipt['work_id']+'/versions/'+turn['id']
        count = []; original = hub.reviews.decide
        def decide(*args):
            count.append(1); return original(*args)
        monkeypatch.setattr(hub.reviews, 'decide', decide)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://temp.local') as client:
            assert (await client.get(url+'/review')).status_code == 401
            value = {'id': 'review-http-once', 'item_id': item['id'], 'decision': 'approve', 'note': '准确原文'}
            client.cookies.set('__Host-desk_session', 'fixture-owner')
            assert (await client.post(url+'/decisions', json=value)).status_code == 403
            csrf = (await client.get('/api/config')).json()['csrf']
            headers = {'Origin': 'https://temp.local', 'X-CSRF-Token': csrf, 'X-Operation-ID': value['id']}
            first = await client.post(url+'/decisions', json=value, headers=headers)
            assert first.status_code == 200, first.text
            assert first.json()['item_id'] == item['id'] and first.json()['operation_id'] == value['id']
            assert first.json()['status'] == 'approved'
            again = await client.post(url+'/decisions', json=value, headers=headers)
            assert again.status_code == 200 and again.json() == first.json() and len(count) == 1
            recovery = await client.get('/api/production-insights/operations/'+value['id'])
            assert recovery.json()['state'] == 'completed' and recovery.json()['result'] == first.json()
            current = await client.get(url+'/review')
            assert current.status_code == 200 and current.json()['review']['items'][0]['status'] == 'approved'
            conflict = await client.post(url+'/decisions', json={**value, 'note': '替换原话'}, headers=headers)
            assert conflict.status_code in (400, 409) and len(count) == 1
            wrong_op = await client.post(url+'/decisions', json=value, headers={**headers, 'X-Operation-ID': 'another-operation'})
            assert wrong_op.status_code == 409 and len(count) == 1
            source_id = current.json()['review']['sources'][0]['id']
            source = await client.get(url+'/sources/'+source_id)
            assert source.status_code == 200 and source.json()['text']
            master = await client.get('/api/production-insights/skills/oil-pig-poster/master')
            assert master.status_code == 200 and '同意，待实施' in master.json()['text']
        await app.state.chat.close()
    asyncio.run(scenario())


def test_lost_wrapper_ack_recovers_domain_receipt_without_reapplying(commands, monkeypatch):
    from easel_workbench.runtime.toolbox_server import create_app
    async def scenario():
        app = create_app(store=commands.store, auth=Auth(), box=commands, root=commands.root)
        turn, receipt = seed(commands); hub = app.state.production_insights
        hub.reviews.execute = answer; hub.reviews.enqueue(turn, receipt); finish(hub.reviews)
        item = hub.reviews.view(receipt['work_id'], turn['id'])['items'][0]
        original = hub.reviews.decide; count = []
        def committed_but_ack_lost(*args):
            count.append(1); original(*args); raise ConnectionError('reply channel lost after durable commit')
        monkeypatch.setattr(hub.reviews, 'decide', committed_but_ack_lost)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url='https://temp.local') as client:
            client.cookies.set('__Host-desk_session', 'fixture-owner')
            op = 'committed-review-no-ack'; url = '/api/production-insights/works/'+receipt['work_id']+'/versions/'+turn['id']+'/decisions'
            csrf = (await client.get('/api/config')).json()['csrf']
            headers = {'Origin': 'https://temp.local', 'X-CSRF-Token': csrf, 'X-Operation-ID': op}
            result = await client.post(url, headers=headers, json={'id': op, 'item_id': item['id'], 'decision': 'approve'})
            assert result.status_code >= 500
            recovery = await client.get('/api/production-insights/operations/'+op)
            assert recovery.status_code == 200 and recovery.json()['state'] == 'completed'
            assert recovery.json()['result']['status'] == 'approved'
            assert len(count) == 1
            again = await client.post(url, headers=headers, json={'id': op, 'item_id': item['id'], 'decision': 'approve'})
            assert again.status_code == 200 and len(count) == 1
        await app.state.chat.close()
    asyncio.run(scenario())


def test_product_registration_and_new_review_outbox_roll_back_together(commands, monkeypatch):
    from easel_workbench.features.works import native_review
    from easel_workbench.features.production_insights.reviews import service, TABLE
    from easel_workbench.runtime import production_outcome
    business = SimpleNamespace(root=commands.root, store=commands.store, box=commands,
                               _session=lambda value: {'profile_id': 'oil-pig'})
    frame = native_review.binding(business, {'turnId': 'atomic-review-turn', 'sessionId': 'atomic-review-session',
                                            'context': {'skill_id': 'oil-pig-poster'}})
    directory = Path(frame['product_directory']); directory.mkdir(parents=True)
    path = directory/'标题与配文.txt'; path.write_text('准确标题\n准确配文', encoding='utf-8')
    turn = {'id': frame['version_id'], 'session_id': frame['session_id'], 'status': 'completed', 'message': '制作贴图',
            'actual_prompt_sha256': 'a'*64, 'native_turn_id': 'actual-native-turn', 'created_at': '2026-11-06',
            'output': '[配文]('+path.as_posix()+')', 'frozen_instructions': native_review.instructions(frame)}
    # Quality assessment itself has separate tests. This fixture exercises the
    # transaction after a producer has delivered its declared complete scopes.
    monkeypatch.setattr(production_outcome, 'assess', lambda *a: {'status': 'completed', 'available_scopes': ['images', 'copy']})
    monkeypatch.setattr(production_outcome, 'record', lambda *a: None)
    reviews = service(commands); original = reviews.enqueue
    def fail_after_outbox(*args, **kwargs):
        original(*args, **kwargs); raise ValueError('simulated transaction failure after enqueue')
    monkeypatch.setattr(reviews, 'enqueue', fail_after_outbox)
    with pytest.raises(ValueError, match='simulated transaction'):
        native_review.receive(business, turn)
    with commands.store.connect() as c:
        assert c.execute('SELECT count(*) FROM '+TABLE+' WHERE id=?', (turn['id'],)).fetchone()[0] == 0
        assert c.execute('SELECT count(*) FROM toolbox_jobs WHERE id=?', (turn['id'],)).fetchone()[0] == 0
        assert 'receipt' not in json.loads(c.execute('SELECT value FROM toolbox_meta WHERE key=?', ('native-review:'+turn['id'],)).fetchone()[0])
        # Captured originals precede the version transaction and survive failure.
        assert c.execute('SELECT count(*) FROM artifacts WHERE task_id=?', (turn['id'],)).fetchone()[0] == 1
    assert path.read_text(encoding='utf-8') == '准确标题\n准确配文'
    monkeypatch.setattr(reviews, 'enqueue', original)
    receipt = native_review.receive(business, turn)
    assert receipt['whole_ready'] and reviews.view(frame['work_id'], turn['id'])['status'] == 'queued'
    native_review.receive(business, turn)
    with commands.store.connect() as c:
        assert c.execute('SELECT count(*) FROM '+TABLE+' WHERE id=?', (turn['id'],)).fetchone()[0] == 1
