"""Ingest a captured Odds API payload into the canonical Corner schema."""

from __future__ import annotations

import argparse
from pathlib import Path

from corner.ingestion import (
    UnresolvedParticipantAlias,
    ingest_payload,
    replay_payload,
    resolve_player_alias,
)
from db.insert import connect


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, nargs="?", help="unchanged raw Odds API response body")
    parser.add_argument("--replay-payload", help="reprocess an existing canonical provider payload")
    parser.add_argument("--resolve-player-alias", metavar="RAW_NAME")
    parser.add_argument("--sport-key", default="americanfootball_nfl")
    args = parser.parse_args()

    action_count = sum(bool(value) for value in (args.fixture, args.replay_payload, args.resolve_player_alias))
    if action_count != 1:
        parser.error("provide exactly one fixture path, --replay-payload, or --resolve-player-alias")

    with connect() as conn:
        if args.resolve_player_alias:
            participant_id = resolve_player_alias(
                conn, sport_key=args.sport_key, raw_name=args.resolve_player_alias
            )
            print(f"Resolved player alias {args.resolve_player_alias!r} to Participant {participant_id}")
            return
        if args.replay_payload:
            processed_count = replay_payload(conn, args.replay_payload)
            print(f"Replayed canonical payload {args.replay_payload}: {processed_count} quote records processed")
            return

        raw_body = args.fixture.read_bytes()
        try:
            payload_id, observation_count = ingest_payload(
                conn,
                raw_body,
                endpoint_context={"source": "fixture", "fixture": args.fixture.name},
            )
        except UnresolvedParticipantAlias as error:
            print(
                f"Payload {error.payload_id} retained with unresolved player alias {error.raw_name!r}. "
                "Resolve it explicitly, then replay this payload."
            )
            return
    print(f"Canonical payload {payload_id}: {observation_count} normalized quote records processed")


if __name__ == "__main__":
    main()
