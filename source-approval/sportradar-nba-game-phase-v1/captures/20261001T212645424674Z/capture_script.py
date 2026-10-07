"""Retain public documentation only. No credentials, game capture or approval.

Reuse the existing source-retention helper without modifying its original dossier.
Each capture freezes both scripts and the plan. Verification is offline.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
HELPER = ROOT.parent / 'draftkings-la-nba-fullgame-2way-moneyline-v1' / 'capture_sources.py'


def helper():
    spec = importlib.util.spec_from_file_location('public_source_retention', HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = ROOT
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--capture', action='store_true')
    mode.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    retain = helper()
    if args.verify:
        retain.verify()
        for path in (ROOT / 'captures').glob('*/manifest.json'):
            manifest = json.loads(path.read_text(encoding='utf-8'))
            if retain.digest((path.parent / 'retention_helper.py').read_bytes()) != manifest['retention_helper_sha256']:
                raise ValueError('retention helper digest mismatch')
        return

    plan_bytes = (ROOT / 'sources.json').read_bytes()
    sources = json.loads(plan_bytes)['sources']
    for source in sources:
        url = urlsplit(source['url'])
        if (url.scheme != 'https' or url.netloc != 'developer.sportradar.com'
                or url.query or url.fragment or not url.path.startswith(('/basketball/', '/getting-started/'))):
            raise ValueError('only credential-free public documentation is permitted')
    started = retain.now()
    directory = ROOT / 'captures' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory.mkdir(parents=True, exist_ok=False)
    script = Path(__file__).read_bytes()
    dependency = HELPER.read_bytes()
    for name, content in [('plan.json', plan_bytes), ('capture_script.py', script),
                          ('retention_helper.py', dependency)]:
        with (directory / name).open('xb') as output:
            output.write(content)
    with ThreadPoolExecutor(max_workers=3) as pool:
        records = list(pool.map(lambda source: retain.capture(source, directory), sources))
    retain.document(directory / 'manifest.json', {
        'format': 'corner.source_review.capture/1', 'started_at': started,
        'finished_at': retain.now(), 'plan_sha256': retain.digest(plan_bytes),
        'capture_script_sha256': retain.digest(script),
        'retention_helper_sha256': retain.digest(dependency),
        'evidence_class': 'published_documentation_not_live_game_evidence',
        'sources': records})
    if any(r.get('http_status') != 200 or r['capture_status'] == 'capture_error' for r in records):
        raise SystemExit('Incomplete documentation capture retained; no approval implied')


if __name__ == '__main__':
    main()
