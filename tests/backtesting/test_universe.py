import os

import pandas as pd

from backtesting.universe import (
    build_liquid_universe,
    build_topn_union_universe,
    daily_top_n_from_local,
    intraday_top_n_return_rank1_by_minute,
    intraday_top_n_return_rank1_by_minute_duckdb,
    list_all_individual_stocks,
)


class _StubClient:
    def __init__(self, ranking_page: dict, daily_by_code: dict):
        self._ranking_page = ranking_page
        self._daily_by_code = daily_by_code
        self.last_cont_yn = "N"
        self.last_next_key = ""

    def request_tr(self, api_id, body, path, cont_yn="N", next_key=""):
        return {"return_code": 0, "return_msg": "정상적으로 처리되었습니다", **self._ranking_page}

    def get_daily_chart(self, stock_code, base_date=""):
        return self._daily_by_code.get(stock_code, {"stk_dt_pole_chart_qry": []})


def _ranking_item(code, name, rank, trading_value):
    return {
        "stk_cd": code, "stk_nm": name, "now_rank": str(rank), "trde_prica": str(trading_value),
        "flu_rt": "+0.00", "cur_prc": "+10000", "pred_pre": "+0", "now_trde_qty": "1000", "pred_trde_qty": "1000",
    }


def _daily_records(trade_values: list[int]) -> dict:
    return {
        "stk_dt_pole_chart_qry": [
            {"dt": f"2026071{i}", "open_pric": "100", "high_pric": "101", "low_pric": "99", "cur_prc": "100", "trde_qty": "10", "trde_prica": str(v)}
            for i, v in enumerate(trade_values)
        ]
    }


def test_build_liquid_universe_filters_by_average_trading_value():
    ranking_page = {
        "trde_prica_upper": [
            _ranking_item("000660", "SK하이닉스", 1, 999999),
            _ranking_item("999999", "저유동성종목", 2, 100),
        ]
    }
    # 000660: 5일 평균 = (120000+110000+130000+90000+150000)/5 = 120000 백만원 = 1200억
    daily_by_code = {
        "000660": _daily_records([120000, 110000, 130000, 90000, 150000]),
        "999999": _daily_records([500, 400, 600, 300, 700]),  # 평균 5억
    }
    client = _StubClient(ranking_page, daily_by_code)

    universe = build_liquid_universe(client, min_avg_trading_value_eok=1000, candidate_pool_size=10)

    assert list(universe["stock_code"]) == ["000660"]
    assert universe.iloc[0]["avg_trading_value_eok"] == 1200.0


def test_build_liquid_universe_sorts_descending_by_avg_value():
    ranking_page = {
        "trde_prica_upper": [
            _ranking_item("111111", "A", 1, 999999),
            _ranking_item("222222", "B", 2, 999999),
        ]
    }
    daily_by_code = {
        "111111": _daily_records([100000] * 5),  # 1000억
        "222222": _daily_records([200000] * 5),  # 2000억
    }
    client = _StubClient(ranking_page, daily_by_code)

    universe = build_liquid_universe(client, min_avg_trading_value_eok=500, candidate_pool_size=10)

    assert list(universe["stock_code"]) == ["222222", "111111"]


def test_build_liquid_universe_skips_candidate_with_no_daily_data():
    ranking_page = {"trde_prica_upper": [_ranking_item("333333", "무기록", 1, 999999)]}
    client = _StubClient(ranking_page, daily_by_code={})

    universe = build_liquid_universe(client, min_avg_trading_value_eok=1000, candidate_pool_size=10)

    assert universe.empty


def test_build_liquid_universe_returns_empty_dataframe_with_expected_shape_when_no_candidates():
    ranking_page = {"trde_prica_upper": []}
    client = _StubClient(ranking_page, daily_by_code={})

    universe = build_liquid_universe(client, min_avg_trading_value_eok=1000, candidate_pool_size=10)

    assert isinstance(universe, pd.DataFrame)
    assert universe.empty


class _StubStockListClient:
    def __init__(self, kospi_items: list[dict], kosdaq_items: list[dict]):
        self._kospi_items = kospi_items
        self._kosdaq_items = kosdaq_items

    def get_stock_list(self, market_type):
        return self._kospi_items if market_type == "0" else self._kosdaq_items


def _stock_list_item(code, name, market_name):
    return {"code": code, "name": name, "marketName": market_name}


def test_list_all_individual_stocks_excludes_etf_from_kospi():
    client = _StubStockListClient(
        kospi_items=[
            _stock_list_item("005930", "삼성전자", "거래소"),
            _stock_list_item("069500", "KODEX 200", "ETF"),
        ],
        kosdaq_items=[_stock_list_item("000660", "SK하이닉스", "코스닥")],
    )

    result = list_all_individual_stocks(client)

    assert set(result["stock_code"]) == {"005930", "000660"}


def test_list_all_individual_stocks_respects_market_filter():
    client = _StubStockListClient(
        kospi_items=[_stock_list_item("005930", "삼성전자", "거래소")],
        kosdaq_items=[_stock_list_item("000660", "SK하이닉스", "코스닥")],
    )

    kospi_only = list_all_individual_stocks(client, market="001")

    assert list(kospi_only["stock_code"]) == ["005930"]


class _StubUnionClient(_StubStockListClient):
    def __init__(self, kospi_items, kosdaq_items, daily_by_code):
        super().__init__(kospi_items, kosdaq_items)
        self._daily_by_code = daily_by_code

    def get_daily_chart(self, stock_code, base_date=""):
        return self._daily_by_code.get(stock_code, {"stk_dt_pole_chart_qry": []})


def _daily_value_records(dates_and_values: list[tuple[str, int]]) -> dict:
    return {
        "stk_dt_pole_chart_qry": [
            {"dt": d, "trde_prica": str(v)} for d, v in dates_and_values
        ]
    }


def test_build_topn_union_universe_includes_stock_that_only_led_on_one_day():
    """과거 특정 하루만 top_n이었던 종목도 합집합에 포함되어야 한다."""
    client = _StubUnionClient(
        kospi_items=[_stock_list_item("A", "종목A", "거래소"), _stock_list_item("B", "종목B", "거래소")],
        kosdaq_items=[],
        daily_by_code={
            "A": _daily_value_records([("20260101", 100), ("20260102", 100)]),
            "B": _daily_value_records([("20260101", 50), ("20260102", 200)]),  # 20260102에만 A를 역전
        },
    )

    result = build_topn_union_universe(client, top_n=1, lookback_days=252)

    assert set(result["stock_code"]) == {"A", "B"}


def test_build_topn_union_universe_excludes_stock_never_in_top_n():
    client = _StubUnionClient(
        kospi_items=[
            _stock_list_item("A", "종목A", "거래소"),
            _stock_list_item("B", "종목B", "거래소"),
            _stock_list_item("C", "종목C", "거래소"),
        ],
        kosdaq_items=[],
        daily_by_code={
            "A": _daily_value_records([("20260101", 300)]),
            "B": _daily_value_records([("20260101", 200)]),
            "C": _daily_value_records([("20260101", 100)]),  # 항상 3위, top_n=2에서 제외
        },
    )

    result = build_topn_union_universe(client, top_n=2, lookback_days=252)

    assert set(result["stock_code"]) == {"A", "B"}


def test_build_topn_union_universe_skips_stock_with_fetch_error():
    class _FlakyUnionClient(_StubUnionClient):
        def get_daily_chart(self, stock_code, base_date=""):
            if stock_code == "A":
                raise RuntimeError("API error")
            return super().get_daily_chart(stock_code, base_date)

    client = _FlakyUnionClient(
        kospi_items=[_stock_list_item("A", "종목A", "거래소"), _stock_list_item("B", "종목B", "거래소")],
        kosdaq_items=[],
        daily_by_code={"B": _daily_value_records([("20260101", 100)])},
    )

    result = build_topn_union_universe(client, top_n=5, lookback_days=252)

    assert set(result["stock_code"]) == {"B"}


def _write_daily_csv(path, dates, closes, volumes):
    idx = pd.to_datetime(dates)
    idx.name = "date"  # 실제 로컬 캐시 CSV 헤더(date,open,...)와 맞춘다 - DuckDB는 컬럼명으로 읽는다.
    pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": volumes},
        index=idx,
    ).to_csv(path)


def test_daily_top_n_from_local_uses_previous_day_ranking(tmp_path):
    """D일 유니버스는 D-1일 거래대금 순위 — 같은 날 값을 쓰면 미래참조."""
    _write_daily_csv(tmp_path / "A.csv", ["2026-01-01", "2026-01-02"], [100, 100], [10, 5])  # 1000, 500
    _write_daily_csv(tmp_path / "B.csv", ["2026-01-01", "2026-01-02"], [100, 100], [20, 1])  # 2000, 100

    result = daily_top_n_from_local(str(tmp_path), top_n=1)

    # 01-02의 유니버스는 01-01 순위(B가 2000으로 1위) — 01-02 당일 순위(A)가 아니다.
    assert result[pd.Timestamp("2026-01-02")] == {"B"}
    # 첫 거래일은 직전일이 없어 유니버스를 정할 수 없다.
    assert pd.Timestamp("2026-01-01") not in result


def test_daily_top_n_from_local_includes_multiple_codes_up_to_top_n(tmp_path):
    _write_daily_csv(tmp_path / "A.csv", ["2026-01-01", "2026-01-02"], [100, 100], [30, 1])  # 3000
    _write_daily_csv(tmp_path / "B.csv", ["2026-01-01", "2026-01-02"], [100, 100], [20, 1])  # 2000
    _write_daily_csv(tmp_path / "C.csv", ["2026-01-01", "2026-01-02"], [100, 100], [10, 1])  # 1000

    result = daily_top_n_from_local(str(tmp_path), top_n=2)

    assert result[pd.Timestamp("2026-01-02")] == {"A", "B"}


def _write_minute_csv(path, times, closes, volumes):
    idx = pd.to_datetime([f"2026-01-02 {t}" for t in times])
    idx.name = "date"
    pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": volumes}, index=idx
    ).to_csv(path)


def test_intraday_top_n_return_rank1_by_minute_breaks_exact_ties_deterministically(tmp_path):
    """회귀 테스트: 벡터화 최적화(2026-08-29) 검증 중 108,791분 표본에서 18건의
    불일치를 발견했는데, 손으로 대조해보니 18건 전부 진짜 동률(등락률까지 정확히
    같음)이었다 — 어느 구현이 틀린 게 아니라 동률 처리 방식 차이였다. 이 테스트는
    그 시나리오(전일종가 100, 두 종목이 정확히 같은 등락률로 거래대금 상위 2위 안에
    듦)를 합성 데이터로 재현해 결과가 항상 같은 종목(정렬 순서상 먼저 오는 코드)으로
    결정적으로 나오는지 확인한다 - 다음에 누가 또 벡터화를 시도할 때 이 케이스를
    "버그"로 오인하지 않도록."""
    (tmp_path / "stocks" / "minute").mkdir(parents=True)
    (tmp_path / "stocks" / "daily").mkdir(parents=True)
    minute_dir = tmp_path / "stocks" / "minute"
    daily_dir = tmp_path / "stocks" / "daily"

    for code in ["A", "B", "C"]:
        _write_daily_csv(daily_dir / f"{code}.csv", ["2026-01-01", "2026-01-02"], [100, 100], [1, 1])

    times = ["09:00", "09:01", "09:02"]
    # A/B: 09:00·09:01엔 등락률이 정확히 5%로 동률(A가 거래대금 1위, B가 2위 - C보다는
    # 항상 크다). 09:02엔 B가 8%로 앞서 동률이 깨진다 - "항상 A만 이긴다"가 아니라
    # 진짜 값 비교가 살아있는지도 같이 확인.
    _write_minute_csv(minute_dir / "A.csv", times, closes=[105, 105, 105], volumes=[100, 100, 100])
    _write_minute_csv(minute_dir / "B.csv", times, closes=[105, 105, 108], volumes=[90, 90, 90])
    _write_minute_csv(minute_dir / "C.csv", times, closes=[110, 110, 110], volumes=[50, 50, 50])

    result = intraday_top_n_return_rank1_by_minute(str(tmp_path), trading_value_rank_n=2)

    # C는 등락률이 가장 높지만(10%) 거래대금이 3위라 top-2(A,B) 밖 - 후보에서 제외.
    assert result[pd.Timestamp("2026-01-02 09:00:00")] == "A"  # A/B 동률(5%) -> 정렬상 먼저인 A
    assert result[pd.Timestamp("2026-01-02 09:01:00")] == "A"  # 반복 확인(우연 아님)
    assert result[pd.Timestamp("2026-01-02 09:02:00")] == "B"  # 동률 깨지면 실제로 더 높은 쪽(B)이 이김


def test_duckdb_version_matches_pandas_version_on_tie_break_scenario(tmp_path):
    """DuckDB 버전(intraday_top_n_return_rank1_by_minute_duckdb)이 판단 로직이 가장
    까다로운 동률 시나리오에서도 pandas 버전과 완전히 같은 결과를 내는지 - 이게
    깨지면 DuckDB 버전을 쓰지 않는다."""
    (tmp_path / "stocks" / "minute").mkdir(parents=True)
    (tmp_path / "stocks" / "daily").mkdir(parents=True)
    minute_dir = tmp_path / "stocks" / "minute"
    daily_dir = tmp_path / "stocks" / "daily"

    for code in ["A", "B", "C"]:
        _write_daily_csv(daily_dir / f"{code}.csv", ["2026-01-01", "2026-01-02"], [100, 100], [1, 1])

    times = ["09:00", "09:01", "09:02"]
    _write_minute_csv(minute_dir / "A.csv", times, closes=[105, 105, 105], volumes=[100, 100, 100])
    _write_minute_csv(minute_dir / "B.csv", times, closes=[105, 105, 108], volumes=[90, 90, 90])
    _write_minute_csv(minute_dir / "C.csv", times, closes=[110, 110, 110], volumes=[50, 50, 50])

    pandas_result = intraday_top_n_return_rank1_by_minute(str(tmp_path), trading_value_rank_n=2)
    duckdb_result = intraday_top_n_return_rank1_by_minute_duckdb(str(tmp_path), trading_value_rank_n=2)

    assert duckdb_result == pandas_result


def test_duckdb_version_matches_pandas_version_with_missing_daily_date_gap(tmp_path):
    """한 종목의 특정 날짜만 일봉이 빠진 경우(수집 결측) - 그 날짜의 등락률은 계산
    불가(제외)돼야 하지만, 그 종목 자체가 거래대금 랭킹 풀에서 통째로 빠지면 안 된다
    (INNER JOIN으로 잘못 구현하면 이 조건이 깨진다 - LEFT JOIN이어야 함)."""
    (tmp_path / "stocks" / "minute").mkdir(parents=True)
    (tmp_path / "stocks" / "daily").mkdir(parents=True)
    minute_dir = tmp_path / "stocks" / "minute"
    daily_dir = tmp_path / "stocks" / "daily"

    # A: 01-02 일봉 누락(01-01만 있음) - 01-02 분봉은 있는데 prev_close를 못 구함.
    _write_daily_csv(daily_dir / "A.csv", ["2026-01-01"], [100], [1])
    _write_daily_csv(daily_dir / "B.csv", ["2026-01-01", "2026-01-02"], [100, 100], [1, 1])

    times = ["09:00"]
    _write_minute_csv(minute_dir / "A.csv", times, closes=[120], volumes=[1000])  # 거래대금 1위, 등락률 불명
    _write_minute_csv(minute_dir / "B.csv", times, closes=[102], volumes=[10])    # 거래대금 2위, 등락률 2%

    pandas_result = intraday_top_n_return_rank1_by_minute(str(tmp_path), trading_value_rank_n=2)
    duckdb_result = intraday_top_n_return_rank1_by_minute_duckdb(str(tmp_path), trading_value_rank_n=2)

    assert duckdb_result == pandas_result
    # A는 등락률을 몰라 후보에서 빠지고, top-2 안의 B가 유일한 유효 후보로 이긴다.
    assert pandas_result[pd.Timestamp("2026-01-02 09:00:00")] == "B"
