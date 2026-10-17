"""Load the raw downloads into tidy pandas frames.

IVE ticks (Kibot): one row per trade with the prevailing bid and ask, times in New York.
BTCUSDT (Binance): one-minute klines with the true taker-buy volume, and individual
aggregated trades with the aggressor side. Times are UTC.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

KIBOT_COLUMNS = ["date", "time", "price", "bid", "ask", "size"]
KLINE_COLUMNS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
                 "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume",
                 "ignore"]
AGGTRADE_COLUMNS = ["agg_trade_id", "price", "quantity", "first_trade_id",
                    "last_trade_id", "transact_time", "is_buyer_maker"]


def _cache_path(name: str, files: list[Path]) -> Path:
    """Parquet cache keyed by the raw files it was built from.

    If files are added (e.g. a download finished later), the key changes and the cache is
    rebuilt, so a cache never silently misses data. Stale caches are removed.
    """
    key = f"{len(files)}_{files[0].stem}_{files[-1].stem}".replace(".csv", "")
    path = PROCESSED / f"{name}_{key}.parquet"
    PROCESSED.mkdir(parents=True, exist_ok=True)
    for old in PROCESSED.glob(f"{name}_*.parquet"):
        if old != path:
            old.unlink()
    return path


def _read_kibot_month(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, header=None, names=KIBOT_COLUMNS)
    df["ts"] = pd.to_datetime(df["date"] + " " + df["time"], format="%m/%d/%Y %H:%M:%S")
    return df[["ts", "price", "bid", "ask", "size"]]


def load_ive_ticks(first_day: str, last_day: str, session=("09:30", "16:00")) -> pd.DataFrame:
    """IVE trades inside the regular session, sorted by time.

    Pre- and post-market prints are dropped: they are thin and often far from the quotes,
    and the paper's volume clock is about the main trading session (DEVIATIONS.md, row 2).
    The parsed result is cached as parquet because the monthly CSVs take a while to parse.
    """
    files = sorted((RAW / "kibot" / "IVE").glob("IVE_*.csv.gz"))
    if not files:
        raise FileNotFoundError("no IVE files; run scripts/download_kibot.py first")
    cache = _cache_path("ive_ticks", files)
    if not cache.exists():
        ticks = pd.concat([_read_kibot_month(f) for f in files], ignore_index=True)
        ticks = ticks.sort_values("ts", kind="stable").reset_index(drop=True)
        ticks.to_parquet(cache, index=False)
    ticks = pd.read_parquet(cache)
    day = ticks["ts"].dt.normalize()
    keep = (day >= pd.Timestamp(first_day)) & (day <= pd.Timestamp(last_day))
    seconds = (ticks["ts"] - day).dt.total_seconds()
    open_s, close_s = (pd.Timedelta(f"{t}:00").total_seconds() for t in session)
    keep &= (seconds >= open_s) & (seconds <= close_s)  # keeps the 16:00:00 closing print
    keep &= (ticks["size"] > 0) & (ticks["price"] > 0)
    return drop_cancelled_flash_crash_trades(ticks.loc[keep]).reset_index(drop=True)


def drop_cancelled_flash_crash_trades(ticks: pd.DataFrame) -> pd.DataFrame:
    """Remove the trades that US exchanges cancelled after the 6 May 2010 flash crash.

    The exchanges broke every trade executed between 14:40 and 15:00 at a price at least
    60% away from the last trade at or before 14:40. On IVE these are "stub quote" prints
    such as $0.08 against a price near $37. They never stood, and a few of them would
    dominate any statistic of price changes (Table 1). No other trades are touched.
    """
    start, end = pd.Timestamp("2010-05-06 14:40:00"), pd.Timestamp("2010-05-06 15:00:00")
    before = ticks.loc[ticks["ts"] <= start, "price"]
    if before.empty:
        return ticks
    reference = before.iloc[-1]
    window = (ticks["ts"] > start) & (ticks["ts"] <= end)
    broken = window & ((ticks["price"] / reference - 1).abs() >= 0.60)
    return ticks.loc[~broken]


def _has_header(path: Path) -> bool:
    """Binance added a header row to its files at some point; detect it from line 1."""
    import io
    import zipfile
    with zipfile.ZipFile(path) as z, z.open(z.namelist()[0]) as f:
        first = io.TextIOWrapper(f).readline()
    return not first[:1].isdigit()


def _read_kline_month(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, header=0 if _has_header(path) else None)
    df.columns = KLINE_COLUMNS
    df = df.astype({"open_time": "int64", "open": float, "close": float,
                    "volume": float, "taker_buy_volume": float, "count": "int64"})
    unit = "us" if df["open_time"].iloc[0] > 10**14 else "ms"  # 2025+ files use microseconds
    df["ts"] = pd.to_datetime(df["open_time"], unit=unit)
    return df[["ts", "open", "close", "volume", "taker_buy_volume", "count"]]


def load_btc_klines(first_month: str, last_month: str) -> pd.DataFrame:
    """One-minute BTCUSDT bars with true buy volume (`taker_buy_volume`), UTC times."""
    files = sorted((RAW / "binance" / "klines").glob("*.zip"))
    if not files:
        raise FileNotFoundError("no klines; run scripts/download_binance.py first")
    cache = _cache_path("btc_klines", files)
    if not cache.exists():
        bars = pd.concat([_read_kline_month(f) for f in files], ignore_index=True)
        bars = bars.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
        bars.to_parquet(cache, index=False)
    bars = pd.read_parquet(cache)
    first = pd.Period(first_month, "M").start_time
    last = pd.Period(last_month, "M").end_time
    bars = bars[(bars["ts"] >= first) & (bars["ts"] <= last) & (bars["volume"] > 0)]
    return bars.reset_index(drop=True)


def load_btc_trades(day: str) -> pd.DataFrame:
    """Aggregated BTCUSDT trades of one UTC day with the true aggressor side.

    `is_buyer_maker` is True when the passive (maker) side was the buyer, i.e. the
    aggressor sold. So the trade is an aggressive buy exactly when it is False.
    """
    path = RAW / "binance" / "aggTrades" / f"BTCUSDT-aggTrades-{day}.zip"
    df = pd.read_csv(path, header=0 if _has_header(path) else None)
    df.columns = AGGTRADE_COLUMNS
    df = df.astype({"price": float, "quantity": float, "transact_time": "int64"})
    maker = df["is_buyer_maker"].astype(str).str.lower() == "true"
    unit = "us" if df["transact_time"].iloc[0] > 10**14 else "ms"
    return pd.DataFrame({
        "ts": pd.to_datetime(df["transact_time"], unit=unit),
        "price": df["price"].to_numpy(),
        "size": df["quantity"].to_numpy(),
        "true_buy": ~maker.to_numpy(),
    })


def trading_days(ts: pd.Series) -> np.ndarray:
    """Calendar day of each timestamp, used to average volume per day."""
    return ts.dt.normalize().to_numpy()
