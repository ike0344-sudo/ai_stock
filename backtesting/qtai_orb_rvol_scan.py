"""ORB x RVOL 상승전조 연구 — 전체 스캔.

사전등록: results/qtai_orb_rvol_preregistration.md (결과 보기 **전** 작성)

data/stocks/minute/*.csv 중 정규장 거래일수 >= 280(census 기준 519종목)을 모집단으로,
고정 오프닝레인지(ORN=5/15/30분) 돌파를 T0로 탐지하고 RVOL_norm/OR_range_pct/대조군
피처 + MFE/MAE/실현수익률 라벨을 계산해 results/qtai_orb_rvol_signals.csv로 저장한다.

data/ 폴더는 읽기 전용으로만 사용(수정/삭제 없음).

실행: python -m backtesting.qtai_orb_rvol_scan [--limit N] [--codes 005930,000660]
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtesting.t0_forward_return import round_trip_cost_pct  # noqa: E402  (재사용)

MINUTE_DIR = "data/stocks/minute"
CENSUS_CSV = "results/qtai_orb_rvol_census.csv"
OUT_CSV = "results/qtai_orb_rvol_signals.csv"

CENSUS_MIN_DAYS = 280          # §1 모집단 채택 기준 (292거래일 안팎)
ORN_LIST = (5, 15, 30)         # 오프닝 레인지 길이(분), 기본값 15
GAP_PCT = 0.03                 # 갭업 시작 제외 기준 (전일 OR고가/종가 대비)
HORIZONS = (1, 3, 5, 10, 15, 30, 60)
MAX_HORIZON = 60
RVOL_LOOKBACK_DAYS = 20        # RVOL_norm 분모용 과거 유효 거래일 수

SESSION_START_MOD = 9 * 60          # 540 (09:00)
SESSION_END_MOD = 15 * 60 + 30      # 930 (15:30, 포함)
FULL_GRID = np.arange(SESSION_START_MOD, SESSION_END_MOD + 1)  # 391칸


def load_population(min_days: int = CENSUS_MIN_DAYS) -> list[str]:
    census = pd.read_csv(CENSUS_CSV)
    pop = census[census["n_days"] >= min_days]["code"].astype(str).tolist()
    return sorted(pop)


def _load_regular_session(code: str) -> pd.DataFrame | None:
    path = os.path.join(MINUTE_DIR, f"{code}.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    mod = df["date"].dt.hour * 60 + df["date"].dt.minute
    reg = (mod >= SESSION_START_MOD) & (mod <= SESSION_END_MOD)
    df = df[reg].copy()
    if df.empty:
        return None
    df["minute_of_day"] = mod[reg].astype(int)
    df["day"] = df["date"].dt.normalize()
    df = df.sort_values(["day", "minute_of_day"])
    df = df.drop_duplicates(subset=["day", "minute_of_day"], keep="last")
    return df.reset_index(drop=True)


def _build_day_arrays(df: pd.DataFrame) -> tuple[list[pd.Timestamp], list[dict]]:
    """day별 정렬된 numpy 배열 딕셔너리 리스트를 만든다 (날짜 경계를 넘지 않는 처리)."""
    days = sorted(df["day"].unique())
    day_arrays = []
    for d in days:
        g = df[df["day"] == d]
        day_arrays.append({
            "mod": g["minute_of_day"].to_numpy(),
            "open": g["open"].to_numpy(dtype=float),
            "high": g["high"].to_numpy(dtype=float),
            "low": g["low"].to_numpy(dtype=float),
            "close": g["close"].to_numpy(dtype=float),
            "volume": g["volume"].to_numpy(dtype=float),
        })
    return days, day_arrays


def _build_cumvol_matrix(day_arrays: list[dict]) -> np.ndarray:
    """[일자 x 391분] 누적거래량 행렬 (forward-fill, 시작 전은 0) — RVOL_norm 분모용."""
    n = len(day_arrays)
    mat = np.zeros((n, len(FULL_GRID)), dtype=float)
    for i, arr in enumerate(day_arrays):
        mod, vol = arr["mod"], arr["volume"]
        s = pd.Series(vol, index=mod).groupby(level=0).sum().sort_index()
        cv = s.cumsum()
        reindexed = cv.reindex(FULL_GRID, method="ffill")
        mat[i, :] = reindexed.fillna(0.0).to_numpy()
    return mat


def process_stock(code: str) -> list[dict]:
    df = _load_regular_session(code)
    if df is None or df.empty:
        return []
    days, day_arrays = _build_day_arrays(df)
    if len(days) < RVOL_LOOKBACK_DAYS + 1:
        return []
    cumvol_mat = _build_cumvol_matrix(day_arrays)

    rows: list[dict] = []
    prev_or_high = {orn: None for orn in ORN_LIST}
    prev_close = None

    for day_idx, (d, arr) in enumerate(zip(days, day_arrays)):
        mod, o, h, l, c, v = (arr["mod"], arr["open"], arr["high"], arr["low"],
                               arr["close"], arr["volume"])
        day_open_actual = float(o[0])

        for orn in ORN_LIST:
            or_end_mod = SESSION_START_MOD + orn
            in_or = mod < or_end_mod
            if not in_or.any():
                continue
            or_high = float(h[in_or].max())
            or_low = float(l[in_or].min())
            or_open = float(o[in_or][0])

            ref = prev_or_high[orn] if prev_or_high[orn] is not None else prev_close
            gap_excluded = bool(ref is not None and ref > 0 and
                                 (day_open_actual / ref - 1.0) >= GAP_PCT)

            # 다음날 갭체크를 위해 오늘 OR고가는 항상 갱신 (오늘이 갭제외라도 갱신)
            prev_or_high[orn] = or_high

            if gap_excluded:
                continue
            if day_idx < RVOL_LOOKBACK_DAYS:
                # RVOL_norm 히스토리 부족 — 사전등록: 이 종목/일 신호는 전부 제외
                continue

            post = mod >= or_end_mod
            post_idx = np.flatnonzero(post)
            if post_idx.size == 0:
                continue
            hit_mask = c[post_idx] > or_high
            if not hit_mask.any():
                continue
            t0_row_idx = int(post_idx[np.argmax(hit_mask)])
            breakout_mod = int(mod[t0_row_idx])
            t0_mod = breakout_mod + 1

            if t0_mod + (MAX_HORIZON - 1) > SESSION_END_MOD:
                continue  # 60분 라벨 완결 불가 → 신호 미생성

            entry_pos = np.searchsorted(mod, t0_mod, side="left")
            if entry_pos >= len(mod) or mod[entry_pos] != t0_mod:
                continue  # 진입봉 없음(드묾) — 신호 미생성
            entry_price = float(o[entry_pos])
            if entry_price <= 0:
                continue

            pre_mask_idx = np.searchsorted(mod, breakout_mod - 5, side="left")
            if pre_mask_idx < len(mod) and mod[pre_mask_idx] == breakout_mod - 5:
                pre_close = float(c[pre_mask_idx])
                ret_5min_pre = (c[t0_row_idx] / pre_close - 1.0) if pre_close > 0 else np.nan
            else:
                ret_5min_pre = np.nan

            up_to_breakout = mod <= breakout_mod
            cum_vol_today = float(v[up_to_breakout].sum())
            cum_value_today = float((c[up_to_breakout] * v[up_to_breakout]).sum())
            or_range_pct = (or_high - or_low) / or_open if or_open > 0 else np.nan

            col = breakout_mod - SESSION_START_MOD
            hist_vals = cumvol_mat[day_idx - RVOL_LOOKBACK_DAYS:day_idx, col]
            denom = float(hist_vals.mean())
            rvol_norm = (cum_vol_today / denom) if denom > 0 else np.nan

            row = {
                "symbol": code, "date": d.date().isoformat(), "day_idx": day_idx,
                "orn": orn, "breakout_mod": breakout_mod, "t0_mod": t0_mod,
                "or_high": or_high, "or_low": or_low, "or_open": or_open,
                "or_range_pct": or_range_pct,
                "entry_price": entry_price,
                "cum_vol_today": cum_vol_today, "cum_value_today": cum_value_today,
                "ret_5min_pre": ret_5min_pre,
                "rvol_norm": rvol_norm,
            }

            valid_row = True
            for hmin in HORIZONS:
                end_mod = t0_mod + hmin - 1
                start_pos = entry_pos
                end_pos_incl = np.searchsorted(mod, end_mod, side="right") - 1
                if end_pos_incl < start_pos:
                    valid_row = False
                    break
                window_h = h[start_pos:end_pos_incl + 1]
                window_l = l[start_pos:end_pos_incl + 1]
                exit_price = float(c[end_pos_incl])
                row[f"mfe_{hmin}m"] = float(window_h.max() / entry_price - 1.0)
                row[f"mae_{hmin}m"] = float(window_l.min() / entry_price - 1.0)
                row[f"ret_{hmin}m"] = float(exit_price / entry_price - 1.0)
            if not valid_row:
                continue

            rows.append(row)

        prev_close = float(c[-1])

    return rows


def main(limit: int | None = None, codes_arg: str | None = None) -> int:
    t_start = time.time()
    if codes_arg:
        pop = [x.strip() for x in codes_arg.split(",") if x.strip()]
    else:
        pop = load_population()
    if limit:
        pop = pop[:limit]
    print(f"모집단 {len(pop)}종목 스캔 시작 (ORN={ORN_LIST})", flush=True)

    all_rows: list[dict] = []
    for i, code in enumerate(pop):
        try:
            rows = process_stock(code)
            all_rows.extend(rows)
        except Exception as e:
            print(f"  [경고] {code} 처리 실패: {e}", flush=True)
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(pop)} · {time.time()-t_start:.0f}s · 신호 {len(all_rows):,}건",
                  flush=True)

    df = pd.DataFrame(all_rows)
    os.makedirs("results", exist_ok=True)
    df.to_csv(OUT_CSV, index=False)

    print(f"\n=== 스캔 완료 {time.time()-t_start:.0f}s ===")
    print(f"총 T0 신호: {len(df):,}건")
    if not df.empty:
        for orn in ORN_LIST:
            sub = df[df["orn"] == orn]
            print(f"  ORN={orn:2d}분: {len(sub):,}건 · 종목 {sub['symbol'].nunique()} · "
                  f"날짜 {sub['date'].nunique()}")
        print(f"\n기간: {df['date'].min()} ~ {df['date'].max()}")
        print(f"RVOL_norm 결측(분모=0 등): {df['rvol_norm'].isna().sum():,}건")
    print(f"\n산출: {OUT_CSV}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--codes", type=str, default=None)
    args = ap.parse_args()
    raise SystemExit(main(args.limit, args.codes))
