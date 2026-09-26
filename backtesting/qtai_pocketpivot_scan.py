"""Pocket Pivot(포켓피봇) 상승전조 가설 — 전종목 스캔 + 라벨링 + 대조군 + 검증.

사전등록: results/qtai_pocketpivot_preregistration.md (결과를 보기 전에 작성됨,
이후 이 스크립트가 그 정의를 바꾸는 일은 없다).

## 재사용
`backtesting.daily_cache.load_daily_all`(전종목 일봉 합본 캐시),
`backtesting.t0_forward_return.round_trip_cost_pct`(왕복비용 모델).

## 신규 구현 (사전등록 §10에 명시)
날짜클러스터 부트스트랩 95%CI, Profit Factor/승률/Sharpe(거래단위) 집계 —
이 저장소에 있는 기존 버전들이 이번 데이터 구조(코드+날짜 컬럼의 넓은 패널)와
시그니처가 안 맞아 이 파일 안에서 새로 작성(복붙이 아니라 로직만 같은 원칙 재구현).

## 핵심 트릭 — 미래를 보지 않고 과거 10일 최대 하락일 거래량을 구하는 법
과거방향 롤링(하락일 거래량 중 최근 10일 최댓값)은 표준 `groupby.rolling`.
미래방향 롤링(MFE/MAE, 진입 후 N일간의 최고/최저 종가)은 날짜를 **내림차순으로
정렬한 뒤 같은 backward rolling을 적용하면 원래 순서의 forward rolling이 된다**는
방향 대칭성을 이용한다(코드별 그룹 경계를 깨지 않게 groupby 안에서 수행) —
`backtesting/mfe_mae.py`가 종목-일자 하나짜리 배열에 쓰는
`pd.Series(px[::-1]).rolling(h).max()[::-1]` 트릭을 다종목 패널 전체에 벡터화한
버전이다(반복문 없음).

실행: python -m backtesting.qtai_pocketpivot_scan
"""
from __future__ import annotations

import os
import time

import numpy as np
import pandas as pd

from backtesting.daily_cache import load_daily_all
from backtesting.t0_forward_return import round_trip_cost_pct

RESULTS_DIR = "results"
DOWN_VOL_LOOKBACK = 10          # 원 규칙: 최근 10거래일
MA_SHORT, MA_LONG = 20, 60      # 이 프로젝트 관행(50/200일 대신)
EXTENDED_MAX_PCT = 0.15         # MA20 대비 +15% 이내
TIGHT_RECENT_DAYS, TIGHT_PRIOR_DAYS = 10, 20
HORIZONS = (5, 10, 20, 40, 60)  # 보유거래일
LIQUIDITY_FLOORS = {"3e8": 3e8, "5e8": 5e8, "10e8": 1e9}
LIQUIDITY_PRIMARY = "5e8"
EXTREME_1D_THRESHOLD = 0.40

# §5 실측 분할 경계(전체 패널 유니온 거래일 1,823일의 50/75 percentile, 사전등록 확정)
IS_END = "2022-12-27"
VALIDATION_START, VALIDATION_END = "2022-12-28", "2024-11-08"
OOS_START = "2024-11-11"


def load_panel() -> pd.DataFrame:
    df = load_daily_all()[["code", "date", "open", "high", "low", "close", "volume"]].copy()
    df = df.sort_values(["code", "date"], kind="mergesort").reset_index(drop=True)
    return df


def add_core_signal_columns(df: pd.DataFrame) -> pd.DataFrame:
    """상승일/하락일/최근10일 최대하락거래량/신호코어. 전부 t-1까지(또는 t 당일,
    거래량비교 자체는 원 규칙대로 당일 거래량을 쓴다) 정보만 사용."""
    g = df.groupby("code", sort=False)
    df["pos"] = g.cumcount()  # 0-indexed, 코드 내 몇 번째 거래일인지

    prev_close = g["close"].shift(1)
    df["up_day"] = df["close"] > prev_close          # NaN 비교는 자동 False (d=0 안전)
    df["down_day"] = df["close"] < prev_close

    df["_down_vol_or_nan"] = np.where(df["down_day"], df["volume"], np.nan)
    roll_max_incl_t = g["_down_vol_or_nan"].rolling(DOWN_VOL_LOOKBACK, min_periods=1).max() \
        .reset_index(level=0, drop=True)
    df["_roll_max_incl_t"] = roll_max_incl_t
    # t 포함 롤링을 1행 shift 해야 "t-10..t-1"(t 제외) 창이 된다.
    df["max_down_vol"] = df.groupby("code", sort=False)["_roll_max_incl_t"].shift(1)

    df["eligible_window"] = df["pos"] >= DOWN_VOL_LOOKBACK
    df["checked"] = df["up_day"] & df["eligible_window"]
    df["no_down_day_in_window"] = df["checked"] & df["max_down_vol"].isna()
    df["history_insufficient_skip"] = df["up_day"] & ~df["eligible_window"]
    df["signal_core"] = (
        df["checked"] & df["max_down_vol"].notna() & (df["volume"] > df["max_down_vol"])
    )
    df.drop(columns=["_down_vol_or_nan", "_roll_max_incl_t"], inplace=True)
    return df


def add_context_tags(df: pd.DataFrame) -> pd.DataFrame:
    """MA20/MA60(t-1까지), 과열여부, 눌림타이트(서술 태그). 절대 당일 데이터 안 씀."""
    code_col = df["code"]

    close_roll20 = df.groupby(code_col, sort=False)["close"].rolling(MA_SHORT, min_periods=MA_SHORT) \
        .mean().reset_index(level=0, drop=True)
    df["_ma20"] = close_roll20
    df["ma20_prev"] = df.groupby(code_col, sort=False)["_ma20"].shift(1)

    close_roll60 = df.groupby(code_col, sort=False)["close"].rolling(MA_LONG, min_periods=MA_LONG) \
        .mean().reset_index(level=0, drop=True)
    df["_ma60"] = close_roll60
    df["ma60_prev"] = df.groupby(code_col, sort=False)["_ma60"].shift(1)

    df["uptrend_tag"] = df["ma20_prev"] > df["ma60_prev"]
    prev_close = df.groupby(code_col, sort=False)["close"].shift(1)
    df["not_extended_tag"] = prev_close <= df["ma20_prev"] * (1 + EXTENDED_MAX_PCT)
    df["context_on"] = df["uptrend_tag"] & df["not_extended_tag"]

    df["_range_pct"] = (df["high"] - df["low"]) / df["close"]
    range_roll10 = df.groupby(code_col, sort=False)["_range_pct"].rolling(TIGHT_RECENT_DAYS, min_periods=TIGHT_RECENT_DAYS) \
        .mean().reset_index(level=0, drop=True)
    df["_range10"] = range_roll10
    df["recent10_avg_range"] = df.groupby(code_col, sort=False)["_range10"].shift(1)

    range_roll20 = df.groupby(code_col, sort=False)["_range_pct"].rolling(TIGHT_PRIOR_DAYS, min_periods=TIGHT_PRIOR_DAYS) \
        .mean().reset_index(level=0, drop=True)
    df["_range20"] = range_roll20
    df["prior20_avg_range"] = df.groupby(code_col, sort=False)["_range20"].shift(TIGHT_RECENT_DAYS + 1)

    df["tight_pullback_tag"] = df["recent10_avg_range"] < df["prior20_avg_range"]

    df["_value"] = df["close"] * df["volume"]
    liquidity_roll20 = df.groupby(code_col, sort=False)["_value"].rolling(20, min_periods=20) \
        .mean().reset_index(level=0, drop=True)
    df["liquidity_ma20"] = liquidity_roll20
    for name, floor in LIQUIDITY_FLOORS.items():
        df[f"liquidity_ok_{name}"] = df["liquidity_ma20"] >= floor

    df.drop(columns=["_ma20", "_ma60", "_range_pct", "_range10", "_range20", "_value"], inplace=True)
    return df


def add_entry_and_labels(df: pd.DataFrame) -> pd.DataFrame:
    """진입가(T0+1 시가)와 5개 horizon의 ret/MFE/MAE(구간 종가 기준), 비용반영 net.
    forward rolling은 날짜 내림차순 정렬 후 backward rolling으로 계산(방향 대칭성) —
    반복문 없이 전체 패널을 한 번에 처리."""
    code_col = df["code"]
    df["entry_price"] = df.groupby(code_col, sort=False)["open"].shift(-1)
    df["entry_date"] = df.groupby(code_col, sort=False)["date"].shift(-1)

    df_desc = df.sort_values(["code", "date"], ascending=[True, False], kind="mergesort")
    desc_code_col = df_desc["code"]

    for n in HORIZONS:
        w = n + 1
        # exit_idx = t+1+n 위치의 종가 (ret_N 용)
        df[f"_exit_close_{n}"] = df.groupby(code_col, sort=False)["close"].shift(-(1 + n))

        fwd_max = df_desc.groupby(desc_code_col, sort=False)["close"].rolling(w, min_periods=w) \
            .max().reset_index(level=0, drop=True)
        fwd_min = df_desc.groupby(desc_code_col, sort=False)["close"].rolling(w, min_periods=w) \
            .min().reset_index(level=0, drop=True)
        # fwd_max[s] = max(close[s..s+n]) at ascending position s(=entry_idx candidate).
        # df 의 인덱스에 그대로 정렬 대입 후, "entry_idx=t+1"의 값을 t로 끌어오려고 1행 shift(-1).
        df["_fwd_max_w"] = fwd_max
        df["_fwd_min_w"] = fwd_min
        df[f"_fwd_max_at_entry_{n}"] = df.groupby(code_col, sort=False)["_fwd_max_w"].shift(-1)
        df[f"_fwd_min_at_entry_{n}"] = df.groupby(code_col, sort=False)["_fwd_min_w"].shift(-1)

    df.drop(columns=["_fwd_max_w", "_fwd_min_w"], inplace=True)

    cost = round_trip_cost_pct(df["entry_price"].fillna(1.0).to_numpy())
    df["cost_pct"] = np.where(df["entry_price"].notna(), cost, np.nan)

    for n in HORIZONS:
        ret = df[f"_exit_close_{n}"] / df["entry_price"] - 1
        mfe = df[f"_fwd_max_at_entry_{n}"] / df["entry_price"] - 1
        mae = df[f"_fwd_min_at_entry_{n}"] / df["entry_price"] - 1
        df[f"ret_{n}"] = ret
        df[f"mfe_{n}"] = mfe
        df[f"mae_{n}"] = mae
        df[f"net_ret_{n}"] = ret - df["cost_pct"]
        df[f"net_mfe_{n}"] = mfe - df["cost_pct"]
        df[f"net_mae_{n}"] = mae - df["cost_pct"]
        df.drop(columns=[f"_exit_close_{n}", f"_fwd_max_at_entry_{n}", f"_fwd_min_at_entry_{n}"], inplace=True)

    return df


def add_extreme_flag(df: pd.DataFrame) -> pd.DataFrame:
    prev_close = df.groupby("code", sort=False)["close"].shift(1)
    chg = df["close"] / prev_close - 1
    df["extreme_1d_move"] = chg.abs() > EXTREME_1D_THRESHOLD
    return df


def add_split(df: pd.DataFrame) -> pd.DataFrame:
    conditions = [df["date"] <= IS_END, (df["date"] >= VALIDATION_START) & (df["date"] <= VALIDATION_END),
                  df["date"] >= OOS_START]
    choices = ["IS", "Validation", "OOS"]
    df["split"] = np.select(conditions, choices, default="?")
    return df


def build_full_panel() -> pd.DataFrame:
    t0 = time.time()
    df = load_panel()
    print(f"[1/6] 로드 {time.time()-t0:.1f}s | {len(df):,}행 {df['code'].nunique():,}종목", flush=True)

    t0 = time.time()
    df = add_core_signal_columns(df)
    print(f"[2/6] 신호코어(상승일/하락일/max_down_vol) {time.time()-t0:.1f}s", flush=True)

    t0 = time.time()
    df = add_context_tags(df)
    print(f"[3/6] 컨텍스트 태그(MA20/60, 과열, 눌림, 유동성) {time.time()-t0:.1f}s", flush=True)

    t0 = time.time()
    df = add_entry_and_labels(df)
    print(f"[4/6] 진입가/라벨(5 horizon MFE/MAE) {time.time()-t0:.1f}s", flush=True)

    t0 = time.time()
    df = add_extreme_flag(df)
    df = add_split(df)
    print(f"[5/6] 극단치 플래그/분할 태깅 {time.time()-t0:.1f}s", flush=True)

    return df


def summarize_prereg_prechecks(df: pd.DataFrame) -> dict:
    n_total = len(df)
    n_history_insufficient = int(df["history_insufficient_skip"].sum())
    n_checked = int(df["checked"].sum())
    n_no_down_day = int(df["no_down_day_in_window"].sum())
    n_signal_core = int(df["signal_core"].sum())
    return {
        "total_rows": n_total,
        "n_codes": df["code"].nunique(),
        "date_min": df["date"].min(),
        "date_max": df["date"].max(),
        "n_history_insufficient_skip": n_history_insufficient,
        "n_up_days_checked(pos>=10)": n_checked,
        "n_no_down_day_in_window_skip": n_no_down_day,
        "n_signal_core_raw": n_signal_core,
        "n_extreme_1d_move": int(df["extreme_1d_move"].sum()),
    }


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    full = build_full_panel()

    precheck = summarize_prereg_prechecks(full)
    print("\n=== 지시전제 실측 / 신호탐지 카운트 ===")
    for k, v in precheck.items():
        print(f"  {k}: {v}")
    pd.Series(precheck).to_csv(f"{RESULTS_DIR}/qtai_pocketpivot_prechecks.csv", header=["value"])

    # signals.csv: signal_core=True 행만, 진입가 존재(마지막 행 제외)하는 것만.
    label_cols = []
    for n in HORIZONS:
        label_cols += [f"ret_{n}", f"mfe_{n}", f"mae_{n}", f"net_ret_{n}", f"net_mfe_{n}", f"net_mae_{n}"]
    keep_cols = (["code", "date", "pos", "entry_date", "entry_price", "volume", "max_down_vol",
                  "uptrend_tag", "not_extended_tag", "context_on", "tight_pullback_tag",
                  "liquidity_ma20"] + [f"liquidity_ok_{k}" for k in LIQUIDITY_FLOORS]
                 + ["cost_pct", "extreme_1d_move", "split"] + label_cols)

    signals = full[full["signal_core"]].copy()
    n_signal_no_entry = int(signals["entry_price"].isna().sum())
    signals = signals[signals["entry_price"].notna()].reset_index(drop=True)
    signals = signals[keep_cols]
    signals.to_csv(f"{RESULTS_DIR}/qtai_pocketpivot_signals.csv", index=False)
    print(f"\nsignals.csv 저장: {len(signals):,}행 (신호는 났지만 다음거래일이 없어 "
          f"제외된 행 {n_signal_no_entry}건)")

    # 대조군 원재료·후속 IS/Validation/OOS 분석에 쓸 전체 패널(가벼운 버전)도 저장
    # (재현/재실행 없이 감사 가능하게, 필수 산출물은 아니고 보조자료).
    universe_cols = (["code", "date", "pos", "up_day", "eligible_window", "signal_core",
                      "entry_price", "context_on", "uptrend_tag", "not_extended_tag"]
                     + [f"liquidity_ok_{k}" for k in LIQUIDITY_FLOORS] + ["cost_pct", "split"] + label_cols)
    full[universe_cols].to_parquet(f"{RESULTS_DIR}/qtai_pocketpivot_full_universe_cache.parquet", index=False)
    print("전체 유니버스(대조군용) 캐시 parquet 저장 완료")

    return full, signals


if __name__ == "__main__":
    main()
