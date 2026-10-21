"""A real-time VPIN: every input uses only data available at that moment.

The paper's pipeline uses three full-sample quantities: sigma for bulk classification,
the bucket size V (from average daily volume) and the CDF used to read VPIN. Each one
looks into the future. Here sigma and V for day d come from the days before d (a
trailing window), and the CDF from VPIN values already observed.
"""
import numpy as np
import pandas as pd
from scipy.stats import norm

from .analysis import next_abs_return
from .bars import bar_log_changes
from .buckets import bucket_edges_daily, buckets_from_edges
from .metric import cdf_expanding, vpin


def daily_estimates(bars: pd.DataFrame, buckets_per_day: int, window: int = 250,
                    min_days: int = 60) -> pd.DataFrame:
    """Per day: sigma of one-minute log changes and bucket size, from earlier days only.

    sigma is the root mean square of within-day log changes (their mean is ~0), and the
    bucket size is the trailing average daily volume / buckets_per_day. `shift(1)` makes
    day d use days d-window .. d-1.
    """
    change = bar_log_changes(bars)
    daily = pd.DataFrame({"day": bars["day"], "sq": change ** 2, "bars": 1.0,
                          "volume": bars["volume"]}).groupby("day").sum()
    daily["days"] = 1.0
    past = daily.rolling(window, min_periods=min_days).sum().shift(1)
    return pd.DataFrame({
        "volume": daily["volume"],
        "sigma": np.sqrt(past["sq"] / past["bars"]),
        "bucket_volume": past["volume"] / past["days"] / buckets_per_day,
    })


def realtime_buckets(bars: pd.DataFrame, buckets_per_day: int, true_buy: np.ndarray | None = None,
                     window: int = 250, min_days: int = 60) -> pd.DataFrame:
    """Buckets from trailing estimates, with BVC buy volume and optionally the true one.

    Both classifications are poured into the same buckets, so their VPINs can be compared
    bucket by bucket.
    """
    est = daily_estimates(bars, buckets_per_day, window, min_days)
    sigma = est["sigma"].reindex(bars["day"]).to_numpy()
    fraction = norm.cdf(bar_log_changes(bars) / sigma)
    fraction = np.where(np.isfinite(fraction), fraction, 0.5)   # burn-in days: no buckets anyway
    volume = bars["volume"].to_numpy(dtype=float)
    edges = bucket_edges_daily(est["volume"].to_numpy(), est["bucket_volume"].to_numpy())
    buckets = buckets_from_edges(bars, volume * fraction, edges)
    if true_buy is not None:
        true = buckets_from_edges(bars, np.asarray(true_buy, dtype=float), edges)
        buckets["true_buy"] = true["buy"].to_numpy()
        buckets["true_sell"] = true["sell"].to_numpy()
    return buckets


def trading_minutes(ts: pd.Series, session_minutes: float | None) -> np.ndarray:
    """Clock that only runs while the market is open, in minutes.

    For a market that closes overnight (IVE), a bucket that spans the close should not
    look 17 hours long. With session_minutes=None the clock is ordinary time (BTC, 24/7).
    """
    if session_minutes is None:
        return (ts - ts.iloc[0]).dt.total_seconds().to_numpy() / 60
    day = ts.dt.normalize()
    day_index = pd.factorize(day)[0]
    within = (ts - day).dt.total_seconds().to_numpy() / 60
    within -= pd.Series(within).groupby(day_index).transform("min").to_numpy()
    return day_index * session_minutes + within


def signals(buckets: pd.DataFrame, n: int, clock: dict) -> pd.DataFrame:
    """Add returns, VPIN (BVC and, if present, true), trailing RV and bucket duration."""
    b = buckets.copy()
    b["ret"] = next_abs_return(b["end_price"].to_numpy())
    b["vpin"] = vpin(b["buy"], b["sell"], b["volume"], n)
    if "true_buy" in b:
        b["vpin_true"] = vpin(b["true_buy"], b["true_sell"], b["volume"], n)
    b["rv"] = b["ret"].rolling(n).mean()        # same window and timing as VPIN
    end = np.searchsorted(clock["ts"], b["end_ts"].to_numpy(), side="right") - 1
    b["duration"] = np.diff(clock["minutes"][end], prepend=np.nan)
    return b


def realtime_cdf(x: np.ndarray, min_history: int) -> np.ndarray:
    """CDF of each value among the values already observed (no look-ahead)."""
    return cdf_expanding(np.asarray(x, dtype=float), min_history)
