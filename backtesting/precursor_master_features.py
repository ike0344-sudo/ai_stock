"""상승전조 마스터 — 단계 3: T0 시점 피처.

## 재사용 (복붙 금지 원칙 — 지시 §0)

기존 `t0_forward_return.compute_stock_day`는 **10초 격자 전체**에 대해 계산한다.
여기서는 **내가 탐지한 T0 시각들에만** 필요하므로, 그 파일의 **하위 함수를 import**해
같은 정의를 그대로 쓴다(`_tick_rule_direction`, `_expanding_period_avg`,
`_shift_window_sum`, `window_sum`). 수식을 옮겨 적지 않았다 —
`_expanding_period_avg(cs, grid, w)`가 grid를 인자로 받아 T0 배열을 그대로 넣을 수 있다.

`divergence`는 `execution_price_divergence.py` 정의 그대로
`price_speed / value_surge`(분모 0/음수는 NaN).

## 신규 피처 (지시 §4)

- `tick_speed` **1/3/5초** — 기존엔 10초 이상만 있었다
- N분 고점 돌파 이진 (scan 단계에서 이미 기록)
- **눌림 후 재가속** 탐지 (스펙 §12) + **온셋 표시**
- 시간대 버킷 9구간 (스펙 §15)

## 미래참조 차단

모든 창은 **t 자신을 제외**한다. `window_sum`은 `[i-w, i)` 를 주고 T0 에서는 i = t-1 에서 읽으므로
실제 창은 `[t-1-w, t-1)` 이다(1초 지연·보수적, 아래 `_win_at` 참고 — 2026-09-26 주석만 정정, 동작 불변).
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _precursor_fastpath import N, SESSION_START, window_sum  # noqa: E402
from backtesting.t0_forward_return import (  # noqa: E402
    _expanding_period_avg, _shift_window_sum, _tick_rule_direction)

# 기존 창(초) + 신규 짧은 창. 지시 §4: 1/3/5초는 새로 만드는 것.
SPEED_WINDOWS = {"w1s": 1, "w3s": 3, "w5s": 5, "w10": 10, "w20": 20, "w30": 30, "w60": 60}
VALUE_WINDOWS = {"v1m": 60, "v3m": 180, "v5m": 300, "v10m": 600}

# 스펙 §15 — 9구간. 장 시작 직후와 마감 직전을 잘게 나눈다(변동성이 다르다).
TIME_BUCKETS = [(0, 10, "09:00-09:10"), (10, 20, "09:10-09:20"), (20, 30, "09:20-09:30"),
                (30, 60, "09:30-10:00"), (60, 120, "10:00-11:00"), (120, 210, "11:00-12:30"),
                (210, 300, "12:30-14:00"), (300, 360, "14:00-15:00"), (360, 391, "15:00-15:30")]


def _win_at(per_sec: np.ndarray, t0s: np.ndarray, w: int) -> np.ndarray:
    """t 자신을 제외한 w 초 합 — 실제 창은 `[t-1-w, t-1)` (t-1 초도 빠진다, 1초 지연).

    `window_sum(x, w)[i]` 는 `[i-w, i)` 합(i 미포함)이고 여기선 i = t-1 에서 읽는다. t 를 포함하면
    "그 순간의 체결"이 신호 계산에 들어가 미래참조가 된다(T0 자체가 돌파 틱이라 특히 위험) — 1초 지연은
    보수적이라 미래참조는 아니다. (주석만 정정 2026-09-26: 예전 문구는 창을 `[t-w, t)` 라 적었으나 동작은 그대로다.
    스튜디오 `tick.py` 의 `[s-w, s)` 값 = 이 함수의 t0 = s+1 값 — P5 보조 테스트로 대조됨.)
    """
    ws = window_sum(per_sec, w)
    idx = t0s - 1
    out = np.full(len(t0s), np.nan)
    ok = idx >= w - 1
    out[ok] = ws[idx[ok]]
    return out


def compute_features(g: dict, t0s: np.ndarray) -> dict[str, np.ndarray]:
    """to_grid 결과 + T0 초 인덱스 배열 → 피처 dict. 전부 `[t-w, t)` 정보만 쓴다."""
    px, vol, cnt = g["px"], g["vol"], g["cnt"]
    tick_sec, tick_prc, tick_qty = g["tick_sec"], g["tick_prc"], g["tick_qty"]
    t0s = np.asarray(t0s, dtype=np.int64)
    out: dict[str, np.ndarray] = {}
    if len(t0s) == 0:
        return out

    d = _tick_rule_direction(tick_prc)
    buy_ps = np.bincount(tick_sec, weights=np.where(d > 0, tick_qty, 0.0), minlength=N)
    sell_ps = np.bincount(tick_sec, weights=np.where(d < 0, tick_qty, 0.0), minlength=N)
    val_ps = np.bincount(tick_sec, weights=tick_prc * tick_qty, minlength=N)
    cs_val = np.concatenate(([0.0], np.cumsum(val_ps)))

    with np.errstate(divide="ignore", invalid="ignore"):
        # --- 체결속도 (신규 1/3/5초 포함) ---
        for k, w in SPEED_WINDOWS.items():
            out[f"{k}_tick_speed"] = _win_at(cnt, t0s, w) / w

        # --- 거래대금 급증 / 매수우위 / 가격속도 / 가속 ---
        for k, w in VALUE_WINDOWS.items():
            wv = _win_at(val_ps, t0s, w)
            wvol = _win_at(vol, t0s, w)
            wb, ws_ = _win_at(buy_ps, t0s, w), _win_at(sell_ps, t0s, w)

            # `_expanding_period_avg`는 grid 위치에 값을 채운 **길이 N 배열**을 돌려준다
            # (원본 t0_forward_return도 `value_surge[T0_GRID]`로 다시 인덱싱한다).
            idx = np.clip(t0s - 1, 0, N - 1)
            avg = _expanding_period_avg(cs_val, idx, w)[idx]
            vs = np.where((avg > 0) & np.isfinite(avg), wv / avg, np.nan)
            out[f"{k}_value_surge"] = vs

            out[f"{k}_buy_ratio"] = np.where(wvol > 0, wb / wvol, np.nan)
            out[f"{k}_buy_sell_gap"] = np.where(wvol > 0, (wb - ws_) / wvol, np.nan)

            # 가격 변화속도: t-1 기준, t 제외
            s = np.clip(t0s - w, 0, N - 1)
            e = np.clip(t0s - 1, 0, N - 1)
            drift = np.where(t0s - w >= 0, px[e] / px[s] - 1, np.nan)
            ps = drift / w
            out[f"{k}_price_speed"] = ps

            # divergence = price_speed / value_surge (execution_price_divergence 정의)
            out[f"{k}_divergence"] = np.where((vs > 0) & np.isfinite(vs), ps / vs, np.nan)

            prev = _shift_window_sum(window_sum(val_ps, w), w)
            pv = np.full(len(t0s), np.nan)
            ok = t0s - 1 >= 0
            pv[ok] = prev[np.clip(t0s - 1, 0, N - 1)][ok]
            out[f"{k}_value_accel"] = np.where(pv > 0, wv / pv - 1, np.nan)

        # --- 당일 누적 거래대금 (실시간 O(1) — 누적값) ---
        # cs_val[k] = sum(val_ps[0:k]) 이므로 cs_val[t0]는 **t0 미포함**이라 안전하다.
        out["cum_value"] = cs_val[np.clip(t0s, 0, N)]
        # `price_t`(T0 그 순간의 체결가)는 **일부러 안 넣는다.** 돌연변이 테스트가
        # "T0 체결을 봤다"고 잡아냈고, 비용 계산에 필요한 가격은 실제 진입가
        # (`mfe_mae`의 entry_price = T0 **다음** 체결가)를 쓰는 게 더 정확하다.

    # --- 시간대 버킷 (스펙 §15) ---
    mins = (t0s + SESSION_START) // 60 - SESSION_START // 60
    bucket = np.full(len(t0s), "기타", dtype=object)
    for lo, hi, name in TIME_BUCKETS:
        bucket[(mins >= lo) & (mins < hi)] = name
    out["time_bucket"] = bucket
    out["t0_minute"] = mins
    return out


# ---------------------------------------------------------------- 눌림 후 재가속 (스펙 §12)

def detect_pullback_reaccel(cnt: np.ndarray, px: np.ndarray, t0: int,
                            w: int = 30, lookback: int = 600) -> dict:
    """T0 직전 `lookback`초에서 "속도↑ → ↓ → 횡보/하락 → 재↑ → 가격 재상승" 구조를 찾는다.

    **온셋 표시를 같이 낸다** — 선행에서 상승 예측으로 보였던 엣지의 46%가
    "이미 랠리 중인 시점"에서 나온 것이었다(2026-09-10). 이 탐지기는 구조상 그 함정에
    특히 걸리기 쉬워서, 탐지 여부와 별개로 "T0 직전에 이미 오르고 있었나"를 같이 준다.

    반환: found(구조 발견), depth(눌림 깊이), already_rising(온셋 표시)
    """
    s = max(0, t0 - lookback)
    if t0 - s < 4 * w:
        return {"pb_found": False, "pb_depth": np.nan, "pb_already_rising": np.nan}

    spd = window_sum(cnt, w)[s:t0] / w        # 구간 내 속도 곡선 (t 제외 구간)
    prc = px[s:t0]
    if len(spd) < 4:
        return {"pb_found": False, "pb_depth": np.nan, "pb_already_rising": np.nan}

    peak = int(np.argmax(spd))                 # 1차 가속 정점
    if peak < w or peak > len(spd) - w:
        found, depth = False, np.nan
    else:
        after = spd[peak:]
        trough = peak + int(np.argmin(after))  # 속도 감소 후 저점
        # 재증가: 저점 이후 속도가 저점의 1.5배 이상으로 회복
        recov = spd[trough:]
        re_up = bool(len(recov) > 1 and recov.max() >= max(spd[trough], 1e-9) * 1.5)
        # 가격 눌림 깊이: 1차 정점 시점 고가 대비 저점 구간 최저
        hi = float(prc[:trough + 1].max()) if trough > 0 else float(prc[0])
        lo = float(prc[peak:trough + 1].min()) if trough > peak else hi
        depth = lo / hi - 1 if hi > 0 else np.nan
        # 가격 재상승: T0 직전 가격이 눌림 저점보다 위
        re_px = bool(prc[-1] > lo)
        found = bool(re_up and re_px and depth < 0)

    # 온셋 표시: T0 직전 5분 동안 이미 +2% 이상 올랐나
    b = max(0, t0 - 300)
    already = bool(px[t0 - 1] / px[b] - 1 >= 0.02) if t0 - 1 > b and px[b] > 0 else False
    return {"pb_found": found, "pb_depth": depth, "pb_already_rising": already}
