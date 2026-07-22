import pandas as pd

from backtesting.universe import (
    build_liquid_universe,
    build_topn_union_universe,
    daily_top_n_from_local,
    list_all_individual_stocks,
)


class _StubClient:
    def __init__(self, ranking_page: dict, daily_by_code: dict):
        self._ranking_page = ranking_page
        self._daily_by_code = daily_by_code
        self.last_cont_yn = "N"
        self.last_next_key = ""

    def request_tr(self, api_id, body, path, cont_yn="N", next_key=""):
        return self._ranking_page

    def get_daily_chart(self, stock_code, base_date=""):
        return self._daily_by_code.get(stock_code, {"stk_dt_pole_chart_qry": []})


def _ranking_item(code, name, rank, trading_value):
    return {"stk_cd": code, "stk_nm": name, "now_rank": str(rank), "trde_prica": str(trading_value)}


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
    pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": volumes},
        index=pd.to_datetime(dates),
    ).to_csv(path)


def test_daily_top_n_from_local_ranks_by_trading_value_per_date(tmp_path):
    _write_daily_csv(tmp_path / "A.csv", ["2026-01-01", "2026-01-02"], [100, 100], [10, 5])  # 1000, 500
    _write_daily_csv(tmp_path / "B.csv", ["2026-01-01", "2026-01-02"], [100, 100], [20, 1])  # 2000, 100

    result = daily_top_n_from_local(str(tmp_path), top_n=1)

    assert result[pd.Timestamp("2026-01-01")] == {"B"}
    assert result[pd.Timestamp("2026-01-02")] == {"A"}


def test_daily_top_n_from_local_includes_multiple_codes_up_to_top_n(tmp_path):
    _write_daily_csv(tmp_path / "A.csv", ["2026-01-01"], [100], [30])  # 3000
    _write_daily_csv(tmp_path / "B.csv", ["2026-01-01"], [100], [20])  # 2000
    _write_daily_csv(tmp_path / "C.csv", ["2026-01-01"], [100], [10])  # 1000

    result = daily_top_n_from_local(str(tmp_path), top_n=2)

    assert result[pd.Timestamp("2026-01-01")] == {"A", "B"}
