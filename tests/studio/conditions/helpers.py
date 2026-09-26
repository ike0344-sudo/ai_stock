"""조건식 테스트 공용 — Panel 대역(types.SimpleNamespace, 실제 Panel 은 backtest-agent 소유)."""
from types import SimpleNamespace

import numpy as np
import pandas as pd

FIELDS = ("open", "high", "low", "close", "volume")


def panel_from(candles: dict[str, pd.DataFrame], dates=None) -> SimpleNamespace:
    """종목별 OHLCV → 넓은 표 묶음(날짜 합집합 또는 dates, 없는 날은 NaN). value = close×volume."""
    wide = {f: pd.DataFrame({c: d[f] for c, d in candles.items()}).sort_index() for f in FIELDS}
    if dates is not None:
        wide = {f: x.reindex(dates) for f, x in wide.items()}
    return SimpleNamespace(**wide, value=wide["close"] * wide["volume"], prev_close=wide["close"].shift(1))


def synth_candles(n_days: int = 300, n_codes: int = 8, seed: int = 0, start: str = "2023-01-02") -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n_days)
    out = {}
    for k in range(n_codes):
        close = 10_000 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, n_days)))
        open_ = close * (1 + rng.normal(0, 0.005, n_days))
        high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n_days))
        low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n_days))
        vol = rng.integers(100_000, 1_000_000, n_days).astype(float)
        out[f"{k:06d}"] = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx
        )
    return out


def synth_panel(**kw) -> SimpleNamespace:
    return panel_from(synth_candles(**kw))


def tamper_after(panel: SimpleNamespace, t: pd.Timestamp, factor: float = 10.0, fields=FIELDS) -> SimpleNamespace:
    """t **이후** 행만 factor 배로 바꾼 사본 — look-ahead 카나리아용."""
    d = {}
    for f in ("open", "high", "low", "close", "volume", "value", "prev_close"):
        x = getattr(panel, f).copy()
        if f in fields or f in ("value", "prev_close"):
            x.loc[x.index > t] = x.loc[x.index > t] * factor
        d[f] = x
    return SimpleNamespace(**d)


def skew_after(panel: SimpleNamespace, t: pd.Timestamp) -> SimpleNamespace:
    """t **이후** 행을 종목마다 다른 배수(짝수 열 ×10, 홀수 열 ×0.1)로 바꾼 사본 — 종목 간 순위·그룹 지표의 카나리아용
    (전체를 같은 배수로 바꾸면 순위가 안 변해 카나리아가 죽는다). 분봉·일봉 공용."""
    k = np.where(np.arange(panel.close.shape[1]) % 2 == 0, 10.0, 0.1)
    d = {}
    for f in ("open", "high", "low", "close", "volume", "value", "prev_close"):
        x = getattr(panel, f).copy()
        if f == "prev_close":  # 종가만 흔든다 — 같이 흔들면 등락률은 그대로라 등락 기반 지표의 카나리아가 죽는다
            d[f] = x
            continue
        m = (x.index > t)
        x.loc[m] = x.loc[m].to_numpy() * k
        d[f] = x
    return SimpleNamespace(**d)


def field(name: str, offset: int = 0, mul=1.0) -> dict:
    return {"kind": "field", "name": name, "offset": offset, "mul": mul}


def ind(name: str, offset: int = 0, mul=1.0, **params) -> dict:
    return {"kind": "ind", "name": name, "params": params, "offset": offset, "mul": mul}


def const(v) -> dict:
    return {"kind": "const", "value": v}


def cond(left: dict, op: str, right: dict) -> dict:
    return {"left": left, "op": op, "right": right}


def group(logic: str, *items) -> dict:
    return {"logic": logic, "items": list(items)}


def intraday_panel(n_days: int = 6, bars: int = 12, n_codes: int = 4, seed: int = 0, missing=()) -> SimpleNamespace:
    """분봉 Panel 대역 — index = 봉 끝 시각(5분, 09:05~), 여러 날. prev_close = 전일 마지막 봉 종가(하루 안 상수).
    missing = [(행 위치, 종목 열 위치)] 는 그 봉을 NaN(체결 없음)으로 비운다."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2026-08-03", periods=n_days)
    idx = pd.DatetimeIndex([d + pd.Timedelta(hours=9, minutes=5 * (k + 1)) for d in days for k in range(bars)])
    shape = (len(idx), n_codes)
    close = 10_000 * np.exp(np.cumsum(rng.normal(0, 0.003, shape), axis=0))
    open_ = close * (1 + rng.normal(0, 0.001, shape))
    high, low = np.maximum(open_, close) * 1.001, np.minimum(open_, close) * 0.999
    vol = rng.integers(1_000, 10_000, shape).astype(float)
    cols = [f"{k:06d}" for k in range(n_codes)]
    f = {n: pd.DataFrame(a, index=idx, columns=cols) for n, a in
         dict(open=open_, high=high, low=low, close=close, volume=vol).items()}
    for r, c in missing:
        for n in f:
            f[n].iloc[r, c] = np.nan
    last_close = f["close"].groupby(idx.normalize()).last().shift(1)  # 날짜별 전일 마지막 종가
    prev = last_close.reindex(idx.normalize()).set_axis(idx)
    return SimpleNamespace(**f, value=f["close"] * f["volume"], prev_close=prev)
