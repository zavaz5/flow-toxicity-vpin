# Deviations from the paper

Easley, López de Prado and O'Hara (2012), *Flow Toxicity and Liquidity in a High-Frequency World*, Review of Financial Studies 25(5).

Each row gives what we changed, why, and how it affects the comparison. The numbers behind each "effect" are in the files listed there, not typed here.

| # | What | Why | Effect |
|---|---|---|---|
| 1 | **IVE ETF ticks** (iShares S&P 500 Value, Kibot) instead of E-mini S&P 500 futures (CME). WTI crude oil futures are not reproduced. | CME tick data are paid. Kibot gives IVE ticks with the bid and ask in force at each trade, for free, from 28 Sep 2009, and that includes the flash crash. We found no free intraday crude oil data. | IVE is a smaller, slower market than the E-mini. Prices are coarse relative to volatility: many one-minute bars have no price change (`results/reproduction/summary.json`, `share_bars_no_price_change`), and bulk classification splits those bars 50/50. The levels of VPIN are not comparable; the paper itself reads VPIN through its CDF (footnote 19). Figures 8 and 9 (crude oil) are not reproduced. |
| 2 | **Regular session only** (09:30–16:00 New York) | IVE trades before and after hours are thin and often far from the quotes. The E-mini trades almost around the clock. | A bucket can start before the close and end after the next open, so its return includes the overnight gap. We recompute the main correlation without these buckets (`results/reproduction/summary.json`: `corr_50_250_intraday` vs `corr_50_250`, and `share_buckets_spanning_close`). |
| 3 | The first one-minute bar of each day is classified by its own open-to-close change, not by the change from the previous day's last bar | An overnight gap is not order flow inside the bar | Only the first bar of each day is affected |
| 4 | **Sample period 28 Sep 2009 – 15 Aug 2011** instead of 1 Jan 2008 – 15 Aug 2011 | Kibot's IVE history starts in September 2009 | About half as many observations, and the 2008 crisis is missing. Volatility changes less across our sample than across 2008–2011. Because bulk-classified VPIN tracks volatility (extension E3), this alone can lower the VPIN–volatility correlation. |
| 5 | Lee-Ready classification uses the quote recorded with each trade, without the 5-second delay | Kibot stores the bid and ask in force at each trade. The delay corrected slow quote reporting on the 1990s NYSE tape. | None expected |
| 6 | Figure 1 shows IVE's own intraday volume profile; the EUR/USD futures (EC1) panel is omitted | No free EC1 data | Illustration only |
| 8 | **Table 1 is also reported without 6 May 2010, and without overnight changes** (`table1_*_no_crash_day*.csv`), next to the paper's definition (`table1_50.csv`, `table1_100.csv`) | On the flash-crash day IVE itself dislocated: it traded down to about half its price for minutes (trades the exchanges let stand). One such price change is ~100 standard deviations and alone sets the kurtosis of the whole sample. The E-mini fell about 5% that day. Overnight gaps do not exist in a market that trades around the clock. | The paper's comparison (clock vs volume time) is only readable in the robustness views |
| 9 | **Trades cancelled by the exchanges on 6 May 2010 are removed** (`vpin.data.drop_cancelled_flash_crash_trades`) | Kibot keeps 42 IVE prints at prices such as $0.08 (the price was about $37) that the exchanges broke: executed 14:40–15:00 and 60% or more away from the last price at 14:40. They never stood. | Affects only that day; the rule is the exchanges' own |
| 7 | Figure 13 (natural gas "fat finger", 8 June 2011) is not reproduced; extension E4 studies crashes after the paper instead | No free natural gas data | The point "not all volatility is toxic" is tested on other events |

## Decisions where the paper is silent

| Question | Our decision |
|---|---|
| Window for σ<sub>ΔP</sub> in bulk classification (Eq. 7) | Standard deviation of one-minute dollar price changes over the whole reproduction sample (the reading closest to the text). The real-time extension uses the trailing 250 days instead. |
| Window for the CDF of VPIN | Whole sample, as Section 4 says ("We use the entire sample period to determine the cumulative distribution function"). Ties get the highest rank. |
| Price at the end of a bucket | Close of the one-minute bar that completes the bucket |
| Table 1, "equally spaced in time" | 50 (or 100) equal slots of the 390-minute session, last price in each slot. "Equally spaced in volume": the price each time cumulative volume crosses a multiple of ADV / 50. Both samples are cut to the same length T, as the table note says. |
| Table 1 statistics | Kurt is raw kurtosis; J-B* = (s² + (k − 3)² / 4) / 6, i.e. Jarque–Bera / T. This reading reproduces the paper's own J-B* from its own Skew and Kurt (`tests/test_analysis.py`). L-B* is the Ljung–Box Q statistic at 10 lags. White* is the R² of x²<sub>t</sub> on the 55 products x<sub>t−i</sub>x<sub>t−j</sub>, 1 ≤ i ≤ j ≤ 10. |
| Table 3, "prior to" and "after" the flash crash | Before: buckets that end before 6 May 2010. After: from 6 May 2010 on. |
| Flash-crash window in Figure 4 | 14:32–15:08 New York time (start of the E-mini decline to its recovery) |
| ln VPIN when VPIN = 0 | Excluded from the correlation (a perfectly balanced window) |
| Table 4b column ">=2%" | Printed as eight columns; we compare Table 4a (nine columns) cell by cell and Table 4b through its summary claim |
| Section 5.4, the last stay of VPIN in a 5%-tile | Dropped: it never ends inside the sample |

## Extensions: settings that are ours, not the paper's

| Setting | Value | Why |
|---|---|---|
| Real-time σ | Root mean square of one-minute **log** changes over the previous 250 days (at least 60) | Uses only the past. Log changes keep σ comparable when the price moves from $35 to $200 (IVE) or $7k to $120k (BTC). |
| Real-time bucket size | Average daily volume over the previous 250 days / buckets per day | Uses only the past |
| Real-time CDF | Share of all earlier VPIN values ≤ the current one, after 60 days of buckets | Uses only the past |
| Trailing volatility (RV) | Mean \|return\| over the same n buckets as VPIN | The simplest volatility forecast with the same window and timing as VPIN |
| BTC "day" | UTC calendar day | BTC trades 24/7 |
| BTC trade-day buckets | 1/250 of the trailing average daily volume | Enough buckets inside a single day to compare classifiers |
