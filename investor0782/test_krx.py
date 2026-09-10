"""KRX 매도/매수 파싱 실패가 화면에 가짜 숫자(0)를 만들지 않는지 확인.

배경: state/agent_reports/data-agent_20260910-1701_tradingagents_salvage.md §3
(TradingAgents 대비 우리 쪽 조용한 실패) 후속.
"""
from krx import Krx, _num


def test_num_플레이스홀더는_0이_아니라_None이다():
    assert _num("") is None
    assert _num("-") is None
    assert _num("N/A") is None
    assert _num("0") == 0            # 진짜 0은 여전히 0
    assert _num("1,234") == 1234


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    """Krx.sell_buy가 쓰는 requests.Session 표면만 흉내낸다."""

    def __init__(self, payload):
        self.headers: dict = {}
        self._payload = payload

    def get(self, url, timeout=None):
        return _FakeResponse({})

    def post(self, url, headers=None, data=None, timeout=None):
        return _FakeResponse(self._payload)


def test_sell_buy는_파싱실패_업종을_통째로_빼고_나머지는_유지(capsys):
    payload = {"output": [
        {"INVST_TP_NM": "개인", "ASK_TRDVAL": "1,000,000,000", "BID_TRDVAL": "2,000,000,000"},
        # 외국인은 매도(ASK_TRDVAL)가 플레이스홀더 — 예전엔 0으로 뭉개져 거짓 숫자가 찍혔다.
        {"INVST_TP_NM": "외국인", "ASK_TRDVAL": "-", "BID_TRDVAL": "500,000,000"},
    ]}
    krx = Krx()
    krx._s = _FakeSession(payload)
    krx._ready = True  # _warm()의 실제 네트워크 호출을 건너뛴다

    out = krx.sell_buy("0", "20260910")

    assert out["ind_netprps"] == (10, 20)     # EOK=100,000,000 단위로 환산됨
    assert "frgnr_netprps" not in out         # 파싱 실패 업종은 아예 빠짐(0으로 안 뭉갬)
    assert "파싱 실패" in capsys.readouterr().out


def test_sell_buy는_전부_정상이면_스킵_로그가_없다(capsys):
    payload = {"output": [
        {"INVST_TP_NM": "개인", "ASK_TRDVAL": "1,000,000,000", "BID_TRDVAL": "2,000,000,000"},
    ]}
    krx = Krx()
    krx._s = _FakeSession(payload)
    krx._ready = True

    out = krx.sell_buy("0", "20260910")

    assert out == {"ind_netprps": (10, 20)}
    assert capsys.readouterr().out == ""
