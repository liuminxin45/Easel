"""Real TEMP chat repositories plus bounded I/O holds and ASGI concurrency."""
import asyncio
import importlib.util
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi import FastAPI, Request

from easel_workbench.chat_api import handle

spec = importlib.util.spec_from_file_location('responsive_chat_fixture', Path(__file__).with_name('test_workbench_chat_business.py'))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
business = fixtures.business


@pytest.mark.parametrize('kind', ['sessions', 'history', 'skills'])
def test_real_chat_io_does_not_block_parallel_health(business, monkeypatch, kind):
    async def scenario():
        entered, release = threading.Event(), threading.Event()
        if kind == 'sessions':
            owner, name, path, value = business.chat, 'list_sessions', '/api/chat/sessions', None
        elif kind == 'history':
            owner, name, path, value = business, 'history', '/api/chat/sessions/test-chat', None
        else:
            from easel_workbench.runtime.native_skills import service as native_skills
            owner, name, path, value = native_skills(business.box,business.chat), 'items', '/api/skills', None
        original = getattr(owner, name)

        def held(*args,**kwargs):
            entered.set()
            assert release.wait(2)
            return original(*args,**kwargs)

        monkeypatch.setattr(owner, name, held)
        app = FastAPI()

        @app.get('/health')
        async def health():
            return {'ok': True}

        @app.api_route('/api/{path:path}', methods=['GET', 'POST'])
        async def chat_route(path: str, request: Request):
            return await handle(business.chat, business, '/api/' + path, request,
                                await request.json() if request.method == 'POST' else None)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://temp.test') as client:
            started = time.monotonic()
            task = asyncio.create_task(client.post(path, json=value) if value else client.get(path))
            try:
                while not entered.is_set():
                    assert time.monotonic() - started < 1
                    await asyncio.sleep(.005)
                assert time.monotonic() - started < .5, 'Chat I/O blocked the application event loop'
                health_started = time.monotonic()
                assert (await client.get('/health')).json() == {'ok': True}
                assert time.monotonic() - health_started < .5
                assert not task.done()
            finally:
                release.set()
            response = await task
            assert response.status_code == 200, response.text
            data = response.json()
            if kind == 'sessions':
                assert data['sessions'][0]['id'] == 'test-chat'
                assert data['sessions'][0]['message_count'] == 0
                assert data['sessions'][0]['linked_works'] == []
            elif kind == 'history':
                assert data['session']['id'] == 'test-chat' and data['session']['messages'] == []
            else:
                assert any(item['name']=='content-production' for item in data)
                assert all('prompt' not in item and 'resources' not in item for item in data)
    asyncio.run(scenario())


def test_question_answer_future_stays_on_application_loop():
    async def scenario():
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def answer(qid, answers, sid, tid):
            assert asyncio.get_running_loop() is loop
            future.set_result(answers)
            return {'ok': True, 'status': 'answered'}

        service = SimpleNamespace(_questions={'question-one': {'session_id': 'test-chat'}}, answer=answer)
        request = SimpleNamespace(method='POST')
        response = await handle(service, None, '/api/chat/question/answer', request,
                                {'id': 'question-one', 'answers': {'choice': ['deny']}})
        assert response.status_code == 200
        assert await future == {'choice': ['deny']}
    asyncio.run(scenario())


class AcceptanceConnection:
    """Observe precisely after the real SQLite commit, before task publication."""
    def __init__(self, connection, after_commit=None, fail=False):
        self.connection, self.after_commit, self.fail = connection, after_commit, fail
        self.accepting = False

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def __enter__(self):
        self.connection.__enter__()
        return self

    def execute(self, sql, *args):
        if sql.startswith('INSERT INTO easel_chat_turns '):
            self.accepting = True
        return self.connection.execute(sql, *args)

    def __exit__(self, kind, error, traceback):
        if self.accepting and self.fail and kind is None:
            error = RuntimeError('TEMP acceptance commit rejected')
            self.connection.__exit__(RuntimeError, error, None)
            raise error
        result = self.connection.__exit__(kind, error, traceback)
        if self.accepting and kind is None and self.after_commit:
            self.after_commit()
        return result


def test_accepted_commit_before_task_registration_is_owned_but_restart_is_unknown(business, monkeypatch):
    from easel import harnesses
    from easel_workbench.chat import ChatService

    class Hold:
        async def run(self, request, emit, ask, bind):
            bind('temp-owned-native')
            request.on_native_turn('temp-owned-native', 'temp-owned-turn')
            await asyncio.Event().wait()

    monkeypatch.setattr(harnesses, 'adapter', lambda runtime: Hold())

    async def scenario():
        service = business.chat
        value = fixtures.value()
        prepared = business.prepare(value)
        connect = service.store.connect
        observations = []
        with ThreadPoolExecutor(max_workers=1) as reader:
            def window():
                assert value['turnId'] not in service._tasks
                observations.append(reader.submit(service.get_turn, value['turnId']).result(timeout=3))
            monkeypatch.setattr(service.store, 'connect', lambda: AcceptanceConnection(connect(), window))
            try:
                turn = await service.submit(value, **prepared)
                assert len(observations) == 1 and observations[0]['status'] == 'accepted'
                assert turn['id'] in service._owned_turns and turn['id'] in service._tasks
                assert service.get_turn(turn['id'])['status'] != 'unknown'
                # A separate service/process owns no marker; durable accepted
                # rows alone still cannot prove execution is running.
                restarted = ChatService(service.box)
                assert restarted.get_turn(turn['id'])['status'] == 'unknown'
            finally:
                await service.close()
        assert not service._owned_turns
    asyncio.run(scenario())


def test_failed_acceptance_commit_clears_transient_owner(business, monkeypatch):
    async def scenario():
        service = business.chat
        value = fixtures.value()
        prepared = business.prepare(value)
        connect = service.store.connect
        monkeypatch.setattr(service.store, 'connect', lambda: AcceptanceConnection(connect(), fail=True))
        with pytest.raises(RuntimeError, match='TEMP acceptance commit rejected'):
            await service.submit(value, **prepared)
        assert not service._owned_turns and not service._tasks
        with connect() as connection:
            assert connection.execute('SELECT COUNT(*) FROM easel_chat_turns').fetchone()[0] == 0
            assert service._session(connection, 'test-chat')['pendingTurnId'] is None
    asyncio.run(scenario())
