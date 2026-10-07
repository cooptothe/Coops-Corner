"""Opt-in, foreground, loopback-only launcher: python -m api --port 8000."""
import argparse


def main():
    parser = argparse.ArgumentParser(description='The Corner fixture-only API (no DB, no live mode).')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    import uvicorn
    uvicorn.run('api.app:app', host='127.0.0.1', port=args.port, access_log=False, timeout_graceful_shutdown=5)


if __name__ == '__main__':
    main()
