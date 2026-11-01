"""Fault sequences and durable restart budgets, without starting any service."""
import copy
import json

import pytest

from easel_workbench.health_policy import assess, attempted


def observation(**changes):
    return {'target': 'release-a/server-11/creation-111', 'local_ok': False,
            'ingress_ok': False, 'age_seconds': 500, 'eligible': True,
            **changes}


def fail(state=None, start=1000, **options):
    state = {} if state is None else state
    for at in (start, start + 10, start + 20):
        state = assess(state, observation(), at, **options)
    return state


def test_three_consecutive_failures_are_required_and_one_good_probe_breaks_streak():
    state = assess({}, observation(), 1000)
    assert state['failures'] == 1 and state['action'] is None
    state = assess(state, observation(), 1010)
    assert state['failures'] == 2 and state['action'] is None
    state = assess(state, observation(local_ok=True, ingress_ok=True), 1020)
    assert state['status'] == 'healthy' and state['failures'] == 0
    state = fail(state, 1030)
    assert state['action'] == 'recover' and state['failures'] == 3


def test_network_only_fault_never_restarts_backend():
    state = fail()
    for at in range(1030, 1200, 10):
        state = assess(state, observation(local_ok=True), at)
        assert state['status'] == 'network_degraded' and state['action'] is None
    assert state['attempts'] == []


def test_process_change_has_fresh_streak_and_startup_grace_without_erasing_budget():
    state = attempted(fail(), 1020, observation()['target'])
    for at, age in ((1030, 0), (1100, 70), (1110, 89)):
        state = assess(state, observation(target='new-server', age_seconds=age), at)
        assert state['status'] == 'starting' and state['failures'] == 0
        assert state['attempts'] == [1020]
    state = assess(state, observation(target='new-server', age_seconds=90), 1120)
    assert state['failures'] == 1 and state['action'] is None


@pytest.mark.parametrize('reason', ['active_turn', 'native_pending', 'maintenance', 'database_unreadable', 'foreign_owner'])
def test_unsafe_execution_defers_and_cannot_reuse_old_failure_streak(reason):
    state = fail()
    state = assess(state, observation(eligible=False, blocked_reason=reason), 1030)
    assert state['status'] == 'deferred' and state['blocked_reason'] == reason
    assert state['action'] is None and state['failures'] == 0
    state = assess(state, observation(), 1040)
    assert state['failures'] == 1 and state['action'] is None


def test_budget_survives_json_process_restart_and_healthy_probes():
    state = attempted(fail(), 1020, observation()['target'])
    state = json.loads(json.dumps(state))
    state = assess(state, observation(local_ok=True), 1030)
    assert state['attempts'] == [1020]
    state = fail(state, 1040)
    assert state['status'] == 'cooling_down' and state['action'] is None
    state = assess(state, observation(), 1140)
    assert state['action'] == 'recover'
    state = attempted(state, 1140, observation()['target'])
    state = assess(json.loads(json.dumps(state)), observation(local_ok=True), 1150)
    state = fail(state, 1300)
    assert state['status'] == 'circuit_open' and state['action'] is None
    assert state['attempts'] == [1020, 1140]


def test_budget_uses_rolling_window_and_last_attempt_keeps_longer_cooldown():
    state = attempted(fail(window=100, cooldown=200), 1020, observation()['target'])
    state = fail(state, 1120, window=100, cooldown=200)
    assert state['attempts'] == [] and state['last_attempt'] == 1020
    assert state['status'] == 'cooling_down'
    state = assess(state, observation(), 1220, window=100, cooldown=200)
    assert state['action'] == 'recover'


def test_clock_rollback_keeps_high_water_mark_and_budget_until_caught_up():
    state = attempted(fail(), 1020, observation()['target'])
    state = assess(state, observation(), 1010)
    assert state['status'] == 'clock_rollback' and state['observed_at'] == 1020
    assert state['attempts'] == [1020] and state['action'] is None
    state = assess(state, observation(local_ok=True), 1019)
    assert state['status'] == 'clock_rollback'
    state = assess(state, observation(), 1021)
    assert state['failures'] == 1 and state['action'] is None


@pytest.mark.parametrize('break_state', [
    lambda s: s.pop('attempts'),
    lambda s: s.update(attempts=[]),
    lambda s: s.update(last_attempt=None),
    lambda s: s.update(attempts=[float('nan')]),
    lambda s: s.update(attempts=[2000], last_attempt=2000),
    lambda s: s.update(failures=-1),
    lambda s: s.update(schema=True),
    lambda s: s.update(window_seconds=3600),
    lambda s: s.update(status=[]),
    lambda s: s.update(observed_at=10 ** 1000),
])
def test_corrupt_persisted_budget_latches_closed_even_after_health_returns(break_state):
    state = attempted(fail(), 1020, observation()['target'])
    break_state(state)
    state = assess(state, observation(), 1030)
    assert state['invalid_state'] and state['action'] is None
    state = assess(json.loads(json.dumps(state, allow_nan=False)), observation(local_ok=True), 1040)
    assert state['invalid_state'] and state['status'] == 'invalid_state'


@pytest.mark.parametrize('change', [{'local_ok': 1}, {'eligible': None}, {'age_seconds': float('inf')}, {'target': ''}])
def test_malformed_observation_never_recommends_recovery(change):
    state = assess(fail(), observation(**change), 1030)
    assert state['invalid_state'] and state['action'] is None
    json.dumps(state, allow_nan=False)


def test_assessment_does_not_mutate_inputs_or_consume_budget_until_recorded():
    original = fail()
    before = copy.deepcopy(original)
    candidate = assess(original, observation(), 1030)
    assert original == before and candidate['attempts'] == []
    saved = attempted(candidate, 1031, observation()['target'])
    assert candidate['attempts'] == [] and saved['attempts'] == [1031]
    assert saved['status'] == 'recovery_requested' and saved['action'] is None
    with pytest.raises(ValueError):
        attempted(saved, 1032, observation()['target'])


@pytest.mark.parametrize('target,at', [('foreign', 1030), (observation()['target'], 1000)])
def test_attempt_requires_current_recovery_recommendation_and_target(target, at):
    with pytest.raises(ValueError):
        attempted(fail(), at, target)


def test_expired_history_can_be_empty_without_invalidating_state():
    state = attempted(fail(), 1020, observation()['target'])
    state = assess(state, observation(local_ok=True), 2820)
    assert state['attempts'] == [] and not state['invalid_state']
    state = assess(json.loads(json.dumps(state)), observation(local_ok=True), 2830)
    assert not state['invalid_state']


def test_window_change_cannot_restore_budget_pruned_by_an_old_configuration():
    state = attempted(fail(window=100), 1020, observation()['target'])
    state = assess(state, observation(local_ok=True), 1121, window=100)
    assert state['attempts'] == []
    state = assess(state, observation(), 1122, window=1800)
    assert state['invalid_state'] and state['action'] is None
