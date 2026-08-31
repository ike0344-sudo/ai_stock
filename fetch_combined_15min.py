"""통합(KRX+NXT, 08:00~20:00) 15분봉 수집 → data/stocks/minute_combined/{code}_15.csv

    python fetch_combined_15min.py 000660 005930

ka10080을 "{code}_AL" 접미사로 호출하는 관례를 그대로 쓴다
(fetch_009150_combined_minute.py / sk_hynix_envelope_integrated.py와 동일).
실전 계좌(KIWOOM_IS_MOCK=false)에서만 NXT 체결가가 실제 값이다.
"""
import os, sys
import pandas as pd
from dotenv import load_dotenv
from fetch_chart import MINUTE_COLUMN_MAP, find_records, to_dataframe
from kiwoom_client import KiwoomClient

OUT_DIR = os.path.join("data", "stocks", "minute_combined")
MAX_PAGES = 40


def fetch(client, code):
    pages = client.get_minute_chart_pages(f"{code}_AL", tic_scope="15", max_pages=MAX_PAGES)
    records = [r for page in pages for r in find_records(page)]
    df = to_dataframe(records, MINUTE_COLUMN_MAP, "%Y%m%d%H%M%S")
    return df[~df.index.duplicated(keep="last")].sort_index()


def main():
    codes = sys.argv[1:] or ["000660", "005930"]
    load_dotenv(".env")
    c = KiwoomClient(os.environ["KIWOOM_APPKEY"], os.environ["KIWOOM_SECRETKEY"],
                     is_mock=os.environ.get("KIWOOM_IS_MOCK", "false").lower() == "true")
    os.makedirs(OUT_DIR, exist_ok=True)
    for code in codes:
        df = fetch(c, code)
        path = os.path.join(OUT_DIR, f"{code}_15.csv")
        df.to_csv(path)
        hh = df.index.strftime("%H:%M")
        print(f"{path}: {len(df)}행 {df.index.min()} ~ {df.index.max()} | 시간대 {hh.min()}~{hh.max()}")


if __name__ == "__main__":
    main()
