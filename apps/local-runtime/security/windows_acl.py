"""AppContainer token + additive ACL workspace boundary for Windows."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import shutil
from threading import RLock
from uuid import uuid4


class SecurityBoundaryError(RuntimeError):
    """A security boundary could not be created or restored safely."""


class SecurityBoundaryUnsupported(SecurityBoundaryError):
    """The requested OS boundary is not available on this platform."""


ISOLATED_NETWORK_GUARANTEE = "unavailable"


if os.name == "nt":
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernelbase = ctypes.WinDLL("kernelbase", use_last_error=True)
    _userenv = ctypes.WinDLL("userenv", use_last_error=True)

    _TOKEN_DUPLICATE = 0x0002
    _TOKEN_QUERY = 0x0008
    _TOKEN_ASSIGN_PRIMARY = 0x0001
    _TOKEN_ADJUST_DEFAULT = 0x0080
    _TOKEN_ADJUST_SESSIONID = 0x0100
    _TOKEN_ADJUST_PRIVILEGES = 0x0020
    _SE_PRIVILEGE_ENABLED = 0x00000002
    _DISABLE_MAX_PRIVILEGE = 0x0001
    _SECURITY_IMPERSONATION = 2
    _TOKEN_PRIMARY = 1
    _DACL_SECURITY_INFORMATION = 0x00000004
    _SE_FILE_OBJECT = 1
    _GRANT_ACCESS = 1
    _NO_MULTIPLE_TRUSTEE = 0
    _TRUSTEE_IS_SID = 0
    _TRUSTEE_IS_GROUP = 2
    _SUB_CONTAINERS_AND_OBJECTS_INHERIT = 0x00000003
    _FILE_GENERIC_READ = 0x120089
    _FILE_GENERIC_WRITE = 0x120116
    _FILE_GENERIC_EXECUTE = 0x1200A0
    _FILE_TRAVERSE = 0x00000020
    _HANDLE_FLAG_INHERIT = 0x00000001
    _STD_INPUT_HANDLE = -10
    _CREATE_NO_WINDOW = 0x08000000

    class _SidAndAttributes(ctypes.Structure):
        _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]

    class _Luid(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class _LuidAndAttributes(ctypes.Structure):
        _fields_ = [("Luid", _Luid), ("Attributes", wintypes.DWORD)]

    class _TokenPrivileges(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", _LuidAndAttributes)]

    class _SecurityCapabilities(ctypes.Structure):
        _fields_ = [
            ("AppContainerSid", wintypes.LPVOID),
            ("Capabilities", ctypes.POINTER(_SidAndAttributes)),
            ("CapabilityCount", wintypes.DWORD),
            ("Reserved", wintypes.DWORD),
        ]

    class _Trustee(ctypes.Structure):
        _fields_ = [
            ("pMultipleTrustee", wintypes.LPVOID),
            ("MultipleTrusteeOperation", wintypes.DWORD),
            ("TrusteeForm", wintypes.DWORD),
            ("TrusteeType", wintypes.DWORD),
            ("ptstrName", wintypes.LPWSTR),
        ]

    class _ExplicitAccess(ctypes.Structure):
        _fields_ = [
            ("grfAccessPermissions", wintypes.DWORD),
            ("grfAccessMode", wintypes.DWORD),
            ("grfInheritance", wintypes.DWORD),
            ("Trustee", _Trustee),
        ]

    _advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    _advapi32.OpenProcessToken.restype = wintypes.BOOL
    _advapi32.CreateRestrictedToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_SidAndAttributes),
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_SidAndAttributes),
        ctypes.POINTER(wintypes.HANDLE),
    ]
    _advapi32.CreateRestrictedToken.restype = wintypes.BOOL
    _advapi32.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(_Luid)]
    _advapi32.LookupPrivilegeValueW.restype = wintypes.BOOL
    _advapi32.AdjustTokenPrivileges.argtypes = [
        wintypes.HANDLE,
        wintypes.BOOL,
        ctypes.POINTER(_TokenPrivileges),
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    _advapi32.AdjustTokenPrivileges.restype = wintypes.BOOL
    _advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID)]
    _advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    _advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
    ]
    _advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    _advapi32.SetEntriesInAclW.argtypes = [
        wintypes.DWORD,
        ctypes.POINTER(_ExplicitAccess),
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPVOID),
    ]
    _advapi32.SetEntriesInAclW.restype = wintypes.DWORD
    _advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    _advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [wintypes.LPVOID]
    _kernel32.LocalFree.restype = wintypes.LPVOID
    _userenv.CreateAppContainerProfile.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
    ]
    _userenv.CreateAppContainerProfile.restype = wintypes.LONG
    _userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
    _userenv.DeleteAppContainerProfile.restype = wintypes.LONG
    _kernelbase.CreateAppContainerToken.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_SecurityCapabilities),
        ctypes.POINTER(wintypes.HANDLE),
    ]
    _kernelbase.CreateAppContainerToken.restype = wintypes.BOOL


def _raise_win32(prefix: str, code: int | None = None) -> None:
    error = int(code if code is not None else ctypes.get_last_error())
    raise SecurityBoundaryError(f"{prefix} ({error})")


class WindowsWorkspaceSecurityLease:
    """Temporarily grant an AppContainer SID access to one workspace tree.

    Only additive inherited access is written. Owner/group and existing ACEs
    are left untouched, and the original DACL is restored when the lease ends.
    """

    def __init__(self, workspace_root: Path, *, runtime_roots: tuple[Path, ...] = ()) -> None:
        if os.name != "nt":
            raise SecurityBoundaryUnsupported("isolated workspace requires Windows")
        self.workspace_root = Path(workspace_root).resolve(strict=True)
        if not self.workspace_root.is_dir():
            raise SecurityBoundaryError("workspace root is not a directory")
        self._lock = RLock()
        self._closed = False
        self._backups: list[tuple[Path, wintypes.LPVOID, wintypes.LPVOID]] = []
        self._temporary_roots: list[Path] = []
        self._temporary_parent: Path | None = None
        self._secured_paths: set[Path] = set()
        self._profile_name = f"ZhiyiLocalRuntime-{uuid4().hex}"
        self._sid = self._create_appcontainer_profile(self._profile_name)
        self._token = None
        try:
            self._token = self._create_appcontainer_token(self._sid)
            self._grant_access(
                self.workspace_root,
                _FILE_GENERIC_READ | _FILE_GENERIC_WRITE | _FILE_GENERIC_EXECUTE,
                _SUB_CONTAINERS_AND_OBJECTS_INHERIT,
            )
            for runtime_root in runtime_roots:
                self.allow_runtime_root(runtime_root)
        except Exception:
            self.close()
            raise

    @property
    def token_handle(self):
        return self._token

    @property
    def appcontainer_sid(self):
        return self._sid

    def create_execution_temp(self, execution_id: str) -> Path:
        with self._lock:
            if self._closed:
                raise SecurityBoundaryError("workspace security lease is closed")
            parent = self.workspace_root / ".zhiyi-runtime-temp"
            if not parent.exists():
                parent.mkdir(parents=True, exist_ok=False)
                self._temporary_parent = parent
            self._grant_access(
                parent,
                _FILE_GENERIC_READ | _FILE_GENERIC_WRITE | _FILE_GENERIC_EXECUTE,
                _SUB_CONTAINERS_AND_OBJECTS_INHERIT,
            )
            target = parent / execution_id
            target.mkdir(parents=True, exist_ok=False)
            self._temporary_roots.append(target)
            return target

    def allow_runtime_root(self, runtime_root: Path) -> None:
        """Allow read/execute access only to a tool dependency root.

        A restricted child still needs to load its interpreter and native
        libraries. These roots are runtime-selected, read-only exceptions;
        they are not workspace authority and never receive write access.
        """
        with self._lock:
            if self._closed:
                raise SecurityBoundaryError("workspace security lease is closed")
            candidate = Path(runtime_root).resolve(strict=True)
            if candidate in self._secured_paths:
                return
            self._grant_access(
                candidate,
                _FILE_GENERIC_READ | _FILE_GENERIC_EXECUTE,
                _SUB_CONTAINERS_AND_OBJECTS_INHERIT if candidate.is_dir() else 0,
            )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for target in reversed(self._temporary_roots):
                try:
                    if target.exists():
                        shutil.rmtree(target)
                except OSError:
                    pass
            restoration_error: SecurityBoundaryError | None = None
            for path, descriptor, old_dacl in reversed(self._backups):
                result = _advapi32.SetNamedSecurityInfoW(
                    ctypes.c_wchar_p(os.fspath(path)),
                    _SE_FILE_OBJECT,
                    _DACL_SECURITY_INFORMATION,
                    None,
                    None,
                    old_dacl,
                    None,
                )
                if result != 0 and restoration_error is None:
                    restoration_error = SecurityBoundaryError(
                        f"could not restore workspace ACL ({result})"
                    )
                _kernel32.LocalFree(descriptor)
            self._backups.clear()
            if self._temporary_parent is not None:
                try:
                    if self._temporary_parent.exists() and not any(self._temporary_parent.iterdir()):
                        self._temporary_parent.rmdir()
                except OSError:
                    pass
                self._temporary_parent = None
            if self._token:
                _kernel32.CloseHandle(self._token)
                self._token = None
            if self._sid:
                _kernel32.LocalFree(self._sid)
                self._sid = None
            if self._profile_name:
                result = _userenv.DeleteAppContainerProfile(self._profile_name)
                if result != 0:
                    raise SecurityBoundaryError(
                        f"could not delete AppContainer profile ({result})"
                    )
                self._profile_name = ""
            if restoration_error is not None:
                # Restoration failure is deliberately visible; callers must
                # not mistake incomplete lease cleanup for safety.
                raise restoration_error

    def _grant_inherited_access(self, path: Path) -> None:
        self._grant_access(
            path,
            _FILE_GENERIC_READ | _FILE_GENERIC_WRITE | _FILE_GENERIC_EXECUTE,
            _SUB_CONTAINERS_AND_OBJECTS_INHERIT,
        )

    def _grant_ancestor_traversal(self, target: Path) -> None:
        ancestors: list[Path] = []
        current = target.parent
        while current != current.parent:
            ancestors.append(current)
            current = current.parent
        for path in reversed(ancestors):
            if path in self._secured_paths:
                continue
            self._grant_access(path, _FILE_GENERIC_EXECUTE | _FILE_TRAVERSE, 0)

    def _grant_access(self, path: Path, permissions: int, inheritance: int) -> None:
        path = Path(path).resolve(strict=True)
        if path in self._secured_paths:
            return
        descriptor = wintypes.LPVOID()
        old_dacl = wintypes.LPVOID()
        result = _advapi32.GetNamedSecurityInfoW(
            ctypes.c_wchar_p(os.fspath(path)),
            _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION,
            None,
            None,
            ctypes.byref(old_dacl),
            None,
            ctypes.byref(descriptor),
        )
        if result != 0:
            _raise_win32("could not read workspace ACL", result)
        trustee = _Trustee(
            None,
            _NO_MULTIPLE_TRUSTEE,
            _TRUSTEE_IS_SID,
            _TRUSTEE_IS_GROUP,
            ctypes.cast(self._sid, wintypes.LPWSTR),
        )
        explicit = _ExplicitAccess(
            permissions,
            _GRANT_ACCESS,
            inheritance,
            trustee,
        )
        new_dacl = wintypes.LPVOID()
        result = _advapi32.SetEntriesInAclW(
            1,
            ctypes.byref(explicit),
            old_dacl,
            ctypes.byref(new_dacl),
        )
        if result != 0:
            _kernel32.LocalFree(descriptor)
            _raise_win32("could not compose workspace ACL", result)
        result = _advapi32.SetNamedSecurityInfoW(
            ctypes.c_wchar_p(os.fspath(path)),
            _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION,
            None,
            None,
            new_dacl,
            None,
        )
        _kernel32.LocalFree(new_dacl)
        if result != 0:
            _kernel32.LocalFree(descriptor)
            _raise_win32("could not apply workspace ACL", result)
        self._backups.append((path, descriptor, old_dacl))
        self._secured_paths.add(path)

    @staticmethod
    def _create_appcontainer_profile(name: str):
        sid = wintypes.LPVOID()
        result = _userenv.CreateAppContainerProfile(
            name,
            "Zhiyi Local Runtime",
            "Zhiyi isolated workspace execution",
            None,
            0,
            ctypes.byref(sid),
        )
        if result != 0:
            _raise_win32("could not create AppContainer profile", result)
        return sid

    @staticmethod
    def _create_appcontainer_token(sid):
        process_token = wintypes.HANDLE()
        access = (
            _TOKEN_DUPLICATE
            | _TOKEN_QUERY
            | _TOKEN_ASSIGN_PRIMARY
            | _TOKEN_ADJUST_DEFAULT
            | _TOKEN_ADJUST_SESSIONID
        )
        if not _advapi32.OpenProcessToken(
            _kernel32.GetCurrentProcess(), access, ctypes.byref(process_token)
        ):
            _raise_win32("could not open current process token")
        appcontainer = wintypes.HANDLE()
        capabilities = _SecurityCapabilities(sid, None, 0, 0)
        try:
            if not _kernelbase.CreateAppContainerToken(
                process_token,
                ctypes.byref(capabilities),
                ctypes.byref(appcontainer),
            ):
                _raise_win32("could not create AppContainer token")
            return appcontainer
        finally:
            _kernel32.CloseHandle(process_token)

    @staticmethod
    def _restricted_sid():
        sid = wintypes.LPVOID()
        if not _advapi32.ConvertStringSidToSidW("S-1-5-12", ctypes.byref(sid)):
            _raise_win32("could not create restricted-code SID")
        return sid

    @staticmethod
    def _create_restricted_token(sid):
        process_token = wintypes.HANDLE()
        access = (
            _TOKEN_DUPLICATE
            | _TOKEN_QUERY
            | _TOKEN_ASSIGN_PRIMARY
            | _TOKEN_ADJUST_DEFAULT
            | _TOKEN_ADJUST_SESSIONID
            | _TOKEN_ADJUST_PRIVILEGES
        )
        if not _advapi32.OpenProcessToken(
            _kernel32.GetCurrentProcess(), access, ctypes.byref(process_token)
        ):
            _raise_win32("could not open current process token")
        restricted = wintypes.HANDLE()
        restricting_sid = _SidAndAttributes(sid, 0)
        try:
            if not _advapi32.CreateRestrictedToken(
                process_token,
                _DISABLE_MAX_PRIVILEGE,
                0,
                None,
                0,
                None,
                1,
                ctypes.byref(restricting_sid),
                ctypes.byref(restricted),
            ):
                _raise_win32("could not create restricted process token")
            _enable_traverse_privilege(restricted)
            return restricted
        finally:
            _kernel32.CloseHandle(process_token)


def _enable_traverse_privilege(token) -> None:
    """Keep only directory traversal; all other token privileges stay disabled."""
    if os.name != "nt":
        return
    luid = _Luid()
    if not _advapi32.LookupPrivilegeValueW(None, "SeChangeNotifyPrivilege", ctypes.byref(luid)):
        _raise_win32("could not resolve traversal privilege")
    privileges = _TokenPrivileges(
        1,
        _LuidAndAttributes(luid, _SE_PRIVILEGE_ENABLED),
    )
    if not _advapi32.AdjustTokenPrivileges(
        token,
        False,
        ctypes.byref(privileges),
        0,
        None,
        None,
    ):
        _raise_win32("could not enable traversal privilege")
    if ctypes.get_last_error() == 1300:
        _raise_win32("restricted token does not contain traversal privilege", 1300)


__all__ = [
    "ISOLATED_NETWORK_GUARANTEE",
    "SecurityBoundaryError",
    "SecurityBoundaryUnsupported",
    "WindowsWorkspaceSecurityLease",
]
