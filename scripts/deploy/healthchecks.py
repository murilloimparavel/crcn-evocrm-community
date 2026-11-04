#!/usr/bin/env python3
"""Read-only HTTP smoke checks; exact HTTP 200, no redirects, bounded stability window."""
import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def check(url, opener=None):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use HTTPS URLs without embedded credentials')
    opener = opener or urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(url, timeout=10) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('urls', nargs='+')
    p.add_argument('--rounds', type=int, default=6)
    p.add_argument('--interval', type=float, default=10)
    a = p.parse_args()
    if not 1 <= a.rounds <= 60 or not 0 <= a.interval <= 60:
        p.error('rounds must be 1..60 and interval 0..60')
    for round_number in range(a.rounds):
        results = [check(url) for url in a.urls]
        print(json.dumps({'round': round_number + 1, 'passed': results}), flush=True)
        if not all(results):
            return 1
        if round_number + 1 < a.rounds:
            time.sleep(a.interval)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
