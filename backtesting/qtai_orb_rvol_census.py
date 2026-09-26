"""ORB×RVOL 연구 — 0단계: 모집단 census.

data/stocks/minute/*.csv 전부(1,055개)를 대상으로, 정규장(09:00~15:30) 기준
실제 거래일 수를 세어 "292일 안팎 데이터 + 20거래일 이상 히스토리" 조건을
만족하는 종목이 몇 개인지 파악한다. 결과를 CSV로 저장(재현 가능하게).

data/ 폴더는 읽기 전용으로만 사용.
"""
from __future__ import annotations

import glob
import os
import time

import numpy as np
import pandas as pd

MINUTE_DIR = "data/stocks/minute"
OUT = "results/qtai_orb_rvol_census.csv"


def regular_session_day_count(path: str) -> dict:
    df = pd.read_csv(path, usecols=["date"])
    dt = pd.to_datetime(df["date"])
    mod = dt.dt.hour * 60 + dt.dt.minute  # minute-of-day
    reg = (mod >= 9 * 60) & (mod <= 15 * 60 + 30)
    dt_reg = dt[reg]
    if dt_reg.empty:
        return {"n_days": 0, "first_day": None, "last_day": None, "n_rows_total": len(df), "n_rows_reg": 0}
    days = dt_reg.dt.normalize().unique()
    return {
        "n_days": len(days),
        "first_day": pd.Timestamp(days.min()).date().isoformat(),
        "last_day": pd.Timestamp(days.max()).date().isoformat(),
        "n_rows_total": len(df),
        "n_rows_reg": int(reg.sum()),
    }


def main() -> int:
    files = sorted(glob.glob(os.path.join(MINUTE_DIR, "*.csv")))
    print(f"minute csv 파일 {len(files)}개 census 시작", flush=True)
    t0 = time.time()
    rows = []
    for i, f in enumerate(files):
        code = os.path.splitext(os.path.basename(f))[0]
        try:
            stat = regular_session_day_count(f)
        except Exception as e:
            stat = {"n_days": -1, "first_day": None, "last_day": None,
                     "n_rows_total": -1, "n_rows_reg": -1, "error": str(e)}
        stat["code"] = code
        rows.append(stat)
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(files)} · {time.time()-t0:.0f}s", flush=True)

    out = pd.DataFrame(rows)
    os.makedirs("results", exist_ok=True)
    out.to_csv(OUT, index=False)
    print(f"\n완료 {time.time()-t0:.0f}s. 저장: {OUT}")

    print("\n=== 거래일수 분포 ===")
    print(out["n_days"].describe())
    for th in (280, 250, 200, 150, 100, 50, 20):
        n = (out["n_days"] >= th).sum()
        print(f"  n_days >= {th:4d}: {n}종목")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
