"""Local Windows stop signaling. No database imports, secrets, or persistent flags.

Events are kernel-lifetime objects. Never open/reset an existing event on startup:
an old helper retaining a handle must delay restart, not stop the new process.
"""
import ctypes as c
from ctypes import wintypes as w
import os
import re
import threading


class HostControlError(RuntimeError):
    pass


class SecurityAttributes(c.Structure):
    _fields_ = [('length', w.DWORD), ('descriptor', w.LPVOID), ('inherit', w.BOOL)]


def api():
    if os.name != 'nt': raise HostControlError('Windows required')
    kernel = c.WinDLL('kernel32', use_last_error=True)
    advapi = c.WinDLL('advapi32', use_last_error=True)
    signatures = (
        (kernel, 'GetCurrentProcess', [], w.HANDLE),
        (kernel, 'CloseHandle', [w.HANDLE], w.BOOL),
        (kernel, 'LocalFree', [w.LPVOID], w.LPVOID),
        (kernel, 'CreateEventW', [c.POINTER(SecurityAttributes), w.BOOL, w.BOOL, w.LPCWSTR], w.HANDLE),
        (kernel, 'OpenEventW', [w.DWORD, w.BOOL, w.LPCWSTR], w.HANDLE),
        (kernel, 'SetEvent', [w.HANDLE], w.BOOL),
        (kernel, 'WaitForSingleObject', [w.HANDLE, w.DWORD], w.DWORD),
        (advapi, 'OpenProcessToken', [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)], w.BOOL),
        (advapi, 'GetTokenInformation', [w.HANDLE, c.c_int, w.LPVOID, w.DWORD, c.POINTER(w.DWORD)], w.BOOL),
        (advapi, 'ConvertSidToStringSidW', [w.LPVOID, c.POINTER(w.LPWSTR)], w.BOOL),
        (advapi, 'ConvertStringSecurityDescriptorToSecurityDescriptorW',
         [w.LPCWSTR, w.DWORD, c.POINTER(w.LPVOID), c.POINTER(w.DWORD)], w.BOOL),
    )
    for library, name, args, result in signatures:
        fn = getattr(library, name); fn.argtypes = args; fn.restype = result
    return kernel, advapi


def current_sid():
    kernel, _ = api()
    return process_sid(kernel.GetCurrentProcess())


def process_sid(process):
    kernel, advapi = api()
    token = w.HANDLE()
    if not advapi.OpenProcessToken(process, 8, c.byref(token)):
        raise HostControlError('cannot inspect Windows identity')
    try:
        size = w.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, c.byref(size))  # TokenUser
        if not size.value: raise HostControlError('cannot inspect Windows identity')
        buffer = c.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, buffer, size, c.byref(size)):
            raise HostControlError('cannot inspect Windows identity')
        sid_pointer = c.cast(buffer, c.POINTER(w.LPVOID))[0]
        text = w.LPWSTR()
        if not advapi.ConvertSidToStringSidW(sid_pointer, c.byref(text)):
            raise HostControlError('cannot decode Windows identity')
        try: return text.value
        finally: kernel.LocalFree(c.cast(text, w.LPVOID))
    finally: kernel.CloseHandle(token)


def endpoint_name(service, sid, instance_key=None):
    if service not in ('discovery', 'execution', 'health') or not re.fullmatch(r'S-1-\d+(?:-\d+)+', sid):
        raise HostControlError('invalid fixed service identity')
    name = 'Global\\Corner.' + service + '.' + sid + '.Stop'
    if instance_key is not None:
        if not re.fullmatch(r'[1-9]\d*\.[1-9]\d*\.[0-9a-f]{32}', instance_key):
            raise HostControlError('invalid process instance key')
        name += '.' + instance_key
    if len(name) >= 260: raise HostControlError('invalid endpoint length')
    return name


def verify_identity(expected_sid):
    if current_sid() != expected_sid: raise HostControlError('unexpected Windows identity')


class StopEndpoint:
    def __init__(self, service, expected_sid, stop, *, instance_key=None):
        verify_identity(expected_sid)
        self.kernel, advapi = api()
        self.name = endpoint_name(service, expected_sid, instance_key)
        self.stop = stop
        self.done = threading.Event()
        self.failed = False
        descriptor = w.LPVOID()
        # Protected DACL: only LocalSystem and this account. No inherited ACEs.
        sddl = 'D:P(A;;GA;;;SY)(A;;GA;;;' + expected_sid + ')'
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, c.byref(descriptor), None):
            raise HostControlError('cannot create restricted stop ACL')
        try:
            attributes = SecurityAttributes(c.sizeof(SecurityAttributes), descriptor, False)
            c.set_last_error(0)
            self.handle = self.kernel.CreateEventW(c.byref(attributes), True, False, self.name)
            existed = c.get_last_error() == 183
        finally: self.kernel.LocalFree(descriptor)
        if not self.handle: raise HostControlError('cannot create stop endpoint')
        if existed:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            raise HostControlError('stop endpoint already exists; restart must wait for prior handles')
        self.thread = threading.Thread(target=self._listen, name='corner-local-stop', daemon=True)
        self.thread.start()

    def _listen(self):
        while not self.done.is_set():
            result = self.kernel.WaitForSingleObject(self.handle, 50)
            if result == 0:
                self.stop.request()
                return
            if result != 258:  # WAIT_TIMEOUT
                self.failed = True
                self.stop.request()  # fail closed; main returns failure after drain
                return

    def close(self):
        self.done.set()
        self.thread.join()  # waits at most the 50ms native event wait
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self): return self
    def __exit__(self, *_): self.close()


def signal_stop(service, expected_sid):
    """Open-only helper. Missing endpoint is an idempotent 'not running' result."""
    verify_identity(expected_sid)
    kernel, _ = api()
    handle = kernel.OpenEventW(2, False, endpoint_name(service, expected_sid))  # EVENT_MODIFY_STATE only
    if not handle:
        if c.get_last_error() == 2: return 'not_running'
        raise HostControlError('stop endpoint inaccessible')
    try:
        if not kernel.SetEvent(handle): raise HostControlError('cannot signal stop')
        return 'stop_requested'
    finally: kernel.CloseHandle(handle)
