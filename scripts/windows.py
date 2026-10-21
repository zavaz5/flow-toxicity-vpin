"""The paper's exact in-sample method on every two-year window (docs/preregistration.md, section 3).

Question: do the paper's predictive numbers appear anywhere in our data? Every window
that starts on 1 January or 1 July is reported, none is selected. This analysis was run
once as an exploration before the pre-registration was written, and is labelled so.

Inside each window, as in the paper: sigma for bulk classification and the CDF use the
whole window; V = average daily volume / buckets per day. sigma comes from log price
changes because BTC's price varies about 15-fold (DEVIATIONS.md).

Usage: python scripts/windows.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from vpin import analysis as A
from vpin import plots as P
from vpin.bars import bar_log_changes, time_bars
from vpin.buckets import build_buckets
from vpin.classify import bvc_buy_fraction
from vpin.data import load_btc_klines, load_ive_ticks
from vpin.metric import cdf_full_sample, vpin

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "extensions" / "windows"
MOVE = 0.0075


def paper_method(bars: pd.DataFrame) -> dict:
    """The paper's Section 5 statistics inside one window."""
    change = bar_log_changes(bars)
    buy = bars["volume"].to_numpy() * bvc_buy_fraction(change, np.nanstd(change))
    adv = bars.groupby("day")["volume"].sum().mean()
    out = {}
    for bpd, n in [(50, 250), (10, 350)]:
        b = build_buckets(bars, buy, adv / bpd)
        v = vpin(b["buy"], b["sell"], b["volume"], n)
        ret = A.next_abs_return(b["end_price"].to_numpy())
        cdf = cdf_full_sample(v)
        corr, _ = A.vpin_return_correlation(v, ret)
        events = A.intermediate_events(cdf, b["end_price"].to_numpy())
        out[(bpd, n)] = {"corr": corr, "insurance": A.insurance_value(A.lagged(cdf), ret, MOVE),
                         "true_positive_top": A.true_positive_rate(events, MOVE, 15),
                         "true_positive_bottom": float((events.loc[events["bin"] <= 4, "max_abs_return"] > MOVE).mean()),
                         "big_moves": int(np.nansum(ret > MOVE))}
    return out


def all_windows(bars: pd.DataFrame, market: str, starts) -> pd.DataFrame:
    rows = []
    for start in starts:
        window = bars[(bars["ts"] >= start) & (bars["ts"] < start + pd.DateOffset(years=2))].reset_index(drop=True)
        if window["day"].nunique() < 300:        # incomplete window at the end of the data
            continue
        r = paper_method(window)
        rows.append({"market": market, "start": start.date().isoformat(),
                     "corr_50_250": r[(50, 250)]["corr"], "insurance_50_250": r[(50, 250)]["insurance"],
                     "big_moves_50_250": r[(50, 250)]["big_moves"],
                     "true_positive_top_50_250": r[(50, 250)]["true_positive_top"],
                     "true_positive_bottom_50_250": r[(50, 250)]["true_positive_bottom"],
                     "true_positive_top_10_350": r[(10, 350)]["true_positive_top"],
                     "true_positive_bottom_10_350": r[(10, 350)]["true_positive_bottom"]})
    return pd.DataFrame(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ticks = load_ive_ticks("2009-09-28", "2026-09-30")
    ive = time_bars(ticks, 60)
    del ticks
    k = load_btc_klines("2020-01", "2026-09")
    btc = pd.DataFrame({"ts": k["ts"], "open": k["open"], "close": k["close"], "volume": k["volume"]})
    btc["day"] = btc["ts"].dt.normalize()
    res = pd.concat([all_windows(ive, "IVE", pd.date_range("2009-10-01", "2024-10-01", freq="6MS")),
                     all_windows(btc, "BTC", pd.date_range("2020-01-01", "2024-10-01", freq="6MS"))])
    res.to_csv(OUT / "windows.csv", index=False)
    summary = {m: {c: [float(g[c].min()), float(g[c].max())] for c in
                   ["corr_50_250", "insurance_50_250", "true_positive_top_10_350", "true_positive_bottom_10_350"]}
               | {"windows": int(len(g))} for m, g in res.groupby("market")}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    P.windows_chart(res, OUT / "windows.png")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
