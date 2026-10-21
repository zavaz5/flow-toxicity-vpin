"""Known-answer simulation: the paper's own PIN model, with prices (docs/preregistration.md, §1).

The paper's Monte Carlo (Appendix A.2) draws buy and sell volume straight from the PIN
model, so trades are labelled correctly and there are no prices. Its empirical VPIN,
however, labels trades by bulk volume classification, which needs prices. Here the
same model also produces a price, so the paper's exact pipeline can be run on it while
the true share of informed trading is known.

One step is one minute of a market that trades around the clock (like the E-mini).
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm

from .buckets import build_buckets, bucket_edges_fixed, fill_buckets
from .metric import cdf_full_sample, vpin

MINUTES_PER_DAY = 1440
PERIOD = 60                      # information period, minutes
BASE = {"alpha": 0.3, "mu": 4.0, "eps": 8.0, "lam": 0.25e-4, "sigma": 1e-4}


@dataclass(frozen=True)
class World:
    """Which state changes between low and high blocks of days."""
    name: str
    alpha_high: float | None = None              # T: news probability in high blocks
    sigma_high: float | None = None              # V: public volatility per minute in high blocks
    eps_high: float | None = None                # V: uninformed arrival rate in high blocks
    t_block_days: int = 10
    v_block_days: int = 10


WORLDS = {
    "0": World("0"),
    "T": World("T", alpha_high=0.7),
    "V": World("V", sigma_high=3e-4, eps_high=16.0),
    "TV": World("TV", alpha_high=0.7, sigma_high=3e-4, eps_high=16.0, t_block_days=10, v_block_days=7),
}


def high_blocks(day: np.ndarray, block_days: int) -> np.ndarray:
    """Alternating blocks of days, low first: True on days in a high block."""
    return (day // block_days) % 2 == 1


def simulate(world: World, days: int = 120, seed: int = 0, tick: float | None = None) -> pd.DataFrame:
    """One replication: one row per minute with price, volume, true buys and informed volume.

    Arrivals: uninformed buys and sells ~ Poisson(eps) each; in a 60-minute period with
    news (probability alpha), informed traders ~ Poisson(mu) per minute, all on the news
    side. Log price: dp = lam * (buys - sells) + sigma * z, so one-sided informed flow
    moves the price (toxicity-induced volatility) and sigma is volatility unrelated to flow.
    `tick` rounds prices to a grid (relative to the starting price of 100).
    """
    rng = np.random.default_rng(seed)
    minutes = days * MINUTES_PER_DAY
    day = np.arange(minutes) // MINUTES_PER_DAY
    t_high = high_blocks(day, world.t_block_days) if world.alpha_high is not None else np.zeros(minutes, bool)
    v_high = high_blocks(day, world.v_block_days) if world.sigma_high is not None else np.zeros(minutes, bool)
    alpha = np.where(t_high, world.alpha_high or BASE["alpha"], BASE["alpha"])
    eps = np.where(v_high, world.eps_high or BASE["eps"], BASE["eps"])
    sigma = np.where(v_high, world.sigma_high or BASE["sigma"], BASE["sigma"])

    period = np.arange(minutes) // PERIOD
    news = rng.random(minutes // PERIOD) < alpha[::PERIOD]
    good = rng.random(minutes // PERIOD) < 0.5                 # delta = 0.5
    informed = rng.poisson(BASE["mu"], minutes) * news[period]
    buys = rng.poisson(eps) + np.where(good[period], informed, 0)
    sells = rng.poisson(eps) + np.where(good[period], 0, informed)
    log_price = np.log(100.0) + np.cumsum(BASE["lam"] * (buys - sells) + sigma * rng.standard_normal(minutes))
    price = np.exp(log_price)
    if tick is not None:
        price = np.round(price / (100 * tick)) * (100 * tick)
    return pd.DataFrame({
        "ts": pd.Timestamp("2020-01-01") + pd.to_timedelta(np.arange(minutes), unit="min"),
        "close": price, "volume": (buys + sells).astype(float), "true_buy": buys.astype(float),
        "informed": informed.astype(float), "t_high": t_high, "v_high": v_high, "day": day,
    })


def buy_volumes(bars: pd.DataFrame) -> dict:
    """The three versions of buy volume compared in the pre-registration.

    paper: BVC with sigma over the whole replication (the paper's method);
    true: the true buy volume (the paper's Appendix setting);
    local: BVC with sigma from the previous day only (our candidate fix), which judges each
    price change against current volatility instead of the whole sample's.
    """
    change = np.diff(bars["close"].to_numpy(), prepend=bars["close"].iloc[0])
    volume = bars["volume"].to_numpy()
    local_sigma = pd.Series(change).rolling(MINUTES_PER_DAY, min_periods=MINUTES_PER_DAY // 2).std().shift(1).to_numpy()
    local = norm.cdf(change / local_sigma)
    return {
        "paper": volume * norm.cdf(change / np.std(change)),
        "true": bars["true_buy"].to_numpy(),
        "local": volume * np.where(np.isfinite(local), local, 0.5),
    }


def auc(score: np.ndarray, label: np.ndarray) -> float:
    """Area under the ROC curve: P(score of a positive > score of a negative), ties count half."""
    ranks = pd.Series(score).rank().to_numpy()
    pos = label.sum()
    neg = len(label) - pos
    return float((ranks[label].sum() - pos * (pos + 1) / 2) / (pos * neg)) if pos and neg else np.nan


def evaluate(bars: pd.DataFrame, buckets_per_day: int = 50, n: int = 50, burn_in_days: int = 2) -> list[dict]:
    """Metrics M1-M5 of the pre-registration for each version of VPIN, one replication.

    Buckets in the first `burn_in_days` days are left out for every version, because the
    local sigma needs one day of history (change log, entry 1).
    """
    v_bucket = bars["volume"].sum() / bars["day"].nunique() / buckets_per_day
    edges = bucket_edges_fixed(bars["volume"].sum(), v_bucket)
    informed = fill_buckets(bars["volume"].to_numpy(), bars["informed"].to_numpy(), edges)
    rows = []
    for version, buy in buy_volumes(bars).items():
        b = build_buckets(bars, buy, v_bucket)
        v = vpin(b["buy"], b["sell"], b["volume"], n)
        share = pd.Series(informed).rolling(n).sum().to_numpy() / pd.Series(b["volume"]).rolling(n).sum().to_numpy()
        cdf = cdf_full_sample(v)
        price = b["end_price"].to_numpy()
        ret = np.concatenate([[np.nan], np.abs(price[1:] / price[:-1] - 1)])
        # state of the whole n-bucket window: the bars at its start and at its end must agree
        end_bar = np.searchsorted(bars["ts"].to_numpy(), b["end_ts"].to_numpy())
        start_bar = np.searchsorted(bars["ts"].to_numpy(), b["start_ts"].shift(n - 1).to_numpy())
        valid = np.isfinite(v) & (bars["day"].to_numpy()[end_bar] >= burn_in_days)
        out = {"version": version}
        ok = valid & np.isfinite(share)
        out["M1_tracking"] = float(np.corrcoef(v[ok], share[ok])[0, 1])
        with np.errstate(divide="ignore"):
            x = np.log(np.concatenate([[np.nan], v[:-1]]))
        ok = valid & np.isfinite(x) & np.isfinite(ret)
        out["M4_predictive_corr"] = float(np.corrcoef(x[ok], ret[ok])[0, 1])
        for state, key in [("v_high", "M2_false_alarm"), ("t_high", "M3")]:
            s = bars[state].to_numpy()
            start_state = np.where(start_bar < len(bars), s[np.minimum(start_bar, len(bars) - 1)], False)
            clean = valid & (s[end_bar] == start_state)
            hi, lo = clean & s[end_bar], clean & ~s[end_bar]
            if key == "M2_false_alarm":
                out[key] = float(np.mean(cdf[hi] >= 0.9) - np.mean(cdf[lo] >= 0.9)) if hi.any() and lo.any() else np.nan
            else:
                out["M3_auc"] = auc(v[clean], s[end_bar][clean]) if hi.any() and lo.any() else np.nan
        # M5: standardized VPIN on both block indicators, windows clean in both states
        t, vv = bars["t_high"].to_numpy(), bars["v_high"].to_numpy()
        sb = np.minimum(start_bar, len(bars) - 1)
        clean2 = valid & (t[end_bar] == t[sb]) & (vv[end_bar] == vv[sb])
        if t[end_bar][clean2].std() > 0 and vv[end_bar][clean2].std() > 0:
            z = (v[clean2] - v[clean2].mean()) / v[clean2].std()
            design = np.column_stack([np.ones(clean2.sum()), t[end_bar][clean2], vv[end_bar][clean2]]).astype(float)
            beta = np.linalg.lstsq(design, z, rcond=None)[0]
            out["M5_coef_toxicity"], out["M5_coef_volatility"] = float(beta[1]), float(beta[2])
        else:
            out["M5_coef_toxicity"] = out["M5_coef_volatility"] = np.nan
        rows.append(out)
    return rows
