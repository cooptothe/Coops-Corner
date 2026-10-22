"""Bounded HTTPX transport used ONLY inside the existing serial quota worker."""
from __future__ import annotations
import json
import logging
import time
from typing import Any
import httpx

BASE = 'https://api.the-odds-api.com/v4/sports'
SAFE_HEADERS = ('x-requests-last','x-requests-used','x-requests-remaining','date')

def fetch(client: httpx.Client, path: str, params: dict[str, Any], key: str) -> tuple[int, Any, dict[str,str]]:
    """No automatic retry, redirect, proxy environment, URL or exception logging."""
    start = time.monotonic()
    try:
        with client.stream('GET', BASE+path, params={**params,'apiKey':key}) as response:
            headers = {name:response.headers[name] for name in SAFE_HEADERS if name in response.headers}
            raw = bytearray()
            for chunk in response.iter_bytes(65536):
                raw.extend(chunk)
                if len(raw)>10*1024*1024 or time.monotonic()-start>40: raise ValueError('Response bounds')
            if key.encode() in raw or key in json.dumps(headers): raise ValueError('Credential echo')
            return response.status_code, json.loads(raw) if response.status_code==200 else [], headers
    except (httpx.HTTPError, ValueError, TypeError):
        raise RuntimeError('Live odds transport failed; quota reservation must be reconciled') from None

def client() -> httpx.Client:
    # HTTPX INFO logs include URLs; never emit a provider URL carrying apiKey.
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    return httpx.Client(timeout=httpx.Timeout(20,connect=5),follow_redirects=False,trust_env=False)
