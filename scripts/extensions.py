"""Experiments beyond the paper. Results go to results/extensions/.

E1  Bulk classification against the truth. Binance records the aggressor of every BTC
    trade, so we know the real buy volume that BVC tries to estimate.
E2  Real-time VPIN out of sample. sigma, V and the CDF use only past data; the paper's
    parameter choices are frozen and tested on IVE data after the paper (2011-08-16 on).
E3  Is VPIN more than volatility? VPIN against trailing realized volatility (RV), in
    regressions with controls, and VPIN from true vs bulk-classified volume (BTC).
E4  Crashes after the paper: when did real-time CDF(VPIN) cross 0.9?

Usage: python scripts/extensions.py [--smoke]
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import yaml
from scipy.stats import norm

from vpin import analysis as A
from vpin import plots as P
from vpin.bars import bar_log_changes, time_bars
from vpin.classify import tick_rule
from vpin.data import load_btc_klines, load_btc_trades, load_ive_ticks
from vpin.metric import cdf_expanding, vpin
from vpin.realtime import daily_estimates, realtime_buckets, trading_minutes

ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load(open(ROOT / "configs" / "pipeline.yaml"))
MOVE = CFG["prediction"]["big_move"]


# ---------- shared evaluation ----------

def signals(buckets: pd.DataFrame, n: int, clock: np.ndarray) -> pd.DataFrame:
    """Add returns, VPIN (BVC and, if present, true), trailing RV and bucket duration."""
    b = buckets.copy()
    b["ret"] = A.next_abs_return(b["end_price"].to_numpy())
    b["vpin"] = vpin(b["buy"], b["sell"], b["volume"], n)
    if "true_buy" in b:
        b["vpin_true"] = vpin(b["true_buy"], b["true_sell"], b["volume"], n)
    b["rv"] = b["ret"].rolling(n).mean()        # same window and timing as VPIN
    end = np.searchsorted(clock["ts"], b["end_ts"].to_numpy(), side="right") - 1
    b["duration"] = np.diff(clock["minutes"][end], prepend=np.nan)
    return b


def realtime_cdf(x: np.ndarray, min_history: int) -> np.ndarray:
    return cdf_expanding(np.asarray(x, dtype=float), min_history)


def metrics(b: pd.DataFrame, col: str, cdf: np.ndarray, mask: np.ndarray) -> dict:
    """Section 5 statistics for one signal on the buckets selected by `mask`."""
    prev = A.lagged(cdf)
    ret = b["ret"].to_numpy()
    with np.errstate(divide="ignore"):
        x = np.log(A.lagged(b[col].to_numpy()))
    ok = mask & np.isfinite(x) & np.isfinite(ret) & np.isfinite(prev)
    big = ok & (ret > MOVE)
    events = A.intermediate_events(cdf, b["end_price"].to_numpy())
    events = events[mask[events["start"].to_numpy()]]
    alarm = float(np.mean(prev[ok] > 0.75))
    insurance = float(np.mean(prev[big] > 0.75)) if big.any() else np.nan
    return {
        "corr": float(np.corrcoef(x[ok], ret[ok])[0, 1]), "n_obs": int(ok.sum()),
        "insurance": insurance, "alarm_rate": alarm, "lift": insurance / alarm if alarm else np.nan,
        "big_moves": int(big.sum()),
        "true_positive_top": A.true_positive_rate(events, MOVE, 15),
        "true_positive_bottom": float((events.loc[events["bin"] <= 4, "max_abs_return"] > MOVE).mean()),
        "mean_stay_top": float(events.loc[events["bin"] >= 15, "buckets"].mean()),
        "mean_stay_bottom": float(events.loc[events["bin"] <= 4, "buckets"].mean()),
    }


def regression(b: pd.DataFrame, mask: np.ndarray, vpin_cols: list[str], n: int) -> list[dict]:
    """|r_tau| on standardized lagged ln VPIN, ln RV, |r_{tau-1}| and ln duration.

    Newey-West standard errors (n lags: VPIN windows overlap). Reports how much R^2
    VPIN adds over the volatility and intensity controls.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        controls = pd.DataFrame({
            "ln_rv": np.log(A.lagged(b["rv"].to_numpy())),
            "abs_ret_prev": A.lagged(b["ret"].to_numpy()),
            "ln_duration": np.log(A.lagged(b["duration"].to_numpy())),
        })
        vp = {c: np.log(A.lagged(b[c].to_numpy())) for c in vpin_cols}
    y = b["ret"].to_numpy()
    data = controls.assign(**vp, y=y)[mask]
    data = data.replace([np.inf, -np.inf], np.nan).dropna()
    z = (data - data.mean()) / data.std()
    out = []
    base = sm.OLS(z["y"], sm.add_constant(z[controls.columns])).fit()
    for c in vpin_cols:
        alone = sm.OLS(z["y"], sm.add_constant(z[[c]])).fit()
        full = sm.OLS(z["y"], sm.add_constant(z[list(controls.columns) + [c]])).fit(
            cov_type="HAC", cov_kwds={"maxlags": n})
        out.append({"signal": c, "n_obs": int(full.nobs), "r2_vpin_alone": alone.rsquared,
                    "r2_controls": base.rsquared, "r2_controls_plus_vpin": full.rsquared,
                    "delta_r2": full.rsquared - base.rsquared,
                    "beta_vpin": full.params[c], "t_vpin_hac": full.tvalues[c],
                    "beta_ln_rv": full.params["ln_rv"], "t_ln_rv_hac": full.tvalues["ln_rv"]})
    return out


# ---------- E2 + E3 on IVE ----------

def ive_experiments(out: Path, fig: Path, smoke: bool) -> dict:
    first = "2010-01-01" if smoke else CFG["ive"]["first_day"]
    last = "2012-12-31" if smoke else CFG["ive"]["last_day"]
    ticks = load_ive_ticks(first, last)
    bars = time_bars(ticks, 60)
    del ticks
    clock = {"ts": bars["ts"].to_numpy(), "minutes": trading_minutes(bars["ts"], 390)}
    split = pd.Timestamp(CFG["ive"]["out_of_sample_period"][0])
    grid = CFG["prediction"]["grid_fig14"]
    bpds = [10, 50] if smoke else grid["buckets_per_day"]
    lengths = [50, 250] if smoke else grid["sample_length"]
    rows, kept = [], {}
    for bpd in bpds:
        buckets = realtime_buckets(bars, bpd)
        for n in lengths:
            b = signals(buckets, n, clock)
            cdf = realtime_cdf(b["vpin"], min_history=60 * bpd)
            is_mask = (b["end_ts"] < split).to_numpy()
            for period, mask in [("in-sample", is_mask), ("out-of-sample", ~is_mask)]:
                rows.append({"buckets_per_day": bpd, "sample_length": n, "period": period,
                             "signal": "VPIN", **metrics(b, "vpin", cdf, mask)})
            kept[(bpd, n)] = (b, cdf)
        print(f"IVE real-time grid: {bpd} buckets/day done", flush=True)
    grid_df = pd.DataFrame(rows)
    grid_df.to_csv(out / "ive_realtime_grid.csv", index=False)

    # Parameters chosen the paper's way, on in-sample data only, then frozen.
    ins = grid_df[grid_df["period"] == "in-sample"]
    chosen = {
        "paper (50, 250)": (50, 250), "paper Table 5 (10, 350)": (10, 350),
        "best in-sample corr": tuple(ins.loc[ins["corr"].idxmax(), ["buckets_per_day", "sample_length"]].astype(int)),
        "best in-sample true positive": tuple(ins.loc[ins["true_positive_top"].idxmax(),
                                                      ["buckets_per_day", "sample_length"]].astype(int)),
    }
    comparison, regressions, yearly = [], [], []
    for label, key in chosen.items():
        if key not in kept:
            continue
        b, cdf_v = kept[key]
        cdf_rv = realtime_cdf(b["rv"], min_history=60 * key[0])
        is_mask = (b["end_ts"] < split).to_numpy()
        for period, mask in [("in-sample", is_mask), ("out-of-sample", ~is_mask)]:
            for signal, col, cdf in [("VPIN", "vpin", cdf_v), ("RV (trailing volatility)", "rv", cdf_rv)]:
                comparison.append({"choice": label, "buckets_per_day": key[0], "sample_length": key[1],
                                   "period": period, "signal": signal, **metrics(b, col, cdf, mask)})
            for r in regression(b, mask, ["vpin"], key[1]):
                regressions.append({"market": "IVE", "choice": label, "period": period, **r})
        if key == (50, 250):
            years = b["end_ts"].dt.year.to_numpy()
            for y in sorted(set(years)):
                m = years == y
                if m.sum() > 5000:
                    yearly.append({"year": int(y), **{f"vpin_{k}": v for k, v in metrics(b, "vpin", cdf_v, m).items()
                                                      if k in ("corr", "insurance", "alarm_rate", "lift")},
                                   **{f"rv_{k}": v for k, v in metrics(b, "rv", cdf_rv, m).items()
                                      if k in ("corr", "insurance", "alarm_rate", "lift")}})
    pd.DataFrame(comparison).to_csv(out / "ive_oos_comparison.csv", index=False)
    pd.DataFrame(yearly).to_csv(out / "ive_by_year.csv", index=False)
    P.yearly_bars(pd.DataFrame(yearly), fig / "e2_ive_by_year.png")

    # E4 for IVE: events after the paper, at the paper's flash-crash setting (50, 50)
    b50 = signals(realtime_buckets(bars, 50), 50, clock)
    events = crash_events(b50, bars, CFG_EVENTS_IVE, "IVE", fig)
    return {"chosen": {k: list(v) for k, v in chosen.items()}, "regressions": regressions, "events": events}


CFG_EVENTS_IVE = ["2011-08-08", "2015-08-24", "2018-02-05", "2020-03-16", "2024-08-05"]


def largest_drop(bars_day: pd.DataFrame, minutes: int = 60):
    """Start time and size of the day's largest price fall over `minutes` minutes."""
    ts, price = bars_day["ts"], bars_day["close"].to_numpy()
    # min over [t, t + minutes): a trailing window on the time-reversed series
    reversed_time = pd.Timestamp(0) + (ts.iloc[-1] - ts).to_numpy()[::-1]
    future_min = pd.Series(price[::-1], index=reversed_time).rolling(f"{minutes}min").min().to_numpy()[::-1]
    drop = future_min / price - 1
    i = int(np.argmin(drop))
    return ts.iloc[i], float(drop[i])


def crash_events(b: pd.DataFrame, bars: pd.DataFrame, days: list[str], market: str, fig: Path,
                 lookback: int = 50) -> list[dict]:
    """Was the real-time alarm CDF >= 0.9 on when the day's largest one-hour fall began,
    and for how long had it been on? Checked for CDF(VPIN), CDF(RV) and, for BTC,
    CDF(VPIN from true labels). `lookback` buckets (one day of volume) are shown."""
    cols = [c for c in ("vpin", "vpin_true", "rv") if c in b]
    alert = CFG["vpin"]["cdf_alert"]
    cdfs = {c: realtime_cdf(b[c], min_history=60 * 50) for c in cols}
    end_ts = b["end_ts"]
    rows, panels = [], []
    for day in days:
        bars_day = bars[bars["day"] == pd.Timestamp(day)]
        if bars_day.empty:
            continue
        t0, drop = largest_drop(bars_day)
        last = int(np.searchsorted(end_ts.to_numpy(), t0.to_datetime64(), side="right") - 1)
        row = {"market": market, "day": day, "drop_start": str(t0), "drop_1h": drop}
        for c in cols:
            cdf = cdfs[c]
            on = bool(np.isfinite(cdf[last]) and cdf[last] >= alert)
            run = last
            while on and run > 0 and np.isfinite(cdf[run - 1]) and cdf[run - 1] >= alert:
                run -= 1
            row[f"{c}_cdf_at_drop"] = float(cdf[last])
            row[f"{c}_alarm_share"] = float(np.mean(cdf[np.isfinite(cdf)] >= alert))  # base rate
            row[f"{c}_alarm_on"] = on
            row[f"{c}_alarm_hours_before"] = (t0 - end_ts.iloc[run]).total_seconds() / 3600 if on else 0.0
        rows.append(row)
        first = max(last - lookback, 0)
        show = slice(first, min(last + lookback // 4, len(b) - 1) + 1)
        price = bars[(bars["ts"] >= end_ts.iloc[first]) & (bars["ts"] <= end_ts.iloc[show.stop - 1])]
        panels.append({"title": f"{market} {day}", "t0": t0, "price": price,
                       "series": {c: (end_ts.iloc[show], cdfs[c][show]) for c in cols}})
    P.crash_panels(panels, fig / f"e4_crashes_{market.lower()}.png", alert)
    return rows


# ---------- E1 + E3 on BTC ----------

def btc_experiments(out: Path, fig: Path, smoke: bool) -> dict:
    cfg = CFG["btc"]
    first, last = ("2024-01", "2024-12") if smoke else (cfg["first_month"], cfg["last_month"])
    k = load_btc_klines(first, last)
    bars = pd.DataFrame({"ts": k["ts"], "open": k["open"], "close": k["close"],
                         "volume": k["volume"], "true_buy": k["taker_buy_volume"]})
    bars["day"] = bars["ts"].dt.normalize()
    clock = {"ts": bars["ts"].to_numpy(), "minutes": trading_minutes(bars["ts"], None)}

    # Bar level: BVC share of buys vs the true share, per year
    est = daily_estimates(bars, 50)
    sigma = est["sigma"].reindex(bars["day"]).to_numpy()
    f_bvc = norm.cdf(bar_log_changes(bars) / sigma)
    f_true = (bars["true_buy"] / bars["volume"]).to_numpy()
    year = bars["ts"].dt.year.to_numpy()
    bar_rows = []
    for y in sorted(set(year)):
        m = (year == y) & np.isfinite(f_bvc)
        if m.sum() < 1000:
            continue
        agree = np.sign(f_bvc[m] - 0.5) == np.sign(f_true[m] - 0.5)
        bar_rows.append({"year": int(y), "bars": int(m.sum()),
                         "corr_buy_share": float(np.corrcoef(f_bvc[m], f_true[m])[0, 1]),
                         "direction_agreement_volume_weighted": float(np.average(agree, weights=bars["volume"].to_numpy()[m])),
                         "mean_abs_bvc_imbalance": float(np.mean(np.abs(2 * f_bvc[m] - 1))),
                         "mean_abs_true_imbalance": float(np.mean(np.abs(2 * f_true[m] - 1)))})
    pd.DataFrame(bar_rows).to_csv(out / "btc_bars_bvc_vs_truth.csv", index=False)

    # Bucket level and VPIN: same buckets, two classifications
    res = {}
    comparison, regressions = [], []
    for bpd, n in [(50, 50), (50, 250)]:
        b = signals(realtime_buckets(bars, bpd, true_buy=bars["true_buy"].to_numpy()), n, clock)
        ok = b["vpin"].notna() & b["vpin_true"].notna()
        oi_bvc = (b["buy"] - b["sell"]).abs() / b["volume"]
        oi_true = (b["true_buy"] - b["true_sell"]).abs() / b["volume"]
        signed_bvc, signed_true = (b["buy"] - b["sell"]) / b["volume"], (b["true_buy"] - b["true_sell"]) / b["volume"]
        same_ret = b["ret"]  # |return| over the same bucket
        res[f"{bpd}_{n}"] = {
            "buckets": int(len(b)),
            "corr_signed_imbalance": float(signed_bvc.corr(signed_true)),
            "corr_abs_imbalance": float(oi_bvc.corr(oi_true)),
            "mean_abs_imbalance_bvc": float(oi_bvc.mean()), "mean_abs_imbalance_true": float(oi_true.mean()),
            "corr_abs_imbalance_with_same_bucket_abs_return_bvc": float(oi_bvc.corr(same_ret)),
            "corr_abs_imbalance_with_same_bucket_abs_return_true": float(oi_true.corr(same_ret)),
            "corr_vpin_bvc_true": float(b.loc[ok, "vpin"].corr(b.loc[ok, "vpin_true"])),
            "mean_vpin_bvc": float(b.loc[ok, "vpin"].mean()), "mean_vpin_true": float(b.loc[ok, "vpin_true"].mean()),
            "corr_vpin_bvc_rv": float(b.loc[ok, "vpin"].corr(b.loc[ok, "rv"])),
            "corr_vpin_true_rv": float(b.loc[ok, "vpin_true"].corr(b.loc[ok, "rv"])),
        }
        mask = np.ones(len(b), dtype=bool)
        for signal, col in [("VPIN (bulk classified)", "vpin"), ("VPIN (true labels)", "vpin_true"),
                            ("RV (trailing volatility)", "rv")]:
            cdf = realtime_cdf(b[col], min_history=60 * bpd)
            comparison.append({"buckets_per_day": bpd, "sample_length": n, "signal": signal,
                               **metrics(b, col, cdf, mask)})
        for r in regression(b, mask, ["vpin", "vpin_true"], n):
            regressions.append({"market": "BTC", "choice": f"({bpd}, {n})", "period": f"{first}..{last}", **r})
        if (bpd, n) == (50, 50):
            P.bvc_vs_truth(b, fig / "e1_btc_vpin_true_vs_bvc.png")
            events = crash_events(b, bars, cfg["crash_days"], "BTC", fig)
    pd.DataFrame(comparison).to_csv(out / "btc_signal_comparison.csv", index=False)

    # Trade level: tick rule vs truth, and bucket imbalance on the trade days
    trade_rows = []
    for day in ([] if smoke else cfg["trade_days"]):
        try:
            t = load_btc_trades(day)
        except FileNotFoundError:
            continue
        sign = tick_rule(t["price"].to_numpy())
        correct = (sign > 0) == t["true_buy"].to_numpy()
        trade_rows.append({"day": day, "trades": len(t),
                           "tick_rule_accuracy_trades": float(correct.mean()),
                           "tick_rule_accuracy_volume": float(np.average(correct, weights=t["size"]))} |
                          trade_day_buckets(t, sign, est, day))
    pd.DataFrame(trade_rows).to_csv(out / "btc_trade_days.csv", index=False)
    return {"buckets": res, "regressions": regressions, "events": events, "bars": bar_rows}


def trade_day_buckets(t: pd.DataFrame, sign: np.ndarray, est: pd.DataFrame, day: str) -> dict:
    """On one trade day: bucket imbalance from the truth, the tick rule and BVC (1 min, 10 s).

    Buckets are 1/250 of the trailing average daily volume, so a day has enough of them.
    """
    size = float(est.loc[pd.Timestamp(day), "bucket_volume"]) * 50 / 250
    sigma = float(est.loc[pd.Timestamp(day), "sigma"])
    vol = t["size"].to_numpy()
    trades = pd.DataFrame({"ts": t["ts"], "close": t["price"], "volume": vol})
    edges = np.arange(int(vol.sum() // size) + 1) * size
    from vpin.buckets import buckets_from_edges, fill_buckets
    truth = fill_buckets(vol, vol * t["true_buy"].to_numpy(), edges)
    tick = fill_buckets(vol, vol * (sign > 0), edges)
    out = {}
    for name, sec in [("bvc_1min", 60), ("bvc_10s", 10)]:
        tt = t.assign(day=t["ts"].dt.normalize())
        bars = time_bars(tt, sec)
        s = sigma * np.sqrt(sec / 60)   # scale the one-minute sigma to the bar length
        bvc = buckets_from_edges(bars, bars["volume"].to_numpy() * norm.cdf(bar_log_changes(bars) / s), edges)["buy"].to_numpy()
        out[f"corr_signed_imbalance_{name}"] = float(np.corrcoef(2 * bvc - size, 2 * truth - size)[0, 1])
    out["corr_signed_imbalance_tick_rule"] = float(np.corrcoef(2 * tick - size, 2 * truth - size)[0, 1])
    out["buckets"] = len(truth)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    started = time.perf_counter()
    tag = "extensions_smoke" if args.smoke else "extensions"
    out = ROOT / "results" / tag
    fig = out / "figures"
    fig.mkdir(parents=True, exist_ok=True)
    btc = btc_experiments(out, fig, args.smoke)
    print("BTC done", flush=True)
    ive = ive_experiments(out, fig, args.smoke)
    pd.DataFrame(btc["regressions"] + ive["regressions"]).to_csv(out / "regressions.csv", index=False)
    pd.DataFrame(btc["events"] + ive["events"]).to_csv(out / "crash_events.csv", index=False)
    summary = {"btc_buckets": btc["buckets"], "ive_chosen_parameters": ive["chosen"],
               "seconds": time.perf_counter() - started}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=float))
    print(json.dumps(summary, indent=1, default=float))


if __name__ == "__main__":
    main()
