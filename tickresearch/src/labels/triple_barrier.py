"""Label Engine — "5분내 +2%" (사전등록: docs/TICKRESEARCH_LABEL_5MIN_2PCT_PREREGISTRATION.md).

## 이 파일이 선행 측정과 다른 단 하나의 핵심

선행(`backtesting/_precursor_fastpath.label_shoot`)은 라벨을
**"앞으로 300초 안에 최고가가 +2%를 닿았나"**로 정의했다. 그래서
**손절을 먼저 크게 맞고 나서 나중에 +2%에 닿아도 양성**이었다.

여기서는 **익절과 손절 중 먼저 닿은 쪽**으로 판정한다. 틱 데이터는 순서를 알기 때문에
이게 가능하고, **이것이 틱이 봉보다 나은 거의 유일한 지점**이다. 이걸 안 쓰면
틱을 쓸 이유가 없다.

선행 정의(`hit`)도 같이 내보낸다 — **선행 결과가 재현되는지 확인**하고, 두 정의의
차이가 얼마나 큰지 실측하기 위해서다(재현 안 되면 둘 중 하나가 틀린 것).

## 진입가

t 시점 신호 → **t 이후 첫 체결가**로 산다. t의 체결가로 사면 낙관적이다
(실측 슬리피지: T0+1초 +0.123%p). 격자는 초 단위라 `price[t]`가 이미 "t초의 마지막
체결가"이므로 **t+1초 이후**를 진입 구간으로 잡는다.

## 비용 — **고정값이 아니다** (사전등록 작성 중 내가 틀렸던 부분)

수수료 0.015%×2 + 세금 0.23% + 슬리피지×2 인데, **슬리피지 편도는
`max(0.1%, 1틱/가격)`**이다. 저가주는 1틱 비율이 0.1%를 훌쩍 넘어 비용이 커진다.

선행 리포트의 "왕복 0.52%"는 **고정 상수가 아니라 그 표본의 평균**이었다
(중앙값 0.48%, 5,000원 0.66% / 91,500원 0.48% / 200,000원 0.76%).
단순 합(0.46%)으로 계산하면 **저가주 비용을 과소평가**한다.

그래서 KRX 호가단위표를 그대로 쓴다 — `backtesting/t0_forward_return.py`에 이미
검증된 `krx_tick_size`가 있어 **중복 구현하지 않고 같은 표를 옮겨 쓴다**
(tickresearch는 독립 실행되므로 import 대신 복제하되, 값이 갈리면 안 되므로
`test_labels.py`가 두 구현의 일치를 검사한다).

`net_return`은 **비용을 뺀 값**이다 — "적중률은 좋은데 돈은 안 되더라"에
17회 중 4번 걸렸기 때문에, 라벨 자체를 순수익으로 둬서 구조적으로 막는다.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..features.grid import N_SEC, SecondGrid

HORIZON_SEC = 300          # 사용자 지시: 5분
TARGET = 0.02              # 사용자 지시: +2%
STOPS = (0.005, 0.01, 0.02)

BARRIER_TP, BARRIER_SL, BARRIER_EXPIRE, BARRIER_NONE = 1, -1, 0, -9


@dataclass(frozen=True)
class LabelResult:
    """진입지점(entries)마다 하나씩. 배열 길이는 모두 len(entries)."""
    entries: np.ndarray            # 진입 t_sec
    entry_price: np.ndarray        # t+1 이후 첫 체결가 (없으면 NaN)
    barrier: np.ndarray            # BARRIER_* (먼저 닿은 쪽)
    exit_sec: np.ndarray           # 청산 시각(t_sec). 만기면 t+HORIZON
    gross_return: np.ndarray       # 비용 전
    net_return: np.ndarray         # 비용 후 ← 본체
    cost: np.ndarray               # 그 진입가에 적용된 왕복 비용률 (가격마다 다르다)
    hit: np.ndarray                # 선행 정의(손절 무시, 최고가 +2% 도달) 0/1
    fwd_return: np.ndarray         # 300초 후 단순 수익률 (대조군)
    ambiguous: np.ndarray          # 같은 초에 익절·손절 둘 다 닿음 → 순서 모름
    stop: float


#  KRX 호가단위표 (원). backtesting/t0_forward_return.py:krx_tick_size 와 같은 표.
TICK_TABLE = ((2_000, 1.0), (5_000, 5.0), (20_000, 10.0), (50_000, 50.0),
              (200_000, 100.0), (500_000, 500.0))


def krx_tick_size(price: np.ndarray) -> np.ndarray:
    """가격 → 최소 호가 간격(원). 배열 전체를 한 번에 처리한다."""
    p = np.asarray(price, dtype=np.float64)
    out = np.full(p.shape, 1_000.0)
    for bound, tick in reversed(TICK_TABLE):
        out = np.where(p < bound, tick, out)
    return out


def round_trip_cost(price: np.ndarray | float, commission: float = 0.00015,
                    tax: float = 0.0023, slippage: float = 0.001) -> np.ndarray:
    """**가격별** 왕복 비용률 = 수수료×2 + 세금 + 슬리피지×2.

    슬리피지 편도는 `max(기본율, 1틱/가격)` — 저가주 과소평가를 막는다.
    고정 0.46%로 계산하면 5,000원짜리 종목의 실제 비용(0.66%)을 크게 놓친다.
    """
    p = np.asarray(price, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        tick_pct = np.where(p > 0, krx_tick_size(p) / p, np.nan)
    return commission * 2 + tax + np.maximum(slippage, tick_pct) * 2


def label(grid: SecondGrid, entries: np.ndarray, stop: float,
          horizon: int = HORIZON_SEC, target: float = TARGET,
          cost: float | None = None) -> LabelResult:
    """triple barrier 라벨.

    entries는 격자 인덱스(t_sec). 각 진입에 대해 `(t, t+horizon]` 구간에서
    익절·손절 중 먼저 닿은 쪽을 찾는다. **t 자신은 진입 구간에 안 넣는다.**
    """
    if not 0 < stop < 1:
        raise ValueError(f"손절폭은 0~1 사이여야 한다: {stop}")
    e = np.asarray(entries, dtype=np.int64)
    n = len(e)

    # (n, horizon) 창 — 진입 t의 다음 초부터. 10초 간격 진입이면 2,341×300으로 작다.
    off = np.arange(1, horizon + 1)
    idx = e[:, None] + off
    inside = idx < N_SEC
    idx = np.clip(idx, 0, N_SEC - 1)

    hi, lo, px = grid.high[idx], grid.low[idx], grid.price[idx]
    # 장 마감을 넘어간 칸은 없는 것으로 — 익절·손절 판정에 끼면 안 된다.
    hi = np.where(inside, hi, -np.inf)
    lo = np.where(inside, lo, np.inf)

    # 진입가 = t 이후 첫 체결가. 체결이 없는 초는 격자가 직전 가격을 유지하므로
    # px[:, 0](= t+1초 가격)이 곧 "t 이후 처음 성립하는 가격"이다.
    p0 = np.where(inside[:, 0], px[:, 0], np.nan)

    tp_px = p0 * (1 + target)
    sl_px = p0 * (1 - stop)
    up = hi >= tp_px[:, None]
    dn = lo <= sl_px[:, None]

    NEVER = horizon + 1
    up_first = np.where(up.any(1), up.argmax(1), NEVER)
    dn_first = np.where(dn.any(1), dn.argmax(1), NEVER)

    barrier = np.where(up_first < dn_first, BARRIER_TP,
                       np.where(dn_first < up_first, BARRIER_SL, BARRIER_EXPIRE))
    # 같은 초에 둘 다 닿음 → 1초 격자로는 순서를 모른다. **보수적으로 손절 처리**하고
    # 몇 건인지 밖으로 내보낸다(사전등록 §4: 5% 넘으면 틱으로 내려가야 한다).
    ambiguous = (up_first == dn_first) & (up_first != NEVER)
    barrier = np.where(ambiguous, BARRIER_SL, barrier)

    hit_idx = np.minimum(up_first, dn_first)
    exit_off = np.where(hit_idx == NEVER, horizon, hit_idx + 1)
    exit_sec = np.minimum(e + exit_off, N_SEC - 1)

    # 청산가: 익절/손절은 barrier 가격에 체결됐다고 본다(슬리피지는 비용에 이미 포함).
    # 만기는 그 시점 가격.
    expire_px = np.where(inside[:, horizon - 1], px[:, horizon - 1], np.nan)
    exit_px = np.where(barrier == BARRIER_TP, tp_px,
                       np.where(barrier == BARRIER_SL, sl_px, expire_px))

    with np.errstate(invalid="ignore"):
        gross = exit_px / p0 - 1
        fwd = expire_px / p0 - 1
    # 비용은 **진입가에 따라 다르다** (저가주는 1틱 비율이 커서 더 비싸다).
    c = round_trip_cost(p0) if cost is None else np.full(n, float(cost))
    net = gross - c

    # 장 마감까지 horizon을 못 채우는 진입은 **라벨을 만들지 않는다**(BARRIER_NONE).
    # 마감에 강제청산한 값을 "5분내 +2%" 라벨에 섞으면 정의가 다른 표본이 들어간다.
    # 이 때문에 15:25 이후 진입지점은 전부 빠진다 — 리포트에 건수를 적는다.
    bad = ~np.isfinite(p0) | (p0 <= 0) | ~inside[:, horizon - 1]
    barrier = np.where(bad, BARRIER_NONE, barrier)
    for a in (gross, net, fwd):
        a[bad] = np.nan

    return LabelResult(entries=e, entry_price=p0, barrier=barrier, exit_sec=exit_sec,
                       gross_return=gross, net_return=net, cost=c,
                       hit=np.where(bad, np.nan, up.any(1).astype(float)),
                       fwd_return=fwd, ambiguous=ambiguous & ~bad, stop=stop)


def breakeven_win_rate(stop: float, target: float = TARGET,
                       cost: float = 0.0052) -> float:
    """이 손익 구조에서 본전이 되는 승률. **결과를 보기 전에 계산해 두는 값이다.**

    cost 기본값 0.0052는 선행 표본(중앙값 91,500원)의 **평균 실측 왕복비용**이다.
    실제 라벨은 종목 가격마다 다른 비용을 쓰므로 이 값은 **어림잡는 기준선**일 뿐이다.
    예: 익절 +2%, 손절 -1% → 0.507 (승률 50.7%를 넘겨야 본전)
    """
    win, loss = target - cost, stop + cost
    return loss / (win + loss)
