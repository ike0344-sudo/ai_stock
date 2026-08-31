"""orderbook_collector가 쌓은 호가 원본 JSONL을 DuckDB로 가정 스키마에 맞춰 파싱하는
스켈레톤 (큐: "호가 DuckDB 파싱 스켈레톤", strategy-agent 승인).

호가 캡처 자체가 아직 보류 상태라(docs/ORDERBOOK_CAPTURE_DESIGN.md — 두 번째 앱키
대기) 실제 데이터가 없다. 그래서 10단 호가/잔량의 실제 FID(필드명)도 대부분
미확인이다 — 1단(매도/매수 최우선호가)만 trading_loop._parse_quote_price에서 실측
확인됐다(sel_fpr_bid/buy_fpr_bid, 부호가 등락방향이라 ABS 필요).

**가정 스키마** (strategy-agent 승인, 2026-08-30):
code, date_str, ts, rank, bid1..10_price, bid1..10_qty, ask1..10_price, ask1..10_qty
(bid=매수호가, ask=매도호가 — 원본 필드명의 "bid"와는 다른 의미이니 혼동 주의,
ka10004 필드명 "sel_fpr_bid"의 bid는 "호가"라는 뜻이지 매수/매도 방향이 아니다)

캡처가 시작되고 2~10단 FID가 확인되면 RAW_FIELD_MAP 값만 채우면 된다 — 쿼리
구조(_select_expr/parse_orderbook_jsonl)는 그대로 둔다.
"""
import duckdb
import pandas as pd

ASSUMED_SCHEMA = ["code", "date_str", "ts", "rank"] + [
    f"{side}{i}_{field}"
    for i in range(1, 11)
    for side in ("bid", "ask")
    for field in ("price", "qty")
]

# 원본 JSON 키(FID) 매핑. None = 아직 미확인 — 캡처 시작 후 실제 응답을 보고
# 이 항목만 채운다. code/ts는 orderbook_collector.collect_once가 붙이는 메타
# 필드(stock_code/received_at)라 이미 확정.
RAW_FIELD_MAP: dict[str, str | None] = {
    "code": "stock_code",
    "ts": "received_at",
    "rank": None,  # 거래대금 순위 FID 미확인 (ka10032 조회분과 join이 필요할 수도)
    "bid1_price": "buy_fpr_bid",  # 매수 최우선호가 (실측 확인, trading_loop.py)
    "ask1_price": "sel_fpr_bid",  # 매도 최우선호가 (실측 확인, trading_loop.py)
}
for _i in range(1, 11):
    for _side in ("bid", "ask"):
        RAW_FIELD_MAP.setdefault(f"{_side}{_i}_price", None)
        RAW_FIELD_MAP.setdefault(f"{_side}{_i}_qty", None)

_PRICE_COLUMNS = {c for c in ASSUMED_SCHEMA if c.endswith("_price")}


def _select_expr(col: str, json_col: str = "json") -> str:
    """RAW_FIELD_MAP 값 → SELECT 절 한 컬럼. 미확인 필드(None)는 NULL로 채워 스키마
    모양은 항상 고정된다 - FID가 하나씩 확인돼도 나머지 컬럼/쿼리는 안 깨진다."""
    raw_key = RAW_FIELD_MAP.get(col)
    if raw_key is None:
        return f"CAST(NULL AS VARCHAR) AS {col}" if col == "code" else f"CAST(NULL AS DOUBLE) AS {col}"
    extract = f"json_extract_string({json_col}, '$.{raw_key}')"
    if col == "code":
        return f"{extract} AS {col}"
    if col == "ts":
        return f"CAST({extract} AS TIMESTAMP) AS {col}"
    if col in _PRICE_COLUMNS:
        # ka10004 가격 필드는 전일종가 대비 등락 부호가 붙어 온다("-70100") -
        # trading_loop._parse_quote_price와 같은 이유로 ABS.
        return f"ABS(CAST({extract} AS DOUBLE)) AS {col}"
    return f"CAST({extract} AS BIGINT) AS {col}"


def parse_orderbook_jsonl(glob_pattern: str) -> pd.DataFrame:
    """orderbook_collector.append_jsonl이 쌓은 data/orderbook/{date}/{code}.jsonl을
    ASSUMED_SCHEMA 컬럼의 DataFrame으로 파싱한다. date_str은 레코드 안에 없어
    ts(received_at)에서 파생한다."""
    cols = [c for c in ASSUMED_SCHEMA if c != "date_str"]
    select_cols = ", ".join(_select_expr(c) for c in cols)
    ts_raw_key = RAW_FIELD_MAP["ts"]
    query = f"""
    SELECT {select_cols},
           strftime(CAST(json_extract_string(json, '$.{ts_raw_key}') AS TIMESTAMP), '%Y-%m-%d') AS date_str
    FROM read_json_objects('{glob_pattern}', format='newline_delimited')
    """
    return duckdb.sql(query).df()[ASSUMED_SCHEMA]
