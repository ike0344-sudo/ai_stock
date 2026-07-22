"""유동성 기준으로 대량 다운로드 대상 종목을 선정.

전체 시장(코스피+코스닥) 2,700여 개 종목의 일봉을 전부 조회해 평균 거래대금을
계산하면 비용이 크므로, 거래대금 순위 API(ka10032, screener.top_by_trading_value)로
당일 기준 상위 후보군을 먼저 저렴하게 추리고, 그 후보군에 대해서만 실제 일봉
데이터로 최근 N거래일 평균 거래대금을 계산해 정확한 임계값을 적용한다.
"""
import os

import pandas as pd

from kiwoom_client import KiwoomClient
from .screener import top_by_trading_value

TRADE_VALUE_UNIT_TO_EOK = 100  # trde_prica는 백만원 단위. 1억원 = 100백만원.


def build_liquid_universe(
    client: KiwoomClient,
    min_avg_trading_value_eok: float = 1000,
    candidate_pool_size: int = 150,
    lookback_days: int = 5,
    market: str = "000",
) -> pd.DataFrame:
    """최근 lookback_days 거래일 평균 거래대금이 min_avg_trading_value_eok(억원) 이상인
    개별종목(ETF/ETN 제외)만 반환. 컬럼: stock_code, name, avg_trading_value_eok.
    """
    candidates = top_by_trading_value(client, top_n=candidate_pool_size, market=market)

    rows = []
    for _, row in candidates.iterrows():
        stock_code = row["stock_code"]
        try:
            payload = client.get_daily_chart(stock_code)
        except Exception:
            continue

        records = payload.get("stk_dt_pole_chart_qry", [])[:lookback_days]
        if not records:
            continue

        try:
            trade_values = [int(r["trde_prica"]) for r in records]
        except (KeyError, ValueError):
            continue

        avg_value_eok = (sum(trade_values) / len(trade_values)) / TRADE_VALUE_UNIT_TO_EOK
        if avg_value_eok >= min_avg_trading_value_eok:
            rows.append(
                {
                    "stock_code": stock_code,
                    "name": row["name"],
                    "avg_trading_value_eok": avg_value_eok,
                }
            )

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values("avg_trading_value_eok", ascending=False).reset_index(drop=True)
    return result


def list_all_individual_stocks(client: KiwoomClient, market: str = "000") -> pd.DataFrame:
    """종목정보 리스트(ka10099)로 코스피(거래소, ETF/ETN/리츠 등 제외)+코스닥 개별종목 전체.

    market: "000"=코스피+코스닥, "001"=코스피만, "101"=코스닥만.
    """
    rows = []
    if market in ("000", "001"):
        for item in client.get_stock_list("0"):
            if item.get("marketName") == "거래소":  # ETF/ETN/리츠 등 제외, 순수 개별종목만
                rows.append({"stock_code": item["code"], "name": item["name"]})
    if market in ("000", "101"):
        for item in client.get_stock_list("10"):
            rows.append({"stock_code": item["code"], "name": item["name"]})
    return pd.DataFrame(rows)


def build_topn_union_universe(
    client: KiwoomClient,
    top_n: int = 35,
    lookback_days: int = 252,
    market: str = "000",
) -> pd.DataFrame:
    """전체 개별종목 시장을 스캔해, 최근 lookback_days 거래일 중 하루라도 거래대금
    상위 top_n 안에 든 적 있는 종목의 합집합을 반환.

    build_liquid_universe와 달리 순위 API의 당일 스냅샷으로 후보를 미리 추리지
    않는다 — 과거 한때 top_n이었지만 지금은 순위가 밀린 종목을 놓치지 않기 위함
    (실측: 상위 150개 후보만으로는 1년 합집합이 풀 크기에 근접해 하한 추정치가 됨).
    비용이 크므로(전체 종목 수만큼 daily chart 호출) 배치성 스크리닝에만 사용.
    """
    all_stocks = list_all_individual_stocks(client, market=market)

    per_day: dict[str, list[tuple[str, int]]] = {}
    name_by_code: dict[str, str] = {}

    for _, row in all_stocks.iterrows():
        stock_code = row["stock_code"]
        name_by_code[stock_code] = row["name"]
        try:
            payload = client.get_daily_chart(stock_code)
        except Exception:
            continue

        for record in payload.get("stk_dt_pole_chart_qry", [])[:lookback_days]:
            try:
                trade_value = int(record["trde_prica"])
            except (KeyError, ValueError):
                continue
            per_day.setdefault(record["dt"], []).append((stock_code, trade_value))

    union_codes: set[str] = set()
    for entries in per_day.values():
        ranked = sorted(entries, key=lambda x: -x[1])[:top_n]
        union_codes.update(code for code, _ in ranked)

    result = pd.DataFrame(
        [{"stock_code": code, "name": name_by_code.get(code, "")} for code in union_codes]
    )
    if not result.empty:
        result = result.sort_values("stock_code").reset_index(drop=True)
    return result


def daily_top_n_from_local(data_dir: str = "data/stocks/daily", top_n: int = 35) -> dict[pd.Timestamp, set[str]]:
    """로컬 일봉 CSV(data/stocks/daily/*.csv)로 날짜별 거래대금(종가×거래량 근사) 상위
    top_n 종목 집합을 계산 — API 호출 없이 이미 받아둔 로컬 데이터만으로 과거 특정
    날짜의 "그날 top_n" 여부를 백테스트에서 재현하기 위함.

    주의: 하루 전체 거래량을 사용해 근사하므로(장중 실시간 누적 거래대금이 아님)
    장중 시점 기준으로는 소폭의 미래참조를 포함한다 — 실거래에서는 하루가 끝나야
    확정되는 값을 사용하는 근사치임을 감안해야 한다.
    """
    trade_value_by_date: dict[pd.Timestamp, list[tuple[str, float]]] = {}

    for filename in os.listdir(data_dir):
        if not filename.endswith(".csv"):
            continue
        code = filename.replace(".csv", "")
        df = pd.read_csv(os.path.join(data_dir, filename), index_col=0, parse_dates=True)
        trade_value = df["close"] * df["volume"]
        for date, value in trade_value.items():
            trade_value_by_date.setdefault(date, []).append((code, value))

    result: dict[pd.Timestamp, set[str]] = {}
    for date, entries in trade_value_by_date.items():
        ranked = sorted(entries, key=lambda x: -x[1])[:top_n]
        result[date] = {code for code, _ in ranked}
    return result
