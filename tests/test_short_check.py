"""collect()가 KRX 순보유잔고 수집 실패/부분실패를 반환값(.attrs)에 남기는지 확인.

배경: state/agent_reports/data-agent_20260910-1701_tradingagents_salvage.md §3-2 —
전체 실패 시 print만 하고 구 캐시로 조용히 대체해, "오늘 데이터가 없다"와 "캐시가
갱신 안 됐다"가 최종 산출물(d)에서 구분 불가능했다.
"""
import pandas as pd

import short_check


class _FakeClient:
    def request_tr(self, api, body, path, cont_yn="N", next_key=""):
        self.last_cont_yn = "N"
        self.last_next_key = ""
        if api == "ka10014":
            return {"shrts_trnsn": [
                {"dt": "20260101", "close_pric": "+50000", "trde_qty": "1000",
                 "shrts_qty": "100", "trde_wght": "10.0"},
            ]}
        if api == "ka20068":
            return {"dbrt_trde_trnsn": [{"dt": "20260101", "dbrt_trde_rpy": "10", "rmnd": "500"}]}
        if api == "ka10059":
            return {"stk_invsr_orgn": [
                {"dt": "20260101", "ind_invsr": "1", "frgnr_invsr": "2", "orgn": "3", "etc_corp": "4"},
            ]}
        raise AssertionError(f"unexpected api {api}")


def _fake_client():
    c = _FakeClient()
    c.last_cont_yn = "N"
    c.last_next_key = ""
    return c


def test_collect_marks_note_when_fetch_balance_fails_and_stale_cache_used(monkeypatch, tmp_path):
    monkeypatch.setattr(short_check, "CACHE", str(tmp_path))
    # 오래된 캐시가 이미 있는 상태를 흉내낸다.
    stale = tmp_path / "000660_balance.csv"
    stale.write_text("dt,bal_qty,bal_amt,list_shrs,bal_rto\n20250101,1000,10000,100000,1.0\n")

    def _boom(code, start_year):
        raise RuntimeError("network down")

    monkeypatch.setattr(short_check, "fetch_balance", _boom)

    result = short_check.collect(_fake_client(), "000660", "20260101")

    note = result.attrs.get("순보유잔고_note")
    assert note is not None
    assert "갱신 실패" in note
    assert "20250101" in note  # 캐시가 어디까지 stale한지 드러나야 한다
    # stale 캐시라도 병합은 되어야 한다(기존 동작 유지).
    assert "순보유잔고" in result.columns


def test_collect_marks_note_when_fetch_balance_fails_with_no_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(short_check, "CACHE", str(tmp_path))
    monkeypatch.setattr(short_check, "fetch_balance", lambda code, start_year: (_ for _ in ()).throw(RuntimeError("boom")))

    result = short_check.collect(_fake_client(), "000660", "20260101")

    note = result.attrs.get("순보유잔고_note")
    assert note is not None
    assert "캐시도 없" in note


def test_collect_marks_note_when_fetch_balance_partially_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(short_check, "CACHE", str(tmp_path))

    def _partial(code, start_year):
        df = pd.DataFrame({"dt": ["20260101"], "bal_qty": [1000], "bal_amt": [10000],
                            "list_shrs": [100000], "bal_rto": [1.0]})
        df.attrs["failed_years"] = [2024]
        return df

    monkeypatch.setattr(short_check, "fetch_balance", _partial)

    result = short_check.collect(_fake_client(), "000660", "20260101")

    note = result.attrs.get("순보유잔고_note")
    assert note is not None
    assert "2024" in note


def test_collect_no_note_when_fully_successful(monkeypatch, tmp_path):
    monkeypatch.setattr(short_check, "CACHE", str(tmp_path))

    def _clean(code, start_year):
        df = pd.DataFrame({"dt": ["20260101"], "bal_qty": [1000], "bal_amt": [10000],
                            "list_shrs": [100000], "bal_rto": [1.0]})
        df.attrs["failed_years"] = []
        return df

    monkeypatch.setattr(short_check, "fetch_balance", _clean)

    result = short_check.collect(_fake_client(), "000660", "20260101")

    assert result.attrs.get("순보유잔고_note") is None


def test_show_prints_note_when_present(capsys):
    d = pd.DataFrame({
        "dt": ["20260101"], "종가": [50000.0], "거래량": [1000.0], "공매도량": [100.0], "비중%": [10.0],
        "대차상환": [10.0], "대차잔고": [500.0], "개인": [1.0], "외국인": [2.0], "기관": [3.0],
        "기타법인": [4.0], "매도압력": [1.0], "흡수율": [1.0], "최대매도주체": ["개인"],
    })
    d.attrs["순보유잔고_note"] = "테스트 알림 메시지"

    short_check.show("000660", d)

    out = capsys.readouterr().out
    assert "테스트 알림 메시지" in out
