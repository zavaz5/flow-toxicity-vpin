"""The VPIN metric (paper Eq. 9) and its empirical CDF.

VPIN after bucket tau = sum of |sell - buy| over the last n buckets / (n * V).
The paper reads VPIN through its CDF, built from the whole sample (Section 4). That
uses future data, so we also provide an expanding CDF that only looks backwards.
"""
import numpy as np
import pandas as pd

from .bars import bar_price_changes
from .buckets import average_daily_volume, build_buckets
from .classify import bvc_buy_fraction


def vpin(buy: np.ndarray, sell: np.ndarray, volume: np.ndarray, n: int) -> np.ndarray:
    """Rolling VPIN over n buckets; NaN until n buckets exist.

    With equal buckets this is exactly Eq. 9. Dividing by summed volume instead of n*V
    also covers buckets of unequal size.
    """
    imbalance = pd.Series(np.abs(np.asarray(sell) - np.asarray(buy)))
    total = pd.Series(np.asarray(volume, dtype=float))
    return (imbalance.rolling(n).sum() / total.rolling(n).sum()).to_numpy()


def cdf_full_sample(x: np.ndarray) -> np.ndarray:
    """Empirical CDF value of every point using the whole sample (the paper's choice)."""
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    ok = ~np.isnan(x)
    ranks = pd.Series(x[ok]).rank(method="max").to_numpy()
    out[ok] = ranks / ok.sum()
    return out


def cdf_expanding(x: np.ndarray, min_history: int) -> np.ndarray:
    """Share of earlier values (and the current one) that are <= the current value.

    Uses only the past, so it is what a market maker could have computed in real time.
    A Fenwick tree over value ranks gives O(N log N) for ~10^5-10^6 buckets.
    """
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    ok = np.flatnonzero(~np.isnan(x))
    if len(ok) == 0:
        return out
    ranks = pd.Series(x[ok]).rank(method="max").to_numpy().astype(int)  # 1..m, ties share max
    tree = np.zeros(len(ok) + 1, dtype=np.int64)
    for seen, (pos, r) in enumerate(zip(ok, ranks), start=1):
        i = r
        while i < len(tree):          # add this value
            tree[i] += 1
            i += i & -i
        count, i = 0, r
        while i > 0:                  # count values with rank <= r
            count += tree[i]
            i -= i & -i
        if seen >= min_history:
            out[pos] = count / seen
    return out


def vpin_series(bars: pd.DataFrame, buckets_per_day: int, n: int,
                sigma: float | None = None, bucket_volume: float | None = None,
                buy_volume: np.ndarray | None = None) -> pd.DataFrame:
    """Buckets with VPIN, the paper's way: BVC on time bars, V = ADV / buckets_per_day.

    `sigma` defaults to the standard deviation of bar price changes over the sample;
    `bucket_volume` to the sample's average daily volume / buckets_per_day. Passing
    `buy_volume` (e.g. true or Lee-Ready buy volume per bar) skips BVC.
    """
    if buy_volume is None:
        change = bar_price_changes(bars)
        if sigma is None:
            sigma = float(np.nanstd(change))
        buy_volume = bars["volume"].to_numpy() * bvc_buy_fraction(change, sigma)
    if bucket_volume is None:
        bucket_volume = average_daily_volume(bars) / buckets_per_day
    buckets = build_buckets(bars, buy_volume, bucket_volume)
    buckets["vpin"] = vpin(buckets["buy"], buckets["sell"], buckets["volume"], n)
    return buckets
