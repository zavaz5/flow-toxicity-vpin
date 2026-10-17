"""Download Binance's public BTCUSDT futures data from data.binance.vision.

Two products:
- monthly 1-minute klines. Each bar carries `taker_buy_volume`, the volume of trades
  whose aggressor was a buyer: the true buy volume that bulk classification estimates;
- daily aggregated trades for a few days (configs/pipeline.yaml, btc.trade_days), each
  with the `is_buyer_maker` flag, to test trade-by-trade rules against the truth.

Zip files are kept as downloaded (pandas reads them directly). Existing files are skipped.

Usage: python scripts/download_binance.py
"""
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

import certifi
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://data.binance.vision/data/futures/um"
OUT = ROOT / "data" / "raw" / "binance"
# python.org builds on macOS ship without CA certificates; use certifi's bundle.
SSL = ssl.create_default_context(cafile=certifi.where())


def download(url: str, path: Path) -> bool:
    """Save `url` to `path`; return False if the file does not exist on the server."""
    if path.exists():
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(5):  # the CDN sometimes stalls a connection; retry quickly
        try:
            with urllib.request.urlopen(url, timeout=60, context=SSL) as response:
                data = response.read()
            break
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return False
            raise
        except (TimeoutError, urllib.error.URLError) as err:
            print(f"  retry {attempt + 1} for {path.name}: {err}", flush=True)
            time.sleep(5)
    else:
        raise RuntimeError(f"could not download {url}")
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.rename(path)  # never leave a half-written zip under the final name
    return True


def main():
    cfg = yaml.safe_load(open(ROOT / "configs" / "pipeline.yaml"))["btc"]
    sym = cfg["symbol"]
    for month in pd.period_range(cfg["first_month"], cfg["last_month"], freq="M"):
        name = f"{sym}-1m-{month}.zip"
        ok = download(f"{BASE}/monthly/klines/{sym}/1m/{name}", OUT / "klines" / name)
        print(f"klines {month}: {'ok' if ok else 'missing'}", flush=True)
        time.sleep(0.2)
    for day in cfg["trade_days"]:
        name = f"{sym}-aggTrades-{day}.zip"
        ok = download(f"{BASE}/daily/aggTrades/{sym}/{name}", OUT / "aggTrades" / name)
        print(f"aggTrades {day}: {'ok' if ok else 'missing'}", flush=True)


if __name__ == "__main__":
    main()
