"""Actual OS containment: a timeout must end the child and its descendants."""
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from easel_health_control import process_tree


def alive(pid):
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)];kernel.GetExitCodeProcess.restype=wintypes.BOOL
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return False
        try:
            code=wintypes.DWORD();assert kernel.GetExitCodeProcess(handle,ctypes.byref(code));return code.value==259
        finally:kernel.CloseHandle(handle)
    try:
        state=Path('/proc')/str(pid)/'stat'
        if state.exists() and state.read_text().split()[2]=='Z':return False
        os.kill(pid,0);return True
    except ProcessLookupError:return False


@pytest.mark.parametrize('timeout',[True,False])
def test_owned_tree_is_gone_after_timeout_or_leader_completion(tmp_path,timeout):
    record=tmp_path/'descendant.pid'
    child="import time;time.sleep(60)"
    leader=("import os,subprocess,sys,time;from pathlib import Path;"
            "p=subprocess.Popen([sys.executable,'-c',"+repr(child)+"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
            "Path("+repr(str(record))+").write_text(str(os.getpid())+','+str(p.pid));"+
            ("time.sleep(60)" if timeout else "time.sleep(.2)"))
    command=[sys.executable,'-c',leader]
    if timeout:
        with pytest.raises(subprocess.TimeoutExpired):process_tree.run_contained(command,timeout=2,cwd=tmp_path)
    else:
        assert process_tree.run_contained(command,timeout=5,cwd=tmp_path).returncode==0
    leader_pid,child_pid=map(int,record.read_text().split(','))
    deadline=time.monotonic()+3
    while time.monotonic()<deadline and (alive(leader_pid) or alive(child_pid)):time.sleep(.02)
    assert not alive(leader_pid) and not alive(child_pid)


@pytest.mark.skipif(os.name!='nt',reason='Windows suspended Job Object admission')
def test_job_assignment_failure_never_executes_uncontained_code(tmp_path,monkeypatch):
    marker=tmp_path/'must-not-exist'
    monkeypatch.setattr(process_tree.WindowsJob,'assign',lambda *args:(_ for _ in ()).throw(OSError('TEMP assignment failure')))
    command=[sys.executable,'-c',"from pathlib import Path;Path("+repr(str(marker))+").write_text('bad')"]
    with pytest.raises(OSError,match='assignment'):
        process_tree.run_contained(command,timeout=2,cwd=tmp_path)
    assert not marker.exists()
