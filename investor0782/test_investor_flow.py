"""차분이 시간대별 칸의 전부다 — 여기가 틀리면 화면 전체가 조용히 거짓말을 한다."""
from investor_flow import _num, diff


def test_부호가_두_번_붙어_온다():
    """ka10051 은 '--264' 처럼 부호를 겹쳐 준다(8/26 실제 응답)."""
    assert _num("--264") == -264
    assert _num("+5467") == 5467
    assert _num("0") == 0
    assert _num("") == 0


def test_첫_응답은_기준선만_잡는다():
    """첫 조회에 누적을 그대로 그리면 하루치가 1분 구간으로 둔갑한다."""
    assert diff(None, {"ind_netprps": -21482}) is None


def test_구간은_누적의_차다():
    prev = {"ind_netprps": -21482, "frgnr_netprps": -754}
    cur = {"ind_netprps": -21500, "frgnr_netprps": -700}
    d = diff(prev, cur)
    assert d["ind_netprps"] == -18
    assert d["frgnr_netprps"] == 54


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
