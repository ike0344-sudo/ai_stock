"""베이스라인 확정 알림 — 09:00은 하루에 한 번뿐이라 놓치면 그날은 끝이다.

    python -m pytest tests/backtesting/test_baseline_alert.py -q

장전 스냅샷이 얇으면(대시보드가 늦게 떴다거나 조회가 실패했다거나) 장중 순위가
조용히 부정확해진다 — 빠진 종목의 장전 물량이 통째로 "정규장 증가분"으로 잡히기
때문이다. 화면만 봐서는 알 수 없어서 알림으로 끌어낸다.
"""
from datetime import datetime

from backtesting import notifier
from backtesting import trading_value_ranking as tvr


def _drain():
    """알림은 데몬 스레드로 나간다 — 어설션 전에 끝나기를 기다린다."""
    import threading

    for t in threading.enumerate():
        if t.name == "baseline-alert":
            t.join(timeout=5)


def _capture(monkeypatch):
    sent = []
    monkeypatch.setattr(notifier, "send_telegram",
                        lambda msg, token, chat, level=notifier.INFO, **kw:
                        sent.append((msg, level)) or True)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    return sent


def _baseline(n, floor=30_000_000_000):
    return {f"{i:06d}": {"trading_value": floor + i, "volume": 1} for i in range(n)}


def test_넓게_잡히면_정상_알림(monkeypatch):
    sent = _capture(monkeypatch)
    tvr._notify_baseline_locked(_baseline(300))
    _drain()
    assert len(sent) == 1
    msg, level = sent[0]
    assert "300개" in msg and level == notifier.INFO


def test_얇게_잡히면_경고로_올린다(monkeypatch):
    sent = _capture(monkeypatch)
    tvr._notify_baseline_locked(_baseline(20))
    _drain()
    msg, level = sent[0]
    assert "얇습니다" in msg and level == notifier.CRITICAL


def test_토큰이_없으면_조용히_넘어간다(monkeypatch):
    sent = _capture(monkeypatch)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    tvr._notify_baseline_locked(_baseline(300))
    _drain()
    assert not sent


def test_알림이_터져도_순위_계산은_계속된다(monkeypatch):
    """알림은 부가 기능이다 — 여기서 예외가 새면 그날 순위가 통째로 멈춘다."""
    _capture(monkeypatch)

    def boom(*a, **kw):
        raise RuntimeError("텔레그램 down")

    monkeypatch.setattr(notifier, "send_telegram", boom)
    tvr._notify_baseline_locked(_baseline(300))     # 예외가 올라오면 실패


def test_잠글_때_한_번만_알린다(monkeypatch):
    """_ensure_baseline 은 조회마다 불린다. 매번 알리면 하루 종일 울린다."""
    sent = _capture(monkeypatch)
    monkeypatch.setattr(tvr, "_save_baseline_file", lambda *a: None)
    monkeypatch.setattr(tvr, "_load_baseline_file", lambda: None)
    tvr._baseline, tvr._baseline_date = None, None
    tvr._pre_market_snapshot = _baseline(300)
    tvr._pre_market_snapshot_date = "2026-08-20"

    now = datetime(2026, 8, 20, 9, 0, 1)
    tvr._ensure_baseline(now)
    tvr._ensure_baseline(now)
    _drain()
    assert len(sent) == 1


def test_장전_조회는_막판에만_촘촘하다(monkeypatch):
    """10초마다 300종목을 받으면 08~09시 한 시간에 1,000회 가까이 더 부른다 — 429가
    나면 정작 베이스라인을 놓친다. 09:00 에 가까울수록만 정확하면 된다."""
    from backtesting import trading_value_ranking as tvr

    calls = []
    monkeypatch.setattr(tvr, "_fetch_rows",
                        lambda _a, _s, _m, top_n, **kw: calls.append(top_n) or
                        [{"stock_code": "005930", "trading_value": 1, "volume": 1}])
    tvr._last_wide_fetch = None

    def at(h, m, s):
        return tvr.refresh_pre_market_snapshot("k", "s", False, now=datetime(2026, 8, 20, h, m, s))

    at(8, 10, 0)
    assert len(calls) == 1
    at(8, 10, 30)                      # 30초 뒤 — 아직 이르다
    assert len(calls) == 1
    at(8, 11, 5)                       # 60초 지났다
    assert len(calls) == 2

    at(8, 56, 0)                       # 막판 구간 진입
    assert len(calls) == 3
    at(8, 56, 11)                      # 10초 지나면 바로 다시
    assert len(calls) == 4
    tvr._last_wide_fetch = None


def test_넓은_조회를_좁은_조회가_되돌리지_않는다(monkeypatch):
    """폴러는 300종목을 받은 직후 화면용 20종목을 받는다. 스냅샷을 통째로 덮어쓰면
    넓혀놓은 것이 즉시 20종목으로 되돌아간다(실측 아니면 못 알아챌 조용한 회귀)."""
    from datetime import datetime

    from backtesting import trading_value_ranking as tvr

    tvr._pre_market_snapshot, tvr._pre_market_snapshot_date = {}, None
    now = datetime(2026, 8, 20, 8, 30)
    wide = [{"stock_code": f"{i:06d}", "trading_value": 1000 - i, "volume": 1} for i in range(300)]
    narrow = [{"stock_code": f"{i:06d}", "trading_value": 2000 - i, "volume": 2} for i in range(20)]

    tvr._update_pre_market_snapshot(wide, now)
    tvr._update_pre_market_snapshot(narrow, now)
    assert len(tvr._pre_market_snapshot) == 300, "좁은 조회가 스냅샷을 좁히면 안 된다"
    assert tvr._pre_market_snapshot["000000"]["trading_value"] == 2000, "겹치면 큰 값(=최신)"
    tvr._pre_market_snapshot, tvr._pre_market_snapshot_date = {}, None


def test_날짜가_바뀌면_스냅샷을_버린다(monkeypatch):
    from datetime import datetime

    from backtesting import trading_value_ranking as tvr

    tvr._pre_market_snapshot, tvr._pre_market_snapshot_date = {}, None
    tvr._update_pre_market_snapshot(
        [{"stock_code": "005930", "trading_value": 999, "volume": 1}],
        datetime(2026, 8, 19, 8, 30))
    tvr._update_pre_market_snapshot(
        [{"stock_code": "000660", "trading_value": 5, "volume": 1}],
        datetime(2026, 8, 20, 8, 30))
    assert set(tvr._pre_market_snapshot) == {"000660"}, "어제 값을 오늘 베이스라인에 섞으면 안 된다"
    tvr._pre_market_snapshot, tvr._pre_market_snapshot_date = {}, None


def test_베이스라인_조회는_스팩을_담는다(monkeypatch):
    """소피증권 순위가 스팩을 빼지 않으므로, 베이스라인에 스팩이 없으면 그 종목만
    장전 물량이 안 빠져 정규장 순위가 위로 뜬다."""
    from datetime import datetime

    from backtesting import trading_value_ranking as tvr

    seen = {}
    monkeypatch.setattr(tvr, "_fetch_rows",
                        lambda _a, _s, _m, top_n, exclude_spac=True:
                        seen.update(spac=exclude_spac) or [])
    tvr._last_wide_fetch = None
    tvr.refresh_pre_market_snapshot("k", "s", False, now=datetime(2026, 8, 20, 8, 30))
    assert seen["spac"] is False
    tvr._last_wide_fetch = None


def test_알림이_HTTP_응답을_막지_않는다(monkeypatch):
    """이 경로는 대시보드 요청 처리 중에도 불린다. 텔레그램은 타임아웃 10초에
    CRITICAL이면 3회 반복이라, 동기로 보내면 09:00 직후 첫 요청이 30초 멈춘다."""
    import time

    from backtesting import notifier
    from backtesting import trading_value_ranking as tvr

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.setattr(notifier, "send_telegram",
                        lambda *a, **kw: time.sleep(2) or True)

    began = time.monotonic()
    tvr._notify_baseline_locked(_baseline(300))
    assert time.monotonic() - began < 0.5, "발송이 끝날 때까지 붙잡고 있으면 안 된다"
    _drain()
