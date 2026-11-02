"""Bounded, content-free request/SQLite observations for external health readers.

No SQL text, parameters, database paths, request bodies or exception messages are
retained. Reads of snapshot() touch only bounded in-memory counters. Cursor calls
are counted as invocations (executemany/executescript each count once), not rows.
query_ms measures SQLite calls; write_tx_ms measures an acquired explicit/implicit
write transaction until commit/rollback/close, excluding time waiting to acquire it.
"""
from collections import OrderedDict, deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import math
import re
import secrets
import sqlite3
import threading
import time

_current = ContextVar('workbench_performance', default=None)
_role = 'unknown'
_lock = threading.Lock()
_routes = OrderedDict()
_recent = deque(maxlen=32)
_active = {}
_writers = {}
_overflow = 0
_roles = {'server', 'worker', 'feedback', 'learning', 'local', 'supervisor', 'auth', 'unknown'}
_limits = {'routes': 64, 'active': 128, 'writers': 128, 'recent': 32}
_integer_fields = {'query_count', 'db_copy_bytes', 'db_copy_count', 'db_copy_blocked', 'db_busy_count'}
_float_fields = {'query_ms', 'write_tx_ms'}


def configure(role):
    """Called by the existing process logger, never by untrusted HTTP input."""
    global _role
    if role not in _roles:
        raise ValueError('Unknown performance role')
    _role = role


def _route(value):
    from easel_workbench.runtime.server_logging import route
    return route(value)


def _emit(event, **metadata):
    # Reuse the existing bounded asynchronous journal; observability cannot fail work.
    try:
        from easel_workbench.runtime.server_logging import emit
        emit(event, **metadata)
    except Exception:
        pass


@dataclass
class Metrics:
    values: dict = field(default_factory=lambda: {**dict.fromkeys(_integer_fields, 0), **dict.fromkeys(_float_fields, 0.0)})
    lock: object = field(default_factory=threading.Lock, repr=False)

    def add(self, **values):
        with self.lock:
            for key, value in values.items():
                if key in self.values and type(value) in (int, float) and math.isfinite(value) and value >= 0:
                    self.values[key] += value

    def read(self):
        with self.lock:
            return {key: int(value) if key in _integer_fields else round(value, 3) for key, value in self.values.items()}


class Span:
    def __init__(self, *, trace_id=None, route='/database', role=None, allow_db_copy=True, phase='request'):
        self.trace_id = trace_id if isinstance(trace_id, str) and re.fullmatch(r'[a-f0-9]{16,64}', trace_id) else secrets.token_hex(8)
        self.route = _route(route)
        self.role = role if role in _roles else _role
        self.parent = _current.get()
        self.allow_db_copy = allow_db_copy is True and (self.parent is None or self.parent.allow_db_copy)
        self.phase = phase if phase in {'request', 'database', 'worker'} else 'request'
        self.started = time.perf_counter()
        self.metrics = Metrics()
        self.status = None
        self.finished = False

    def read(self):
        return {'trace_id': self.trace_id, 'route': self.route, 'role': self.role, 'phase': self.phase,
                'duration_ms': round((time.perf_counter() - self.started) * 1000, 3), **self.metrics.read()}


def _publish(value):
    global _overflow
    value={**value,'at':time.time()}
    with _lock:
        key = (value['role'], value['route'], value['phase'])
        item = _routes.get(key)
        if item is None:
            if len(_routes) >= _limits['routes']:
                _routes.popitem(last=False)
                _overflow += 1
            item = {'role': key[0], 'route': key[1], 'phase': key[2], 'count': 0, 'slow_count': 0,
                    'duration_ms': 0.0, 'max_duration_ms': 0.0, **Metrics().read()}
            _routes[key] = item
        _routes.move_to_end(key)
        item['count'] += 1
        item['slow_count'] += value['duration_ms'] >= 1000
        item['max_duration_ms'] = max(item['max_duration_ms'], value['duration_ms'])
        for field_name in ('duration_ms', *_integer_fields, *_float_fields):
            item[field_name] += value[field_name]
        _recent.append(dict(value))
    _emit('performance_finished', **{key: item for key, item in value.items() if key != 'role'})


@contextmanager
def span(**metadata):
    """asyncio.to_thread propagates this context; plain threads require copy_context()."""
    global _overflow
    item = Span(**metadata)
    token = _current.set(item)
    with _lock:
        if len(_active) < _limits['active']:
            _active[id(item)] = item
        else:
            _overflow += 1
    try:
        yield item
    finally:
        item.finished = True
        _current.reset(token)
        value = item.read()
        if item.parent is not None and not item.parent.finished:
            item.parent.metrics.add(**item.metrics.read())
        if type(item.status) is int:
            value['status'] = item.status
        with _lock:
            _active.pop(id(item), None)
        _publish(value)


def snapshot():
    """A bounded read-only process projection: no DB connection or filesystem scan."""
    with _lock:
        return {'schema_version': 1, 'role': _role, 'limits': dict(_limits), 'overflow': _overflow,
                'routes': [dict(item) for item in _routes.values()], 'recent': [dict(item) for item in _recent],
                'active': [item.read() for item in _active.values()],
                'writers': [{**metadata, 'write_tx_ms': round((time.perf_counter() - started) * 1000, 3)}
                            for started, metadata in _writers.values()]}


class DatabaseCopyForbidden(RuntimeError):
    """A read path attempted a real whole-database backup, before any target write."""


def _command(sql):
    # Inspect only syntax needed for transaction boundaries; never retain SQL.
    head = re.sub(r'\A(?:\s+|--[^\n]*(?:\n|$)|/\*.*?\*/)*', '', sql, flags=re.S)
    first = re.match(r'[A-Za-z]+', head)
    operation = first.group().upper() if first else ''
    return operation, operation == 'BEGIN' and bool(re.match(r'BEGIN\s+(?:IMMEDIATE|EXCLUSIVE)\b', head, re.I))


class PerformanceCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=()):
        return self.connection._call(sql, lambda: super(PerformanceCursor, self).execute(sql, parameters))

    def executemany(self, sql, seq_of_parameters):
        return self.connection._call(sql, lambda: super(PerformanceCursor, self).executemany(sql, seq_of_parameters))

    def executescript(self, sql_script):
        return self.connection._call(sql_script, lambda: super(PerformanceCursor, self).executescript(sql_script))


class PerformanceConnection(sqlite3.Connection):
    """Drop-in factory; desk.Connection retains its existing close-on-exit policy."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._outside = Metrics()
        self._write_started = None
        self._write_owner = None
        self._trace_id = secrets.token_hex(8)
        self._opened = time.perf_counter()
        self._reported = False

    def _record(self, owner=None, **values):
        owner = owner if owner is not None else _current.get()
        (owner.metrics if owner is not None and not owner.finished else self._outside).add(**values)

    def cursor(self, factory=None):
        return super().cursor(factory or PerformanceCursor)

    def execute(self, sql, parameters=()):
        return self.cursor().execute(sql, parameters)

    def executemany(self, sql, seq_of_parameters):
        return self.cursor().executemany(sql, seq_of_parameters)

    def executescript(self, sql_script):
        return self.cursor().executescript(sql_script)

    def _begin_write(self, now):
        global _overflow
        self._write_started = now
        self._write_owner = _current.get()
        metadata = {'trace_id': self._write_owner.trace_id if self._write_owner else self._trace_id,
                    'route': self._write_owner.route if self._write_owner else '/page-or-asset',
                    'role': self._write_owner.role if self._write_owner else _role,'resource_ref':self._trace_id}
        with _lock:
            if len(_writers) < _limits['writers']:
                _writers[id(self)] = (now, metadata)
            else:
                _overflow += 1
        _emit('database_write_started',write_tx_ms=0,**{key:value for key,value in metadata.items() if key!='role'})

    def _end_write(self):
        if self._write_started is None:
            return
        duration = (time.perf_counter() - self._write_started) * 1000
        _emit('database_write_finished',trace_id=self._write_owner.trace_id if self._write_owner else self._trace_id,
              route=self._write_owner.route if self._write_owner else '/page-or-asset',resource_ref=self._trace_id,
              duration_ms=round(duration,3),write_tx_ms=round(duration,3))
        self._record(self._write_owner, write_tx_ms=duration)
        self._write_started = None
        self._write_owner = None
        with _lock:
            _writers.pop(id(self), None)

    def _call(self, sql, call):
        operation, immediate = _command(sql)
        started = time.perf_counter()
        succeeded = False
        self._record(query_count=1)
        try:
            result = call()
            succeeded = True
            return result
        except sqlite3.Error as error:
            if (getattr(error, 'sqlite_errorcode', 0) & 255) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                self._record(db_busy_count=1)
            raise
        finally:
            now = time.perf_counter()
            self._record(query_ms=(now - started) * 1000)
            if not self.in_transaction:
                self._end_write()
            elif succeeded and self._write_started is None and (immediate or operation in {'INSERT', 'UPDATE', 'DELETE', 'REPLACE'}):
                self._begin_write(now)

    def commit(self):
        return self._call('COMMIT', super().commit)

    def rollback(self):
        return self._call('ROLLBACK', super().rollback)

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            if not self.in_transaction:
                self._end_write()

    def close(self):
        if self._reported:
            return super().close()
        try:
            return super().close()
        finally:
            self._end_write()
            self._reported = True
            values = self._outside.read()
            if any(values.values()):
                _publish({'trace_id': self._trace_id, 'route': '/page-or-asset', 'role': _role, 'phase': 'database',
                          'duration_ms': round((time.perf_counter() - self._opened) * 1000, 3), **values})

    def backup(self, target, *, pages=-1, progress=None, name='main', sleep=0.250):
        owner = _current.get()
        if owner is not None and not owner.allow_db_copy:
            self._record(db_copy_blocked=1)
            raise DatabaseCopyForbidden('Whole database copies are forbidden in this scope')
        # Constant-size metadata read, not a scan or an additional backup.
        page_size = sqlite3.Connection.execute(self, 'PRAGMA page_size').fetchone()[0]
        copied = 0

        def observe(status, remaining, total):
            nonlocal copied
            copied = max(copied, max(0, total - remaining) * page_size)
            if progress is not None:
                progress(status, remaining, total)

        self._record(db_copy_count=1)
        started=time.perf_counter()
        _emit('database_copy_started',trace_id=owner.trace_id if owner else self._trace_id,resource_ref=self._trace_id)
        try:
            return super().backup(target, pages=pages, progress=observe, name=name, sleep=sleep)
        finally:
            self._record(db_copy_bytes=copied)
            _emit('database_copy_finished',trace_id=owner.trace_id if owner else self._trace_id,resource_ref=self._trace_id,
                  duration_ms=round((time.perf_counter()-started)*1000,3),db_copy_bytes=copied)
