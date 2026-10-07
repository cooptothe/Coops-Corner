"""One-shot public-source retention; no policy approval, browser session or API keys.

Run --capture for a NEW capture directory; --verify checks existing captures offline.
Response bodies are unchanged entity bytes returned by urllib (not TLS/wire dumps).
Readable text/links are derivatives, never substitutes for retained body bytes.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
HEADERS = {'User-Agent': 'TheCorner-SourceReview/1.0', 'Accept': 'text/html, application/json', 'Accept-Encoding': 'identity'}
SAFE_HEADERS = ('Content-Type', 'Content-Encoding', 'Content-Length', 'Date', 'ETag',
                'Last-Modified', 'Cache-Control', 'Vary', 'Content-Language', 'Location')
MAX_BYTES = 10 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def digest(body):
    return hashlib.sha256(body).hexdigest()


def document(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        if tag == 'a':
            href = dict(attrs).get('href')
            if href:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(' '.join(data.split()))


def json_strings(value, path='$'):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from json_strings(child, path + '/' + key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from json_strings(child, path + '/' + str(index))


def capture(source, directory):
    identifier = source['id']
    if not re.fullmatch('[a-z0-9_]+', identifier):
        raise ValueError('unsafe source identifier')
    record = dict(source, requested_at=now(), request_headers=HEADERS,
                  credentials_sent=False, browser_location_context='none established',
                  tls_verification='default system trust; certificate verification enabled')
    try:
        try:
            response = urlopen(Request(source['url'], headers=HEADERS), timeout=25)
        except HTTPError as exc:
            response = exc  # Retain denial/error body, never claim it is the rules.
        with response:
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise ValueError('response exceeded capture limit; no truncated body accepted')
            record.update(received_at=now(), http_status=response.status, final_url=response.geturl(),
                          response_headers={k: response.headers[k] for k in SAFE_HEADERS if k in response.headers})
            charset = response.headers.get_content_charset() or 'utf-8'
        filename = identifier + '.body'
        with (directory / filename).open('xb') as handle:
            handle.write(body)
        record.update(body_file=filename, body_bytes=len(body), body_sha256=digest(body),
                      capture_status='retained_response_not_yet_content_validated')
        if record['response_headers'].get('Content-Encoding', 'identity').lower() in ('', 'identity'):
            parser = Text()
            decoded = body.decode(charset, errors='replace')
            if 'json' in record['response_headers'].get('Content-Type', ''):
                for path, value in json_strings(json.loads(decoded)):
                    parser.parts.append('JSON PATH ' + path)
                    parser.feed(value)
            else:
                parser.feed(decoded)
            text = ('DERIVED HTML TEXT - NOT ORIGINAL RESPONSE BYTES\n' + '\n'.join(parser.parts) + '\n').encode('utf-8')
            with (directory / (identifier + '.txt')).open('xb') as handle:
                handle.write(text)
            record.update(text_file=identifier + '.txt', text_sha256=digest(text),
                          text_encoding=charset, decode_errors='replace')
            document(directory / (identifier + '.links.json'), parser.links)
            record.update(links_file=identifier + '.links.json',
                          links_sha256=digest((directory / (identifier + '.links.json')).read_bytes()))
    except (URLError, TimeoutError, OSError, ValueError, LookupError) as exc:
        record.update(capture_status='capture_error', finished_at=now(), error=str(exc))
    print(identifier, record['capture_status'], record.get('http_status', ''), record.get('body_sha256', ''), flush=True)
    return record


def verify():
    manifests = sorted((ROOT / 'captures').glob('*/manifest.json'))
    if not manifests:
        raise ValueError('no capture manifests')
    for path in manifests:
        manifest = json.loads(path.read_text(encoding='utf-8'))
        for filename, key in [('plan.json', 'plan_sha256'), ('capture_script.py', 'capture_script_sha256')]:
            if (path.parent / filename).exists() and digest((path.parent / filename).read_bytes()) != manifest[key]:
                raise ValueError('capture implementation/plan digest mismatch')
        for record in manifest['sources']:
            for file_key, sha_key in [('body_file', 'body_sha256'), ('text_file', 'text_sha256'),
                                      ('links_file', 'links_sha256')]:
                if file_key in record:
                    file = path.parent / record[file_key]
                    if file.parent.resolve() != path.parent.resolve():
                        raise ValueError('capture path escape')
                    if digest(file.read_bytes()) != record[sha_key]:
                        raise ValueError('digest mismatch: ' + str(file))
        print('Verified', path.relative_to(ROOT), 'integrity only; NOT approval')


if __name__ == '__main__':
    args = argparse.ArgumentParser()
    mode = args.add_mutually_exclusive_group(required=True)
    mode.add_argument('--capture', action='store_true')
    mode.add_argument('--verify', action='store_true')
    args.add_argument('--plan', default='sources.json', choices=('sources.json', 'sources-rendered-assets.json'))
    options = args.parse_args()
    if options.verify:
        verify()
    else:
        started = now()
        directory = ROOT / 'captures' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        directory.mkdir(parents=True, exist_ok=False)
        plan_bytes = (ROOT / options.plan).read_bytes()
        for name, content in [('plan.json', plan_bytes), ('capture_script.py', Path(__file__).read_bytes())]:
            with (directory / name).open('xb') as handle:
                handle.write(content)
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda source: capture(source, directory), json.loads(plan_bytes)['sources']))
        document(directory / 'manifest.json', dict(format='corner.source_review.capture/1',
            started_at=started, finished_at=now(), plan_sha256=digest(plan_bytes),
            capture_script_sha256=digest(Path(__file__).read_bytes()), sources=results))
