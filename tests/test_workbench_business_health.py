"""TEMP progress observations; never start a business worker or production call."""
import json
from pathlib import Path
import sqlite3

import pytest

from easel_workbench.business_health import snapshot


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
    put(root, 'collection_schedules.json', {'sources': {'active': {}, 'disabled': {}}})
    put(root, 'data/collection-config.json', {'enabled': True, 'sources': {'disabled': {'enabled': False}}})
    connection = sqlite3.connect(root / 'data/desk.sqlite')
    connection.execute('CREATE TABLE collection_source_versions(source_id TEXT,revision INTEGER,payload TEXT)')
    connection.execute('CREATE TABLE collection_tasks(source_id TEXT,status TEXT,source_snapshot TEXT)')
    return connection


@pytest.mark.parametrize('status,key', [('failed', 'latest_failed_source_count'), ('partial', 'latest_partial_source_count')])
def test_watching_does_not_hide_latest_failed_or_partial_source(tmp_path, status, key):
    with collection_fixture(tmp_path) as connection:
        connection.execute('INSERT INTO collection_tasks VALUES(?,?,?)', ('active', status, '{"revision":0}'))
    result = snapshot(tmp_path, now=1000)
    assert result['status'] == 'degraded' and result['roles']['collector'][key] == 1
    assert result['roles']['collector']['enabled_source_count'] == 1


def test_new_success_covers_old_failure_and_disabled_sources_are_excluded(tmp_path):
    with collection_fixture(tmp_path) as connection:
        connection.execute('INSERT INTO collection_tasks VALUES(?,?,?)', ('active', 'failed', '{"revision":0}'))
        connection.execute('INSERT INTO collection_tasks VALUES(?,?,?)', ('active', 'completed', '{"revision":0}'))
        connection.execute('INSERT INTO collection_tasks VALUES(?,?,?)', ('disabled', 'failed', '{"revision":0}'))
    result = snapshot(tmp_path, now=1000)
    assert result['ok'] is True
    assert result['roles']['collector']['latest_failed_source_count'] == 0
    assert result['roles']['collector']['latest_completed_source_count'] == 1


def test_old_source_revision_cannot_claim_current_source_outcome(tmp_path):
    with collection_fixture(tmp_path) as connection:
        connection.execute('INSERT INTO collection_source_versions VALUES(?,?,?)', ('active', 1,
            '{"enabled":true,"builtin":true}'))
        connection.execute('INSERT INTO collection_tasks VALUES(?,?,?)', ('active', 'failed', '{"revision":0}'))
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
