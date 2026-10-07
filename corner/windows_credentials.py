"""Read-only, exact-target user-vault access; never provisions credentials."""
import ctypes as c
from ctypes import wintypes as w
import os


class CredentialError(RuntimeError):
    pass


class Credential(c.Structure):
    _fields_ = [('flags', w.DWORD), ('type', w.DWORD), ('target', w.LPWSTR),
                ('comment', w.LPWSTR), ('last_written', w.FILETIME),
                ('blob_size', w.DWORD), ('blob', c.POINTER(c.c_ubyte)),
                ('persist', w.DWORD), ('attribute_count', w.DWORD),
                ('attributes', w.LPVOID), ('target_alias', w.LPWSTR), ('username', w.LPWSTR)]


def _read_entry(target):
    if os.name != 'nt': raise CredentialError('Windows vault required')
    library = c.WinDLL('advapi32', use_last_error=True)
    pointer = c.POINTER(Credential)()
    library.CredReadW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.POINTER(c.POINTER(Credential))]
    library.CredReadW.restype = w.BOOL
    library.CredFree.argtypes = [w.LPVOID]
    library.CredFree.restype = None
    if not library.CredReadW(target, 1, 0, c.byref(pointer)):
        raise CredentialError('required service credential unavailable')
    try:
        entry = pointer.contents
        if not entry.blob or not 0 < entry.blob_size <= 2560:
            raise CredentialError('invalid service credential')
        return (entry.type, entry.target, entry.username, entry.persist,
                c.string_at(entry.blob, entry.blob_size))
    finally:
        library.CredFree(pointer)


def password(service, target, login):
    if service not in ('discovery', 'execution', 'health') or target != 'Corner/Postgres/' + service.capitalize():
        raise CredentialError('wrong service credential target')
    kind, actual_target, username, persistence, blob = _read_entry(target)
    if (kind != 1 or actual_target != target or username != login or persistence != 2):
        raise CredentialError('service credential identity/persistence mismatch')
    # Explicit provisioning format: generic UTF-16LE password, no trailing NUL.
    try: value = blob.decode('utf-16-le', errors='strict')
    except UnicodeError: raise CredentialError('invalid service credential encoding') from None
    if not value or '\0' in value: raise CredentialError('invalid service credential')
    return value
