"""차분이 시간대별 칸의 전부다 — 여기가 틀리면 화면 전체가 조용히 거짓말을 한다."""
from investor_flow import _color, _fmt, _num, diff


def test_부호가_두_번_붙어_온다():
    """ka10051 은 '--264' 처럼 부호를 겹쳐 준다(8/26 실제 응답)."""
    assert _num("--264") == -264
    assert _num("+5467") == 5467
    assert _num("0") == 0


def test_플레이스홀더는_0이_아니라_None이다():
    """빈 문자열/플레이스홀더를 0으로 뭉개면 "데이터 없음"이 "순매수 0"으로
    거짓 표시된다(state/agent_reports 참고: TradingAgents salvage §3 후속).
    진짜 0("0")과는 명확히 구분되어야 한다."""
    assert _num("") is None
    assert _num("-") is None
    assert _num("N/A") is None
    assert _num("0") == 0          # 진짜 0은 여전히 0
    assert _num("--264") == -264   # 정상 파싱은 그대로


def test_fmt_color_는_None을_데이터없음으로_그린다():
    """_fmt/_color가 None을 falsy로 취급해 "0"으로 그리던 버그(`if v:`는 None도
    falsy)를 잡는다 — 0782의 기존 '-' 표기와 맞춘다."""
    assert _fmt(None) == "-"
    assert _fmt(0) == "0"          # 진짜 0은 여전히 "0"
    assert _fmt(-18) == "-18"
    from investor_flow import ZERO
    assert _color(None) == ZERO


def test_첫_응답은_기준선만_잡는다():
    """첫 조회에 누적을 그대로 그리면 하루치가 1분 구간으로 둔갑한다."""
    assert diff(None, {"ind_netprps": -21482}) is None


def test_구간은_누적의_차다():
    prev = {"ind_netprps": -21482, "frgnr_netprps": -754}
    cur = {"ind_netprps": -21500, "frgnr_netprps": -700}
    d = diff(prev, cur)
    assert d["ind_netprps"] == -18
    assert d["frgnr_netprps"] == 54


def test_구간은_한쪽이_없으면_None이다():
    """파싱 실패(None)와 진짜 값을 빼서 가짜 증감을 만들면 안 된다."""
    prev = {"ind_netprps": -21482, "frgnr_netprps": None}
    cur = {"ind_netprps": -21500, "frgnr_netprps": -700}
    d = diff(prev, cur)
    assert d["ind_netprps"] == -18
    assert d["frgnr_netprps"] is None


def test_CSV_를_읽어_증감까지_만든다(tmp_path):
    """0782 CSV 는 cp949·누적·최신이 위다. 증감은 바로 아랫줄과의 차여야 한다."""
    from pathlib import Path

    from investor_flow import load_csv

    p = Path(tmp_path) / "001.csv"
    p.write_text(
        "시간,개인,외국인,기관계,금융투자,보험,투신,기타금융,은행,연기금등,사모펀드,기타법인\n"
        '14:56:00,"-24,744","+1,458","+7,613","0","0","0","0","0","0","0","0"\n'
        '14:54:00,"-24,787","+1,471","+7,704","0","0","0","0","0","0","0","0"\n',
        encoding="cp949")
    rows = load_csv(p)
    assert rows[0][0] == "14:56:00"
    assert rows[0][1]["ind_netprps"] == -24744          # 누적은 파일 값 그대로
    assert rows[0][2]["ind_netprps"] == 43              # 증감 = -24,744 - (-24,787)
    assert rows[-1][2] is None                          # 맨 아랫줄은 견줄 곳이 없다


def test_CSV_플레이스홀더_셀은_None이지_0이_아니다(tmp_path):
    """0782가 어떤 칸을 '-'로 내보내도(장 시작 전 등) 그게 0으로 둔갑하면 안 된다."""
    from pathlib import Path

    from investor_flow import load_csv

    p = Path(tmp_path) / "001.csv"
    p.write_text(
        "시간,개인,외국인,기관계,금융투자,보험,투신,기타금융,은행,연기금등,사모펀드,기타법인\n"
        '09:01:00,"-","+100","0","0","0","0","0","0","0","0","0"\n',
        encoding="cp949")
    rows = load_csv(p)
    assert rows[0][1]["ind_netprps"] is None            # "-" 는 데이터 없음
    assert rows[0][1]["frgnr_netprps"] == 100            # 정상 값은 그대로
    assert rows[0][1]["orgn_netprps"] == 0                # 진짜 0은 그대로 0
