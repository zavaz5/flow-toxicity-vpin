"""Rule D5 of the pre-registration: the one-day-sigma fix of bulk classification on real data.

The simulation found that bulk classification with one sigma for the whole sample turns
calm-versus-turbulent changes in volatility into fake order imbalance, while measuring each
price change against the previous day's volatility ("local sigma") does not. Here the same
fix is applied to the real-time pipeline:
- BTC, where the true buy volume is known: does local-sigma VPIN track true-label VPIN
  better than standard bulk-classified VPIN?
- BTC and IVE 2011-2026: corr with the next |return|, lift, and value beyond trailing
  volatility (Newey-West t), for every version. Reported whatever they show.

Usage: python scripts/local_sigma.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from vpin import uncertainty as U
from vpin.bars import bar_log_changes, time_bars
from vpin.buckets import bucket_edges_daily, buckets_from_edges
from vpin.data import load_btc_klines, load_ive_ticks
from vpin.realtime import daily_estimates, realtime_cdf, signals, trading_minutes

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import extensions as E  # noqa: E402  (regression helper shared with the other extensions)

OUT = ROOT / "results" / "extensions" / "local_sigma"


def local_fraction(bars: pd.DataFrame, bars_per_day: int) -> np.ndarray:
    """Z(change / sigma of the previous day's one-minute log changes); 0.5 before a day exists."""
    change = bar_log_changes(bars)
    sigma = pd.Series(change).rolling(bars_per_day, min_periods=bars_per_day // 2).std().shift(1).to_numpy()
    f = norm.cdf(change / sigma)
    return np.where(np.isfinite(f), f, 0.5)


def bucket_versions(bars: pd.DataFrame, bpd: int, bars_per_day: int, true_buy=None) -> pd.DataFrame:
    """Same real-time buckets for every version: standard BVC (trailing 250-day sigma),
    local-sigma BVC and, if given, the true buy volume."""
    est = daily_estimates(bars, bpd)
    volume = bars["volume"].to_numpy(dtype=float)
    sigma = est["sigma"].reindex(bars["day"]).to_numpy()
    f_std = norm.cdf(bar_log_changes(bars) / sigma)
    edges = bucket_edges_daily(est["volume"].to_numpy(), est["bucket_volume"].to_numpy())
    b = buckets_from_edges(bars, volume * np.where(np.isfinite(f_std), f_std, 0.5), edges)
    local = buckets_from_edges(bars, volume * local_fraction(bars, bars_per_day), edges)
    b["local_buy"], b["local_sell"] = local["buy"].to_numpy(), local["sell"].to_numpy()
    if true_buy is not None:
        t = buckets_from_edges(bars, np.asarray(true_buy, dtype=float), edges)
        b["true_buy"], b["true_sell"] = t["buy"].to_numpy(), t["sell"].to_numpy()
    return b


def evaluate(bars, bpd, n, bars_per_day, session_minutes, market, mask_fn, true_buy=None):
    clock = {"ts": bars["ts"].to_numpy(), "minutes": trading_minutes(bars["ts"], session_minutes)}
    b = signals(bucket_versions(bars, bpd, bars_per_day, true_buy), n, clock)
    from vpin.metric import vpin
    b["vpin_local"] = vpin(b["local_buy"], b["local_sell"], b["volume"], n)
    mask = mask_fn(b)
    rows, cols = [], ["vpin", "vpin_local", "rv"] + (["vpin_true"] if true_buy is not None else [])
    names = {"vpin": "VPIN, standard BVC", "vpin_local": "VPIN, local-sigma BVC (fix)", "vpin_true": "VPIN, true labels",
             "rv": "trailing volatility"}
    for col in cols:
        cdf = realtime_cdf(b[col], min_history=60 * bpd)
        res = U.section5(b[col].to_numpy(), cdf, b["ret"].to_numpy(), b["end_price"].to_numpy(), b["end_ts"], mask=mask)
        rows.append({"market": market, "buckets_per_day": bpd, "sample_length": n, "signal": names[col],
                     **{f"{m}": res[m]["value"] for m in ("corr", "lift", "tp_diff")},
                     **{f"{m}_se": res[m]["se"] for m in ("corr", "lift", "tp_diff")}})
    regs = [dict(market=market, choice=f"({bpd}, {n})", **r) for r in E.regression(b, mask, [c for c in cols if c != "rv"], n)]
    tracking = None
    if true_buy is not None:
        ok = mask & b["vpin"].notna().to_numpy() & b["vpin_true"].notna().to_numpy() & b["vpin_local"].notna().to_numpy()
        months = U.month_ids(b["end_ts"][ok])
        v, vl, vt = (b[c].to_numpy()[ok] for c in ("vpin", "vpin_local", "vpin_true"))
        sums = U.monthly_sums(months, U.corr_columns(vl, vt) + U.corr_columns(v, vt), months.max() + 1)
        tracking = U.bootstrap(sums, {"corr_local_true": lambda t: U.corr_from_sums(t[0:6]),
                                      "corr_standard_true": lambda t: U.corr_from_sums(t[6:12]),
                                      "difference": lambda t: U.corr_from_sums(t[0:6]) - U.corr_from_sums(t[6:12])})
    return rows, regs, tracking


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    k = load_btc_klines("2020-01", "2026-09")
    btc = pd.DataFrame({"ts": k["ts"], "open": k["open"], "close": k["close"], "volume": k["volume"]})
    btc["day"] = btc["ts"].dt.normalize()
    rows, regs, tracking = [], [], {}
    for bpd, n in [(50, 50), (50, 250)]:
        r, g, t = evaluate(btc, bpd, n, 1440, None, "BTC", lambda b: np.ones(len(b), bool), k["taker_buy_volume"].to_numpy())
        rows += r
        regs += g
        tracking[f"BTC_{bpd}_{n}"] = t
    ticks = load_ive_ticks("2009-09-28", "2026-09-30")
    ive = time_bars(ticks, 60)
    del ticks
    oos = pd.Timestamp("2011-08-16")
    r, g, _ = evaluate(ive, 50, 250, 390, 390, "IVE 2011-26", lambda b: (b["end_ts"] >= oos).to_numpy())
    rows += r
    regs += g
    pd.DataFrame(rows).to_csv(OUT / "predictive.csv", index=False)
    pd.DataFrame(regs).to_csv(OUT / "regressions.csv", index=False)
    (OUT / "tracking.json").write_text(json.dumps(tracking, indent=2, default=float))
    print(pd.DataFrame(rows).round(3).to_string(index=False))
    print(pd.DataFrame(regs)[["market", "choice", "signal", "beta_vpin", "t_vpin_hac", "delta_r2"]].to_string(index=False))
    print(json.dumps(tracking, indent=1, default=float))


if __name__ == "__main__":
    main()
