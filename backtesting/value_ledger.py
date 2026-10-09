"""52주 신고거래대금 장부 (사용자 2026-10-09) — 화면: /value_ledger.html (신고가 장부와 같은 월 칸 모양).

    python -m backtesting.value_ledger          # → static/dashboard/value_ledger.json
    python -m backtesting.value_ledger --csv    # + results/value_record_52w/{YYYY-MM}.csv·_summary.csv

52주 신고거래대금 = 그날 통합(AL) 실거래대금이 **그날 제외** 직전 245거래일 최대를 넘은 날
(value_burst 의 '1년' 등급과 같은 정의 · 245거래일이 안 찬 종목·날은 판정 안 함 — 상장 초기엔 아무 날이나 신고가 된다).
대금은 data/stocks/daily_al(value_mw, 백만원) — KRX 일봉은 NXT 가 빠져 2025-03 뒤로 반 토막이라 쓰지 않는다.
저장 하한 1,000억(10-09 사용자). 역대 = 앞선 데이터 4년 이상인 날 중 데이터 전체 기간 최대도 넘은 날(10-10 사용자 "따로 표시"). 5일뒤·20일뒤 = 그날 통합 종가 매수 기준.
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import numpy as np
import pandas as pd

OUT_PATH = "static/dashboard/value_ledger.json"
CSV_DIR = "results/value_record_52w"
Y1 = 245
Y4 = 980  # 역대 판정에 필요한 최소 이력(value_burst 의 4년과 같은 길이)
MIN_EOK = 1000  # 10-09 사용자 "천억 이상만" (처음 300억 = value_burst 저장 하한)
COLS = ["날짜", "코드", "종목명", "거래대금_억", "직전52주최대_억", "배수", "평소20일대비", "등락률%", "종가", "누적횟수", "5일뒤%", "20일뒤%", "역대"]


def events() -> pd.DataFrame:
    names = json.load(open("data/stock_names.json", encoding="utf-8"))
    rows = []
    for p in glob.glob("data/stocks/daily_al/*.csv"):
        d = pd.read_csv(p, dtype={"date": str})
        if len(d) <= Y1:
            continue
        val = d.value_mw / 100  # 억
        prev_max = val.shift(1).rolling(Y1, min_periods=Y1).max().replace(0, np.nan)  # 1년 넘게 거래정지 뒤 재개는 비교 대상이 없어 뺀다
        hit = (val > prev_max) & (val >= MIN_EOK)
        if not hit.any():
            continue
        code = os.path.basename(p)[:6]
        c = d.close
        rows.append(pd.DataFrame({
            "날짜": pd.to_datetime(d.date[hit]).dt.strftime("%Y-%m-%d"), "코드": code, "종목명": names.get(code, code),
            "거래대금_억": val[hit].round(0), "직전52주최대_억": prev_max[hit].round(0), "배수": (val / prev_max)[hit].round(2),
            "평소20일대비": (val / val.shift(1).rolling(20).mean().replace(0, np.nan))[hit].round(1),  # 직전 20일 대금 0(거래정지 뒤 재개)이면 빈칸
            "등락률%": ((c / c.shift(1) - 1) * 100)[hit].round(2), "종가": c[hit],
            "5일뒤%": ((c.shift(-5) / c - 1) * 100)[hit].round(2), "20일뒤%": ((c.shift(-20) / c - 1) * 100)[hit].round(2),
            # 역대 = 데이터 전체 기간(2019-06 또는 상장 이후) 그날 제외 최대 초과. 앞선 데이터가 4년(980거래일) 안 되면 판정 안 함 —
            # 데이터가 2019-06 부터라 1년만 재면 2020~21년 신고의 92~98% 가 '역대'가 돼 52주와 구분이 안 된다(10-10)
            "역대": (val > val.shift(1).expanding(min_periods=Y4).max())[hit]}))
    out = pd.concat(rows).sort_values(["날짜", "거래대금_억"], ascending=[True, False])
    out["누적횟수"] = out.groupby("코드").cumcount() + 1  # 데이터 시작 이후 그 종목의 몇 번째 52주 신고인지
    return out[COLS].reset_index(drop=True)


def build(e: pd.DataFrame) -> dict:
    rows = e.replace({np.nan: None}).values.tolist()
    rows = [[r[0], r[1], r[2], int(r[3]), int(r[4]), r[5], r[6], r[7], int(r[8]), int(r[9]), r[10], r[11], int(bool(r[12]))] for r in rows]
    return {"date": e["날짜"].max(), "min_value_eok": MIN_EOK, "days": Y1, "rows": rows}


def write_json(payload: dict, path: str = OUT_PATH) -> str:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)  # NaN·inf 는 브라우저 JSON 이 못 읽는다
    os.replace(tmp, path)
    return path


def write_csv(e: pd.DataFrame) -> None:
    os.makedirs(CSV_DIR, exist_ok=True)
    m = e["날짜"].str[:7]
    for k, g in e.groupby(m):
        g.to_csv(f"{CSV_DIR}/{k}.csv", index=False, encoding="utf-8-sig")
    e.groupby(m).agg(건수=("코드", "size"), 종목수=("코드", "nunique"), 거래일수=("날짜", "nunique"),
                     대금합_억=("거래대금_억", "sum"), 대금중앙_억=("거래대금_억", "median"),
                     등락률중앙=("등락률%", "median")).rename_axis("월").to_csv(f"{CSV_DIR}/_summary.csv", encoding="utf-8-sig")


def demo() -> None:
    """정의 점검: 245일 평탄 뒤 큰 날 → 신고, 그보다 작은 다음 날 → 아님."""
    v = pd.Series([1200.0] * 250 + [1500, 1300, 1600])
    pm = v.shift(1).rolling(Y1, min_periods=Y1).max()
    assert list(((v > pm) & (v >= MIN_EOK)).iloc[-3:]) == [True, False, True]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="store_true")
    a = ap.parse_args()
    demo()
    e = events()
    p = build(e)
    print(f"52주 신고거래대금 {len(p['rows'])}건 → {write_json(p)} (기준일 {p['date']})")
    if a.csv:
        write_csv(e)
