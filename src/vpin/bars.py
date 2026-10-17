"""Time bars: the unit that bulk volume classification works on (paper, Section 2.3).

The paper aggregates trades into one-minute bars and classifies each bar's volume by
the standardized price change from the previous bar. Bars with no trades simply do
not exist: they carry no volume to classify.
"""
import numpy as np
import pandas as pd


def time_bars(ticks: pd.DataFrame, seconds: int) -> pd.DataFrame:
    """Aggregate trades into bars of `seconds` length.

    Returns one row per non-empty bar: `ts` (bar start), `open` and `close` (first and
    last trade price), `volume` (total size) and `day`. If the ticks carry a `buy_volume`
    column (already classified trades) it is summed as well.
    """
    start = ticks["ts"].dt.floor(f"{seconds}s")
    agg = {"price": ["first", "last"], "size": "sum"}
    if "buy_volume" in ticks:
        agg["buy_volume"] = "sum"
    grouped = ticks.groupby(start, sort=True).agg(agg)
    bars = pd.DataFrame({
        "ts": grouped.index,
        "open": grouped[("price", "first")].to_numpy(),
        "close": grouped[("price", "last")].to_numpy(),
        "volume": grouped[("size", "sum")].to_numpy(dtype=float),
    })
    if "buy_volume" in ticks:
        bars["buy_volume"] = grouped[("buy_volume", "sum")].to_numpy(dtype=float)
    bars["day"] = bars["ts"].dt.normalize()
    return bars.reset_index(drop=True)


def bar_price_changes(bars: pd.DataFrame) -> np.ndarray:
    """Price change of each bar relative to the previous bar of the same day.

    The paper uses P_i - P_{i-1} between consecutive time bars (Eq. 7). Its E-mini data
    trade almost around the clock; IVE closes overnight, so the first bar of a day is
    compared with its own first trade instead of yesterday's close: an overnight gap is
    not order flow inside the bar (DEVIATIONS.md, row 3).
    """
    close = bars["close"].to_numpy()
    change = np.diff(close, prepend=np.nan)
    first_of_day = bars["day"].ne(bars["day"].shift()).to_numpy()
    change[first_of_day] = close[first_of_day] - bars["open"].to_numpy()[first_of_day]
    return change


def bar_log_changes(bars: pd.DataFrame) -> np.ndarray:
    """Like bar_price_changes, in log prices.

    Used by the real-time pipeline over many years: a dollar change means different
    things at $35 and at $200 (or at BTC $7k and $120k), a log change does not.
    """
    close = np.log(bars["close"].to_numpy())
    change = np.diff(close, prepend=np.nan)
    first_of_day = bars["day"].ne(bars["day"].shift()).to_numpy()
    change[first_of_day] = close[first_of_day] - np.log(bars["open"].to_numpy()[first_of_day])
    return change
