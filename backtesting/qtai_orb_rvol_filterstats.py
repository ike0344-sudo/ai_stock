"""ORB x RVOL 연구 — 필터 통과율 집계 (리포트 데이터 요약용).

스캔 로직을 계측(instrument)해 갭업 제외/RVOL 히스토리 부족 제외 건수를 별도로 센다.
qtai_orb_rvol_scan.process_stock의 로직을 그대로 복제하되 카운터만 추가한 버전
(원본 스캔 스크립트를 건드리지 않기 위해 별도 파일로 작성).
"""
from __future__ import annotations

import sys
from collections import Counter

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from backtesting.qtai_orb_rvol_scan import (  # noqa: E402
    GAP_PCT, HORIZONS, MAX_HORIZON, ORN_LIST, RVOL_LOOKBACK_DAYS, SESSION_END_MOD,
    SESSION_START_MOD, _build_cumvol_matrix, _build_day_arrays, _load_regular_session,
    load_population)


def count_for_stock(code: str, stat: Counter) -> None:
    df = _load_regular_session(code)
    if df is None or df.empty:
        stat["종목_데이터없음"] += 1
        return
    days, day_arrays = _build_day_arrays(df)
    if len(days) < RVOL_LOOKBACK_DAYS + 1:
        stat["종목_히스토리부족"] += 1
        return

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
                stat[f"orn{orn}_OR구간없음"] += 1
                continue
            or_high = float(h[in_or].max())

            ref = prev_or_high[orn] if prev_or_high[orn] is not None else prev_close
            gap_excluded = bool(ref is not None and ref > 0 and
                                 (day_open_actual / ref - 1.0) >= GAP_PCT)
            prev_or_high[orn] = or_high
            stat[f"orn{orn}_종목일_전체"] += 1

            if gap_excluded:
                stat[f"orn{orn}_갭업제외"] += 1
                continue
            if day_idx < RVOL_LOOKBACK_DAYS:
                stat[f"orn{orn}_RVOL히스토리부족"] += 1
                continue

            post = mod >= or_end_mod
            post_idx = np.flatnonzero(post)
            if post_idx.size == 0:
                stat[f"orn{orn}_돌파구간없음"] += 1
                continue
            hit_mask = c[post_idx] > or_high
            if not hit_mask.any():
                stat[f"orn{orn}_돌파없음"] += 1
                continue
            t0_row_idx = int(post_idx[np.argmax(hit_mask)])
            breakout_mod = int(mod[t0_row_idx])
            t0_mod = breakout_mod + 1

            if t0_mod + (MAX_HORIZON - 1) > SESSION_END_MOD:
                stat[f"orn{orn}_60분미완결제외"] += 1
                continue

            entry_pos = np.searchsorted(mod, t0_mod, side="left")
            if entry_pos >= len(mod) or mod[entry_pos] != t0_mod:
                stat[f"orn{orn}_진입봉없음"] += 1
                continue

            stat[f"orn{orn}_신호채택"] += 1

        prev_close = float(c[-1])


def main():
    pop = load_population()
    stat = Counter()
    for i, code in enumerate(pop):
        count_for_stock(code, stat)
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(pop)}", flush=True)

    print(f"\n모집단 종목 수: {len(pop)}")
    print(f"데이터 없음: {stat['종목_데이터없음']}, 히스토리 부족(<21일): {stat['종목_히스토리부족']}")
    for orn in ORN_LIST:
        total = stat[f'orn{orn}_종목일_전체']
        print(f"\n--- ORN={orn}분 ---")
        print(f"  종목일 전체(OR구간 존재): {total:,}")
        for k in ["갭업제외", "RVOL히스토리부족", "돌파구간없음", "돌파없음",
                  "60분미완결제외", "진입봉없음", "신호채택"]:
            n = stat[f"orn{orn}_{k}"]
            pct = 100 * n / total if total else 0
            print(f"    {k:16s}: {n:>7,} ({pct:5.2f}%)")


if __name__ == "__main__":
    main()
