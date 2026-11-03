import json
import sqlite3

from easel_workbench.diagnostics.usage import snapshot


def test_usage_export_reads_existing_aggregates_without_writing_or_raw_content(tmp_path):
    path = tmp_path/'data/usage.sqlite'
    path.parent.mkdir()
    with sqlite3.connect(path) as c:
        c.executescript('''CREATE TABLE usage_meta(key,value);
            INSERT INTO usage_meta VALUES('enabled','true'),('secret','PRIVATE credential');
            CREATE TABLE usage_daily(day,action,kind,screen,count);
            INSERT INTO usage_daily VALUES('2026-11-03','work.open','activate','works.list',3),
                ('2026-11-03','settings.usage','activate','settings.usage',2),
                ('2026-11-03','','view','skills',5),
                ('2026-11-03','','view','notifications',1),
                ('2020-01-01','work.open','activate','works.list',99);
            CREATE TABLE usage_edges(day,source,target,count);
            INSERT INTO usage_edges VALUES('2026-11-03','skills','works.list',4),
                ('2026-11-03','notifications','settings.usage',1);
            CREATE TABLE usage_events(document);
            INSERT INTO usage_events VALUES('PRIVATE body and filename');''')
    before = path.read_bytes(), path.stat().st_mtime_ns
    result = snapshot(tmp_path, now=1793664000)  # 2026-11-03 UTC
    assert result['status'] == 'available'
    assert result['enabled'] is True
    assert result['totals']['activate'] == 5
    assert {row['id']: row['retired'] for row in result['screens']} == {'skills': False, 'notifications': True}
    assert {row['id']: row['retired'] for row in result['actions']} == {'work.open': False, 'settings.usage': True}
    assert sum(row['retired'] for row in result['paths']) == 1
    assert 'PRIVATE' not in json.dumps(result)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_missing_or_unreadable_usage_is_unavailable_and_never_created(tmp_path):
    assert snapshot(tmp_path) == {'status': 'unavailable'}
    assert not (tmp_path/'data').exists()
    (tmp_path/'data').mkdir()
    (tmp_path/'data/usage.sqlite').write_bytes(b'corrupt database')
    assert snapshot(tmp_path) == {'status': 'unavailable'}


def test_usage_registries_remain_identical_for_queued_historical_events():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    backend = json.loads((root/'easel_workbench/runtime/usage_registry.json').read_text(encoding='utf-8'))
    assert backend == json.loads((root/'web/frontend/src/workbench/usage_registry.json').read_text(encoding='utf-8'))
    assert set(backend['retired']['screens']) <= backend['screens'].keys()
    assert {'skills', 'profiles', 'research', 'chat.list', 'chat.detail', 'works.list'} <= backend['screens'].keys()
