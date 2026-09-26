"""분류 "보조지표" — 설계 studio-conditions §3.3 `ind_oscillator.py` 표(새 것만; rsi·rsi_wilder·atr·bb_upper·bb_lower 는 기존).

계산 함수는 `fn(panel, p) -> 넓은 표`. 전부 t 까지의 값만 쓴다(일목 선행스팬도 t−26 에 계산된 값을 앞으로 민 것이라 미래참조 없음).
`daily_live`: 설계표 live ✔ 인 지표는 `LIVE` 에 점화식 함수를 등록했다(cci·adx·obv·mfi·vr·일목·SAR·켈트너·변동성은 설계표 "—" 라 일봉 확정값만).

정의 결정(설계가 모호한 곳):
- 평활: EMA = `ewm(span=n, adjust=False, min_periods=n)`, 와일더 = `ewm(alpha=1/n, adjust=False, min_periods=n)`(기존 rsi_wilder 와 같음, 초기값=첫 유효값).
  고전 와일더의 "처음 n개 합/평균으로 시작"과 초기 몇십 봉은 미세하게 다르다.
- `rsi_signal` 은 기존 `rsi`(단순평균 RSI)의 m봉 단순평균.  `stoch_k` = 느린 %K(빠른 %K 의 k봉 SMA), `stoch_d` = 느린 %K 의 d봉 SMA.
  고저가 같아 분모가 0 이면 NaN.
- `obv` 는 **패널 첫 봉을 0 으로 누적**한다 — 절대값이 아니라 추세·신호선 교차로 쓸 것(시작 시점에 따라 전체가 평행이동).
- `keltner_*`·`atr_pct` 의 ATR 은 기존 `atr`(TR 단순평균). `volatility` 는 일간 수익률(%)의 표본표준편차(ddof=1).
- `envelope_*` 의 pct 는 **퍼센트**(5 = ±5%) — 설계표의 `(1 ± pct)` 를 `(1 ± pct/100)` 으로 읽었다(기존 envelope 전략은 0.02 같은 비율).
- `psar` 는 와일더 방식: 두 번째 봉에서 추세를 종가 방향으로 정해 시작, SAR 은 직전 두 봉 저가(상승)/고가(하락)를 넘지 않고,
  반전 시 SAR = 직전 극점(EP), 가속계수는 극점 갱신 때마다 step 씩 max 까지. 출력은 그 봉의 SAR(그 봉 고저가로 반전 여부까지 반영).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .catalog import ParamDef, IndicatorDef, _DAILY_INTRA, _n, register_indicators
from .ind_common import ema, hh, ll, past_roll, prev_ffill, rma, safe_div, sma, true_range, typical_price
from .live_builtin import live_bb_lower, live_bb_upper, live_ema, live_rsi, live_sma  # daily_live 내장 점화식 재사용

Frame = pd.DataFrame


# ------------------------------------------------------------------ 계산
def rsi_signal(panel: Any, p: dict) -> Frame:
    from .indicators import rsi  # 함수 안에서 import — 모듈 로드 순환 방지
    return sma(rsi(panel.close, p["n"]), p["m"])


def _macd_line(panel: Any, p: dict) -> Frame:
    if p["fast"] >= p["slow"]:
        raise ValueError(f"MACD: fast({p['fast']}) 는 slow({p['slow']}) 보다 작아야 함")
    return ema(panel.close, p["fast"]) - ema(panel.close, p["slow"])


def macd(panel: Any, p: dict) -> Frame:
    return _macd_line(panel, p)


def macd_signal(panel: Any, p: dict) -> Frame:
    return ema(_macd_line(panel, p), p["sig"])


def macd_hist(panel: Any, p: dict) -> Frame:
    line = _macd_line(panel, p)
    return line - ema(line, p["sig"])


def _fast_k(panel: Any, n: int) -> Frame:
    top, bot = hh(panel.high, n), ll(panel.low, n)
    return safe_div(panel.close - bot, top - bot) * 100


def stoch_k(panel: Any, p: dict) -> Frame:
    return sma(_fast_k(panel, p["n"]), p["k"])


def stoch_d(panel: Any, p: dict) -> Frame:
    return sma(sma(_fast_k(panel, p["n"]), p["k"]), p["d"])


def cci(panel: Any, p: dict) -> Frame:
    n, tp = p["n"], typical_price(panel)
    mid = sma(tp, n)
    dev = None
    for i in range(n):  # 평균편차 = mean(|TP − SMA_t|) — SMA_t 기준이라 누적합으로는 못 구함(창 n 만큼 표 연산)
        term = (tp.shift(i) - mid).abs()
        dev = term if dev is None else dev + term
    md = dev / n
    return safe_div(tp - mid, 0.015 * md)


def _dm(panel: Any) -> tuple[Frame, Frame]:
    up = panel.high - panel.high.shift(1)
    dn = panel.low.shift(1) - panel.low
    known = up.notna() & dn.notna()
    plus = up.where((up > dn) & (up > 0), 0.0).where(known)
    minus = dn.where((dn > up) & (dn > 0), 0.0).where(known)
    return plus, minus


def _di(panel: Any, n: int) -> tuple[Frame, Frame]:
    plus, minus = _dm(panel)
    tr = rma(true_range(panel).where(plus.notna()), n)  # DM 과 같은 봉부터 시작하게 TR 첫 봉을 뺀다
    return 100 * safe_div(rma(plus, n), tr), 100 * safe_div(rma(minus, n), tr)


def plus_di(panel: Any, p: dict) -> Frame:
    return _di(panel, p["n"])[0]


def minus_di(panel: Any, p: dict) -> Frame:
    return _di(panel, p["n"])[1]


def adx(panel: Any, p: dict) -> Frame:
    pdi, mdi = _di(panel, p["n"])
    dx = 100 * safe_div((pdi - mdi).abs(), pdi + mdi)
    return rma(dx, p["n"])


def obv(panel: Any, p: dict) -> Frame:
    c = panel.close
    step = (np.sign(c.diff()) * panel.volume).fillna(0)
    return step.cumsum().where(c.notna())


def obv_signal(panel: Any, p: dict) -> Frame:
    return sma(obv(panel, p), p["m"])


def mfi(panel: Any, p: dict) -> Frame:
    n, tp = p["n"], typical_price(panel)
    mf, d = tp * panel.volume, tp.diff()
    pos = mf.where(d > 0, 0.0).where(d.notna()).rolling(n).sum()
    neg = mf.where(d < 0, 0.0).where(d.notna()).rolling(n).sum()
    out = (100 - 100 / (1 + pos / neg.where(neg > 0))).where(neg > 0, 100.0)  # 자금 유출 0 이면 100(RSI 와 같은 관례)
    return out.where(neg.notna())


def williams_r(panel: Any, p: dict) -> Frame:
    top, bot = hh(panel.high, p["n"]), ll(panel.low, p["n"])
    return safe_div(top - panel.close, top - bot) * -100


def momentum(panel: Any, p: dict) -> Frame:
    return panel.close - panel.close.shift(p["n"])


def roc(panel: Any, p: dict) -> Frame:
    return (panel.close / panel.close.shift(p["n"]) - 1) * 100


def _mid(panel: Any, n: int) -> Frame:
    return (hh(panel.high, n) + ll(panel.low, n)) / 2


def ichimoku_conv(panel: Any, p: dict) -> Frame:
    return _mid(panel, p["n"])


def ichimoku_base(panel: Any, p: dict) -> Frame:
    return _mid(panel, p["n"])


def _span_a(panel: Any, p: dict) -> Frame:
    # t 에서 보이는 구름 = t−shift 에 계산된 값(앞으로 민 것) → 미래참조 없음
    return ((_mid(panel, p["conv_n"]) + _mid(panel, p["base_n"])) / 2).shift(p["shift"])


def _span_b(panel: Any, p: dict) -> Frame:
    return _mid(panel, p["span_n"]).shift(p["shift"])


def ichimoku_span_a(panel: Any, p: dict) -> Frame:
    return _span_a(panel, p)


def ichimoku_span_b(panel: Any, p: dict) -> Frame:
    return _span_b(panel, p)


def ichimoku_cloud_top(panel: Any, p: dict) -> Frame:
    return np.maximum(_span_a(panel, p), _span_b(panel, p))


def ichimoku_cloud_bottom(panel: Any, p: dict) -> Frame:
    return np.minimum(_span_a(panel, p), _span_b(panel, p))


def envelope_upper(panel: Any, p: dict) -> Frame:
    return sma(panel.close, p["n"]) * (1 + p["pct"] / 100)


def envelope_lower(panel: Any, p: dict) -> Frame:
    return sma(panel.close, p["n"]) * (1 - p["pct"] / 100)


def _bb(panel: Any, n: int, k: float) -> tuple[Frame, Frame, Frame]:
    mid = panel.close.rolling(n).mean()
    sd = panel.close.rolling(n).std(ddof=0)
    return mid + k * sd, mid, mid - k * sd


def bb_pctb(panel: Any, p: dict) -> Frame:
    up, _, lo = _bb(panel, p["n"], float(p["k"]))
    return safe_div(panel.close - lo, up - lo)


def bb_width(panel: Any, p: dict) -> Frame:
    up, mid, lo = _bb(panel, p["n"], float(p["k"]))
    return safe_div(up - lo, mid) * 100


def psar(panel: Any, p: dict) -> Frame:
    step, mx = float(p["step"]), float(p["max"])
    H, L, C = (panel.high.to_numpy(float), panel.low.to_numpy(float), panel.close.to_numpy(float))
    T, K = H.shape
    out = np.full((T, K), np.nan)
    trend = np.zeros(K)                                   # +1 상승 / −1 하락 / 0 아직 시작 전
    sar, ep, af = np.full(K, np.nan), np.full(K, np.nan), np.full(K, step)
    ph, pl, pc, ph2, pl2 = (np.full(K, np.nan) for _ in range(5))  # 직전·전전 봉의 고가·저가, 직전 종가
    for t in range(T):  # 시간 순서 상태 갱신이라 봉 방향은 루프, 종목 방향은 벡터
        h, l, c = H[t], L[t], C[t]
        ok = np.isfinite(h) & np.isfinite(l) & np.isfinite(c)
        st = ok & (trend == 0) & np.isfinite(ph)          # 두 번째 유효 봉: 추세 결정
        if st.any():
            up = c >= pc
            trend = np.where(st, np.where(up, 1.0, -1.0), trend)
            sar = np.where(st, np.where(up, pl, ph), sar)
            ep = np.where(st, np.where(up, np.fmax(ph, h), np.fmin(pl, l)), ep)
            out[t] = np.where(st, sar, out[t])
        run = ok & (trend != 0) & ~st
        if run.any():
            upt = trend > 0
            nsar = sar + af * (ep - sar)
            nsar = np.where(upt, np.fmin(np.fmin(nsar, pl), pl2), np.fmax(np.fmax(nsar, ph), ph2))
            rev = np.where(upt, l < nsar, h > nsar)
            newext = np.where(upt, h > ep, l < ep)
            ep_keep = np.where(newext, np.where(upt, h, l), ep)
            af_keep = np.where(newext, np.minimum(af + step, mx), af)
            sar = np.where(run, np.where(rev, ep, nsar), sar)
            ep_new = np.where(rev, np.where(upt, l, h), ep_keep)
            af = np.where(run, np.where(rev, step, af_keep), af)
            trend = np.where(run & rev, -trend, trend)
            ep = np.where(run, ep_new, ep)
            out[t] = np.where(run, sar, out[t])
        pl2, ph2 = np.where(ok, pl, pl2), np.where(ok, ph, ph2)
        ph, pl, pc = np.where(ok, h, ph), np.where(ok, l, pl), np.where(ok, c, pc)
    return pd.DataFrame(out, index=panel.close.index, columns=panel.close.columns)


def _keltner(panel: Any, p: dict) -> tuple[Frame, Frame]:
    return ema(panel.close, p["n"]), p["mult"] * sma(true_range(panel), p["n"])


def keltner_upper(panel: Any, p: dict) -> Frame:
    mid, band = _keltner(panel, p)
    return mid + band


def keltner_lower(panel: Any, p: dict) -> Frame:
    mid, band = _keltner(panel, p)
    return mid - band


def psy(panel: Any, p: dict) -> Frame:
    c, pc = panel.close, panel.close.shift(1)
    up = (c > pc).astype(float).where(pc.notna() & c.notna())
    return up.rolling(p["n"]).mean() * 100


def vr(panel: Any, p: dict) -> Frame:
    c, pc, v, n = panel.close, panel.close.shift(1), panel.volume, p["n"]
    known = pc.notna() & c.notna()
    uv = v.where(c > pc, 0.0).where(known).rolling(n).sum()
    dv = v.where(c < pc, 0.0).where(known).rolling(n).sum()
    fv = v.where(c == pc, 0.0).where(known).rolling(n).sum()
    return safe_div(uv + fv / 2, dv + fv / 2) * 100


def atr_pct(panel: Any, p: dict) -> Frame:
    return sma(true_range(panel), p["n"]) / panel.close * 100


def volatility(panel: Any, p: dict) -> Frame:
    ret = (panel.close / panel.close.shift(1) - 1) * 100
    return ret.rolling(p["n"]).std(ddof=1)


# ------------------------------------------------------------------ daily_live (D−1 까지 일봉의 과거 집계 + 오늘 가상 봉 항)
# 값은 "오늘 가상 봉을 일봉 끝에 붙여 위 일반 함수로 다시 계산한 값"과 같아야 한다(`timeframe.check_live_equals_recompute`).
def live_rsi_signal(live: Any, p: dict) -> Frame:
    from .indicators import rsi
    n, m = int(p["n"]), int(p["m"])
    today = live_rsi(live, {"n": n})
    if m == 1:
        return today
    return (past_roll(live, lambda pn: rsi(pn.close, n), m - 1, "sum") + today) / m


def _live_macd_line(live: Any, p: dict) -> Frame:
    if p["fast"] >= p["slow"]:
        raise ValueError(f"MACD: fast({p['fast']}) 는 slow({p['slow']}) 보다 작아야 함")
    return live_ema(live, {"src": "close", "n": int(p["fast"])}) - live_ema(live, {"src": "close", "n": int(p["slow"])})


def live_macd(live: Any, p: dict) -> Frame:
    return _live_macd_line(live, p)


def _live_macd_signal(live: Any, p: dict) -> Frame:
    f, s, sig = int(p["fast"]), int(p["slow"]), int(p["sig"])
    a = 2.0 / (sig + 1)
    line = _live_macd_line(live, p)
    day_line = lambda pn: ema(pn.close, f) - ema(pn.close, s)  # noqa: E731
    sig0 = live.prev(live.own(lambda pn: day_line(pn).ewm(span=sig, adjust=False, min_periods=1).mean()))  # D−1 의 신호선 상태
    cnt = live.prev(live.own(lambda pn: day_line(pn).notna().cumsum().astype(float)))                       # 그때까지 유효 MACD 수
    out = (a * line + (1 - a) * sig0).where(sig0.notna(), line)                                             # 이력이 없으면 오늘 값이 씨앗
    return out.where(line.notna() & (cnt >= sig - 1))


def live_macd_signal(live: Any, p: dict) -> Frame:
    return _live_macd_signal(live, p)


def live_macd_hist(live: Any, p: dict) -> Frame:
    return _live_macd_line(live, p) - _live_macd_signal(live, p)


def _live_hh_ll(live: Any, n: int) -> tuple[Frame, Frame]:
    if n == 1:
        return live.h.copy(), live.l.copy()
    top = np.maximum(past_roll(live, lambda pn: pn.high, n - 1, "max"), live.h)
    bot = np.minimum(past_roll(live, lambda pn: pn.low, n - 1, "min"), live.l)
    return top, bot


def _live_fast_k(live: Any, n: int) -> Frame:
    top, bot = _live_hh_ll(live, n)
    return safe_div(live.c - bot, top - bot) * 100


def live_stoch_k(live: Any, p: dict) -> Frame:
    n, k = int(p["n"]), int(p["k"])
    return (past_roll(live, lambda pn: _fast_k(pn, n), k - 1, "sum") + _live_fast_k(live, n)) / k


def live_stoch_d(live: Any, p: dict) -> Frame:
    n, k, d = int(p["n"]), int(p["k"]), int(p["d"])
    return (past_roll(live, lambda pn: sma(_fast_k(pn, n), k), d - 1, "sum") + live_stoch_k(live, p)) / d


def live_williams_r(live: Any, p: dict) -> Frame:
    top, bot = _live_hh_ll(live, int(p["n"]))
    return safe_div(top - live.c, top - bot) * -100


def _base_close(live: Any, n: int) -> Frame:
    return live.prev(live.own(lambda pn: pn.close.shift(n - 1)))  # t−n 종가 = 일봉 D−1 행에서 n−1 봉 전


def live_momentum(live: Any, p: dict) -> Frame:
    return live.c - _base_close(live, int(p["n"]))


def live_roc(live: Any, p: dict) -> Frame:
    return (live.c / _base_close(live, int(p["n"])) - 1) * 100


def live_envelope_upper(live: Any, p: dict) -> Frame:
    return live_sma(live, {"src": "close", "n": int(p["n"])}) * (1 + p["pct"] / 100)


def live_envelope_lower(live: Any, p: dict) -> Frame:
    return live_sma(live, {"src": "close", "n": int(p["n"])}) * (1 - p["pct"] / 100)


def _live_bb(live: Any, p: dict) -> tuple[Frame, Frame, Frame]:
    n, k = int(p["n"]), float(p["k"])
    return (live_bb_upper(live, {"n": n, "k": k}), live_sma(live, {"src": "close", "n": n}),
            live_bb_lower(live, {"n": n, "k": k}))


def live_bb_pctb(live: Any, p: dict) -> Frame:
    up, _, lo = _live_bb(live, p)
    return safe_div(live.c - lo, up - lo)


def live_bb_width(live: Any, p: dict) -> Frame:
    up, mid, lo = _live_bb(live, p)
    return safe_div(up - lo, mid) * 100


def live_psy(live: Any, p: dict) -> Frame:
    n, pc = int(p["n"]), prev_ffill(live, "close")
    today = (live.c > pc).astype(float).where(pc.notna() & live.c.notna())
    if n == 1:
        return today * 100
    up = lambda pn: (pn.close > pn.close.shift(1)).astype(float).where(pn.close.shift(1).notna() & pn.close.notna())  # noqa: E731
    return (past_roll(live, up, n - 1, "sum") + today) / n * 100


def live_atr_pct(live: Any, p: dict) -> Frame:
    n, pc = int(p["n"]), prev_ffill(live, "close")
    tr_today = np.fmax(np.fmax(live.h - live.l, (live.h - pc).abs()), (live.l - pc).abs())
    atr = (past_roll(live, true_range, n - 1, "sum") + tr_today) / n
    return atr / live.c * 100


LIVE = {
    "rsi_signal": live_rsi_signal, "macd": live_macd, "macd_signal": live_macd_signal, "macd_hist": live_macd_hist,
    "stoch_k": live_stoch_k, "stoch_d": live_stoch_d, "williams_r": live_williams_r, "momentum": live_momentum,
    "roc": live_roc, "envelope_upper": live_envelope_upper, "envelope_lower": live_envelope_lower,
    "bb_pctb": live_bb_pctb, "bb_width": live_bb_width, "psy": live_psy, "atr_pct": live_atr_pct,
}


# ------------------------------------------------------------------ 카탈로그
def _d(name: str, label: str, definition: str, params: tuple, example: str, *, vol: bool = False,
       timing: str = "t 포함") -> IndicatorDef:
    return IndicatorDef(name, label, definition, params, _DAILY_INTRA, timing, category="oscillator",
                        definition=definition, example=example, live=name in LIVE, volume_based=vol)


def _f(name: str, default: float, lo: float, hi: float, label: str) -> ParamDef:
    return ParamDef(name, "float", default, lo, hi, label_ko=label)


_MACD_P = (_n(12, "fast"), _n(26, "slow"), _n(9, "sig"))
_ICHI_P = (_n(9, "conv_n"), _n(26, "base_n"), _n(52, "span_n"), _n(26, "shift"))
_BB_P = (_n(20), _f("k", 2.0, 0.1, 10.0, "표준편차 배수"))

DEFS: tuple[IndicatorDef, ...] = (
    _d("rsi_signal", "RSI 신호선", "SMA_m(RSI_n) — RSI 는 기존 rsi(단순평균)", (_n(14), _n(9, "m")), "RSI 가 신호선 상향 돌파"),
    _d("macd", "MACD 선", "EMA_fast(C) − EMA_slow(C)", _MACD_P, "MACD > 0"),
    _d("macd_signal", "MACD 신호선", "EMA_sig(MACD)", _MACD_P, "MACD 가 신호선 상향 돌파"),
    _d("macd_hist", "MACD 히스토그램", "MACD − 신호선", _MACD_P, "MACD 히스토그램 양수 전환"),
    _d("stoch_k", "스토캐스틱 %K(느린)", "빠른 %K=(C−LL_n)÷(HH_n−LL_n)×100 → 느린 %K=SMA_k(빠른 %K)", (_n(14), _n(3, "k"), _n(3, "d")),
       "%K ≤ 20 에서 %D 상향 돌파"),
    _d("stoch_d", "스토캐스틱 %D", "SMA_d(느린 %K)", (_n(14), _n(3, "k"), _n(3, "d")), "%K 가 %D 상향 돌파"),
    _d("cci", "CCI", "(TP − SMA_n(TP)) ÷ (0.015 × 평균편차), TP=(H+L+C)÷3", (_n(20),), "CCI ≥ 100"),
    _d("adx", "ADX", "DX=100×|+DI−−DI|÷(+DI+−DI), ADX=DX 의 와일더 평활(n)", (_n(14),), "ADX ≥ 25 (추세 강함)"),
    _d("plus_di", "+DI", "100 × 와일더평활(+DM) ÷ 와일더평활(TR)", (_n(14),), "+DI 가 −DI 상향 돌파"),
    _d("minus_di", "−DI", "100 × 와일더평활(−DM) ÷ 와일더평활(TR)", (_n(14),), "−DI 가 +DI 상향 돌파"),
    _d("obv", "OBV", "OBV_t = OBV_{t−1} + 부호(C_t−C_{t−1}) × V_t — 패널 첫 봉 0 기준으로 누적한다(시작 시점에 따라 전체가 평행이동). "
       "절대값 말고 추세·신호선 교차로 쓸 것", (), "OBV 가 신호선 위", vol=True),
    _d("obv_signal", "OBV 신호선", "SMA_m(OBV) — OBV 는 패널 첫 봉 0 기준 누적이라 절대값 말고 OBV 와의 교차·방향으로 쓸 것",
       (_n(10, "m"),), "OBV 가 신호선 상향 돌파", vol=True),
    _d("mfi", "MFI", "100 − 100÷(1+ 양의 자금흐름 합÷음의 자금흐름 합), 자금흐름=TP×V (유출 0 이면 100)", (_n(14),), "MFI ≤ 20", vol=True),
    _d("williams_r", "윌리엄스 %R", "(HH_n − C) ÷ (HH_n − LL_n) × −100", (_n(14),), "%R ≥ −20 (과매수)"),
    _d("momentum", "모멘텀", "C_t − C_{t−n}", (_n(10),), "10봉 모멘텀 > 0"),
    _d("roc", "ROC(%)", "(C_t ÷ C_{t−n} − 1) × 100", (_n(12),), "12봉 ROC > 0"),
    _d("ichimoku_conv", "일목 전환선", "(HH_n + LL_n) ÷ 2 (기본 9)", (_n(9),), "종가가 전환선 위"),
    _d("ichimoku_base", "일목 기준선", "(HH_n + LL_n) ÷ 2 (기본 26)", (_n(26),), "전환선이 기준선 상향 돌파"),
    _d("ichimoku_span_a", "일목 선행스팬1", "t 에서 보이는 값 = (전환선+기준선)÷2 를 t−shift 에 계산한 것(미래참조 없음)",
       (_n(9, "conv_n"), _n(26, "base_n"), _n(26, "shift")), "종가가 구름 위", timing="t−shift 에 계산된 값"),
    _d("ichimoku_span_b", "일목 선행스팬2", "t 에서 보이는 값 = (HH_52+LL_52)÷2 를 t−shift 에 계산한 것(미래참조 없음)",
       (_n(52, "span_n"), _n(26, "shift")), "종가가 구름 위", timing="t−shift 에 계산된 값"),
    _d("ichimoku_cloud_top", "일목 구름 상단", "max(선행스팬1, 선행스팬2) — 둘 다 t 에서 보이는 값", _ICHI_P, "종가가 구름 상단 돌파",
       timing="t−shift 에 계산된 값"),
    _d("ichimoku_cloud_bottom", "일목 구름 하단", "min(선행스팬1, 선행스팬2) — 둘 다 t 에서 보이는 값", _ICHI_P, "종가가 구름 하단 이탈",
       timing="t−shift 에 계산된 값"),
    _d("envelope_upper", "엔벨로프 상단", "SMA_n(C) × (1 + pct÷100)", (_n(20), _f("pct", 5.0, 0.1, 50.0, "폭(%)")), "종가 > 엔벨로프 상단"),
    _d("envelope_lower", "엔벨로프 하단", "SMA_n(C) × (1 − pct÷100)", (_n(20), _f("pct", 5.0, 0.1, 50.0, "폭(%)")), "종가 < 엔벨로프 하단"),
    _d("bb_pctb", "볼린저 %b", "(C − 하단) ÷ (상단 − 하단) (밴드 폭 0 이면 값 없음)", _BB_P, "%b ≥ 1 (상단 돌파)"),
    _d("bb_width", "볼린저 폭(%)", "(상단 − 하단) ÷ 중심 × 100", _BB_P, "밴드 폭 5% 이하(수축)"),
    _d("psar", "파라볼릭 SAR", "와일더 SAR — 상승 중엔 종가 아래, 하락 중엔 위. 반전 시 직전 극점",
       (_f("step", 0.02, 0.001, 0.5, "가속 단위"), _f("max", 0.2, 0.01, 1.0, "가속 최대")), "종가가 SAR 위(상승 추세)"),
    _d("keltner_upper", "켈트너 상단", "EMA_n(C) + mult × ATR_n", (_n(20), _f("mult", 2.0, 0.1, 10.0, "ATR 배수")), "종가 > 켈트너 상단"),
    _d("keltner_lower", "켈트너 하단", "EMA_n(C) − mult × ATR_n", (_n(20), _f("mult", 2.0, 0.1, 10.0, "ATR 배수")), "종가 < 켈트너 하단"),
    _d("psy", "투자심리선(%)", "최근 n봉 중 종가가 직전보다 오른 봉의 비율 × 100", (_n(12),), "PSY ≥ 75"),
    _d("vr", "VR(%)", "(상승봉 V 합 + 보합 V 합÷2) ÷ (하락봉 V 합 + 보합 V 합÷2) × 100", (_n(20),), "VR ≥ 450", vol=True),
    _d("atr_pct", "ATR(%)", "ATR_n ÷ C × 100 (ATR=TR 단순평균)", (_n(14),), "ATR(%) ≥ 3"),
    _d("volatility", "변동성(%)", "일간 수익률(%)의 n봉 표본표준편차", (_n(20),), "20일 변동성 ≥ 3%"),
)

COMPUTE = {
    "rsi_signal": rsi_signal, "macd": macd, "macd_signal": macd_signal, "macd_hist": macd_hist,
    "stoch_k": stoch_k, "stoch_d": stoch_d, "cci": cci, "adx": adx, "plus_di": plus_di, "minus_di": minus_di,
    "obv": obv, "obv_signal": obv_signal, "mfi": mfi, "williams_r": williams_r, "momentum": momentum, "roc": roc,
    "ichimoku_conv": ichimoku_conv, "ichimoku_base": ichimoku_base, "ichimoku_span_a": ichimoku_span_a,
    "ichimoku_span_b": ichimoku_span_b, "ichimoku_cloud_top": ichimoku_cloud_top,
    "ichimoku_cloud_bottom": ichimoku_cloud_bottom, "envelope_upper": envelope_upper, "envelope_lower": envelope_lower,
    "bb_pctb": bb_pctb, "bb_width": bb_width, "psar": psar, "keltner_upper": keltner_upper,
    "keltner_lower": keltner_lower, "psy": psy, "vr": vr, "atr_pct": atr_pct, "volatility": volatility,
}

# 설계표에서 live ✔ 인 것(점화식 O(1)) 전부. cci·adx·obv·mfi·vr·일목·SAR·켈트너·변동성은 설계표 live "—" 라 일봉 확정값(daily_prev)만.
LIVE_CANDIDATES = frozenset(LIVE)

register_indicators(DEFS, COMPUTE, LIVE)
