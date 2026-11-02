"""Operator bridge identity, retained-unknown and duplicate-request contracts."""
import json
from types import SimpleNamespace

import pytest

from easel_workbench.diagnostics import health_bridge as bridge


def fixture(root):
    bound = {'release': 'workbench-test', 'manifest_sha256': 'a'*64,
             'native_release': 'native-test', 'native_manifest_sha256': 'b'*64}
    return {'schema': 1, 'binding': bound, 'busy': False, 'unknown_receipts': False,
        'manager_task_verified': True,
        'manager': {'pid': None, 'creation_ticks': None, 'alive': False},
        'server': {'pid': 123, 'creation_ticks': '999', 'alive': True, 'age_seconds': 1000}}


def request(bound):
    return {'schema': 1, 'operation_id': 'a'*32, 'action': 'restart_manager',
        'binding': bound, 'expected_identity': {'pid': None, 'creation_ticks': None}, 'observed_at': 1000}


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    (tmp_path/bridge.watchdog.STATE_DIR).mkdir(parents=True)
    current = fixture(tmp_path)
    calls = []
    monkeypatch.setattr(bridge, 'inspect', lambda root: current)
    monkeypatch.setattr(bridge.watchdog, 'operator_gates', lambda root: calls.append('idle_and_queue'))
    monkeypatch.setattr(bridge.watchdog, 'controls', lambda root: {'runtime': current['binding']})
    monkeypatch.setattr(bridge, 'task', lambda root, start=False: calls.append('start' if start else 'verify') or True)
    monkeypatch.setattr(bridge, '_self_identity', lambda: {'pid': 555, 'creation_ticks': '777'})
    return SimpleNamespace(root=tmp_path, current=current, calls=calls, request=request(current['binding']))


def test_absent_manager_only_starts_verified_existing_task_once(prepared):
    answer = bridge.recover(prepared.root, prepared.request)
    assert answer['outcome'] == 'manager_restart_requested'
    assert prepared.calls == ['idle_and_queue', 'start']
    assert bridge.recover(prepared.root, prepared.request)['outcome'] == 'deferred'
    assert prepared.calls == ['idle_and_queue', 'start']


@pytest.mark.parametrize('change', ['binding', 'pid', 'busy', 'unknown'])
def test_changed_observation_never_starts_or_stops_a_process(prepared, change):
    if change == 'binding': prepared.current['binding'] = {**prepared.current['binding'], 'release': 'workbench-other'}
    elif change == 'pid': prepared.current['manager']['pid'] = 8
    elif change == 'busy': prepared.current['busy'] = True
    else: prepared.current['unknown_receipts'] = True
    with pytest.raises(bridge.watchdog.GuardError): bridge.recover(prepared.root, prepared.request)
    assert prepared.calls == []


def test_unknown_bridge_receipt_does_not_repeat_task_start(prepared, monkeypatch):
    def uncertain(root, start=False):
        prepared.calls.append('start')
        raise OSError('simulated response lost after OS task accepted')
    monkeypatch.setattr(bridge, 'task', uncertain)
    with pytest.raises(OSError): bridge.recover(prepared.root, prepared.request)
    assert bridge.recover(prepared.root, prepared.request)['outcome'] == 'deferred'
    assert prepared.calls == ['idle_and_queue', 'start']
    path = prepared.root/bridge.watchdog.STATE_DIR/('external-health-'+'a'*32+'.json')
    assert json.loads(path.read_text(encoding='utf-8'))['phase'] == 'unknown'


def test_changed_idle_queue_before_any_mutation_is_acknowledged_deferral(prepared, monkeypatch):
    def busy(root): raise ValueError('native queue accepted new work')
    monkeypatch.setattr(bridge.watchdog,'operator_gates',busy)
    answer=bridge.recover(prepared.root,prepared.request)
    assert answer['outcome']=='deferred' and prepared.calls==[]
    path=prepared.root/bridge.watchdog.STATE_DIR/('external-health-'+'a'*32+'.json')
    assert json.loads(path.read_text(encoding='utf-8'))['phase']=='completed'
    proof=bridge.reconcile(prepared.root,prepared.request)
    assert proof['status']=='receipt_confirmed' and proof['outcome']=='deferred'


def test_manager_start_race_checks_binding_again(prepared, monkeypatch):
    first = prepared.current
    changed = {**first, 'binding': {**first['binding'], 'release': 'workbench-other'}}
    values = iter([first, changed])
    monkeypatch.setattr(bridge, 'inspect', lambda root: next(values))
    assert bridge.recover(prepared.root, prepared.request)['outcome'] == 'deferred'
    assert prepared.calls == ['idle_and_queue']


@pytest.mark.parametrize('alive', [False, True])
def test_interrupted_bridge_releases_only_its_dead_executor_fence(prepared, monkeypatch, alive):
    state=prepared.root/bridge.watchdog.STATE_DIR
    original=prepared.request
    bridge.atomic(state/('external-health-'+original['operation_id']+'.json'),
        {'request': original,'phase':'unknown','executor':{'pid':555,'creation_ticks':'777'}})
    (state/'paused').write_text('owned',encoding='utf-8')
    bridge.atomic(state/'health-recovery.json',{'watchdog_pid':555,'watchdog_creation_ticks':'777',
        'binding':{'runtime':{k:original['binding'][k] for k in ('release','manifest_sha256')},
                   'native':{'release':original['binding']['native_release'],'manifest_sha256':original['binding']['native_manifest_sha256']}}})
    monkeypatch.setattr(bridge,'rows',lambda: {555:{'creation_ticks':'777'}} if alive else {})
    monkeypatch.setattr(bridge.watchdog,'resume_fence',lambda root:prepared.calls.append('release_owned_fence'))
    answer=bridge.reconcile(prepared.root,original)
    assert answer['status']==('executor_still_alive' if alive else 'owned_abandoned_fence_reconciled')
    assert prepared.calls==([] if alive else ['release_owned_fence'])
