"""Statistics behind the paper's tables and figures.

Each function maps to one exhibit:
- sampling_table (Table 1): price changes sampled by clock time vs by volume.
- vpin_summary, vpin_quantiles (Tables 2 and 3).
- next_abs_return, vpin_return_correlation (Figures 10 and 11).
- conditional_tables, insurance_value (Table 4, Figure 12).
- intermediate_events, true_positive_rate (Table 5, Figure 14).
"""
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.diagnostic import acorr_ljungbox


# ---------- Table 1: clock time vs volume time ----------

def sample_by_clock(bars: pd.DataFrame, draws_per_day: int, session_minutes: float,
                    with_day: bool = False):
    """Last price in each of `draws_per_day` equal clock intervals of every day."""
    minute = (bars["ts"] - bars["day"]).dt.total_seconds() / 60
    minute -= minute.groupby(bars["day"]).transform("min")
    slot = np.minimum((minute / (session_minutes / draws_per_day)).astype(int), draws_per_day - 1)
    last = bars.groupby([bars["day"], slot])["close"].last()
    days = last.index.get_level_values(0).to_numpy()
    return (last.to_numpy(), days) if with_day else last.to_numpy()


def sample_by_volume(bars: pd.DataFrame, draws_per_day: int, with_day: bool = False):
    """Price each time cumulative volume crosses a multiple of ADV / draws_per_day."""
    adv = bars.groupby("day")["volume"].sum().mean()
    cum = bars["volume"].cumsum().to_numpy()
    marks = np.arange(1, int(cum[-1] // (adv / draws_per_day)) + 1) * (adv / draws_per_day)
    idx = np.searchsorted(cum, marks, side="left")
    price = bars["close"].to_numpy()[idx]
    return (price, bars["day"].to_numpy()[idx]) if with_day else price


def _white_r2(x: np.ndarray, lags: int = 10) -> float:
    """R^2 of x_t^2 on all products x_{t-i} x_{t-j}, 1 <= i <= j <= lags (Table 1's White*)."""
    t = len(x)
    lagged = np.column_stack([x[lags - i: t - i] for i in range(1, lags + 1)])
    cols = [lagged[:, i] * lagged[:, j] for i in range(lags) for j in range(i, lags)]
    design = np.column_stack([np.ones(t - lags)] + cols)
    y = x[lags:] ** 2
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    resid = y - design @ beta
    return float(1 - resid.var() / y.var())


def sampling_stats(prices: np.ndarray, days: np.ndarray | None = None) -> dict:
    """Statistics of standardized first differences, as in Table 1.

    Kurt is raw (not excess) kurtosis: the paper's J-B* = (s^2 + (k-3)^2 / 4) / 6
    reproduces its own numbers only with raw k. J-B* is the Jarque-Bera statistic
    divided by T; L-B* is the Ljung-Box Q statistic at 10 lags.
    """
    x = np.diff(np.asarray(prices, dtype=float))
    if days is not None:            # intraday only: drop changes that span the close
        x = x[days[1:] == days[:-1]]
    return diff_stats(x)


def diff_stats(x: np.ndarray) -> dict:
    """Table 1 statistics of a series of price changes (standardized here)."""
    x = (x - x.mean()) / x.std()
    s, k = stats.skew(x), stats.kurtosis(x, fisher=False)
    return {
        "T": len(x), "Mean": x.mean(), "StDev": x.std(), "Skew": s, "Kurt": k,
        "Min": x.min(), "Max": x.max(),
        "L-B*": float(acorr_ljungbox(x, lags=[10])["lb_stat"].iloc[0]),
        "White*": _white_r2(x), "J-B*": (s ** 2 + (k - 3) ** 2 / 4) / 6,
    }


def sampling_table(bars: pd.DataFrame, draws_per_day: int, session_minutes: float,
                   intraday_only: bool = False) -> pd.DataFrame:
    """Table 1 for one sampling frequency: clock time vs volume time, equal T.

    `intraday_only` drops price changes that span the overnight close. The paper's
    E-mini trades almost around the clock, so its sample has no such changes.
    """
    clock, clock_day = sample_by_clock(bars, draws_per_day, session_minutes, with_day=True)
    volume, volume_day = sample_by_volume(bars, draws_per_day, with_day=True)
    t = min(len(clock), len(volume))  # "both samples have the same number of observations"
    pick = (lambda d: d[:t]) if intraday_only else (lambda d: None)
    return pd.DataFrame({"Chrono time": sampling_stats(clock[:t], pick(clock_day)),
                         "Volume time": sampling_stats(volume[:t], pick(volume_day))})


# ---------- Tables 2 and 3 ----------

QUANTILE_LEVELS = [0.1, 0.25, 0.5, 0.75, 0.9]


def vpin_summary(v: np.ndarray) -> dict:
    """Table 2: moments, AR(1) and quantiles of the VPIN series."""
    v = v[~np.isnan(v)]
    out = {"Average": v.mean(), "StDev": v.std(ddof=1), "Skew": stats.skew(v),
           "Ex. Kurt": stats.kurtosis(v), "AR(1)": np.corrcoef(v[1:], v[:-1])[0, 1],
           "#Observ.": len(v)}
    out.update({f"CDF({q})": np.quantile(v, q) for q in QUANTILE_LEVELS})
    return out


def vpin_quantiles(v: np.ndarray, levels=np.arange(0.1, 1.0, 0.1)) -> pd.Series:
    """Table 3: VPIN value at each CDF level."""
    v = v[~np.isnan(v)]
    return pd.Series(np.quantile(v, levels), index=np.round(levels, 1))


# ---------- Section 5: VPIN and the next bucket's return ----------

def next_abs_return(end_price: np.ndarray) -> np.ndarray:
    """|P_tau / P_{tau-1} - 1|: absolute return over bucket tau (NaN for the first)."""
    p = np.asarray(end_price, dtype=float)
    return np.concatenate([[np.nan], np.abs(p[1:] / p[:-1] - 1)])


def lagged(x: np.ndarray) -> np.ndarray:
    """x_{tau-1} aligned with tau, so that VPIN never overlaps the return it predicts."""
    return np.concatenate([[np.nan], np.asarray(x, dtype=float)[:-1]])


def vpin_return_correlation(v: np.ndarray, abs_ret: np.ndarray) -> tuple[float, int]:
    """Pearson correlation of ln VPIN_{tau-1} with |return over bucket tau| (Figure 10)."""
    with np.errstate(divide="ignore"):   # VPIN = 0 (a perfectly balanced window) gives -inf
        x, y = np.log(lagged(v)), abs_ret
    ok = np.isfinite(x) & np.isfinite(y)
    return float(np.corrcoef(x[ok], y[ok])[0, 1]), int(ok.sum())


def _bins(cdf: np.ndarray) -> np.ndarray:
    """5%-tile bin of a CDF value: 0 for (0, 0.05), ..., 19 for [0.95, 1]."""
    return np.minimum(np.floor(cdf * 20), 19)


def conditional_tables(cdf_prev: np.ndarray, abs_ret: np.ndarray, width: float = 0.0025,
                       n_bins: int = 8) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Table 4a (return given VPIN bin, rows sum to 1) and 4b (VPIN bin given return,
    columns sum to 1). Return bins are [0, 0.25%), ..., [1.75%, 2%), >= 2%."""
    ok = np.isfinite(cdf_prev) & np.isfinite(abs_ret)
    vbin = _bins(cdf_prev[ok]).astype(int)
    rbin = np.minimum(np.floor(abs_ret[ok] / width), n_bins).astype(int)
    counts = pd.crosstab(vbin, rbin).reindex(index=range(20), columns=range(n_bins + 1), fill_value=0)
    counts.index = [f"{i * 5}-{i * 5 + 5}%" for i in range(20)]
    counts.columns = [f"<{(j + 1) * width:.2%}" for j in range(n_bins)] + [f">={n_bins * width:.2%}"]
    rows, cols = counts.sum(axis=1).replace(0, np.nan), counts.sum(axis=0).replace(0, np.nan)
    return counts.div(rows, axis=0), counts.div(cols, axis=1)  # empty bins stay NaN


def insurance_value(cdf_prev: np.ndarray, abs_ret: np.ndarray, move: float = 0.0075,
                    level: float = 0.75) -> float:
    """Prob(CDF(VPIN_{tau-1}) > level | |return_tau| > move) (Figure 12)."""
    ok = np.isfinite(cdf_prev) & np.isfinite(abs_ret) & (abs_ret > move)
    return float(np.mean(cdf_prev[ok] > level)) if ok.any() else np.nan


# ---------- Section 5.4: volatility while VPIN stays in a 5%-tile ----------

def _max_abs_move(p: np.ndarray) -> float:
    """max over m < l of |p_l / p_m - 1| (Eq. 10), in one pass with running extremes."""
    run_min = np.minimum.accumulate(p[:-1])
    run_max = np.maximum.accumulate(p[:-1])
    up = np.max(p[1:] / run_min - 1)
    down = np.max(1 - p[1:] / run_max)
    return float(max(up, down))


def intermediate_events(cdf: np.ndarray, end_price: np.ndarray) -> pd.DataFrame:
    """One row per stay of VPIN in a 5%-tile: the bin and the largest absolute return
    between any two buckets from the crossing into the bin to the crossing out of it.
    The last stay, which never ends inside the sample, is dropped."""
    ok = np.flatnonzero(np.isfinite(cdf))
    bins = _bins(cdf[ok])
    cross = ok[np.flatnonzero(np.diff(bins) != 0) + 1]   # buckets where a new bin starts
    starts = np.concatenate([[ok[0]], cross])
    p = np.asarray(end_price, dtype=float)
    rows = []
    for a, b in zip(starts[:-1], starts[1:]):
        rows.append((int(a), int(_bins(cdf[a])), int(b - a), _max_abs_move(p[a: b + 1])))
    return pd.DataFrame(rows, columns=["start", "bin", "buckets", "max_abs_return"])


def true_positive_rate(events: pd.DataFrame, move: float = 0.0075, first_bin: int = 15) -> float:
    """Share of stays in the upper quartile (bins 15-19) with a move above `move` (Fig. 14)."""
    top = events[events["bin"] >= first_bin]
    return float((top["max_abs_return"] > move).mean()) if len(top) else np.nan


def event_table(events: pd.DataFrame, width: float = 0.0025, n_bins: int = 8) -> pd.DataFrame:
    """Table 5: distribution of the largest intermediate move for each VPIN 5%-tile."""
    rbin = np.minimum(np.floor(events["max_abs_return"] / width), n_bins).astype(int)
    counts = pd.crosstab(events["bin"], rbin).reindex(index=range(20), columns=range(n_bins + 1),
                                                       fill_value=0)
    counts.index = [f"{i * 5}-{i * 5 + 5}%" for i in range(20)]
    counts.columns = [f"<{(j + 1) * width:.2%}" for j in range(n_bins)] + [f">={n_bins * width:.2%}"]
    return counts.div(counts.sum(axis=1).replace(0, np.nan), axis=0)
