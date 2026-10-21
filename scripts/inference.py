"""Inference package (docs/preregistration.md, section 2).

I2 placebo: VPIN with the direction of every one-minute imbalance drawn at random (its size
   kept). If it predicts the next |return| about as well as the real VPIN, the direction of
   trading, the thing that is supposed to reveal informed traders, carries little of
   VPIN's predictive power.
I3 leave-one-year-out stability of corr(ln signal, next |return|) and lift.
I4 power: the smallest correlation our reproduction could detect.
I1 ledger: every test behind a claim, with Bonferroni, Benjamini-Hochberg and
   Harvey-Liu-Zhu (|t| > 3) flags over the family of "test" rows.

Usage: python scripts/inference.py   (after reproduce.py, extensions.py, simulation.py, local_sigma.py)
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from vpin import analysis as A
from vpin import uncertainty as U
from vpin.bars import bar_log_changes, bar_price_changes, time_bars
from vpin.buckets import average_daily_volume, bucket_edges_daily, build_buckets, buckets_from_edges
from vpin.classify import bvc_buy_fraction
from vpin.data import load_btc_klines, load_ive_ticks
from vpin.metric import cdf_full_sample, vpin
from vpin.realtime import daily_estimates, realtime_cdf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "extensions" / "inference"
MOVE = 0.0075
SEEDS = range(20)
OOS_START = pd.Timestamp("2011-08-16")


# ---------- shared pieces ----------

def corr_and_lift(signal, cdf, ret, mask) -> tuple[float, float]:
    """corr(ln signal_{tau-1}, |r_tau|) and lift, without bootstrap (used many times)."""
    with np.errstate(divide="ignore"):
        x = np.log(A.lagged(signal))
    prev = A.lagged(cdf)
    ok = mask & np.isfinite(x) & np.isfinite(ret) & np.isfinite(prev)
    big = ok & (ret > MOVE)
    insurance, alarm = np.mean(prev[big] > 0.75), np.mean(prev[ok] > 0.75)
    return float(np.corrcoef(x[ok], ret[ok])[0, 1]), float(insurance / alarm)


def placebo_buy(volume, fraction, seed) -> np.ndarray:
    """Keep the size of each bar's imbalance |f - 0.5|, draw its direction at random."""
    sign = np.random.default_rng(seed).choice([-1.0, 1.0], size=len(volume))
    return volume * (0.5 + sign * np.abs(fraction - 0.5))


def realtime_setup(bars, bpd):
    """Real-time edges and BVC fractions (trailing 250-day sigma), as in extensions.py."""
    est = daily_estimates(bars, bpd)
    sigma = est["sigma"].reindex(bars["day"]).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        f = norm.cdf(bar_log_changes(bars) / sigma)
    f = np.where(np.isfinite(f), f, 0.5)            # burn-in days without a sigma: no buckets anyway
    edges = bucket_edges_daily(est["volume"].to_numpy(), est["bucket_volume"].to_numpy())
    return edges, f


def series(bars, buy, edges, n):
    b = buckets_from_edges(bars, buy, edges)
    return vpin(b["buy"], b["sell"], b["volume"], n), b


# ---------- I2 placebo and I3 leave-one-year-out ----------

def placebo_and_loyo():
    rows, loyo = [], []
    # (a) IVE 2009-2011, the paper's in-sample method at (50, 250)
    ticks = load_ive_ticks("2009-09-28", "2026-09-30")
    ive = time_bars(ticks, 60)
    del ticks
    ins = ive[ive["ts"] < OOS_START].reset_index(drop=True)
    change = bar_price_changes(ins)
    f = bvc_buy_fraction(change, np.nanstd(change))
    v_bucket = average_daily_volume(ins) / 50
    vol = ins["volume"].to_numpy(dtype=float)

    def paper_stats(buy):
        b = build_buckets(ins, buy, v_bucket)
        v = vpin(b["buy"], b["sell"], b["volume"], 250)
        ret = A.next_abs_return(b["end_price"].to_numpy())
        return corr_and_lift(v, cdf_full_sample(v), ret, np.ones(len(v), bool))

    rows.append({"sample": "IVE 2009-11, paper's method (50, 250)", "seed": "real", **dict(zip(["corr", "lift"], paper_stats(vol * f)))})
    rows += [{"sample": "IVE 2009-11, paper's method (50, 250)", "seed": s, **dict(zip(["corr", "lift"], paper_stats(placebo_buy(vol, f, s))))} for s in SEEDS]

    # (b) IVE 2011-2026, real-time (50, 250); (c) BTC 2020-2026, real-time (50, 50)
    k = load_btc_klines("2020-01", "2026-09")
    btc = pd.DataFrame({"ts": k["ts"], "open": k["open"], "close": k["close"], "volume": k["volume"]})
    btc["day"] = btc["ts"].dt.normalize()
    for label, bars, n, mask_fn, true_buy in [
        ("IVE 2011-26, real-time (50, 250)", ive, 250, lambda b: (b["end_ts"] >= OOS_START).to_numpy(), None),
        ("BTC 2020-26, real-time (50, 50)", btc, 50, lambda b: np.ones(len(b), bool), k["taker_buy_volume"].to_numpy()),
    ]:
        edges, f = realtime_setup(bars, 50)
        vol = bars["volume"].to_numpy(dtype=float)
        v, b = series(bars, vol * f, edges, n)
        ret = A.next_abs_return(b["end_price"].to_numpy())
        mask = mask_fn(b)
        cdf = realtime_cdf(v, 60 * 50)
        rows.append({"sample": label, "seed": "real", **dict(zip(["corr", "lift"], corr_and_lift(v, cdf, ret, mask)))})
        for s in SEEDS:
            vp, _ = series(bars, placebo_buy(vol, f, s), edges, n)
            rows.append({"sample": label, "seed": s, **dict(zip(["corr", "lift"], corr_and_lift(vp, realtime_cdf(vp, 60 * 50), ret, mask)))})
        # I3: leave one calendar year out, for every signal of this sample
        signals = {"VPIN": (v, cdf), "trailing volatility": None}
        rv = pd.Series(ret).rolling(n).mean().to_numpy()
        signals["trailing volatility"] = (rv, realtime_cdf(rv, 60 * 50))
        if true_buy is not None:
            vt, _ = series(bars, np.asarray(true_buy, float), edges, n)
            signals["VPIN, true labels"] = (vt, realtime_cdf(vt, 60 * 50))
        years = b["end_ts"].dt.year.to_numpy()
        for name, (sig, c) in signals.items():
            for y in sorted(set(years[mask])):
                corr, lift = corr_and_lift(sig, c, ret, mask & (years != y))
                loyo.append({"sample": label, "signal": name, "left_out": int(y), "corr": corr, "lift": lift})
            corr, lift = corr_and_lift(sig, c, ret, mask)
            loyo.append({"sample": label, "signal": name, "left_out": "none", "corr": corr, "lift": lift})
        if label.startswith("BTC"):
            paired = btc_paired_tests(b, v, signals["VPIN, true labels"][0], rv, ret, true_buy, bars, edges)
        else:
            paired_ive = U.bootstrap(*paired_corr_sums(b["end_ts"], mask, ret, {"rv": rv, "vpin": v}),
                                     reps=U.REPS)
    return pd.DataFrame(rows), pd.DataFrame(loyo), paired, paired_ive


def paired_corr_sums(ts, mask, ret, sig: dict):
    """Month sums for corr(ln a_{tau-1}, r) - corr(ln b_{tau-1}, r), same buckets for both."""
    with np.errstate(divide="ignore"):
        xa, xb = (np.log(A.lagged(s)) for s in sig.values())
    ok = mask & np.isfinite(xa) & np.isfinite(xb) & np.isfinite(ret)
    months = U.month_ids(ts)
    za, zb, zy = (np.where(ok, z, 0.0) for z in (xa, xb, ret))
    cols = [c * ok for c in U.corr_columns(za, zy)] + [c * ok for c in U.corr_columns(zb, zy)]
    sums = U.monthly_sums(months, cols, months.max() + 1)
    return sums, {"difference": lambda t: U.corr_from_sums(t[0:6]) - U.corr_from_sums(t[6:12])}


def btc_paired_tests(b, v, vt, rv, ret, true_buy, bars, edges):
    """Extensions 1-2 as paired month-block tests on the same buckets."""
    mask = np.ones(len(b), bool)
    out = {"corr_vpin_bvc_minus_true": U.bootstrap(*paired_corr_sums(b["end_ts"], mask, ret, {"a": v, "b": vt}))["difference"],
           "corr_rv_minus_vpin_bvc": U.bootstrap(*paired_corr_sums(b["end_ts"], mask, ret, {"a": rv, "b": v}))["difference"]}
    t = buckets_from_edges(bars, np.asarray(true_buy, float), edges)
    oi_bvc = np.abs(b["buy"] - b["sell"]).to_numpy() / b["volume"].to_numpy()
    oi_true = np.abs(t["buy"] - t["sell"]).to_numpy() / t["volume"].to_numpy()
    ok = np.isfinite(ret)
    months = U.month_ids(b["end_ts"][ok])
    cols = U.corr_columns(oi_bvc[ok], ret[ok]) + U.corr_columns(oi_true[ok], ret[ok]) + [oi_bvc[ok], oi_true[ok]]
    res = U.bootstrap(U.monthly_sums(months, cols, months.max() + 1), {
        "same_bucket": lambda t: U.corr_from_sums(t[0:6]) - U.corr_from_sums(t[6:12]),
        "inflation": lambda t: t[12] / t[13]})
    out["corr_imbalance_same_return_bvc_minus_true"] = res["same_bucket"]
    out["imbalance_inflation"] = res["inflation"]
    return out


# ---------- I1 ledger ----------

def ledger(placebo, paired, paired_ive) -> pd.DataFrame:
    rep = json.loads((ROOT / "results/reproduction/summary.json").read_text())["prediction"]["uncertainty"]
    oos = pd.read_csv(ROOT / "results/extensions/ive_oos_comparison.csv")
    reg = pd.read_csv(ROOT / "results/extensions/regressions.csv")
    bars = pd.read_csv(ROOT / "results/extensions/btc_bars_bvc_vs_truth.csv")
    sim = pd.read_csv(ROOT / "results/extensions/simulation/per_replication_main.csv")
    rows = []

    def add(area, claim, est, se, null=0.0, role="test", note="", direction="+"):
        """direction "+": the claim says estimate > null; "≠": a test of equality (e.g. the paper's value)."""
        rows.append({"area": area, "claim": claim, "estimate": est, "null": null, "se": se,
                     "z": (est - null) / se if se and se > 0 else np.nan, "direction": direction,
                     "role": role, "note": note})

    u, u10 = rep["50_250"], rep["10_350"]
    add("Reproduction IVE", "corr(ln VPIN, next |r|) > 0 at (50, 250)", u["corr"]["value"], u["corr"]["se"])
    add("Reproduction IVE", "corr at (50, 250) equals the paper's 0.40", u["corr"]["value"], u["corr"]["se"], null=0.40, direction="≠")
    add("Reproduction IVE", "lift > 1 at (50, 250)", u["lift"]["value"], u["lift"]["se"], null=1.0)
    add("Reproduction IVE", "low VPIN → next |r| < 0.25% more than 90% of the time", u["bottom_small"]["value"], u["bottom_small"]["se"], null=0.90)
    add("Reproduction IVE", "true positives top − bottom quartile > 0 at (50, 250)", u["tp_diff"]["value"], u["tp_diff"]["se"])
    add("Reproduction IVE", "true positives top − bottom quartile > 0 at (10, 350)", u10["tp_diff"]["value"], u10["tp_diff"]["se"])
    pooled = bars[bars["year"].astype(str) == "all"].iloc[0]
    add("Ext. 1 BTC", "BVC gets the bar's direction right more than half the time",
        pooled["direction_agreement_volume_weighted"], pooled["direction_agreement_se"], null=0.5)
    add("Ext. 1 BTC", "BVC inflates bucket imbalance (ratio > 1)", paired["imbalance_inflation"]["value"], paired["imbalance_inflation"]["se"], null=1.0)
    add("Ext. 1 BTC", "BVC imbalance follows the same bucket's |r| more than the true one", paired["corr_imbalance_same_return_bvc_minus_true"]["value"], paired["corr_imbalance_same_return_bvc_minus_true"]["se"])
    add("Ext. 2 BTC", "BVC VPIN predicts next |r| better than true-label VPIN", paired["corr_vpin_bvc_minus_true"]["value"], paired["corr_vpin_bvc_minus_true"]["se"])
    add("Ext. 2 BTC", "trailing volatility predicts next |r| better than BVC VPIN", paired["corr_rv_minus_vpin_bvc"]["value"], paired["corr_rv_minus_vpin_bvc"]["se"])
    for _, r in reg.iterrows():
        if (r["market"], r["choice"]) in {("BTC", "(50, 50)"), ("IVE", "paper (50, 250)")} and not (r["market"] == "IVE" and r["period"] == "in-sample"):
            rows.append({"area": "Ext. 2 regression", "claim": f"{r['market']} {r['choice']} {r['period']}: {r['signal']} adds to volatility controls (Newey–West t)",
                         "estimate": r["beta_vpin"], "null": 0.0, "se": np.nan, "z": r["t_vpin_hac"], "direction": "+", "role": "test", "note": "z is the Newey–West t"})
    o = oos[(oos["choice"] == "paper (50, 250)") & (oos["period"] == "out-of-sample") & (oos["signal"] == "VPIN")].iloc[0]
    add("Out of sample IVE 2011-26", "VPIN corr with next |r| > 0", o["corr"], o["corr_se"])
    add("Out of sample IVE 2011-26", "VPIN lift > 1", o["lift"], o["lift_se"], null=1.0)
    add("Out of sample IVE 2011-26", "VPIN true positives top − bottom > 0", o["true_positive_diff"], o["true_positive_diff_se"])
    add("Out of sample IVE 2011-26", "trailing volatility predicts next |r| better than VPIN", paired_ive["difference"]["value"], paired_ive["difference"]["se"])
    ev = pd.read_csv(ROOT / "results/extensions/crash_events.csv")
    ive_ev = ev[ev["market"] == "IVE"]
    only_v = int((ive_ev["vpin_alarm_on"].astype(bool) & ~ive_ev["rv_alarm_on"].astype(bool)).sum())
    only_r = int((~ive_ev["vpin_alarm_on"].astype(bool) & ive_ev["rv_alarm_on"].astype(bool)).sum())
    from scipy.stats import binom
    p = float(binom.sf(only_v - 1, only_v + only_r, 0.5)) if only_v + only_r else 1.0
    rows.append({"area": "Crashes", "claim": "VPIN alarm beats the volatility alarm on the same IVE falls (exact McNemar)",
                 "estimate": only_v - only_r, "null": 0.0, "se": np.nan, "z": float(norm.isf(p)), "direction": "+", "role": "test",
                 "note": f"one-sided p = {p:.3f}; z = normal quantile of p"})
    for name, metric, world in [("D2: paper VPIN raises false alarms in volatile blocks", "M2_false_alarm", "V"),
                                ("D3: paper VPIN predicts next |r| where informed trading never changes", "M4_predictive_corr", "V")]:
        x = sim[(sim["world"] == world) & (sim["version"] == "paper")][metric]
        add("Ext. 3 simulation", name, x.mean(), x.std(ddof=1) / np.sqrt(len(x)), note="Monte Carlo s.e.")
    a = sim[(sim["world"] == "V") & (sim["version"] == "paper")].set_index("rep")["M2_false_alarm"]
    b = sim[(sim["world"] == "V") & (sim["version"] == "local")].set_index("rep")["M2_false_alarm"]
    d = (a - b).dropna()
    add("Ext. 3 simulation", "D4: local-sigma fix has fewer false alarms than the paper's VPIN", d.mean(), d.std(ddof=1) / np.sqrt(len(d)), note="paired over replications")
    tracking_path = ROOT / "results/extensions/local_sigma/tracking.json"
    if tracking_path.exists():
        t = json.loads(tracking_path.read_text())["BTC_50_50"]["difference"]
        add("Ext. 4 fix (D5)", "local-sigma VPIN tracks true-label VPIN better than standard BVC (BTC)", t["value"], t["se"])
    for sample, g in placebo.groupby("sample", sort=False):
        real = g[g["seed"] == "real"]["corr"].iloc[0]
        fake = g[g["seed"] != "real"]["corr"].astype(float)
        add("Placebo", f"{sample}: real VPIN predicts better than direction-shuffled VPIN", real - fake.mean(), fake.std(ddof=1),
            note="se = spread of the 20 placebo draws")
    led = pd.DataFrame(rows)
    led["p_two_sided"] = 2 * norm.sf(np.abs(led["z"]))
    fam = led["role"] == "test"
    m = int(fam.sum())
    led["bonferroni"] = fam & (led["p_two_sided"] < 0.05 / m)
    order = led.loc[fam, "p_two_sided"].sort_values()
    thresh = 0.05 * np.arange(1, m + 1) / m
    passed = order.to_numpy() <= thresh
    k = np.max(np.nonzero(passed)[0]) + 1 if passed.any() else 0
    led["bh_q05"] = False
    led.loc[order.index[:k], "bh_q05"] = True
    led["hlz_abs_t_gt_3"] = fam & (led["z"].abs() > 3)
    # A claim is supported only if it is significant AND the estimate lies on the claimed side.
    right_side = (led["direction"] == "≠") | (led["z"] > 0)
    led["supported_bh"] = led["bh_q05"] & right_side
    led["supported_bonferroni"] = led["bonferroni"] & right_side
    return led


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    placebo, loyo, paired, paired_ive = placebo_and_loyo()
    placebo.to_csv(OUT / "placebo.csv", index=False)
    loyo.to_csv(OUT / "leave_one_year_out.csv", index=False)
    rep_se = json.loads((ROOT / "results/reproduction/summary.json").read_text())["prediction"]["uncertainty"]["50_250"]["corr"]["se"]
    led = ledger(placebo, paired, paired_ive)
    led.to_csv(ROOT / "results" / "report" / "ledger.csv", index=False)
    summary = {
        "power": {"corr_se_50_250": rep_se, "mde_80pct_power": (1.96 + 0.84) * rep_se},
        "placebo": {s: {"real_corr": float(g[g["seed"] == "real"]["corr"].iloc[0]),
                        "placebo_corr_mean": float(g[g["seed"] != "real"]["corr"].astype(float).mean()),
                        "placebo_corr_sd": float(g[g["seed"] != "real"]["corr"].astype(float).std(ddof=1)),
                        "real_lift": float(g[g["seed"] == "real"]["lift"].iloc[0]),
                        "placebo_lift_mean": float(g[g["seed"] != "real"]["lift"].astype(float).mean())}
                    for s, g in placebo.groupby("sample", sort=False)},
        "loyo": {f"{s} | {sig}": {"corr_min": float(g[g['left_out'] != 'none']["corr"].min()),
                                  "corr_max": float(g[g['left_out'] != 'none']["corr"].max()),
                                  "sign_flips": int((np.sign(g[g['left_out'] != 'none']["corr"]) != np.sign(g[g['left_out'] == 'none']["corr"].iloc[0])).sum()),
                                  "years": int((g['left_out'] != 'none').sum())}
                 for (s, sig), g in loyo.groupby(["sample", "signal"], sort=False)},
        "ledger": {"tests": int((led["role"] == "test").sum()), "abs_z_gt_1_96": int((led["z"].abs() > 1.96).sum()),
                   "bonferroni": int(led["bonferroni"].sum()), "bh_q05": int(led["bh_q05"].sum()),
                   "hlz": int(led["hlz_abs_t_gt_3"].sum()), "supported_bh": int(led["supported_bh"].sum()),
                   "supported_bonferroni": int(led["supported_bonferroni"].sum()),
                   "significant_wrong_side": int((led["bh_q05"] & ~led["supported_bh"]).sum())},
    }
    for s, v in summary["placebo"].items():
        v["placebo_share_of_real_corr"] = v["placebo_corr_mean"] / v["real_corr"] if v["real_corr"] else np.nan
        v["direction_carries_little"] = bool(v["placebo_share_of_real_corr"] >= 0.8)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=float))
    print(json.dumps(summary, indent=1, default=float))
    pd.set_option("display.width", 220)
    print(led[["area", "claim", "z", "direction", "bh_q05", "supported_bh", "supported_bonferroni"]].round(2).to_string(index=False))


if __name__ == "__main__":
    main()
