"""Health reads only a bounded index summary and never builds the catalog."""
import json
import sqlite3
import time

import pytest

from easel_workbench.diagnostics import content_library


def ready():
    return {'status':'ready','building':False,'counts':{'nodes':1234,'projects':50},'refreshed_at':1793667000,
            'last_list_ms':12.3,'last_list_bytes':8192,'performance_degraded':False}


def test_only_numeric_metadata_leaves_the_library_health_boundary(tmp_path):
    calls=[];value=ready();value.update(title='PRIVATE_TITLE',path='PRIVATE_PATH',payload={'secret':'PRIVATE_SECRET'})
    value['counts']['documents']=['PRIVATE_BODY']
    def reader(root):calls.append(root);return value
    result=content_library.snapshot(tmp_path,reader=reader)
    assert result==ready() and calls==[tmp_path]
    assert 'PRIVATE' not in json.dumps(result)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('value',[None,[],{'status':'ready'},
    {'status':'ready','counts':{'nodes':False,'projects':2},'refreshed_at':1},
    {'status':'ready','counts':{'nodes':2,'projects':3},'refreshed_at':float('nan')}])
def test_missing_or_invalid_summary_cannot_be_green(tmp_path,value):
    result=content_library.snapshot(tmp_path,reader=lambda root:value)
    assert result['status']=='unavailable'
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('state',['building','stale','error','unavailable'])
def test_nonready_index_state_is_preserved_without_starting_work(tmp_path,state):
    value=ready();value['status']=state;value['building']=state=='building'
    assert content_library.snapshot(tmp_path,reader=lambda root:value)['status']==state
    assert not list(tmp_path.iterdir())


def test_inconsistent_ready_but_building_is_not_reported_ready(tmp_path):
    value=ready();value['building']=True
    assert content_library.snapshot(tmp_path,reader=lambda root:value)['status']=='building'


def test_reader_errors_are_an_optional_feature_failure_not_raw_diagnostics(tmp_path):
    def reader(root):raise RuntimeError('PRIVATE_MESSAGE '+str(root))
    assert content_library.snapshot(tmp_path,reader=reader)=={'status':'unavailable','performance_degraded':False}
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(('metrics','degraded'),[
    ({'last_list_ms':1000,'last_list_bytes':100000},False),
    ({'last_list_ms':1000.01},True),({'last_list_bytes':100001},True),
    ({'last_list_ms':float('nan'),'last_list_bytes':False,'performance_degraded':True},False),
])
def test_library_performance_flag_is_derived_from_bounded_measurements(tmp_path,metrics,degraded):
    value=ready();value.update(metrics)
    result=content_library.snapshot(tmp_path,reader=lambda root:value)
    assert result['status']=='ready' and result['performance_degraded'] is degraded
    assert not list(tmp_path.iterdir())


def test_bridge_invokes_only_the_readonly_library_summary(tmp_path,monkeypatch):
    from easel_workbench.diagnostics import health_bridge as bridge
    bound={'runtime':{'release':'workbench-test','manifest_sha256':'a'*64},
           'native':{'release':'native-test','manifest_sha256':'b'*64}}
    monkeypatch.setattr(bridge.watchdog,'controls',lambda root:bound)
    monkeypatch.setattr(bridge.watchdog,'read',lambda path:{'release':'workbench-test','paused':False,'roles':{}})
    monkeypatch.setattr(bridge.watchdog,'health_token',lambda root:'c'*64)
    monkeypatch.setattr(bridge.watchdog,'ingress_origin',lambda root:'https://example.ts.net:8443')
    monkeypatch.setattr(bridge,'_operator_idle',lambda root:{'busy':False,'unknown_receipts':False})
    monkeypatch.setattr(bridge,'snapshot',lambda root:{'status':'healthy','ok':True})
    monkeypatch.setattr(bridge,'usage_snapshot',lambda root:{'status':'unavailable'})
    monkeypatch.setattr(bridge,'rows',lambda:{})
    monkeypatch.setattr(bridge,'task',lambda root:True)
    called=[]
    monkeypatch.setattr(bridge,'library_snapshot',lambda root:(called.append(root) or ready()))
    result=bridge.inspect(tmp_path)
    assert result['content_library']==ready() and called==[tmp_path.resolve()]
    assert not list(tmp_path.iterdir())


def test_actual_index_health_missing_database_does_not_create_anything(tmp_path):
    assert content_library.snapshot(tmp_path)['status']=='unavailable'
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(('state','expected'),[
    ({'status':'ready','building':False},'ready'),
    ({'status':'building','building':True,'build_started_at':1},'stale'),
    ({'status':'error','building':False},'error'),
])
def test_actual_index_summary_is_readonly_and_never_constructs_catalog(tmp_path,monkeypatch,state,expected):
    from easel_workbench.features.works import library_index
    path=tmp_path/'data'/'content-library.sqlite';path.parent.mkdir()
    value=ready();value.update(state,refreshed_at=time.time(),path='PRIVATE_PATH',error_type='PRIVATE_ERROR')
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        db.execute('INSERT INTO metadata VALUES(?,?)',('state',json.dumps(value)))
    before=path.read_bytes();stamp=path.stat().st_mtime_ns
    def forbidden(*args,**kwargs):raise AssertionError('health must never construct the catalog')
    monkeypatch.setattr(library_index,'LibraryIndex',forbidden)
    result=content_library.snapshot(tmp_path)
    assert result['status']==expected
    assert result['counts']=={'nodes':1234,'projects':50}
    assert 'PRIVATE' not in json.dumps(result)
    assert path.read_bytes()==before and path.stat().st_mtime_ns==stamp
    assert {item.name for item in path.parent.iterdir()}=={'content-library.sqlite'}
