"""Read-only, bounded aggregate export. Never opens creative data or raw events."""
import datetime as dt
from pathlib import Path
import sqlite3
import time

from easel_workbench.runtime.usage_service import REGISTRY, KINDS, TZ


def snapshot(root, *, now=None):
    path = Path(root).resolve() / 'data/usage.sqlite'
    if not path.is_file() or path.is_symlink():
        return {'status': 'unavailable'}
    cut = dt.datetime.fromtimestamp((time.time() if now is None else now)-6*86400, TZ).date().isoformat()
    try:
        connection = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=.1)
        try:
            deadline = time.monotonic()+.5
            connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            enabled = connection.execute("SELECT value FROM usage_meta WHERE key='enabled'").fetchone()
            actions = connection.execute('SELECT action,kind,SUM(count) FROM usage_daily WHERE day>=? GROUP BY action,kind', (cut,)).fetchall()
            screens = connection.execute("SELECT screen,SUM(count) FROM usage_daily WHERE day>=? AND kind='view' GROUP BY screen", (cut,)).fetchall()
            edges = connection.execute('SELECT source,target,SUM(count) FROM usage_edges WHERE day>=? GROUP BY source,target ORDER BY SUM(count) DESC LIMIT 15', (cut,)).fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return {'status': 'unavailable'}
    retired = REGISTRY['retired']
    rows = {}
    totals = {kind: 0 for kind in KINDS}
    for action, kind, count in actions:
        if kind in totals:
            totals[kind] += count
        if action not in REGISTRY['actions'] or kind not in KINDS:
            continue
        row = rows.setdefault(action, {'id': action, 'retired': action in retired['actions']})
        row[kind] = count
    return {'status': 'available', 'days': 7, 'enabled': bool(enabled and enabled[0] == 'true'),
        'totals': totals, 'actions': list(rows.values()),
        'screens': [{'id': key, 'count': count, 'retired': key in retired['screens']}
            for key, count in screens if key in REGISTRY['screens']],
        'paths': [{'from': source, 'to': target, 'count': count,
            'retired': source in retired['screens'] or target in retired['screens']}
            for source, target, count in edges if source in REGISTRY['screens'] and target in REGISTRY['screens']]}
