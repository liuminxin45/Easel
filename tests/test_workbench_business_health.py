"""TEMP progress observations; never start a business worker or production call."""
import json
import datetime as dt
import hashlib
from pathlib import Path
import sqlite3

import pytest

from easel_workbench.business_health import snapshot
from easel_workbench.features.collection.schedules import TZ, packed, validate_schedule


def put(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value), encoding='utf-8')


def controls(root, roles):
    put(root, '.local/workbench-deployment/admission.json', {'workers': True})
    put(root, '.local/workbench-deployment/pids.json', {'roles': dict.fromkeys(roles, 123), 'release': 'workbench-test', 'paused': False})


def test_alive_collector_with_blocked_cycle_is_not_business_healthy(tmp_path):
    controls(tmp_path, ['collector'])
    put(tmp_path, 'data/collection/heartbeat.json', {'heartbeat': 999, 'state': 'blocked', 'error_type': 'OperationalError',
        'error': 'secret token and original article must never enter public health'})
    before = (tmp_path / 'data/collection/heartbeat.json').read_bytes()
    result = snapshot(tmp_path, now=1000)
    assert result['status'] == 'degraded' and result['ok'] is False
    assert result['degraded_roles'] == ['collector']
    assert result['roles']['collector']['error_type'] == 'OperationalError'
    assert 'secret' not in json.dumps(result)
    assert (tmp_path / 'data/collection/heartbeat.json').read_bytes() == before


@pytest.mark.parametrize('document,reason', [
    ({'heartbeat': 100, 'state': 'watching'}, 'progress_expired'),
    ({'heartbeat': 1100, 'state': 'watching'}, 'future_progress_timestamp'),
    ({'heartbeat': 999, 'state': 'watching', 'release': 'workbench-old'}, 'different_release'),
    ({'heartbeat': 999}, 'missing_cycle_outcome'),
])
def test_progress_needs_recent_matching_cycle_evidence(tmp_path, document, reason):
    controls(tmp_path, ['worker'])
    put(tmp_path, 'data/worker-status.json', document)
    result = snapshot(tmp_path, now=1000)
    assert result['ok'] is not True
    assert result['roles']['worker']['reason'] == reason


def test_historical_task_failures_do_not_mean_loop_is_broken(tmp_path):
    controls(tmp_path, ['local'])
    put(tmp_path, 'data/local-operations/heartbeat.json', {'heartbeat': 999, 'state': 'waiting',
        'counts': {'failed': 12, 'needs_attention': 9}})
    assert snapshot(tmp_path, now=1000)['ok'] is True


def test_feedback_success_supersedes_old_error_not_just_a_fresh_beat(tmp_path):
    controls(tmp_path, ['feedback'])
    put(tmp_path, 'data/news-feedback-worker.json', {'heartbeat': 999, 'state': 'watching'})
    put(tmp_path, 'data/news-feedback-error.json', {'at': 990, 'error_type': 'OperationalError'})
    assert snapshot(tmp_path, now=1000)['roles']['feedback']['ok'] is False
    put(tmp_path, 'data/news-feedback-worker.json', {'heartbeat': 999, 'state': 'watching', 'last_success_at': 995})
    assert snapshot(tmp_path, now=1000)['roles']['feedback']['ok'] is True


def test_missing_progress_is_unknown_without_creating_a_file(tmp_path):
    controls(tmp_path, ['learning'])
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob('*'))
    assert snapshot(tmp_path, now=1000)['roles']['learning']['ok'] is None
    assert sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob('*')) == before


def test_no_enabled_publisher_is_normal_and_database_stays_unchanged(tmp_path):
    controls(tmp_path, ['publisher'])
    database = tmp_path / 'data/desk.sqlite'
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE distribution_connections(id TEXT,document TEXT)')
        connection.execute('CREATE TABLE distribution_runners(id TEXT,document TEXT)')
        connection.execute('INSERT INTO distribution_connections VALUES(?,?)', ('disabled', '{"enabled":false}'))
    before = database.read_bytes()
    assert snapshot(tmp_path, now=1000)['roles']['publisher'] == {'status': 'not_configured', 'ok': True}
    assert database.read_bytes() == before


def test_publisher_cycle_error_cannot_hide_behind_heartbeat(tmp_path):
    controls(tmp_path, ['publisher'])
    database = tmp_path / 'data/desk.sqlite'
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE distribution_connections(id TEXT,document TEXT)')
        connection.execute('CREATE TABLE distribution_runners(id TEXT,document TEXT)')
        connection.execute('INSERT INTO distribution_connections VALUES(?,?)', ('enabled', '{"enabled":true}'))
        connection.execute('INSERT INTO distribution_runners VALUES(?,?)', ('distribution-local', json.dumps({
            'last_seen_at': 999, 'state': 'polling', 'last_error_type': 'OperationalError', 'last_error_at': 998})))
    result = snapshot(tmp_path, now=1000)
    assert result['roles']['publisher']['ok'] is False


def test_admission_pause_is_an_ordinary_state(tmp_path):
    controls(tmp_path, ['collector'])
    put(tmp_path, '.local/workbench-deployment/admission.json', {'workers': False})
    assert snapshot(tmp_path, now=1000) == {'status': 'paused', 'ok': True, 'roles': {}}


def collection_fixture(root):
    controls(root, ['collector'])
    put(root, 'data/collection/heartbeat.json', {'heartbeat': 999, 'state': 'watching'})
    put(root, 'sources.json', {'active': {'name': 'TEMP'}, 'disabled': {'name': 'TEMP disabled'}})
    plan = {'kind': 'daily', 'times': ['10:00']}
    put(root, 'collection_schedules.json', {'sources': {'active': plan, 'disabled': plan}})
    put(root, 'data/collection-config.json', {'enabled': True, 'sources': {'disabled': {'enabled': False}}})
    connection = sqlite3.connect(root / 'data/desk.sqlite')
    connection.execute('CREATE TABLE collection_source_versions(source_id TEXT,revision INTEGER,payload TEXT)')
    connection.execute('CREATE TABLE collection_tasks(source_id TEXT,status TEXT,source_snapshot TEXT,finished_at TEXT,error TEXT,warnings TEXT,fetched INTEGER DEFAULT 0)')
    connection.execute('CREATE TABLE collection_schedule_state(source_id TEXT,next_run_at TEXT,last_slot TEXT,schedule_hash TEXT)')
    connection.execute('INSERT INTO collection_schedule_state VALUES(?,?,?,?)', ('active',
        dt.datetime.fromtimestamp(1500,TZ).isoformat(), None, hashlib.sha256(packed(validate_schedule(plan)).encode()).hexdigest()))
    return connection


@pytest.mark.parametrize('status,key', [('failed', 'latest_failed_source_count'), ('partial', 'latest_partial_source_count')])
def test_watching_does_not_hide_latest_failed_or_partial_source(tmp_path, status, key):
    with collection_fixture(tmp_path) as connection:
        connection.execute('INSERT INTO collection_tasks(source_id,status,source_snapshot) VALUES(?,?,?)', ('active', status, '{"revision":0}'))
    result = snapshot(tmp_path, now=1000)
    assert result['status'] == 'degraded' and result['roles']['collector'][key] == 1
    assert result['roles']['collector']['enabled_source_count'] == 1


def test_new_success_covers_old_failure_and_disabled_sources_are_excluded(tmp_path):
    with collection_fixture(tmp_path) as connection:
        connection.execute('INSERT INTO collection_tasks(source_id,status,source_snapshot) VALUES(?,?,?)', ('active', 'failed', '{"revision":0}'))
        connection.execute('INSERT INTO collection_tasks(source_id,status,source_snapshot) VALUES(?,?,?)', ('active', 'completed', '{"revision":0}'))
        connection.execute('INSERT INTO collection_tasks(source_id,status,source_snapshot) VALUES(?,?,?)', ('disabled', 'failed', '{"revision":0}'))
    result = snapshot(tmp_path, now=1000)
    assert result['ok'] is True
    assert result['roles']['collector']['latest_failed_source_count'] == 0
    assert result['roles']['collector']['latest_completed_source_count'] == 1


def test_old_source_revision_cannot_claim_current_source_outcome(tmp_path):
    with collection_fixture(tmp_path) as connection:
        connection.execute('INSERT INTO collection_source_versions VALUES(?,?,?)', ('active', 1,
            '{"enabled":true,"builtin":true}'))
        connection.execute('INSERT INTO collection_tasks(source_id,status,source_snapshot) VALUES(?,?,?)', ('active', 'failed', '{"revision":0}'))
    result = snapshot(tmp_path, now=1000)
    assert result['ok'] is None
    assert result['roles']['collector']['latest_failed_source_count'] == 0
    assert result['roles']['collector']['unobserved_source_count'] == 1


@pytest.mark.parametrize('state', ['polling', 'working'])
def test_progress_beat_does_not_clear_last_failure_before_real_success(tmp_path, state):
    controls(tmp_path, ['learning'])
    put(tmp_path, 'data/learning/heartbeat.json', {'heartbeat': 999, 'state': state,
        'error_type': 'OperationalError', 'last_error_at': 990, 'last_success_at': 900})
    assert snapshot(tmp_path, now=1000)['roles']['learning']['ok'] is False
    put(tmp_path, 'data/learning/heartbeat.json', {'heartbeat': 1000, 'state': 'completed', 'last_success_at': 1000})
    assert snapshot(tmp_path, now=1000)['roles']['learning']['ok'] is True


def scheduled(root, connection, now, plan, *, next_run, last_slot):
    put(root, 'data/collection/heartbeat.json', {'heartbeat': now.timestamp(), 'state': 'watching'})
    put(root, 'collection_schedules.json', {'sources': {'active': plan, 'disabled': plan}})
    connection.execute('UPDATE collection_schedule_state SET next_run_at=?,last_slot=?,schedule_hash=? WHERE source_id=?',
        (next_run.isoformat(), last_slot.isoformat() if last_slot else None,
         hashlib.sha256(packed(validate_schedule(plan)).encode()).hexdigest(), 'active'))


def completed(connection, finished, *, revision=0):
    connection.execute('INSERT INTO collection_tasks(source_id,status,source_snapshot,finished_at,fetched) VALUES(?,?,?,?,?)',
        ('active', 'completed', json.dumps({'revision': revision}), finished.isoformat(), 0))


def test_watching_with_days_old_success_is_late_by_actual_daily_schedule(tmp_path):
    now = dt.datetime(2026, 11, 4, 11, tzinfo=TZ)
    with collection_fixture(tmp_path) as connection:
        scheduled(tmp_path, connection, now, {'kind': 'daily', 'times': ['10:00']},
            next_run=now-dt.timedelta(days=2), last_slot=now-dt.timedelta(days=3))
        completed(connection, now-dt.timedelta(days=3))
    before = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    result = snapshot(tmp_path, now=now.timestamp())
    collector = result['roles']['collector']
    assert result['ok'] is False and collector['late_source_count'] == 1
    assert collector['latest_failed_source_count'] == 0
    assert collector['max_success_age_seconds'] >= 3*86400-1
    assert collector['reason'] == 'scheduled_sources_late'
    assert all(path.read_bytes() == content for path, content in before.items())


def test_first_enable_before_its_future_slot_has_no_historical_debt(tmp_path):
    now = dt.datetime(2026, 11, 4, 9, 30, tzinfo=TZ)
    with collection_fixture(tmp_path) as connection:
        scheduled(tmp_path, connection, now, {'kind': 'daily', 'times': ['10:00']},
            next_run=now.replace(hour=10, minute=0), last_slot=None)
    collector = snapshot(tmp_path, now=now.timestamp())['roles']['collector']
    assert collector['late_source_count'] == 0
    assert collector['status'] == 'unknown'  # no fabricated first success either


def test_execution_grace_does_not_require_the_not_yet_due_window(tmp_path):
    now = dt.datetime(2026, 11, 4, 10, 5, tzinfo=TZ)
    with collection_fixture(tmp_path) as connection:
        scheduled(tmp_path, connection, now, {'kind': 'daily', 'times': ['10:00']},
            next_run=now.replace(minute=0), last_slot=now-dt.timedelta(days=1))
        completed(connection, now-dt.timedelta(days=1))
    result = snapshot(tmp_path, now=now.timestamp())
    assert result['ok'] is True and result['roles']['collector']['late_source_count'] == 0


def test_weekly_empty_check_is_fresh_until_the_next_real_weekly_window(tmp_path):
    now = dt.datetime(2026, 11, 3, 12, tzinfo=TZ)  # Tuesday
    friday = dt.datetime(2026, 10, 30, 18, 30, tzinfo=TZ)
    with collection_fixture(tmp_path) as connection:
        scheduled(tmp_path, connection, now, {'kind': 'weekly', 'weekdays': [4], 'times': ['18:30']},
            next_run=friday+dt.timedelta(days=7), last_slot=friday)
        completed(connection, friday+dt.timedelta(minutes=2))  # zero fetched rows
    result = snapshot(tmp_path, now=now.timestamp())
    assert result['ok'] is True and result['roles']['collector']['late_source_count'] == 0


def test_new_weekly_source_before_first_friday_is_not_late(tmp_path):
    now = dt.datetime(2026, 11, 3, 12, tzinfo=TZ)
    with collection_fixture(tmp_path) as connection:
        scheduled(tmp_path, connection, now, {'kind': 'weekly', 'weekdays': [4], 'times': ['18:30']},
            next_run=dt.datetime(2026, 11, 6, 18, 30, tzinfo=TZ), last_slot=None)
    assert snapshot(tmp_path, now=now.timestamp())['roles']['collector']['late_source_count'] == 0


def test_custom_interval_detects_lateness_even_when_period_is_less_than_grace(tmp_path):
    now = dt.datetime(2026, 11, 4, 11, tzinfo=TZ)
    plan = {'kind': 'interval', 'seconds': 300}
    with collection_fixture(tmp_path) as connection:
        connection.execute('INSERT INTO collection_source_versions VALUES(?,?,?)',
            ('active', 1, '{"enabled":true,"builtin":false,"refresh_seconds":300}'))
        scheduled(tmp_path, connection, now, plan, next_run=now-dt.timedelta(minutes=25), last_slot=now-dt.timedelta(minutes=30))
        completed(connection, now-dt.timedelta(minutes=30), revision=1)
    collector = snapshot(tmp_path, now=now.timestamp())['roles']['collector']
    assert collector['late_source_count'] == 1 and collector['ok'] is False


def test_old_revision_success_cannot_pay_a_current_revision_scheduled_window(tmp_path):
    now = dt.datetime(2026, 11, 4, 11, tzinfo=TZ)
    with collection_fixture(tmp_path) as connection:
        connection.execute('INSERT INTO collection_source_versions VALUES(?,?,?)',
            ('active', 1, '{"enabled":true,"builtin":true}'))
        scheduled(tmp_path, connection, now, {'kind': 'daily', 'times': ['10:00']},
            next_run=now+dt.timedelta(days=1), last_slot=now.replace(hour=10))
        completed(connection, now-dt.timedelta(minutes=1), revision=0)
        connection.execute('INSERT INTO collection_tasks(source_id,status,source_snapshot) VALUES(?,?,?)', ('active', 'queued', '{"revision":1}'))
    assert snapshot(tmp_path, now=now.timestamp())['roles']['collector']['late_source_count'] == 1


def test_explicit_upstream_500_is_separate_and_no_error_payload_is_returned(tmp_path):
    with collection_fixture(tmp_path) as connection:
        connection.execute('INSERT INTO collection_tasks(source_id,status,source_snapshot,error) VALUES(?,?,?,?)',
            ('active', 'failed', '{"revision":0}', 'HTTP Error 500 https://provider.invalid/private?token=DO-NOT-RETURN'))
    result = snapshot(tmp_path, now=1000)
    assert result['external_provider'] is True
    assert result['roles']['collector']['external_provider_source_count'] == 1
    assert 'DO-NOT-RETURN' not in json.dumps(result)
