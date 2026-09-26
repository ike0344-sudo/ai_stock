"""지표 정확도 — 기존 compute_rsi 와 동일, 봉 t 제외 규칙, 카탈로그 전수."""
import numpy as np
import pandas as pd
import pytest

from backtesting.indicators import compute_rsi
from studio.domain.conditions import indicators as I
from studio.domain.conditions.catalog import INDICATORS
from tests.studio.conditions.helpers import synth_panel


@pytest.fixture(scope="module")
def panel():
    return synth_panel(n_days=260, n_codes=6, seed=1)


@pytest.mark.parametrize("n", [2, 5, 14])
def test_rsi_equals_legacy_compute_rsi(panel, n):
    got = I.rsi(panel.close, n)
    for code in panel.close.columns:
        want = pd.to_numeric(compute_rsi(panel.close[code], n))  # pd.NA 가 섞여 object 로 나올 수 있어 숫자로
        pd.testing.assert_series_equal(got[code], want, check_names=False, rtol=0, atol=0)


def test_rsi_zero_loss_is_100_and_warmup_nan():
    close = pd.DataFrame({"a": np.arange(1.0, 31.0), "flat": np.full(30, 5.0)})
    r = I.rsi(close, 14)
    assert (r["a"].iloc[14:] == 100.0).all()          # 연속 상승 = 손실 0 → 100
    assert (r["flat"].iloc[14:] == 100.0).all()       # 변화 없음도 손실 0 → 100 (기존과 같음)
    assert r["a"].iloc[:14].isna().all()              # 워밍업 n 봉은 NaN
    assert compute_rsi(close["flat"], 14).iloc[20] == 100.0


def test_highest_lowest_exclude_current_by_default(panel):
    x = panel.high
    h = I.highest(x, 5)
    for t in (10, 50, 200):
        assert h.iloc[t].equals(x.iloc[t - 5:t].max())       # t 제외
    assert I.highest(x, 5, include_current=True).iloc[50].equals(x.iloc[46:51].max())
    assert I.lowest(panel.low, 7).iloc[60].equals(panel.low.iloc[53:60].min())
    assert h.iloc[:5].isna().all().all()


def test_vol_ratio_excludes_today(panel):
    v = panel.volume
    r = I.vol_ratio(v, 20)
    t = 100
    assert np.allclose(r.iloc[t], v.iloc[t] / v.iloc[t - 20:t].mean())  # rolling mean 은 마지막 자리 오차 가능


def test_change_gap_atr_bollinger_ema(panel):
    c = panel.close
    assert I.change_pct(c, 5).iloc[30].equals((c.iloc[30] / c.iloc[25] - 1) * 100)
    g = I.gap_pct(panel.open, panel.prev_close)
    assert np.allclose(g.iloc[10], (panel.open.iloc[10] / c.iloc[9] - 1) * 100)
    assert I.gap_pct(panel.open, panel.prev_close).iloc[0].isna().all()
    a = I.atr(panel.high, panel.low, c, 14)
    tr = np.maximum.reduce([(panel.high - panel.low).iloc[20:34].to_numpy(),
                            (panel.high - c.shift(1)).abs().iloc[20:34].to_numpy(),
                            (panel.low - c.shift(1)).abs().iloc[20:34].to_numpy()])
    assert np.allclose(a.iloc[33].to_numpy(), tr.mean(axis=0))
    up, lo = I.bollinger(c, 20, 2.0, True), I.bollinger(c, 20, 2.0, False)
    w = c.iloc[81:101]
    assert np.allclose(up.iloc[100], w.mean() + 2 * w.std(ddof=0))
    assert np.allclose(lo.iloc[100], w.mean() - 2 * w.std(ddof=0))
    e = I.ema(c, 10)
    assert e.iloc[:9].isna().all().all() and np.allclose(e.iloc[9:], c.ewm(span=10, adjust=False).mean().iloc[9:])


def test_value_rank_descending_and_ties_and_nan():
    v = pd.DataFrame({"a": [10.0, 5.0], "b": [30.0, 5.0], "c": [20.0, np.nan]})
    r = I.value_rank(v)
    assert r.iloc[0].to_dict() == {"a": 3.0, "b": 1.0, "c": 2.0}
    assert r.iloc[1]["a"] == 1.0 and r.iloc[1]["b"] == 1.0 and np.isnan(r.iloc[1]["c"])  # 동률은 같은 순위
    v2 = pd.DataFrame({"a": [1.0, 1.0, 10.0], "b": [5.0, 5.0, 5.0]})
    assert I.value_rank(v2, lookback=2).iloc[2].to_dict() == {"a": 1.0, "b": 2.0}  # (1+10)/2=5.5 > 5


@pytest.mark.parametrize("name", sorted(INDICATORS))
def test_every_catalog_entry_computes_or_is_declared_pending(panel, name):
    if name in ("day_change_pct", "time", "cum_value", "vwap"):  # 분봉 전용(module-6) — 일봉 표에선 ValueError
        with pytest.raises(ValueError, match="분봉 전용"):
            I.compute(panel, name)
    else:
        assert I.compute(panel, name).shape == panel.close.shape
    assert INDICATORS[name].compute  # 목록 전용(계산 없음)으로 남은 지표는 이제 없다
