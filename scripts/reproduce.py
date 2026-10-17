"""Reproduce the paper's exhibits on IVE ticks over the paper's sample period.

Settings follow the paper exactly (configs/pipeline.yaml, `vpin` and `prediction`):
one-minute bars, bulk volume classification with a full-sample sigma, V = ADV / 50,
n = 50, and a CDF built from the whole sample. Every number is written to
results/reproduction/ together with the paper's value (src/vpin/paper_numbers.py).

Usage: python scripts/reproduce.py            # full run (~2009-09 to 2011-08)
       python scripts/reproduce.py --smoke    # three months, small grids: a quick check
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from vpin import analysis as A
from vpin import paper_numbers as PN
from vpin import plots as P
from vpin import uncertainty as U
from vpin.bars import bar_price_changes, time_bars
from vpin.buckets import average_daily_volume, build_buckets
from vpin.classify import bvc_buy_fraction, lee_ready
from vpin.data import load_ive_ticks
from vpin.metric import cdf_full_sample, vpin, vpin_series

ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load(open(ROOT / "configs" / "pipeline.yaml"))
SESSION_MINUTES = 390
CRASH = ("2010-05-06 14:32", "2010-05-06 15:08")  # E-mini fell from 14:32 and recovered by ~15:08 ET


def write_json(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=float))


def bvc_buy_volume(bars: pd.DataFrame, sigma: float) -> np.ndarray:
    return bars["volume"].to_numpy() * bvc_buy_fraction(bar_price_changes(bars), sigma)


def with_vpin(bars, buy_volume, bucket_volume, n):
    """Buckets with VPIN and its full-sample CDF (the paper's convention)."""
    b = build_buckets(bars, buy_volume, bucket_volume)
    b["vpin"] = vpin(b["buy"], b["sell"], b["volume"], n)
    b["cdf"] = cdf_full_sample(b["vpin"].to_numpy())
    return b


def first_alert(day_buckets: pd.DataFrame, level: float):
    """Time on the day when CDF(VPIN) first reaches `level`, or None."""
    hit = day_buckets[day_buckets["cdf"] >= level]
    return None if hit.empty else hit["end_ts"].iloc[0]


def flash_crash(ticks, bars1, bars10, adv, out, fig):
    """Figure 4 (three classification schemes) and Figure 2 (time gap) on 6 May 2010."""
    n, bpd = CFG["vpin"]["sample_length"], CFG["vpin"]["buckets_per_day"]
    v_bucket = adv / bpd
    trades = pd.DataFrame({"ts": ticks["ts"], "close": ticks["price"], "volume": ticks["size"].astype(float)})
    lr_buy = trades["volume"].to_numpy() * (lee_ready(ticks["price"].to_numpy(), ticks["bid"].to_numpy(),
                                                       ticks["ask"].to_numpy()) > 0)
    schemes = {
        "BVC, 1-minute bars": with_vpin(bars1, bvc_buy_volume(bars1, np.nanstd(bar_price_changes(bars1))), v_bucket, n),
        "BVC, 10-second bars": with_vpin(bars10, bvc_buy_volume(bars10, np.nanstd(bar_price_changes(bars10))), v_bucket, n),
        "Lee-Ready, trade by trade": with_vpin(trades, lr_buy, v_bucket, n),
    }
    day = pd.Timestamp(CFG["ive"]["flash_crash_day"])
    price = bars1[bars1["day"] == day]
    panels, rows = [], []
    for name, b in schemes.items():
        d = b[b["end_ts"].dt.normalize() == day]
        alert = first_alert(d, CFG["vpin"]["cdf_alert"])
        lead = None if alert is None else (pd.Timestamp(CRASH[0]) - alert).total_seconds() / 3600
        after = d[d["end_ts"] >= pd.Timestamp(CRASH[1])]
        rows.append({"scheme": name, "mean_vpin_sample": b["vpin"].mean(), "max_vpin_day": d["vpin"].max(),
                     "max_cdf_day": d["cdf"].max(), "first_cdf_0.9": None if alert is None else str(alert),
                     "lead_hours_before_14:32": lead,
                     "mean_cdf_after_crash": after["cdf"].mean() if len(after) else np.nan})
        panels.append({"title": name, "buckets": d, "price": price})
    pd.DataFrame(rows).to_csv(out / "flash_crash.csv", index=False)
    P.day_vpin(panels, CRASH, fig / "fig4_flash_crash.png", CFG["vpin"]["cdf_alert"])
    # Figure 2: clock time behind each VPIN value (first to last of its n buckets)
    b = schemes["BVC, 1-minute bars"]
    b["gap_hours"] = (b["end_ts"] - b["start_ts"].shift(n - 1)).dt.total_seconds() / 3600
    d = b[b["end_ts"].dt.normalize() == day]
    P.time_gap(d, fig / "fig2_time_gap.png", "VPIN updates speed up on 6 May 2010")
    gap = {"buckets_on_day": len(d), "gap_hours_first": d["gap_hours"].iloc[0], "gap_hours_min": d["gap_hours"].min()}
    return rows, gap


def stability(bars1, buy_volume, v_bucket, n, shifts, fig):
    """Figure 5: start the bucket sequence 0..shifts-1 bars later and compare trajectories."""
    ts = bars1["ts"].to_numpy()
    common = np.arange(shifts, len(bars1))           # bars where every trajectory exists
    total = np.zeros(len(common))
    total_sq = np.zeros(len(common))
    base = None
    for k in range(shifts):
        sub = bars1.iloc[k:]
        b = build_buckets(sub, buy_volume[k:], v_bucket)
        v = vpin(b["buy"], b["sell"], b["volume"], n)
        end_bar = np.searchsorted(ts, b["end_ts"].to_numpy())  # bar index completing each bucket
        # VPIN in force at each bar = last VPIN computed at or before that bar
        pos = np.searchsorted(end_bar, common, side="right") - 1
        at_bar = np.where(pos >= 0, v[np.maximum(pos, 0)], np.nan)
        if base is None:
            base = at_bar
        diff = at_bar - base
        total += np.nan_to_num(diff)
        total_sq += np.nan_to_num(diff) ** 2
    mean = total / shifts
    std = np.sqrt(np.maximum(total_sq / shifts - mean ** 2, 0))
    ok = np.isfinite(base)
    P.stability(bars1["ts"].iloc[common[ok]], mean[ok], std[ok], fig / "fig5_stability.png")
    return {"shifts": shifts, "mean_cross_sectional_std": float(std[ok].mean()),
            "max_cross_sectional_std": float(std[ok].max()), "mean_vpin": float(np.nanmean(base)),
            "std_over_mean": float(std[ok].mean() / np.nanmean(base))}


def prediction(bars1, buy_volume, adv, grids, out, fig, reps):
    """Section 5: correlation surface, conditional tables, insurance value, Table 5."""
    move, width = CFG["prediction"]["big_move"], CFG["prediction"]["return_bin"]
    cache, rows = {}, []
    wanted = {(b, s) for g in grids.values() for b in g["buckets_per_day"] for s in g["sample_length"]}
    wanted |= {tuple(CFG["prediction"]["preferred"]), tuple(CFG["prediction"]["best_table5"])}
    for bpd in sorted({b for b, _ in wanted}):
        buckets = build_buckets(bars1, buy_volume, adv / bpd)
        ret = A.next_abs_return(buckets["end_price"].to_numpy())
        for n in sorted(s for b, s in wanted if b == bpd):
            v = vpin(buckets["buy"], buckets["sell"], buckets["volume"], n)
            cdf = cdf_full_sample(v)
            corr, n_obs = A.vpin_return_correlation(v, ret)
            row = {"buckets_per_day": bpd, "sample_length": n, "corr": corr, "n_obs": n_obs,
                   "insurance": A.insurance_value(A.lagged(cdf), ret, move)}
            if bpd in grids["fig14"]["buckets_per_day"] and n in grids["fig14"]["sample_length"] \
                    or (bpd, n) in {tuple(CFG["prediction"]["preferred"]), tuple(CFG["prediction"]["best_table5"])}:
                events = A.intermediate_events(cdf, buckets["end_price"].to_numpy())
                row["true_positive"] = A.true_positive_rate(events, move)
                row["top_quartile_stays"] = int((events["bin"] >= 15).sum())
                cache[(bpd, n)] = (buckets, v, cdf, ret, events)
            rows.append(row)
    surface = pd.DataFrame(rows)
    surface.to_csv(out / "parameter_grid.csv", index=False)

    def grid_view(key, col):
        g = grids[key]
        sel = surface[surface["buckets_per_day"].isin(g["buckets_per_day"]) & surface["sample_length"].isin(g["sample_length"])]
        return sel.pivot(index="sample_length", columns="buckets_per_day", values=col)

    pref, best = tuple(CFG["prediction"]["preferred"]), tuple(CFG["prediction"]["best_table5"])
    P.heatmap(grid_view("fig10", "corr"), "Corr(ln VPIN, next |return|) — Figure 10", fig / "fig10_correlation.png", mark=pref)
    P.heatmap(grid_view("fig12", "insurance"), "P(CDF(VPIN) > 0.75 | |return| > 0.75%) — Figure 12",
              fig / "fig12_insurance.png", fmt="{:.0%}", vmin=0, vmax=1, mark=pref)
    P.heatmap(grid_view("fig14", "true_positive"), "P(max move > 0.75% while VPIN in top quartile) — Figure 14",
              fig / "fig14_true_positive.png", fmt="{:.0%}", vmin=0, vmax=1, mark=best)

    buckets, v, cdf, ret, events = cache[pref]
    # Robustness (DEVIATIONS.md, row 2): drop buckets whose return spans the overnight close
    day = buckets["end_ts"].dt.normalize().to_numpy()
    spans_close = np.concatenate([[True], day[1:] != day[:-1]])
    corr_intraday, _ = A.vpin_return_correlation(v, np.where(spans_close, np.nan, ret))
    t4a, t4b = A.conditional_tables(A.lagged(cdf), ret, width)
    t4a.to_csv(out / "table4a.csv")
    t4b.to_csv(out / "table4b.csv")
    P.table_heatmaps(t4a, np.array(PN.TABLE4A), "Table 4a: P(next |return| bin | VPIN 5%-tile), (50, 250)",
                     fig / "table4a_conditional.png")
    signed = np.concatenate([[np.nan], buckets["end_price"].to_numpy()[1:] / buckets["end_price"].to_numpy()[:-1] - 1])
    P.scatter_next_return(np.log(A.lagged(v)), signed, fig / "fig11_scatter.png", "Return over the next bucket vs ln VPIN (50, 250)")
    bottom = t4a.iloc[:5, 0].mean()  # share of next |return| < 0.25% when VPIN is in its bottom quartile
    big = np.isfinite(ret) & (ret > move) & np.isfinite(A.lagged(cdf))
    _, _, cdf_b, _, events_b = cache[best]
    t5 = A.event_table(events_b, width)
    t5.to_csv(out / "table5.csv")
    P.table_heatmaps(t5, np.array(PN.TABLE5), "Table 5: largest move while VPIN stays in a 5%-tile, (10, 350)",
                     fig / "table5_events.png")
    # ± by month-block bootstrap (vpin.uncertainty), and the iid Fisher interval the paper uses
    unc = {}
    for key in (pref, best):
        kb, kv, kcdf, kret, _ = cache[key]
        unc[f"{key[0]}_{key[1]}"] = U.section5(kv, kcdf, kret, kb["end_price"].to_numpy(), kb["end_ts"], reps=reps)
    r, n_obs = A.vpin_return_correlation(v, ret)
    half = 1.96 / np.sqrt(n_obs - 3)
    fisher_ci = [float(np.tanh(np.arctanh(r) - half)), float(np.tanh(np.arctanh(r) + half))]
    at = lambda key: surface[(surface["buckets_per_day"] == key[0]) & (surface["sample_length"] == key[1])].iloc[0]
    fig14 = grid_view("fig14", "true_positive")
    fig12 = grid_view("fig12", "insurance")
    return {
        "corr_50_250": at(pref)["corr"], "n_obs_50_250": int(at(pref)["n_obs"]),
        "corr_50_250_intraday": corr_intraday, "share_buckets_spanning_close": float(spans_close.mean()),
        "corr_max": surface["corr"].max(),
        "corr_argmax": surface.loc[surface["corr"].idxmax(), ["buckets_per_day", "sample_length"]].tolist(),
        "bottom_quartile_small_move": bottom,
        "insurance_50_250": at(pref)["insurance"], "big_moves_50_250": int(big.sum()),
        "insurance_fig12_median": float(np.nanmedian(fig12.to_numpy())),
        "true_positive_50_250": at(pref)["true_positive"], "true_positive_10_350": at(best)["true_positive"],
        "true_positive_fig14_max": float(np.nanmax(fig14.to_numpy())),
        "true_positive_fig14_argmax": [int(c) for c in np.unravel_index(np.nanargmax(fig14.to_numpy()), fig14.shape)[::-1]],
        "top_quartile_stays_10_350": int(at(best)["top_quartile_stays"]),
        "uncertainty": unc, "corr_50_250_fisher_ci_iid": fisher_ci,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    started = time.perf_counter()
    period = ["2010-04-01", "2010-06-30"] if args.smoke else CFG["ive"]["reproduction_period"]
    tag = "smoke" if args.smoke else "reproduction"
    out, fig = ROOT / "results" / tag, ROOT / "results" / tag / "figures"
    out.mkdir(parents=True, exist_ok=True)
    n, bpd = CFG["vpin"]["sample_length"], CFG["vpin"]["buckets_per_day"]

    ticks = load_ive_ticks(*period)
    bars1, bars10 = time_bars(ticks, 60), time_bars(ticks, 10)
    adv = average_daily_volume(bars1)
    sigma = float(np.nanstd(bar_price_changes(bars1)))
    buy1 = bvc_buy_volume(bars1, sigma)
    summary = {"period": period, "days": int(bars1["day"].nunique()), "ticks": len(ticks),
               "one_minute_bars": len(bars1), "adv_shares": adv, "bucket_volume_50": adv / bpd,
               "sigma_dollars_1min": sigma,
               "share_bars_no_price_change": float(np.mean(bar_price_changes(bars1) == 0))}

    base = with_vpin(bars1, buy1, adv / bpd, n)
    base[["end_ts", "end_price", "buy", "sell", "vpin", "cdf"]].to_csv(
        out / "vpin_50_50.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})  # same bytes every run
    summary["table2"] = {"ours": A.vpin_summary(base["vpin"].to_numpy()), "paper": PN.TABLE2_SP500}
    crash = pd.Timestamp(CFG["ive"]["flash_crash_day"])
    t3 = pd.DataFrame({"before": A.vpin_quantiles(base.loc[base["end_ts"] < crash, "vpin"].to_numpy()),
                       "after": A.vpin_quantiles(base.loc[base["end_ts"] >= crash, "vpin"].to_numpy()),
                       "total": A.vpin_quantiles(base["vpin"].to_numpy())})
    t3.to_csv(out / "table3.csv")
    events = {"Flash crash": "2010-05-06", "Fukushima": "2011-03-14", "US downgrade": "2011-08-08"}
    P.vpin_history(base, fig / "fig6_vpin_history.png", "IVE: VPIN (50 buckets/day, n = 50) and price",
                   {k: d for k, d in events.items() if period[0] <= d <= period[1]})

    P.volume_profile(bars1, fig / "fig1_volume_profile.png")
    # Table 1 as the paper defines it, then two robustness views (DEVIATIONS.md, row 8):
    # without the flash-crash day, and without it and without overnight changes.
    no_crash = bars1[bars1["day"] != pd.Timestamp(CFG["ive"]["flash_crash_day"])].reset_index(drop=True)
    for draws in (50, 100):
        A.sampling_table(bars1, draws, SESSION_MINUTES).to_csv(out / f"table1_{draws}.csv")
        A.sampling_table(no_crash, draws, SESSION_MINUTES).to_csv(out / f"table1_{draws}_no_crash_day.csv")
        A.sampling_table(no_crash, draws, SESSION_MINUTES, intraday_only=True).to_csv(
            out / f"table1_{draws}_no_crash_day_intraday.csv")
        U.table1(no_crash, draws, SESSION_MINUTES, reps=50 if args.smoke else U.REPS).to_csv(
            out / f"table1_{draws}_bootstrap.csv")
    P.sampling_histograms(A.sample_by_clock(no_crash, 50, SESSION_MINUTES), A.sample_by_volume(no_crash, 50),
                          fig / "fig3_sampling.png")

    if period[0] <= CFG["ive"]["flash_crash_day"] <= period[1]:
        summary["flash_crash"], summary["time_gap"] = flash_crash(ticks, bars1, bars10, adv, out, fig)
    summary["stability"] = stability(bars1, buy1, adv / bpd, n, 50 if args.smoke else 1000, fig)
    grids = CFG["prediction"]
    if args.smoke:
        grids = {k: {"buckets_per_day": [10, 50], "sample_length": [50, 250]} for k in ("grid_fig10", "grid_fig12", "grid_fig14")}
    grids = {k.replace("grid_", ""): v for k, v in grids.items() if k.startswith("grid_")}
    summary["prediction"] = prediction(bars1, buy1, adv, grids, out, fig, 50 if args.smoke else U.REPS)
    summary["seconds"] = time.perf_counter() - started
    write_json(summary, out / "summary.json")
    print(json.dumps(summary, indent=1, default=float)[:3000])


if __name__ == "__main__":
    main()
