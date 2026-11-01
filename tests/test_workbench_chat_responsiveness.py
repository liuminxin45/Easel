"""Real TEMP chat repositories plus bounded I/O holds and ASGI concurrency."""
import asyncio
import importlib.util
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request

from easel_workbench.chat_api import handle

spec = importlib.util.spec_from_file_location('responsive_chat_fixture', Path(__file__).with_name('test_workbench_chat_business.py'))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
business = fixtures.business


@pytest.mark.parametrize('kind', ['sessions', 'history', 'plan'])
def test_real_chat_io_does_not_block_parallel_health(business, monkeypatch, kind):
    async def scenario():
        entered, release = threading.Event(), threading.Event()
        if kind == 'sessions':
            owner, name, path, value = business.chat, 'history', '/api/chat/sessions', None
        elif kind == 'history':
            owner, name, path, value = business, 'history', '/api/chat/sessions/test-chat', None
        else:
            owner, name, path, value = business, 'plan', '/api/chat/plan', fixtures.value()
        original = getattr(owner, name)

        def held(*args):
            entered.set()
            assert release.wait(2)
            return original(*args)

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
                assert data['session_id'] == 'test-chat' and data['turn_id'] == value['turnId']
                repeated = await client.post(path, json=value)
                assert repeated.status_code == 200 and repeated.json() == data
                with business.store.connect() as connection:
                    assert connection.execute('SELECT COUNT(*) FROM easel_chat_plans').fetchone()[0] == 1
                    assert connection.execute('SELECT COUNT(*) FROM toolbox_jobs').fetchone()[0] == 0
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
