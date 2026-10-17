"""Tests for the statistics behind the paper's exhibits."""
import numpy as np
import pandas as pd
import pytest

from vpin import analysis as A
from vpin import paper_numbers as PN
from vpin.buckets import build_buckets
from vpin.metric import cdf_expanding, vpin


@pytest.mark.parametrize("sampling", ["Chrono time", "Volume time"])
def test_jb_star_formula_matches_the_papers_own_table1(sampling):
    """Table 1 prints Skew, Kurt and J-B*. Our reading J-B* = (s^2 + (k-3)^2/4)/6 with raw
    kurtosis k must give back the paper's J-B* from the paper's own s and k."""
    row = PN.TABLE1_50[sampling]
    jb = (row["Skew"] ** 2 + (row["Kurt"] - 3) ** 2 / 4) / 6
    assert jb == pytest.approx(row["J-B*"], rel=1e-3)


def test_max_abs_move_finds_the_largest_pairwise_return():
    p = np.array([100.0, 102.0, 99.0, 101.0, 97.0])
    # largest rise: 99 -> 101 or 100 -> 102 (2.02%); largest fall: 102 -> 97 (4.90%)
    assert A._max_abs_move(p) == pytest.approx(1 - 97 / 102)


def test_intermediate_events_follow_bin_changes():
    cdf = np.array([np.nan, 0.10, 0.12, 0.80, 0.81, 0.82, 0.30, 0.31])
    price = np.array([100, 100, 101, 101, 103, 99, 99, 100.0])
    ev = A.intermediate_events(cdf, price)
    # stays: bin 2 from bucket 1 to 3, bin 16 from 3 to 6; the last stay (bin 6) is open
    assert ev["bin"].tolist() == [2, 16]
    assert ev["start"].tolist() == [1, 3]
    assert ev["max_abs_return"].iloc[1] == pytest.approx(1 - 99 / 103)


def test_conditional_tables_are_normalized():
    rng = np.random.default_rng(0)
    cdf = rng.uniform(0, 1, 5000)
    ret = np.abs(rng.normal(0, 0.004, 5000))
    t4a, t4b = A.conditional_tables(cdf, ret)
    assert np.allclose(t4a.sum(axis=1), 1)
    filled = t4b.notna().any(axis=0)            # return bins with at least one observation
    assert np.allclose(t4b.loc[:, filled].sum(axis=0), 1)
    assert t4b.loc[:, ~filled].isna().all().all()


def test_vpin_does_not_change_when_all_volume_is_rescaled():
    """Paper Eq. 8: multiplying every bar's volume (and V) by beta leaves imbalance shares as they are."""
    rng = np.random.default_rng(1)
    bars = pd.DataFrame({"ts": pd.date_range("2010-01-04 09:30", periods=500, freq="min"),
                         "close": 100 + rng.normal(0, 0.05, 500).cumsum(),
                         "volume": rng.integers(100, 1000, 500).astype(float)})
    share = rng.uniform(0, 1, 500)
    a = build_buckets(bars, bars["volume"] * share, 5000.0)
    scaled = bars.assign(volume=bars["volume"] * 7)
    b = build_buckets(scaled, scaled["volume"] * share, 35000.0)
    va = vpin(a["buy"], a["sell"], a["volume"], 10)
    vb = vpin(b["buy"], b["sell"], b["volume"], 10)
    assert np.allclose(va, vb, equal_nan=True)


def test_expanding_cdf_matches_brute_force():
    rng = np.random.default_rng(2)
    x = rng.normal(size=300)
    x[::37] = x[5]                      # ties
    fast = cdf_expanding(x, min_history=1)
    slow = np.array([np.mean(x[: i + 1] <= x[i]) for i in range(len(x))])
    assert np.allclose(fast, slow)
