"""Deterministic editorial ranking; inputs are annotated, not news verification."""

if __name__ == "__main__" and not __package__:
    import sys as _bootstrap_sys
    from pathlib import Path as _BootstrapPath
    _bootstrap_sys.path.insert(0,str(_BootstrapPath(__file__).resolve().parents[3]))

import argparse
import json
from pathlib import Path


def rank(candidates, limit=10):
    if not isinstance(limit, int) or not 0 <= limit <= 30:
        raise ValueError('limit must be 0..30')
    eligible = []
    rejected = []
    for index, c in enumerate(candidates):
        if not c.get('event_id'):
            raise ValueError('event_id required')
        m, i, b = (c.get(k, 0) for k in ('match', 'interesting', 'major'))
        if type(m) is not int or m not in range(4) or any(type(v) is not int or v not in range(3) for v in (i, b)):
            raise ValueError('invalid tier')
        if not all(c.get(k) is True for k in ('supported', 'fresh', 'substantive')):
            rejected.append({'event_id': c['event_id'], 'reason': 'quality gate'})
            continue
        if m and not (c.get('rule_ids') and c.get('match_reason')):
            raise ValueError('matching needs rule IDs and causal reason')
        if (i and not c.get('interesting_reason')) or (b and not c.get('major_reason')):
            raise ValueError('bypass needs explanation')
        priority = max(m, 3 if i == 2 else i, 4 if b == 2 else b)
        eligible.append(((-priority, -b, -i, -m, index), c))
    ordered = [c for _, c in sorted(eligible, key=lambda x: x[0])]
    seen, unique = set(), []
    for c in ordered:
        if c['event_id'] in seen:
            rejected.append({'event_id': c['event_id'], 'reason': 'duplicate underlying event'})
        else:
            seen.add(c['event_id'])
            unique.append(c)
    selected, deferred, counts = [], [], {}
    for c in unique:
        entity = c.get('entity')
        if len(selected) >= limit or (entity and counts.get(entity, 0) >= 2):
            deferred.append(c)
        else:
            selected.append(c)
            if entity:
                counts[entity] = counts.get(entity, 0) + 1
    for c in deferred:
        if len(selected) < limit:
            selected.append(c)
    chosen = {c['event_id'] for c in selected}
    rejected += [{'event_id': c['event_id'], 'reason': 'capacity/diversity'} for c in unique if c['event_id'] not in chosen]
    return {'algorithm': '1.0', 'selected': selected, 'omitted': rejected, 'input_count': len(candidates), 'qualified_unique_count': len(unique)}


def self_test():
    def c(e, **kw):
        return dict(event_id=e, supported=True, fresh=True, substantive=True, **kw)
    checks = 0
    a = c('interest', match=3, rule_ids=['P001'], match_reason='actual personal utility')
    b = c('major', major=2, major_reason='substantive capability breakthrough')
    x = c('explore', interesting=2, interesting_reason='new usable mechanism')
    assert rank([a, b])['selected'][0]['event_id'] == 'major'; checks += 1
    assert rank([c('weak', match=1, rule_ids=['H001'], match_reason='tentative'), x])['selected'][0]['event_id'] == 'explore'; checks += 1
    assert len(rank([a, a])['selected']) == 1; checks += 1
    bad = c('bad'); bad['supported'] = False
    assert not rank([bad])['selected']; checks += 1
    assert [v['event_id'] for v in rank([c(str(n), entity='same') for n in range(3)] + [c('other', entity='other')], 3)['selected']] == ['0', '1', 'other']; checks += 1
    assert len(rank([c(str(n), entity='same') for n in range(3)], 3)['selected']) == 3; checks += 1
    assert not rank([a], 0)['selected']; checks += 1
    assert [v['event_id'] for v in rank([c('a'), c('b')])['selected']] == ['a', 'b']; checks += 1
    try:
        rank([c('name-only', match=3)])
        raise AssertionError('unsupported match accepted')
    except ValueError:
        checks += 1
    print(json.dumps({'self_tests_passed': checks, 'fixtures': 'synthetic, not actual news'}))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('input', nargs='?')
    p.add_argument('--self-test', action='store_true')
    args = p.parse_args()
    if args.self_test:
        self_test()
    elif args.input:
        print(json.dumps(rank(json.loads(Path(args.input).read_text(encoding='utf-8'))), ensure_ascii=False, indent=2))
    else:
        p.error('input JSON file or --self-test required')
