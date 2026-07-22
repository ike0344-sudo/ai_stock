from backtesting.screener import STEX_TP_COMBINED, TRADE_VALUE_UNIT_WON, _is_excluded_instrument, top_by_trading_value


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
        self.sent_bodies: list[dict] = []

    def request_tr(self, api_id, body, path, cont_yn="N", next_key=""):
        self.sent_bodies.append(body)
        page = self._pages[self._i]
        self._i += 1
        self.last_cont_yn = "Y" if self._i < len(self._pages) else "N"
        self.last_next_key = str(self._i) if self.last_cont_yn == "Y" else ""
        return page


def _item(code: str, name: str, rank: int, trade_value: int, change_rate: float = 0.0) -> dict:
    return {
        "stk_cd": code,
        "stk_nm": name,
        "now_rank": str(rank),
        "trde_prica": str(trade_value),
        "flu_rt": f"{change_rate:+.2f}",
    }


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


def test_top_by_trading_value_converts_trde_prica_from_millions_to_won():
    # trde_prica는 백만원 단위로 내려온다 (예: 4,720,789 == 4,720,789백만원 == 약 4.7조원).
    # 원 단위로 환산하지 않으면 프론트엔드가 실제보다 100만분의 1로 작게 표시한다.
    page1 = {"trde_prica_upper": [_item("000660", "SK하이닉스", 1, 4_720_789)]}
    client = _StubRankingClient([page1])

    df = top_by_trading_value(client, top_n=1)

    assert df.iloc[0]["trading_value"] == 4_720_789 * TRADE_VALUE_UNIT_WON
    assert df.iloc[0]["trading_value"] == 4_720_789_000_000


def test_top_by_trading_value_requests_combined_krx_and_nxt():
    # stex_tp=1(KRX 단독)은 넥스트레이드(NXT) 거래대금이 빠져 실제보다 낮게 집계된다
    # (실측: SK하이닉스 KRX단독 5.15조 vs 통합 8.94조) — 반드시 3(통합)을 요청해야 한다.
    page1 = {"trde_prica_upper": [_item("000660", "SK하이닉스", 1, 1000)]}
    client = _StubRankingClient([page1])

    top_by_trading_value(client, top_n=1)

    assert client.sent_bodies[0]["stex_tp"] == STEX_TP_COMBINED == "3"


def test_top_by_trading_value_strips_al_suffix_from_combined_response():
    # stex_tp=3(통합) 응답은 종목코드에 "_AL" 접미사가 붙는다 — 캔들 조회/주문 등
    # 다운스트림은 순수 6자리 코드를 기대하므로 반드시 제거해야 한다.
    page1 = {"trde_prica_upper": [_item("000660_AL", "SK하이닉스", 1, 1000)]}
    client = _StubRankingClient([page1])

    df = top_by_trading_value(client, top_n=1)

    assert df.iloc[0]["stock_code"] == "000660"


def test_top_by_trading_value_extracts_change_rate():
    page1 = {
        "trde_prica_upper": [
            _item("000660", "SK하이닉스", 1, 1000, change_rate=5.83),
            _item("005930", "삼성전자", 2, 900, change_rate=-2.1),
        ]
    }
    client = _StubRankingClient([page1])

    df = top_by_trading_value(client, top_n=2)

    assert df.iloc[0]["change_rate"] == 5.83
    assert df.iloc[1]["change_rate"] == -2.1
