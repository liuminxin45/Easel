"""Identity-bound Windows process handles for controlled backend retirement.

No discovery or automatic termination. Callers must separately validate role,
command line, disabled configuration and deployment gates. PID alone is never
sufficient: keep this handle from inspection through the explicit stop action.
"""
import ctypes
from ctypes import wintypes

kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel.OpenProcess.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
kernel.CloseHandle.restype = wintypes.BOOL
kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
kernel.GetProcessTimes.restype = wintypes.BOOL
kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel.WaitForSingleObject.restype = wintypes.DWORD
kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel.TerminateProcess.restype = wintypes.BOOL


class ProcessIdentity:
    def __init__(self, pid, *, expected_creation_ticks=None):
        if type(pid) is not int or pid <= 0:
            raise ValueError('Invalid process ID')
        self.pid = pid
        self.handle = kernel.OpenProcess(0x1000 | 0x100000 | 0x0001, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(self.handle, *(ctypes.byref(t) for t in times)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.creation_ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            if expected_creation_ticks is not None and self.creation_ticks != expected_creation_ticks:
                raise ValueError('Process identity changed; no stop performed')
        except BaseException:
            self.close()
            raise

    def exited(self):
        if not self.handle:
            raise RuntimeError('Identity handle is closed')
        result = kernel.WaitForSingleObject(self.handle, 0)
        if result == 0:
            return True
        if result == 258:
            return False
        raise ctypes.WinError(ctypes.get_last_error())

    def terminate(self, *, expected_creation_ticks, timeout_ms=10000):
        if not self.handle or expected_creation_ticks != self.creation_ticks:
            raise ValueError('An inspected process identity is required')
        if type(timeout_ms) is not int or not 0 <= timeout_ms <= 60000:
            raise ValueError('Invalid process exit deadline')
        if self.exited():
            return
        if not kernel.TerminateProcess(self.handle, 1):
            error=ctypes.get_last_error()
            # Parent wrapper exit can finish a child between the liveness check
            # and termination. Accept it only after this same handle signals exit.
            if kernel.WaitForSingleObject(self.handle,timeout_ms)==0:return
            raise ctypes.WinError(error)
        result = kernel.WaitForSingleObject(self.handle, timeout_ms)
        if result == 258:
            raise TimeoutError('Process exit not yet confirmed; retain ownership and do not replace')
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            kernel.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
