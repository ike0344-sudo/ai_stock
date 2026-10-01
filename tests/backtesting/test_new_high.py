"""52주 신고가·후보 — 상태 경계(3%·7%·20%·터치후밀림) 손계산."""
import numpy as np
import pandas as pd

from backtesting.new_high import atr_pct, high52_of, state_series


def _panel(closes: dict, highs: dict | None = None, volumes: dict | None = None, n: int = 260) -> tuple:
    """마지막 날 종가로 상태를 가르는 5+종목. high52 는 마지막 날 직전(오늘 제외) 최댓값 100 으로 고정(첫 N-1일=100, 마지막날만 다름)."""
    idx = pd.bdate_range("2020-01-02", periods=n)
    close = pd.DataFrame({k: [100.0] * (n - 1) + [v] for k, v in closes.items()}, index=idx)
    highs = highs or {}
    high = pd.DataFrame({k: [100.0] * (n - 1) + [highs.get(k, closes[k])] for k in closes}, index=idx)
    low = close - 1
    vol = volumes or {k: 1000.0 for k in closes}
    volume = pd.DataFrame({k: [1000.0] * (n - 1) + [vol[k]] for k in closes}, index=idx)
    return close, high, low, volume


def test_상태_경계_5종목_손계산():
    """52주 최고가(어제까지) = 100(위 _panel 구성). 고가까지% = 100/종가−1."""
    closes = {
        "관찰": 83.0,      # 100/83-1=20.5%>20% -> 밖(후보 아님)
        "관찰2": 85.0,     # 100/85-1=17.6% -> 관찰(7~20%)
        "근접": 95.0,      # 100/95-1=5.3% -> 근접(3~7%)
        "임박": 98.5,      # 100/98.5-1=1.5% -> 임박(0~3%)
        "돌파": 101.0,     # 종가>=100 -> 돌파
    }
    close, high, low, volume = _panel(closes)
    h52 = high52_of(high)
    state, breakout = state_series(close, high, h52, volume)
    last = state.iloc[-1]
    assert last["관찰"] == "밖"
    assert last["관찰2"] == "관찰"
    assert last["근접"] == "근접"
    assert last["임박"] == "임박"
    assert last["돌파"] in ("돌파중", "돌파성공")


def test_터치_후_밀림이_최우선():
    """당일 고가가 52주 최고가(100) 이상인데 종가는 그 아래(밀림) — 밴드보다 우선."""
    closes = {"밀림": 95.0}   # 근접 밴드에 들 값이지만
    highs = {"밀림": 101.0}   # 당일 고가가 최고가를 찍었다
    close, high, low, volume = _panel(closes, highs)
    h52 = high52_of(high)
    state, breakout = state_series(close, high, h52, volume)
    assert state.iloc[-1]["밀림"] == "터치 후 밀림"


def test_돌파중_대_돌파성공():
    """옛 스파이크(50일째 고가 100) 뒤 80대에서 쉬다 마지막 이틀 그 100을 다시 넘김 — 첫날 돌파중, 둘째 날 돌파성공.
    (주의: 평평한 가격이 그대로 52주 최고가와 같으면 그 자체가 매일 '돌파'가 되어버려 — 쉬는 구간은 최고가보다 낮게 둬야 한다.)"""
    idx = pd.bdate_range("2020-01-02", periods=260)
    vals = [80.0] * 260
    vals[49] = 100.0  # 옛 스파이크(50일째) — 이후 250거래일 안에 계속 "52주 최고가" 기준으로 남는다
    vals[-2], vals[-1] = 101.0, 102.0
    close = pd.DataFrame({"C": vals}, index=idx)
    high = close.copy()
    low = close - 1
    volume = pd.DataFrame({"C": [1000.0] * 260}, index=idx)
    h52 = high52_of(high)
    state, breakout = state_series(close, high, h52, volume)
    assert state["C"].iloc[-2] == "돌파중" and state["C"].iloc[-1] == "돌파성공"


def test_거래정지_플랫은_돌파로_안_잡는다():
    """거래량 0 인 채 가격이 52주 최고가와 우연히 같으면(거래정지) 돌파가 아니다 — 실측(삼부토건 등)으로 발견해 고침."""
    idx = pd.bdate_range("2020-01-02", periods=260)
    close = pd.DataFrame({"HALT": [100.0] * 260})
    close.index = idx
    high = close.copy()
    low = close - 0  # 거래정지는 시가=고가=저가=종가
    volume = pd.DataFrame({"HALT": [1000.0] * 200 + [0.0] * 60}, index=idx)  # 최근 60일 거래정지
    h52 = high52_of(high)
    state, breakout = state_series(close, high, h52, volume)
    assert state["HALT"].iloc[-1] not in ("돌파중", "돌파성공", "터치 후 밀림")
    assert not breakout["HALT"].iloc[-1]


def test_ATR_퍼센트_손계산():
    idx = pd.bdate_range("2020-01-02", periods=3)
    high = pd.DataFrame({"A": [110.0, 112.0, 108.0]}, index=idx)
    low = pd.DataFrame({"A": [100.0, 101.0, 100.0]}, index=idx)
    close = pd.DataFrame({"A": [105.0, 111.0, 104.0]}, index=idx)
    a = atr_pct(high, low, close, n=2)
    # t=2: TR1(t=1)=max(112-101,|112-105|,|101-105|)=11 ; TR2(t=2)=max(108-100,|108-111|,|100-111|)=11 -> ATR=11, /104
    assert a["A"].iloc[-1] == pytest_approx(11.0 / 104.0)


def pytest_approx(x, tol=1e-9):
    import pytest
    return pytest.approx(x, abs=tol)
