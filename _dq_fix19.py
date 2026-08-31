"""ratio<0.05 교집합 19종목-일 재수집 — 로컬 분봉을 원자적으로 교체한다.

기존 로컬에서 새로 받은 구간(가장 오래된 목표일 ~ 오늘)에 해당하는 날짜는 새 데이터로
전부 교체하고, 그 밖의(더 오래된) 날짜는 기존 로컬 값을 그대로 보존한다.
쓰기는 tmp+os.replace로 원자적(backtesting/data_loader.py의 _atomic_to_csv와 동일 패턴).
"""
import os
import sys

sys.path.insert(0, "C:/Users/ike03/Desktop/code/ai_stock")
os.chdir("C:/Users/ike03/Desktop/code/ai_stock")

from dotenv import load_dotenv
import pandas as pd

from kiwoom_client import KiwoomClient

load_dotenv("C:/Users/ike03/Desktop/code/ai_stock/.env")
client = KiwoomClient(
    os.environ["KIWOOM_APPKEY"], os.environ["KIWOOM_SECRETKEY"],
    is_mock=os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true",
)

targets = {
    "000650": "2025-11-10", "0120G0": "2025-11-24", "003920": "2026-05-28",
    "044820": "2026-05-28", "014530": "2026-06-01", "000050": "2026-06-02",
    "077500": "2026-06-18", "265740": "2026-06-19", "025950": "2026-06-22",
    "000670": "2026-06-29", "006120": "2026-06-29", "006040": "2026-07-01",
    "039440": "2026-07-01", "174900": "2026-07-01", "317400": "2026-07-01",
    "383310": "2026-07-01", "482630": "2026-07-01", "006110": "2026-07-02",
    "327260": "2026-07-02",
}

MIN_DIR = "data/stocks/minute"


def _atomic_to_csv(df: pd.DataFrame, path: str) -> None:
    tmp = f"{path}.tmp"
    df.to_csv(tmp)
    os.replace(tmp, path)


def parse_row(r: dict) -> dict:
    t = r["cntr_tm"]
    ts = f"{t[0:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}:00"
    return {
        "date": ts,
        "open": abs(int(r.get("open_pric", 0))),
        "high": abs(int(r.get("high_pric", 0))),
        "low": abs(int(r.get("low_pric", 0))),
        "close": abs(int(r.get("cur_prc", 0))),
        "volume": int(r.get("trde_qty", 0)),
    }


for code, target_date in sorted(targets.items(), key=lambda kv: kv[1]):
    path = f"{MIN_DIR}/{code}.csv"
    old = pd.read_csv(path, parse_dates=["date"])
    old_target = old[old["date"].dt.strftime("%Y-%m-%d") == target_date]
    before_rows, before_vol = len(old_target), int(old_target["volume"].sum())

    body = {"stk_cd": code, "tic_scope": "1", "upd_stkpc_tp": "1"}
    cont_yn, next_key = "N", ""
    fetched = []
    min_date_seen = None
    for _ in range(120):
        payload = client.request_tr("ka10080", body, path="/api/dostk/chart", cont_yn=cont_yn, next_key=next_key)
        chunk = payload.get("stk_min_pole_chart_qry", [])
        if not chunk:
            break
        for r in chunk:
            t = r.get("cntr_tm", "")
            if len(t) < 12:
                continue
            d = f"{t[0:4]}-{t[4:6]}-{t[6:8]}"
            fetched.append(parse_row(r))
            if min_date_seen is None or d < min_date_seen:
                min_date_seen = d
        if min_date_seen is not None and min_date_seen < target_date:
            break
        if client.last_cont_yn != "Y" or not client.last_next_key:
            break
        cont_yn, next_key = "Y", client.last_next_key

    new_df = pd.DataFrame(fetched)
    new_df["date"] = pd.to_datetime(new_df["date"])
    new_df = new_df.drop_duplicates("date").sort_values("date")
    fetch_min_date = new_df["date"].min()

    # 새로 받은 구간(fetch_min_date ~ 끝)은 새 데이터로 교체, 그 이전(더 오래된) 로컬은 보존
    old_keep = old[old["date"] < fetch_min_date]
    merged = pd.concat([old_keep, new_df], ignore_index=True).drop_duplicates("date").sort_values("date")
    merged = merged.set_index("date")

    new_target = new_df[new_df["date"].dt.strftime("%Y-%m-%d") == target_date]
    after_rows, after_vol = len(new_target), int(new_target["volume"].sum())

    _atomic_to_csv(merged, path)
    print(
        f"{code} {target_date}: 이전 {before_rows}행/{before_vol}거래량 -> "
        f"이후 {after_rows}행/{after_vol}거래량 (fetch 시작일 {fetch_min_date.date()}, "
        f"파일 전체 {len(merged)}행)",
        flush=True,
    )

print("완료 - 19종목 전부 처리")
