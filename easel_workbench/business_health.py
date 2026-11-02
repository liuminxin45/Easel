"""Content-free, read-only business progress beside transport liveness.

This projection never opens a service, runs a queue, changes a receipt or asks
the supervisor to restart anything. A live process is not a successful cycle.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
import re
import sqlite3
import time

_FILES = {'worker': 'data/worker-status.json', 'collector': 'data/collection/heartbeat.json',
          'feedback': 'data/news-feedback-worker.json', 'learning': 'data/learning/heartbeat.json',
          'local': 'data/local-operations/heartbeat.json', 'overviews': 'data/news-overviews-status.json'}
_OK = frozenset(('watching', 'idle', 'waiting', 'working', 'polling', 'running', 'preflight', 'dispatched', 'ready', 'completed'))
_BAD = frozenset(('blocked', 'error', 'failed', 'stopped'))


def _json(path):
    if path.is_symlink() or path.stat().st_size > 128 * 1024:
        raise ValueError('invalid_status_file')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('invalid_status_document')
    return value


def _at(value):
    if type(value) in (float, int):
        return float(value) if math.isfinite(value) and value >= 0 else None
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is not None:
                return parsed.timestamp()
        except (ValueError, OverflowError):
            pass
    return None


def _error(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', value) else None


def _signal(document, now, max_age, release):
    stamp = _at(document.get('heartbeat_epoch', document.get('heartbeat', document.get('at', document.get('last_seen_at')))))
    if stamp is None:
        return {'status': 'unknown', 'ok': None, 'reason': 'missing_progress_timestamp'}
    age = now - stamp
    if age < -30:
        return {'status': 'unknown', 'ok': None, 'reason': 'future_progress_timestamp'}
    result = {'age_seconds': round(max(0, age), 2)}
    if document.get('release') and release and document['release'] != release:
        return {**result, 'status': 'unknown', 'ok': None, 'reason': 'different_release'}
    if age > max_age:
        return {**result, 'status': 'stale', 'ok': False, 'reason': 'progress_expired'}
    state = document.get('state')
    if state in _OK:
        result['progress'] = state
    error_type = _error(document.get('error_type', document.get('last_error_type')))
    success = _at(document.get('last_success_at', document.get('last_cycle_success_at')))
    failure = _at(document.get('last_error_at'))
    if state in _BAD or error_type and (success is None or failure is None or failure >= success):
        return {**result, 'status': 'degraded', 'ok': False, 'reason': 'cycle_failed',
                **({'error_type': error_type} if error_type else {})}
    if state in ('disabled', 'paused') or document.get('enabled') is False:
        return {**result, 'status': 'paused', 'ok': True}
    if state in _OK or success is not None:
        return {**result, 'status': 'healthy', 'ok': True}
    return {**result, 'status': 'unknown', 'ok': None, 'reason': 'missing_cycle_outcome'}


def _publisher(root):
    # Do not instantiate DistributionService/Store: constructors migrate/write.
    database = root / 'data/desk.sqlite'
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=.05) as connection:
        connection.execute('PRAGMA query_only=ON')
        enabled = connection.execute("SELECT count(*) FROM distribution_connections WHERE json_extract(document,'$.enabled')=1").fetchone()[0]
        if not enabled:
            return None
        row = connection.execute("SELECT document FROM distribution_runners WHERE id='distribution-local'").fetchone()
        document = json.loads(row[0]) if row else {}
        if not isinstance(document, dict):
            raise ValueError('invalid_runner_document')
        return document


def _collection(root):
    """Project latest task outcomes for current enabled source revisions only."""
    config = _json(root / 'data/collection-config.json')
    if type(config.get('enabled', False)) is not bool:
        raise ValueError('invalid_collection_enabled')
    if config.get('enabled') is not True:
        return {'enabled_source_count': 0, 'latest_failed_source_count': 0,
                'latest_partial_source_count': 0, 'unobserved_source_count': 0}
    baseline = root / 'sources.json'
    if not baseline.is_file():
        baseline = Path(__file__).resolve().parent / 'runtime/sources.json'
    sources = {key: {'revision': 0, 'enabled': True, 'builtin': True} for key in _json(baseline)}
    plans = root / 'collection_schedules.json'
    if not plans.is_file():
        plans = Path(__file__).resolve().parent / 'runtime/collection_schedules.json'
    scheduled = _json(plans).get('sources', {})
    overrides = config.get('sources', {})
    if not isinstance(overrides, dict) or not isinstance(scheduled, dict):
        raise ValueError('invalid_source_configuration')
    with sqlite3.connect((root / 'data/desk.sqlite').as_uri() + '?mode=ro', uri=True, timeout=.05) as connection:
        connection.execute('PRAGMA query_only=ON')
        for source, revision, payload in connection.execute('''SELECT v.source_id,v.revision,v.payload FROM collection_source_versions v
                JOIN (SELECT source_id,MAX(revision) revision FROM collection_source_versions GROUP BY source_id) latest
                USING(source_id,revision)'''):
            entry = json.loads(payload)
            if not isinstance(entry, dict):
                raise ValueError('invalid_source_version')
            sources[source] = {key: entry.get(key) for key in ('enabled', 'deleted', 'builtin')}
            sources[source]['revision'] = revision
        enabled = {}
        for source, entry in sources.items():
            override = overrides.get(source, {})
            if not isinstance(override, dict):
                raise ValueError('invalid_source_override')
            active = entry['enabled'] if entry['revision'] else override.get('enabled', True) is True
            if active and not entry.get('deleted') and (not entry.get('builtin') or source in scheduled):
                enabled[source] = entry['revision']
        counts = {'enabled_source_count': len(enabled), 'latest_failed_source_count': 0,
                  'latest_partial_source_count': 0, 'latest_completed_source_count': 0,
                  'latest_active_source_count': 0, 'unobserved_source_count': len(enabled)}
        for source, status, raw in connection.execute('''SELECT t.source_id,t.status,t.source_snapshot FROM collection_tasks t
                JOIN (SELECT source_id,MAX(rowid) latest_row FROM collection_tasks GROUP BY source_id) latest ON t.rowid=latest.latest_row'''):
            if source not in enabled:
                continue
            version = json.loads(raw) if raw else {'revision': 0}
            if not isinstance(version, dict) or version.get('revision', 0) != enabled[source]:
                continue
            counts['unobserved_source_count'] -= 1
            if status == 'failed': counts['latest_failed_source_count'] += 1
            elif status == 'partial': counts['latest_partial_source_count'] += 1
            elif status in ('completed', 'empty'): counts['latest_completed_source_count'] += 1
            elif status in ('queued', 'running'): counts['latest_active_source_count'] += 1
            else: counts['unobserved_source_count'] += 1
        return counts


def snapshot(root, *, now=None, max_age=180):
    """Return independent business status; transport ``ok`` remains separate.

    Disabled admission/roles are ordinary states. Unknown observations never
    become a successful cycle merely because their process PID is present.
    """
    root = Path(root).resolve()
    now = time.time() if now is None else now
    if type(now) not in (int, float) or not math.isfinite(now) or not math.isfinite(max_age) or max_age <= 0:
        raise ValueError('invalid_health_clock')
    state = root / '.local/workbench-deployment'
    try:
        admission = _json(state / 'admission.json')
        pids = _json(state / 'pids.json')
    except FileNotFoundError:
        return {'status': 'unavailable', 'ok': None, 'reason': 'missing_supervision_snapshot', 'roles': {}}
    except (OSError, ValueError):
        return {'status': 'unavailable', 'ok': None, 'reason': 'invalid_supervision_snapshot', 'roles': {}}
    if admission.get('workers') is not True or pids.get('paused') is True:
        return {'status': 'paused', 'ok': True, 'roles': {}}
    roles = pids.get('roles')
    if not isinstance(roles, dict):
        return {'status': 'unavailable', 'ok': None, 'reason': 'invalid_role_snapshot', 'roles': {}}
    results = {}
    for role in sorted(set(roles) - {'server'}):
        if role not in _FILES and role != 'publisher':
            continue
        try:
            if role == 'publisher':
                document = _publisher(root)
                if document is None:
                    results[role] = {'status': 'not_configured', 'ok': True}
                    continue
            else:
                document = _json(root / _FILES[role])
                if role == 'feedback':
                    try:
                        failure = _json(root / 'data/news-feedback-error.json')
                    except FileNotFoundError:
                        failure = {}
                    failure_at, success_at = _at(failure.get('at')), _at(document.get('last_success_at'))
                    if failure_at is not None and (success_at is None or failure_at >= success_at) and now-failure_at <= max_age:
                        document = {**document, 'state': 'blocked', 'error_type': failure.get('error_type')}
            results[role] = _signal(document, now, max_age, pids.get('release'))
            if role == 'collector' and results[role]['status'] != 'paused':
                try:
                    outcomes = _collection(root)
                    results[role].update(outcomes)
                    if outcomes['latest_failed_source_count'] or outcomes['latest_partial_source_count']:
                        results[role].update(status='degraded', ok=False, reason='latest_source_tasks_need_attention')
                    elif outcomes['unobserved_source_count'] and results[role]['ok'] is True:
                        results[role].update(status='unknown', ok=None, reason='current_sources_not_observed')
                except (OSError, ValueError, TypeError, sqlite3.Error):
                    results[role]['source_tasks_status'] = 'unavailable'
                    if results[role]['ok'] is True:
                        results[role].update(status='unknown', ok=None, reason='source_tasks_unavailable')
        except FileNotFoundError:
            results[role] = {'status': 'unknown', 'ok': None, 'reason': 'missing_progress_signal'}
        except (OSError, ValueError, TypeError, sqlite3.Error):
            results[role] = {'status': 'unknown', 'ok': None, 'reason': 'progress_unavailable'}
    if 'server' in roles:
        try:
            document = _json(root / _FILES['overviews'])
            results['overviews'] = _signal({**document, 'state': 'ready' if not document.get('error_type') else 'error'}, now, max_age, pids.get('release'))
        except (OSError, ValueError):
            results['overviews'] = {'status': 'unknown', 'ok': None, 'reason': 'progress_unavailable'}
    degraded = [role for role, result in results.items() if result['ok'] is False]
    unknown = [role for role, result in results.items() if result['ok'] is None]
    return {'status': 'degraded' if degraded else 'unknown' if unknown else 'healthy',
            'ok': False if degraded else None if unknown else True,
            'degraded_roles': degraded, 'unknown_roles': unknown, 'roles': results}
