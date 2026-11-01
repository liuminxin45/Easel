"""TEMP durable crash sequences; never launch a workbench or stop a process."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from easel_workbench.role_backoff import RoleBackoff


def test_short_lived_crashes_back_off_exponentially_with_a_persistent_cap(tmp_path):
    path=tmp_path/'backoff.json';now=1000
    delays=[]
    for index in range(9):
        policy=RoleBackoff(path);assert policy.ready('workbench-a','server',now)
        policy.started('workbench-a','server',index+1,now)
        policy.exited('workbench-a','server',index+1,now+1)
        entry=policy.state['entries']['workbench-a:server'];delays.append(entry['next_attempt']-(now+1))
        assert entry['failures']==index+1
        policy=RoleBackoff(path)
        assert not policy.ready('workbench-a','server',entry['next_attempt']-.01)
        now=entry['next_attempt'];assert policy.ready('workbench-a','server',now)
    assert delays==[3,6,12,24,48,96,120,120,120]


def test_budget_is_reloaded_by_a_real_separate_python_process(tmp_path):
    path=tmp_path/'backoff.json';policy=RoleBackoff(path)
    policy.started('workbench-a','worker',13,1000);policy.exited('workbench-a','worker',13,1001)
    code='from easel_workbench.role_backoff import RoleBackoff;import sys,json;p=RoleBackoff(sys.argv[1]);print(json.dumps({"ready":p.ready("workbench-a","worker",1002),"entry":p.state["entries"]["workbench-a:worker"]}))'
    result=json.loads(subprocess.check_output([sys.executable,'-c',code,str(path)],cwd=Path(__file__).resolve().parents[1],text=True))
    assert result['ready'] is False and result['entry']['failures']==1 and result['entry']['next_attempt']==1004


def test_only_observed_stable_runtime_resets_consecutive_failures(tmp_path):
    policy=RoleBackoff(tmp_path/'backoff.json')
    policy.started('workbench-a','server',1,1000);policy.exited('workbench-a','server',1,1001)
    policy.started('workbench-a','server',2,1004)
    policy.alive('workbench-a','server',2,1063)
    assert policy.state['entries']['workbench-a:server']['failures']==1
    policy.alive('workbench-a','server',2,1064)
    assert policy.state['entries']['workbench-a:server']['failures']==0
    policy.exited('workbench-a','server',2,1065)
    assert policy.state['entries']['workbench-a:server']['next_attempt']==1068


def test_long_unobserved_absence_does_not_fake_stable_runtime(tmp_path):
    path=tmp_path/'backoff.json';policy=RoleBackoff(path)
    policy.started('workbench-a','collector',9,1000);policy.exited('workbench-a','collector',9,1001)
    policy.started('workbench-a','collector',10,1004)
    policy=RoleBackoff(path);policy.missing('workbench-a','collector',2000)
    entry=policy.state['entries']['workbench-a:collector']
    assert entry['failures']==2 and entry['next_attempt']==2006
    before=path.read_bytes();policy.missing('workbench-a','collector',2001)
    assert path.read_bytes()==before


def test_live_adoption_does_not_charge_retry_and_stability_is_real(tmp_path):
    path=tmp_path/'backoff.json';policy=RoleBackoff(path)
    policy.started('workbench-a','local',5,1000);policy.exited('workbench-a','local',5,1001)
    policy.adopted('workbench-a','local',7,1002,1003)
    assert policy.state['entries']['workbench-a:local']['failures']==1
    before=path.read_bytes();policy=RoleBackoff(path)
    policy.adopted('workbench-a','local',7,1002,1004)
    assert path.read_bytes()==before
    policy.alive('workbench-a','local',7,1062)
    assert policy.state['entries']['workbench-a:local']['failures']==0


def test_role_and_release_budgets_are_independent(tmp_path):
    policy=RoleBackoff(tmp_path/'backoff.json')
    policy.started('workbench-a','server',11,1000);policy.exited('workbench-a','server',11,1001)
    assert not policy.ready('workbench-a','server',1002)
    for release,role in [('workbench-b','server'),('workbench-a','worker')]:
        assert policy.ready(release,role,1002);policy.started(release,role,12,1002)
    assert policy.snapshot('workbench-a')['server']['failures']==1
    assert policy.snapshot('workbench-b')['server']['failures']==0


def test_alive_polling_does_not_rewrite_unchanged_budget(tmp_path):
    path=tmp_path/'backoff.json';policy=RoleBackoff(path);policy.started('workbench-a','publisher',2,1000)
    before=path.read_bytes()
    for at in range(1001,1060):policy.alive('workbench-a','publisher',2,at)
    assert path.read_bytes()==before
    policy.alive('workbench-a','publisher',2,1060);after=path.read_bytes();assert before!=after
    for at in range(1061,1100):policy.alive('workbench-a','publisher',2,at)
    assert path.read_bytes()==after


@pytest.mark.parametrize('raw',['{broken','{}','[]','{"schema":2,"entries":{}}','{"schema":1,"entries":{}}','{"schema":1,"entries":{"workbench-a:server":{"failures":0}}}'])
def test_corrupt_persistent_state_fails_closed_and_original_bytes_remain(tmp_path,raw):
    path=tmp_path/'backoff.json';path.write_text(raw,encoding='utf-8');before=path.read_bytes()
    with pytest.raises(ValueError,match='original file retained'):RoleBackoff(path)
    assert path.read_bytes()==before


def test_clock_rollback_cannot_admit_a_retry_or_clear_budget(tmp_path):
    path=tmp_path/'backoff.json';policy=RoleBackoff(path)
    policy.started('workbench-a','learning',1,1000);policy.exited('workbench-a','learning',1,1001)
    before=path.read_bytes();assert not policy.ready('workbench-a','learning',999)
    with pytest.raises(ValueError):policy.started('workbench-a','learning',2,999)
    assert path.read_bytes()==before


def test_spawn_error_is_persistent_and_does_not_reset_other_roles(tmp_path):
    path=tmp_path/'backoff.json';policy=RoleBackoff(path)
    policy.spawn_failed('workbench-a','feedback',1000,'PermissionError')
    policy=RoleBackoff(path);assert not policy.ready('workbench-a','feedback',1001)
    assert policy.snapshot('workbench-a')['feedback']=={'failures':1,'next_attempt':1003,'error_type':'PermissionError'}
    assert policy.ready('workbench-a','worker',1001)


class StopSupervisor(Exception):pass


def supervisor_root(tmp_path,*,admitted=True,all_roles=True):
    state=tmp_path/'.local/workbench-deployment';state.mkdir(parents=True)
    data=tmp_path/'data';data.mkdir();release=tmp_path/'workbench-releases/workbench-fixture';release.mkdir(parents=True)
    manifest=release/'workbench-release.json';manifest.write_text('{}',encoding='utf-8')
    (data/'active-workbench.json').write_text(json.dumps({'release':release.name,'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}),encoding='utf-8')
    (state/'admission.json').write_text(json.dumps({'workers':admitted}),encoding='utf-8')
    if all_roles:
        for name,value in [('feedback-config.json',{}),('collection-config.json',{'enabled':True}),('learning-enabled.json',{'enabled':True}),('automation-enabled.json',{'local_io':True})]:
            (data/name).write_text(json.dumps(value),encoding='utf-8')
    return state


def test_supervisor_adopts_each_exact_live_role_once_and_keeps_seven_roles(tmp_path,monkeypatch):
    from easel_workbench import supervisor,processes
    state=supervisor_root(tmp_path);clock=[1000];calls=[];roles={}
    def existing(root,release,role):
        calls.append(role);pid=100+len(calls)
        child=SimpleNamespace(pid=pid,poll=lambda:None,identity=SimpleNamespace(creation_ticks=int((900+11_644_473_600)*10_000_000)))
        roles[role]=pid;return child
    def sleep(_):
        clock[0]+=3
        if clock[0]>=1009:raise StopSupervisor()
    monkeypatch.setattr(processes,'existing',existing)
    monkeypatch.setattr(supervisor.time,'time',lambda:clock[0]);monkeypatch.setattr(supervisor.time,'sleep',sleep)
    monkeypatch.setattr(supervisor.subprocess,'Popen',lambda *_a,**_k:pytest.fail('An adopted live role was duplicated'))
    with pytest.raises(StopSupervisor):supervisor.main(tmp_path)
    assert len(calls)==7 and len(set(calls))==7
    status=json.loads((state/'pids.json').read_text());assert status['roles']==roles
    assert len(status['backoff'])==7 and all(e['failures']==0 for e in status['backoff'].values())


def test_supervisor_retries_short_exit_once_only_after_delay(tmp_path,monkeypatch):
    from easel_workbench import supervisor,processes
    state=supervisor_root(tmp_path,admitted=False,all_roles=False);clock=[1000];starts=[]
    def spawn(*_a,**_k):
        starts.append(clock[0]);first=len(starts)==1
        return SimpleNamespace(pid=200+len(starts),poll=lambda:1 if first and clock[0]>=1003 else None)
    def sleep(_):
        clock[0]+=3
        if clock[0]>=1012:raise StopSupervisor()
    monkeypatch.setattr(processes,'existing',lambda *_:None)
    monkeypatch.setattr(supervisor.time,'time',lambda:clock[0]);monkeypatch.setattr(supervisor.time,'sleep',sleep)
    monkeypatch.setattr(supervisor.subprocess,'Popen',spawn)
    with pytest.raises(StopSupervisor):supervisor.main(tmp_path)
    assert starts==[1000,1006]
    budget=RoleBackoff(state/'role-backoff.json').snapshot('workbench-fixture')['server'];assert budget['failures']==1
    assert json.loads((state/'admission.json').read_text())=={'workers':False}


def test_supervisor_paused_state_never_starts_or_adopts_roles(tmp_path,monkeypatch):
    from easel_workbench import supervisor,processes
    state=supervisor_root(tmp_path);(state/'paused').write_text('deployment pause',encoding='utf-8')
    monkeypatch.setattr(processes,'existing',lambda *_:pytest.fail('Paused supervisor adopted a role'))
    monkeypatch.setattr(supervisor.subprocess,'Popen',lambda *_a,**_k:pytest.fail('Paused supervisor launched a role'))
    def sleep(_):raise StopSupervisor()
    monkeypatch.setattr(supervisor.time,'sleep',sleep)
    with pytest.raises(StopSupervisor):supervisor.main(tmp_path)
    assert json.loads((state/'pids.json').read_text())['roles']=={}
    assert not (state/'role-backoff.json').exists()


def test_server_spawn_failure_is_delayed_without_preventing_other_roles(tmp_path,monkeypatch):
    from easel_workbench import supervisor,processes
    state=supervisor_root(tmp_path);spawned=[]
    def spawn(command,**_options):
        role=command[2]
        if role=='server':raise PermissionError('TEMP executable is unavailable')
        spawned.append(role);return SimpleNamespace(pid=300+len(spawned),poll=lambda:None)
    monkeypatch.setattr(processes,'existing',lambda *_:None)
    monkeypatch.setattr(supervisor.time,'time',lambda:1000)
    monkeypatch.setattr(supervisor.subprocess,'Popen',spawn)
    def sleep(_):raise StopSupervisor()
    monkeypatch.setattr(supervisor.time,'sleep',sleep)
    with pytest.raises(StopSupervisor):supervisor.main(tmp_path)
    status=json.loads((state/'pids.json').read_text())
    assert set(status['roles'])=={'worker','publisher','feedback','collector','learning','local'}
    assert status['backoff']['server']=={'failures':1,'next_attempt':1003,'error_type':'PermissionError'}
