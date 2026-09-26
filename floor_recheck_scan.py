"""전략1 3분 거래대금 하한 재검증(2026-09-26 lead 지시) — 1단계: 하한별로 **다시 탐지**해 거래를 저장한다(읽기 전용, data/ 에 안 씀).

final_strategy.py 는 수정하지 않는다 — 실행 중에만 `final_strategy.MIN_TRADE_VALUE` 와 `validate_strategy1.MIN_TRADE_VALUE`
(둘 다 모듈 전역을 읽는다)를 덮어쓴다. 그 외는 validate_strategy1.scan_all_trades 기본 경로(진입 조건·ML 피처·tiered exit·비용 전부 그대로).
실행: python floor_recheck_scan.py 40 80 100 120 140 160   → results/floor_recheck/trades_<억>.pkl
"""
import sys
import time

import pandas as pd

from backtesting import final_strategy as fs
from backtesting import validate_strategy1 as v1

DATA = "data"
OUT = "results/floor_recheck"


def scan(floor_eok: int, use_duckdb: bool = True) -> pd.DataFrame:
    val = int(floor_eok * 100_000_000)
    fs.MIN_TRADE_VALUE = val
    v1.MIN_TRADE_VALUE = val
    return v1.scan_all_trades(DATA, use_duckdb_conditions=use_duckdb)


if __name__ == "__main__":
    floors = [int(x) for x in sys.argv[1:]] or [40, 120]
    for f in floors:
        t0 = time.time()
        df = scan(f)
        df.to_pickle(f"{OUT}/trades_{f}.pkl")
        print(f"floor {f}억: {len(df)}건 종목 {df['code'].nunique() if len(df) else 0}개 "
              f"{df['entry_time'].min()} ~ {df['entry_time'].max()}  ({time.time()-t0:.0f}s)", flush=True)
