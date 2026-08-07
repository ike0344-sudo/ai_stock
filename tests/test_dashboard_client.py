import sys
import types
import urllib.request

# webview는 GUI 바인딩이 있어야 임포트되므로, 테스트 환경에서는 더미 모듈로 대체한다.
sys.modules.setdefault("webview", types.SimpleNamespace(create_window=lambda *a, **k: None, start=lambda: None))

import dashboard_client


def test_load_url_returns_none_when_no_config(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard_client, "CONFIG_PATH", tmp_path / "dashboard_client_config.json")
    assert dashboard_client._load_url() is None


def test_save_then_load_url_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard_client, "CONFIG_PATH", tmp_path / "dashboard_client_config.json")
    dashboard_client._save_url("http://100.64.0.1:8765/ranking.html")
    assert dashboard_client._load_url() == "http://100.64.0.1:8765/ranking.html"


def test_local_server_serves_ranking_page_and_read_only_api(monkeypatch):
    monkeypatch.setattr(
        dashboard_client, "get_ranking",
        lambda appkey, secretkey, is_mock, window: {"rows": [], "as_of": None, "active": True},
    )
    # 실제 키움 API 접속(백그라운드 폴러/프리플라이트 토큰 발급)은 이 테스트에서 원치 않음
    monkeypatch.setattr(dashboard_client, "start_background_poller", lambda *a, **k: None)
    monkeypatch.setattr(dashboard_client, "_preflight_error", lambda *a, **k: None)
    url = dashboard_client._start_local_server("key", "secret", True)

    with urllib.request.urlopen(url) as res:
        assert res.status == 200
        assert b"[0184]" in res.read()

    with urllib.request.urlopen(url.replace("ranking.html", "api/trading-value-ranking?window=extended")) as res:
        assert res.status == 200

    # 주문/계좌 관련 라우트는 아예 존재하지 않는다 (읽기 전용 보장)
    try:
        urllib.request.urlopen(url.replace("ranking.html", "api/sell-all"))
        assert False, "sell 라우트가 있으면 안 됨"
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_start_local_server_appends_preflight_error_to_url(monkeypatch):
    monkeypatch.setattr(dashboard_client, "start_background_poller", lambda *a, **k: None)
    monkeypatch.setattr(dashboard_client, "_preflight_error", lambda *a, **k: "키움 API 연결 실패: 테스트")
    url = dashboard_client._start_local_server("key", "secret", True)
    assert "error=" in url


def test_warn_if_no_webview2_shows_messagebox_when_mshtml(monkeypatch):
    fake_platforms = types.ModuleType("webview.platforms")
    fake_winforms = types.ModuleType("webview.platforms.winforms")
    fake_winforms.renderer = "mshtml"
    monkeypatch.setitem(sys.modules, "webview.platforms", fake_platforms)
    monkeypatch.setitem(sys.modules, "webview.platforms.winforms", fake_winforms)
    calls = []
    monkeypatch.setattr(dashboard_client.ctypes.windll.user32, "MessageBoxW", lambda *a: calls.append(a))

    dashboard_client._warn_if_no_webview2()

    assert len(calls) == 1


def test_warn_if_no_webview2_stays_silent_when_edgechromium(monkeypatch):
    fake_platforms = types.ModuleType("webview.platforms")
    fake_winforms = types.ModuleType("webview.platforms.winforms")
    fake_winforms.renderer = "edgechromium"
    monkeypatch.setitem(sys.modules, "webview.platforms", fake_platforms)
    monkeypatch.setitem(sys.modules, "webview.platforms.winforms", fake_winforms)
    calls = []
    monkeypatch.setattr(dashboard_client.ctypes.windll.user32, "MessageBoxW", lambda *a: calls.append(a))

    dashboard_client._warn_if_no_webview2()

    assert calls == []
