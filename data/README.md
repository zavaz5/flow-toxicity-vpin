# Data

Raw data are downloaded by scripts and never committed (`.gitignore`). Only `samples/` is committed: a few hundred rows of each format, made by `python scripts/make_samples.py`.

## IVE ticks (Kibot)

- **What:** every trade in IVE (iShares S&P 500 Value ETF) with the bid and ask in force at the time, from 28 Sep 2009 to 30 Sep 2026.
- **Source:** Kibot's free sample data for the public `guest` account (`http://api.kibot.com`). IVE is the symbol Kibot offers as free tick history. Use is subject to Kibot's terms.
- **Download:** `python scripts/download_kibot.py` writes one gzipped CSV per month to `data/raw/kibot/IVE/IVE_YYYY-MM.csv.gz` (about 50 MB in total). Re-running skips months already downloaded.
- **Raw columns:** `date` (MM/DD/YYYY), `time` (HH:MM:SS, New York), `price`, `bid`, `ask`, `size` (shares). No header.
- **Cleaning** (`vpin.data.load_ive_ticks`): keep 09:30:00–16:00:00 New York time, positive price and size. The parsed ticks are cached in `data/processed/`.

| Sample file | Content |
|---|---|
| `samples/IVE_20100506_ticks.csv` | First trades of the flash-crash day: `ts`, `price`, `bid`, `ask`, `size` |
| `samples/IVE_20100506_bars_1min.csv` | One-minute bars of that day: `ts` (bar start), `open`, `close`, `volume`, `day` |
| `samples/IVE_20100506_buckets_50_50.csv` | VPIN buckets that end on that day (50 buckets per day, n = 50): `end_ts`, `end_price`, `buy`, `sell`, `vpin`, `cdf` |

## BTCUSDT (Binance)

- **What:** Binance USD-M BTCUSDT perpetual futures. One-minute klines from January 2020 to September 2026, and aggregated trades for five days (`configs/pipeline.yaml`, `btc.trade_days`).
- **Source:** Binance public data, `https://data.binance.vision/data/futures/um/`.
- **Download:** `python scripts/download_binance.py` (about 150 MB of klines and 400 MB of trades).
- **Why BTC:** Binance marks the aggressor of every trade. A kline's `taker_buy_volume` is the true buy volume of that minute, which bulk volume classification tries to estimate. For aggregated trades, `is_buyer_maker = true` means the aggressor sold.

| Sample file | Content |
|---|---|
| `samples/BTCUSDT_202510_klines_1min.csv` | `ts` (UTC), `open`, `close`, `volume` (BTC), `taker_buy_volume` (BTC), `count` (trades) |
| `samples/BTCUSDT_20251010_trades.csv` | `ts` (UTC), `price`, `size` (BTC), `true_buy` (aggressor was a buyer) |
