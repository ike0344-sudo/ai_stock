"""키움 REST API로 일봉/분봉 차트를 받아 캔들차트로 표시.

사용법:
    python fetch_chart.py 005930                 # 일봉
    python fetch_chart.py 000660 --interval 15    # 15분봉 (정규장 09:00~15:30만 반환됨)
    python fetch_chart.py 000660 --interval 15 --days 3   # 최근 3거래일만
    python fetch_chart.py 005930 --inspect         # 응답 원본 구조 확인
"""
import argparse
import json
import os

import mplfinance as mpf
import pandas as pd
from dotenv import load_dotenv

from kiwoom_client import KiwoomClient

RECORDS_KEY_CANDIDATES = [
    "stk_dt_pole_chart_qry", "stk_min_pole_chart_qry",
    "inds_dt_pole_qry", "inds_min_pole_qry",  # 업종(지수) 차트 응답
    "output", "chart", "data",
]

DAILY_COLUMN_MAP = {
    "date": "dt",
    "open": "open_pric",
    "high": "high_pric",
    "low": "low_pric",
    "close": "cur_prc",
    "volume": "trde_qty",
}

# 분봉(ka10080)은 날짜+시각이 cntr_tm 하나에 들어있음 (YYYYMMDDHHMMSS)
MINUTE_COLUMN_MAP = {
    "date": "cntr_tm",
    "open": "open_pric",
    "high": "high_pric",
    "low": "low_pric",
    "close": "cur_prc",
    "volume": "trde_qty",
}


def find_records(payload: dict):
    # HTTP 200이어도 API 자체 오류(토큰 만료/레이트리밋 등)는 return_code!=0으로 응답에
    # 실려 온다(kiwoom_client.py place_order 등과 동일 관례) — 이 체크 없이 진행하면
    # 레코드 리스트가 없어 아래 "차트 레코드 리스트를 찾지 못했습니다"만 보여서 진짜
    # 원인이 로그에 안 남는다(screener.py의 ka10032 return_code 누락과 같은 문제가
    # 여기서도 실측됨 — live_monitor.py의 "확인 중 오류" 반복이 이 경로).
    # return_code가 없는(테스트 픽스처 등) 페이로드는 그냥 아래 키 탐색으로 넘어간다.
    return_code = payload.get("return_code")
    if return_code is not None and return_code != 0:
        raise RuntimeError(
            f"차트 조회 API 오류 - return_code={return_code} {payload.get('return_msg', '')}".strip()
        )
    for key in RECORDS_KEY_CANDIDATES:
        if key in payload and isinstance(payload[key], list):
            return payload[key]
    for key, value in payload.items():
        if isinstance(value, list) and value:
            return value
    raise RuntimeError(
        "응답에서 차트 레코드 리스트를 찾지 못했습니다. --inspect 로 raw 응답을 확인하세요."
    )


def to_dataframe(records: list, column_map: dict, date_format: str) -> pd.DataFrame:
    df = pd.DataFrame(records)
    df = df.rename(columns={v: k for k, v in column_map.items()})
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col].astype(str).str.replace("+", "").str.replace("-", ""), errors="coerce")
    df["date"] = pd.to_datetime(df["date"], format=date_format)
    df = df.set_index("date").sort_index()
    return df[["open", "high", "low", "close", "volume"]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stock_code", help="종목코드 (예: 005930, 000660)")
    parser.add_argument(
        "--interval",
        default="day",
        help="day(일봉) 또는 분 단위(1/3/5/10/15/30/45/60). 기본 day",
    )
    parser.add_argument("--days", type=int, default=None, help="최근 N거래일만 표시")
    parser.add_argument("--inspect", action="store_true", help="raw 응답 JSON만 출력하고 종료")
    args = parser.parse_args()

    load_dotenv()
    appkey = os.environ["KIWOOM_APPKEY"]
    secretkey = os.environ["KIWOOM_SECRETKEY"]
    is_mock = os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true"

    client = KiwoomClient(appkey, secretkey, is_mock=is_mock)

    is_minute = args.interval != "day"
    if is_minute:
        payload = client.get_minute_chart(args.stock_code, tic_scope=args.interval)
    else:
        payload = client.get_daily_chart(args.stock_code)

    if args.inspect:
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:3000])
        return

    records = find_records(payload)
    column_map = MINUTE_COLUMN_MAP if is_minute else DAILY_COLUMN_MAP
    date_format = "%Y%m%d%H%M%S" if is_minute else "%Y%m%d"
    df = to_dataframe(records, column_map, date_format)

    if args.days is not None:
        trading_days = sorted(df.index.normalize().unique())[-args.days:]
        df = df[df.index.normalize().isin(trading_days)]

    title = f"{args.stock_code} ({args.interval if is_minute else 'day'})"
    mpf.plot(df, type="candle", volume=True, style="charles", title=title)


if __name__ == "__main__":
    main()
