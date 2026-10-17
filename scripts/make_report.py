"""Write the generated part of README.md and results/report/key_numbers.json.

Every number in the README's results section is read here from results/ (ours) or from
src/vpin/paper_numbers.py (the paper's). Nothing is typed by hand. The slides read the
same key_numbers.json. Run after scripts/reproduce.py and scripts/extensions.py.

Usage: python scripts/make_report.py
"""
import json
import platform
import subprocess
from pathlib import Path

import pandas as pd

from vpin import paper_numbers as PN

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / "results" / "reproduction"
EXT = ROOT / "results" / "extensions"
START, END = "<!-- results:start -->", "<!-- results:end -->"


def verdict(ours: float, paper: float) -> str:
    """One rule for every numeric claim: ours / paper >= 0.8 is 'reproduced',
    0.4-0.8 'weaker', below 0.4 'much weaker'."""
    ratio = ours / paper
    return "reproduced" if ratio >= 0.8 else "weaker" if ratio >= 0.4 else "much weaker"


def pct(x, digits=0):
    return f"{x:.{digits}%}"


def table1_wins(path: Path) -> tuple[int, int]:
    """How many of Kurt, J-B*, L-B*, White* are lower in volume time than in clock time."""
    t = pd.read_csv(path, index_col=0)
    stats = ["Kurt", "J-B*", "L-B*", "White*"]
    return int(sum(t.loc[s, "Volume time"] < t.loc[s, "Chrono time"] for s in stats)), len(stats)


def key_numbers() -> dict:
    rep = json.loads((REP / "summary.json").read_text())
    ext = json.loads((EXT / "summary.json").read_text())
    pred, stab = rep["prediction"], rep["stability"]
    crash = pd.read_csv(REP / "flash_crash.csv").set_index("scheme")
    oos = pd.read_csv(EXT / "ive_oos_comparison.csv")
    btc = pd.read_csv(EXT / "btc_signal_comparison.csv")
    bars = pd.read_csv(EXT / "btc_bars_bvc_vs_truth.csv")
    trades = pd.read_csv(EXT / "btc_trade_days.csv")
    reg = pd.read_csv(EXT / "regressions.csv")
    events = pd.read_csv(EXT / "crash_events.csv")
    wins = {str(d): table1_wins(REP / f"table1_{d}_no_crash_day_intraday.csv") for d in (50, 100)}
    raw_wins = {str(d): table1_wins(REP / f"table1_{d}.csv") for d in (50, 100)}

    def row(choice, period, signal):
        r = oos[(oos["choice"] == choice) & (oos["period"] == period) & (oos["signal"] == signal)]
        return r.iloc[0].to_dict()

    def btc_row(n, signal):
        return btc[(btc["sample_length"] == n) & (btc["signal"] == signal)].iloc[0].to_dict()

    return {
        "data": {"period": rep["period"], "days": rep["days"], "ticks": rep["ticks"],
                 "share_bars_no_price_change": rep["share_bars_no_price_change"]},
        "flash_crash": {k: {"lead_hours": v["lead_hours_before_14:32"], "max_cdf": v["max_cdf_day"],
                            "first": v["first_cdf_0.9"]} for k, v in crash.iterrows()},
        "stability": {"ours": stab["std_over_mean"], "paper": PN.STABILITY_MEAN_STD / PN.STABILITY_VPIN_MEAN},
        "table1": {"wins_clean": wins, "wins_raw": raw_wins},
        "table2": rep["table2"],
        "prediction": pred,
        "ive_oos": {c: {p: {s: row(c, p, s) for s in ("VPIN", "RV (trailing volatility)")}
                        for p in ("in-sample", "out-of-sample")} for c in oos["choice"].unique()},
        "ive_chosen": ext["ive_chosen_parameters"],
        "btc_signals": {str(n): {s: btc_row(n, s) for s in btc["signal"].unique()} for n in (50, 250)},
        "btc_buckets": ext["btc_buckets"],
        "btc_bars": {"direction_agreement_min": bars["direction_agreement_volume_weighted"].min(),
                     "direction_agreement_max": bars["direction_agreement_volume_weighted"].max(),
                     "corr_buy_share_min": bars["corr_buy_share"].min(),
                     "corr_buy_share_max": bars["corr_buy_share"].max()},
        "btc_trades": {"tick_accuracy_min": trades["tick_rule_accuracy_volume"].min(),
                       "tick_accuracy_max": trades["tick_rule_accuracy_volume"].max(),
                       "corr_tick_min": trades["corr_signed_imbalance_tick_rule"].min(),
                       "corr_bvc_1min_min": trades["corr_signed_imbalance_bvc_1min"].min(),
                       "corr_bvc_1min_max": trades["corr_signed_imbalance_bvc_1min"].max(),
                       "corr_bvc_10s_min": trades["corr_signed_imbalance_bvc_10s"].min(),
                       "corr_bvc_10s_max": trades["corr_signed_imbalance_bvc_10s"].max(),
                       "days": len(trades)},
        "regressions": reg.to_dict(orient="records"),
        "events": events.to_dict(orient="records"),
    }


def scorecard(k: dict) -> pd.DataFrame:
    p = k["prediction"]
    fc = k["flash_crash"]
    w = k["table1"]["wins_clean"]
    rows = [
        ("VPIN is stable to the starting point (Fig. 5): std / mean across 1,000 starts",
         pct(k["stability"]["paper"], 1), pct(k["stability"]["ours"], 1),
         "reproduced" if k["stability"]["ours"] <= k["stability"]["paper"] else "weaker"),
        ("Volume time is closer to normal than clock time (Table 1): statistics that improve, 50 / 100 draws a day",
         "4 of 4 / 4 of 4", f"{w['50'][0]} of 4 / {w['100'][0]} of 4 (without 6 May 2010 and overnight changes)",
         "reproduced" if min(w["50"][0], w["100"][0]) >= 3 else "partly"),
        ("CDF(VPIN) > 0.9 at least 2 hours before the flash crash (Fig. 4), BVC 1-minute bars",
         f"≥ {PN.FLASH_CRASH_LEAD_HOURS} h", f"{fc['BVC, 1-minute bars']['lead_hours']:.1f} h",
         "reproduced" if fc["BVC, 1-minute bars"]["lead_hours"] >= PN.FLASH_CRASH_LEAD_HOURS else "not reproduced"),
        ("... with BVC 10-second bars", f"≥ {PN.FLASH_CRASH_LEAD_HOURS} h",
         "only during the crash" if (fc["BVC, 10-second bars"]["lead_hours"] or -1) < 0 else f"{fc['BVC, 10-second bars']['lead_hours']:.1f} h",
         "reproduced" if (fc["BVC, 10-second bars"]["lead_hours"] or -1) >= PN.FLASH_CRASH_LEAD_HOURS else "not reproduced"),
        ("... with Lee-Ready trade-by-trade classification", f"≥ {PN.FLASH_CRASH_LEAD_HOURS} h",
         f"never (max CDF {fc['Lee-Ready, trade by trade']['max_cdf']:.2f})" if pd.isna(fc["Lee-Ready, trade by trade"]["lead_hours"]) else f"{fc['Lee-Ready, trade by trade']['lead_hours']:.1f} h",
         "not reproduced" if pd.isna(fc["Lee-Ready, trade by trade"]["lead_hours"]) or fc["Lee-Ready, trade by trade"]["lead_hours"] < 2 else "reproduced"),
        ("Low VPIN (bottom quartile) → next |return| < 0.25% (Table 4a)", "> " + pct(PN.BOTTOM_QUARTILE_SMALL_MOVE),
         pct(p["bottom_quartile_small_move"]), verdict(p["bottom_quartile_small_move"], PN.BOTTOM_QUARTILE_SMALL_MOVE)),
        ("Corr(ln VPIN, next |return|) at (50, 250) (Fig. 10)", f"{PN.CORR_50_250:.2f}", f"{p['corr_50_250']:.2f}",
         verdict(p["corr_50_250"], PN.CORR_50_250)),
        ("P(VPIN in top quartile | next |return| > 0.75%) at (50, 250) (Sec. 5.2)", "> " + pct(PN.INSURANCE_50_250),
         pct(p["insurance_50_250"]), verdict(p["insurance_50_250"], PN.INSURANCE_50_250)),
        ("P(move > 0.75% while VPIN stays in the top quartile) at (50, 250) (Fig. 14)", pct(PN.TRUE_POSITIVE_50_250, 1),
         pct(p["true_positive_50_250"], 1), verdict(p["true_positive_50_250"], PN.TRUE_POSITIVE_50_250)),
        ("... at (10, 350) (Table 5)", pct(PN.TRUE_POSITIVE_10_350, 1), pct(p["true_positive_10_350"], 1),
         verdict(p["true_positive_10_350"], PN.TRUE_POSITIVE_10_350)),
    ]
    return pd.DataFrame(rows, columns=["Claim", "Paper (E-mini)", "Ours (IVE)", "Verdict"])


def md_table(df: pd.DataFrame) -> str:
    """Markdown table; a '|' inside a cell (as in |return|) is escaped."""
    cell = lambda v: str(v).replace("|", "\\|")
    lines = ["| " + " | ".join(cell(c) for c in df.columns) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(cell(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(lines)


def results_section(k: dict) -> str:
    d, p = k["data"], k["prediction"]
    o = k["ive_oos"]
    b50 = k["btc_signals"]["50"]
    bb = k["btc_buckets"]["50_50"]
    t = k["btc_trades"]
    best_corr, best_tp = k["ive_chosen"]["best in-sample corr"], k["ive_chosen"]["best in-sample true positive"]
    oos_rows = []
    for choice, per in o.items():
        for period in ("in-sample", "out-of-sample"):
            v, r = per[period]["VPIN"], per[period]["RV (trailing volatility)"]
            oos_rows.append((choice, period, f"{v['corr']:.2f}", f"{r['corr']:.2f}", f"{v['lift']:.1f}×",
                             f"{r['lift']:.1f}×", pct(v["true_positive_top"]), pct(v["true_positive_bottom"])))
    oos_df = pd.DataFrame(oos_rows, columns=["Parameters", "Period", "Corr VPIN", "Corr RV", "Lift VPIN", "Lift RV",
                                             "True positives, VPIN top quartile", "... bottom quartile"])
    btc_df = pd.DataFrame([(s, f"{r['corr']:.2f}", pct(r["insurance"]), pct(r["alarm_rate"]), f"{r['lift']:.1f}×")
                           for s, r in b50.items()],
                          columns=["Signal (50 buckets/day, n = 50)", "Corr with next |return|",
                                   "P(top quartile | big move)", "Share of time in top quartile", "Lift"])
    ev = pd.DataFrame(k["events"])
    ev_df = pd.DataFrame([(r["market"], r["day"], pct(r["drop_1h"], 1),
                           "on" if r["vpin_alarm_on"] else "off",
                           ("on" if r["vpin_true_alarm_on"] is True else "off" if r["vpin_true_alarm_on"] is False else "–"),
                           "on" if r["rv_alarm_on"] else "off") for r in ev.to_dict(orient="records")],
                         columns=["Market", "Day", "Largest 1-hour fall", "VPIN alarm", "True-label VPIN alarm", "RV alarm"])
    oos_out = oos_df[oos_df["Period"] == "out-of-sample"]
    rv_wins = sum(float(r["Corr RV"]) > float(r["Corr VPIN"]) and float(r["Lift RV"][:-1]) > float(r["Lift VPIN"][:-1])
                  for _, r in oos_out.iterrows())
    decay = [(c, per["in-sample"]["VPIN"]["corr"], per["out-of-sample"]["VPIN"]["corr"]) for c, per in o.items()]
    ive_ev = [r for r in k["events"] if r["market"] == "IVE"]
    btc_ev = [r for r in k["events"] if r["market"] == "BTC"]
    count = lambda evs, col: sum(bool(r[col]) is True and r[col] == r[col] for r in evs)
    alarm_share = ive_ev[0]["vpin_alarm_share"] if ive_ev else float("nan")
    ive_reg = [r for r in k["regressions"] if r["market"] == "IVE" and r["choice"] == "paper (50, 250)"]
    btc_reg = [r for r in k["regressions"] if r["market"] == "BTC" and r["choice"] == "(50, 50)"]
    return f"""{START}
<!-- Generated by scripts/make_report.py from results/. Do not edit by hand. -->

### Reproduction on IVE, {d['period'][0]} to {d['period'][1]} ({d['days']} days, {d['ticks']:,} trades)

Verdict rule for numeric claims: ours / paper ≥ 0.8 "reproduced", 0.4–0.8 "weaker", below 0.4 "much weaker".

{md_table(scorecard(k))}

The mechanics reproduce: VPIN does not depend on where the bucket sequence starts, volume time makes returns more normal, and low VPIN goes with calm markets. The predictive claims are much weaker on IVE. Overnight gaps do not explain it: without buckets that span the close, the correlation at (50, 250) is {p['corr_50_250_intraday']:.2f} (all buckets: {p['corr_50_250']:.2f}). The largest correlation anywhere on the grid is {p['corr_max']:.2f}, at {p['corr_argmax'][0]} buckets/day and n = {p['corr_argmax'][1]}.

![Figure 4 on IVE](results/reproduction/figures/fig4_flash_crash.png)

### E1. Bulk classification against the truth (BTCUSDT, Binance)

Binance records the aggressor of every trade, so the true buy volume is known.

- One-minute bars: BVC gets the sign of the imbalance right for {pct(k['btc_bars']['direction_agreement_min'])}–{pct(k['btc_bars']['direction_agreement_max'])} of volume, depending on the year.
- Buckets: BVC inflates the size of the imbalance {bb['mean_abs_imbalance_bvc'] / bb['mean_abs_imbalance_true']:.1f} times (mean |imbalance| {bb['mean_abs_imbalance_bvc']:.2f} vs {bb['mean_abs_imbalance_true']:.2f}), and the two VPINs correlate only {bb['corr_vpin_bvc_true']:.2f}.
- BVC's imbalance is tied to the bucket's own price move ({bb['corr_abs_imbalance_with_same_bucket_abs_return_bvc']:.2f} vs {bb['corr_abs_imbalance_with_same_bucket_abs_return_true']:.2f} for the true imbalance): it partly measures volatility by construction.
- On {t['days']} trade days the tick rule classifies {pct(t['tick_accuracy_min'])}–{pct(t['tick_accuracy_max'])} of volume correctly; bucket imbalance from the tick rule correlates ≥ {t['corr_tick_min']:.2f} with the truth, BVC only {t['corr_bvc_1min_min']:.2f}–{t['corr_bvc_1min_max']:.2f} (1-minute bars) and {t['corr_bvc_10s_min']:.2f}–{t['corr_bvc_10s_max']:.2f} (10-second bars). Caveat: Binance's aggregated trades group the fills of one order, which helps the tick rule.

![BVC vs true labels](results/extensions/figures/e1_btc_vpin_true_vs_bvc.png)

### E3. Is VPIN more than volatility?

"Lift" = P(signal in its top quartile | next |return| > 0.75%) divided by the share of time the signal is in its top quartile. A signal that is always "on" has a high hit rate and a lift of 1.

{md_table(btc_df)}

VPIN from **true** labels has a negative correlation with the next move ({b50['VPIN (true labels)']['corr']:.2f}); VPIN from bulk classification is positive ({b50['VPIN (bulk classified)']['corr']:.2f}), and trailing volatility beats both ({b50['RV (trailing volatility)']['corr']:.2f}). Whatever predictive power VPIN has comes from its volatility component. In regressions of the next |return| on ln VPIN with volatility and trade-intensity controls (Newey–West errors), VPIN adds ΔR² = {btc_reg[0]['delta_r2']:.4f} on BTC and {ive_reg[1]['delta_r2']:.4f} on IVE out of sample (`results/extensions/regressions.csv`).

### E2. Real-time VPIN, out of sample (IVE after {k['data']['period'][1]})

No look-ahead: sigma, bucket size and the CDF use only past data. Parameters are the paper's, or chosen the paper's way on the in-sample period and then frozen (best in-sample correlation: {tuple(best_corr)}; best in-sample true-positive rate: {tuple(best_tp)}).

{md_table(oos_df)}

In-sample → out-of-sample correlation of VPIN: {'; '.join(f'{c} {a:.2f} → {b:.2f}' for c, a, b in decay)}. Trailing volatility (RV) has both the higher correlation and the higher lift out of sample for {rv_wins} of {len(oos_out)} parameter choices.

![By year](results/extensions/figures/e2_ive_by_year.png)

### E4. Crashes after the paper

Was the real-time alarm (CDF ≥ 0.9) on when the day's largest one-hour fall began?

{md_table(ev_df)}

IVE: the VPIN alarm (CDF ≥ 0.9, 50 buckets/day, n = 50) was on at {count(ive_ev, 'vpin_alarm_on')} of {len(ive_ev)} falls and is on {pct(alarm_share)} of all the time; the RV alarm was on at {count(ive_ev, 'rv_alarm_on')} and is on {pct(ive_ev[0]['rv_alarm_share'])} of the time. This is the extension result most favourable to VPIN, but it rests on five events. BTC: bulk-classified VPIN was on at {count(btc_ev, 'vpin_alarm_on')} of {len(btc_ev)} falls, true-label VPIN at {count(btc_ev, 'vpin_true_alarm_on')}, RV at {count(btc_ev, 'rv_alarm_on')}.

{END}"""


def environment() -> str:
    cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
    return f"Python {platform.python_version()}, {platform.system()} {platform.mac_ver()[0] or platform.release()}, {cpu or platform.processor()}"


def main():
    k = key_numbers()
    out = ROOT / "results" / "report"
    out.mkdir(parents=True, exist_ok=True)
    (out / "key_numbers.json").write_text(json.dumps(k, indent=2, default=float))
    scorecard(k).to_csv(out / "scorecard.csv", index=False)
    readme = (ROOT / "README.md").read_text()
    a, b = readme.index(START), readme.index(END) + len(END)
    readme = readme[:a] + results_section(k) + readme[b:]
    env_start, env_end = "<!-- env:start -->", "<!-- env:end -->"
    a, b = readme.index(env_start), readme.index(env_end) + len(env_end)
    readme = readme[:a] + f"{env_start}{environment()}{env_end}" + readme[b:]
    (ROOT / "README.md").write_text(readme)
    print(scorecard(k).to_string())


if __name__ == "__main__":
    main()
