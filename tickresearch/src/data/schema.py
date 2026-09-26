"""표준 체결 스키마 정의.

원본(키움 ka10079 수집분)을 그대로 쓰지 않고 이 스키마로 정규화한다 — 원본 컬럼명이
한국어 API 관례(`cur_prc`, `trde_qty`)라 코드 가독성이 나쁘고, 시간이 HHMMSS 문자열이라
매번 파싱해야 하며, **원본이 시간 역순**이라 매 분석마다 뒤집는 비용이 반복되기 때문이다.

## 실측으로 확인한 원본 사실 (2026-09-24, 임의 가정 아님)
- 컬럼: `time`(large_string, HHMMSS) / `cur_prc`(int64) / `trde_qty`(int64) / `pred_pre_sig`(int64)
- **정렬: 시간 역순**(19:59:59 → 08:00:00). 반드시 뒤집어야 한다.
- 파일 메타데이터에 **`ref_price`**(전일 종가)가 있다 — 표본 8건 대조 결과 일봉 캐시의
  전일 종가와 **8/8 일치**. 일봉에 의존하지 않고 여기서 기준가를 얻는다.
- 범위: 08:00~20:00 전체(장전/정규장/장후). 정규장은 09:00:00~15:30:00.
- **`pred_pre_sig`는 매수/매도 구분이 아니다** — 전일종가 대비 부호다(값 2=상승/3=보합/
  5=하락). 앞선 연구에서 이걸 side로 쓰면 안 된다는 것이 실증됐다. side 컬럼으로 쓰지 않는다.

## side 처리 (명세 §5)
원본에 매수/매도 구분이 **없다**. 호가 데이터도 없으므로 Lee-Ready의 호가 기반 분류는
불가능하고, **tick rule**(직전 체결 대비 가격 방향)로 추정한다.
**추정임을 반드시 구분해 저장한다** — `side_source` 컬럼에 `"tick_rule"`을 남기고,
나중에 실제 side나 호가가 생기면 `"actual"`/`"lee_ready"`로 구분해 채운다.
"""
from __future__ import annotations

import polars as pl

# 정규장 (한국거래소). 원본은 이 범위 밖도 포함하므로 session 컬럼으로 표시만 하고
# 자르지 않는다 — 시간외 데이터도 나중에 쓸 수 있게 남겨두자는 수집 시점 결정을 따른다.
SESSION_OPEN = "09:00:00"
SESSION_CLOSE = "15:30:00"

SIDE_BUY, SIDE_SELL, SIDE_UNKNOWN = "BUY", "SELL", "UNKNOWN"
SIDE_SOURCE_TICK_RULE = "tick_rule"      # 추정 (호가 없음)
SIDE_SOURCE_ACTUAL = "actual"            # 원본에 실제 구분이 있을 때 (현재 해당 없음)

SESSION_PRE, SESSION_REGULAR, SESSION_POST = "pre", "regular", "post"

# 표준 스키마 — 명세 §4를 따르되, 검증에 필요한 컬럼을 추가한다.
TICK_SCHEMA: dict[str, pl.DataType] = {
    "timestamp": pl.Datetime("us"),   # 체결 시각 (날짜+시각)
    "symbol": pl.Utf8,                # 6자리 종목코드
    "price": pl.Int64,                # 체결가 (원, KRX는 정수)
    "volume": pl.Int64,               # 체결 수량
    "trade_value": pl.Int64,          # price * volume (원)
    "side": pl.Utf8,                  # BUY / SELL / UNKNOWN
    "side_source": pl.Utf8,           # tick_rule / actual  ← 추정 여부를 반드시 남긴다
    "session": pl.Utf8,               # pre / regular / post
    "ref_price": pl.Int64,            # 전일 종가 (파일 메타데이터에서, 등락률 기준)
    "seq": pl.Int64,                  # 파일 내 시간순 일련번호 (같은 초 안의 순서 보존용)
}

REQUIRED_RAW_COLUMNS = ["time", "cur_prc", "trde_qty"]


def empty_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=TICK_SCHEMA)


def validate_schema(df: pl.DataFrame) -> None:
    """표준 스키마를 지키는지 확인. 어긋나면 바로 예외 — 조용히 틀린 결과를 만들지 않는다."""
    missing = [c for c in TICK_SCHEMA if c not in df.columns]
    if missing:
        raise ValueError(f"표준 스키마 컬럼 누락: {missing}")
    wrong = {c: (df.schema[c], t) for c, t in TICK_SCHEMA.items() if df.schema[c] != t}
    if wrong:
        raise ValueError(f"표준 스키마 타입 불일치: {wrong}")
