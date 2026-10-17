"""Write small CSV samples of every data format to data/samples/ (these are committed).

The raw data are not committed (data/README.md). The samples show what the code reads
and produces: IVE ticks and one-minute bars on the flash-crash day, the first VPIN
buckets of that day, and BTCUSDT klines and trades.

Usage: python scripts/make_samples.py [--rows 200]
"""
import argparse
from pathlib import Path

import pandas as pd

from vpin.bars import time_bars
from vpin.data import load_btc_klines, load_btc_trades, load_ive_ticks

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "samples"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=200)
    rows = parser.parse_args().rows
    OUT.mkdir(parents=True, exist_ok=True)
    ticks = load_ive_ticks("2010-05-06", "2010-05-06")
    ticks.head(rows).to_csv(OUT / "IVE_20100506_ticks.csv", index=False)
    time_bars(ticks, 60).head(rows).to_csv(OUT / "IVE_20100506_bars_1min.csv", index=False)
    buckets = pd.read_csv(ROOT / "results" / "reproduction" / "vpin_50_50.csv.gz", parse_dates=["end_ts"])
    buckets[buckets["end_ts"].dt.normalize() == "2010-05-06"].to_csv(OUT / "IVE_20100506_buckets_50_50.csv", index=False)
    load_btc_klines("2025-10", "2025-10").head(rows).to_csv(OUT / "BTCUSDT_202510_klines_1min.csv", index=False)
    load_btc_trades("2025-10-10").head(rows).to_csv(OUT / "BTCUSDT_20251010_trades.csv", index=False)
    print(sorted(p.name for p in OUT.glob("*.csv")))


if __name__ == "__main__":
    main()
