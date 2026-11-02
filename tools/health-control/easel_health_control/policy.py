"""Pure bounded recommendations. A proposal grants no process authority."""
import copy
import math

ACTIONS = frozenset(('recover_server', 'restart_manager'))


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def initial(window):
    return {'schema': 1, 'target': None, 'observed_at': 0, 'failures': 0,
            'attempts': [], 'last_attempt': None, 'window_seconds': window,
            'pending_operation': None, 'decision': 'waiting', 'action': None, 'invalid_state': False}


def valid(value, window):
    if not isinstance(value, dict) or not set(initial(window)).issubset(value): return False
    attempts, observed = value['attempts'], value['observed_at']
    return (type(value['schema']) is int and value['schema'] == 1 and value['invalid_state'] is False
        and value['window_seconds'] == window and number(observed)
        and (value['target'] is None or isinstance(value['target'], str) and 0 < len(value['target']) <= 2048)
        and type(value['failures']) is int and 0 <= value['failures'] <= 1000000
        and isinstance(attempts, list) and len(attempts) <= 100000
        and all(number(at) and at <= observed for at in attempts) and attempts == sorted(attempts)
        and (value['last_attempt'] is None or number(value['last_attempt']) and value['last_attempt'] <= observed)
        and (not attempts or value['last_attempt'] == attempts[-1])
        and (attempts or value['last_attempt'] is None or value['last_attempt'] <= observed-window)
        and (value['pending_operation'] is None or isinstance(value['pending_operation'], str) and 0 < len(value['pending_operation']) <= 128)
        and value['action'] in ACTIONS | {None} and isinstance(value['decision'], str))


def assess(previous, observation, now, *, threshold=3, startup_grace=90,
           cooldown=120, window=1800, max_restarts=2):
    if (type(threshold) is not int or not 1 <= threshold <= 1000 or type(max_restarts) is not int
            or not 1 <= max_restarts <= 1000 or not all(number(v) for v in (startup_grace, cooldown, window)) or window == 0):
        raise ValueError('invalid_policy_options')
    if previous == {}: previous = initial(window)
    if not valid(previous, window) or not number(now):
        return {**initial(window), 'observed_at': now if number(now) else 0, 'decision': 'invalid_state', 'invalid_state': True}
    state = copy.deepcopy(previous)
    state['action'] = None
    if now < state['observed_at']:
        state.update(decision='clock_rollback', failures=0)
        return state
    state['observed_at'] = now
    state['attempts'] = [at for at in state['attempts'] if at > now-window]
    if state['pending_operation']:
        state.update(decision='receipt_unknown', failures=0)
        return state
    if observation['target'] != state['target']:
        state.update(target=observation['target'], failures=0)
    if not observation.get('needs_repair'):
        state.update(decision=observation['status'], failures=0)
    elif not observation.get('eligible') or observation.get('action') not in ACTIONS:
        state.update(decision='deferred', failures=0)
    elif observation.get('age_seconds', 0) < startup_grace:
        state.update(decision='starting', failures=0)
    else:
        state['failures'] = min(threshold, state['failures']+1)
        if state['failures'] < threshold: state['decision'] = 'waiting'
        elif len(state['attempts']) >= max_restarts: state['decision'] = 'circuit_open'
        elif state['last_attempt'] is not None and now-state['last_attempt'] < cooldown: state['decision'] = 'cooling_down'
        else: state.update(decision='recovery_candidate', action=observation['action'])
    return state


def consume(state, now, operation_id):
    result = copy.deepcopy(state)
    if (not valid(result, result['window_seconds']) or result['decision'] != 'recovery_candidate'
            or result['action'] not in ACTIONS or not number(now) or now < result['observed_at']
            or not isinstance(operation_id, str) or not operation_id):
        raise ValueError('invalid_repair_recommendation')
    result['attempts'].append(now)
    result.update(last_attempt=now, observed_at=now, failures=0, pending_operation=operation_id,
                  decision='repair_requested', action=None)
    return result
