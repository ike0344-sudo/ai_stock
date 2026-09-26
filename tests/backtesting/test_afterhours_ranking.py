"""애프터장 순위 — 등락률 계산·정렬·기준가 없음 처리가 맞는지.

배경/근거: state/agent_reports/data-agent_20260921-2006_afterhours_top35.md
"""
import json
from datetime import date
from datetime import datetime

import pytest

from backtesting.afterhours_ranking import (
    capture_baseline,
    compute_afterhours_rows,
    in_baseline_window,
    is_afterhours,
    load_baseline,
    load_ranking,
    refresh_ranking,
    should_refresh,
)


def _row(code, name, value, volume=0, price=None):
    return {"stock_code": code, "name": name, "trading_value": value,
            "volume": volume, "current_price": price}


def _base(value, volume=0, close=None):
    return {"trading_value": value, "volume": volume, "close_price": close}


# ── 순위: 등락률이 아니라 거래대금 순이어야 한다 ──────────────────────────────

def test_순위는_등락률이_아니라_시간외_거래대금순이다():
    current = [
        _row("AAA", "작은대금큰등락", 300, price=200),   # 시간외 200, +100%
        _row("BBB", "큰대금작은등락", 5000, price=101),  # 시간외 4000, +1%
    ]
    baseline = {"AAA": _base(100, close=100), "BBB": _base(1000, close=100)}

    rows, _ = compute_afterhours_rows(current, baseline)

    assert [r["stock_code"] for r in rows] == ["BBB", "AAA"]   # 대금 큰 쪽이 1위
    assert rows[0]["rank"] == 1 and rows[1]["rank"] == 2
    assert rows[0]["after_trading_value"] == 4000
    assert rows[1]["after_trading_value"] == 200


def test_시간외분은_현재누적에서_베이스라인을_뺀_값이다():
    current = [_row("AAA", "가", 5_000, volume=700, price=110)]
    baseline = {"AAA": _base(3_000, volume=500, close=100)}

    rows, _ = compute_afterhours_rows(current, baseline)

    assert rows[0]["after_trading_value"] == 2_000
    assert rows[0]["after_volume"] == 200
    assert rows[0]["day_trading_value"] == 5_000      # 전체 누적도 같이 남긴다


# ── 등락률: KRX 15:30 종가 대비 ────────────────────────────────────────────

def test_등락률은_15시30분_종가_대비로_계산된다():
    current = [_row("AAA", "가", 5_000, price=110)]
    baseline = {"AAA": _base(1_000, close=100)}

    rows, _ = compute_afterhours_rows(current, baseline)

    assert rows[0]["change_vs_close_pct"] == 10.0
    assert rows[0]["close_price"] == 100


def test_하락도_부호가_살아있다():
    current = [_row("AAA", "가", 5_000, price=92)]
    baseline = {"AAA": _base(1_000, close=100)}

    rows, _ = compute_afterhours_rows(current, baseline)

    assert rows[0]["change_vs_close_pct"] == -8.0


# ── 기준가가 없을 때 (사용자가 명시적으로 요구한 케이스) ──────────────────────

def test_기준가가_없으면_등락률은_0이_아니라_None이다():
    """0 으로 두면 '보합'으로 보여서 진짜 보합과 구분이 안 된다 — 거짓말이 된다."""
    current = [_row("AAA", "기준가없음", 5_000, price=110)]
    baseline = {"AAA": _base(1_000, close=None)}

    rows, stats = compute_afterhours_rows(current, baseline)

    assert rows[0]["change_vs_close_pct"] is None
    assert rows[0]["after_trading_value"] == 4_000     # 대금 순위는 그대로 나온다
    assert stats["missing_close_price"] == 1


def test_기준가가_0이면_나눗셈하지_않고_None이다():
    current = [_row("AAA", "가", 5_000, price=110)]
    baseline = {"AAA": _base(1_000, close=0)}

    rows, _ = compute_afterhours_rows(current, baseline)

    assert rows[0]["change_vs_close_pct"] is None      # ZeroDivisionError 안 남


def test_현재가가_없으면_None이다():
    current = [_row("AAA", "가", 5_000, price=None)]
    baseline = {"AAA": _base(1_000, close=100)}

    rows, _ = compute_afterhours_rows(current, baseline)

    assert rows[0]["change_vs_close_pct"] is None


# ── 베이스라인 없는 종목: 0 으로 치면 안 된다 (가장 위험한 실패 모드) ─────────

def test_베이스라인_없는_종목은_0으로_치지_않고_제외한다():
    """0 으로 치면 정규장 하루치가 통째로 '시간외'로 둔갑해 1위로 튀어오른다."""
    current = [
        _row("AAA", "정상", 5_000, price=110),
        _row("ZZZ", "베이스라인없음", 900_000, price=110),   # 0 처리하면 압도적 1위가 됨
    ]
    baseline = {"AAA": _base(1_000, close=100)}

    rows, stats = compute_afterhours_rows(current, baseline)

    assert [r["stock_code"] for r in rows] == ["AAA"]      # ZZZ 는 없어야 한다
    assert stats["excluded_no_baseline"] == 1
    assert "ZZZ" in stats["excluded_no_baseline_codes"]


def test_시간외_거래가_없으면_순위에서_빠진다():
    current = [
        _row("AAA", "거래있음", 5_000, price=110),
        _row("BBB", "거래없음", 1_000, price=100),     # 베이스라인과 동일 = 시간외 0
    ]
    baseline = {"AAA": _base(1_000, close=100), "BBB": _base(1_000, close=100)}

    rows, stats = compute_afterhours_rows(current, baseline)

    assert [r["stock_code"] for r in rows] == ["AAA"]
    assert stats["excluded_no_trade"] == 1


def test_top_n_으로_잘라준다():
    current = [_row(f"C{i:03d}", f"종목{i}", 1_000 + i * 10, price=100) for i in range(50)]
    baseline = {f"C{i:03d}": _base(1_000, close=100) for i in range(50)}

    rows, stats = compute_afterhours_rows(current, baseline, top_n=35)

    assert len(rows) == 35
    assert stats["ranked"] == 49        # 시간외 0 인 C000 하나 빠짐
    assert rows[0]["after_trading_value"] > rows[-1]["after_trading_value"]


# ── 시간 창 ────────────────────────────────────────────────────────────────

def test_시간외_시간대_판정():
    assert is_afterhours(datetime(2026, 9, 21, 16, 0))        # 월요일 16:00
    assert is_afterhours(datetime(2026, 9, 21, 19, 59))
    assert not is_afterhours(datetime(2026, 9, 21, 15, 29))   # 정규장
    assert not is_afterhours(datetime(2026, 9, 21, 20, 1))    # NXT 종료 후
    assert not is_afterhours(datetime(2026, 9, 26, 16, 0))    # 토요일


def test_베이스라인_창은_종가동시호가_뒤_시간외종가_앞이다():
    """15:30 종가 동시호가(하루 최대 물량)는 들어가고, 15:40 시간외종가는 안 들어가야."""
    assert not in_baseline_window(datetime(2026, 9, 21, 15, 30))   # 아직 체결 반영 전
    assert in_baseline_window(datetime(2026, 9, 21, 15, 35))
    assert not in_baseline_window(datetime(2026, 9, 21, 15, 40))   # 시간외종가 시작


# ── 베이스라인 파일 / 상태 파일 ─────────────────────────────────────────────

def test_어제_베이스라인은_안_쓴다(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"date": "2026-09-20", "baseline": {"AAA": _base(1)}}),
                    encoding="utf-8")

    assert load_baseline(datetime(2026, 9, 21, 16, 0), str(path)) is None


def test_베이스라인_없고_직전결과도_없으면_빈표와_사유를_쓴다(tmp_path):
    """누적값을 그대로 보여주면 정규장 top35 를 시간외 순위로 오해하게 된다."""
    state = tmp_path / "state.json"
    out = refresh_ranking("k", "s", False, now=datetime(2026, 9, 21, 16, 0),
                          state_path=str(state), baseline_path=str(tmp_path / "none.json"))

    assert out["rows"] == []
    assert "베이스라인" in out["error"]
    assert json.loads(state.read_text(encoding="utf-8"))["rows"] == []


# ── "장 끝나도 종목이 계속 보여야 한다" ────────────────────────────────────

def test_베이스라인_없어도_직전_결과를_지우지_않는다(tmp_path):
    """날짜가 바뀌면 그날 베이스라인이 잡히는 15:39 까지 load_baseline 이 None 이다.
    그때마다 어제 최종 결과를 빈 표로 덮어쓰면 '장 끝나면 종목이 사라진다'."""
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "date": "2026-09-21", "as_of": "20:01:00",
        "rows": [{"rank": 1, "stock_code": "111111", "name": "어제1위",
                  "after_trading_value": 92_000_000_000}],
        "stats": {"ranked": 1},
    }), encoding="utf-8")

    # 다음 날 15:31 — 아직 오늘 베이스라인이 없는 시점
    out = refresh_ranking("k", "s", False, now=datetime(2026, 9, 22, 15, 31),
                          state_path=str(state), baseline_path=str(tmp_path / "none.json"))

    assert len(out["rows"]) == 1                       # 지워지지 않았다
    assert out["rows"][0]["stock_code"] == "111111"
    assert out["date"] == "2026-09-21"                 # 언제 자료인지 보존
    assert out["baseline_missing"] is True
    assert json.loads(state.read_text(encoding="utf-8"))["rows"]      # 파일에도 남아있다


def test_장_끝난_뒤에도_그날_결과가_최종으로_표시된다(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "date": "2026-09-21", "as_of": "20:01:00",
        "rows": [{"rank": 1, "stock_code": "111111", "name": "밤에터짐"}],
    }), encoding="utf-8")

    got = load_ranking(str(state), now=datetime(2026, 9, 21, 22, 0))   # 장 끝난 뒤

    assert len(got["rows"]) == 1          # 종목이 계속 보인다
    assert got["active"] is False         # 갱신은 멈춤
    assert got["session_closed"] is True  # "최종"으로 표시할 수 있다
    assert "stale_date" not in got        # 오늘 자료라 '지난 자료' 경고는 아니다


def test_다음날이면_최종이_아니라_지난자료로_표시된다(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "date": "2026-09-21", "as_of": "20:01:00",
        "rows": [{"rank": 1, "stock_code": "111111"}],
    }), encoding="utf-8")

    got = load_ranking(str(state), now=datetime(2026, 9, 22, 10, 0))

    assert len(got["rows"]) == 1           # 그래도 계속 보여준다
    assert got["stale_date"] == "2026-09-21"
    assert got["session_closed"] is False  # 오늘 최종이 아니다 — 어제 자료다


def test_20시_직후_유예동안_한번_더_받아_최종치를_확정한다():
    """20:00 에 딱 멈추면 저장된 값이 19:59 분이라 마감 직전 체결이 빠진다."""
    assert should_refresh(datetime(2026, 9, 21, 19, 59))
    assert should_refresh(datetime(2026, 9, 21, 20, 3))     # 유예 구간
    assert not should_refresh(datetime(2026, 9, 21, 20, 6))  # 유예 종료
    assert not should_refresh(datetime(2026, 9, 21, 15, 29))
    assert not should_refresh(datetime(2026, 9, 26, 16, 0))  # 토요일

    # 유예 중이라도 화면의 '갱신 중' 표시는 꺼져 있어야 한다
    assert not is_afterhours(datetime(2026, 9, 21, 20, 3))


def test_베이스라인_창_밖에서는_안_찍는다(tmp_path):
    path = tmp_path / "baseline.json"
    got = capture_baseline("k", "s", False, now=datetime(2026, 9, 21, 16, 0), path=str(path))

    assert got["captured"] is False
    assert not path.exists()          # API 도 안 치고 파일도 안 만든다


def test_대시보드는_파일만_읽고_없으면_사유를_준다(tmp_path):
    got = load_ranking(str(tmp_path / "없는파일.json"), now=datetime(2026, 9, 21, 16, 0))

    assert got["rows"] == []
    assert got["error"]
    assert got["active"] is True      # 지금은 시간외 시간대


# ── 지연/비용 (2026-09-22 최적화) ──────────────────────────────────────────

def test_클라이언트를_재사용해_폴링마다_토큰을_새로_안_받는다(monkeypatch):
    """새로 만들면 token=None 이라 매번 발급받는다(실측 0.22초 + 요청 1회 낭비).
    자기제한(1.1초) 상태가 폴링 사이에도 이어지는 효과가 더 크다."""
    from backtesting import afterhours_ranking as ah

    made = []

    class _FakeClient:
        def __init__(self, *a, **k):
            made.append(1)

    monkeypatch.setattr(ah, "KiwoomClient", _FakeClient)
    monkeypatch.setattr(ah, "_client", None)
    monkeypatch.setattr(ah, "_client_key", None)

    a = ah._get_client("k", "s", False)
    b = ah._get_client("k", "s", False)

    assert a is b                 # 같은 인스턴스 = 토큰도 그대로
    assert len(made) == 1         # 한 번만 생성됐다


def test_키가_바뀌면_클라이언트를_새로_만든다(monkeypatch):
    from backtesting import afterhours_ranking as ah

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(ah, "KiwoomClient", _FakeClient)
    monkeypatch.setattr(ah, "_client", None)
    monkeypatch.setattr(ah, "_client_key", None)

    a = ah._get_client("k1", "s", False)
    b = ah._get_client("k2", "s", False)

    assert a is not b


def test_라이브는_순환수집_풀을_쓴다(monkeypatch, tmp_path):
    """통짜 5페이지(4.5초) 대신 1페이지+순환 1페이지(1.2초)로 받는다."""
    import pandas as pd

    from backtesting import afterhours_ranking as ah

    seen = []

    def fake_top(client, top_n, max_pages, exchange, exclude_spac, page):
        seen.append({"page": page, "exchange": exchange})
        return pd.DataFrame([{"stock_code": "111111", "name": "가", "trading_value": 5_000,
                              "volume": 10, "current_price": 110}])

    monkeypatch.setattr(ah, "top_by_trading_value", fake_top)
    monkeypatch.setattr(ah, "_get_client", lambda *a: object())
    monkeypatch.setattr(ah, "_pool", {})
    monkeypatch.setattr(ah, "_pool_date", None)
    monkeypatch.setattr(ah, "_next_deep_page", 2)

    bp = tmp_path / "b.json"
    bp.write_text(json.dumps({"date": "2026-09-22", "baseline": {
        "111111": {"trading_value": 1_000, "volume": 5, "close_price": 100}}}), encoding="utf-8")

    out = ah.refresh_ranking("k", "s", False, now=datetime(2026, 9, 22, 16, 0),
                             state_path=str(tmp_path / "s.json"), baseline_path=str(bp))

    assert [s["page"] for s in seen] == [1, 2]        # 한 사이클에 2콜뿐
    assert all(s["exchange"] == "3" for s in seen)    # 시간외는 KRX+NXT 둘 다
    assert out["stats"]["oldest_row_age_sec"] is not None   # 신선도를 화면에 넘긴다


def test_하위권이_후보군_문턱보다_작으면_미확정으로_표시한다():
    """장 초반엔 시간외 물량이 작아 꼴찌가 후보군 밖 종목에 밀릴 수 있다 —
    '상위 35'라고 단정하면 조용히 틀린 표가 된다."""
    # 후보군 최하위 누적 = 1,000. 시간외 35위값이 그보다 작으면 미확정.
    current = [_row("AAA", "큼", 5_000, price=110), _row("BBB", "작음", 1_000, price=110)]
    baseline = {"AAA": _base(1_000, close=100), "BBB": _base(900, close=100)}

    rows, stats = compute_afterhours_rows(current, baseline)

    assert stats["pool_floor"] == 1_000
    assert rows[-1]["after_trading_value"] == 100      # BBB 시간외 100 < 문턱 1,000
    assert stats["tail_guaranteed"] is False


def test_하위권이_문턱_이상이면_확정으로_표시한다():
    # 시간외 <= 누적 이라 "확정"은 후보군 최하위 종목이 거의 전부 시간외일 때 성립한다:
    # BBB 는 누적 1,000 이 전부 시간외(베이스라인 0), AAA 는 누적 5,000 중 1,000 만 시간외.
    current = [_row("AAA", "가", 5_000, price=110), _row("BBB", "나", 1_000, price=110)]
    baseline = {"AAA": _base(4_000, close=100), "BBB": _base(0, close=100)}

    rows, stats = compute_afterhours_rows(current, baseline)

    assert stats["pool_floor"] == 1_000
    assert all(r["after_trading_value"] >= stats["pool_floor"] for r in rows)
    assert stats["tail_guaranteed"] is True


# ── 스팩 포함 (2026-09-22) ────────────────────────────────────────────────

def test_스팩을_후보에_포함한다(monkeypatch, tmp_path):
    """합병 공시가 시간외에 터지는 종목군이라 보고 싶다는 요청."""
    import pandas as pd

    from backtesting import afterhours_ranking as ah

    seen = {}

    def fake_top(client, top_n, max_pages, exchange, exclude_spac, page=None):
        seen["exclude_spac"] = exclude_spac
        return pd.DataFrame([{"stock_code": "0200G0", "name": "한국제17호스팩",
                              "trading_value": 5_000, "volume": 10, "current_price": 110}])

    monkeypatch.setattr(ah, "top_by_trading_value", fake_top)
    monkeypatch.setattr(ah, "_get_client", lambda *a: object())

    rows = ah._fetch("k", "s", False, 500, "3", max_pages=5)

    assert seen["exclude_spac"] is False           # 스팩을 안 걸러낸다
    assert rows[0]["name"] == "한국제17호스팩"


def test_베이스라인과_라이브가_같은_기준을_쓴다(monkeypatch, tmp_path):
    """라이브만 스팩을 켜면 그 스팩은 15:35 베이스라인이 없어 시간외분을 못 구한다.
    둘 다 _fetch 를 지나므로 기준이 갈릴 수 없다는 걸 고정한다."""
    import pandas as pd

    from backtesting import afterhours_ranking as ah

    calls = []

    def fake_top(client, top_n, max_pages, exchange, exclude_spac, page=None):
        calls.append({"exchange": exchange, "exclude_spac": exclude_spac})
        return pd.DataFrame([{"stock_code": "0200G0", "name": "한국제17호스팩",
                              "trading_value": 5_000, "volume": 10, "current_price": 110}])

    monkeypatch.setattr(ah, "top_by_trading_value", fake_top)
    monkeypatch.setattr(ah, "_get_client", lambda *a: object())

    bp, sp = str(tmp_path / "b.json"), str(tmp_path / "s.json")
    ah.capture_baseline("k", "s", False, now=datetime(2026, 9, 23, 15, 35), path=bp)
    ah.refresh_ranking("k", "s", False, now=datetime(2026, 9, 23, 16, 0),
                       state_path=sp, baseline_path=bp)

    assert len(calls) == 4                                    # 베이스라인 2(통합+KRX) + 라이브 2(순환)
    assert all(c["exclude_spac"] is False for c in calls)     # 셋 다 같은 기준
    # 그 결과 스팩이 베이스라인에도 있어서 순위에서 안 빠진다
    got = json.loads(io_read(sp))
    assert got["stats"]["excluded_no_baseline"] == 0


def io_read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_ETF_ETN은_여전히_제외된다():
    """스팩만 넣으라는 요청이다 — ETF/ETN 까지 섞이면 안 된다."""
    from backtesting.screener import _is_excluded_instrument

    assert _is_excluded_instrument("한국제17호스팩", exclude_spac=False) is False   # 스팩 통과
    assert _is_excluded_instrument("KODEX 200", exclude_spac=False) is True        # ETF 제외
    assert _is_excluded_instrument("신한 레버리지 WTI원유 ETN", exclude_spac=False) is True
    assert _is_excluded_instrument("신한지주", exclude_spac=False) is False         # 개별종목은 통과


def test_주기와_깊이는_예산_안에_있다():
    """429 가 나면 갱신이 멈춰 화면이 얼어붙는다 — 느린 것보다 나쁘다.
    2콜/사이클 기준으로 한도(초당 1회)를 넘지 않는지 산수로 고정한다."""
    from backtesting.afterhours_ranking import POLL_SECONDS

    calls_per_cycle = 2                      # 1페이지 + 순환 깊은 페이지 1개
    fetch_seconds = 0.09 + 1.1               # 첫 요청은 대기 없음, 두 번째가 자기제한 1.1초
    effective = POLL_SECONDS + fetch_seconds
    my_rate = calls_per_cycle / effective
    other_poller = 0.2                       # 같은 TR 을 쓰는 trading_value_ranking

    assert my_rate + other_poller <= 0.7, "한도 대비 마진이 30% 미만이면 너무 조인 것"
    assert effective <= 9.0, "프론트 1초를 더해도 체감 10초 이하여야 한다"


def test_순환수집은_1페이지를_매번_받고_깊은_페이지를_돌아가며_받는다(monkeypatch):
    """시간외 top35 의 91% 가 누적 1페이지 안에 있다는 실측에 맞춘 구조."""
    import pandas as pd

    from backtesting import afterhours_ranking as ah

    asked = []

    def fake_top(client, top_n, max_pages, exchange, exclude_spac, page):
        asked.append(page)
        return pd.DataFrame([{"stock_code": f"p{page}", "name": f"종목{page}",
                              "trading_value": 100, "volume": 1, "current_price": 10}])

    monkeypatch.setattr(ah, "top_by_trading_value", fake_top)
    monkeypatch.setattr(ah, "_get_client", lambda *a: object())
    monkeypatch.setattr(ah, "_pool", {})
    monkeypatch.setattr(ah, "_pool_date", None)
    monkeypatch.setattr(ah, "_next_deep_page", 2)

    now = datetime(2026, 9, 22, 16, 0)
    for _ in range(3):
        ah._fetch_live_pool("k", "s", False, now)

    assert asked == [1, 2, 1, 3, 1, 4]        # 1페이지는 매번, 깊은 쪽은 순환
    # 풀은 누적된다 — 이번 사이클에 안 받은 페이지의 종목도 남아 순위에 계속 참여한다
    assert {r["stock_code"] for r in ah._fetch_live_pool("k", "s", False, now)} >= {
        "p1", "p2", "p3", "p4"}


def test_순환_깊이는_기존_통짜보다_깊다():
    """실측에서 시간외 top35 의 최대 누적순위가 660위였는데 기존 5페이지(raw 500)는
    그걸 놓치고 있었다. 순환은 raw 700 까지 훑는다."""
    from backtesting.afterhours_ranking import LIVE_MAX_PAGES, LIVE_PAGES

    assert LIVE_PAGES > LIVE_MAX_PAGES
    assert LIVE_PAGES * 100 >= 700


def test_날짜가_바뀌면_풀을_비운다(monkeypatch):
    """누적 거래대금은 날마다 0 부터 다시 쌓인다 — 어제 값이 남으면 시간외분이 엉킨다."""
    import pandas as pd

    from backtesting import afterhours_ranking as ah

    monkeypatch.setattr(ah, "top_by_trading_value",
                        lambda client, top_n, max_pages, exchange, exclude_spac, page:
                        pd.DataFrame([{"stock_code": f"p{page}", "name": "가",
                                       "trading_value": 100, "volume": 1, "current_price": 10}]))
    monkeypatch.setattr(ah, "_get_client", lambda *a: object())
    monkeypatch.setattr(ah, "_pool", {})
    monkeypatch.setattr(ah, "_pool_date", None)
    monkeypatch.setattr(ah, "_next_deep_page", 2)

    ah._fetch_live_pool("k", "s", False, datetime(2026, 9, 22, 16, 0))
    before = len(ah._pool)
    pool = ah._fetch_live_pool("k", "s", False, datetime(2026, 9, 23, 16, 0))

    assert before == 2
    assert len(pool) == 2        # 어제 것이 누적되지 않고 새로 시작


def test_백필은_통합_AL_코드로_받고_기준가는_KRX로_받는다(tmp_path, monkeypatch):
    """거래소는 stex_tp 가 아니라 **코드 접미사**로 갈린다(2026-09-21 실측).
    _AL 을 안 붙이면 KRX 만 와서 시간외가 통째로 과소평가된다."""
    import pandas as pd

    from backtesting import afterhours_ranking as ah

    asked = []

    def fake_minute_bars(client, code, day):
        asked.append(code)
        idx = pd.to_datetime([f"{day} 15:20", f"{day} 15:30", f"{day} 16:00", f"{day} 19:00"])
        if code.endswith("_AL"):        # 통합 — 시간외가 크다
            return pd.DataFrame({"close": [100, 100, 110, 120], "volume": [10, 10, 100, 100]}, index=idx)
        # 접미사 없음 = KRX — 기준가(15:30 종가)만 여기서 가져온다
        return pd.DataFrame({"close": [100, 105, 106, 107], "volume": [10, 10, 1, 1]}, index=idx)

    monkeypatch.setattr(ah, "_minute_bars", fake_minute_bars)
    monkeypatch.setattr(ah, "KiwoomClient", lambda *a, **k: object())
    monkeypatch.setattr(ah, "top_by_trading_value",
                        lambda client, top_n, max_pages, exchange, exclude_spac, page=None:
                        pd.DataFrame([{"stock_code": "111111", "name": "가", "trading_value": 1}]))

    out = ah.backfill_from_minutes("k", "s", False, date(2026, 9, 21),
                                   top_n=5, candidates=1, state_path=str(tmp_path / "s.json"))

    assert "111111_AL" in asked          # 시간외 대금은 통합으로 받았다
    assert "111111" in asked             # 기준가는 KRX 로 받았다
    row = out["rows"][0]
    # 시간외 = 16:00(110*100) + 19:00(120*100) = 23,000. 15:30 이하 봉은 빠진다.
    assert row["after_trading_value"] == 23_000
    assert row["close_price"] == 105     # KRX 15:30 봉 종가
    assert row["change_vs_close_pct"] == pytest.approx((120 - 105) / 105 * 100)
    assert out["backfilled"] is True


def test_어제_상태파일이면_그_사실을_표시한다(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"date": "2026-09-20", "as_of": "19:00:00", "rows": []}),
                     encoding="utf-8")

    got = load_ranking(str(state), now=datetime(2026, 9, 21, 16, 0))

    assert got["stale_date"] == "2026-09-20"
