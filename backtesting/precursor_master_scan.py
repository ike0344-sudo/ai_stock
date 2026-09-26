"""상승전조 마스터 — 단계 1~2 실행: 사전필터 통과율 + T0 탐지.

사전등록 §3: **필터 통과율을 먼저 센다.** 어느 한쪽 군이 10건 미만이면 필터가 병목이라고
명시하고 lead에게 묻는다 — 임의로 빼지 않는다.

사용: python backtesting/precursor_master_scan.py [--limit N]
산출: results/precursor_master_signals.csv (T0 목록 + 라벨 + 필터 결과)
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import time
from collections import Counter

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _precursor_fastpath import to_grid  # noqa: E402
from backtesting.precursor_master_features import (  # noqa: E402
    compute_features, detect_pullback_reaccel)
from backtesting.precursor_master import (  # noqa: E402
    HORIZONS_MIN, T0_BREAKOUT_MINUTES, T0_DEFAULT_MINUTES, TICK_DIR,
    detect_breakouts, is_gap_open, load_15min_ma, load_daily_ma, mfe_mae,
    passes_15min_filter, passes_daily_filter)

OUT = "results/precursor_master_signals.csv"


def main(limit: int | None = None) -> int:
    t_start = time.time()
    files = sorted(glob.glob(os.path.join(TICK_DIR, "*", "*.parquet")))
    if limit:
        files = files[:limit]
    print(f"틱 파일 {len(files):,}개 스캔 시작", flush=True)

    ma_daily: dict[str, pd.DataFrame | None] = {}
    ma_15: dict[str, pd.DataFrame | None] = {}
    rows, stat = [], Counter()

    for i, f in enumerate(files):
        parts = f.replace(os.sep, "/").split("/")
        code, day_s = parts[-2], parts[-1][:10]
        day = pd.Timestamp(day_s)

        if code not in ma_daily:
            ma_daily[code] = load_daily_ma(code)
            ma_15[code] = load_15min_ma(code)
        md, m15 = ma_daily[code], ma_15[code]

        g = to_grid(f)
        if g is None:
            stat["격자실패"] += 1
            continue
        px = g["px"]

        prev_close = np.nan
        if md is not None and day in md.index:
            prev_close = md.loc[day, "prev_close"]
        if is_gap_open(px, prev_close):
            stat["갭시작제외"] += 1
            continue

        f_day = passes_daily_filter(md, day) if md is not None else None
        f_15 = passes_15min_filter(m15, day) if m15 is not None else None
        stat[f"일봉필터_{f_day}"] += 1
        stat[f"15분필터_{f_15}"] += 1
        stat["종목일"] += 1

        # T0 탐지 — 기본 5분 + 민감도용 다른 창도 같이 기록
        hits = {w: set(detect_breakouts(px, w).tolist()) for w in T0_BREAKOUT_MINUTES}
        t0_list = sorted(hits[T0_DEFAULT_MINUTES])
        if not t0_list:
            continue
        feats = compute_features(g, np.array(t0_list, dtype=np.int64))
        for j, t0 in enumerate(t0_list):
            lab = mfe_mae(g["tick_sec"], g["tick_prc"], t0, HORIZONS_MIN)
            if not lab:
                stat["라벨없음"] += 1
                continue
            r = {"symbol": code, "date": day_s, "t0_sec": t0,
                 "pass_daily": f_day, "pass_15min": f_15,
                 "prev_close": prev_close, **lab}
            for w in T0_BREAKOUT_MINUTES:
                r[f"brk{w}m"] = t0 in hits[w]
            for k, v in feats.items():
                r[k] = v[j]
            r.update(detect_pullback_reaccel(g["cnt"], px, t0))
            rows.append(r)
        stat["신호"] += len(t0_list)

        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{len(files)} · {time.time()-t_start:.0f}초 · 신호 {len(rows):,}",
                  flush=True)

    df = pd.DataFrame(rows)
    os.makedirs("results", exist_ok=True)
    df.to_csv(OUT, index=False)

    print(f"\n=== 스캔 완료 {time.time()-t_start:.0f}초 ===")
    print(f"종목·일 {stat['종목일']:,} | 갭시작 제외 {stat['갭시작제외']:,} | "
          f"격자실패 {stat['격자실패']:,}")
    print(f"T0 신호 {len(df):,}건 (라벨없음 {stat['라벨없음']:,}건 제외)")
    print("\n--- 사전필터 통과율 (지시 §2: 표본이 죽으면 멈춘다) ---")
    for k in ("일봉필터", "15분필터"):
        tot = sum(v for kk, v in stat.items() if kk.startswith(k))
        for val in ("True", "False", "None"):
            n = stat[f"{k}_{val}"]
            print(f"  {k} {val:5s}: {n:>5,} 종목·일 ({100*n/max(tot,1):5.1f}%)")
    if not df.empty:
        both = df[(df["pass_daily"] == True) & (df["pass_15min"] == True)]  # noqa: E712
        print(f"\n  두 필터 동시 통과 신호: {len(both):,}건 / 전체 {len(df):,}건 "
              f"({100*len(both)/len(df):.1f}%)")
        print(f"  통과 신호의 종목 수 {both['symbol'].nunique()} · 날짜 수 {both['date'].nunique()}")
    print(f"\n산출: {OUT}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    raise SystemExit(main(ap.parse_args().limit))
