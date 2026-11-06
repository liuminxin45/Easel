"""Exact legacy recovery plans, TEMP DB only; no native call or process kill."""
import importlib.util
import json
from pathlib import Path

import pytest

_spec=importlib.util.spec_from_file_location('retire_fixtures',Path(__file__).with_name('test_workbench_chat.py'))
_f=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_f)
runtime,commands,service=_f.runtime,_f.commands,_f.service
from easel.harnesses import store
from easel_workbench.features.conversations import retirement
from easel_workbench.features.conversations.local_execution import release, closed
from easel_workbench.features.conversations.receipts import sha


@pytest.fixture
def legacy(service):
    s,_=service
    turn,env=s._admit(_f.value(),snapshot=None,actual_prompt='FROZEN original')
    s._release_owned(turn['id'])
    turn.update(status='unknown',stop_requested=True,native_id='old-thread',native_turn_id='old-turn',hook_status='completed')
    with s.store.connect() as c:s._put_turn(c,turn)
    store.bind(s.sessions_dir,'workbench-session','codex','old-thread')
    state=s.root/'.local/workbench-deployment';state.mkdir(parents=True,exist_ok=True)
    (state/'pids.json').write_text(json.dumps({'manager':1,'roles':{'server':2}}))
    (s.root/'data/active-workbench.json').write_text(json.dumps({'release':'workbench-old','manifest_sha256':'a'*64}))
    inventory={pid:{'creation_ticks':str(pid*1000),'command':'owned-'+str(pid)} for pid in (1,2)}
    plan=retirement.preview(s.root,turn['id'],inventory=inventory)
    proof={'source':'identity_fenced_profile_retirement','exited':True,'processes':[
        {'pid':pid,'creation_ticks':str(pid*1000),'command_sha256':sha(('owned-'+str(pid)).encode())} for pid in (1,2)]}
    return s,turn,plan,proof


def test_controlled_retirement_preserves_unknown_frozen_inputs_history_and_binding(legacy):
    s,turn,plan,proof=legacy
    result=retirement.apply(s.root,plan,proof)
    actual=s.get_turn(turn['id'],private=True)
    assert actual['status']=='unknown' and actual['execution_closed'] and actual['actual_prompt']=='FROZEN original'
    assert result['pending_released'] and result['replayed'] is False
    assert store.binding(s.sessions_dir,'workbench-session')['native_id']=='old-thread'
    session=s.history('workbench-session')['session']
    assert session['pendingTurnId'] is None and session['messages'][0]['content']=='用户原话'
    assert session['native_session_key']!='workbench-session'
    with pytest.raises(ValueError):retirement.apply(s.root,plan,proof)


@pytest.mark.parametrize('change',['turn','session','binding','owner-time','owner-command','no-exit'])
def test_retirement_refuses_drift_or_unproven_process_exit(legacy,change):
    s,turn,plan,proof=legacy
    if change=='turn':
        turn['output']='later actual result'
        with s.store.connect() as c:s._put_turn(c,turn)
    if change=='session':
        with s.store.connect() as c:
            session=s._session(c,turn['session_id']);session['title']='later user rename';s._put_session(c,session)
    if change=='binding':
        plan['native_binding']={**plan['native_binding'],'native_id':'different'}
    if change=='owner-time':proof['processes'][0]['creation_ticks']='9000'
    if change=='owner-command':proof['processes'][0]['command_sha256']='f'*64
    if change=='no-exit':proof['exited']=False
    with pytest.raises(ValueError):retirement.apply(s.root,plan,proof)
    assert s.history('workbench-session')['session']['pendingTurnId']==turn['id']


def test_old_closure_cannot_release_new_pending_or_execution_generation(legacy):
    s,turn,plan,proof=legacy
    retirement.apply(s.root,plan,proof)
    session=s.history('workbench-session')['session']
    assert not release(session,s.get_turn(turn['id'],private=True))
    session['pendingTurnId']='new-explicit-turn'
    assert not release(session,s.get_turn(turn['id'],private=True))
    assert not closed({**turn,'local_execution_closed':{'source':'owned_rpc_process'}})


def test_orphan_recovery_never_closes_a_live_owner_and_reclaims_exact_test_tree(tmp_path):
    import os,sys,subprocess,time
    if os.name!='nt':pytest.skip('Windows native process ownership')
    from easel_workbench.features.conversations.local_execution import process_ownership,close_orphan
    from easel_workbench.runtime.scripts.windows_process_identity import ProcessIdentity
    pidfile=tmp_path/'child.pid'
    code="import subprocess,sys,time;from pathlib import Path;child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(90)']);Path(sys.argv[1]).write_text(str(child.pid));time.sleep(90)"
    proc=subprocess.Popen([sys.executable,'-c',code,str(pidfile)],creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        until=time.monotonic()+5
        while not pidfile.exists() or not pidfile.read_text():
            assert time.monotonic()<until;time.sleep(.01)
        with ProcessIdentity(int(pidfile.read_text())) as child:
            ownership=process_ownership(proc.pid)
            turn={'id':'TEMP-only-orphan','local_process':{'pid':proc.pid,'process_token':'b'*32,**ownership}}
            assert close_orphan(turn) is None and proc.poll() is None and not child.exited()
            # Simulate persisted ownership from an exited backend whose PID was reused.
            turn['local_process']['owner_creation_ticks']='1'
            receipt=close_orphan(turn)
            assert receipt['orphan_reclaimed'] and receipt['tree_closed'] and closed({**turn,'local_execution_closed':receipt})
            assert child.exited() and proc.wait(timeout=3)==receipt['returncode']
    finally:
        if proc.poll() is None:
            subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
            proc.wait(timeout=5)
