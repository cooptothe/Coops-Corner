"""Local systemd timer client. No Odds API credentials or direct odds requests."""
import httpx
from corner.live_odds import config

def main() -> int:
    cfg = config()
    if not cfg:
        print('Premium live scheduling disabled.'); return 0
    status = None
    try:
        with httpx.Client(trust_env=False,timeout=10,follow_redirects=False) as client:
            response = client.post('http://127.0.0.1:8765/api/v1/cron/refresh-live-odds',
                headers={'Authorization':'Bearer '+cfg['cron_token']},json={})
        status = response.status_code
        if status != 202: raise ValueError()
        print('Premium live refresh queued; provider calls: 0.'); return 0
    except Exception as error:
        # Local status/class only; never log authorization, config or bodies.
        print('Premium live scheduler could not queue refresh. '
              + 'error_type=' + type(error).__name__ + ' http_status=' + str(status)); return 1

if __name__ == '__main__': raise SystemExit(main())
