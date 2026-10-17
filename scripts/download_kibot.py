"""Download Kibot's free IVE tick history (trade price, bid, ask, size), one file per month.

Kibot serves IVE ticks to the public "guest" account. The guest session expires after a
few requests, so we log in again before every monthly request. Files that already exist
are skipped, so the script can be re-run after an interruption.

Usage: python scripts/download_kibot.py [--first 2009-09] [--last 2026-09]
"""
import argparse
import gzip
import http.cookiejar
import time
import urllib.request
from pathlib import Path

import pandas as pd

API = "http://api.kibot.com/"
OUT = Path(__file__).resolve().parents[1] / "data" / "raw" / "kibot" / "IVE"


def open_session():
    """Return a URL opener that keeps Kibot's session cookie between the two calls."""
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def fetch_month(month: pd.Period) -> str:
    """Log in as guest and fetch every IVE tick of one calendar month as CSV text."""
    opener = open_session()
    opener.open(API + "?action=login&user=guest&password=guest", timeout=60).read()
    first = month.start_time.strftime("%m/%d/%Y")
    last = month.end_time.strftime("%m/%d/%Y")
    url = (API + "?action=history&symbol=IVE&interval=tickbidask"
           f"&startdate={first}&enddate={last}")
    text = opener.open(url, timeout=600).read().decode("utf-8")
    if text.startswith(("400", "401", "404", "500")):  # Kibot reports errors as plain text
        raise RuntimeError(f"Kibot refused {month}: {text[:120]!r}")
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--first", default="2009-09")
    parser.add_argument("--last", default="2026-09")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for month in pd.period_range(args.first, args.last, freq="M"):
        path = OUT / f"IVE_{month}.csv.gz"
        if path.exists():
            continue
        for attempt in range(3):
            try:
                text = fetch_month(month)
                break
            except Exception as err:  # network hiccups and expired sessions: retry
                print(f"{month}: attempt {attempt + 1} failed: {err}", flush=True)
                time.sleep(10)
        else:
            raise SystemExit(f"giving up on {month}")
        with gzip.open(path, "wt") as f:
            f.write(text)
        print(f"{month}: {text.count(chr(10))} ticks", flush=True)
        time.sleep(1)  # be polite to a free service


if __name__ == "__main__":
    main()
