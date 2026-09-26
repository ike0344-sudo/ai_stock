"""O(1) 창 집계 primitives — 모든 Feature의 토대.

## 절대 규칙: 창은 `[t-w, t)` 다

**t 자신을 포함하지 않는다.** t 시점에 진입 판단을 한다면 t의 체결은 아직 일어나지
않았거나 그 판단의 결과일 수 있다. 포함하면 미래 참조다.

이 규칙을 여기 한 곳에서만 구현하고 모든 Feature가 이걸 쓴다 —
Feature마다 창을 새로 짜면 어디선가 반드시 한 칸이 밀린다(실제로 겪은 사고:
1분봉 `close`를 읽어 ~1분 밀렸고, 측정 결과가 판정보류로 날아갔다).

## 왜 누적합인가

창 길이가 1초든 600초든 **비용이 같다**(누적합 두 점의 뺄셈). 창을 늘려도 느려지지
않아야 수십 개 Feature × 여러 창을 감당할 수 있다.
"""
from __future__ import annotations

import numpy as np


def window_sum(x: np.ndarray, w: int) -> np.ndarray:
    """`out[t] = x[t-w : t].sum()`. 창이 안 차는 앞 w칸은 NaN.

    NaN으로 두는 이유: 0으로 채우면 "거래가 없었다"와 "아직 창이 안 찼다"가 구분되지
    않아 장 초반 지표가 조용히 왜곡된다.
    """
    if w <= 0:
        raise ValueError(f"창 길이는 1 이상이어야 한다: w={w}")
    n = len(x)
    cs = np.concatenate(([0.0], np.cumsum(x)))
    out = np.full(n, np.nan)
    if n > w:
        out[w:] = cs[w:n] - cs[: n - w]
    return out


def prev_window_sum(x: np.ndarray, w: int) -> np.ndarray:
    """직전 동일 길이 창 `[t-2w, t-w)`. 증가율·가속도 계산의 분모."""
    cur = window_sum(x, w)
    out = np.full(len(x), np.nan)
    if len(x) > w:
        out[w:] = cur[: len(x) - w]
    return out


def ratio(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    """분모가 0이거나 NaN이면 NaN. **0으로 나눠 inf를 만들지 않는다.**

    실제 사고: `value_surge`에서 분모 0일 때 inf가 나와 470만 행 스캔 후 지표 계산
    단계에서 죽었다. 그 뒤로 모든 나눗셈은 이 함수를 거친다.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where((den != 0) & np.isfinite(den) & np.isfinite(num), num / den, np.nan)
    return out


def expanding_mean_per_window(x: np.ndarray, w: int) -> np.ndarray:
    """장 시작부터 `t-w`까지의 **창 길이당 평균**. "평소 대비 몇 배"의 분모.

    인과적이다 — t 시점까지의 정보만 쓴다. 경과한 창 개수가 1개 미만이면 NaN
    (표본이 없는데 평균을 내지 않는다).
    """
    n = len(x)
    cs = np.concatenate(([0.0], np.cumsum(x)))
    out = np.full(n, np.nan)
    t = np.arange(n)
    k = t - w                       # 창 시작 이전까지의 누적
    elapsed = k / w                 # 지나간 창 개수
    ok = (k >= 0) & (elapsed >= 1)
    out[ok] = cs[k[ok]] / elapsed[ok]
    return out


def lookback_change(x: np.ndarray, w: int) -> np.ndarray:
    """`x[t-1] / x[t-1-w] - 1`. 값 배열(가격 등)의 창 구간 변화율.

    **t가 아니라 t-1을 쓴다** — t 시점 가격은 그 순간의 체결 결과라 창에 포함하면
    미래 참조가 된다. 창 규칙 `[t-w, t)`와 같은 맥락.
    """
    n = len(x)
    out = np.full(n, np.nan)
    if n > w + 1:
        end = x[w: n - 1]        # t-1
        start = x[: n - w - 1]   # t-1-w
        out[w + 1:] = ratio(end, start) - 1
    return out
