# Pre-registration: known-answer simulation and inference package

Written on 21 October 2026, **before** any of the code below was written or run. The SHA-256 of this file is stored in every run manifest of these experiments. This file is not timestamped by an outside service, so the only evidence of its timing is the order of the git history, if it is committed before the results. Changes after the first run go to the change log at the end, with date and reason.

Exception, stated openly: the **all-windows analysis** (section 3) was run once as an exploration before this file was written, to answer the question "do the paper's numbers appear anywhere in our data?". It is reported in full (every window) and labelled exploratory.

## 1. Known-answer simulation

### Why

The paper validates VPIN by Monte Carlo (Appendix A.2, Table A1). That simulation draws buy and sell volumes directly from the PIN model: trades are labelled correctly and there are no prices. In the empirical work, however, the paper labels trades by bulk volume classification (BVC), which needs prices. So the paper never checks whether **VPIN as it computes it** recovers informed trading, or whether it reacts to price volatility that has nothing to do with informed trading. We simulate markets from the paper's own model, add prices, and run the paper's exact pipeline on them, where the true share of informed trading is known.

### Model

- A continuously trading market (like the E-mini), one step per minute, D = 120 days per replication.
- Information periods of 60 minutes. In each, news arrives with probability α; good and bad news are equally likely (δ = 0.5). During news, informed traders arrive at Poisson rate μ per minute on the side of the news (buy on good, sell on bad).
- Uninformed buys and uninformed sells each arrive at Poisson rate ε per minute. Every trade is one unit.
- Log price: Δp_t = λ (B_t − S_t) + σ_pub,t · z_t, with z_t iid N(0, 1). Order flow has a permanent linear impact λ; σ_pub is public-information volatility unrelated to order flow. Informed one-sided flow therefore moves the price in news periods (toxicity-induced volatility, the paper's mechanism).
- Baseline parameters: α = 0.3, μ = 4, ε = 8, λ = 0.25 bp, σ_pub = 1 bp per minute.

### Worlds

Days are grouped into blocks that alternate between a low and a high state.

| World | High state | Everything else |
|---|---|---|
| 0 | none (constant baseline) | baseline |
| T (toxicity) | α = 0.7 in 10-day blocks | baseline |
| V (volatility) | σ_pub = 3 bp and ε = 16 in 10-day blocks (more public volatility and more uninformed volume, as on real turbulent days) | α, μ at baseline: informed trading does not change |
| TV | T's α blocks (10 days) and V's blocks (7 days) at the same time, on different schedules | — |

R = 200 replications per world, seeds 0–199 (offset by world).

### Measures (the same code as for the real data)

One-minute bars → buckets of V = average daily volume / 50 → VPIN over n = 50 buckets → CDF over the whole replication. Three versions of the buy volume:

1. **VPIN_paper**: BVC with σ = standard deviation of one-minute price changes over the whole replication (the paper's method).
2. **VPIN_true**: the true buy volume (the paper's Appendix setting).
3. **VPIN_local**: BVC with σ from the previous 1,440 minutes only (one day). This is our candidate fix: it measures each price change against current volatility, not against the whole sample.

The **true informed share** over the same n buckets is Σ informed volume / Σ volume.

### Metrics, per replication, then mean ± Monte Carlo standard error (s.d./√R) and the 2.5–97.5% range across replications

- **M1 tracking:** corr(VPIN, true informed share), by bucket.
- **M2 false alarms:** in world V, the share of buckets with CDF ≥ 0.9 in high blocks minus low blocks.
- **M3 detection:** in worlds T and TV, AUC of VPIN for telling high-α buckets from low-α buckets. Buckets whose n-bucket window spans a block change are excluded.
- **M4 the paper's predictive test:** corr(ln VPIN_{τ−1}, |r_τ|).
- **M5 separability (world TV):** OLS of standardized VPIN on the two block indicators; standardized coefficients on the α indicator and on the volatility indicator.

### Decision rules (fixed now)

- **D1** (the paper's Appendix claim): VPIN_true tracks informed trading if M1 in world T > 0.5.
- **D2:** VPIN_paper confounds volatility if, in world V, M2 > 0 by more than 3 Monte Carlo standard errors. The same rule is applied to VPIN_true and VPIN_local.
- **D3:** the paper's predictive test cannot tell toxicity from volatility if, in world V (no change in informed trading), M4 for VPIN_paper > 0 by more than 3 Monte Carlo standard errors.
- **D4:** VPIN_local counts as an improvement if (a) its M2 in world V is less than half of VPIN_paper's, and (b) its M3 AUC in world T is at most 0.05 below VPIN_paper's.
- **D5:** only if D4 holds, VPIN_local is applied to the real data with the real-time pipeline: on BTC, its correlation with true-label VPIN against VPIN_paper's; on IVE (2011–2026) and BTC, corr(ln VPIN, next |return|) and lift. All results are reported, whatever they show.

Robustness variant (secondary): prices rounded to a tick equal to the baseline per-minute public s.d. (1 bp). On IVE, about a third of one-minute bars show no price change, so discreteness matters for BVC.

## 2. Inference package

- **I1 ledger:** every test behind a claim in the README, slides or guide gets one row: estimate, standard error (month-block bootstrap or Newey–West), z or t, and family flags. The flags are Bonferroni (family-wise 5%), Benjamini–Hochberg (q < 0.05) and Harvey–Liu–Zhu (|t| > 3). Rows are labelled test / control / descriptive; only "test" rows enter the family.
- **I2 placebo, direction-shuffled VPIN:** each one-minute bar keeps the size of its BVC imbalance |2f − 1| · volume, but its sign is drawn at random (seeds 0–19); VPIN is recomputed. It is compared with the real VPIN on corr(ln VPIN, next |return|) and lift. Samples: IVE 2009–2011 (paper's method), IVE 2011–2026 (real-time) and BTC (real-time). Rule: if the placebo keeps ≥ 80% of the real VPIN's correlation, the direction of trading carries little of VPIN's predictive power in that sample.
- **I3 leave-one-year-out:** corr(ln signal, next |return|) and lift for VPIN and trailing volatility on IVE 2011–2026 (real-time, (50, 250)), and for bulk-classified VPIN, true-label VPIN and volatility on BTC ((50, 50)). Report the minimum, the maximum and the number of sign flips.
- **I4 power:** the minimum detectable correlation at 80% power and 5% two-sided significance, MDE = (1.96 + 0.84) × s.e., for the reproduction correlation at (50, 250), compared with the paper's 0.40.

## 3. All windows (exploratory, run before this file)

The paper's exact in-sample method on every two-year window, starting every six months: IVE 2009–2026 (31 windows) and BTC 2020–2026 (10 windows). σ comes from log price changes because BTC's price varies about 15-fold. Reported: correlation at (50, 250), insurance value, the number of moves above 0.75%, and true-positive rates at (50, 250) and (10, 350).

## Change log

1. **21 October 2026, while coding, before the first run: burn-in.** The pre-registration did not say how to treat the first day, when the one-day σ of VPIN_local does not exist yet. Buckets that end in the first two days of each replication are excluded from all metrics, for every version alike, so the comparison stays fair.
2. **21 October 2026, after the simulation, before D5 was run: "one day" on IVE.** For BTC, which trades around the clock, one day is the previous 1,440 one-minute bars. IVE trades 6.5 hours, so for IVE one day is the previous 390 one-minute bars (one session). This only states what "one day" means; no threshold changed.
