"""유동성 기준으로 대량 다운로드 대상 종목을 선정.

전체 시장(코스피+코스닥) 2,700여 개 종목의 일봉을 전부 조회해 평균 거래대금을
계산하면 비용이 크므로, 거래대금 순위 API(ka10032, screener.top_by_trading_value)로
당일 기준 상위 후보군을 먼저 저렴하게 추리고, 그 후보군에 대해서만 실제 일봉
데이터로 최근 N거래일 평균 거래대금을 계산해 정확한 임계값을 적용한다.
"""
import os

import duckdb
import pandas as pd

from kiwoom_client import KiwoomClient
from . import minute_store
from .entry_filters import _day_return
from .screener import top_by_trading_value

TRADE_VALUE_UNIT_TO_EOK = 100  # trde_prica는 백만원 단위. 1억원 = 100백만원.


def _trading_value_minute_dir(data_dir: str) -> str:
    """대금 순위 계산용 분봉 디렉터리 — **통합(AL) 기준**(2026-09-01 lead 판단,
    data-agent_20260901-1645_minute_al_bridge.md). KRX 전용으로는 대금 중앙값
    오차 17.5%(최대 298%)라 순위가 흔들린다(가격/수익률은 95% 일치라 그쪽은 안 바꿈).

    data_dir이 기본값("data")일 때만 통합 경로로 간다 — tests/backtesting/
    test_universe.py가 tmp_path를 data_dir로 넘겨 만드는 소규모 픽스처는 그대로
    자기 경로(tmp_path/stocks/minute)를 쓴다(격리 유지, 매번 1,265종목 실데이터를
    읽게 만들지 않는다). 프로덕션 호출(기본값 그대로 쓰는 곳)만 AL로 바뀐다."""
    if data_dir == "data":
        return minute_store.minute_al_dir()
    return os.path.join(data_dir, "stocks", "minute")


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

    D일의 유니버스는 **D-1일에 확정된** 거래대금 순위로 정한다. 같은 날 종가·거래량
    으로 뽑으면 장중 진입 시점에는 알 수 없는 값을 쓰는 미래참조가 된다 — 실거래의
    screener.top_by_trading_value 는 장중 누적 대금으로 순위를 매기므로 여기서도
    최소한 "진입 전에 알 수 있는 값"만 쓴다. 첫 거래일은 직전일이 없어 빠진다.
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

    ranked_by_date = {
        date: {code for code, _ in sorted(entries, key=lambda x: -x[1])[:top_n]}
        for date, entries in trade_value_by_date.items()
    }
    dates = sorted(ranked_by_date)
    return {today: ranked_by_date[prev] for prev, today in zip(dates, dates[1:])}


def intraday_top_n_return_rank1_by_minute(
    data_dir: str = "data", trading_value_rank_n: int = 25
) -> dict[pd.Timestamp, str]:
    """매 분마다 "장중 누적 거래대금 상위 trading_value_rank_n종목" 중 그 시점까지의
    등락률(entry_filters._day_return)이 가장 높은 1개 종목의 코드를 매핑한다.

    daily_top_n_from_local(일봉 close*volume 근사, D-1 확정)과 달리, 이 함수는 실거래
    유니버스 선정(screener.top_by_trading_value, 키움 ka10032/[0184])과 같은 개념 —
    "그 시점까지의 장중 누적 거래대금" — 을 로컬 분봉으로 재구성한다. 09:00부터 그
    분까지 누적한 값이라 그 시점에 실제로 알 수 있는 값이고(미래참조 없음), 실거래와
    정의가 정확히 일치한다는 점에서 D-1 근사보다 낫다(2026-08-29 사용자 지적).

    한계 2가지 — 로컬 데이터로는 실제 [0184] 이력을 재현할 방법이 없어 정량화 불가:
    1) 로컬 분봉 캐시가 1045종목뿐인데 실제 시장(코스피+코스닥 전체, 이 모듈 상단
       docstring 기준 약 2,700종목)은 그보다 훨씬 넓다. 캐시에 없는 종목이 실제
       상위권이면 여기서 계산한 순위가 실제보다 위로 밀린다 — 이 방향은 항상 낙관
       편향(실제로는 트레이딩값랭크N위 밖일 종목을 그 안으로 오판)이다.
    2) ka10032는 세션을 안 갈라 시간외 거래대금이 섞인다(trading_value_ranking.py:1-22,
       실제 보정 로직은 trading_value_ranking.py:321 _apply_regular_session_baseline).
       여기서는 로컬 분봉(정규장만 수집됨을 전제)만으로 누적하므로 시간외 물량이
       전혀 안 섞인 값이다 — 시간외 비중이 컸던 날/종목일수록 실제 [0184] 순위와
       어긋날 수 있다.

    동률 처리(2026-08-29 정정): "등락률이 완전히 같을 확률은 실질적으로 0"이라던
    원래 가정은 틀렸다 — 벡터화 최적화 검증 중 108,791개 분봉·30종목 표본에서
    18건의 불일치를 발견해 손으로 대조해보니, 18건 전부 진짜 동률이었다(등락률
    소수점까지 정확히 일치, 코드 자체가 다른 값을 낸 버그가 아님). 원인: 장 시작
    직후(예: 09:14) 아직 한 번도 체결이 없어 등락률이 정확히 0.0인 종목이 여럿
    있으면 항상 동률이 난다(14/18건). 나머지 4건은 우연히 같은 등락률(0이 아닌 값)
    이었다. 그래서 동률 처리가 실제로 필요했다 — 아래 rank(method="first")가 그
    타이브레이크다: 같은 등락률이면 value_today의 열 순서(=codes_today, 종목코드
    오름차순 정렬)상 먼저 오는 코드가 이긴다. 결정적이고 재현 가능하지만 "어느 게
    맞다"는 의미는 없다(동률은 원래 어느 쪽이든 맞다) — tests/backtesting/
    test_universe.py의 동률 회귀 테스트 참고.

    2026-08-29: 날짜별 파이썬 루프(분마다 nlargest+idxmax)를 rank(axis=1) 기반
    벡터 연산으로 교체 — 실측 84초→13초(30종목, 6.6배), 1045종목 환산 시 약
    25분→4분. 동률 처리를 제외한 판단 로직은 그대로: rank<=N인 칸만 남기고
    나머지를 NaN으로 지운 뒤 idxmax(axis=1) 한 번으로 뽑는 게, "값이 top-N 안에
    드는 코드만 골라 그중 등락률 최댓값"이라는 원래 로직과 동치다(값이 NaN인
    칸은 랭크도 NaN이 되어 자동 제외되므로 dropna 후 nlargest와 같은 집합이 나옴).
    """
    minute_dir = _trading_value_minute_dir(data_dir)
    daily_dir = os.path.join(data_dir, "stocks", "daily")

    cum_value_by_code: dict[str, pd.Series] = {}
    day_return_by_code: dict[str, pd.Series] = {}
    for filename in os.listdir(minute_dir):
        if not filename.endswith(".csv"):
            continue
        code = filename[:-4]
        daily_path = os.path.join(daily_dir, f"{code}.csv")
        if not os.path.exists(daily_path):
            continue
        minute_df = pd.read_csv(os.path.join(minute_dir, filename), index_col=0, parse_dates=True)
        daily_df = pd.read_csv(daily_path, index_col=0, parse_dates=True)
        # detect_entries(breakout_reversal.py)와 동일한 관례: 실제 체결대금 컬럼이 있으면
        # 그대로 쓰고, 없으면(REST 과거이력) close*volume으로 근사.
        per_minute_value = minute_df["value"] if "value" in minute_df.columns else minute_df["close"] * minute_df["volume"]
        cum_value_by_code[code] = per_minute_value.groupby(minute_df.index.normalize()).cumsum()
        day_return_by_code[code] = _day_return(minute_df, daily_df)

    all_days = sorted({d for s in cum_value_by_code.values() for d in s.index.normalize().unique()})
    rank1_by_minute: dict[pd.Timestamp, str] = {}
    for day in all_days:
        codes_today = sorted(c for c, s in cum_value_by_code.items() if (s.index.normalize() == day).any())
        if not codes_today:
            continue
        value_today = pd.concat(
            {c: cum_value_by_code[c][cum_value_by_code[c].index.normalize() == day] for c in codes_today}, axis=1
        )
        return_today = pd.concat(
            {c: day_return_by_code[c][day_return_by_code[c].index.normalize() == day] for c in codes_today}, axis=1
        )
        rank = value_today.rank(axis=1, method="first", ascending=False)
        masked_returns = return_today.where(rank <= trading_value_rank_n)
        has_candidate = masked_returns.notna().any(axis=1)
        winners = masked_returns.idxmax(axis=1)
        for ts, winner in zip(value_today.index[has_candidate], winners[has_candidate]):
            rank1_by_minute[ts] = winner
    return rank1_by_minute


# ponytail: 파일 파싱(전체 종목 CSV 로드) + 파이썬 dict 조립이 나머지 90%+를 먹는 게
# 진짜 병목이었다(2026-08-30 lead 실측: 80종목 30.6s -> DuckDB 1.6s, 18.8배). 판단
# 로직은 위 pandas 버전과 완전히 동일 - SQL로 옮긴 건 "매 분마다 거래대금 상위 N위
# 중 등락률 최댓값 1개"라는 집합연산이라 DuckDB 윈도우함수로 그대로 표현되기 때문.
# 동률 처리도 동일 규칙(코드 오름차순이 이긴다)을 ORDER BY ... code ASC로 재현했다.
def intraday_top_n_return_rank1_by_minute_duckdb(
    data_dir: str = "data", trading_value_rank_n: int = 25
) -> dict[pd.Timestamp, str]:
    """intraday_top_n_return_rank1_by_minute와 완전히 동일한 결과를 내는 DuckDB 버전
    (판단 로직 불변 - 파일 I/O + 데이터프레임 조립만 SQL 엔진에 맡긴다).

    pandas 버전은 유지한다(둘 다 존재) - 이 함수가 진짜로 같은 결과를 내는지는
    tests/backtesting/test_universe.py::test_duckdb_version_matches_pandas_version가
    지킨다. 다르면 이 함수를 쓰지 말 것.

    로컬 CSV에 "value" 컬럼이 있는 파일이 하나도 없어(2026-08-30 확인) close*volume
    근사만 구현했다 - pandas 버전처럼 파일별로 있으면 쓰고 없으면 근사하는 폴백은
    없다. value 컬럼이 든 데이터가 실제로 생기면 이 함수를 그때 확장할 것.
    """
    minute_glob = os.path.join(_trading_value_minute_dir(data_dir), "*.csv").replace("\\", "/")
    daily_glob = os.path.join(data_dir, "stocks", "daily", "*.csv").replace("\\", "/")

    query = f"""
    WITH daily_codes AS (
        SELECT DISTINCT parse_filename(filename, true) AS code
        FROM read_csv('{daily_glob}', filename=true, union_by_name=true)
    ),
    daily AS (
        SELECT
            parse_filename(filename, true) AS code,
            date::DATE AS d,
            LAG(close) OVER (PARTITION BY filename ORDER BY date) AS prev_close
        FROM read_csv('{daily_glob}', filename=true, union_by_name=true)
    ),
    minute AS (
        SELECT
            parse_filename(filename, true) AS code,
            date AS ts,
            date::DATE AS d,
            close AS mclose,
            close * volume AS per_minute_value
        FROM read_csv('{minute_glob}', filename=true, union_by_name=true)
        WHERE parse_filename(filename, true) IN (SELECT code FROM daily_codes)
    ),
    joined AS (
        SELECT m.code, m.ts, m.d, m.mclose, m.per_minute_value, dl.prev_close
        FROM minute m
        LEFT JOIN daily dl USING (code, d)
    ),
    cum AS (
        SELECT code, ts, d,
            SUM(per_minute_value) OVER (PARTITION BY code, d ORDER BY ts ROWS UNBOUNDED PRECEDING) AS cum_value,
            CASE WHEN prev_close IS NULL OR prev_close = 0 THEN NULL
                 ELSE (mclose - prev_close) / prev_close END AS day_return
        FROM joined
    ),
    ranked AS (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY d, ts ORDER BY cum_value DESC, code ASC) AS vol_rank
        FROM cum
    )
    SELECT ts, code AS winner_code
    FROM ranked
    WHERE vol_rank <= {trading_value_rank_n} AND day_return IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (PARTITION BY d, ts ORDER BY day_return DESC, code ASC) = 1
    ORDER BY ts
    """
    result = duckdb.sql(query).df()
    return dict(zip(pd.to_datetime(result["ts"]), result["winner_code"]))
