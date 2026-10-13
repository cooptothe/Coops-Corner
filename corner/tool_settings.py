"""Validation for saved tool settings and presets (pure; storage is in tracker_store).

Settings are whatever small JSON object a tool's filters serialise to. The server does not interpret them
(each page validates every value when it applies them); it only keeps them small, plain and per-account.
"""
import json
import re

TOOLS = ('positive_ev', 'arbitrage', 'middle', 'props', 'promo', 'games', 'tracker', 'sizing', 'account', 'parlay')
MAX_BYTES = 8192
MAX_DEPTH = 4
MAX_ITEMS = 300
MAX_NAME = 40
MAX_PRESETS = 25


class SettingsError(ValueError):
    def __init__(self, message, status=400, code='invalid'):
        super().__init__(message)
        self.status, self.code = status, code


def clean_tool(value):
    if value not in TOOLS:
        raise SettingsError('Unknown tool.', 404, 'unknown_tool')
    return value


def _check(value, depth):
    if depth > MAX_DEPTH:
        raise SettingsError('Settings are nested too deeply.')
    if value is None or isinstance(value, (bool, str)):
        if isinstance(value, str) and len(value) > 300:
            raise SettingsError('A setting value is too long.')
        return
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value != value:
            raise SettingsError('Settings must be plain values.')
        return
    if isinstance(value, list):
        if len(value) > MAX_ITEMS:
            raise SettingsError('A setting list is too long.')
        for item in value:
            _check(item, depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 60:
            raise SettingsError('Too many settings.')
        for key, item in value.items():
            if not isinstance(key, str) or not 0 < len(key) <= 40:
                raise SettingsError('Setting names must be short text.')
            _check(item, depth + 1)
        return
    raise SettingsError('Settings must be plain values.')


def clean_settings(value):
    """The same object, once it is known to be a small plain-JSON dictionary."""
    if not isinstance(value, dict):
        raise SettingsError('Settings must be an object.')
    _check(value, 1)
    if len(json.dumps(value, separators=(',', ':'))) > MAX_BYTES:
        raise SettingsError('Those settings are too large to save.', 413, 'too_large')
    return value


def clean_name(value):
    """(display name, case-insensitive key) for a preset."""
    name = re.sub(r'\s+', ' ', value).strip() if isinstance(value, str) else ''
    if not name or len(name) > MAX_NAME or re.search(r'[\x00-\x1f\x7f]', name):
        raise SettingsError(f'Give the preset a name of 1 to {MAX_NAME} characters.')
    return name, name.lower()
