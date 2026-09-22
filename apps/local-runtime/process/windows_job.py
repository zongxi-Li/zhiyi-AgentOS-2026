"""Process-tree containment primitives.

Windows uses a Job Object with kill-on-close. Non-Windows test environments
use a process group fallback; that fallback is not presented as Windows
containment.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
from ctypes import wintypes
from threading import Lock


if os.name == "nt":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", wintypes.ULARGE_INTEGER),
            ("WriteOperationCount", wintypes.ULARGE_INTEGER),
            ("OtherOperationCount", wintypes.ULARGE_INTEGER),
            ("ReadTransferCount", wintypes.ULARGE_INTEGER),
            ("WriteTransferCount", wintypes.ULARGE_INTEGER),
            ("OtherTransferCount", wintypes.ULARGE_INTEGER),
        ]

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _CREATE_SUSPENDED = 0x00000004
    _THREAD_SUSPEND_RESUME = 0x0002
    _TH32CS_SNAPTHREAD = 0x00000004

    class _ThreadEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.INT,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32)]
    _kernel32.Thread32First.restype = wintypes.BOOL
    _kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32)]
    _kernel32.Thread32Next.restype = wintypes.BOOL
    _kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenThread.restype = wintypes.HANDLE
    _kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    _kernel32.ResumeThread.restype = wintypes.DWORD


class ProcessContainmentError(RuntimeError):
    """The process could not be placed under the runtime lifecycle boundary."""


class WindowsJobObject:
    """Own the process-tree lifecycle for one Local Runtime execution."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._closed = False
        self._process_group_id: int | None = None
        self._handle = None
        if os.name == "nt":
            handle = _kernel32.CreateJobObjectW(None, None)
            if not handle:
                raise ProcessContainmentError("could not create process job")
            limits = _ExtendedLimitInformation()
            limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not _kernel32.SetInformationJobObject(
                handle,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                _kernel32.CloseHandle(handle)
                raise ProcessContainmentError("could not configure process job")
            self._handle = handle

    def creation_flags(self) -> int:
        if os.name == "nt":
            return int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) | _CREATE_SUSPENDED
        return 0

    def start_new_session(self) -> bool:
        return os.name != "nt"

    def attach(self, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            if self._closed:
                raise ProcessContainmentError("process job is already closed")
            if os.name == "nt":
                process_handle = getattr(process, "_handle", None)
                if process_handle is None:
                    process_handle = getattr(process, "handle", None)
                if process_handle is None:
                    raise ProcessContainmentError("process does not expose a native handle")
                if not _kernel32.AssignProcessToJobObject(self._handle, process_handle):
                    error = ctypes.get_last_error()
                    raise ProcessContainmentError(f"could not attach process to job ({error})")
            else:
                self._process_group_id = process.pid

    def resume(self, process: subprocess.Popen[bytes]) -> None:
        """Resume only after the process is owned by the Job Object."""
        if os.name != "nt":
            return
        native_resume = getattr(process, "resume", None)
        if native_resume is not None:
            native_resume()
            return
        snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
        if snapshot == wintypes.HANDLE(-1).value:
            raise ProcessContainmentError("could not enumerate process threads")
        entry = _ThreadEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        try:
            found = _kernel32.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.th32OwnerProcessID == process.pid:
                    thread = _kernel32.OpenThread(
                        _THREAD_SUSPEND_RESUME,
                        False,
                        entry.th32ThreadID,
                    )
                    if thread:
                        try:
                            if _kernel32.ResumeThread(thread) == 0xFFFFFFFF:
                                raise ProcessContainmentError("could not resume process")
                            return
                        finally:
                            _kernel32.CloseHandle(thread)
                found = _kernel32.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            _kernel32.CloseHandle(snapshot)
        raise ProcessContainmentError("could not find process primary thread")

    def terminate(self, process: subprocess.Popen[bytes] | None = None) -> None:
        with self._lock:
            if self._closed:
                return
            if os.name == "nt":
                if self._handle and not _kernel32.TerminateJobObject(self._handle, 1):
                    raise ProcessContainmentError("could not terminate process job")
            elif self._process_group_id is not None:
                try:
                    os.killpg(self._process_group_id, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process is not None:
                process.kill()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if os.name == "nt" and self._handle:
                _kernel32.CloseHandle(self._handle)
                self._handle = None


__all__ = ["ProcessContainmentError", "WindowsJobObject"]
