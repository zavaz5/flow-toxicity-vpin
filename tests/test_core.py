"""Unit tests for classification, buckets, VPIN and the CDFs, on tiny hand-made inputs."""
import numpy as np
import pandas as pd
import pytest

from vpin.bars import bar_price_changes, time_bars
from vpin.buckets import bucket_edges_fixed, build_buckets, fill_buckets
from vpin.classify import bvc_buy_fraction, lee_ready, tick_rule
from vpin.metric import cdf_expanding, cdf_full_sample, vpin


def test_bvc_is_half_without_price_change_and_symmetric():
    f = bvc_buy_fraction(np.array([0.0, 1.0, -1.0]), sigma=1.0)
    assert f[0] == pytest.approx(0.5)
    assert f[1] + f[2] == pytest.approx(1.0)       # up and down moves mirror each other
    assert f[1] == pytest.approx(0.8413, abs=1e-4)  # Z(1)


def test_tick_rule_carries_sign_through_zero_ticks():
    assert tick_rule(np.array([10, 11, 11, 10, 10, 12])).tolist() == [1, 1, 1, -1, -1, 1]


def test_lee_ready_uses_quotes_then_tick_rule_at_mid():
    price = np.array([10.0, 10.2, 10.1, 10.1])
    bid = np.array([9.9, 10.0, 10.0, 10.1])
    ask = np.array([10.1, 10.2, 10.2, 10.3])
    # at mid, first trade (tick-rule default +1); above mid -> buy;
    # at mid after a down-tick -> sell; below mid -> sell
    assert lee_ready(price, bid, ask).tolist() == [1, 1, -1, -1]


def test_fill_buckets_splits_a_bar_across_buckets():
    # bar 1: 30 units, all buys; bar 2: 30 units, all sells; buckets of 20
    volume = np.array([30.0, 30.0])
    buy = np.array([30.0, 0.0])
    edges = bucket_edges_fixed(volume.sum(), 20.0)
    assert edges.tolist() == [0, 20, 40, 60]
    assert fill_buckets(volume, buy, edges).tolist() == [20.0, 10.0, 0.0]


def test_build_buckets_reports_the_completing_bar():
    bars = pd.DataFrame({
        "ts": pd.date_range("2010-05-06 09:30", periods=3, freq="min"),
        "close": [1.0, 2.0, 3.0],
        "volume": [10.0, 25.0, 5.0],
    })
    b = build_buckets(bars, buy_volume=np.array([10.0, 0.0, 5.0]), bucket_volume=20.0)
    assert len(b) == 2
    assert b["buy"].tolist() == [10.0, 5.0]            # 10 from bar 1; 5 from bar 3
    assert b["end_price"].tolist() == [2.0, 3.0]       # bar 2 completes bucket 1, bar 3 bucket 2
    assert b["start_ts"].iloc[1] == bars["ts"].iloc[1]  # bucket 2 starts inside bar 2


def test_vpin_equals_average_absolute_imbalance():
    buy = np.array([10.0, 0.0, 5.0, 5.0])
    sell = 10.0 - buy
    v = vpin(buy, sell, np.full(4, 10.0), n=2)
    assert np.isnan(v[0])
    assert v[1] == pytest.approx((10 + 10) / 20)
    assert v[3] == pytest.approx(0.0)


def test_expanding_cdf_never_looks_ahead():
    x = np.array([3.0, 1.0, 2.0, 5.0, 4.0])
    real_time = cdf_expanding(x, min_history=1)
    assert real_time.tolist() == pytest.approx([1.0, 0.5, 2 / 3, 1.0, 0.8])
    # the full-sample CDF of the last point uses all five values
    assert cdf_full_sample(x)[-1] == pytest.approx(0.8)
    assert cdf_full_sample(x)[0] == pytest.approx(0.6)


def test_bar_price_changes_restart_each_day():
    ticks = pd.DataFrame({
        "ts": pd.to_datetime(["2010-05-06 15:59:10", "2010-05-06 15:59:50",
                              "2010-05-07 09:30:05", "2010-05-07 09:30:40"]),
        "price": [10.0, 10.5, 12.0, 12.2],
        "size": [1, 1, 1, 1],
    })
    bars = time_bars(ticks, 60)
    change = bar_price_changes(bars)
    assert change.tolist() == pytest.approx([0.5, 0.2])  # no 10.5 -> 12.0 overnight jump


def test_daily_edges_skip_burn_in_and_follow_each_days_size():
    from vpin.buckets import bucket_edges_daily
    # day 1: no size yet (burn-in); day 2: buckets of 4; day 3: buckets of 5
    edges = bucket_edges_daily(np.array([10.0, 10.0, 10.0]), np.array([np.nan, 4.0, 5.0]))
    # first edge at cum 10 (end of burn-in); buckets ending on day 2 have size 4 (14, 18);
    # buckets ending on day 3 have size 5 (23, 28); the last 2 units stay unfinished
    assert edges.tolist() == [10.0, 14.0, 18.0, 23.0, 28.0]


def test_flash_crash_rule_removes_only_cancelled_trades():
    from vpin.data import drop_cancelled_flash_crash_trades
    ticks = pd.DataFrame({
        "ts": pd.to_datetime(["2010-05-06 14:39:00", "2010-05-06 14:45:00", "2010-05-06 14:49:07",
                              "2010-05-06 15:05:00", "2010-05-07 14:49:07"]),
        "price": [37.0, 33.0, 0.0765, 0.0765, 0.0765],
        "size": [100, 100, 719, 1, 1],
    })
    kept = drop_cancelled_flash_crash_trades(ticks)
    # -11% stays (a real move); the 14:49 penny print goes; outside the window nothing changes
    assert kept["price"].tolist() == [37.0, 33.0, 0.0765, 0.0765]
