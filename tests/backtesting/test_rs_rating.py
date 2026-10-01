"""RS 점수 — 손으로 만든 5종목 가짜 일봉으로 원점수·백분위가 손계산과 같은지."""
import numpy as np
import pandas as pd

from backtesting.rs_rating import excluded_codes, rs_score, raw_score, quarter_returns

N = 260  # 252 거래일 확보용 여유


def _panel() -> pd.DataFrame:
    """5종목, 마지막 날의 R63/126/189/252 이 서로 뚜렷이 다르게 만든 가격(계단 함수 — 손계산 쉽게).
    A: 마지막 63일만 2배 → R63 큼, 나머지 n 은 0. B: 마지막 252일 전체 1.5배 → 넷 다 R>0, 값은 작음.
    C: 전부 보합(R 전부 0). D: 마지막 63일 반토막(R63<0). E: 신규상장(짧은 이력, 252 미만 → RS 없음)."""
    idx = pd.bdate_range("2020-01-02", periods=N)

    def steps(*segs):  # [(길이, 값)] 뒤에서부터 채움
        out = np.empty(N)
        pos = N
        for length, val in reversed(segs):
            out[pos - length:pos] = val
            pos -= length
        assert pos == 0
        return out

    a = steps((N - 63, 100.0), (63, 200.0))          # 63일 전 100 -> 지금 200: R63=+100%, R126/189/252 도 0 아님(63일전이 이미 100)
    b = steps((N - 252, 100.0), (252, 150.0))
    c = np.full(N, 100.0)
    d = steps((N - 63, 100.0), (63, 50.0))
    e = np.concatenate([np.full(N - 100, np.nan), np.full(100, 100.0)])  # 최근 100일치만(신규상장)
    return pd.DataFrame({"AAAAAA": a, "BBBBBB": b, "CCCCCC": c, "DDDDDD": d, "EEEEEE": e}, index=idx)


def test_원점수_손계산과_같다():
    """종합 원점수 = 0.4q1+0.2q2+0.2q3+0.2q4(겹치지 않는 분기 수익률, 18:15 편지) — 옛 오닐식(겹치는 누적) 아님."""
    close = _panel()
    raw = raw_score(close)
    last = raw.iloc[-1]

    def hand(col: str) -> float:
        c = close[col]
        q = [c.iloc[-1 - 63 * i] / c.iloc[-1 - 63 * (i + 1)] - 1 for i in range(4)]
        return 0.4 * q[0] + 0.2 * q[1] + 0.2 * q[2] + 0.2 * q[3]

    for col in ("AAAAAA", "BBBBBB", "CCCCCC", "DDDDDD"):
        assert raw[col].iloc[-1] == pytest_approx(hand(col))
    assert not np.isnan(raw["CCCCCC"].iloc[-1]) and raw["CCCCCC"].iloc[-1] == 0.0
    # A: 마지막 63일만 2배(q1=+100%, q2=q3=q4=0) -> 0.4  B: 252일 전체 1.5배 겹치지 않는 4분기 전부 동일 복리 -> 작지만 다 양수
    assert raw["AAAAAA"].iloc[-1] > raw["BBBBBB"].iloc[-1] > raw["CCCCCC"].iloc[-1] > raw["DDDDDD"].iloc[-1]
    assert np.isnan(last["EEEEEE"])  # 252거래일 안 된 신규상장 — q4 없음 -> 원점수 NaN


def test_분기수익률_겹치지_않는다():
    close = _panel()
    q = quarter_returns(close)
    c = close["AAAAAA"]
    assert q[1]["AAAAAA"].iloc[-1] == pytest_approx(c.iloc[-1] / c.iloc[-64] - 1)          # 최근 63일
    assert q[2]["AAAAAA"].iloc[-1] == pytest_approx(c.iloc[-64] / c.iloc[-127] - 1)         # 63~126일 전(q1 과 안 겹침)


def pytest_approx(x, tol=1e-9):
    import pytest
    return pytest.approx(x, abs=tol)


def test_백분위_1_99_손계산과_같다():
    """4종목만(NaN 인 EEEEEE 제외 대상) 순위: A>B>C>D. n=4 -> pct=1/4,2/4,3/4,4/4 -> ceil(*99)=[25,50,75,99]."""
    close = _panel()
    raw = raw_score(close)
    rs = rs_score(raw)
    last = rs.iloc[-1]
    assert last["EEEEEE"] != last["EEEEEE"]  # NaN (신규상장은 점수 없음)
    assert (int(last["DDDDDD"]), int(last["CCCCCC"]), int(last["BBBBBB"]), int(last["AAAAAA"])) == (25, 50, 75, 99)


def test_동률은_평균_순위():
    close = _panel()
    close["FFFFFF"] = close["CCCCCC"]  # CCCCCC 와 완전히 같은 가격(동률)
    raw = raw_score(close)
    rs = rs_score(raw)
    last = rs.iloc[-1]
    assert last["CCCCCC"] == last["FFFFFF"]  # 동률은 같은 점수


def test_ETF_ETN_스팩만_빠지고_우선주는_남는다():
    names = {"005930": "삼성전자", "005935": "삼성전자우", "069500": "KODEX 200", "123456": "가나다스팩"}
    excl = excluded_codes(names)
    assert excl == {"069500", "123456"}
    assert "005935" not in excl  # 우선주는 제외 목록에 없다(그대로 남긴다)


def test_시가총액_모집단_2000억_미만_제외():
    from backtesting.rs_rating import population_mask, MIN_MARKET_CAP
    idx = pd.bdate_range("2020-01-02", periods=3)
    close = pd.DataFrame({"AAAAAA": [10000.0] * 3, "BBBBBB": [10000.0] * 3, "CCCCCC": [10000.0] * 3}, index=idx)
    # AAAAAA: 10000원 x 3천만주 = 3000억(>=2000억, 포함) / BBBBBB: 10000 x 1천만주 = 1000억(<2000억, 제외) / CCCCCC: 상장주식수 모름(제외)
    pop = population_mask(close, shares={"AAAAAA": 30_000_000, "BBBBBB": 10_000_000})
    assert pop["AAAAAA"].all() and (~pop["BBBBBB"]).all() and (~pop["CCCCCC"]).all()
    assert 10000.0 * 30_000_000 >= MIN_MARKET_CAP > 10000.0 * 10_000_000


def test_기간별_원점수는_그_기간_단독_수익률():
    from backtesting.rs_rating import period_raw
    close = _panel()
    r63 = period_raw(close, 63)
    assert r63["AAAAAA"].iloc[-1] == pytest_approx(close["AAAAAA"].iloc[-1] / close["AAAAAA"].iloc[-64] - 1)


def test_MTT_8개_기준_손계산():
    from backtesting.rs_rating import mtt
    from types import SimpleNamespace
    idx = pd.bdate_range("2020-01-02", periods=260)
    # 꾸준히 우상향(모든 이평 정배열·52주 저가 대비 크게 위·52주 고가 근처) + RS=80(>=70) -> 8/8 전부 충족
    up = pd.Series(np.linspace(100, 260, 260), index=idx)
    close = pd.DataFrame({"UP": up, "FLAT": pd.Series(100.0, index=idx)})
    high, low = close + 1, close - 1
    rs = pd.DataFrame({"UP": [80.0] * 260, "FLAT": [50.0] * 260}, index=idx)
    b = {"close": close, "high": high, "low": low, "rs": rs}
    m = mtt(b, idx[-1])
    assert bool(m.loc["UP", "mtt_all"]) and m.loc["UP", "mtt_count"] == 8
    assert not bool(m.loc["FLAT", "mtt_all"])  # 보합은 이평이 전부 같아 정배열·1개월 상승·RS 조건이 깨짐


def test_MTT_이력_부족이면_NaN():
    from backtesting.rs_rating import mtt
    idx = pd.bdate_range("2020-01-02", periods=50)  # 200일선을 못 만드는 짧은 이력
    close = pd.DataFrame({"NEW": [100.0] * 50}, index=idx)
    b = {"close": close, "high": close + 1, "low": close - 1, "rs": pd.DataFrame({"NEW": [80.0] * 50}, index=idx)}
    m = mtt(b, idx[-1])
    assert pd.isna(m.loc["NEW", "mtt_count"])


def test_상위_2퍼센트_순위로_자르고_구분칸():
    from backtesting.rs_rating import top2_table
    idx = pd.bdate_range("2020-01-02", periods=1)
    codes = [f"C{i:03d}" for i in range(100)]  # 100종목 -> 2% = 2명씩
    close = pd.DataFrame({c: [1000.0 + i] for i, c in enumerate(codes)}, index=idx)
    volume = pd.DataFrame({c: [10.0] for c in codes}, index=idx)
    rs1 = pd.DataFrame({c: [float(i)] for i, c in enumerate(codes)}, index=idx)   # 값 클수록 1M 순위 좋음(내림차순)
    rs3 = pd.DataFrame({c: [float(100 - i)] for i, c in enumerate(codes)}, index=idx)  # 값 클수록 3M 순위 좋음 -> 앞쪽 코드가 3M 상위
    rscomp = rs1
    b = {"close": close, "volume": volume, "rs": rscomp,
         "period_rs": {"1m": rs1, "3m": rs3, "6m": rs1}}
    out = top2_table(b, idx[0])
    assert out.attrs["n1"] == 2 and out.attrs["n3"] == 2
    # 1M 상위 2명 = C098,C099(값 최대) / 3M 상위 2명 = C000,C001(값 최대, 100-i 식이라 i 작을수록 큼) -> 겹침 없음 -> 전부 "1M만" 또는 "3M만"
    assert set(out["구분"]) == {"1M만", "3M만"} and len(out) == 4
    assert list(out["구분"]) == ["3M만", "3M만", "1M만", "1M만"]  # 정렬: 둘다->3M만->1M만
    assert out[out["구분"] == "3M만"]["RS3M"].is_monotonic_decreasing


def test_상위_2퍼센트_최소_1명():
    from backtesting.rs_rating import top2_codes
    idx = pd.bdate_range("2020-01-02", periods=1)
    rs = pd.DataFrame({"A": [1.0], "B": [2.0]}, index=idx)  # 2종목의 2% < 1 -> 최소 1명 보장
    c1, c3, n1, n3 = top2_codes({"1m": rs, "3m": rs}, idx[0])
    assert n1 == 1 and n3 == 1 and c1 == {"B"}


def test_섹터_RS_중앙값_손계산():
    from backtesting.rs_rating import sector_rs_median
    rs_day = pd.Series({"A": 10.0, "B": 90.0, "C": 50.0, "D": 99.0, "E": np.nan})
    sector_of = {"A": "반도체", "B": "반도체", "C": "반도체", "D": "바이오"}  # E 는 섹터 매핑 자체가 없음
    m = sector_rs_median(rs_day, sector_of)
    assert m == {"반도체": 50.0, "바이오": 99.0}  # 반도체 중앙값(10,50,90)=50, E 는 섹터 없어 제외


def test_섹터_없는_종목은_미분류():
    from backtesting.rs_rating import load_sectors_stockeasy
    sectors, sub = load_sectors_stockeasy("/no/such/file.csv")
    assert sectors == {} and sub == {}  # 파일 없으면 빈 dict(호출부가 "미분류"로 채움)
