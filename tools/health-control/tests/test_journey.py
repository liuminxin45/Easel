"""Controller browser checks never create production sessions or model turns."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from easel_health_control import journey
from easel_health_control.state import StateStore


NOW=dt.datetime.fromisoformat('2026-11-03T12:00:00+08:00').timestamp()


def config(tmp_path):
    app=tmp_path/'app';(app/'data').mkdir(parents=True)
    native=app/'native-releases/native-test';native.mkdir(parents=True)
    raw=json.dumps({'files':{}}).encode();(native/'native-manifest.json').write_bytes(raw)
    native_binding={'release':'native-test','manifest_sha256':hashlib.sha256(raw).hexdigest()}
    backend=app/'workbench-releases/workbench-test';backend.mkdir(parents=True)
    module=backend/'easel_workbench/diagnostics/session_journey.py';module.parent.mkdir(parents=True);module.write_text('pass',encoding='utf-8')
    raw=json.dumps({'native':native_binding,'files':{'easel_workbench/diagnostics/session_journey.py':hashlib.sha256(module.read_bytes()).hexdigest()}}).encode()
    (backend/'workbench-release.json').write_bytes(raw)
    for name,value in [('active-workbench.json',{'release':'workbench-test','manifest_sha256':hashlib.sha256(raw).hexdigest()}),
                       ('active-native.json',native_binding)]:
        (app/'data'/name).write_text(json.dumps(value),encoding='utf-8')
    state=app/'.local/workbench-deployment';state.mkdir(parents=True)
    (state/'admission.json').write_text(json.dumps({'workers':True}),encoding='utf-8')
    (state/'cutover.json').write_text(json.dumps({'phase':'live','target_root':str(app)}),encoding='utf-8')
    return {'app_root':str(app)}


def completed(operation,**change):
    workspace=StateStore(operation['workspace']);evidence=StateStore(workspace.root/'evidence')
    evidence.write('report.json',{'passed':True,'binding':operation['binding'],'real_model_calls':0,
        'production_data_access':False,'checks':[{'passed':True}]})
    receipt={'operation_id':operation['operation_id'],'binding':operation['binding'],'status':'completed',
        'real_model_calls':0,'production_data_access':False,'checks':1,
        'report_sha256':hashlib.sha256((evidence.root/'report.json').read_bytes()).hexdigest(),**change}
    workspace.write('receipt.json',receipt)
    return receipt


def test_launch_journal_precedes_spawn_and_repeated_ticks_do_not_block_or_relaunch(tmp_path):
    cfg=config(tmp_path);store=StateStore(tmp_path/'controller');calls=[]
    def spawn(command,**options):
        calls.append((command,options))
        old=StateStore(store.root/'browser-journey').read('operation.json')
        assert old['launch_attempted'] and old['status']=='launching'
        assert old['real_model_calls']==0 and old['production_data_access'] is False
        assert Path(command[-1]).name=='request.json' and command[1]=='-I'
        assert options['stdin'] is not None and options['stdout'] is not None
        return SimpleNamespace(pid=99)
    first=journey.scheduled_tick(cfg,store,clock=lambda:NOW,spawn=spawn)
    again=journey.scheduled_tick(cfg,store,clock=lambda:NOW+1,spawn=spawn)
    assert first['operation_id']==again['operation_id'] and len(calls)==1
    assert again['status']=='running'


def test_matching_original_receipt_completes_without_spawning_another_worker(tmp_path):
    cfg=config(tmp_path);store=StateStore(tmp_path/'controller');calls=[]
    spawn=lambda *a,**k:(calls.append(a) or SimpleNamespace(pid=99))
    first=journey.scheduled_tick(cfg,store,clock=lambda:NOW,spawn=spawn)
    completed(first)
    second=journey.scheduled_tick(cfg,store,clock=lambda:NOW+2,spawn=spawn)
    assert second['status']=='completed' and second['worker_receipt_confirmed']
    assert len(calls)==1


def test_unknown_spawn_is_not_replayed_even_on_next_day(tmp_path):
    cfg=config(tmp_path);store=StateStore(tmp_path/'controller');calls=[]
    def spawn(*a,**k):calls.append(a);raise OSError('launch response lost')
    first=journey.scheduled_tick(cfg,store,clock=lambda:NOW,spawn=spawn)
    assert first['status']=='unknown'
    journey.scheduled_tick(cfg,store,clock=lambda:NOW+600,spawn=spawn)
    next_day=journey.scheduled_tick(cfg,store,clock=lambda:NOW+86400,spawn=spawn)
    assert next_day['status']=='blocked' and next_day['reason']=='previous_browser_journey_unresolved'
    assert len(calls)==1


@pytest.mark.parametrize('change',[{'operation_id':'other'},{'binding':{}},{'real_model_calls':1},{'production_data_access':True}])
def test_mismatched_or_unsafe_receipt_cannot_be_reported_as_success(tmp_path,change):
    cfg=config(tmp_path);store=StateStore(tmp_path/'controller')
    first=journey.scheduled_tick(cfg,store,clock=lambda:NOW,spawn=lambda *a,**k:SimpleNamespace(pid=99))
    completed(first,**change)
    value=journey.scheduled_tick(cfg,store,clock=lambda:NOW+2,spawn=lambda *a,**k:pytest.fail('must not relaunch'))
    assert value['status']=='unknown'


def test_next_day_runs_new_isolated_workspace_only_after_previous_terminal_receipt(tmp_path):
    cfg=config(tmp_path);store=StateStore(tmp_path/'controller');calls=[]
    spawn=lambda *a,**k:(calls.append(a) or SimpleNamespace(pid=99))
    first=journey.scheduled_tick(cfg,store,clock=lambda:NOW,spawn=spawn)
    StateStore(first['workspace']).write('receipt.json',{'operation_id':first['operation_id'],'binding':first['binding'],
        'status':'failed','real_model_calls':0,'production_data_access':False})
    later=journey.scheduled_tick(cfg,store,clock=lambda:NOW+86400,spawn=spawn)
    assert first['operation_id']!=later['operation_id'] and first['workspace']!=later['workspace']
    assert len(calls)==2 and Path(first['workspace'],'receipt.json').is_file()


def test_canary_state_is_unchanged_and_disabled_journey_does_not_read_app(tmp_path):
    store=StateStore(tmp_path/'controller');store.write('daily-status.json',{'operation_id':'original-real-agent','status':'failed'})
    before=(store.root/'daily-status.json').read_bytes()
    value=journey.scheduled_tick({'app_root':str(tmp_path/'missing'),'daily_browser_journey_enabled':False},store,
        clock=lambda:NOW,spawn=lambda *a,**k:pytest.fail('disabled'))
    assert value['status']=='disabled' and (store.root/'daily-status.json').read_bytes()==before
    assert store.read('journey-status.json')['status']=='disabled'


def test_workspace_inside_production_is_rejected(tmp_path):
    cfg=config(tmp_path)
    with pytest.raises(ValueError,match='external'):
        journey.scheduled_tick(cfg,StateStore(Path(cfg['app_root'])/'state'),clock=lambda:NOW)


def test_changed_manifest_member_is_rejected_before_app_import(tmp_path):
    from easel_health_control.journey_entry import package
    directory=tmp_path/'release';directory.mkdir();(directory/'module.py').write_text('value=1',encoding='utf-8')
    raw=json.dumps({'files':{'module.py':hashlib.sha256((directory/'module.py').read_bytes()).hexdigest()}}).encode()
    (directory/'manifest.json').write_bytes(raw)
    expected=hashlib.sha256(raw).hexdigest();package(directory,'manifest.json',expected)
    (directory/'module.py').write_text('value=2',encoding='utf-8')
    with pytest.raises(ValueError,match='member_changed'):package(directory,'manifest.json',expected)


@pytest.mark.parametrize('gate',['paused','workers','fenced','mixed_pair','missing_capability'])
def test_unready_or_mixed_selection_does_not_reserve_daily_identity(tmp_path,gate):
    cfg=config(tmp_path);app=Path(cfg['app_root']);state=StateStore(tmp_path/'controller')
    if gate=='paused':(app/'.local/workbench-deployment/paused').write_text('hold',encoding='utf-8')
    elif gate=='workers':(app/'.local/workbench-deployment/admission.json').write_text('{"workers":false}',encoding='utf-8')
    elif gate=='fenced':(app/'.local/workbench-deployment/cutover.json').write_text(json.dumps({'phase':'fenced','target_root':str(app)}),encoding='utf-8')
    elif gate=='mixed_pair':
        (app/'data/active-native.json').write_text(json.dumps({'release':'native-other','manifest_sha256':'c'*64}),encoding='utf-8')
    else:
        manifest=app/'workbench-releases/workbench-test/workbench-release.json'
        value=json.loads(manifest.read_text());value['files']={};manifest.write_text(json.dumps(value),encoding='utf-8')
        pointer={'release':'workbench-test','manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}
        (app/'data/active-workbench.json').write_text(json.dumps(pointer),encoding='utf-8')
    value=journey.scheduled_tick(cfg,state,clock=lambda:NOW,spawn=lambda *a,**k:pytest.fail('must not launch'))
    assert value['status']=='deferred' and value['launch_attempted'] is False
    assert not (state.root/'browser-journey/operation.json').exists()
    assert not (state.root/'browser-journey/2026-11-03').exists()


def test_entry_rechecks_admission_after_verification_and_never_starts_on_transition(tmp_path,monkeypatch):
    from easel_health_control import journey_entry
    cfg=config(tmp_path);app=Path(cfg['app_root']);store=StateStore(tmp_path/'controller')
    operation=journey.scheduled_tick(cfg,store,clock=lambda:NOW,spawn=lambda *a,**k:SimpleNamespace(pid=99))
    original=journey_entry.package;calls=[]
    def package(*args):
        result=original(*args);calls.append(args)
        if len(calls)==2:(app/'.local/workbench-deployment/admission.json').write_text('{"workers":false}',encoding='utf-8')
        return result
    monkeypatch.setattr(journey_entry,'package',package)
    with pytest.raises(journey.JourneyDeferred):
        journey_entry.execute(operation,runner=lambda *a,**k:pytest.fail('no child may start'))
    assert len(calls)==2


def test_proven_preflight_deferred_receipt_is_not_retried_on_same_day(tmp_path):
    cfg=config(tmp_path);store=StateStore(tmp_path/'controller');calls=[]
    first=journey.scheduled_tick(cfg,store,clock=lambda:NOW,spawn=lambda *a,**k:(calls.append(a) or SimpleNamespace(pid=99)))
    StateStore(first['workspace']).write('receipt.json',{'operation_id':first['operation_id'],'binding':first['binding'],
        'status':'deferred','real_model_calls':0,'production_data_access':False,'child_started':False,'preflight_confirmed_not_started':True})
    second=journey.scheduled_tick(cfg,store,clock=lambda:NOW+2,spawn=lambda *a,**k:pytest.fail('must not relaunch'))
    assert second['status']=='deferred' and second['worker_receipt_confirmed'] and len(calls)==1


@pytest.mark.parametrize('fault',['missing','hash_mismatch','wrong_binding','failed','unsafe_model','unsafe_production'])
def test_success_receipt_requires_actual_matching_passed_evidence(tmp_path,fault):
    cfg=config(tmp_path);store=StateStore(tmp_path/'controller')
    first=journey.scheduled_tick(cfg,store,clock=lambda:NOW,spawn=lambda *a,**k:SimpleNamespace(pid=99))
    receipt=completed(first);path=Path(first['workspace'])/'evidence/report.json'
    if fault=='missing':path.unlink()
    elif fault=='hash_mismatch':path.write_text('{}',encoding='utf-8')
    else:
        value=json.loads(path.read_text())
        if fault=='wrong_binding':value['binding']={}
        elif fault=='failed':value['passed']=False
        elif fault=='unsafe_model':value['real_model_calls']=1
        else:value['production_data_access']=True
        path.write_text(json.dumps(value),encoding='utf-8')
        receipt['report_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();StateStore(first['workspace']).write('receipt.json',receipt)
    second=journey.scheduled_tick(cfg,store,clock=lambda:NOW+1,spawn=lambda *a,**k:pytest.fail('must not launch'))
    assert second['status']=='unknown' and second['reason']=='journey_success_evidence_unverified'


def test_previously_confirmed_success_is_revalidated_instead_of_cached_green(tmp_path):
    cfg=config(tmp_path);store=StateStore(tmp_path/'controller')
    first=journey.scheduled_tick(cfg,store,clock=lambda:NOW,spawn=lambda *a,**k:SimpleNamespace(pid=99));completed(first)
    assert journey.scheduled_tick(cfg,store,clock=lambda:NOW+1)['status']=='completed'
    (Path(first['workspace'])/'evidence/report.json').write_text('{}',encoding='utf-8')
    assert journey.scheduled_tick(cfg,store,clock=lambda:NOW+2)['status']=='unknown'


def test_missing_global_journal_recovers_original_per_day_identity_without_rewriting_request(tmp_path):
    cfg=config(tmp_path);store=StateStore(tmp_path/'controller');calls=[]
    first=journey.scheduled_tick(cfg,store,clock=lambda:NOW,spawn=lambda *a,**k:(calls.append(a) or SimpleNamespace(pid=99)))
    path=Path(first['workspace'])/'request.json';original=path.read_bytes()
    (store.root/'browser-journey/operation.json').unlink()
    second=journey.scheduled_tick(cfg,store,clock=lambda:NOW+2,spawn=lambda *a,**k:pytest.fail('must not duplicate'))
    assert second['operation_id']==first['operation_id'] and path.read_bytes()==original and len(calls)==1


def test_existing_day_workspace_without_identity_is_not_overwritten(tmp_path):
    cfg=config(tmp_path);store=StateStore(tmp_path/'controller')
    (store.root/'browser-journey/2026-11-03').mkdir(parents=True)
    value=journey.scheduled_tick(cfg,store,clock=lambda:NOW,spawn=lambda *a,**k:pytest.fail('must not duplicate'))
    assert value['status']=='unknown' and value['reason']=='daily_browser_identity_missing'
    assert not (store.root/'browser-journey/2026-11-03/request.json').exists()


@pytest.mark.parametrize('missing_journal',[False,True])
def test_backwards_calendar_day_is_refused_even_if_global_journal_is_missing(tmp_path,missing_journal):
    cfg=config(tmp_path);store=StateStore(tmp_path/'controller')
    first=journey.scheduled_tick(cfg,store,clock=lambda:NOW,spawn=lambda *a,**k:SimpleNamespace(pid=99))
    path=Path(first['workspace'])/'request.json';original=path.read_bytes()
    if missing_journal:(store.root/'browser-journey/operation.json').unlink()
    value=journey.scheduled_tick(cfg,store,clock=lambda:NOW-86400,spawn=lambda *a,**k:pytest.fail('clock rollback'))
    assert value['status']=='blocked' and value['reason']=='browser_journey_clock_rollback'
    assert path.read_bytes()==original


def test_old_success_binding_is_explicitly_stale_after_deploy_and_not_rerun_same_day(tmp_path):
    cfg=config(tmp_path);store=StateStore(tmp_path/'controller');app=Path(cfg['app_root'])
    first=journey.scheduled_tick(cfg,store,clock=lambda:NOW,spawn=lambda *a,**k:SimpleNamespace(pid=99));completed(first)
    manifest=app/'workbench-releases/workbench-test/workbench-release.json';value=json.loads(manifest.read_text())
    value['native']={'release':'native-other','manifest_sha256':'c'*64};manifest.write_text(json.dumps(value),encoding='utf-8')
    (app/'data/active-native.json').write_text(json.dumps(value['native']),encoding='utf-8')
    (app/'data/active-workbench.json').write_text(json.dumps({'release':'workbench-test','manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}),encoding='utf-8')
    result=journey.scheduled_tick(cfg,store,clock=lambda:NOW+1,spawn=lambda *a,**k:pytest.fail('same day'))
    assert result['status']=='stale_binding' and result['tested_status']=='completed' and not result['binding_matches_current']
