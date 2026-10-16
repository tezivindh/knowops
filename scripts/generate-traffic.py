#!/usr/bin/env python3
"""Generate a small, read-only request sample for observability evidence."""
import argparse
import time
import urllib.error
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://localhost:3000/api/v1/auth/me")
parser.add_argument("--host", default="knowops.local")
parser.add_argument("--count", type=int, default=60)
args = parser.parse_args()
for _ in range(args.count):
    try:
        urllib.request.urlopen(urllib.request.Request(args.url, headers={"Host": args.host}), timeout=5).close()
    except urllib.error.HTTPError as error:
        if error.code != 401:
            raise
        error.close()
    time.sleep(1)
print(f"Generated {args.count} read-only requests (401 is expected without a session)")
