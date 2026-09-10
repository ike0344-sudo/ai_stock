"""fetch_balance가 연도별 수집 실패를 반환값(.attrs)에 남기는지 확인.

배경: state/agent_reports/data-agent_20260910-1701_tradingagents_salvage.md §3-2 —
3회 재시도 다 실패한 연도가 print만 되고 반환 DataFrame에는 흔적이 없어, 그 해가
빠진 채로도 정상 반환된 것처럼 보였다.
"""
import pandas as pd
import requests

import krx_short_balance


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _ok_year_payload(year):
    return {
        "OutBlock_1": [
            {"RPT_DUTY_OCCR_DD": f"{year}/01/02", "BAL_QTY": "1,000", "BAL_AMT": "10,000",
             "LIST_SHRS": "100,000", "BAL_RTO": "1.0"},
        ]
    }


class _FakeSession:
    """krx_short_balance.fetch_balance가 쓰는 requests.Session 표면만 흉내낸다."""

    def __init__(self, fail_years: set[int]):
        self.headers: dict = {}
        self._fail_years = fail_years

    def get(self, url, timeout=None):
        return _FakeResponse({})

    def post(self, url, headers=None, data=None, timeout=None):
        if data["bld"] == "dbms/comm/finder/finder_srtisu":
            return _FakeResponse({"block1": [{"short_code": "000660", "full_code": "KR7000660001"}]})
        year = int(data["trdDd"][:4])
        if year in self._fail_years:
            raise requests.exceptions.ConnectionError("boom")
        return _FakeResponse(_ok_year_payload(year))


def test_fetch_balance_records_failed_years_in_attrs(monkeypatch):
    current_year = pd.Timestamp.today().year
    fail_year = current_year - 1
    ok_year = current_year
    session = _FakeSession(fail_years={fail_year})
    monkeypatch.setattr(krx_short_balance.requests, "Session", lambda: session)

    df = krx_short_balance.fetch_balance("000660", start_year=fail_year)

    assert df.attrs["failed_years"] == [fail_year]
    # 실패한 연도의 행은 없고, 성공한 연도만 반환됨 (기존 동작 유지 확인)
    assert all(row.startswith(str(ok_year)) for row in df["dt"])


def test_fetch_balance_no_failures_leaves_attrs_empty(monkeypatch):
    current_year = pd.Timestamp.today().year
    session = _FakeSession(fail_years=set())
    monkeypatch.setattr(krx_short_balance.requests, "Session", lambda: session)

    df = krx_short_balance.fetch_balance("000660", start_year=current_year)

    assert df.attrs["failed_years"] == []
