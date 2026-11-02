"""P2 contracts: real host, unique compatibility exports and rollback after work writes."""
import asyncio
import importlib.util
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('p2_business_fixture', ROOT / 'tests/test_workbench_chat_business.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
business = fixtures.business


def test_legacy_imports_resolve_to_unique_p2_implementations():
    from easel_workbench import chat, chat_api, chat_business, chat_products
    from easel_workbench.application.chat import ChatBusiness
    from easel_workbench.contracts.production import PlanConflict
    from easel_workbench.features.conversations.service import ChatService
    from easel_workbench.features.works.products import ChatProducts
    from easel_workbench.http import chat as http
    assert chat.ChatService is ChatService
    assert chat_business.ChatBusiness is ChatBusiness
    assert chat_business.PlanConflict is PlanConflict
    assert chat_products.ChatProducts is ChatProducts
    assert chat_api.handle is http.handle and chat_api.stream is http.stream


@pytest.mark.parametrize('source', [
    'from easel_workbench.http.chat import handle',
    'def delayed():\n from ...application.chat import ChatBusiness',
    "from importlib import import_module\nimport_module('easel_workbench.chat')",
    'from easel_workbench import chat_business',
    'from easel_workbench.runtime import native_api',
])
def test_feature_boundary_rejects_http_application_and_compat_back_edges(source):
    spec = importlib.util.spec_from_file_location('p2_audit', ROOT / 'scripts/audit_workbench_private_architecture.py')
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    record = audit.inspect_source('easel_workbench/features/works/example.py', source.encode())
    assert any(error['rule'] == 'feature-import-http-application-or-compat'
               for error in audit.boundary_errors(record))


def test_real_http_acceptance_rolls_back_all_work_writes_when_call_registration_fails(business, monkeypatch):
    from easel import harnesses
    from easel_workbench.application import create_app
    from easel_workbench.application.chat import ChatBusiness
    from easel_workbench.features.conversations.service import ChatService
    from easel_workbench.features.works.versions import WorkVersions

    class Auth:
        data = {'origin': 'https://temp.local', 'host': 'temp.local', 'secret': 'A' * 32}
        def session(self, token):
            return {'csrf': 'fixture', 'until': 9999999999} if token == 'fixture-owner' else None

    executions = []
    monkeypatch.setattr(harnesses, 'adapter', lambda runtime: executions.append(runtime))
    app = create_app(root=business.root, store=business.store, box=business.box, auth=Auth())
    service, coordinator = app.state.chat, app.state.chat_business
    assert type(service) is ChatService and type(coordinator) is ChatBusiness
    assert type(coordinator.works) is WorkVersions
    assert service.settings is app.state.settings
    assert service.store is coordinator.store is coordinator.works.store is business.store
    observed = []
    accept = coordinator.works.accept

    def register(connection, plan):
        assert connection.in_transaction
        accept(connection, plan)
        # The failure is deliberately later than real work/version/run writes.
        observed.append(connection.execute('SELECT count(*) FROM toolbox_jobs').fetchone()[0])
    monkeypatch.setattr(coordinator.works, 'accept', register)
    with business.store.connect() as connection:
        connection.execute("""CREATE TRIGGER p2_fail_call BEFORE INSERT ON creator_model_calls
            BEGIN SELECT RAISE(ABORT, 'TEMP call registration rejected'); END""")

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url=Auth.data['origin']) as client:
            client.cookies.set('__Host-desk_session', 'fixture-owner')
            config = (await client.get('/api/config')).json()
            headers = {'Origin': Auth.data['origin'], 'X-CSRF-Token': config['csrf']}
            value = fixtures.value()
            planned = await client.post('/api/chat/plan', json=value, headers=headers)
            assert planned.status_code == 200, planned.text
            value['context']['plan_token'] = planned.json()['plan_token']
            rejected = await client.post('/api/chat/stream', json=value, headers=headers)
            # The established host maps unexpected storage failures to 503.
            assert rejected.status_code == 503, rejected.text
            assert observed == [1] and executions == []
            with business.store.connect() as connection:
                for table in ('easel_chat_turns', 'creator_model_calls', 'toolbox_jobs', 'toolbox_works',
                              'toolbox_review_inputs', 'creator_task_runs'):
                    assert connection.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0, table
            assert service.history('test-chat')['session']['pendingTurnId'] is None
            assert not service._tasks and not service._owned_turns
        await service.close()
    asyncio.run(scenario())
