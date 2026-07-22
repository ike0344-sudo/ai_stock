"""trading-dashboard + backtest-dashboard의 HTTP 라우팅 계층 — dashboard_data.py/
backtest_results.py가 파싱한 상태를 JSON으로 직렬화해 응답하고, static/dashboard/의
프론트엔드를 서빙한다. 파일 파싱/손상 처리는 전혀 하지 않고 각 데이터 계층에
위임한다(Design §9.2 의존 규칙).

trading_loop.py/risk_manager.py를 import하지 않는다 — 완전히 분리된 프로세스로
실행된다(trading-dashboard.design.md §1.2). top35 갱신(POST /api/top35-update)이
이 서버의 유일한 쓰기 트리거이며, 그 로직은 top35_job.py 한 모듈에만 격리돼 있다
(backtest-dashboard.design.md §1.1/§9.2) — 그 외 라우트는 여전히 read-only.

정적 파일은 index.html/app.js/style.css 3개로 화이트리스트 매핑한다 — 요청 경로를
그대로 파일시스템 경로로 쓰지 않아 경로 순회(path traversal)를 원천 차단한다
(Design §7 Security Considerations). /api/results/<filename>도 동일 원칙으로
backtest_results.list_results()가 반환한 이름만 허용한다.

여러 전략을 동시에 관리하기 위해 run-trading --strategy가 state/{strategy}/ 밑에
상태를 쓰는 규칙을 그대로 신뢰한다 — 이 서버는 state_root 밑의 서브폴더를 스캔해
전략 목록으로 노출하고(GET /api/strategies), 나머지 상태 조회 라우트는 ?strategy=
쿼리 파라미터로 어느 전략의 파일을 읽을지 선택한다(생략 시 첫 번째로 발견된 전략,
전략이 하나도 없으면 strategy_1 — cli.py의 기본 전략명과 동일해 첫 실행 직후에도
바로 맞아떨어진다).
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import kill_switch_control, sell_all_job, sell_order, top35_job
from .account_status import get_account_snapshot
from .backtest_results import list_results, read_result
from .dashboard_data import (
    load_dashboard_state,
    load_order_history,
    load_pnl_history,
    load_signal_history,
    load_strategy_config,
)
from .market_snapshot import get_market_snapshot
from .strategy_catalog import describe_strategy
from .trading_value_ranking import get_ranking as get_trading_value_ranking

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "dashboard")

CONTENT_TYPES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
}

DEFAULT_STRATEGY = "strategy_1"

STATE_FILENAMES = {
    "risk_state": "risk_state.json",
    "signals": "signals.jsonl",
    "orders": "orders.jsonl",
    "pnl_history": "pnl_history.jsonl",
    "kill_switch_override": "kill_switch_override.json",
    "config": "config.json",
}


def list_strategies(state_root: str) -> list[str]:
    """state_root 밑의 서브폴더 이름을 전략 목록으로 반환한다(정렬됨). run-trading
    --strategy가 전략마다 state/{strategy}/ 폴더를 쓰기 때문에, 폴더 존재 여부로
    "실행된 적 있는 전략"을 판별할 수 있다. state_root 자체가 없으면 빈 리스트."""
    if not os.path.isdir(state_root):
        return []
    return sorted(
        name for name in os.listdir(state_root)
        if os.path.isdir(os.path.join(state_root, name))
    )


class DashboardRequestHandler(BaseHTTPRequestHandler):
    state_root = "state"
    results_dir = "results"
    kiwoom_appkey = ""
    kiwoom_secretkey = ""
    kiwoom_is_mock = True

    def log_message(self, format, *args):
        pass  # 폴링마다(수 초 간격) 기본 http.server 접근 로그가 콘솔을 채우지 않도록 억제

    def _strategy_path(self, strategy: str, key: str) -> str:
        return os.path.join(self.state_root, strategy, STATE_FILENAMES[key])

    def _selected_strategy(self, query: dict) -> str:
        requested = query.get("strategy", [None])[0]
        if requested:
            return requested
        strategies = list_strategies(self.state_root)
        return strategies[0] if strategies else DEFAULT_STRATEGY

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/market-snapshot":
            self._send_json(get_market_snapshot(self.kiwoom_appkey, self.kiwoom_secretkey, self.kiwoom_is_mock))
        elif parsed.path == "/api/account-snapshot":
            self._send_json(get_account_snapshot(self.kiwoom_appkey, self.kiwoom_secretkey, self.kiwoom_is_mock))
        elif parsed.path == "/api/sell-all-status":
            self._send_json(sell_all_job.get_status())
        elif parsed.path == "/api/trading-value-ranking":
            window = query.get("window", ["regular"])[0]
            if window not in ("regular", "extended"):
                self._send_json({"error": "window는 regular 또는 extended만 허용됩니다"}, status=400)
            else:
                self._send_json(get_trading_value_ranking(self.kiwoom_appkey, self.kiwoom_secretkey, self.kiwoom_is_mock, window))
        elif parsed.path == "/api/strategies":
            self._send_json({
                "strategies": list_strategies(self.state_root),
                "selected": self._selected_strategy(query),
            })
        elif parsed.path == "/api/state":
            strategy = self._selected_strategy(query)
            self._send_json(load_dashboard_state(self._strategy_path(strategy, "risk_state")))
        elif parsed.path == "/api/config":
            strategy = self._selected_strategy(query)
            self._send_json(load_strategy_config(self._strategy_path(strategy, "config")))
        elif parsed.path == "/api/strategy-info":
            strategy = self._selected_strategy(query)
            self._send_json(describe_strategy(strategy))
        elif parsed.path == "/api/signals":
            strategy = self._selected_strategy(query)
            limit = int(query.get("limit", ["200"])[0])
            self._send_json(load_signal_history(self._strategy_path(strategy, "signals"), limit=limit))
        elif parsed.path == "/api/results":
            self._send_json(list_results(self.results_dir))
        elif parsed.path.startswith("/api/results/"):
            filename = parsed.path[len("/api/results/"):]
            result = read_result(self.results_dir, filename)
            if result is None:
                self.send_response(404)
                self.end_headers()
            else:
                self._send_json(result)
        elif parsed.path == "/api/top35-status":
            self._send_json(top35_job.get_status())
        elif parsed.path == "/api/orders":
            strategy = self._selected_strategy(query)
            limit = int(query.get("limit", ["200"])[0])
            self._send_json(load_order_history(self._strategy_path(strategy, "orders"), limit=limit))
        elif parsed.path == "/api/pnl-history":
            strategy = self._selected_strategy(query)
            self._send_json(load_pnl_history(self._strategy_path(strategy, "pnl_history")))
        elif parsed.path == "/api/kill-switch/status":
            strategy = self._selected_strategy(query)
            self._send_json(kill_switch_control.get_override_status(self._strategy_path(strategy, "kill_switch_override")))
        elif parsed.path in ("/", "/index.html"):
            self._send_static("index.html")
        elif parsed.path == "/app.js":
            self._send_static("app.js")
        elif parsed.path == "/style.css":
            self._send_static("style.css")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/top35-update":
            started = top35_job.start_job(self.kiwoom_appkey, self.kiwoom_secretkey, self.kiwoom_is_mock)
            if started:
                self._send_json({"started": True}, status=200)
            else:
                self._send_json({"started": False, "reason": "이미 실행 중입니다"}, status=409)
        elif parsed.path == "/api/kill-switch/activate":
            strategy = self._selected_strategy(query)
            path = self._strategy_path(strategy, "kill_switch_override")
            kill_switch_control.request_kill_switch(path)
            self._send_json(kill_switch_control.get_override_status(path))
        elif parsed.path == "/api/kill-switch/clear":
            strategy = self._selected_strategy(query)
            path = self._strategy_path(strategy, "kill_switch_override")
            kill_switch_control.clear_kill_switch(path)
            self._send_json(kill_switch_control.get_override_status(path))
        elif parsed.path == "/api/sell-all":
            started = sell_all_job.start_job(self.kiwoom_appkey, self.kiwoom_secretkey, self.kiwoom_is_mock)
            if started:
                self._send_json({"started": True}, status=200)
            else:
                self._send_json({"started": False, "reason": "이미 실행 중입니다"}, status=409)
        elif parsed.path == "/api/sell":
            code = query.get("code", [""])[0]
            try:
                quantity = int(query.get("quantity", ["0"])[0])
            except ValueError:
                quantity = 0
            if not code or quantity <= 0:
                self._send_json({"ok": False, "message": "code/quantity가 올바르지 않습니다"}, status=400)
            else:
                try:
                    result = sell_order.sell_one(self.kiwoom_appkey, self.kiwoom_secretkey, self.kiwoom_is_mock, code, quantity)
                    ok = result.get("return_code") == 0
                    self._send_json({"ok": ok, "message": result.get("return_msg", "")}, status=200 if ok else 502)
                except Exception as exc:
                    self._send_json({"ok": False, "message": str(exc)}, status=502)
        else:
            self.send_response(404)
            self.end_headers()

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, filename: str) -> None:
        path = os.path.join(STATIC_DIR, filename)
        if not os.path.exists(path):
            self.send_response(404)
            self.end_headers()
            return
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES[filename])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_dashboard_server(
    state_root: str = "state",
    results_dir: str = "results",
    kiwoom_appkey: str = "",
    kiwoom_secretkey: str = "",
    kiwoom_is_mock: bool = True,
    port: int = 8765,
    host: str = "127.0.0.1",
) -> ThreadingHTTPServer:
    """서버 인스턴스만 만들어 반환(기동은 호출자 책임) — port=0으로 호출하면 OS가 빈
    포트를 배정해, 테스트에서 실제 소켓으로 스모크 테스트하기 쉽게 한다."""
    handler_cls = type(
        "BoundDashboardRequestHandler",
        (DashboardRequestHandler,),
        {
            "state_root": state_root,
            "results_dir": results_dir,
            "kiwoom_appkey": kiwoom_appkey,
            "kiwoom_secretkey": kiwoom_secretkey,
            "kiwoom_is_mock": kiwoom_is_mock,
        },
    )
    return ThreadingHTTPServer((host, port), handler_cls)


def run_dashboard_server(
    state_root: str = "state",
    results_dir: str = "results",
    kiwoom_appkey: str = "",
    kiwoom_secretkey: str = "",
    kiwoom_is_mock: bool = True,
    port: int = 8765,
) -> None:
    """localhost:port에서 대시보드 서버를 기동한다(블로킹). Ctrl+C로 중단."""
    server = build_dashboard_server(
        state_root, results_dir,
        kiwoom_appkey, kiwoom_secretkey, kiwoom_is_mock, port=port,
    )
    print(f"대시보드 서버 시작: http://127.0.0.1:{port} (Ctrl+C로 중단)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
