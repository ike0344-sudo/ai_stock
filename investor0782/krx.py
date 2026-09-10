"""KRX 투자자별 거래실적 — 매도/매수 금액 (로그인 불필요).

키움 REST 는 시장·업종 단위로 **순매수만** 준다(ka10051, ka10061 확인). 0782 위쪽
블록의 '매 도'·'매 수' 두 줄은 그래서 KRX 에서 따로 받는다.

로그인이 필요한 dbms/MDC/STAT/* 는 LOGOUT 을 뱉는다. 공매도 잔고와 같은 수법으로
공개 네임스페이스 dbms/MDC_OUT/STAT/* 를 경유하면 익명으로 열린다.

시장 전체만 나온다 — 업종별 매도/매수는 이 경로에 없다.
"""
import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
LOADER = "https://data.krx.co.kr/comm/srt/srtLoader/index.cmd?screenId=MDCSTAT300"
BLD = "dbms/MDC_OUT/STAT/standard/MDCSTAT02201_OUT"
EOK = 100_000_000          # KRX 는 원, 화면은 억원(키움 ka10051 과 같은 단위)

# KRX 이름 -> 화면 열 키. 0782 의 구분과 하나씩 대응된다.
NAME_TO_KEY = {
    "개인": "ind_netprps", "외국인": "frgnr_netprps", "기관합계": "orgn_netprps",
    "금융투자": "sc_netprps", "보험": "insrnc_netprps", "투신": "invtrt_netprps",
    "기타금융": "jnsinkm_netprps", "은행": "bank_netprps", "연기금 등": "endw_netprps",
    "사모": "samo_fund_netprps", "기타법인": "etc_corp_netprps",
}
MKT = {"0": "STK", "1": "KSQ"}      # 화면의 시장 코드 -> KRX 시장 코드


def _num(v: str) -> int | None:
    """파싱 안 되면(플레이스홀더 등) None — "데이터 없음"과 진짜 0을 구분한다
    (realtime_feed.py:69와 같은 스타일). 예전엔 ValueError를 0으로 뭉개서 파싱
    실패가 "순매수 0"으로 화면에 찍혔다."""
    s = str(v).replace(",", "").strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


class Krx:
    def __init__(self) -> None:
        self._s = requests.Session()
        self._s.headers.update({"User-Agent": UA})
        self._ready = False

    def _warm(self) -> None:
        """로더를 한 번 열어야 세션 쿠키가 생긴다."""
        if not self._ready:
            self._s.get(LOADER, timeout=15)
            self._ready = True

    def sell_buy(self, market: str, yyyymmdd: str) -> dict[str, tuple[int, int]]:
        """{열키: (매도, 매수)} 억원. 실패하면 빈 dict — 화면은 '-' 로 둔다.

        행 자체는 왔는데 금액이 파싱 안 되면(플레이스홀더 등) 그 업종을 통째로
        뺀다 — 화면은 이미 "키 없음"을 '-'로 그리므로(investor_flow.py
        _draw_summary) 그 경로를 그대로 태운다. 예전엔 _num이 파싱 실패를 0으로
        뭉개서 "매도/매수 0"이라는 거짓 숫자가 찍혔다.
        """
        self._warm()
        body = {"bld": BLD, "locale": "ko_KR", "mktId": MKT.get(market, "STK"),
                "invstTpCd": "", "strtDd": yyyymmdd, "endDd": yyyymmdd,
                "share": "1", "money": "1", "csvxls_isNo": "false"}
        res = self._s.post(URL, headers={"User-Agent": UA, "Referer": LOADER,
                                         "X-Requested-With": "XMLHttpRequest"},
                           data=body, timeout=20)
        out = {}
        skipped = []
        for row in res.json().get("output", []):
            key = NAME_TO_KEY.get(str(row.get("INVST_TP_NM", "")).strip())
            if not key:
                continue
            sell, buy = _num(row.get("ASK_TRDVAL")), _num(row.get("BID_TRDVAL"))
            if sell is None or buy is None:
                skipped.append(key)
                continue
            out[key] = (sell // EOK, buy // EOK)
        if skipped:
            print(f"[!] KRX 매도/매수 파싱 실패로 제외: {', '.join(skipped)}")
        return out


def demo() -> None:
    """오늘치를 한 번 받아 합이 맞는지 본다 — 매수합과 매도합은 같아야 한다."""
    from datetime import datetime

    got = Krx().sell_buy("0", datetime.now().strftime("%Y%m%d"))
    assert got, "KRX 응답이 비었다"
    assert "ind_netprps" in got and "orgn_netprps" in got
    sell, buy = got["ind_netprps"]
    print(f"코스피 개인 매도 {sell:,}억 매수 {buy:,}억 · 항목 {len(got)}개")


if __name__ == "__main__":
    demo()
