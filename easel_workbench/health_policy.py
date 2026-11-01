"""Persistent, side-effect-free decisions for the private health supervisor.

An assessment is only a recommendation. The executor must recheck ownership and
write fences, then persist ``attempted`` before touching any process. Successful
health checks never erase restart history.
"""
from __future__ import annotations

import math


_STATUSES = frozenset({
    'healthy', 'network_degraded', 'starting', 'waiting', 'deferred',
    'cooling_down', 'circuit_open', 'recovery_candidate',
    'recovery_requested', 'clock_rollback', 'invalid_state',
})


def _number(value):
    if type(value) is int:
        return 0 <= value <= 2 ** 53
    return type(value) is float and math.isfinite(value) and value >= 0


def _initial(window):
    return {
        'schema': 1, 'target': None, 'failures': 0, 'attempts': [],
        'last_attempt': None, 'observed_at': 0.0,
        'window_seconds': float(window), 'status': 'waiting', 'action': None,
        'blocked_reason': None, 'invalid_state': False,
    }


def _state(previous, window):
    if type(previous) is not dict:
        return None
    if not previous:
        return _initial(window)
    required = set(_initial(window))
    if not required.issubset(previous):
        return None
    if (type(previous['schema']) is not int or previous['schema'] != 1
            or previous['invalid_state'] is not False
            or not isinstance(previous['status'], str)
            or previous['status'] not in _STATUSES
            or previous['action'] not in (None, 'recover')
            or type(previous['failures']) is not int
            or not 0 <= previous['failures'] <= 1_000_000
            or not _number(previous['observed_at'])
            or not _number(previous['window_seconds'])
            or previous['window_seconds'] != window):
        return None
    target = previous['target']
    if target is not None and (not isinstance(target, str) or not 0 < len(target) <= 1024):
        return None
    if previous['blocked_reason'] is not None and not isinstance(previous['blocked_reason'], str):
        return None
    attempts, last = previous['attempts'], previous['last_attempt']
    if (type(attempts) is not list or len(attempts) > 100_000
            or not all(_number(value) for value in attempts)
            or attempts != sorted(attempts)
            or any(value > previous['observed_at'] for value in attempts)
            or (last is not None and (not _number(last) or last > previous['observed_at']))):
        return None
    if attempts and last != attempts[-1]:
        return None
    # Empty history is valid after expiry, but cannot conceal a recent last
    # attempt. A partially truncated persisted budget therefore fails closed.
    if not attempts and last is not None and last > previous['observed_at'] - window:
        return None
    return {key: list(value) if key == 'attempts' else value
            for key, value in previous.items() if key in required}


def _invalid(now, window):
    state = _initial(window)
    state.update(status='invalid_state', invalid_state=True,
                 observed_at=float(now) if _number(now) else 0.0,
                 blocked_reason='invalid_persisted_policy_or_observation')
    return state


def assess(previous: dict, observation: dict, now: float, *, threshold=3,
           startup_grace=90, cooldown=120, window=1800, max_restarts=2) -> dict:
    """Return a JSON-safe recommendation without resetting the restart budget.

    ``{}`` explicitly represents first initialization. Any nonempty malformed
    state latches ``invalid_state``; the caller must not replace unreadable state
    with ``{}``. Window-size changes require an explicit reviewed state reset.
    Time rollback retains the previous high-water mark until the clock catches
    up, and requires a new failure streak afterward.
    """
    if (type(threshold) is not int or not 1 <= threshold <= 1_000_000
            or type(max_restarts) is not int or not 1 <= max_restarts <= 100_000
            or not _number(startup_grace) or not _number(cooldown)
            or not _number(window) or window <= 0):
        raise ValueError('Invalid health recovery policy')
    state = _state(previous, window)
    if state is None or not _number(now):
        return _invalid(now, window)
    if (type(observation) is not dict
            or not isinstance(observation.get('target'), str)
            or not 0 < len(observation['target']) <= 1024
            or type(observation.get('local_ok')) is not bool
            or observation.get('ingress_ok') is not None and type(observation['ingress_ok']) is not bool
            or type(observation.get('eligible')) is not bool
            or not _number(observation.get('age_seconds'))
            or observation.get('blocked_reason') is not None and not isinstance(observation['blocked_reason'], str)):
        return _invalid(now, window)
    state.update(action=None, blocked_reason=None)
    if now < state['observed_at']:
        state.update(status='clock_rollback', failures=0, blocked_reason='clock_rollback')
        return state
    state['observed_at'] = float(now)
    state['attempts'] = [at for at in state['attempts'] if at > now - window]
    if state['target'] != observation['target']:
        state.update(target=observation['target'], failures=0)
    if observation['local_ok']:
        state.update(status='network_degraded' if observation.get('ingress_ok') is False else 'healthy', failures=0)
        return state
    if not observation['eligible']:
        state.update(status='deferred', failures=0,
                     blocked_reason=observation.get('blocked_reason') or 'not_eligible')
        return state
    if observation['age_seconds'] < startup_grace:
        state.update(status='starting', failures=0)
        return state
    state['failures'] = min(state['failures'] + 1, threshold)
    if state['failures'] < threshold:
        state['status'] = 'waiting'
    elif len(state['attempts']) >= max_restarts:
        state['status'] = 'circuit_open'
    elif state['last_attempt'] is not None and now - state['last_attempt'] < cooldown:
        state['status'] = 'cooling_down'
    else:
        state.update(status='recovery_candidate', action='recover')
    return state


def attempted(state: dict, now: float, target: str) -> dict:
    """Consume one budget slot before the executor attempts recovery.

    Persist this returned state atomically before any termination. A failed or
    interrupted recovery still consumes its slot; a restart cannot clear it.
    """
    if type(state) is not dict or not _number(state.get('window_seconds')):
        raise ValueError('A valid assessed recovery recommendation is required')
    result = _state(state, state['window_seconds'])
    if (result is None or result['action'] != 'recover'
            or result['status'] != 'recovery_candidate'
            or result['target'] != target or not _number(now)
            or now < result['observed_at']):
        raise ValueError('Recovery recommendation is stale, invalid or belongs to another target')
    result['attempts'].append(float(now))
    result.update(last_attempt=float(now), observed_at=float(now),
                  status='recovery_requested', action=None, failures=0)
    return result
