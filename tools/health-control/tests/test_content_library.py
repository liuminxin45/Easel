import importlib.util
import json
from pathlib import Path

import pytest

from easel_health_control.content_library import project


def ready():
    return {'status':'ready','building':False,'counts':{'nodes':10000,'projects':1000},'refreshed_at':1000,
            'last_list_ms':9,'last_list_bytes':2048,'performance_degraded':False}


def test_untrusted_feature_payload_is_reduced_to_bounded_metadata():
    value=ready();value['raw']='PRIVATE_BODY';value['counts']['paths']=['PRIVATE_PATH']
    assert project(value)==ready()
    assert 'PRIVATE' not in json.dumps(project(value))


@pytest.mark.parametrize('value',[None,[],{'status':'green'}, {'status':'ready'},
    {'status':'ready','refreshed_at':1,'counts':{'nodes':10**100,'projects':1}},
    {'status':'ready','refreshed_at':1,'counts':{'nodes':True,'projects':1}}])
def test_malformed_or_incomplete_summary_is_unavailable(value):
    assert project(value)['status']=='unavailable'


@pytest.mark.parametrize('state,expected',[('ready','healthy'),('building','content_library_building'),
    ('stale','content_library_degraded'),('error','content_library_degraded'),('unavailable','content_library_unknown')])
def test_library_state_is_visible_but_never_restarts_a_healthy_process(state,expected):
    spec=importlib.util.spec_from_file_location('library_health_monitor_fixture',Path(__file__).with_name('test_monitor_core.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    fixture=module.MonitorFaultTests();fixture.setUp()
    try:
        fixture.healthy();value=ready();value.update(status=state,building=state=='building')
        fixture.inspection['content_library']=value
        result=fixture.monitor().tick(allow_repair=True)
        assert result['observation']['status']==expected
        assert result['observation']['content_library']['status']==state
        assert fixture.calls==[]
    finally:fixture.doCleanups()


@pytest.mark.parametrize('metrics',[
    {'last_list_ms':1001,'performance_degraded':False},
    {'last_list_bytes':100001,'performance_degraded':False},
])
def test_slow_or_oversized_ready_library_is_degraded_without_process_restart(metrics):
    spec=importlib.util.spec_from_file_location('library_health_monitor_fixture',Path(__file__).with_name('test_monitor_core.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    fixture=module.MonitorFaultTests();fixture.setUp()
    try:
        fixture.healthy();value=ready();value.update(metrics)
        fixture.inspection['content_library']=value
        result=fixture.monitor().tick(allow_repair=True)
        assert result['observation']['status']=='content_library_degraded'
        assert result['observation']['content_library']['status']=='ready'
        assert result['observation']['content_library']['performance_degraded'] is True
        assert fixture.calls==[]
    finally:fixture.doCleanups()


def test_performance_flag_is_recomputed_with_exact_thresholds():
    value=ready();value.update(last_list_ms=1000,last_list_bytes=100000,performance_degraded=True)
    assert project(value)['performance_degraded'] is False
