"""TEMP SQLite/ASGI concurrency, cancellation and exact-operation regression."""
import asyncio
import sqlite3
import threading
import time

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request

from easel_workbench.runtime.native_api import NativeApi


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class Store:
    def __init__(self, path):
        self.path = path

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=2, factory=Connection)
        connection.row_factory = sqlite3.Row
        return connection


def fixture(tmp_path):
    store = Store(tmp_path / 'receipts.sqlite')
    with store.connect() as connection:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE easel_ui_operations(id TEXT PRIMARY KEY, signature TEXT, result TEXT)')
    api = NativeApi.__new__(NativeApi)
    api.store, api.root = store, tmp_path
    api._write_lock, api._operation = asyncio.Lock(), ''
    app = FastAPI()

    @app.get('/health')
    async def health():
        return {'ok': True}

    return api, app


def request(operation):
    return Request({'type': 'http', 'method': 'POST', 'path': '/api/test-operation',
                    'query_string': b'', 'headers': [(b'x-operation-id', operation.encode())]})


async def ready(event):
    started = time.monotonic()
    while not event.is_set():
        assert time.monotonic() - started < 1, 'Worker did not start without blocking ASGI'
        await asyncio.sleep(.005)
    assert time.monotonic() - started < .5, 'Synchronous work blocked the event loop'


async def probe(app):
    started = time.monotonic()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://temp.test') as client:
        assert (await client.get('/health')).json() == {'ok': True}
    assert time.monotonic() - started < .5


def test_actual_sqlite_writer_contention_does_not_block_health(tmp_path):
    async def scenario():
        api, app = fixture(tmp_path)
        locked = api.store.connect()
        locked.execute('BEGIN IMMEDIATE')
        attempted = threading.Event()
        original = api._reserve_operation

        def reserve(*args):
            attempted.set()
            return original(*args)

        api._reserve_operation = reserve
        task = asyncio.create_task(api._mutate(request('sqlite-wait'), {}, lambda value: {'ok': True}))
        try:
            await ready(attempted)
            await probe(app)
            assert not task.done()
        finally:
            locked.rollback()
            locked.close()
        assert await task == {'ok': True}
        assert api.receipt('sqlite-wait')['state'] == 'completed'
    asyncio.run(scenario())


@pytest.mark.parametrize('route', ['/api/trends', '/api/output-context'])
def test_native_slow_reads_do_not_block_health(tmp_path, route):
    async def scenario():
        api, app = fixture(tmp_path)
        entered, release = threading.Event(), threading.Event()

        def slow(*args):
            entered.set()
            assert release.wait(2)
            return {'source': 'exact-temp'} if route.endswith('trends') else []

        if route.endswith('trends'):
            api._trends = slow
        else:
            api._work_tree = slow
        scope = {'type': 'http', 'method': 'GET', 'path': route, 'query_string': b'', 'headers': []}
        task = asyncio.create_task(api.dispatch(route, Request(scope), {}))
        try:
            await ready(entered)
            await probe(app)
            assert not task.done()
        finally:
            release.set()
        await task
    asyncio.run(scenario())


def test_cancelled_sync_action_keeps_identity_and_lock_until_worker_finishes(tmp_path):
    async def scenario():
        api, app = fixture(tmp_path)
        entered, release = threading.Event(), threading.Event()
        calls = []

        def first(fields):
            entered.set()
            assert release.wait(2)
            calls.append(api._operation)
            return {'made': 'first'}

        task = asyncio.create_task(api._mutate(request('original-once'), {}, first))
        following = None
        try:
            await ready(entered)
            task.cancel()
            await asyncio.sleep(.01)
            task.cancel()  # Repeated disconnect must not release the owner early.
            following = asyncio.create_task(api._mutate(request('following'), {}, lambda _: calls.append(api._operation) or {'made': 'second'}))
            await probe(app)
            await asyncio.sleep(.02)
            assert api._operation == 'original-once' and api._write_lock.locked()
            assert not task.done() and not following.done() and not calls
            assert api.receipt('original-once')['state'] == 'unavailable'
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await following == {'made': 'second'}
        assert calls == ['original-once', 'following']
        assert api.receipt('original-once')['state'] == 'unavailable'
        with pytest.raises(HTTPException) as error:
            await api._mutate(request('original-once'), {}, first)
        assert error.value.status_code == 409 and calls == ['original-once', 'following']
    asyncio.run(scenario())


def test_original_async_action_stays_on_application_loop_and_reuses_receipt(tmp_path):
    async def scenario():
        api, _ = fixture(tmp_path)
        loop, calls = asyncio.get_running_loop(), []

        async def action(fields):
            assert asyncio.get_running_loop() is loop
            calls.append(api._operation)
            return {'value': fields['value']}

        for _ in range(2):
            assert await api._mutate(request('async-once'), {'value': 'original'}, action) == {'value': 'original'}
        assert calls == ['async-once'] and api._operation == ''
        with pytest.raises(HTTPException) as error:
            await api._mutate(request('async-once'), {'value': 'changed'}, action)
        assert error.value.status_code == 409
    asyncio.run(scenario())
