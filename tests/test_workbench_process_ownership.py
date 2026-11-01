"""TEMP identity inventories protect unrelated processes and pause ownership."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

from easel_workbench import processes


def row(pid,parent,created,*,name='python.exe',command='fixture'):
    return {'pid':pid,'parent':parent,'creation_ticks':str(created),'name':name,'command':command}


def test_older_children_of_reused_pid_are_excluded_with_their_branches():
    inventory={2816:row(2816,1,200),3000:row(3000,2816,210),
               19768:row(19768,2816,50,name='OneDrive.exe'),
               23920:row(23920,2816,70,name='OneDrive.Sync.Service.exe'),
               24000:row(24000,19768,80,name='Other.exe')}
    assert processes.descendant_pids(inventory,{2816})=={2816,3000}


def test_later_descendants_are_included_recursively_and_equal_tick_edges_are_valid():
    inventory={1:row(1,0,100),2:row(2,1,101),3:row(3,2,101),4:row(4,0,1)}
    assert processes.descendant_pids(inventory,{1})=={1,2,3}


@pytest.mark.parametrize('value',[None,'',True,-1,'bad','1.5',{},2**64])
def test_unknown_or_invalid_child_creation_cannot_authorize_a_stop(value):
    inventory={1:row(1,0,100),2:row(2,1,101)};inventory[2]['creation_ticks']=value
    with pytest.raises(ValueError,match='creation evidence'):processes.descendant_pids(inventory,{1})


def test_missing_root_or_bad_root_creation_fails_closed():
    with pytest.raises(ValueError,match='missing'):processes.descendant_pids({},[10])
    with pytest.raises(ValueError,match='creation evidence'):processes.descendant_pids({10:{'parent':0}},[10])


@pytest.fixture
def stop_fixture(tmp_path,monkeypatch):
    project=Path(__file__).resolve().parents[1];monkeypatch.syspath_prepend(str(project/'scripts'))
    spec=importlib.util.spec_from_file_location('owned_profile_stop',project/'scripts/activate_workbench.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    state=tmp_path/'.local/workbench-deployment';state.mkdir(parents=True);data=tmp_path/'data';data.mkdir()
    release='workbench-fixture';script=tmp_path/'workbench-releases'/release/'launch.py'
    manager=f'"pythonw.exe" "{tmp_path / "launcher.pyw"}"'
    worker=f'"pythonw.exe" "{script}" worker --root "{tmp_path}" --port 9123'
    inventory={1:row(1,0,100,name='pythonw.exe',command=manager),
               2:row(2,1,200,name='pythonw.exe',command=worker),
               3:row(3,2,210,command=worker)}
    (data/'active-workbench.json').write_text(json.dumps({'release':release}),encoding='utf-8')
    (state/'pids.json').write_text(json.dumps({'manager':1,'release':release,'roles':{'worker':2}}),encoding='utf-8')
    monkeypatch.setattr(module,'ROOT',tmp_path);monkeypatch.setattr(module,'STATE',state)
    terminated=[];held=[];fail=set();read_count=[0]
    class Handle:
        def __init__(self,r):self.pid=r['pid'];self.creation_ticks=int(r['creation_ticks']);self.closed=False;held.append(self)
        def terminate(self,*,expected_creation_ticks):
            assert expected_creation_ticks==self.creation_ticks
            terminated.append(self.pid)
            if self.pid in fail:raise TimeoutError('TEMP exit unconfirmed')
        def close(self):self.closed=True
        def __enter__(self):return self
        def __exit__(self,*_):self.close()
    def current_rows():
        read_count[0]+=1
        return copy.deepcopy(inventory) if read_count[0]==1 else {}
    monkeypatch.setattr(processes,'rows',current_rows);monkeypatch.setattr(module,'checked_identity',Handle)
    return module,state,inventory,terminated,held,fail


def test_stop_excludes_old_onedrive_orphans_and_stops_only_exact_owned_handles(stop_fixture):
    module,state,inventory,terminated,held,_=stop_fixture
    inventory[19768]=row(19768,2,50,name='OneDrive.exe',command='OneDrive.exe')
    inventory[23920]=row(23920,2,70,name='OneDrive.Sync.Service.exe',command='OneDrive.Sync.Service.exe')
    module.stop_new_profile()
    assert terminated==[1,2,3] and {h.pid for h in held}=={1,2,3}
    assert all(h.closed for h in held)
    marker=json.loads((state/'paused').read_text());assert marker['owner']=='runtime-stop' and len(marker['operation_id'])==32


def test_recent_unowned_child_refuses_before_any_stop_and_cleans_only_own_pause(stop_fixture):
    module,state,inventory,terminated,held,_=stop_fixture
    inventory[4]=row(4,2,250,name='OneDrive.exe',command='OneDrive.exe')
    with pytest.raises(ValueError,match='process kind'):module.stop_new_profile()
    assert terminated==[] and all(h.closed for h in held) and not (state/'paused').exists()


def test_invalid_creation_refuses_and_restores_old_live_pause_state(stop_fixture):
    module,state,inventory,terminated,_,_=stop_fixture;inventory[3].pop('creation_ticks')
    with pytest.raises(ValueError,match='creation evidence'):module.stop_new_profile()
    assert terminated==[] and not (state/'paused').exists()


def test_native_cli_is_not_authorized_by_a_project_path_substring(stop_fixture):
    module,state,inventory,terminated,_,_=stop_fixture
    inventory[4]=row(4,2,250,name='codex.exe',command=f'codex.exe app-server --cwd "{module.ROOT}"')
    with pytest.raises(ValueError,match='process kind'):module.stop_new_profile()
    assert terminated==[] and not (state/'paused').exists()


def test_foreign_python_is_not_authorized_by_a_project_path_substring(stop_fixture):
    module,state,inventory,terminated,_,_=stop_fixture
    inventory[3]['command']=f'python.exe -c "print(1)" --note "{module.ROOT}/workbench-releases/other/launch.py"'
    with pytest.raises(ValueError,match='Unowned'):module.stop_new_profile()
    assert terminated==[] and not (state/'paused').exists()


def test_existing_other_pause_is_neither_overwritten_nor_deleted(stop_fixture):
    module,state,_,terminated,held,_=stop_fixture;pause=state/'paused';original=b'operator maintenance'
    pause.write_bytes(original)
    with pytest.raises(ValueError,match='Another owner'):module.stop_new_profile()
    assert pause.read_bytes()==original and terminated==[] and held==[]


def test_missing_owned_snapshot_refuses_without_stopping_or_retaining_own_pause(stop_fixture):
    module,state,_,terminated,held,_=stop_fixture;(state/'pids.json').unlink()
    with pytest.raises(ValueError,match='No owned process snapshot'):module.stop_new_profile()
    assert terminated==[] and held==[] and not (state/'paused').exists()


def test_validation_failure_cannot_remove_a_replacement_pause_owner(stop_fixture,monkeypatch):
    module,state,inventory,terminated,_,_=stop_fixture;inventory[3]['command']='python.exe foreign.py'
    original=module.checked_identity;replacement={'owner':'operator','operation_id':'different-operation'}
    def checked(r):
        handle=original(r)
        if r['pid']==1:(state/'paused').write_text(json.dumps(replacement),encoding='utf-8')
        return handle
    monkeypatch.setattr(module,'checked_identity',checked)
    with pytest.raises(ValueError,match='Unowned'):module.stop_new_profile()
    assert terminated==[] and json.loads((state/'paused').read_text())==replacement


def test_after_termination_is_attempted_an_unconfirmed_exit_keeps_the_fence(stop_fixture):
    module,state,_,terminated,held,fail=stop_fixture;fail.add(1)
    with pytest.raises(TimeoutError,match='unconfirmed'):module.stop_new_profile()
    assert terminated==[1] and all(h.closed for h in held)
    assert json.loads((state/'paused').read_text())['owner']=='runtime-stop'
