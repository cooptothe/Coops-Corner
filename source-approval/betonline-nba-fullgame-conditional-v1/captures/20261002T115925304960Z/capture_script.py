"""One-shot public review-document retention, not a production evidence loader.

No credentials, betting endpoints, recurring execution, or approval grants.
Reuse the existing retention helper without changing the historical dossier.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
HELPER = ROOT / 'draftkings-la-nba-fullgame-2way-moneyline-v1' / 'capture_sources.py'
DOSSIERS = {
    'pinnacle-nba-fullgame-conditional-v1': {'www.pinnacle.com'},
    'novig-nba-fullgame-conditional-v1': {'support.novig.com'},
    'novig-nba-fullgame-conditional-v2': {'support.novig.com', 'the-odds-api.com'},
    'betonline-nba-fullgame-conditional-v1': {'help.betonline.ag', 'www.betonline.ag', 'the-odds-api.com'},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dossier', choices=sorted(DOSSIERS))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--capture', action='store_true')
    mode.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    directory_root = ROOT / args.dossier
    spec = importlib.util.spec_from_file_location('public_source_retention', HELPER)
    retain = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(retain)
    retain.ROOT = directory_root
    if args.verify:
        retain.verify()
        for path in (directory_root / 'captures').glob('*/manifest.json'):
            manifest = json.loads(path.read_text(encoding='utf-8'))
            if retain.digest((path.parent / 'retention_helper.py').read_bytes()) != manifest['retention_helper_sha256']:
                raise ValueError('retention helper digest mismatch')
        return
    plan = (directory_root / 'sources.json').read_bytes()
    sources = json.loads(plan)['sources']
    for source in sources:
        url = urlsplit(source['url'])
        if (url.scheme != 'https' or url.netloc not in DOSSIERS[args.dossier] or url.query
                or url.fragment or not (url.path.startswith(('/en/future/', '/en/articles/',
                                                            '/sports-odds-data/', '/liveapi/guides/'))
                or (url.netloc == 'www.betonline.ag' and url.path == '/rules'))):
            raise ValueError('only fixed public documentation hosts/paths permitted')
    started = retain.now()
    directory = directory_root / 'captures' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory.mkdir(parents=True, exist_ok=False)
    script, dependency = Path(__file__).read_bytes(), HELPER.read_bytes()
    for name, content in [('plan.json', plan), ('capture_script.py', script), ('retention_helper.py', dependency)]:
        with (directory / name).open('xb') as output:
            output.write(content)
    with ThreadPoolExecutor(max_workers=3) as pool:
        records = list(pool.map(lambda source: retain.capture(source, directory), sources))
    retain.document(directory / 'manifest.json', {
        'format': 'corner.source_review.capture/1', 'started_at': started, 'finished_at': retain.now(),
        'plan_sha256': retain.digest(plan), 'capture_script_sha256': retain.digest(script),
        'retention_helper_sha256': retain.digest(dependency),
        'evidence_class': 'public_documents_not_offering_or_applicability_proof', 'sources': records})
    if any(r.get('http_status') != 200 or r['capture_status'] == 'capture_error' for r in records):
        raise SystemExit('Incomplete capture retained; no approval implied')


if __name__ == '__main__':
    main()
