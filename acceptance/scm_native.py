"""Administrator-only primitives for fresh disposable acceptance identities.

No passwords in subprocess arguments, XML, environment, reports or exceptions.
Import performs no mutation. This module is not a runtime dependency.
"""
from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes as w
import re
import secrets


class NativeError(RuntimeError):
    def __init__(self, operation, code):
        self.operation, self.code = operation, int(code)
        super().__init__(operation + ' failed, code ' + str(self.code))


def check(ok, operation):
    if not ok: raise NativeError(operation, c.get_last_error())


def function(library, name, args, result=w.BOOL):
    fn = getattr(library, name); fn.argtypes = args; fn.restype = result
    return fn


def local_account_sid(kernel, advapi, name):
    """Resolve only the local SAM user, using its actual machine-qualified name.

    SCM/LogonUser accept a dot for the local machine; LookupAccountName does not
    give that shorthand the same meaning. Never fall back to an unqualified name.
    """
    computer = c.create_unicode_buffer(256)
    length = w.DWORD(len(computer))
    check(function(kernel, 'GetComputerNameW', [w.LPWSTR, c.POINTER(w.DWORD)])(
        computer, c.byref(length)), 'GetComputerName')
    qualified = computer.value + '\\' + name
    lookup = function(advapi, 'LookupAccountNameW', [w.LPCWSTR, w.LPCWSTR, w.LPVOID,
        c.POINTER(w.DWORD), w.LPWSTR, c.POINTER(w.DWORD), c.POINTER(w.DWORD)])
    size, domain_size, kind = w.DWORD(), w.DWORD(), w.DWORD()
    c.set_last_error(0)
    ok = lookup(None, qualified, None, c.byref(size), None, c.byref(domain_size), c.byref(kind))
    error = c.get_last_error()
    if ok or error != 122 or size.value == 0 or domain_size.value == 0:
        raise NativeError('LookupAccountNameSize', error)
    sid_buffer = c.create_string_buffer(size.value)
    domain = c.create_unicode_buffer(domain_size.value)
    check(lookup(None, qualified, sid_buffer, c.byref(size), domain,
                 c.byref(domain_size), c.byref(kind)), 'LookupAccountName')
    if kind.value != 1 or domain.value.casefold() != computer.value.casefold():
        raise NativeError('RefuseNonLocalUserSID', 1332)
    return sid_buffer


class UserInfo(c.Structure):
    _fields_ = [('name', w.LPWSTR), ('password', w.LPWSTR), ('age', w.DWORD),
                ('privilege', w.DWORD), ('home', w.LPWSTR), ('comment', w.LPWSTR),
                ('flags', w.DWORD), ('script', w.LPWSTR)]


class UnicodeString(c.Structure):
    _fields_ = [('length', w.USHORT), ('maximum', w.USHORT), ('buffer', w.LPWSTR)]


class ObjectAttributes(c.Structure):
    _fields_ = [('length', w.ULONG), ('root', w.HANDLE), ('name', w.LPVOID),
                ('attributes', w.ULONG), ('security', w.LPVOID), ('qos', w.LPVOID)]


class Profile(c.Structure):
    _fields_ = [('size', w.DWORD), ('flags', w.DWORD), ('username', w.LPWSTR),
                ('path', w.LPWSTR), ('default', w.LPWSTR), ('server', w.LPWSTR),
                ('policy', w.LPWSTR), ('handle', w.HANDLE)]


class Luid(c.Structure):
    _fields_ = [('low', w.DWORD), ('high', w.LONG)]


class Privilege(c.Structure):
    _fields_ = [('count', w.DWORD), ('luid', Luid), ('attributes', w.DWORD)]


class ServiceStatus(c.Structure):
    _fields_ = [(name, w.DWORD) for name in ('type', 'state', 'controls', 'win32_exit', 'service_exit',
                                            'checkpoint', 'wait_hint', 'pid', 'flags')]


class ServiceConfig(c.Structure):
    _fields_ = [('type', w.DWORD), ('start', w.DWORD), ('error', w.DWORD), ('binary', w.LPWSTR),
                ('group', w.LPWSTR), ('tag', w.DWORD), ('dependencies', w.LPWSTR),
                ('account', w.LPWSTR), ('display', w.LPWSTR)]


class Action(c.Structure):
    _fields_ = [('kind', w.DWORD), ('delay', w.DWORD)]


class FailureActions(c.Structure):
    _fields_ = [('reset', w.DWORD), ('reboot', w.LPWSTR), ('command', w.LPWSTR),
                ('count', w.DWORD), ('actions', c.POINTER(Action))]


class Account:
    def __init__(self, suffix):
        if not re.fullmatch('[0-9a-f]{12}', suffix): raise ValueError('disposable suffix required')
        self.name = 'cah' + suffix
        self.password = 'Aa1!' + secrets.token_urlsafe(32)
        self.created = self.loaded = self.credential_written = False
        self.token = w.HANDLE()
        self.sid = None
        self.advapi = c.WinDLL('advapi32', use_last_error=True)
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.net = c.WinDLL('netapi32', use_last_error=True)
        self.userenv = c.WinDLL('userenv', use_last_error=True)

    def create(self):
        info = UserInfo(self.name, self.password, 0, 1, None, 'Disposable Corner host acceptance', 0x10001, None)
        code = function(self.net, 'NetUserAdd', [w.LPCWSTR, w.DWORD, w.LPVOID, c.POINTER(w.DWORD)], w.DWORD)(None, 1, c.byref(info), None)
        if code: raise NativeError('NetUserAdd', code)
        self.created = True
        self.sid_buffer = local_account_sid(self.kernel, self.advapi, self.name)
        text = w.LPWSTR()
        check(function(self.advapi, 'ConvertSidToStringSidW', [w.LPVOID, c.POINTER(w.LPWSTR)])(
            self.sid_buffer, c.byref(text)), 'ConvertSid')
        try: self.sid = text.value
        finally: function(self.kernel, 'LocalFree', [w.LPVOID], w.LPVOID)(c.cast(text, w.LPVOID))
        self.service_right(True)
        return self

    def service_right(self, add):
        attrs = ObjectAttributes(); attrs.length = c.sizeof(attrs)
        policy = w.HANDLE()
        status = function(self.advapi, 'LsaOpenPolicy', [w.LPVOID, c.POINTER(ObjectAttributes), w.DWORD, c.POINTER(w.HANDLE)], w.LONG)(
            None, c.byref(attrs), 0x810, c.byref(policy))
        if status: raise NativeError('LsaOpenPolicy', status)
        try:
            right = 'SeServiceLogonRight'
            value = UnicodeString(len(right) * 2, (len(right) + 1) * 2, right)
            if add:
                status = function(self.advapi, 'LsaAddAccountRights', [w.HANDLE, w.LPVOID, c.POINTER(UnicodeString), w.ULONG], w.LONG)(
                    policy, self.sid_buffer, c.byref(value), 1)
            else:
                status = function(self.advapi, 'LsaRemoveAccountRights', [w.HANDLE, w.LPVOID, w.BOOL, c.POINTER(UnicodeString), w.ULONG], w.LONG)(
                    policy, self.sid_buffer, True, None, 0)
            if status: raise NativeError('LsaAccountRights', status)
        finally: function(self.advapi, 'LsaClose', [w.HANDLE], w.LONG)(policy)

    def load_profile(self):
        if not self.token:
            check(function(self.advapi, 'LogonUserW', [w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, w.DWORD, w.DWORD, c.POINTER(w.HANDLE)])(
                self.name, '.', self.password, 5, 0, c.byref(self.token)), 'LogonUserService')
        # Enable privileges only on the short-lived administrator harness process.
        process = function(self.kernel, 'GetCurrentProcess', [], w.HANDLE)()
        admin_token = w.HANDLE()
        check(function(self.advapi, 'OpenProcessToken', [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)])(
            process, 0x28, c.byref(admin_token)), 'OpenAdministratorToken')
        try:
            for name in ('SeBackupPrivilege', 'SeRestorePrivilege', 'SeDebugPrivilege'):
                privilege = Privilege(); privilege.count = 1; privilege.attributes = 2
                check(function(self.advapi, 'LookupPrivilegeValueW', [w.LPCWSTR, w.LPCWSTR, c.POINTER(Luid)])(
                    None, name, c.byref(privilege.luid)), 'LookupPrivilege')
                c.set_last_error(0)
                check(function(self.advapi, 'AdjustTokenPrivileges', [w.HANDLE, w.BOOL, w.LPVOID, w.DWORD, w.LPVOID, w.LPVOID])(
                    admin_token, False, c.byref(privilege), 0, None, None), 'EnableProfilePrivilege')
                if c.get_last_error(): raise NativeError('EnableProfilePrivilege', c.get_last_error())
        finally: function(self.kernel, 'CloseHandle', [w.HANDLE])(admin_token)
        self.profile = Profile(); self.profile.size = c.sizeof(Profile); self.profile.flags = 1; self.profile.username = self.name
        check(function(self.userenv, 'LoadUserProfileW', [w.HANDLE, c.POINTER(Profile)])(
            self.token, c.byref(self.profile)), 'LoadUserProfile')
        self.loaded = True

    def unload_profile(self):
        if self.loaded:
            check(function(self.userenv, 'UnloadUserProfile', [w.HANDLE, w.HANDLE])(
                self.token, self.profile.handle), 'UnloadTestProfile')
            self.loaded = False

    @contextmanager
    def impersonate(self):
        check(function(self.advapi, 'ImpersonateLoggedOnUser', [w.HANDLE])(self.token), 'ImpersonateTestAccount')
        try: yield
        finally:
            if not function(self.advapi, 'RevertToSelf', [])():
                # Never continue administrative cleanup while still impersonating.
                raise NativeError('RevertToSelf', c.get_last_error())

    def credential(self, login=None, password=None):
        from corner.windows_credentials import Credential
        target = 'Corner/Postgres/Execution'
        # Python loads some codecs lazily. Prepare bytes/structures/functions
        # BEFORE impersonating: the new service account intentionally cannot read
        # the administrator's Python installation to import encodings.utf_16_le.
        if password is not None:
            raw = password.encode('utf-16-le')
            blob = (c.c_ubyte * len(raw)).from_buffer_copy(raw)
            entry = Credential(); entry.type = 1; entry.target = target; entry.username = login
            entry.persist = 2; entry.blob_size = len(raw); entry.blob = blob
            write = function(self.advapi, 'CredWriteW', [c.POINTER(Credential), w.DWORD])
            entry_pointer = c.byref(entry)
        else:
            delete = function(self.advapi, 'CredDeleteW', [w.LPCWSTR, w.DWORD, w.DWORD])
        with self.impersonate():
            if password is None:
                ok = delete(target, 1, 0)
                if not ok and c.get_last_error() != 1168: check(False, 'DeleteTestCredential')
                self.credential_written = False
            else:
                check(write(entry_pointer, 0), 'WriteTestCredential')
                self.credential_written = True

    def cleanup(self):
        if self.credential_written and not self.loaded:
            self.load_profile()
        if self.credential_written:
            self.credential()
        self.unload_profile()
        if self.token:
            function(self.kernel, 'CloseHandle', [w.HANDLE])(self.token); self.token = w.HANDLE()
        if self.created:
            if self.sid:
                self.service_right(False)
                ok = function(self.userenv, 'DeleteProfileW', [w.LPCWSTR, w.LPCWSTR, w.LPCWSTR])(self.sid, None, None)
                if not ok and c.get_last_error() not in (2, 3): check(False, 'DeleteTestProfile')
            code = function(self.net, 'NetUserDel', [w.LPCWSTR, w.LPCWSTR], w.DWORD)(None, self.name)
            if code: raise NativeError('NetUserDel', code)
            self.created = False


class Service:
    def __init__(self, name):
        if not re.fullmatch('CornerHost[0-9a-f]{12}', name): raise ValueError('disposable service required')
        self.name = name; self.handle = None
        self.event_source_created = False
        self.library = c.WinDLL('advapi32', use_last_error=True)
        self.manager = function(self.library, 'OpenSCManagerW', [w.LPCWSTR, w.LPCWSTR, w.DWORD], w.HANDLE)(None, None, 3)
        check(self.manager, 'OpenSCManager')

    def install(self, binary, account):
        self.handle = function(self.library, 'CreateServiceW', [w.HANDLE, w.LPCWSTR, w.LPCWSTR,
            w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.LPCWSTR, w.LPCWSTR, w.LPVOID, w.LPCWSTR, w.LPCWSTR, w.LPCWSTR], w.HANDLE)(
            self.manager, self.name, self.name, 0xF01FF, 0x10, 3, 1, '"' + str(binary) + '"',
            None, None, None, '.\\' + account.name, account.password)
        check(self.handle, 'CreateDisposableService')
        # Native SCM installation bypasses WinSW's installer. Pre-register this
        # fresh event source so a non-admin service needn't create HKLM keys.
        import winreg
        self.event_source = 'SYSTEM\\CurrentControlSet\\Services\\EventLog\\Application\\' + self.name
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.event_source):
                raise NativeError('RefuseExistingEventSource', 183)
        except FileNotFoundError:
            pass
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, self.event_source, 0, winreg.KEY_WRITE) as key:
            self.event_source_created = True
            winreg.SetValueEx(key, 'TypesSupported', 0, winreg.REG_DWORD, 7)
        actions = (Action * 3)(Action(1, 2000), Action(1, 5000), Action(0, 0))
        failure = FailureActions(3600, None, None, 3, actions)
        change = function(self.library, 'ChangeServiceConfig2W', [w.HANDLE, w.DWORD, w.LPVOID])
        check(change(self.handle, 2, c.byref(failure)), 'ConfigureRecovery')
        noncrash = w.BOOL(True)
        check(change(self.handle, 4, c.byref(noncrash)), 'ConfigureFailureFlag')

    def configuration(self):
        size = w.DWORD()
        query = function(self.library, 'QueryServiceConfigW', [w.HANDLE, w.LPVOID, w.DWORD, c.POINTER(w.DWORD)])
        query(self.handle, None, 0, c.byref(size))
        buffer = c.create_string_buffer(size.value)
        check(query(self.handle, buffer, size, c.byref(size)), 'QueryServiceConfiguration')
        cfg = c.cast(buffer, c.POINTER(ServiceConfig)).contents
        return {'account': cfg.account, 'binary': cfg.binary, 'start_type': cfg.start, 'service_type': cfg.type}

    def status(self):
        status, size = ServiceStatus(), w.DWORD()
        check(function(self.library, 'QueryServiceStatusEx', [w.HANDLE, w.DWORD, w.LPVOID, w.DWORD, c.POINTER(w.DWORD)])(
            self.handle, 0, c.byref(status), c.sizeof(status), c.byref(size)), 'QueryServiceStatus')
        return {name: getattr(status, name) for name, _ in status._fields_}

    def start(self):
        check(function(self.library, 'StartServiceW', [w.HANDLE, w.DWORD, w.LPVOID])(self.handle, 0, None), 'StartService')

    def stop(self):
        status = ServiceStatus()
        ok = function(self.library, 'ControlService', [w.HANDLE, w.DWORD, w.LPVOID])(self.handle, 1, c.byref(status))
        if not ok and c.get_last_error() != 1062: check(False, 'ControlServiceStop')

    def disable_recovery(self):
        action = (Action * 1)(Action(0, 0)); failure = FailureActions(0, None, None, 1, action)
        check(function(self.library, 'ChangeServiceConfig2W', [w.HANDLE, w.DWORD, w.LPVOID])(
            self.handle, 2, c.byref(failure)), 'DisableTestRecovery')

    def delete(self):
        if self.handle:
            if self.status()['state'] != 1: raise NativeError('RefuseDeleteRunningService', 0)
            check(function(self.library, 'DeleteService', [w.HANDLE])(self.handle), 'DeleteTestService')
            function(self.library, 'CloseServiceHandle', [w.HANDLE])(self.handle); self.handle = None
        if self.manager:
            function(self.library, 'CloseServiceHandle', [w.HANDLE])(self.manager); self.manager = None
        if self.event_source_created:
            import winreg
            winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, self.event_source)
            self.event_source_created = False


def directory(path, sid, writable=False):
    from corner.windows_control import api, SecurityAttributes
    kernel, advapi = api()
    descriptor = w.LPVOID()
    access = 'FA' if writable else 'GRGX'
    sddl = 'O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;' + access + ';;;' + sid + ')'
    check(advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, c.byref(descriptor), None), 'DirectoryACL')
    try:
        attrs = SecurityAttributes(c.sizeof(SecurityAttributes), descriptor, False)
        check(function(kernel, 'CreateDirectoryW', [w.LPCWSTR, c.POINTER(SecurityAttributes)])(str(path), c.byref(attrs)), 'CreatePrivateDirectory')
    finally: kernel.LocalFree(descriptor)
