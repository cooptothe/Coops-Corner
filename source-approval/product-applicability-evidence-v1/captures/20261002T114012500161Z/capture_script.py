"""One-shot research capture, NOT ingestion or a production evidence loader.

No database imports, retries, redirects, alternative books, or approval grants.
API credentials are loaded in memory and never included in retained metadata.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import urllib.parse

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
ENDPOINT = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds/"
PARAMS = dict(bookmakers="novig", markets="h2h", oddsFormat="decimal",
              dateFormat="iso", includeLinks="true", includeSids="true")
HEADERS = {"date", "age", "etag", "last-modified", "cache-control", "content-type",
           "content-encoding", "content-length", "x-requests-used",
           "x-requests-remaining", "x-requests-last", "x-request-id"}
LIMIT = 10 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_bytes(data, key):
    variants = (key, urllib.parse.quote(key, safe=""), urllib.parse.quote_plus(key),
                json.dumps(key)[1:-1])
    if any(value.encode() in data for value in variants):
        raise ValueError("credential_echo_refused")
    return data


def summarize(body, books=("novig",)):
    """Pointers to full payload; never invent missing source identifiers."""
    events = json.loads(body)
    if not isinstance(events, list):
        raise ValueError("unexpected_response_shape")
    matches = []
    for ei, event in enumerate(events):
        if not isinstance(event, dict) or event.get("sport_key") != "basketball_nba":
            continue
        for bi, book in enumerate(event.get("bookmakers", [])):
            if book.get("key") not in books:
                continue
            for mi, market in enumerate(book.get("markets", [])):
                outcomes = market.get("outcomes", [])
                if market.get("key") != "h2h":
                    continue
                matches.append({
                    "bookmaker_key": book["key"],
                    "json_pointer": f"/{ei}/bookmakers/{bi}/markets/{mi}",
                    "event_id": event.get("id"), "commence_time": event.get("commence_time"),
                    "home_team": event.get("home_team"), "away_team": event.get("away_team"),
                    "outcome_count": len(outcomes),
                    "two_team_prices_present": len(outcomes) == 2 and
                        {o.get("name") for o in outcomes} ==
                        {event.get("home_team"), event.get("away_team")} and
                        all(isinstance(o.get("price"), (int, float)) and
                            not isinstance(o.get("price"), bool) and o["price"] > 1
                            for o in outcomes),
                    "full_bookmaker_object": book,
                })
    result = {"event_count": len(events), "novig_h2h_markets": matches,
            "complete_two_team_market_count": sum(m["two_team_prices_present"] for m in matches),
            "governing_contract_proven": False, "pregame_authority_proven": False,
            "season_type_proven": False, "production_admissible": False}
    if books != ("novig",):
        result["h2h_markets"] = result.pop("novig_h2h_markets")
        result["complete_markets_by_book"] = {
            book: sum(m["two_team_prices_present"] for m in matches if m["bookmaker_key"] == book)
            for book in books}
    return result


def capture(key, session, destination, books=("novig",)):
    if books not in (("novig",), ("draftkings", "pinnacle", "novig")):
        raise ValueError("unsupported_research_scope")
    params = {**PARAMS, "bookmakers": ",".join(books)}
    metadata = {"format": "corner.novig_quote_capture/1", "requested_at": now(),
                "endpoint": ENDPOINT, "public_parameters": params,
                "credential_retained": False, "redirects_allowed": False,
                "automatic_retries": 0, "production_admissible": False,
                "messages_sent": False, "status": "capture_failed"}
    if books != ("novig",):
        metadata["format"] = "corner.candidate_quote_capture/1"
    body = None
    summary = None
    try:
        with session.get(ENDPOINT, params={**params, "apiKey": key},
                         headers={"Accept": "application/json", "Accept-Encoding": "identity"},
                         timeout=(10, 30), allow_redirects=False, stream=True) as response:
            metadata.update(received_headers_at=now(), http_status=response.status_code)
            headers = {k.lower(): v for k, v in response.headers.items() if k.lower() in HEADERS}
            safe_bytes(json.dumps(headers).encode(), key)
            metadata["response_headers"] = headers
            # Preserve entity bytes exactly; do not normalize JSON or decompress silently.
            candidate = response.raw.read(LIMIT + 1, decode_content=False)
            metadata["received_body_at"] = now()
            if len(candidate) > LIMIT:
                raise ValueError("response_size_limit")
            body = safe_bytes(candidate, key)
            metadata.update(body_sha256=digest(body), body_bytes=len(body),
                            raw_body_representation="HTTP_entity_bytes_without_transfer_framing")
            if response.status_code != 200:
                metadata["status"] = "http_error_retained"
            elif headers.get("content-encoding", "identity").lower() != "identity":
                metadata["status"] = "encoded_body_retained_not_interpreted"
            else:
                summary = summarize(body, books)
                metadata["status"] = ("novig_quote_retained" if
                    summary["complete_two_team_market_count"] else "no_complete_novig_quote")
                if books != ("novig",):
                    metadata["status"] = ("candidate_quotes_retained" if
                        summary["complete_two_team_market_count"] else "no_complete_candidate_quotes")
    except Exception as error:
        # Exceptions from requests can include the full credential-bearing URL.
        metadata["error_type"] = type(error).__name__
        metadata["status"] = "capture_failed"
    metadata["finished_at"] = now()
    destination.mkdir(parents=True, exist_ok=False)
    if body is not None:
        (destination / "response.body").write_bytes(body)
    if summary is not None:
        encoded = json.dumps(summary, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
        safe_bytes(encoded, key)
        (destination / "mapping-summary.json").write_bytes(encoded)
        metadata["summary_sha256"] = digest(encoded)
    script = Path(__file__).read_bytes()
    (destination / "capture_script.py").write_bytes(script)
    metadata["capture_script_sha256"] = digest(script)
    encoded = json.dumps(metadata, indent=2).encode() + b"\n"
    safe_bytes(encoded, key)
    (destination / "manifest.json").write_bytes(encoded)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true", required=True)
    parser.add_argument("--scope", choices=("novig", "candidate-books"), default="novig")
    args = parser.parse_args()
    load_dotenv(ROOT.parent / ".env")
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print('{"status":"missing_ODDS_API_KEY","request_sent":false}')
        return 2
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    books = ("novig",) if args.scope == "novig" else ("draftkings", "pinnacle", "novig")
    dossier = "novig-real-quote-evidence" if args.scope == "novig" else "product-applicability-evidence-v1"
    destination = ROOT / dossier / "captures" / stamp
    with requests.Session() as session:
        result = capture(key, session, destination, books)
    print(json.dumps({"status": result["status"], "capture_directory": str(destination),
                      "http_status": result.get("http_status"),
                      "body_sha256": result.get("body_sha256")}, indent=2))
    return 0 if result["status"] in ("novig_quote_retained", "candidate_quotes_retained") else 1


if __name__ == "__main__":
    raise SystemExit(main())
