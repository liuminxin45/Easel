"""Real SQLite/TEMP concurrency, copy prevention and content-free observations."""
import asyncio
import contextlib
import json
import sqlite3
import threading
import time

import pytest

from easel_workbench.diagnostics import performance as perf
from easel_workbench.runtime import server_logging as journal
from easel_workbench.runtime.desk import Connection


@pytest.fixture(autouse=True)
def observations(monkeypatch):
    events = []
    monkeypatch.setattr(perf, '_emit', lambda event, **fields: events.append({'event': event, **fields}))
    with perf._lock:
        perf._routes.clear(); perf._recent.clear(); perf._active.clear(); perf._writers.clear()
    perf.configure('server')
    yield events
    with perf._lock:
        assert not perf._active and not perf._writers


@pytest.fixture(scope='module')
def large_database(tmp_path_factory):
    # Production stat at audit: 354,398,208 bytes. This TEMP fixture exceeds it.
    path = tmp_path_factory.mktemp('performance-real-scale') / 'scale.sqlite'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE scale(id INTEGER PRIMARY KEY, payload BLOB)')
        connection.executemany('INSERT INTO scale VALUES(?,zeroblob(6291456))', [(i,) for i in range(64)])
    assert path.stat().st_size >= 384 * 1024 * 1024
    return path


def test_large_indexed_read_and_real_whole_database_copy_have_distinct_metrics(large_database, tmp_path):
    with contextlib.closing(sqlite3.connect(large_database, factory=Connection)) as source:
        with perf.span(route='/api/easel/plans', trace_id='1' * 16, allow_db_copy=False) as read:
            assert source.execute('SELECT length(payload) FROM scale WHERE id=?', (30,)).fetchone()[0] == 6291456
        with contextlib.closing(sqlite3.connect(tmp_path / 'copy.sqlite')) as target:
            with perf.span(route='/api/other', trace_id='2' * 16) as copied:
                source.backup(target, pages=16)
            assert target.execute('SELECT count(*) FROM scale').fetchone()[0] == 64
    assert read.metrics.read()['query_count'] == 1
    assert read.metrics.read()['db_copy_bytes'] == 0
    assert copied.metrics.read()['db_copy_bytes'] >= 384 * 1024 * 1024
    assert copied.metrics.read()['db_copy_count'] == 1
    assert read.metrics.read()['write_tx_ms'] == 0


def test_copy_guard_blocks_the_real_backup_before_any_target_write(large_database, tmp_path):
    with contextlib.closing(sqlite3.connect(large_database, factory=Connection)) as source, contextlib.closing(sqlite3.connect(tmp_path / 'forbidden.sqlite')) as target:
        with perf.span(route='/api/easel/plans', allow_db_copy=False) as blocked:
            # A nested observer may not bypass the caller's explicit guard.
            with perf.span(route='/api/easel/plans', allow_db_copy=True):
                with pytest.raises(perf.DatabaseCopyForbidden):
                    source.backup(target)
        assert target.execute('SELECT count(*) FROM sqlite_master').fetchone()[0] == 0
    assert blocked.metrics.read()['db_copy_blocked'] == 1
    assert blocked.metrics.read()['db_copy_count'] == blocked.metrics.read()['db_copy_bytes'] == 0


def test_slow_read_is_not_misclassified_as_a_write_lock_or_copy():
    with contextlib.closing(sqlite3.connect(':memory:', factory=Connection)) as connection:
        connection.create_function('delayed', 1, lambda ignored: time.sleep(.08) or 1)
        with perf.span(route='/api/trends') as measured:
            assert connection.execute('SELECT delayed(?)', ('USER_SECRET_DO_NOT_LOG',)).fetchone()[0] == 1
    metrics = measured.metrics.read()
    assert metrics['query_ms'] >= 60 and metrics['query_count'] == 1
    assert metrics['write_tx_ms'] == metrics['db_copy_bytes'] == 0
    assert 'USER_SECRET_DO_NOT_LOG' not in json.dumps(perf.snapshot())


def test_non_http_writer_is_visible_while_held_and_contender_reports_busy_not_held_time(tmp_path, observations):
    path = tmp_path / 'concurrent.sqlite'
    with sqlite3.connect(path) as setup:
        setup.execute('PRAGMA journal_mode=WAL'); setup.execute('CREATE TABLE state(id INTEGER)')
    entered, release = threading.Event(), threading.Event()
    errors, result = [], {}

    def hold():
        try:
            with sqlite3.connect(path, factory=Connection) as writer:
                writer.execute('BEGIN IMMEDIATE'); writer.execute('INSERT INTO state VALUES(1)')
                entered.set(); assert release.wait(5)
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=hold)
    thread.start(); assert entered.wait(5)
    try:
        with contextlib.closing(sqlite3.connect(path, timeout=.10, factory=Connection)) as contender:
            with perf.span(route='/api/easel/plans', trace_id='3' * 16) as waiting:
                with pytest.raises(sqlite3.OperationalError):
                    contender.execute('BEGIN IMMEDIATE')
        result = waiting.metrics.read()
        active = perf.snapshot()['writers']
        assert len(active) == 1 and active[0]['write_tx_ms'] >= 75
        assert any(event['event'] == 'database_write_started' for event in observations)
        started=next(event for event in observations if event['event']=='database_write_started')
        assert started['write_tx_ms']==0 and started['resource_ref'] and started['trace_id']
        assert not any(event['event'] == 'database_write_finished' for event in observations)
    finally:
        release.set(); thread.join(5)
    assert not thread.is_alive() and not errors
    assert result['db_busy_count'] == 1 and result['query_ms'] >= 75
    assert result['write_tx_ms'] == 0
    standalone = [item for item in perf.snapshot()['recent'] if item['phase'] == 'database']
    assert any(item['write_tx_ms'] >= 75 for item in standalone)
    assert any(event['event'] == 'database_write_finished' for event in observations)
    ended=next(event for event in observations if event['event']=='database_write_finished')
    assert ended['write_tx_ms']>=75 and ended['resource_ref']==started['resource_ref'] and ended['trace_id']==started['trace_id']


def test_context_follows_to_thread_without_mixing_concurrent_requests():
    def database(count):
        with contextlib.closing(sqlite3.connect(':memory:', factory=Connection)) as connection:
            for _ in range(count):
                connection.cursor().execute('SELECT ?', ('PRIVATE ORIGINAL',)).fetchone()

    async def run():
        async def request(trace, count):
            with perf.span(route='/api/trends', trace_id=trace) as item:
                await asyncio.to_thread(database, count)
            return item
        return await asyncio.gather(request('a' * 16, 2), request('b' * 16, 5))

    a, b = asyncio.run(run())
    assert a.metrics.read()['query_count'] == 2 and b.metrics.read()['query_count'] == 5
    assert {item['trace_id'] for item in perf.snapshot()['recent']} == {'a' * 16, 'b' * 16}


def test_snapshot_is_bounded_memory_only_and_journal_never_contains_payloads(tmp_path, monkeypatch):
    for index in range(200):
        # Unknown high-cardinality routes collapse before aggregation.
        with perf.span(route='/api/private-user-' + str(index), trace_id=f'{index:016x}'):
            pass
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, 'connect', lambda *args, **kwargs: pytest.fail('diagnostics opened database'))
        snapshot = perf.snapshot()
    assert len(snapshot['routes']) == 1 and len(snapshot['recent']) == 32
    assert all(type(item['at']) in (int,float) and abs(time.time()-item['at'])<60 for item in snapshot['recent'])
    assert not snapshot['active'] and not snapshot['writers']
    log = journal.Journal(tmp_path / 'logs', 'worker')
    try:
        log.emit('performance_finished', route='/api/easel/plans?SECRET_KEY=hidden', query_count=2,
                 db_copy_bytes=67108864, write_tx_ms=1250.5, trace_id='f' * 16,
                 sql='SELECT SECRET', user_text='PRIVATE ORIGINAL', secret='KEY_MATERIAL')
    finally:
        log.close()
    raw = ''.join(path.read_text(encoding='utf-8') for path in (tmp_path / 'logs').glob('*.jsonl'))
    for secret in ('SECRET', 'PRIVATE ORIGINAL', 'KEY_MATERIAL', 'sql', 'user_text'):
        assert secret not in raw
    events = [json.loads(line) for line in raw.splitlines()]
    row = next(item for item in events if item['event'] == 'performance_finished')
    assert row['query_count'] == 2 and row['db_copy_bytes'] == 67108864 and row['write_tx_ms'] == 1250.5
