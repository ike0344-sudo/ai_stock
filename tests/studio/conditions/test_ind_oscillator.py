"""분류 "보조지표" — 정의 식으로 직접 계산한 기대값(MACD·스토캐스틱·ADX·일목·SAR 포함)."""
import numpy as np
import pandas as pd
import pytest

from studio.domain.conditions.indicators import compute
from tests.studio.conditions.helpers import synth_panel
from tests.studio.conditions.ind_helpers import mk, nan_eq, val

nan = np.nan


def test_rsi_signal_is_sma_of_simple_rsi():
    nan_eq(val(mk([1, 2, 1, 2, 1]), "rsi_signal", n=2, m=2), [nan, nan, nan, 50, 50])   # RSI(2)=50 이 계속
    p = synth_panel(n_days=120, n_codes=2, seed=1)
    want = compute(p, "rsi", {"n": 14}).rolling(5).mean()
    np.testing.assert_allclose(compute(p, "rsi_signal", {"n": 14, "m": 5}).to_numpy(), want.to_numpy(), equal_nan=True)


def test_macd_line_signal_hist_hand_computed():
    p = mk([1, 2, 3, 4])
    kw = dict(fast=2, slow=3, sig=2)
    # EMA2(α=2/3): 1, 5/3, 23/9, 95/27 (t1~) / EMA3(α=1/2): 1, 3/2, 9/4, 25/8 (t2~)
    nan_eq(val(p, "macd", **kw), [nan, nan, 23 / 9 - 9 / 4, 95 / 27 - 25 / 8])
    m2, m3 = 11 / 36, 85 / 216
    sig3 = m2 / 3 + 2 * m3 / 3                                    # 신호선 EMA2 는 MACD 값 2개가 모여야 시작
    nan_eq(val(p, "macd_signal", **kw), [nan, nan, nan, sig3])
    nan_eq(val(p, "macd_hist", **kw), [nan, nan, nan, m3 - sig3])
    with pytest.raises(ValueError, match="fast"):
        val(p, "macd", fast=26, slow=12, sig=9)


def test_stochastic_slow_k_and_d():
    p = mk([9, 11, 8, 12], h=[10, 12, 11, 13], l=[8, 9, 7, 10])
    fast = [nan, nan, (8 - 7) / (12 - 7) * 100, (12 - 7) / (13 - 7) * 100]
    nan_eq(val(p, "stoch_k", n=3, k=1, d=2), fast)
    nan_eq(val(p, "stoch_d", n=3, k=1, d=2), [nan, nan, nan, (fast[2] + fast[3]) / 2])
    nan_eq(val(mk([5, 5, 5, 5]), "stoch_k", n=3, k=1, d=1), [nan] * 4)      # 고저 같으면 분모 0 → 값 없음


def test_cci_mean_deviation():
    nan_eq(val(mk([1, 2, 6]), "cci", n=3), [nan, nan, (6 - 3) / (0.015 * ((2 + 1 + 3) / 3))])   # = 100
    nan_eq(val(mk([4, 4, 4]), "cci", n=3), [nan, nan, nan])                                       # 편차 0


def test_adx_and_di_hand_computed_n2():
    p = mk([9, 11, 8, 12], h=[10, 12, 11, 13], l=[8, 9, 7, 8])
    # +DM 2,0,2 / −DM 0,2,0 / TR 3,4,5 → 와일더(α=1/2): +DM 2,1,1.5 / −DM 0,1,0.5 / TR 3,3.5,4.25
    nan_eq(val(p, "plus_di", n=2), [nan, nan, 100 * 1 / 3.5, 100 * 1.5 / 4.25])
    nan_eq(val(p, "minus_di", n=2), [nan, nan, 100 * 1 / 3.5, 100 * 0.5 / 4.25])
    dx3 = 100 * abs(100 * 1.5 / 4.25 - 100 * 0.5 / 4.25) / (100 * 2.0 / 4.25)                     # = 50, dx2 = 0
    nan_eq(val(p, "adx", n=2), [nan, nan, nan, (0 + dx3) / 2])                                    # 25


def test_obv_and_signal():
    p = mk([10, 11, 11, 10], v=[100, 200, 300, 400])
    nan_eq(val(p, "obv"), [0, 200, 200, -200])                     # 같은 종가는 0, 첫 봉 0 에서 시작
    nan_eq(val(p, "obv_signal", m=2), [nan, 100, 200, 0])


def test_obv_catalog_definition_warns_about_panel_start_baseline():
    from studio.domain.conditions.catalog import INDICATORS
    for n in ("obv", "obv_signal"):                                  # 화면은 정의 문구를 그대로 보여준다(카탈로그가 유일한 출처)
        d = INDICATORS[n].definition
        assert "패널 첫 봉 0 기준" in d and "절대값 말고" in d, n


def test_mfi_and_all_up_is_100():
    p = mk([10, 11, 10.5, 12], v=[100] * 4)
    nan_eq(val(p, "mfi", n=2), [nan, nan, 100 * 1100 / (1100 + 1050), 100 * 1200 / (1200 + 1050)])
    nan_eq(val(mk([1, 2, 3, 4]), "mfi", n=2), [nan, nan, 100, 100])   # 자금 유출 0


def test_williams_r_momentum_roc():
    p = mk([9, 11, 8, 12], h=[10, 12, 11, 13], l=[8, 9, 7, 10])
    nan_eq(val(p, "williams_r", n=3), [nan, nan, (12 - 8) / (12 - 7) * -100, (13 - 12) / (13 - 7) * -100])
    nan_eq(val(mk([1, 3, 6, 10]), "momentum", n=2), [nan, nan, 5, 7])
    nan_eq(val(mk([1, 3, 6, 10]), "roc", n=2), [nan, nan, 500, (10 / 3 - 1) * 100])


def test_ichimoku_lines_and_cloud_are_shifted_forward_from_past():
    p = mk(np.arange(1, 13))                                         # c_t = t+1 → (n봉 최고+최저)/2 = c_t − (n−1)/2
    nan_eq(val(p, "ichimoku_conv", n=2)[:4], [nan, 1.5, 2.5, 3.5])
    nan_eq(val(p, "ichimoku_base", n=3)[:4], [nan, nan, 2, 3])
    kw = dict(conv_n=2, base_n=3, span_n=4, shift=2)
    a = val(p, "ichimoku_span_a", conv_n=2, base_n=3, shift=2)
    b = val(p, "ichimoku_span_b", span_n=4, shift=2)
    # raw_a(t) = (conv+base)/2 = c_t − 0.75 (t≥2), 보이는 값 span_a(t) = raw_a(t−2) → t≥4
    nan_eq(a[:8], [nan, nan, nan, nan, 2.25, 3.25, 4.25, 5.25])
    # raw_b(t) = c_t − 1.5 (t≥3) → span_b(t) = raw_b(t−2), t≥5
    nan_eq(b[:8], [nan, nan, nan, nan, nan, 2.5, 3.5, 4.5])
    nan_eq(val(p, "ichimoku_cloud_top", **kw)[3:8], [nan, nan, 3.25, 4.25, 5.25])     # t=5: max(3.25, 2.5)
    nan_eq(val(p, "ichimoku_cloud_bottom", **kw)[3:8], [nan, nan, 2.5, 3.5, 4.5])


def test_envelope_bands_are_percent():
    p = mk([100] * 4)
    nan_eq(val(p, "envelope_upper", n=3, pct=5.0), [nan, nan, 105, 105])
    nan_eq(val(p, "envelope_lower", n=3, pct=5.0), [nan, nan, 95, 95])


def test_bollinger_pctb_and_width():
    p = mk([1, 2, 3])                                                 # SMA=2, σ(모)=√(2/3), k=2
    sd = np.sqrt(2 / 3)
    nan_eq(val(p, "bb_pctb", n=3, k=2.0)[2:], [0.5 + 1 / (4 * sd)])
    nan_eq(val(p, "bb_width", n=3, k=2.0)[2:], [4 * sd / 2 * 100])
    nan_eq(val(mk([5, 5, 5]), "bb_pctb", n=3, k=2.0), [nan, nan, nan])   # 밴드 폭 0


def test_psar_hand_computed_with_reversal():
    h = [10, 11, 12, 13, 13.5, 12.5, 9, 8]
    l = [9, 10, 10.5, 11, 12, 8, 7, 6.5]
    c = [9.5, 10.5, 11.5, 12.5, 13, 8.5, 7.5, 7]
    got = val(mk(c, h=h, l=l), "psar", step=0.1, max=0.3)
    # t1 상승 시작 SAR=직전 저가 9, EP=11 · t2 9.2 → 직전 두 저가(10, 9) 이하로 9 · t3 9.6 · t4 10.62→10.5 ·
    # t5 저가 8 이 SAR 11 을 깨 반전(SAR=직전 극점 13.5) · t6 하락 13.5(직전 두 고가 이상) · t7 12.5
    nan_eq(got, [nan, 9, 9, 9.6, 10.5, 13.5, 13.5, 12.5])


def _ref_psar(h, l, c, step, mx):
    """스칼라 기준 구현(한 종목) — 벡터 구현과 대조용."""
    out = [np.nan] * len(h)
    trend = 0
    sar = ep = af = None
    ph = pl = pc = ph2 = pl2 = None
    for t in range(len(h)):
        if not (np.isfinite(h[t]) and np.isfinite(l[t]) and np.isfinite(c[t])):
            continue
        if trend == 0 and ph is not None:
            up = c[t] >= pc
            trend = 1 if up else -1
            sar = pl if up else ph
            ep = max(ph, h[t]) if up else min(pl, l[t])
            af = step
            out[t] = sar
        elif trend != 0:
            nsar = sar + af * (ep - sar)
            if trend > 0:
                nsar = min([nsar] + [x for x in (pl, pl2) if x is not None])
                rev = l[t] < nsar
                ext = h[t] > ep
            else:
                nsar = max([nsar] + [x for x in (ph, ph2) if x is not None])
                rev = h[t] > nsar
                ext = l[t] < ep
            if rev:
                sar, ep, af, trend = ep, (l[t] if trend > 0 else h[t]), step, -trend
            else:
                sar = nsar
                if ext:
                    ep = h[t] if trend > 0 else l[t]
                    af = min(af + step, mx)
            out[t] = sar
        pl2, ph2 = pl, ph
        ph, pl, pc = h[t], l[t], c[t]
    return out


def test_psar_vectorised_equals_scalar_reference_on_random_walks_with_leading_nan():
    p = synth_panel(n_days=250, n_codes=5, seed=8)
    p.high.iloc[:30, 2] = np.nan   # 상장 전 빈칸 — 종목마다 시작 시점이 다름
    p.low.iloc[:30, 2] = np.nan
    p.close.iloc[:30, 2] = np.nan
    got = compute(p, "psar", {"step": 0.02, "max": 0.2})
    for j in range(5):
        want = _ref_psar(p.high.iloc[:, j].to_numpy(), p.low.iloc[:, j].to_numpy(), p.close.iloc[:, j].to_numpy(), 0.02, 0.2)
        nan_eq(got.iloc[:, j].to_numpy(), want)
    assert (got.iloc[:, 0].dropna() != 0).all() and got.iloc[:, 0].notna().sum() > 200


def test_keltner_bands():
    p = mk([10] * 4, h=[11] * 4, l=[9] * 4)                           # ATR=2, EMA=10
    nan_eq(val(p, "keltner_upper", n=3, mult=2.0), [nan, nan, 14, 14])
    nan_eq(val(p, "keltner_lower", n=3, mult=2.0), [nan, nan, 6, 6])


def test_psy_vr_atr_pct_volatility():
    nan_eq(val(mk([1, 2, 1, 2, 3]), "psy", n=3), [nan, nan, nan, 200 / 3, 200 / 3])
    p = mk([10, 11, 11, 10], v=[100, 200, 300, 400])
    nan_eq(val(p, "vr", n=2), [nan, nan, (200 + 150) / (0 + 150) * 100, (0 + 150) / (400 + 150) * 100])
    nan_eq(val(mk([10] * 4, h=[11] * 4, l=[9] * 4), "atr_pct", n=2), [nan, 20, 20, 20])
    got = val(mk([100, 110, 99, 108.9]), "volatility", n=3)
    nan_eq(got[3:], [np.std([10, -10, 10], ddof=1)], rtol=1e-9)
    assert np.isnan(got[:3]).all()
