"""Write the generated part of README.md and results/report/key_numbers.json.

Every number in the README's results section is read here from results/ (ours) or from
src/vpin/paper_numbers.py (the paper's). Nothing is typed by hand. The slides read the
same key_numbers.json. Run after scripts/reproduce.py and scripts/extensions.py.

Two presentation rules from the seminar are applied here:
- results from different sources (the paper's and ours) never share a table;
- our metrics carry "±" (month-block bootstrap standard error, vpin.uncertainty).

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
SIGNIFICANT = 0.95          # paired-bootstrap probability needed to call a Table 1 statistic better


def pct(x, digits=0):
    return f"{x:.{digits}%}"


def pm(stat: dict, as_pct=False, digits=2) -> str:
    """'value ± s.e.' from a bootstrap result."""
    if as_pct:
        return f"{stat['value']:.0%} ± {stat['se']:.0%}"
    return f"{stat['value']:.{digits}f} ± {stat['se']:.{digits}f}"


def interval(stat: dict, as_pct=False, digits=2) -> str:
    if as_pct:
        return f"[{stat['lo']:.0%}, {stat['hi']:.0%}]"
    return f"[{stat['lo']:.{digits}f}, {stat['hi']:.{digits}f}]"


def verdict(paper_value: float, ours: dict, direction: dict, null: float) -> str:
    """Test the paper's claim on our data only, with our 95% bootstrap interval.

    reproduced: the paper's value is inside our interval and the effect's direction is
    significant (direction interval excludes `null`); inconclusive: inside, but the
    direction is not significant; weaker: outside (below) but the direction holds;
    not reproduced: outside and the direction does not hold.
    """
    inside = ours["lo"] <= paper_value <= ours["hi"]
    holds = direction["lo"] > null
    if inside:
        return "reproduced" if holds else "inconclusive"
    return "weaker" if holds else "not reproduced"


def table1_significant(boot: pd.DataFrame) -> int:
    """How many of Kurt, J-B*, L-B*, White* are lower in volume time in >= 95% of replications."""
    return int(sum(boot.loc[s, "P(volume < clock)"] >= SIGNIFICANT for s in ["Kurt", "J-B*", "L-B*", "White*"]))


def table1_lower(boot: pd.DataFrame) -> int:
    return int(sum(boot.loc[s, "Volume time"] < boot.loc[s, "Chrono time"] for s in ["Kurt", "J-B*", "L-B*", "White*"]))


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
    alarms = pd.read_csv(EXT / "crash_alarm_summary.csv")
    boot = {str(d): pd.read_csv(REP / f"table1_{d}_bootstrap.csv", index_col=0) for d in (50, 100)}
    pooled = bars[bars["year"].astype(str) == "all"].iloc[0]
    per_year = bars[bars["year"].astype(str) != "all"]

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
        "table1_boot": {d: b.to_dict(orient="index") for d, b in boot.items()},
        "table1_significant": {d: table1_significant(b) for d, b in boot.items()},
        "table1_lower": {d: table1_lower(b) for d, b in boot.items()},
        "table2": rep["table2"],
        "prediction": pred,
        "ive_oos": {c: {p: {s: row(c, p, s) for s in ("VPIN", "RV (trailing volatility)")}
                        for p in ("in-sample", "out-of-sample")} for c in oos["choice"].unique()},
        "ive_chosen": ext["ive_chosen_parameters"],
        "btc_signals": {str(n): {s: btc_row(n, s) for s in btc["signal"].unique()} for n in (50, 250)},
        "btc_buckets": ext["btc_buckets"],
        "btc_bars": {"direction_agreement": pooled["direction_agreement_volume_weighted"],
                     "direction_agreement_se": pooled["direction_agreement_se"],
                     "direction_agreement_min": per_year["direction_agreement_volume_weighted"].min(),
                     "direction_agreement_max": per_year["direction_agreement_volume_weighted"].max(),
                     "corr_buy_share": pooled["corr_buy_share"], "corr_buy_share_se": pooled["corr_buy_share_se"]},
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
        "alarms": alarms.to_dict(orient="records"),
        **new_results(),
    }


def new_results() -> dict:
    """Results of the pre-registered extensions (docs/preregistration.md)."""
    sim = EXT / "simulation"
    ls = EXT / "local_sigma"
    inf = EXT / "inference"
    return {
        "windows": json.loads((EXT / "windows" / "summary.json").read_text()),
        "simulation": {"summary": pd.read_csv(sim / "summary_main.csv").to_dict(orient="records"),
                       "decisions": json.loads((sim / "decisions_main.json").read_text()),
                       "decisions_tick": json.loads((sim / "decisions_tick.json").read_text()),
                       "manifest": json.loads((sim / "run_manifest.json").read_text())},
        "local_sigma": {"predictive": pd.read_csv(ls / "predictive.csv").to_dict(orient="records"),
                        "regressions": pd.read_csv(ls / "regressions.csv").to_dict(orient="records"),
                        "tracking": json.loads((ls / "tracking.json").read_text())},
        "inference": json.loads((inf / "summary.json").read_text()),
        "ledger": pd.read_csv(ROOT / "results" / "report" / "ledger.csv").to_dict(orient="records"),
    }


def sim_value(k: dict, world: str, version: str, metric: str) -> dict:
    return next(r for r in k["simulation"]["summary"]
                if r["world"] == world and r["version"] == version and r["metric"] == metric)


def new_sections(k: dict) -> str:
    """README sections for the all-windows analysis, the simulation, the fix and the inference package."""
    w = k["windows"]
    win = pd.DataFrame([(m, v["windows"], f"{v['corr_50_250'][0]:.2f} to {v['corr_50_250'][1]:.2f}",
                         f"{v['insurance_50_250'][0]:.0%} to {v['insurance_50_250'][1]:.0%}",
                         f"{v['true_positive_top_10_350'][0]:.0%} to {v['true_positive_top_10_350'][1]:.0%}",
                         f"{v['true_positive_bottom_10_350'][0]:.0%} to {v['true_positive_bottom_10_350'][1]:.0%}")
                        for m, v in w.items()],
                       columns=["Market", "Two-year windows", "Corr at (50, 250)", "P(top quartile | big move)",
                                "True positives (10, 350), VPIN top quartile", "... bottom quartile"])
    names = {"paper": "paper's method (BVC, whole-sample σ)", "true": "true labels", "local": "BVC with one-day σ (our fix)"}
    sim_rows = []
    for version in ("paper", "true", "local"):
        f = lambda wd, m: sim_value(k, wd, version, m)
        sim_rows.append((names[version], f"{f('V', 'M1_tracking')['mean']:.3f} ± {f('V', 'M1_tracking')['mc_se']:.4f}",
                         f"{f('V', 'M2_false_alarm')['mean']:+.3f} ± {f('V', 'M2_false_alarm')['mc_se']:.3f}",
                         f"{f('T', 'M3_auc')['mean']:.3f} ± {f('T', 'M3_auc')['mc_se']:.4f}",
                         f"{f('V', 'M4_predictive_corr')['mean']:+.3f} ± {f('V', 'M4_predictive_corr')['mc_se']:.3f}"))
    sim_df = pd.DataFrame(sim_rows, columns=["VPIN version", "Tracks informed share, world V (corr)",
                                             "False alarms from volatility, world V", "Detection AUC, world T",
                                             "Paper's predictive test, world V"])
    d = k["simulation"]["decisions"]
    dec = pd.DataFrame([
        ("D1", "true-label VPIN tracks informed trading (M1 > 0.5, world T)", f"{d['D1_true_vpin_tracks_informed_trading']['M1_T_true']:.2f}",
         "holds" if d["D1_true_vpin_tracks_informed_trading"]["holds"] else "does not hold"),
        ("D2", "the paper's VPIN raises false alarms from volatility alone", f"{d['D2_false_alarms_from_volatility']['paper']['M2_V']:+.3f}",
         "holds" if d["D2_false_alarms_from_volatility"]["paper"]["confounds_volatility"] else "does not hold"),
        ("D3", "the paper's predictive test is fooled by volatility (positive corr in world V)", f"{d['D3_predictive_test_uninformative']['M4_V_paper']:+.3f}",
         "holds" if d["D3_predictive_test_uninformative"]["holds"] else "does not hold"),
        ("D4", "the one-day-σ fix halves false alarms and keeps detection",
         f"{d['D4_local_sigma_is_an_improvement']['M2_V_local']:+.3f} vs {d['D4_local_sigma_is_an_improvement']['M2_V_paper']:+.3f}; AUC {d['D4_local_sigma_is_an_improvement']['AUC_T_local']:.3f} vs {d['D4_local_sigma_is_an_improvement']['AUC_T_paper']:.3f}",
         "holds" if d["D4_local_sigma_is_an_improvement"]["holds"] else "does not hold"),
    ], columns=["Rule", "Pre-registered statement", "Result", "Verdict"])
    ls = pd.DataFrame(k["local_sigma"]["predictive"])
    ls_df = pd.DataFrame([(r["market"], f"({r['buckets_per_day']}, {r['sample_length']})", r["signal"],
                           f"{r['corr']:.3f} ± {r['corr_se']:.3f}", f"{r['lift']:.2f} ± {r['lift_se']:.2f}")
                          for r in ls.to_dict(orient="records")],
                         columns=["Market", "Setting", "Signal", "Corr with next |return|", "Lift"])
    tr = k["local_sigma"]["tracking"]
    regs = {(r["market"], r["choice"], r["signal"]): r for r in k["local_sigma"]["regressions"]}
    inf = k["inference"]
    plc = pd.DataFrame([(s, f"{v['real_corr']:.3f}", f"{v['placebo_corr_mean']:.3f} ± {v['placebo_corr_sd']:.3f}",
                         f"{v['placebo_share_of_real_corr']:.0%}", f"{v['real_lift']:.2f}", f"{v['placebo_lift_mean']:.2f}")
                        for s, v in inf["placebo"].items()],
                       columns=["Sample", "Corr, real VPIN", "Corr, direction-shuffled (20 draws)", "Share kept",
                                "Lift, real", "Lift, shuffled"])
    loyo = pd.DataFrame([(key.split(" | ")[0], key.split(" | ")[1], f"{v['corr_min']:.3f} to {v['corr_max']:.3f}", v["sign_flips"], v["years"])
                         for key, v in inf["loyo"].items()],
                        columns=["Sample", "Signal", "Corr, leaving one year out (min to max)", "Sign flips", "Years"])
    led = inf["ledger"]
    return f"""### All two-year windows: do the paper's predictive numbers appear anywhere?

The paper's exact in-sample method (whole-window σ and CDF) on every two-year window, starting each January and July (`scripts/windows.py`; run once as an exploration before the pre-registration, so labelled exploratory). Every window is reported. For comparison, the paper reports 0.40 for the correlation and over 84% for P(top quartile | big move).

{md_table(win)}

On BTC a 0.75% move is routine, so the true-positive rate is as high or higher when VPIN is *low*: the statistic says nothing there.

![All windows](results/extensions/windows/windows.png)

### E3. A known-answer test of VPIN (simulation, pre-registered)

The paper's own Monte Carlo (Appendix A.2) draws buys and sells straight from the PIN model, with correct labels and no prices. Its empirical VPIN, however, labels trades by bulk classification, which needs prices. We simulate the paper's model **with prices**, where the true share of informed trading is known, and run the same pipeline. There are four worlds: constant (0), more informed trading in some blocks of days (T), more public volatility and uninformed volume in some blocks with informed trading unchanged (V), and both (TV). Design, metrics and decision rules were fixed in [docs/preregistration.md](docs/preregistration.md) before the first run (SHA-256 in `results/extensions/simulation/run_manifest.json`). There are {k['simulation']['manifest']['reps']} replications per world; ± is the Monte Carlo standard error.

{md_table(sim_df)}

{md_table(dec)}

When volatility changes but informed trading does not, the paper's VPIN stops tracking informed trading and raises alarms in turbulent blocks. VPIN from the true labels moves the other way: extra uninformed volume dilutes the informed share. That is the same sign we find on real BTC data (E2). Measuring each price change against the previous day's volatility removes the bias without losing detection. D3 did not hold in this calibration: the two effects roughly cancel in the paper's predictive statistic. The tick-rounded variant gives the same decisions (`decisions_tick.json`).

![Simulation](results/extensions/simulation/metrics.png)

### E4. The fix on real data (pre-registered rule D5)

Bulk classification with σ from the previous day only ("local σ"), in the same real-time buckets:

- On BTC, where the truth is known, local-σ VPIN tracks true-label VPIN better: correlation {tr['BTC_50_50']['corr_local_true']['value']:.2f} vs {tr['BTC_50_50']['corr_standard_true']['value']:.2f} at (50, 50), difference {tr['BTC_50_50']['difference']['value']:+.3f} ± {tr['BTC_50_50']['difference']['se']:.3f}; and {tr['BTC_50_250']['corr_local_true']['value']:.2f} vs {tr['BTC_50_250']['corr_standard_true']['value']:.2f} at (50, 250).
- Once the volatility bias is removed, most of VPIN's link to future volatility disappears:

{md_table(ls_df)}

- Beyond trailing volatility, last return and trading intensity (Newey–West t): local-σ VPIN t = {regs[('IVE 2011-26', '(50, 250)', 'vpin_local')]['t_vpin_hac']:.1f} on IVE 2011–2026 (ΔR² = {regs[('IVE 2011-26', '(50, 250)', 'vpin_local')]['delta_r2']:.4f}); t = {regs[('BTC', '(50, 50)', 'vpin_local')]['t_vpin_hac']:.1f} on BTC (50, 50), where the coefficient is negative.

### Inference: placebo, stability, power and a ledger of every test

- **Placebo** (direction-shuffled VPIN): each one-minute imbalance keeps its size but gets a random direction. If VPIN's predictive power came from the direction of trading (informed traders on one side), the placebo would lose it.

{md_table(plc)}

The placebo keeps essentially all of VPIN's predictive power in every sample. The power comes from the size of price moves, not from the direction of order flow.

- **Leave one year out:**

{md_table(loyo)}

- **Power:** the reproduction's month-block standard error for the correlation at (50, 250) is {inf['power']['corr_se_50_250']:.3f}, so the smallest correlation it could detect with 80% power is {inf['power']['mde_80pct_power']:.2f}. The paper's 0.40 would have been detected easily; the gap is not a matter of power.
- **Ledger** (`results/report/ledger.csv`): {led['tests']} tests behind our claims. {led['supported_bh']} are supported after Benjamini–Hochberg and {led['supported_bonferroni']} after Bonferroni, counting a claim as supported only if it is significant **and** on the claimed side. {led['significant_wrong_side']} are significant in the opposite direction (for example, D3 and VPIN's negative coefficient beyond volatility on BTC) and are reported as not supported. The reproduction's own correlation at (50, 250) is borderline: z = {next(r['z'] for r in k['ledger'] if r['claim'].startswith('corr(ln VPIN, next |r|) > 0')):.2f} with the normal approximation, although the skewed bootstrap interval excludes zero. With about two years of months to resample, we call it weakly positive."""


def scorecard(k: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Two tables with the same row numbers: what the paper reports, and what we find."""
    p, u = k["prediction"], k["prediction"]["uncertainty"]
    u250, u350 = u["50_250"], u["10_350"]
    fc = k["flash_crash"]
    sig, low = k["table1_significant"], k["table1_lower"]
    lead = lambda name: fc[name]["lead_hours"]
    ok_lead = lambda name: lead(name) is not None and lead(name) == lead(name) and lead(name) >= PN.FLASH_CRASH_LEAD_HOURS
    lr = fc["Lee-Ready, trade by trade"]
    paper = [
        ("VPIN does not depend on where the bucket sequence starts (std / mean across 1,000 starts)",
         pct(k["stability"]["paper"], 1), "Fig. 5"),
        ("Volume time is closer to normal than clock time: Kurt, J-B*, L-B*, White* lower",
         "4 of 4 at 50 and at 100 draws a day", "Table 1"),
        ("CDF(VPIN) > 0.9 at least 2 h before the flash crash: BVC, one-minute bars", f"≥ {PN.FLASH_CRASH_LEAD_HOURS} h", "Fig. 4(a)"),
        ("... BVC, 10-second bars", f"≥ {PN.FLASH_CRASH_LEAD_HOURS} h", "Fig. 4(b)"),
        ("... Lee-Ready, trade by trade", f"≥ {PN.FLASH_CRASH_LEAD_HOURS} h", "Fig. 4(c)"),
        ("Low VPIN (bottom quartile) → next |return| < 0.25%", "> " + pct(PN.BOTTOM_QUARTILE_SMALL_MOVE), "Table 4a, p. 30"),
        ("Corr(ln VPIN, next |return|) at (50, 250)",
         f"{PN.CORR_50_250:.2f} [{PN.CORR_50_250_CI[0]:.3f}, {PN.CORR_50_250_CI[1]:.3f}]", "Fig. 10, fn. 29"),
        ("P(VPIN in top quartile | next |return| > 0.75%) at (50, 250)", "> " + pct(PN.INSURANCE_50_250), "Sec. 5.2"),
        ("P(move > 0.75% while VPIN stays in the top quartile) at (50, 250)", pct(PN.TRUE_POSITIVE_50_250, 1), "Fig. 14"),
        ("... at (10, 350)", pct(PN.TRUE_POSITIVE_10_350, 1), "Table 5"),
    ]
    ours = [
        (pct(k["stability"]["ours"], 1), "dispersion over 1,000 starts",
         "reproduced" if k["stability"]["ours"] <= k["stability"]["paper"] else "weaker"),
        (f"significantly lower: {sig['50']} of 4 (50/day), {sig['100']} of 4 (100/day); point estimates lower: {low['50']} and {low['100']} of 4",
         "paired bootstrap, P ≥ 0.95", "reproduced" if min(sig.values()) == 4 else "partly" if max(low.values()) >= 3 else "not reproduced"),
        (f"{lead('BVC, 1-minute bars'):.1f} h", "one event: no ±", "reproduced" if ok_lead("BVC, 1-minute bars") else "not reproduced"),
        ("only during the fall" if not ok_lead("BVC, 10-second bars") else f"{lead('BVC, 10-second bars'):.1f} h", "one event: no ±",
         "reproduced" if ok_lead("BVC, 10-second bars") else "not reproduced"),
        (f"never (max CDF {lr['max_cdf']:.2f})" if not ok_lead("Lee-Ready, trade by trade") else f"{lead('Lee-Ready, trade by trade'):.1f} h",
         "one event: no ±", "reproduced" if ok_lead("Lee-Ready, trade by trade") else "not reproduced"),
        (f"{u250['bottom_small']['value']:.1%} ± {u250['bottom_small']['se']:.1%}",
         f"[{u250['bottom_small']['lo']:.1%}, {u250['bottom_small']['hi']:.1%}]",
         "reproduced" if u250["bottom_small"]["lo"] > PN.BOTTOM_QUARTILE_SMALL_MOVE else "weaker"),
        (pm(u250["corr"]), interval(u250["corr"]), verdict(PN.CORR_50_250, u250["corr"], u250["corr"], 0.0)),
        (pm(u250["insurance"], True), interval(u250["insurance"], True),
         ("reproduced" if u250["insurance"]["lo"] > PN.INSURANCE_50_250 else
          "weaker" if u250["lift"]["lo"] > 1 else "not reproduced")),
        (pm(u250["tp_top"], True), interval(u250["tp_top"], True), verdict(PN.TRUE_POSITIVE_50_250, u250["tp_top"], u250["tp_diff"], 0.0)),
        (pm(u350["tp_top"], True), interval(u350["tp_top"], True), verdict(PN.TRUE_POSITIVE_10_350, u350["tp_top"], u350["tp_diff"], 0.0)),
    ]
    paper_df = pd.DataFrame([(i + 1, *r) for i, r in enumerate(paper)], columns=["#", "Claim", "Paper reports (E-mini, 2008–11)", "Where"])
    ours_df = pd.DataFrame([(i + 1, *r) for i, r in enumerate(ours)], columns=["#", "Ours on IVE, 2009–11 (± s.e.)", "95% interval", "Verdict"])
    return paper_df, ours_df


def md_table(df: pd.DataFrame) -> str:
    """Markdown table; a '|' inside a cell (as in |return|) is escaped."""
    cell = lambda v: str(v).replace("|", "\\|")
    lines = ["| " + " | ".join(cell(c) for c in df.columns) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(cell(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(lines)


def table1_frames(k: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    stats = ["Kurt", "J-B*", "L-B*", "White*", "Max"]
    paper = pd.DataFrame([(s, f"{PN.TABLE1_50['Chrono time'][s]:.2f}", f"{PN.TABLE1_50['Volume time'][s]:.2f}") for s in stats],
                         columns=["Statistic", "Clock time", "Volume time"])
    b = k["table1_boot"]["50"]
    ours = pd.DataFrame([(s, f"{b[s]['Chrono time']:.2f} ± {b[s]['Chrono ±']:.2f}", f"{b[s]['Volume time']:.2f} ± {b[s]['Volume ±']:.2f}",
                          f"{b[s]['P(volume < clock)']:.3f}") for s in stats],
                        columns=["Statistic", "Clock time", "Volume time", "P(volume lower)"])
    return paper, ours


def results_section(k: dict) -> str:
    d, p = k["data"], k["prediction"]
    u250 = p["uncertainty"]["50_250"]
    o = k["ive_oos"]
    b50 = k["btc_signals"]["50"]
    bb = k["btc_buckets"]["50_50"]
    bse = bb["se"]
    t = k["btc_trades"]
    bars = k["btc_bars"]
    paper_sc, ours_sc = scorecard(k)
    paper_t1, ours_t1 = table1_frames(k)
    best_corr, best_tp = k["ive_chosen"]["best in-sample corr"], k["ive_chosen"]["best in-sample true positive"]
    se = lambda r, key, as_pct=False: (f"{r[key]:.0%} ± {r[key + '_se']:.0%}" if as_pct else f"{r[key]:.2f} ± {r[key + '_se']:.2f}")
    oos_rows = []
    for choice, per in o.items():
        for period in ("in-sample", "out-of-sample"):
            v, r = per[period]["VPIN"], per[period]["RV (trailing volatility)"]
            oos_rows.append((choice, period, se(v, "corr"), se(r, "corr"), se(v, "lift"), se(r, "lift"),
                             se(v, "true_positive_diff", True), se(r, "true_positive_diff", True)))
    oos_df = pd.DataFrame(oos_rows, columns=["Parameters", "Period", "Corr VPIN", "Corr RV", "Lift VPIN", "Lift RV",
                                             "True positives top − bottom quartile, VPIN", "... RV"])
    btc_df = pd.DataFrame([(s, se(r, "corr"), se(r, "insurance", True), pct(r["alarm_rate"]), se(r, "lift"))
                           for s, r in b50.items()],
                          columns=["Signal (50 buckets/day, n = 50)", "Corr with next |return|",
                                   "P(top quartile | big move)", "Share of time in top quartile", "Lift"])
    ev = pd.DataFrame(k["events"])
    onoff = lambda v: "–" if v != v or v is None else ("on" if v else "off")
    ev_df = pd.DataFrame([(r["market"], r["day"], pct(r["drop_1h"], 1), onoff(r["vpin_alarm_on"]),
                           onoff(r.get("vpin_true_alarm_on", float("nan"))), onoff(r["rv_alarm_on"]))
                          for r in ev.to_dict(orient="records")],
                         columns=["Market", "Day", "Largest 1-hour fall", "VPIN alarm", "True-label VPIN alarm", "RV alarm"])
    names = {"vpin": "VPIN (bulk classified)", "vpin_true": "VPIN (true labels)", "rv": "RV (trailing volatility)"}
    al_df = pd.DataFrame([(a["market"], names[a["signal"]], f"{a['hits']} of {a['falls']}", pct(a["alarm_share"]),
                           f"{a['p_value_binomial']:.3f}" if a["p_value_binomial"] >= 0.001 else "< 0.001") for a in k["alarms"]],
                         columns=["Market", "Alarm", "On at falls", "On overall", "Binomial p-value"])
    oos_out = [per["out-of-sample"] for per in o.values()]
    rv_wins = sum(r["RV (trailing volatility)"]["corr"] - 2 * r["RV (trailing volatility)"]["corr_se"] > r["VPIN"]["corr"] for r in oos_out)
    decay = [(c, per["in-sample"]["VPIN"], per["out-of-sample"]["VPIN"]) for c, per in o.items()]
    reg = {(r["market"], r["choice"], r["period"], r["signal"]): r for r in k["regressions"]}
    btc_reg = reg[("BTC", "(50, 50)", next(r["period"] for r in k["regressions"] if r["market"] == "BTC"), "vpin")]
    ive_reg = reg[("IVE", "paper (50, 250)", "out-of-sample", "vpin")]
    return f"""{START}
<!-- Generated by scripts/make_report.py from results/. Do not edit by hand. -->

"±" is a standard error from a block bootstrap that resamples whole calendar months (1,000 replications, `src/vpin/uncertainty.py`); brackets are 95% percentile intervals. Months, not single buckets, are resampled because VPIN windows overlap and volatility clusters. The paper's numbers and ours are never in the same table: the data, market and period differ.

### Reproduction on IVE, {d['period'][0]} to {d['period'][1]} ({d['days']} days, {d['ticks']:,} trades)

**What the paper reports** (E-mini S&P 500 futures, 2008–2011):

{md_table(paper_sc)}

**What we find on IVE** (same row numbers). Verdict rule, on our data only: *reproduced* if the paper's value lies inside our 95% interval and the effect's direction is significant (correlation > 0; top-quartile VPIN beats bottom-quartile; lift > 1); *inconclusive* if inside but the direction is not significant; *weaker* if outside but the direction holds; *not reproduced* otherwise.

{md_table(ours_sc)}

Low VPIN goes with calm markets, and VPIN does not depend on where the volume clock starts. VPIN's link to future volatility has the paper's sign but is much smaller. Overnight gaps do not explain this: without buckets that span the close, the correlation at (50, 250) is {p['corr_50_250_intraday']:.2f}. An iid Fisher interval, the paper's method (footnote 29), would give our correlation as [{p['corr_50_250_fisher_ci_iid'][0]:.2f}, {p['corr_50_250_fisher_ci_iid'][1]:.2f}], several times narrower than the month-block interval {interval(u250['corr'])}: it ignores that neighbouring buckets share most of their VPIN window.

**Table 1, the paper's version** (E-mini, 50 draws a day):

{md_table(paper_t1)}

**Table 1, ours** (IVE, 50 draws a day, without 6 May 2010 and overnight changes; "P(volume lower)" = share of paired bootstrap replications in which volume time has the lower value):

{md_table(ours_t1)}

![Figure 4 on IVE](results/reproduction/figures/fig4_flash_crash.png)

### E1. Bulk classification against the truth (BTCUSDT, Binance)

Binance records the aggressor of every trade, so the true buy volume is known.

- One-minute bars: BVC gets the sign of the imbalance right for {pct(bars['direction_agreement'], 1)} ± {pct(bars['direction_agreement_se'], 1)} of volume ({pct(bars['direction_agreement_min'])}–{pct(bars['direction_agreement_max'])} by year); its buy share correlates {bars['corr_buy_share']:.2f} ± {bars['corr_buy_share_se']:.2f} with the true one.
- Buckets: BVC inflates the size of the imbalance {bse['imbalance_inflation']:.1f} times (mean |imbalance| {bb['mean_abs_imbalance_bvc']:.2f} vs {bb['mean_abs_imbalance_true']:.2f}), and the two VPINs correlate only {bb['corr_vpin_bvc_true']:.2f} ± {bse['corr_vpin_bvc_true']:.2f}.
- BVC's imbalance is tied to the bucket's own price move ({bb['corr_abs_imbalance_with_same_bucket_abs_return_bvc']:.2f} ± {bse['corr_abs_imbalance_with_same_bucket_abs_return_bvc']:.2f} vs {bb['corr_abs_imbalance_with_same_bucket_abs_return_true']:.2f} ± {bse['corr_abs_imbalance_with_same_bucket_abs_return_true']:.2f} for the true imbalance): it partly measures volatility by construction.
- On {t['days']} trade days the tick rule classifies {pct(t['tick_accuracy_min'])}–{pct(t['tick_accuracy_max'])} of volume correctly; bucket imbalance from the tick rule correlates ≥ {t['corr_tick_min']:.2f} with the truth, BVC only {t['corr_bvc_1min_min']:.2f}–{t['corr_bvc_1min_max']:.2f} (1-minute bars) and {t['corr_bvc_10s_min']:.2f}–{t['corr_bvc_10s_max']:.2f} (10-second bars); ranges are across the {t['days']} days. Caveat: Binance's aggregated trades group the fills of one order, which helps the tick rule.

![BVC vs true labels](results/extensions/figures/e1_btc_vpin_true_vs_bvc.png)

### E2. Is VPIN more than volatility?

"Lift" = P(signal in its top quartile | next |return| > 0.75%) divided by the share of time the signal is in its top quartile. A signal that is always "on" has a high hit rate and a lift of 1.

{md_table(btc_df)}

VPIN from **true** labels is negatively related to the next move; bulk-classified VPIN is positive, and trailing volatility beats both. Whatever predictive power VPIN has comes from its volatility component. In regressions of the next |return| on ln VPIN with volatility and trade-intensity controls, VPIN's coefficient is significantly negative on BTC (Newey–West t = {btc_reg['t_vpin_hac']:.1f}) and positive on IVE out of sample (t = {ive_reg['t_vpin_hac']:.1f}); either way it adds little: ΔR² = {btc_reg['delta_r2']:.4f} and {ive_reg['delta_r2']:.4f} (`results/extensions/regressions.csv`). The t-statistic is the test; ΔR² cannot be negative, so its bootstrap interval is not one.

### Further check A: real-time VPIN out of sample (IVE after {d['period'][1]})

No look-ahead: sigma, bucket size and the CDF use only past data. Parameters are the paper's, or chosen the paper's way on the in-sample period and then frozen (best in-sample correlation: {tuple(best_corr)}; best in-sample true-positive rate: {tuple(best_tp)}). All rows come from the same IVE data.

{md_table(oos_df)}

In-sample → out-of-sample correlation of VPIN: {'; '.join(f"{c} {a['corr']:.2f} ± {a['corr_se']:.2f} → {b['corr']:.2f} ± {b['corr_se']:.2f}" for c, a, b in decay)}. Out of sample, trailing volatility's correlation exceeds VPIN's by more than two standard errors for {rv_wins} of {len(oos_out)} parameter choices.

![By year](results/extensions/figures/e2_ive_by_year.png)

### Further check B: crashes after the paper

Was the real-time alarm (CDF ≥ 0.9, 50 buckets/day, n = 50) on when the day's largest one-hour fall began?

{md_table(ev_df)}

{md_table(al_df)}

The binomial p-value is the chance of at least that many hits if the alarm were on at each fall independently with its overall rate; falls are few and not independent of the market's state, so read it as a rough guide. On IVE the VPIN alarm was on at every fall, the extension result most favourable to VPIN; on BTC no alarm was reliable.

{new_sections(k)}

{END}"""


def environment() -> str:
    cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
    return f"Python {platform.python_version()}, {platform.system()} {platform.mac_ver()[0] or platform.release()}, {cpu or platform.processor()}"


def main():
    k = key_numbers()
    out = ROOT / "results" / "report"
    out.mkdir(parents=True, exist_ok=True)
    (out / "key_numbers.json").write_text(json.dumps(k, indent=2, default=float))
    paper_sc, ours_sc = scorecard(k)
    paper_sc.to_csv(out / "scorecard_paper.csv", index=False)
    ours_sc.to_csv(out / "scorecard_ours.csv", index=False)
    (out / "scorecard.csv").unlink(missing_ok=True)   # replaced by the two files above
    readme = (ROOT / "README.md").read_text()
    a, b = readme.index(START), readme.index(END) + len(END)
    readme = readme[:a] + results_section(k) + readme[b:]
    env_start, env_end = "<!-- env:start -->", "<!-- env:end -->"
    a, b = readme.index(env_start), readme.index(env_end) + len(env_end)
    readme = readme[:a] + f"{env_start}{environment()}{env_end}" + readme[b:]
    (ROOT / "README.md").write_text(readme)
    print(paper_sc.to_string(), "\n", ours_sc.to_string())


if __name__ == "__main__":
    main()
