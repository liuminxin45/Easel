"""Inspect and adopt only exact private-profile launch arguments on Windows."""
import ctypes
import json
from pathlib import Path
import subprocess
from .runtime.scripts.windows_process_identity import ProcessIdentity


def rows():
    script="[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process | ForEach-Object {[pscustomobject]@{pid=[int]$_.ProcessId;parent=[int]$_.ParentProcessId;name=$_.Name;command=$_.CommandLine;creation_ticks=[string]$_.CreationDate.ToFileTimeUtc()}}) -Compress"
    r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,encoding='utf-8',timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode:raise RuntimeError('Cannot inspect profile process ownership')
    return {v['pid']:v for v in json.loads(r.stdout.lstrip('\ufeff'))}


def argv(command):
    shell=ctypes.WinDLL('shell32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    shell.CommandLineToArgvW.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype=ctypes.POINTER(ctypes.c_wchar_p)
    count=ctypes.c_int();pointer=shell.CommandLineToArgvW(command,ctypes.byref(count))
    if not pointer:raise RuntimeError('Invalid process arguments')
    try:return [pointer[n] for n in range(count.value)]
    finally:kernel.LocalFree(ctypes.cast(pointer,ctypes.c_void_p))


class Adopted:
    def __init__(self,row):
        self.pid=row['pid'];self.identity=checked_identity(row)
    def poll(self):return 0 if self.identity.exited() else None
    def close(self):self.identity.close()


def checked_identity(row):
    # CIM exposes creation time at microsecond precision; retain native 100ns
    # ticks in the held handle for all subsequent exact identity checks.
    handle=ProcessIdentity(row['pid'])
    if handle.creation_ticks//10 != int(row['creation_ticks'])//10:
        handle.close();raise ValueError('Process identity changed')
    return handle


def existing(root,release,role):
    inventory=rows();members={}
    script=(Path(release)/'launch.py').resolve()
    for pid,row in inventory.items():
        if row['name'].lower() not in ('python.exe','pythonw.exe') or not row.get('command'):continue
        arguments=argv(row['command'])
        if len(arguments)<5:continue
        if Path(arguments[1]).resolve()!=script or arguments[2]!=role:continue
        if '--root' not in arguments:continue
        if Path(arguments[arguments.index('--root')+1]).resolve()!=Path(root).resolve():continue
        members[pid]=row
    tops=[row for pid,row in members.items() if row['parent'] not in members]
    if len(tops)>1:raise RuntimeError('Duplicate owned role already exists: '+role)
    return Adopted(tops[0]) if tops else None
