"""Three ways to split volume into buys and sells.

- Bulk volume classification (BVC, paper Eq. 7): a bar's volume is split in proportion
  Z(dP / sigma) to buys, the rest to sells. Z is the standard normal CDF.
- Tick rule: a trade above the last different price is a buy, below it a sell.
- Lee-Ready (1991): a trade above the quote midpoint is a buy, below it a sell; trades
  at the midpoint fall back to the tick rule. The paper's trade-by-trade benchmark.
"""
import numpy as np
from scipy.stats import norm


def bvc_buy_fraction(price_change: np.ndarray, sigma: float) -> np.ndarray:
    """Share of a bar's volume classified as buys: Z(dP / sigma).

    No price change gives 0.5 (volume split evenly); a large rise gives almost 1.
    """
    if not sigma > 0:
        raise ValueError("sigma must be positive")
    return norm.cdf(np.asarray(price_change, dtype=float) / sigma)


def tick_rule(price: np.ndarray) -> np.ndarray:
    """+1 for buys, -1 for sells, by comparing each price with the last different one.

    Zero-ticks inherit the previous sign. The first trades, before any price change,
    have no reference and are set to +1 (a convention; it affects only a handful).
    """
    sign = np.sign(np.diff(np.asarray(price, dtype=float), prepend=np.nan))
    sign[sign == 0] = np.nan
    # forward-fill the last non-zero tick
    idx = np.where(~np.isnan(sign), np.arange(len(sign)), 0)
    np.maximum.accumulate(idx, out=idx)
    filled = sign[idx]
    filled[np.isnan(filled)] = 1.0
    return filled


def lee_ready(price: np.ndarray, bid: np.ndarray, ask: np.ndarray) -> np.ndarray:
    """+1 / -1 by the quote rule, with the tick rule for trades at the midpoint.

    Kibot stores the bid and ask in force at each trade, so no 5-second quote delay is
    applied (the delay corrected for slow quote reporting on the 1990s NYSE tape).
    """
    price = np.asarray(price, dtype=float)
    mid = (np.asarray(bid, dtype=float) + np.asarray(ask, dtype=float)) / 2
    sign = np.sign(price - mid)
    at_mid = (sign == 0) | ~np.isfinite(sign)
    sign[at_mid] = tick_rule(price)[at_mid]
    return sign
