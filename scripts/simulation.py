"""Run the known-answer simulation (docs/preregistration.md, section 1).

200 replications per world, fixed seeds (1000 * world index + replication), run in
parallel processes. Writes per-replication metrics, a summary with Monte Carlo standard
errors, the pre-registered decisions D1-D4 evaluated by code, and figures, to
results/extensions/simulation/. A second, secondary run rounds prices to a 1 bp tick.

Usage: python scripts/simulation.py [--reps 200] [--smoke]
"""
import argparse
import hashlib
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from vpin import plots as P
from vpin.simulation import WORLDS, evaluate, simulate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "extensions" / "simulation"
PREREG = ROOT / "docs" / "preregistration.md"
METRICS = ["M1_tracking", "M2_false_alarm", "M3_auc", "M4_predictive_corr", "M5_coef_toxicity", "M5_coef_volatility"]


def one(args):
    world_name, rep, tick, days = args
    world_index = list(WORLDS).index(world_name)
    bars = simulate(WORLDS[world_name], days=days, seed=1000 * world_index + rep, tick=tick)
    return [{"world": world_name, "rep": rep, **row} for row in evaluate(bars)]


def run(reps: int, tick, days: int) -> pd.DataFrame:
    jobs = [(w, r, tick, days) for w in WORLDS for r in range(reps)]
    with ProcessPoolExecutor() as pool:
        rows = [row for chunk in pool.map(one, jobs, chunksize=4) for row in chunk]
    return pd.DataFrame(rows)


def summarize(per_rep: pd.DataFrame) -> pd.DataFrame:
    """Mean, Monte Carlo standard error (s.d./sqrt(R)) and 2.5-97.5% range across replications."""
    long = per_rep.melt(id_vars=["world", "rep", "version"], value_vars=METRICS, var_name="metric").dropna()
    g = long.groupby(["world", "version", "metric"])["value"]
    return pd.DataFrame({"mean": g.mean(), "mc_se": g.std(ddof=1) / np.sqrt(g.count()),
                         "p2.5": g.quantile(0.025), "p97.5": g.quantile(0.975), "reps": g.count()}).reset_index()


def decisions(s: pd.DataFrame) -> dict:
    """The pre-registered decision rules, evaluated mechanically."""
    get = lambda w, v, m: s[(s["world"] == w) & (s["version"] == v) & (s["metric"] == m)].iloc[0]
    out = {}
    m1 = get("T", "true", "M1_tracking")
    out["D1_true_vpin_tracks_informed_trading"] = {"M1_T_true": m1["mean"], "rule": "M1 > 0.5", "holds": bool(m1["mean"] > 0.5)}
    out["D2_false_alarms_from_volatility"] = {
        v: {"M2_V": get("V", v, "M2_false_alarm")["mean"], "mc_se": get("V", v, "M2_false_alarm")["mc_se"],
            "confounds_volatility": bool(get("V", v, "M2_false_alarm")["mean"] > 3 * get("V", v, "M2_false_alarm")["mc_se"])}
        for v in ("paper", "true", "local")}
    m4 = get("V", "paper", "M4_predictive_corr")
    out["D3_predictive_test_uninformative"] = {"M4_V_paper": m4["mean"], "mc_se": m4["mc_se"],
                                               "holds": bool(m4["mean"] > 3 * m4["mc_se"])}
    m2p, m2l = get("V", "paper", "M2_false_alarm")["mean"], get("V", "local", "M2_false_alarm")["mean"]
    a_p, a_l = get("T", "paper", "M3_auc")["mean"], get("T", "local", "M3_auc")["mean"]
    out["D4_local_sigma_is_an_improvement"] = {"M2_V_paper": m2p, "M2_V_local": m2l, "AUC_T_paper": a_p, "AUC_T_local": a_l,
                                               "a_false_alarms_halved": bool(m2l < 0.5 * m2p),
                                               "b_detection_kept": bool(a_l >= a_p - 0.05)}
    out["D4_local_sigma_is_an_improvement"]["holds"] = (out["D4_local_sigma_is_an_improvement"]["a_false_alarms_halved"]
                                                        and out["D4_local_sigma_is_an_improvement"]["b_detection_kept"])
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reps", type=int, default=200)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    reps, days = (4, 30) if args.smoke else (args.reps, 120)
    out = OUT if not args.smoke else OUT.parent / "simulation_smoke"
    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    manifest = {"prereg_sha256": hashlib.sha256(PREREG.read_bytes()).hexdigest(), "reps": reps, "days": days}
    for label, tick in [("main", None), ("tick", 1e-4)]:
        per_rep = run(reps, tick, days)
        per_rep.to_csv(out / f"per_replication_{label}.csv", index=False)
        s = summarize(per_rep)
        s.to_csv(out / f"summary_{label}.csv", index=False)
        (out / f"decisions_{label}.json").write_text(json.dumps(decisions(s), indent=2, default=float))
        if label == "main":
            P.simulation_metrics(s, out / "metrics.png")
            for world in ("T", "V"):
                bars = simulate(WORLDS[world], days=days, seed=1000 * list(WORLDS).index(world))
                P.simulation_path(bars, world, out / f"example_{world}.png")
    manifest["seconds"] = time.perf_counter() - started
    (out / "run_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(json.loads((out / "decisions_main.json").read_text()), indent=1))


if __name__ == "__main__":
    main()
