"""Actual Windows reader interference plus deterministic persistent I/O faults."""
import ctypes
import errno
import json
import os
import threading
import time

import pytest

from easel_workbench.runtime import feedback_ledger as ledger


def test_transient_replacement_failure_preserves_original_until_atomic_success(tmp_path, monkeypatch):
    path=tmp_path/'status.json';path.write_text('{"old":true}',encoding='utf-8')
    real=ledger.os.replace;calls=[]
    def replace(source,target):
        calls.append(source)
        assert json.loads(path.read_text(encoding='utf-8'))=={'old':True}
        if len(calls)<3:raise PermissionError('simulated Windows sharing violation')
        real(source,target)
    monkeypatch.setattr(ledger.os,'replace',replace)
    ledger.atomic(path,{'new':True})
    assert len(calls)==3 and json.loads(path.read_text(encoding='utf-8'))=={'new':True}
    assert list(tmp_path.glob('*.tmp'))==[]


def test_persistent_denial_is_bounded_and_does_not_report_success(tmp_path,monkeypatch):
    path=tmp_path/'status.json';path.write_bytes(b'original')
    calls=[]
    def denied(*args):calls.append(1);raise PermissionError('permanent')
    monkeypatch.setattr(ledger.os,'replace',denied)
    started=time.perf_counter()
    with pytest.raises(PermissionError):ledger.atomic(path,{'new':True})
    assert len(calls)==6 and time.perf_counter()-started<2
    assert path.read_bytes()==b'original' and list(tmp_path.glob('*.tmp'))==[]


def test_disk_full_is_not_retried_or_silenced(tmp_path,monkeypatch):
    path=tmp_path/'status.json';path.write_bytes(b'original');calls=[]
    def full(*args):calls.append(1);raise OSError(errno.ENOSPC,'full')
    monkeypatch.setattr(ledger.os,'replace',full)
    with pytest.raises(OSError):ledger.atomic(path,{'new':True})
    assert len(calls)==1 and path.read_bytes()==b'original'


@pytest.mark.skipif(os.name!='nt',reason='Windows share-delete semantics')
def test_real_windows_reader_lock_releases_and_publication_recovers(tmp_path):
    path=tmp_path/'pids.json';path.write_text('{"old":true}',encoding='utf-8')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
    kernel.CreateFileW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    # Permit reads/writes but deliberately deny FILE_SHARE_DELETE.
    handle=kernel.CreateFileW(str(path),0x80000000,3,None,3,0,None)
    assert handle not in (None,ctypes.c_void_p(-1).value)
    released=threading.Event()
    def release():
        time.sleep(.1);kernel.CloseHandle(handle);released.set()
    thread=threading.Thread(target=release);thread.start()
    try:
        ledger.atomic(path,{'new':True})
        assert released.is_set() and json.loads(path.read_text(encoding='utf-8'))=={'new':True}
    finally:thread.join(2)
