"""Native process identities; unknown creation/access never authorizes takeover."""
import ctypes,os,pathlib
from pathlib import Path
from ctypes import wintypes

def process_identity(pid):
    """PID plus creation identity; reused/dead PIDs never prove a live worker."""
    if type(pid) is not int or pid <= 0:
        return None
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            code = wintypes.DWORD()
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
                return None
            times = [wintypes.FILETIME() for _ in range(4)]
            kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)):
                return None
            return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return pathlib.Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None



def process_creation(pid):
    if os.name=='nt':
        from easel_workbench.runtime.scripts.windows_process_identity import ProcessIdentity
        with ProcessIdentity(pid) as handle:return str(handle.creation_ticks)
    path=Path('/proc')/str(pid)/'stat'
    if path.exists():return path.read_text().rsplit(')',1)[1].split()[19]
    return None


def owner_is_gone(task):
    """PID reuse is safe; unknown/access-denied identity is never treated as gone."""
    pid=task.get('owner_pid');expected=task.get('owner_creation')
    if type(pid) is not int or pid<=0:return False
    if os.name=='nt':
        from easel_workbench.runtime.scripts.windows_process_identity import ProcessIdentity
        try:
            with ProcessIdentity(pid) as handle:
                if handle.exited():return True
                return expected is not None and str(handle.creation_ticks)!=str(expected)
        except OSError as error:return getattr(error,'winerror',None)==87
    try:
        os.kill(pid,0)
    except ProcessLookupError:return True
    except PermissionError:return False
    actual=process_creation(pid)
    return expected is not None and actual is not None and actual!=str(expected)
