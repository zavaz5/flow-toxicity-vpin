"""Measurement precision (±) of our metrics: a block bootstrap by calendar month.

Buckets are strongly dependent: VPIN windows overlap (n buckets) and volatility comes
in clusters. Resampling single buckets would understate the error, as would the iid
Fisher interval the paper uses (footnote 29). We resample whole calendar months with
replacement, recompute the metric, and report the standard deviation across
replications as "±" and the 2.5–97.5% percentiles as a 95% interval. The seed is
fixed, so results are deterministic.

To make 1,000 replications cheap, every metric is a function of per-month sums
(sufficient statistics). A replication adds up the sums of the months it drew, each
as many times as it was drawn.
"""
import numpy as np
import pandas as pd

from .analysis import diff_stats, intermediate_events, lagged, sample_by_clock, sample_by_volume

REPS = 1000
SEED = 0


def month_ids(ts) -> np.ndarray:
    """Integer id (0, 1, ...) of the calendar month of each timestamp."""
    return pd.factorize(pd.DatetimeIndex(ts).to_period("M"))[0]


def draws(n_months: int, reps: int = REPS, seed: int = SEED) -> np.ndarray:
    """reps x n_months matrix: how often each month is drawn in each replication."""
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n_months, size=(reps, n_months))
    counts = np.zeros((reps, n_months))
    np.add.at(counts, (np.repeat(np.arange(reps), n_months), idx.ravel()), 1)
    return counts


def monthly_sums(months: np.ndarray, columns: list[np.ndarray], n_months: int) -> np.ndarray:
    """n_months x k matrix of per-month sums of each column (NaN-free inputs)."""
    return np.column_stack([np.bincount(months, weights=c, minlength=n_months) for c in columns])


def bootstrap(sums: np.ndarray, stats: dict, reps: int = REPS, seed: int = SEED) -> dict:
    """Apply each stat (a function of the summed vector) to the full sample and to every
    replication. Returns {name: {value, se, lo, hi}}."""
    weights = draws(sums.shape[0], reps, seed)
    totals = weights @ sums
    out = {}
    for name, f in stats.items():
        with np.errstate(divide="ignore", invalid="ignore"):
            values = np.array([f(t) for t in totals])
            point = f(sums.sum(axis=0))
        values = values[np.isfinite(values)]
        out[name] = {"value": float(point), "se": float(np.std(values, ddof=1)) if len(values) > 1 else np.nan,
                     "lo": float(np.percentile(values, 2.5)) if len(values) else np.nan,
                     "hi": float(np.percentile(values, 97.5)) if len(values) else np.nan}
    return out


def corr_from_sums(t) -> float:
    """Pearson correlation from [n, Σx, Σy, Σx², Σy², Σxy]."""
    n, sx, sy, sxx, syy, sxy = t[:6]
    return (n * sxy - sx * sy) / np.sqrt((n * sxx - sx ** 2) * (n * syy - sy ** 2))


def corr_columns(x, y):
    return [np.ones_like(x), x, y, x * x, y * y, x * y]


def section5(signal: np.ndarray, cdf: np.ndarray, ret: np.ndarray, price: np.ndarray, ts,
             mask: np.ndarray | None = None, move: float = 0.0075, reps: int = REPS) -> dict:
    """Section 5 metrics with ± for one signal (VPIN, or a benchmark such as RV).

    corr: corr(ln signal_{tau-1}, |r_tau|); insurance: P(CDF_{tau-1} > 0.75 | |r_tau| > move);
    alarm: P(CDF_{tau-1} > 0.75); lift = insurance / alarm; bottom_small:
    P(|r_tau| < 0.25% | CDF_{tau-1} < 0.25); tp_top / tp_bottom: share of stays in a top /
    bottom-quartile 5%-tile with a move above `move`; tp_diff = tp_top - tp_bottom.
    """
    months = month_ids(ts)
    m = months.max() + 1
    mask = np.ones(len(ret), dtype=bool) if mask is None else mask
    with np.errstate(divide="ignore"):
        x = np.log(lagged(signal))
    prev = lagged(cdf)
    ok = mask & np.isfinite(x) & np.isfinite(ret) & np.isfinite(prev)
    xo, yo = np.where(ok, x, 0.0), np.where(ok, ret, 0.0)
    big, alarm, bottom = ok & (ret > move), ok & (prev > 0.75), ok & (prev < 0.25)
    small = ret < 0.0025
    cols = [c * ok for c in corr_columns(xo, yo)]
    cols += [(big & alarm).astype(float), big.astype(float), alarm.astype(float), ok.astype(float),
             (bottom & small).astype(float), bottom.astype(float)]
    sums = monthly_sums(months, cols, m)

    events = intermediate_events(cdf, price)
    start = events["start"].to_numpy()
    keep = mask[start]
    ev_month = months[start][keep]
    top = (events["bin"].to_numpy() >= 15)[keep]
    bot = (events["bin"].to_numpy() <= 4)[keep]
    hit = (events["max_abs_return"].to_numpy() > move)[keep]
    ev_sums = monthly_sums(ev_month, [top * 1.0, (top & hit) * 1.0, bot * 1.0, (bot & hit) * 1.0], m)
    sums = np.hstack([sums, ev_sums])
    stats = {
        "corr": corr_from_sums,
        "insurance": lambda t: t[6] / t[7],
        "alarm": lambda t: t[8] / t[9],
        "lift": lambda t: (t[6] / t[7]) / (t[8] / t[9]),
        "bottom_small": lambda t: t[10] / t[11],
        "tp_top": lambda t: t[13] / t[12],
        "tp_bottom": lambda t: t[15] / t[14],
        "tp_diff": lambda t: t[13] / t[12] - t[15] / t[14],
    }
    out = bootstrap(sums, stats, reps)
    out["n_obs"] = int(ok.sum())
    out["big_moves"] = int(big.sum())
    return out


def ols_delta_r2(X: np.ndarray, y: np.ndarray, extra: int, ts, reps: int = REPS) -> dict:
    """R² of y on [1, X] and on [1, X without its last `extra` columns], with ±.

    OLS from per-month cross-product sums: R² does not depend on how the variables are
    scaled, so no re-standardization is needed inside a replication.
    """
    months = month_ids(ts)
    m = months.max() + 1
    Z = np.column_stack([np.ones(len(y)), X])
    p = Z.shape[1]
    cols = [Z[:, i] * Z[:, j] for i in range(p) for j in range(p)] + [Z[:, i] * y for i in range(p)] + [y * y, y]
    sums = monthly_sums(months, cols, m)

    def r2(t, use):
        zz = t[: p * p].reshape(p, p)[np.ix_(use, use)]
        zy = t[p * p: p * p + p][use]
        yy, sy, n = t[p * p + p], t[p * p + p + 1], t[0]
        beta = np.linalg.solve(zz, zy)
        return 1 - (yy - beta @ zy) / (yy - sy ** 2 / n)

    full, base = list(range(p)), list(range(p - extra))
    return bootstrap(sums, {"r2_full": lambda t: r2(t, full), "r2_base": lambda t: r2(t, base),
                            "delta_r2": lambda t: r2(t, full) - r2(t, base)}, reps)


TABLE1_STATS = ["Skew", "Kurt", "Min", "Max", "L-B*", "White*", "J-B*"]


def table1(bars: pd.DataFrame, draws_per_day: int, session_minutes: float, reps: int = REPS,
           seed: int = SEED) -> pd.DataFrame:
    """Table 1 on intraday price changes with ± and P(volume time < clock time).

    Both samples draw the same months in each replication (a paired bootstrap), so the
    last column is the share of replications in which sampling by volume gives the lower
    (closer to normal / less dependent) value.
    """
    samples = {"Chrono time": sample_by_clock(bars, draws_per_day, session_minutes, with_day=True),
               "Volume time": sample_by_volume(bars, draws_per_day, with_day=True)}
    t_len = min(len(v[0]) for v in samples.values())   # equal T, as in the paper
    pieces, labels = {}, None
    for name, (price, day) in samples.items():
        price, day = price[:t_len], day[:t_len]
        same = day[1:] == day[:-1]
        change, month = np.diff(price)[same], pd.DatetimeIndex(day[1:][same]).to_period("M")
        pieces[name] = {mo: change[month == mo] for mo in month.unique()}
        labels = sorted(set(labels or []) | set(pieces[name]))
    point = {name: diff_stats(np.concatenate([pieces[name][mo] for mo in labels if mo in pieces[name]]))
             for name in samples}
    rng = np.random.default_rng(seed)
    boot = {name: {s: [] for s in TABLE1_STATS} for name in samples}
    for _ in range(reps):
        drawn = [labels[i] for i in rng.integers(0, len(labels), len(labels))]
        for name in samples:
            x = np.concatenate([pieces[name][mo] for mo in drawn if mo in pieces[name]])
            for s, v in diff_stats(x).items():
                if s in boot[name]:
                    boot[name][s].append(v)
    rows = {}
    for s in TABLE1_STATS:
        c, v = np.array(boot["Chrono time"][s]), np.array(boot["Volume time"][s])
        rows[s] = {"Chrono time": point["Chrono time"][s], "Chrono ±": c.std(ddof=1),
                   "Volume time": point["Volume time"][s], "Volume ±": v.std(ddof=1),
                   # for Skew "lower" means closer to zero
                   "P(volume < clock)": float(np.mean(np.abs(v) < np.abs(c)) if s in ("Skew", "Min") else np.mean(v < c))}
    out = pd.DataFrame(rows).T
    out.loc["T"] = [point["Chrono time"]["T"], 0, point["Volume time"]["T"], 0, np.nan]
    return out


def fmt(stat: dict, pct: bool = False, digits: int = 2) -> str:
    """'0.08 ± 0.02' or '51% ± 6%' (± is the bootstrap standard error)."""
    if pct:
        return f"{stat['value']:.0%} ± {stat['se']:.0%}"
    return f"{stat['value']:.{digits}f} ± {stat['se']:.{digits}f}"
