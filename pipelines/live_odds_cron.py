"""Local systemd timer client. No Odds API credentials or direct odds requests."""
import httpx
from corner.live_odds import config

def main() -> int:
    cfg = config()
    if not cfg:
        print('Premium live scheduling disabled.'); return 0
    try:
        with httpx.Client(trust_env=False,timeout=10,follow_redirects=False) as client:
            response = client.post('http://127.0.0.1:8765/api/v1/cron/refresh-live-odds',
                headers={'Authorization':'Bearer '+cfg['cron_token']},json={})
        if response.status_code != 202: raise ValueError()
        print('Premium live refresh queued; provider calls: 0.'); return 0
    except Exception:
        print('Premium live scheduler could not queue refresh.'); return 1

if __name__ == '__main__': raise SystemExit(main())
