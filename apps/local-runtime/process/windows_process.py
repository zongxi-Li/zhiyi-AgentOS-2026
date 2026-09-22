"""Create a child with a Restricted Token without invoking elevation."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import msvcrt
import os
from pathlib import Path
import shutil
import subprocess

from security.windows_acl import SecurityBoundaryError, WindowsWorkspaceSecurityLease


if os.name == "nt":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _CREATE_UNICODE_ENVIRONMENT = 0x00000400
    _CREATE_NEW_PROCESS_GROUP = 0x00000200
    _CREATE_SUSPENDED = 0x00000004
    _EXTENDED_STARTUPINFO_PRESENT = 0x00080000
    _STARTF_USESTDHANDLES = 0x00000100
    _SW_HIDE = 0
    _HANDLE_FLAG_INHERIT = 0x00000001
    _WAIT_OBJECT_0 = 0x00000000
    _WAIT_TIMEOUT = 0x00000102
    _STILL_ACTIVE = 259
    _PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
    _PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
    _GENERIC_READ = 0x80000000
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_NORMAL = 0x00000080
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class _StartupInfo(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", wintypes.LPBYTE),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class _ProcessInformation(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    class _SidAndAttributes(ctypes.Structure):
        _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]

    class _SecurityCapabilities(ctypes.Structure):
        _fields_ = [
            ("AppContainerSid", wintypes.LPVOID),
            ("Capabilities", ctypes.POINTER(_SidAndAttributes)),
            ("CapabilityCount", wintypes.DWORD),
            ("Reserved", wintypes.DWORD),
        ]

    class _StartupInfoEx(ctypes.Structure):
        _fields_ = [
            ("StartupInfo", _StartupInfo),
            ("lpAttributeList", wintypes.LPVOID),
        ]

    _kernel32.CreatePipe.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _kernel32.CreatePipe.restype = wintypes.BOOL
    _kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    _kernel32.SetHandleInformation.restype = wintypes.BOOL
    _kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    _kernel32.ResumeThread.restype = wintypes.DWORD
    _kernel32.InitializeProcThreadAttributeList.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    _kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    _kernel32.UpdateProcThreadAttribute.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.c_size_t,
        wintypes.LPVOID,
        ctypes.c_size_t,
        wintypes.LPVOID,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    _kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    _kernel32.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
    _kernel32.DeleteProcThreadAttributeList.restype = None
    _kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateProcess.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(_StartupInfo),
        ctypes.POINTER(_ProcessInformation),
    ]
    _kernel32.CreateProcessW.restype = wintypes.BOOL
    _advapi32.CreateProcessAsUserW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(_StartupInfo),
        ctypes.POINTER(_ProcessInformation),
    ]
    _advapi32.CreateProcessAsUserW.restype = wintypes.BOOL


class WindowsRestrictedProcess:
    """Popen-compatible process wrapper for a Restricted Token child."""

    def __init__(self, *, handle, thread_handle, pid: int, stdout, stderr) -> None:
        self._handle = handle
        self._thread_handle = thread_handle
        self.pid = pid
        self.stdout = stdout
        self.stderr = stderr
        self.returncode: int | None = None

    def resume(self) -> None:
        if self._thread_handle:
            result = _kernel32.ResumeThread(self._thread_handle)
            if result == 0xFFFFFFFF:
                raise SecurityBoundaryError("could not resume restricted process")
            _kernel32.CloseHandle(self._thread_handle)
            self._thread_handle = None

    @property
    def handle(self):
        return self._handle

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        code = wintypes.DWORD()
        if not _kernel32.GetExitCodeProcess(self._handle, ctypes.byref(code)):
            raise SecurityBoundaryError("could not query restricted process")
        if code.value == _STILL_ACTIVE:
            return None
        self.returncode = int(code.value)
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        milliseconds = 0xFFFFFFFF if timeout is None else max(0, int(timeout * 1000))
        result = _kernel32.WaitForSingleObject(self._handle, milliseconds)
        if result == _WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired(self.pid, timeout)
        if result != _WAIT_OBJECT_0:
            raise SecurityBoundaryError("could not wait for restricted process")
        value = self.poll()
        if value is None:
            raise SecurityBoundaryError("restricted process did not report an exit code")
        return value

    def kill(self) -> None:
        if self.poll() is None and not _kernel32.TerminateProcess(self._handle, 1):
            error = ctypes.get_last_error()
            if error not in {5, 87}:
                raise SecurityBoundaryError(f"could not terminate restricted process ({error})")

    def close(self) -> None:
        if self._thread_handle:
            _kernel32.CloseHandle(self._thread_handle)
            self._thread_handle = None
        if self.stdout is not None:
            self.stdout.close()
            self.stdout = None
        if self.stderr is not None:
            self.stderr.close()
            self.stderr = None
        if self._handle:
            _kernel32.CloseHandle(self._handle)
            self._handle = None


def create_restricted_process(
    *,
    request,
    cwd: Path,
    environment: dict[str, str],
    security: WindowsWorkspaceSecurityLease,
    creation_flags: int,
) -> WindowsRestrictedProcess:
    if os.name != "nt":
        raise SecurityBoundaryError("restricted process launch requires Windows")
    read_out, write_out = _pipe()
    read_err, write_err = _pipe()
    stdin = _kernel32.CreateFileW(
        "NUL",
        _GENERIC_READ,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE,
        None,
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if stdin == _INVALID_HANDLE_VALUE:
        _close_many(read_out, write_out, read_err, write_err)
        raise SecurityBoundaryError("could not create restricted stdin")
    if not _kernel32.SetHandleInformation(stdin, _HANDLE_FLAG_INHERIT, _HANDLE_FLAG_INHERIT):
        _close_many(read_out, write_out, read_err, write_err, stdin)
        raise SecurityBoundaryError("could not prepare restricted stdin")
    try:
        command_line = _command_line(request, environment)
        application_name = _application_name(request, environment)
        command_buffer = ctypes.create_unicode_buffer(command_line)
        environment_buffer = ctypes.create_unicode_buffer(_environment_block(environment))
        environment_pointer = ctypes.cast(environment_buffer, wintypes.LPVOID)
        startup = _StartupInfo()
        startup.cb = ctypes.sizeof(startup)
        startup.dwFlags = _STARTF_USESTDHANDLES
        startup.wShowWindow = _SW_HIDE
        startup.hStdInput = stdin
        startup.hStdOutput = write_out
        startup.hStdError = write_err
        information = _ProcessInformation()
        flags = int(creation_flags) | _CREATE_UNICODE_ENVIRONMENT | _CREATE_SUSPENDED
        startup_pointer = ctypes.byref(startup)
        attribute_buffer = None
        startup_ex = None
        inherited_handles = None
        if getattr(security, "appcontainer_sid", None) is not None:
            inherited_handles = (wintypes.HANDLE * 3)(stdin, write_out, write_err)
            attribute_buffer, startup_ex = _startup_handle_attributes(inherited_handles)
            startup_ex.StartupInfo = startup
            startup_ex.StartupInfo.cb = ctypes.sizeof(_StartupInfoEx)
            startup_ex.lpAttributeList = ctypes.cast(attribute_buffer, wintypes.LPVOID)
            startup_pointer = ctypes.cast(
                ctypes.byref(startup_ex), ctypes.POINTER(_StartupInfo)
            )
            flags |= _EXTENDED_STARTUPINFO_PRESENT
        if not _advapi32.CreateProcessAsUserW(
            security.token_handle,
            ctypes.c_wchar_p(application_name) if application_name else None,
            command_buffer,
            None,
            None,
            True,
            flags,
            environment_pointer,
            ctypes.c_wchar_p(os.fspath(cwd)),
            startup_pointer,
            ctypes.byref(information),
        ):
            error = ctypes.get_last_error()
            raise SecurityBoundaryError(f"could not create restricted process ({error})")
        if attribute_buffer is not None:
            _kernel32.DeleteProcThreadAttributeList(attribute_buffer)
        _kernel32.CloseHandle(write_out)
        _kernel32.CloseHandle(write_err)
        _kernel32.CloseHandle(stdin)
        out_file = _handle_to_file(read_out, os.O_RDONLY)
        read_out = None
        err_file = _handle_to_file(read_err, os.O_RDONLY)
        read_err = None
        return WindowsRestrictedProcess(
            handle=information.hProcess,
            thread_handle=information.hThread,
            pid=int(information.dwProcessId),
            stdout=out_file,
            stderr=err_file,
        )
    except Exception:
        attribute_buffer = locals().get("attribute_buffer")
        if attribute_buffer is not None:
            try:
                _kernel32.DeleteProcThreadAttributeList(attribute_buffer)
            except Exception:
                pass
        _close_many(read_out, write_out, read_err, write_err, stdin)
        if "information" in locals():
            _close_many(information.hProcess, information.hThread)
        raise


def _pipe():
    read_handle = wintypes.HANDLE()
    write_handle = wintypes.HANDLE()
    if not _kernel32.CreatePipe(
        ctypes.byref(read_handle), ctypes.byref(write_handle), None, 0
    ):
        raise SecurityBoundaryError("could not create restricted process pipe")
    if not _kernel32.SetHandleInformation(read_handle, _HANDLE_FLAG_INHERIT, 0):
        _close_many(read_handle, write_handle)
        raise SecurityBoundaryError("could not protect restricted process pipe")
    if not _kernel32.SetHandleInformation(write_handle, _HANDLE_FLAG_INHERIT, _HANDLE_FLAG_INHERIT):
        _close_many(read_handle, write_handle)
        raise SecurityBoundaryError("could not prepare restricted process pipe")
    return read_handle, write_handle


def _startup_attributes(security_capabilities):
    size = ctypes.c_size_t(0)
    _kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    if size.value <= 0:
        raise SecurityBoundaryError("could not size AppContainer process attributes")
    buffer = ctypes.create_string_buffer(size.value)
    if not _kernel32.InitializeProcThreadAttributeList(
        ctypes.cast(buffer, wintypes.LPVOID),
        1,
        0,
        ctypes.byref(size),
    ):
        raise SecurityBoundaryError("could not initialize AppContainer process attributes")
    if not _kernel32.UpdateProcThreadAttribute(
        ctypes.cast(buffer, wintypes.LPVOID),
        0,
        _PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
        ctypes.byref(security_capabilities),
        ctypes.sizeof(security_capabilities),
        None,
        None,
    ):
        _kernel32.DeleteProcThreadAttributeList(ctypes.cast(buffer, wintypes.LPVOID))
        raise SecurityBoundaryError("could not set AppContainer process attributes")
    return buffer, _StartupInfoEx()


def _startup_handle_attributes(handles):
    size = ctypes.c_size_t(0)
    _kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    if size.value <= 0:
        raise SecurityBoundaryError("could not size child handle attributes")
    buffer = ctypes.create_string_buffer(size.value)
    if not _kernel32.InitializeProcThreadAttributeList(
        ctypes.cast(buffer, wintypes.LPVOID),
        1,
        0,
        ctypes.byref(size),
    ):
        raise SecurityBoundaryError("could not initialize child handle attributes")
    if not _kernel32.UpdateProcThreadAttribute(
        ctypes.cast(buffer, wintypes.LPVOID),
        0,
        _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
        ctypes.cast(handles, wintypes.LPVOID),
        ctypes.sizeof(handles),
        None,
        None,
    ):
        _kernel32.DeleteProcThreadAttributeList(ctypes.cast(buffer, wintypes.LPVOID))
        raise SecurityBoundaryError("could not set child handle attributes")
    return buffer, _StartupInfoEx()


def _handle_to_file(handle, flags: int):
    value = handle.value if hasattr(handle, "value") else handle
    descriptor = msvcrt.open_osfhandle(int(value), flags | getattr(os, "O_BINARY", 0))
    return os.fdopen(descriptor, "rb", buffering=0)


def _close_many(*handles) -> None:
    for handle in handles:
        if handle:
            try:
                _kernel32.CloseHandle(handle)
            except Exception:
                pass


def _environment_block(environment: dict[str, str]) -> str:
    entries = [f"{key}={value}" for key, value in sorted(environment.items())]
    return "\0".join(entries) + "\0\0" if entries else "\0\0"


def _command_line(request, environment: dict[str, str]) -> str:
    if request.mode.value == "shell":
        comspec = environment.get("ComSpec") or environment.get("COMSPEC") or os.environ.get("ComSpec")
        if not comspec:
            raise SecurityBoundaryError("shell interpreter is unavailable")
        command = request.command or ""
        return f'{subprocess.list2cmdline([comspec])} /d /s /c "{command}"'
    return subprocess.list2cmdline([request.program, *request.args])


def _application_name(request, environment: dict[str, str]) -> str | None:
    if request.mode.value == "shell":
        return environment.get("ComSpec") or environment.get("COMSPEC") or os.environ.get("ComSpec")
    program = request.program or ""
    if os.path.isabs(program):
        return program
    return shutil.which(program, path=environment.get("PATH"))


__all__ = ["WindowsRestrictedProcess", "create_restricted_process"]
