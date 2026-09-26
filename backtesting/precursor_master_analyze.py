"""상승전조 마스터 — 단계 5~6: ML importance → 단순규칙 → OOS 1회 적용 → 민감도.

사전등록: docs/PRECURSOR_MASTER_PREREGISTRATION.md §7 기각조건

## 순서 (지시 §7 — 모델보다 importance가 목적)

1. IS로 모델 학습 → **feature importance**(정확도가 목적이 아니다)
2. 상위 피처로 **단순 규칙 2~3개 조건**을 IS에서 선정
3. **OOS에 1회 적용** (OOS 보고 다시 고르지 않는다)
4. 대조군(상시진입·무작위) / 온셋격리 / 종목일반화 / 슬리피지 1.5배

## 왜 importance 상위 = 채택이 아닌가

바로 오늘 측정에서 `tick_speed`가 AUC 0.798인데 **순수익은 대조군보다 나빴다**
(익절률 6배 오르는 동안 손절률이 5배 올라 상쇄). importance는 "관련 있다"를 말할 뿐
"돈이 된다"를 말하지 않는다. **판정은 반드시 순수익과 대조군 대비로 한다.**
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtesting.precursor_master import IS_RANGE, OOS_RANGE, UNIVERSE_CHANGE_RANGE  # noqa: E402
from backtesting.t0_forward_return import round_trip_cost_pct  # noqa: E402

SIGNALS = "results/precursor_master_signals.csv"
MIN_SUCCESS = 10          # 사전등록 §7(f) — 성공사례 10건 미만 칸은 판정불가
META = {"symbol", "date", "t0_sec", "pass_daily", "pass_15min", "prev_close",
        "entry_price", "entry_sec", "time_bucket", "t0_minute"}


def load() -> pd.DataFrame:
    d = pd.read_csv(SIGNALS, low_memory=False, dtype={"symbol": str})
    return d[(d["pass_daily"] == True) & (d["pass_15min"] == True)].copy()  # noqa: E712


def split(d: pd.DataFrame) -> dict[str, pd.DataFrame]:
    def seg(r):
        return d[(d["date"] >= r[0]) & (d["date"] <= r[1])].copy()
    return {"IS": seg(IS_RANGE), "OOS": seg(OOS_RANGE), "제외구간": seg(UNIVERSE_CHANGE_RANGE)}


def net_return(d: pd.DataFrame, horizon: int, target: float,
               slip_mult: float = 1.0) -> np.ndarray:
    """목표 target에 닿으면 target, 아니면 horizon 종료 시점 수익(≈MFE/MAE로 근사 불가하므로
    MAE가 -target보다 깊으면 손절로 본다). **비용은 가격대별**로 뺀다.

    경로는 틱으로 쟀지만 MFE/MAE만 저장했으므로, 여기서는
    "익절선 먼저 닿았는지"를 MFE/MAE 크기 비교로 **근사**한다 — 둘 다 닿은 경우
    순서를 모르므로 **보수적으로 손절 우선**으로 본다(낙관 편향 차단).
    """
    mfe = d[f"mfe_{horizon}m"].to_numpy()
    mae = d[f"mae_{horizon}m"].to_numpy()
    cost = round_trip_cost_pct(d["entry_price"].to_numpy())
    if slip_mult != 1.0:
        cost = cost + 0.001 * (slip_mult - 1.0) * 2
    hit_tp = mfe >= target
    hit_sl = mae <= -target
    gross = np.where(hit_sl, -target, np.where(hit_tp, target, mfe + mae))
    return gross - cost


def day_mean_ci(v: np.ndarray, days: np.ndarray, n_boot: int = 2000,
                seed: int = 0) -> tuple[float, float, float, int]:
    """날짜 단위 평균·부트스트랩 CI. 행 단위로 재면 표본 3만이라 뭐든 유의해진다."""
    ok = np.isfinite(v)
    v, days = v[ok], days[ok]
    if len(v) == 0:
        return np.nan, np.nan, np.nan, 0
    u = np.unique(days)
    per = np.array([v[days == x].mean() for x in u])
    if len(per) < 2:
        return float(per.mean()), np.nan, np.nan, len(v)
    rng = np.random.default_rng(seed)
    b = per[rng.integers(0, len(per), size=(n_boot, len(per)))].mean(axis=1)
    return float(per.mean()), float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5)), len(v)


def evaluate(d: pd.DataFrame, horizon: int, target: float, slip_mult: float = 1.0) -> dict:
    if d.empty:
        return {"n": 0}
    r = net_return(d, horizon, target, slip_mult)
    m, lo, hi, n = day_mean_ci(r, d["date"].to_numpy())
    mfe = d[f"mfe_{horizon}m"].to_numpy()
    return {"n": n, "net": m, "lo": lo, "hi": hi,
            "hit": float(np.nanmean(mfe >= target)),
            "symbols": d["symbol"].nunique(), "days": d["date"].nunique()}


def feature_columns(d: pd.DataFrame) -> list[str]:
    out = []
    for c in d.columns:
        if c in META or c.startswith(("mfe_", "mae_", "brk")):
            continue
        if d[c].dtype.kind in "fiub":
            out.append(c)
    return out
