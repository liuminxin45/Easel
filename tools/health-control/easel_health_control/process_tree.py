"""Run one owned subprocess tree with a hard lifetime boundary.

Windows children start suspended, enter a kill-on-close Job Object, then resume.
Failure to create or assign the job never permits application code to run.
No process is found or terminated by an unverified numeric PID.
"""
import os
import signal
import subprocess


class WindowsJob:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes=ctypes;self.handle=None
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.nt=ctypes.WinDLL('ntdll',use_last_error=True)
        class Basic(ctypes.Structure):
            _fields_=[('PerProcessUserTimeLimit',ctypes.c_longlong),('PerJobUserTimeLimit',ctypes.c_longlong),
                ('LimitFlags',wintypes.DWORD),('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),
                ('ActiveProcessLimit',wintypes.DWORD),('Affinity',ctypes.c_size_t),('PriorityClass',wintypes.DWORD),('SchedulingClass',wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_=[(name,ctypes.c_ulonglong) for name in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
        class Extended(ctypes.Structure):
            _fields_=[('BasicLimitInformation',Basic),('IoInfo',IO),('ProcessMemoryLimit',ctypes.c_size_t),
                ('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]
        self.kernel.CreateJobObjectW.argtypes=[wintypes.LPVOID,wintypes.LPCWSTR];self.kernel.CreateJobObjectW.restype=wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,wintypes.LPVOID,wintypes.DWORD];self.kernel.SetInformationJobObject.restype=wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE];self.kernel.AssignProcessToJobObject.restype=wintypes.BOOL
        self.kernel.CloseHandle.argtypes=[wintypes.HANDLE];self.kernel.CloseHandle.restype=wintypes.BOOL
        self.nt.NtResumeProcess.argtypes=[wintypes.HANDLE];self.nt.NtResumeProcess.restype=wintypes.LONG
        self.handle=self.kernel.CreateJobObjectW(None,None)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        limits=Extended();limits.BasicLimitInformation.LimitFlags=0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
            error=ctypes.WinError(ctypes.get_last_error());self.close();raise error

    def assign(self,process):
        # Popen owns this exact process handle, including while its initial
        # thread is suspended. Child execution cannot race job assignment.
        if not self.kernel.AssignProcessToJobObject(self.handle,int(process._handle)):
            raise self.ctypes.WinError(self.ctypes.get_last_error())

    def resume(self,process):
        if self.nt.NtResumeProcess(int(process._handle))<0:
            raise OSError('owned_journey_process_resume_failed')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle);self.handle=None


def run_contained(command,*,timeout,cwd=None,env=None):
    job=WindowsJob() if os.name=='nt' else None
    process=None;assigned=False
    try:
        options={'cwd':cwd,'env':env,'stdin':subprocess.DEVNULL,'stdout':subprocess.PIPE,'stderr':subprocess.PIPE}
        if job is not None:
            options['creationflags']=getattr(subprocess,'CREATE_NO_WINDOW',0)|0x00000004  # CREATE_SUSPENDED
        else:
            options['start_new_session']=True
        process=subprocess.Popen(command,**options)
        if job is not None:
            try:
                job.assign(process);assigned=True;job.resume(process)
            except BaseException:
                # Only our still-suspended Popen handle is terminated if job
                # binding failed. Never resume an uncontained child.
                if not assigned:process.kill()
                job.close();process.wait(timeout=5);raise
        try:
            stdout,stderr=process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            if job is not None:job.close()
            else:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            stdout,stderr=process.communicate(timeout=5)
            raise subprocess.TimeoutExpired(command,timeout,output=stdout,stderr=stderr) from error
        return subprocess.CompletedProcess(command,process.returncode,stdout,stderr)
    finally:
        if job is not None:job.close()
        elif process is not None:
            # This session group was created by this Popen; it includes only
            # the harness's own driver/browser descendants.
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
