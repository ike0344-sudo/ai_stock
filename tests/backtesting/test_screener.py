from backtesting.screener import _is_excluded_instrument, top_by_trading_value


def test_is_excluded_instrument_detects_known_brand_prefixes():
    assert _is_excluded_instrument("KODEX 200") is True
    assert _is_excluded_instrument("TIGER 미국S&P500") is True
    assert _is_excluded_instrument("SOL AI반도체TOP2플러스") is True


def test_is_excluded_instrument_detects_etn_suffix():
    assert _is_excluded_instrument("삼성 레버리지 ETN") is True


def test_is_excluded_instrument_detects_spac_marker():
    assert _is_excluded_instrument("NH스팩19호") is True
    assert _is_excluded_instrument("미래에셋비전기업인수목적1호") is True


def test_is_excluded_instrument_leaves_regular_stocks_alone():
    assert _is_excluded_instrument("SK하이닉스") is False
    assert _is_excluded_instrument("삼성전자") is False
    assert _is_excluded_instrument("NAVER") is False


class _StubRankingClient:
    def __init__(self, pages: list[dict]):
        self._pages = pages
        self.last_cont_yn = "N"
        self.last_next_key = ""
        self._i = 0

    def request_tr(self, api_id, body, path, cont_yn="N", next_key=""):
        page = self._pages[self._i]
        self._i += 1
        self.last_cont_yn = "Y" if self._i < len(self._pages) else "N"
        self.last_next_key = str(self._i) if self.last_cont_yn == "Y" else ""
        return page


def _item(code: str, name: str, rank: int, trade_value: int) -> dict:
    return {"stk_cd": code, "stk_nm": name, "now_rank": str(rank), "trde_prica": str(trade_value)}


def test_top_by_trading_value_filters_spac():
    page1 = {
        "trde_prica_upper": [
            _item("000660", "SK하이닉스", 1, 1000),
            _item("450000", "NH스팩19호", 2, 900),
            _item("005930", "삼성전자", 3, 800),
        ]
    }
    client = _StubRankingClient([page1])

    df = top_by_trading_value(client, top_n=5)

    assert set(df["stock_code"]) == {"000660", "005930"}


def test_top_by_trading_value_filters_etf_and_respects_top_n():
    page1 = {
        "trde_prica_upper": [
            _item("000660", "SK하이닉스", 1, 1000),
            _item("069500", "KODEX 200", 2, 900),
            _item("005930", "삼성전자", 3, 800),
        ]
    }
    client = _StubRankingClient([page1])

    df = top_by_trading_value(client, top_n=2)

    assert list(df["stock_code"]) == ["000660", "005930"]


def test_top_by_trading_value_paginates_until_top_n_filled():
    page1 = {"trde_prica_upper": [_item("069500", "KODEX 200", 1, 900)]}  # 전부 ETF라 다음 페이지 필요
    page2 = {
        "trde_prica_upper": [
            _item("005930", "삼성전자", 2, 800),
            _item("000660", "SK하이닉스", 3, 700),
        ]
    }
    client = _StubRankingClient([page1, page2])

    df = top_by_trading_value(client, top_n=2, max_pages=5)

    assert len(df) == 2
    assert set(df["stock_code"]) == {"005930", "000660"}


def test_top_by_trading_value_includes_etf_when_disabled():
    page1 = {"trde_prica_upper": [_item("069500", "KODEX 200", 1, 900)]}
    client = _StubRankingClient([page1])

    df = top_by_trading_value(client, top_n=5, exclude_etf=False)

    assert list(df["stock_code"]) == ["069500"]
