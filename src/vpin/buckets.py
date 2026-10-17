"""Equal-volume buckets: the paper's volume clock (Section 2.2).

Trades (or bars) are poured into buckets of V units of volume each. If a bar does not
fit into the current bucket, the excess spills into the next one, and a large bar can
fill several buckets. A split bar keeps its buy share in every piece.

Implementation: within a bar, buy volume accrues at a constant rate (its buy share), so
cumulative buy volume is a piecewise-linear function of cumulative volume. The buy
volume of a bucket is that function evaluated at the bucket's right edge minus its left
edge, which np.interp computes exactly.
"""
import numpy as np
import pandas as pd


def fill_buckets(volume: np.ndarray, buy_volume: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Buy volume inside each bucket (edges[k], edges[k+1]] of cumulative volume.

    `edges` starts at 0 and must not go beyond the total volume.
    """
    cum_volume = np.concatenate([[0.0], np.cumsum(volume)])
    cum_buy = np.concatenate([[0.0], np.cumsum(buy_volume)])
    return np.diff(np.interp(edges, cum_volume, cum_buy))


def bucket_edges_fixed(total_volume: float, bucket_volume: float) -> np.ndarray:
    """Edges 0, V, 2V, ... up to the last complete bucket (as in the paper)."""
    n = int(total_volume // bucket_volume)
    return np.arange(n + 1) * bucket_volume


def bucket_edges_daily(day_volume: np.ndarray, day_bucket_volume: np.ndarray) -> np.ndarray:
    """Edges when the bucket size changes from day to day (real-time pipeline).

    `day_bucket_volume[d]` is the bucket size for day d, estimated from earlier days only;
    a bucket gets the size of the day in which it ends. Days before the first known size
    are burn-in: the first bucket starts at the beginning of the first day with a size.
    """
    day_volume = np.asarray(day_volume, dtype=float)
    size = pd.Series(np.asarray(day_bucket_volume, dtype=float)).ffill().to_numpy()
    known = np.flatnonzero(np.isfinite(size) & (size > 0))
    day_start = np.concatenate([[0.0], np.cumsum(day_volume)])
    if len(known) == 0:
        return day_start[:1]
    edges = [day_start[known[0]]]
    for d in range(known[0], len(day_volume)):
        count = int((day_start[d + 1] - edges[-1]) // size[d])
        edges.extend(edges[-1] + size[d] * np.arange(1, count + 1))
    return np.asarray(edges)


def buckets_from_edges(bars: pd.DataFrame, buy_volume: np.ndarray, edges: np.ndarray) -> pd.DataFrame:
    """One row per bucket (edges[k], edges[k+1]] of cumulative volume.

    Columns: `buy`, `sell`, `volume`, `end_ts` and `end_price` (the bar that completes
    the bucket), `start_ts` (the bar where the bucket starts).
    """
    volume = bars["volume"].to_numpy(dtype=float)
    buy = fill_buckets(volume, buy_volume, edges)
    size = np.diff(edges)
    cum_volume = np.cumsum(volume)
    # The bar that holds the right edge completes the bucket: first bar with cum >= edge.
    end_bar = np.searchsorted(cum_volume, edges[1:] * (1 - 1e-12), side="left")
    start_bar = np.searchsorted(cum_volume, edges[:-1] * (1 + 1e-12), side="right")
    start_bar = np.minimum(start_bar, len(volume) - 1)
    out = pd.DataFrame({
        "buy": buy,
        "sell": size - buy,
        "volume": size,
        "start_ts": bars["ts"].to_numpy()[start_bar],
        "end_ts": bars["ts"].to_numpy()[end_bar],
        "end_price": bars["close"].to_numpy()[end_bar],
    })
    return out


def build_buckets(bars: pd.DataFrame, buy_volume: np.ndarray, bucket_volume: float) -> pd.DataFrame:
    """Buckets of fixed size V over the whole sample (the paper's procedure)."""
    edges = bucket_edges_fixed(bars["volume"].sum(), bucket_volume)
    return buckets_from_edges(bars, buy_volume, edges)


def average_daily_volume(bars: pd.DataFrame) -> float:
    """Average volume per trading day: the paper's V is 1/50 of it."""
    return float(bars.groupby("day")["volume"].sum().mean())
