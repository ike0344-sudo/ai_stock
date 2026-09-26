"""상승전조 마스터 연구 — 범위 A(파이프라인 + 패턴탐색).

사전등록: `docs/PRECURSOR_MASTER_PREREGISTRATION.md` (결과 보기 **전**에 작성)

## 이 파일이 재사용하는 것 (복붙 금지 원칙)

- `_precursor_fastpath.to_grid` — 틱 → 1초 격자. **tie-break 수정본**이라 같은 초의
  마지막 체결가가 맞다(원본이 역시간순이라 뒤집지 않으면 45.7%가 틀렸던 사고가 있었다).
  `tick_sec`/`tick_prc`를 같이 돌려주므로 **MFE/MAE는 틱 단위로 정확히** 잴 수 있다.
- `precursor_10_60s.classify_stock_day` — 온셋격리. 선행에서 엣지 46%가 "이미 랠리 중"
  이었음을 밝힌 기준이라 **같은 기준을 써야 비교가 된다**.
- `t0_forward_return.round_trip_cost_pct` — 가격대별 왕복비용(슬리피지 1틱 하한).
- `data_loader._resample_minute` — 날짜 경계를 지키는 리샘플(15:29+다음날 09:00 방지).

## T0를 tick_speed로 정의하지 않는 이유

`tick_speed` 급등을 신호로 삼고 "어떤 피처가 중요한가"를 물으면 `tick_speed`가 1등으로
나오는 게 당연하다 — **평가 대상을 정의에 넣으면 검증이 안 된다.** 그래서 T0는
"최근 N분 고점 돌파"로 정의한다(사전등록 §2).
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _precursor_fastpath import N, SESSION_END, SESSION_START, to_grid  # noqa: E402
from backtesting.data_loader import _resample_minute  # noqa: E402

TICK_DIR = "data/stocks/tick_al"
MINUTE_DIR = "data/stocks/minute"
DAILY_DIR = "data/stocks/daily"

# 사전등록 §5 — 유니버스가 09-21에 126→173종목으로 바뀌므로 그 앞에서만 나눈다.
IS_RANGE = ("2026-08-04", "2026-08-28")
OOS_RANGE = ("2026-09-01", "2026-09-18")
UNIVERSE_CHANGE_RANGE = ("2026-09-21", "2026-09-23")   # 판정에 쓰지 않음, 참고만

T0_BREAKOUT_MINUTES = (1, 3, 5, 10, 20)     # 민감도로 전부 측정
T0_DEFAULT_MINUTES = 5                       # 기본값(사전등록에 고정)
COOLDOWN_SEC = 300                           # 같은 종목 5분 내 재신호 무시
HORIZONS_MIN = (1, 3, 5, 10, 15, 30, 60)     # 스펙 §13
GAP_OPEN_PCT = 0.05                          # 갭시작 제외 기준(확립된 규칙)


# ---------------------------------------------------------------- 단계 1: 상위 시간틀

def load_daily_ma(code: str) -> pd.DataFrame | None:
    """일봉 MA5/10/20/60/120. **shift(1)로 전일까지만** — 당일 종가를 쓰면 미래참조다."""
    p = os.path.join(DAILY_DIR, f"{code}.csv")
    if not os.path.exists(p):
        return None
    d = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()
    if d.empty:
        return None
    out = pd.DataFrame(index=d.index)
    for w in (5, 10, 20, 60, 120):
        out[f"ma{w}"] = d["close"].rolling(w).mean().shift(1)
    out["prev_close"] = d["close"].shift(1)
    out["close"] = d["close"]
    out["high20"] = d["high"].rolling(20).max().shift(1)
    out["high60"] = d["high"].rolling(60).max().shift(1)
    return out


def load_15min_ma(code: str) -> pd.DataFrame | None:
    """1분봉 → **정규장 필터** → 15분 리샘플 → MA60/120.

    정규장 필터가 필수다: 1분봉의 1.4%가 15:35~19:59 시간외인데(실측), 그대로 리샘플하면
    마지막 15분봉에 시간외가 섞여 MA가 오염된다.
    MA는 `shift(1)`로 **완성된 봉만** 본다.
    """
    p = os.path.join(MINUTE_DIR, f"{code}.csv")
    if not os.path.exists(p):
        return None
    d = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()
    t = d.index.time
    d = d[(t >= dt.time(9, 0)) & (t <= dt.time(15, 30))]
    if d.empty:
        return None
    b = _resample_minute(d, 15)
    if len(b) < 121:
        return None
    out = pd.DataFrame(index=b.index)
    out["ma60"] = b["close"].rolling(60).mean().shift(1)
    out["ma120"] = b["close"].rolling(120).mean().shift(1)
    out["close"] = b["close"]
    return out


def passes_daily_filter(ma: pd.DataFrame, day: pd.Timestamp) -> bool | None:
    """MA5 > MA10 > MA20 (전일까지의 정보). 데이터 없으면 None."""
    if day not in ma.index:
        return None
    r = ma.loc[day]
    if pd.isna(r[["ma5", "ma10", "ma20"]]).any():
        return None
    return bool(r["ma5"] > r["ma10"] > r["ma20"])


def passes_15min_filter(ma15: pd.DataFrame, day: pd.Timestamp) -> bool | None:
    """그 날 **첫 봉 시점**의 MA60 > MA120. 장중 변화는 보지 않는다(신호 시점마다
    바뀌면 T0마다 필터가 달라져 해석이 어렵다 — 개장 시점 상태로 고정)."""
    sub = ma15[ma15.index.normalize() == day]
    if sub.empty:
        return None
    r = sub.iloc[0]
    if pd.isna(r[["ma60", "ma120"]]).any():
        return None
    return bool(r["ma60"] > r["ma120"])


# ---------------------------------------------------------------- 단계 2: T0 탐지

def detect_breakouts(px: np.ndarray, window_min: int,
                     cooldown: int = COOLDOWN_SEC) -> np.ndarray:
    """최근 window_min분 고점을 상향 돌파한 초 인덱스.

    창은 `[t-w, t)` — **t 자신을 제외**한다(t의 가격으로 t의 고점을 만들면 절대 못 넘는다).
    쿨다운으로 같은 종목의 촘촘한 재신호를 묶는다(스펙 §20).
    """
    w = window_min * 60
    if len(px) <= w:
        return np.array([], dtype=np.int64)
    # 롤링 최대(과거 w초, t 제외)
    s = pd.Series(px).rolling(w).max().shift(1).to_numpy()
    hit = np.flatnonzero((px > s) & np.isfinite(s))
    if len(hit) == 0:
        return hit
    keep, last = [], -10**9
    for i in hit:
        if i - last >= cooldown:
            keep.append(i)
            last = i
    return np.array(keep, dtype=np.int64)


def is_gap_open(px: np.ndarray, prev_close: float) -> bool:
    """시가가 전일종가 대비 +5% 이상이면 갭시작 — 확립된 제외 규칙.

    갭시작 종목은 누적 거래대금이 0이라 저대금 필터를 자동 통과해 결과를 부풀린 전례가
    있다(OOS +1.51% → 제외 후 +0.20%).
    """
    if not prev_close or not np.isfinite(prev_close) or prev_close <= 0:
        return False
    return bool(px[0] / prev_close - 1 >= GAP_OPEN_PCT)


# ---------------------------------------------------------------- 단계 4: 라벨

def mfe_mae(tick_sec: np.ndarray, tick_prc: np.ndarray, t0: int,
            horizons_min=HORIZONS_MIN) -> dict:
    """T0 이후 각 horizon의 MFE(최대 유리)·MAE(최대 불리). **틱 단위로 잰다.**

    진입가는 **T0 이후 첫 체결가** — T0의 체결가로 사면 낙관적이다
    (실측 진입 슬리피지 T0+1초 +0.123%p).
    장 마감까지 horizon을 못 채우면 그 horizon은 NaN(강제청산 값을 섞지 않는다).
    """
    j0 = int(np.searchsorted(tick_sec, t0, side="right"))   # T0 **다음** 체결부터
    if j0 >= len(tick_sec):
        return {}
    entry = float(tick_prc[j0])
    if entry <= 0:
        return {}
    out = {"entry_price": entry, "entry_sec": int(tick_sec[j0])}
    for h in horizons_min:
        end = t0 + h * 60
        if end > N - 1:                       # 장 마감을 넘으면 라벨 없음
            out[f"mfe_{h}m"] = np.nan
            out[f"mae_{h}m"] = np.nan
            continue
        j1 = int(np.searchsorted(tick_sec, end, side="right"))
        seg = tick_prc[j0:j1]
        if len(seg) == 0:
            out[f"mfe_{h}m"] = 0.0
            out[f"mae_{h}m"] = 0.0
            continue
        out[f"mfe_{h}m"] = float(seg.max() / entry - 1)
        out[f"mae_{h}m"] = float(seg.min() / entry - 1)
    return out
