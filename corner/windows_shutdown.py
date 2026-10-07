"""Database-independent, instance-verified graceful/forced process shutdown.

No PID-tree enumeration, vault, domain imports, installation or stale-file cleanup.
"""
from contextlib import ExitStack
import ctypes as c
from ctypes import wintypes as w
import json
import math
import os
from pathlib import Path
import re
import time
from uuid import uuid4

from corner import windows_control as ctl

Error = ctl.HostControlError
INVALID_HANDLE = c.c_void_p(-1).value
FORCED_EXIT_CODE = 137


def api():
    kernel, advapi = ctl.api()
    signatures = (
        (kernel, 'OpenProcess', [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
        (kernel, 'GetProcessTimes', [w.HANDLE] + [c.POINTER(w.FILETIME)] * 4, w.BOOL),
        (kernel, 'QueryFullProcessImageNameW', [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)], w.BOOL),
        (kernel, 'TerminateProcess', [w.HANDLE, w.UINT], w.BOOL),
        (kernel, 'CreateFileW', [w.LPCWSTR, w.DWORD, w.DWORD, c.POINTER(ctl.SecurityAttributes), w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
        (kernel, 'WriteFile', [w.HANDLE, w.LPCVOID, w.DWORD, c.POINTER(w.DWORD), w.LPVOID], w.BOOL),
        (kernel, 'ReadFile', [w.HANDLE, w.LPVOID, w.DWORD, c.POINTER(w.DWORD), w.LPVOID], w.BOOL),
        (kernel, 'SetFilePointerEx', [w.HANDLE, c.c_longlong, c.POINTER(c.c_longlong), w.DWORD], w.BOOL),
        (kernel, 'GetDriveTypeW', [w.LPCWSTR], w.UINT),
        (kernel, 'GetFileInformationByHandleEx', [w.HANDLE, c.c_int, w.LPVOID, w.DWORD], w.BOOL),
        (advapi, 'GetSecurityInfo', [w.HANDLE, c.c_int, w.DWORD, c.POINTER(w.LPVOID), w.LPVOID, w.LPVOID, w.LPVOID, c.POINTER(w.LPVOID)], w.DWORD),
        (advapi, 'ConvertSecurityDescriptorToStringSecurityDescriptorW', [w.LPVOID, w.DWORD, w.DWORD, c.POINTER(w.LPWSTR), w.LPVOID], w.BOOL),
    )
    for library, name, args, result in signatures:
        fn = getattr(library, name); fn.argtypes = args; fn.restype = result
    return kernel, advapi


def local_path(path):
    path = Path(path)
    kernel, _ = api()
    if not path.is_absolute() or str(path).startswith('\\\\') or ':' in str(path)[2:]:
        raise Error('absolute local runtime record required')
    if kernel.GetDriveTypeW(path.anchor) not in (3, 6):
        raise Error('fixed local runtime volume required')
    return str(path)


def creation_time(kernel, handle):
    times = [w.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle, *(c.byref(t) for t in times)):
        raise Error('cannot verify process creation time')
    return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)


def image_path(kernel, handle):
    size = w.DWORD(32768); buffer = c.create_unicode_buffer(size.value)
    if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, c.byref(size)):
        raise Error('cannot verify process executable')
    return buffer.value


def instance_key(record):
    return str(record['pid']) + '.' + record['creation_time'] + '.' + record['instance_token']


def validate_record(record, service, sid):
    if (not isinstance(record, dict) or set(record) != {'format', 'service', 'sid', 'pid', 'creation_time',
            'instance_token', 'stop_event', 'executable'} or record['format'] != 'corner.windows-instance/1'
            or record['service'] != service or record['sid'] != sid
            or type(record['pid']) is not int or not 0 < record['pid'] <= 0xffffffff
            or not isinstance(record['creation_time'], str) or not re.fullmatch(r'[1-9]\d{0,19}', record['creation_time'])
            or not isinstance(record['instance_token'], str) or not re.fullmatch('[0-9a-f]{32}', record['instance_token'])
            or not isinstance(record['executable'], str) or not record['executable']):
        raise Error('invalid runtime identity record')
    if record['stop_event'] != ctl.endpoint_name(service, sid, instance_key(record)):
        raise Error('runtime event/instance binding mismatch')
    return record


class RuntimeRecord:
    """CREATE_NEW, protected owner/DACL, no writable sharing, delete on last close.

    Parent directory must be deployment-controlled. Never overwrite stale records.
    """
    def __init__(self, path, record):
        self.kernel, advapi = api()
        descriptor = w.LPVOID()
        sid = record['sid']
        sddl = 'O:' + sid + 'D:P(A;;FA;;;SY)(A;;FA;;;' + sid + ')'
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, c.byref(descriptor), None):
            raise Error('cannot create identity ACL')
        try:
            attributes = ctl.SecurityAttributes(c.sizeof(ctl.SecurityAttributes), descriptor, False)
            self.handle = self.kernel.CreateFileW(local_path(path), 0xC0010000, 5, c.byref(attributes),
                1, 0x04000000 | 0x00200000, None)  # READ|WRITE|DELETE; SHARE_READ|DELETE; CREATE_NEW
        finally: self.kernel.LocalFree(descriptor)
        if self.handle == INVALID_HANDLE: raise Error('runtime record exists or cannot be created')
        try:
            data = json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
            if len(data) > 4096: raise Error('runtime identity too large')
            written = w.DWORD()
            if not self.kernel.WriteFile(self.handle, data, len(data), c.byref(written), None) or written.value != len(data):
                raise Error('cannot publish runtime identity')
        except BaseException:
            self.close(); raise

    def close(self):
        if self.handle not in (None, INVALID_HANDLE):
            self.kernel.CloseHandle(self.handle); self.handle = None

    def __enter__(self): return self
    def __exit__(self, *_): self.close()


class ServiceInstance:
    """Publish only after the exact event exists. Keep handles for process lifetime."""
    def __init__(self, service, sid, stop, path):
        self.resources = ExitStack()
        try:
            # Stable guard retains the prior singleton/stale-handle behavior.
            self.guard = self.resources.enter_context(ctl.StopEndpoint(service, sid, stop))
            kernel, _ = api(); process = kernel.GetCurrentProcess()
            self.record = {'format': 'corner.windows-instance/1', 'service': service, 'sid': sid,
                'pid': os.getpid(), 'creation_time': creation_time(kernel, process),
                'instance_token': uuid4().hex, 'executable': image_path(kernel, process)}
            self.endpoint = self.resources.enter_context(ctl.StopEndpoint(service, sid, stop,
                instance_key=instance_key(self.record)))
            self.record['stop_event'] = self.endpoint.name
            self.resources.enter_context(RuntimeRecord(path, self.record))
        except BaseException:
            self.resources.close(); raise

    @property
    def failed(self): return self.guard.failed or self.endpoint.failed
    def __enter__(self): return self
    def __exit__(self, *args): return self.resources.__exit__(*args)


def verify_record_acl(kernel, advapi, handle, sid):
    # Reject reparse points/directories even if a substituted path has a plausible ACL.
    info = (w.DWORD * 2)()
    if not kernel.GetFileInformationByHandleEx(handle, 9, info, c.sizeof(info)) or info[0] & (0x400 | 0x10):
        raise Error('invalid runtime record file type')
    descriptor, owner = w.LPVOID(), w.LPVOID()
    if advapi.GetSecurityInfo(handle, 1, 5, c.byref(owner), None, None, None, c.byref(descriptor)):
        raise Error('cannot verify runtime record ACL')
    text, owner_text = w.LPWSTR(), w.LPWSTR()
    try:
        if not advapi.ConvertSidToStringSidW(owner, c.byref(owner_text)) or owner_text.value != sid:
            raise Error('wrong runtime record owner')
        if not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 4, c.byref(text), None):
            raise Error('cannot decode runtime record ACL')
        if text.value != 'D:P(A;;FA;;;SY)(A;;FA;;;' + sid + ')':
            raise Error('unexpected runtime record ACL')
    finally:
        if text: kernel.LocalFree(c.cast(text, w.LPVOID))
        if owner_text: kernel.LocalFree(c.cast(owner_text, w.LPVOID))
        kernel.LocalFree(descriptor)


def read_record(kernel, handle, service, sid):
    if not kernel.SetFilePointerEx(handle, 0, None, 0): raise Error('cannot read runtime record')
    buffer = c.create_string_buffer(4097); count = w.DWORD()
    if not kernel.ReadFile(handle, buffer, len(buffer), c.byref(count), None) or not 0 < count.value <= 4096:
        raise Error('invalid runtime identity size')
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out: raise Error('duplicate runtime identity field')
            out[key] = value
        return out
    try: record = json.loads(buffer.raw[:count.value].decode('utf-8'), object_pairs_hook=unique)
    except (UnicodeError, ValueError): raise Error('invalid runtime identity encoding') from None
    return validate_record(record, service, sid)


def verify_process(kernel, handle, record):
    if creation_time(kernel, handle) != record['creation_time']:
        raise Error('process creation time mismatch')
    if os.path.normcase(image_path(kernel, handle)) != os.path.normcase(record['executable']):
        raise Error('process executable mismatch')
    if ctl.process_sid(handle) != record['sid']:
        raise Error('process account mismatch')


def wait_until(kernel, handle, deadline):
    while True:
        remaining = max(0, deadline - time.monotonic())
        result = kernel.WaitForSingleObject(handle, min(100, math.ceil(remaining * 1000)))
        if result == 0: return True
        if result != 258: raise Error('process wait failed')
        if time.monotonic() >= deadline: return False


def stop_instance(service, sid, path, *, graceful_drain_timeout, hard_stop_verification_timeout):
    for value in (graceful_drain_timeout, hard_stop_verification_timeout):
        if type(value) not in (float, int) or not math.isfinite(value) or not 0 < value <= 3600:
            raise Error('explicit finite shutdown timeouts required')
    ctl.verify_identity(sid)
    kernel, advapi = api()
    record_handle = kernel.CreateFileW(local_path(path), 0x80000000, 7, None, 3, 0x00200000, None)
    if record_handle == INVALID_HANDLE:
        # Missing/stale identity is not evidence that an arbitrary process is safe to kill.
        raise Error('runtime identity unavailable; termination refused')
    with ExitStack() as resources:
        resources.callback(kernel.CloseHandle, record_handle)
        verify_record_acl(kernel, advapi, record_handle, sid)
        record = read_record(kernel, record_handle, service, sid)
        if record['pid'] == os.getpid(): raise Error('self termination refused')
        process = kernel.OpenProcess(0x100000 | 0x1000 | 1, False, record['pid'])  # SYNCHRONIZE|QUERY_LIMITED|TERMINATE
        if not process: raise Error('recorded process unavailable; termination refused')
        resources.callback(kernel.CloseHandle, process)
        # Same HANDLE retained through verification, waiting and force; never reopen by PID.
        if creation_time(kernel, process) != record['creation_time']: raise Error('process creation time mismatch')
        if kernel.WaitForSingleObject(process, 0) == 0: return 'already_exited'
        try: verify_process(kernel, process, record)
        except Error:
            if kernel.WaitForSingleObject(process, 0) == 0: return 'already_exited'
            raise
        event = kernel.OpenEventW(2, False, record['stop_event'])
        if not event:
            if kernel.WaitForSingleObject(process, 0) == 0: return 'already_exited'
            raise Error('instance event unavailable; termination refused')
        resources.callback(kernel.CloseHandle, event)
        if not kernel.SetEvent(event): raise Error('cannot signal exact process instance')
        if wait_until(kernel, process, time.monotonic() + graceful_drain_timeout): return 'graceful_exit'
        # Re-read the held immutable file, not a potentially replaced path.
        if read_record(kernel, record_handle, service, sid) != record: raise Error('runtime identity changed')
        if kernel.WaitForSingleObject(process, 0) == 0: return 'graceful_exit'
        try: verify_process(kernel, process, record)
        except Error:
            if kernel.WaitForSingleObject(process, 0) == 0: return 'already_exited'
            raise
        verification_deadline = time.monotonic() + hard_stop_verification_timeout
        if not kernel.TerminateProcess(process, FORCED_EXIT_CODE):
            if wait_until(kernel, process, verification_deadline): return 'already_exited'
            raise Error('forced termination failed')
        if not wait_until(kernel, process, verification_deadline):
            raise Error('forced termination not confirmed before deadline')
        return 'forced_exit'
