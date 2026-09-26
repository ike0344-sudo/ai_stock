"""Feature Engine — 명세 §7~§16 구현.

## 설계 원칙 3가지

1. **모든 창은 `windows.py`의 `[t-w, t)` 규칙을 쓴다.** Feature마다 창을 새로 짜지 않는다.
2. **선행 연구의 판정을 `prior_verdict`로 박아둔다.** 이 저장소에서 17회 측정한 결과
   이미 무쓸모/역방향으로 확인된 Feature가 있다. **그래도 만든다** — 라벨이 바뀌면 부호도
   바뀐다는 걸 3번 확인했기 때문이다(`tick_speed`가 "5분내 +2%"에서 죽었다가
   "당일 +20%"에서 살아났다). 다만 **분석 단계에서 "이미 N회 기각됨"을 감안해
   더 강한 증거를 요구**하기 위해 표시를 남긴다(다중비교 방어).
3. **실시간에서 그대로 계산 가능한 것만 만든다.** 미래를 보는 Feature는 여기 없다 —
   그건 Label Engine(Phase 3) 몫이다.

호가 기반 Feature(명세 §17)는 **데이터가 없어 만들지 않는다.** 없는 걸 추정해 넣으면
나중에 진짜 호가가 들어왔을 때 과거와 섞여 구분이 안 된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import polars as pl

from .grid import SecondGrid
from .windows import (expanding_mean_per_window, lookback_change, prev_window_sum,
                      ratio, window_sum)

# 기본 창(초). 명세 §7~§9의 1/3/5/10/30/60초를 따른다.
SHORT_WINDOWS = (1, 3, 5, 10, 30, 60)
SPEED_WINDOWS = (1, 3, 5, 10)
ACCEL_WINDOWS = (3, 5, 10)


@dataclass(frozen=True)
class FeatureSpec:
    """Feature 한 개의 정의와 **선행 판정**."""
    name: str
    group: str
    description: str
    prior_verdict: str = "미측정"      # 이 저장소 17회 측정 기준
    prior_note: str = ""

    def is_previously_rejected(self) -> bool:
        return self.prior_verdict.startswith("기각")


# 선행 17회 측정에서 확인된 판정 — 리포트 근거를 같이 남긴다.
PRIOR: dict[str, tuple[str, str]] = {
    "tick_speed": ("유효(라벨의존)",
                   "'60초내 +0.5%' AUC 0.65~0.66으로 최강 / '5분내 +2%'에선 0.52로 죽음 / "
                   "'당일 +20%'에서 0.633으로 부활 — 라벨이 바뀌면 부호도 바뀐다"),
    "value_surge": ("유효(부분)", "초 단위 창(1~10초) AUC 0.58~0.63. 분 단위 창은 무쓸모"),
    "value_speed": ("기각(1회)", "억/분 정의로 AUC 0.436~0.481 — 역방향/무차별"),
    "value_accel": ("기각(3회)", "IC 0.001~0.012로 3개 라벨에서 전부 무쓸모"),
    "buy_ratio": ("기각(6회)", "6회 전부 '매수 비중이 높을수록 오히려 나쁘다' 방향"),
    "buy_sell_gap": ("유효(방향반전)", "순매도 우세가 반등 예고(AUC 0.58~0.59, 부호 반대)"),
    "execution_strength": ("기각(3회)", "체결강도 변화율이 3개 라벨에서 전부 0.5 근방"),
    "price_speed": ("유효(라벨의존)", "분 단위 창에서 IC -0.036~-0.059(평균회귀) / "
                                     "'당일 +20%' 60초 창에선 순방향 AUC 0.655"),
    "cum_value": ("유효(최강)", "누적 거래대금이 적을수록 +20% 확률↑ — 33일·15개월·"
                                "55배 표본에서 문턱 단조성 전부 재현"),
}


def _spec(name: str, group: str, desc: str) -> FeatureSpec:
    base = name.split("__")[0]
    v, n = PRIOR.get(base, ("미측정", ""))
    return FeatureSpec(name=name, group=group, description=desc, prior_verdict=v, prior_note=n)


def compute(grid: SecondGrid) -> tuple[pl.DataFrame, list[FeatureSpec]]:
    """1초 격자 → Feature 행렬(길이 N_SEC). 모든 값은 `[t-w, t)` 정보만 쓴다."""
    g = grid
    cols: dict[str, np.ndarray] = {}
    specs: list[FeatureSpec] = []

    def put(name: str, group: str, desc: str, arr: np.ndarray) -> None:
        cols[name] = arr
        specs.append(_spec(name, group, desc))

    # --- §7 기본: 가격/누적 ---
    put("cum_value", "기본", "장 시작~t 직전 누적 거래대금(원)",
        np.concatenate(([0.0], np.cumsum(g.value)))[:-1])
    put("cum_volume", "기본", "누적 거래량", np.concatenate(([0.0], np.cumsum(g.volume)))[:-1])
    put("cum_trades", "기본", "누적 체결 건수", np.concatenate(([0.0], np.cumsum(g.trades)))[:-1])
    if g.ref_price:
        put("chg_from_ref", "기본", "전일종가 대비 등락률(t-1 기준)",
            np.concatenate(([np.nan], g.price[:-1] / g.ref_price - 1)))

    # --- §7 수익률(과거 방향) ---
    for w in SHORT_WINDOWS:
        put(f"return__{w}s", "가격", f"직전 {w}초 가격 변화율", lookback_change(g.price, w))

    # --- §8 체결금액 ---
    val_w = {}
    for w in SHORT_WINDOWS:
        val_w[w] = window_sum(g.value, w)
        put(f"trade_value__{w}s", "체결금액", f"최근 {w}초 거래대금", val_w[w])
    for w in ACCEL_WINDOWS:
        put(f"value_accel__{w}s", "체결금액",
            f"최근 {w}초 거래대금 / 직전 {w}초 거래대금", ratio(val_w[w], prev_window_sum(g.value, w)))
    for w in SPEED_WINDOWS:
        put(f"value_surge__{w}s", "체결금액",
            f"최근 {w}초 거래대금 / 그때까지 창당 평균",
            ratio(val_w[w], expanding_mean_per_window(g.value, w)))

    # --- §9 체결속도 ---
    trd_w = {}
    for w in SPEED_WINDOWS + (30, 60):
        trd_w[w] = window_sum(g.trades, w)
        put(f"tick_speed__{w}s", "체결속도", f"최근 {w}초 초당 체결 건수", trd_w[w] / w)
    for w in ACCEL_WINDOWS:
        put(f"trade_speed_ratio__{w}s", "체결속도",
            f"최근 {w}초 체결속도 / 그때까지 평균", ratio(trd_w[w] / w, expanding_mean_per_window(g.trades, w) / w))
        put(f"trade_speed_accel__{w}s", "체결속도",
            f"최근 {w}초 체결수 / 직전 {w}초", ratio(trd_w[w], prev_window_sum(g.trades, w)))

    # --- §10~§11 매수/매도, 체결강도 ---
    for w in SPEED_WINDOWS + (30, 60):
        bv, sv = window_sum(g.buy_volume, w), window_sum(g.sell_volume, w)
        bval = window_sum(g.buy_value, w)
        tot_v = window_sum(g.volume, w)
        put(f"buy_ratio__{w}s", "수급", f"최근 {w}초 매수 체결량 비중", ratio(bv, tot_v))
        put(f"buy_sell_gap__{w}s", "수급", f"(매수-매도)/전체 체결량", ratio(bv - sv, tot_v))
        put(f"buy_value_ratio__{w}s", "수급", "매수 체결대금 비중", ratio(bval, val_w.get(w, window_sum(g.value, w))))
        put(f"execution_strength__{w}s", "수급", "매수체결량/매도체결량×100", ratio(bv, sv) * 100)
    for w in ACCEL_WINDOWS:
        cur = ratio(window_sum(g.buy_volume, w), window_sum(g.sell_volume, w)) * 100
        prev = np.full(len(cur), np.nan)
        prev[w:] = cur[: len(cur) - w]
        put(f"execution_strength_change__{w}s", "수급", "체결강도의 직전 창 대비 변화율",
            ratio(cur, prev) - 1)

    # --- §13 체결 간격 ---
    for w in (5, 10, 30):
        # 그 창에 체결이 있었던 초 수 → 평균 간격 근사. 1초 격자라 초 미만은 못 본다(명시).
        act = window_sum(g.has_trade.astype(np.float64), w)
        put(f"active_second_ratio__{w}s", "체결간격", f"최근 {w}초 중 체결이 있던 초 비율", act / w)
        put(f"avg_inter_trade_time__{w}s", "체결간격", f"평균 체결 간격 근사(초)",
            ratio(np.full(len(act), float(w)), trd_w.get(w, window_sum(g.trades, w))))

    # --- §14~§15 가격/거래량 가속도 ---
    for w in ACCEL_WINDOWS:
        r_now = lookback_change(g.price, w)
        r_prev = np.full(len(r_now), np.nan)
        r_prev[w:] = r_now[: len(r_now) - w]
        put(f"price_velocity__{w}s", "가격", f"직전 {w}초 초당 가격 변화율", r_now / w)
        put(f"price_accel__{w}s", "가격", "가격 변화율의 변화(가속도)", r_now - r_prev)
        vol_now = window_sum(g.volume, w)
        put(f"volume_velocity__{w}s", "거래량", f"최근 {w}초 초당 거래량", vol_now / w)
        put(f"volume_accel__{w}s", "거래량", "거래량의 직전 창 대비 배율",
            ratio(vol_now, prev_window_sum(g.volume, w)))

    df = pl.DataFrame({"t_sec": np.arange(len(g.price), dtype=np.int64), **cols})
    return df, specs


def spec_table(specs: list[FeatureSpec]) -> pl.DataFrame:
    """Feature 목록 + 선행 판정. 분석 단계에서 다중비교 방어에 쓴다."""
    return pl.DataFrame([{
        "feature": s.name, "group": s.group, "prior_verdict": s.prior_verdict,
        "previously_rejected": s.is_previously_rejected(),
        "description": s.description, "prior_note": s.prior_note,
    } for s in specs])
