"""trading-dashboard + backtest-dashboard의 HTTP 라우팅 계층 — dashboard_data.py/
backtest_results.py가 파싱한 상태를 JSON으로 직렬화해 응답하고, static/dashboard/의
프론트엔드를 서빙한다. 파일 파싱/손상 처리는 전혀 하지 않고 각 데이터 계층에
위임한다(Design §9.2 의존 규칙).

trading_loop.py를 import하지 않는다 — 완전히 분리된 프로세스로 실행된다
(trading-dashboard.design.md §1.2). top35 갱신(POST /api/top35-update)이 이 서버의
유일한 쓰기 트리거이며, 그 로직은 top35_job.py 한 모듈에만 격리돼 있다
(backtest-dashboard.design.md §1.1/§9.2) — 그 외 라우트는 여전히 read-only.

예외적으로 risk_manager.py는 check_order()만 읽기 전용으로 호출한다 — /api/sell,
/api/sell-all이 실제 매도 주문을 내기 전에 risk_manager의 승인을 거치게 해, 리스크
심사를 대시보드가 우회하지 않도록 한다(감사 지적사항). risk_state는 조회만 하고
쓰지 않으며, /api/kill-switch/*는 사람이 누르는 긴급 수동 오버라이드라 이 승인
경로에서 의도적으로 제외한다.

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
import math
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import kill_switch_control, risk_manager, sell_all_job, sell_order, stop_control, top35_job
from .account_status import get_account_snapshot
from .backtest_results import list_results, read_result
from .dashboard_data import (
    load_all_signal_history,
    load_dashboard_state,
    load_order_history,
    load_pnl_history,
    load_strategy_config,
)
from .dashboard_monitor import DEFAULT_STATE_DIR as DASHBOARD_MONITOR_STATE_DIR
from .heartbeat import read_heartbeat_age_seconds
from .market_snapshot import get_market_snapshot
from .nasdaq_drop_monitor import DEFAULT_STATE_DIR as NASDAQ_DROP_MONITOR_STATE_DIR
from .orderbook_collector import is_extended_market_open
from .strategy_catalog import describe_strategy
from .trading_value_ranking import get_ranking as get_trading_value_ranking
from .trading_value_ranking import start_background_poller as start_ranking_background_poller

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static", "dashboard")

# run-trading/monitor-signals의 --strategy 실행 파라미터 플래그 중, config.json
# 스냅샷(cli.py의 _write_strategy_config/_write_scalp_config)에 실제로 남는 키만
# 매핑한다 — "시작" 버튼이 직전 실행과 동일한 옵션(예: 전략1의 --interval-seconds 1)으로
# 재시작하기 위함. 전략마다 config.json에 있는 키가 다르므로(strategy_3은 top_n/
# interval_seconds만 있음) 없는 키는 그냥 건너뛴다 — 상위 커맨드(run-trading 또는
# monitor-signals)가 애초에 받지 않는 플래그가 잘못 섞이는 일도 이 방식으로 막힌다.
CONFIG_TO_CLI_FLAG = {
    "top_n": "--top-n",
    "proba_threshold": "--proba-threshold",
    "max_concurrent_positions": "--max-concurrent-positions",
    "total_capital_krw": "--total-capital",
    "interval_seconds": "--interval-seconds",
    "model_path": "--model-path",
}


def spawn_detached(command: list[str], cwd: str, log_file) -> subprocess.Popen:
    """대시보드가 재시작/종료돼도 방금 띄운 전략 프로세스가 같이 죽지 않도록, 가능하면
    부모의 프로세스 그룹/잡 오브젝트에서 분리해 띄운다(실측 사고: 대시보드 프로세스를
    재시작했더니 그 "시작" 버튼으로 띄웠던 전략1·3 실계좌 프로세스가 같이 종료됐다 —
    상위에서 프로세스 트리 전체를 정리하는 방식으로 관리되고 있었던 것으로 보임).

    CREATE_BREAKAWAY_FROM_JOB은 상위가 잡 오브젝트로 관리 중이고 그 잡이 breakaway를
    허용하면 분리에 성공하지만, 허용하지 않으면 프로세스 생성 자체가 예외로 실패한다
    (조용히 무시되지 않음) — 그래서 먼저 시도하고, 실패하면 그 플래그 없이(그래도
    CREATE_NEW_PROCESS_GROUP은 유지해 최소한 Ctrl+C 전파는 막고서) 다시 시도한다.
    다만 이건 잡 오브젝트 기반 관리에만 통하는 방어책이고, 상위가 프로세스 트리(부모
    PID) 기준으로 통째로 정리하는 방식이면 이 플래그로도 못 막는다 — 그런 경우
    대비책은 코드가 아니라 운용 규칙(REAL_TRADING_SAFETY.md 등에 안내: 실계좌
    프로세스는 대시보드 "시작" 버튼 대신 별도 터미널에서 CLI로 직접 띄우면 대시보드
    재시작의 영향을 받지 않는다)."""
    if os.name == "nt":
        try:
            return subprocess.Popen(
                command, cwd=cwd, stdout=log_file, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_BREAKAWAY_FROM_JOB,
            )
        except OSError:
            return subprocess.Popen(
                command, cwd=cwd, stdout=log_file, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
    return subprocess.Popen(
        command, cwd=cwd, stdout=log_file, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


MONITOR_ONLY_STRATEGIES = {"strategy_3", "strategy_4"}  # 주문 없이 관찰만 하는 전략 — monitor-signals로 실행


def build_strategy_command(strategy: str, config: dict) -> list[str]:
    """대시보드 "시작" 버튼이 실행할 커맨드를 조립한다. strategy_3/4만 monitor-signals
    (주문 없는 감시 전용)로 실행하고 나머지는 run-trading — cli.py 자체가 이미 이 둘을
    strategy_1과 다른 실행 경로로 분기하는 것과 같은 특별 취급이다."""
    subcommand = "monitor-signals" if strategy in MONITOR_ONLY_STRATEGIES else "run-trading"
    command = [sys.executable, "-m", "backtesting.cli", subcommand, "--strategy", strategy]
    for key, flag in CONFIG_TO_CLI_FLAG.items():
        if key in config:
            command += [flag, str(config[key])]
    return command

CONTENT_TYPES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
    "ranking.html": "text/html; charset=utf-8",
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


NON_STRATEGY_STATE_FOLDERS = {
    os.path.basename(NASDAQ_DROP_MONITOR_STATE_DIR),
    os.path.basename(DASHBOARD_MONITOR_STATE_DIR),
}


def list_strategies(state_root: str) -> list[str]:
    """state_root 밑의 서브폴더 이름을 전략 목록으로 반환한다(정렬됨). run-trading
    --strategy가 전략마다 state/{strategy}/ 폴더를 쓰기 때문에, 폴더 존재 여부로
    "실행된 적 있는 전략"을 판별할 수 있다. state_root 자체가 없으면 빈 리스트.

    NON_STRATEGY_STATE_FOLDERS에 있는 폴더(nasdaq_drop_monitor 등)는 같은 state/
    루트를 쓰지만 strategy_catalog에 등록된 매매 전략이 아니라 별도 유틸리티라
    전략 선택 드롭다운/상태 배지에서 제외한다(자기 전용 상태 API로 따로 노출)."""
    if not os.path.isdir(state_root):
        return []
    return sorted(
        name for name in os.listdir(state_root)
        if os.path.isdir(os.path.join(state_root, name)) and name not in NON_STRATEGY_STATE_FOLDERS
    )


def _json_safe(value):
    """NaN/Infinity를 None으로 바꿔 표준 JSON으로만 직렬화되게 한다. json.dumps 기본값은
    NaN을 리터럴 NaN으로 그대로 내보내는데(파이썬 확장, 표준 JSON 아님) 브라우저
    JSON.parse는 이를 파싱하지 못해 그 요청을 통째로 실패시킨다 — pandas DataFrame이
    None 값을 가진 float 컬럼을 NaN으로 바꿔버리는 경로(trading_value_ranking.py의
    prev_day_volume=0 종목 등)에서 실측으로 발생했다. 특정 엔드포인트만 고치는 대신
    모든 응답이 거치는 이 지점에서 한 번에 막아, 앞으로 비슷한 경로가 추가돼도 같은
    문제가 재발하지 않게 한다."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(v) for key, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


MIN_STALE_THRESHOLD_SECONDS = 60.0
STALE_THRESHOLD_MULTIPLIER = 3


def is_strategy_running(state_root: str, strategy: str) -> bool:
    """폴더가 "실행된 적 있음"을 의미하는 list_strategies와 달리, 이건 "지금도 살아
    있는지"를 heartbeat.json의 나이로 판단한다(dashboard_server는 별도 프로세스라 PID를
    모름). 임계값은 이 전략의 config.json에 적힌 interval_seconds(폴링 주기)의 3배 —
    한 사이클이 조금 늦어져도 오탐(false "중지됨")이 안 나게 여유를 둔다. config가 없거나
    interval_seconds를 모르면 60초를 기본 임계값으로 쓴다.

    stop_requested.json이 있으면 하트비트 나이와 무관하게 무조건 False — 그렇지 않으면
    "중지" 버튼을 눌러 루프가 실제로 막 종료됐어도 마지막 하트비트가 아직 임계값을 안
    넘긴 동안(최대 90초 가까이) "실행중"으로 잘못 보이는 문제가 있었다(실측). 정지
    요청 파일은 다음 "시작"에서만 지워지므로(clear_stop_flag) 그 전까지는 계속 "중지됨"으로
    남는다."""
    if stop_control.is_stop_requested(os.path.join(state_root, strategy, stop_control.DEFAULT_STOP_FLAG_FILENAME)):
        return False
    config = load_strategy_config(os.path.join(state_root, strategy, STATE_FILENAMES["config"]))
    interval_seconds = config.get("interval_seconds")
    threshold = max(MIN_STALE_THRESHOLD_SECONDS, float(interval_seconds) * STALE_THRESHOLD_MULTIPLIER) if interval_seconds else MIN_STALE_THRESHOLD_SECONDS
    age = read_heartbeat_age_seconds(os.path.join(state_root, strategy))
    return age is not None and age < threshold


def start_strategy(state_root: str, strategy: str) -> bool:
    """전략 실전매매 루프를 새로 띄운다. 이미 실행 중이면 아무 것도 안 하고 False —
    POST /api/strategy/start와 아래 일별 자동시작 스케줄러가 이 함수 하나를 공유해
    "중복 실행 방지" 로직이 한 곳에만 있게 한다."""
    if is_strategy_running(state_root, strategy):
        return False
    config = load_strategy_config(os.path.join(state_root, strategy, STATE_FILENAMES["config"]))
    command = build_strategy_command(strategy, config)
    strategy_dir = os.path.join(state_root, strategy)
    os.makedirs(strategy_dir, exist_ok=True)
    log_file = open(os.path.join(strategy_dir, "loop_log.txt"), "a", encoding="utf-8")
    spawn_detached(command, PROJECT_ROOT, log_file)
    return True


STRATEGY_AUTO_START_HOUR = 7
STRATEGY_AUTO_START_MINUTE = 50
STRATEGY_AUTO_START_STRATEGY = "strategy_1"
STRATEGY_AUTO_START_SCHEDULER_POLL_SECONDS = 30.0
STRATEGY_AUTO_START_MARKER_FILENAME = "auto_start_last_success_date.txt"


def _strategy_auto_start_marker_path(state_root: str, strategy: str) -> str:
    return os.path.join(state_root, strategy, STRATEGY_AUTO_START_MARKER_FILENAME)


def _read_strategy_auto_start_last_success(state_root: str, strategy: str) -> str | None:
    """마지막 성공 날짜를 파일로 영속화한다 — in-memory 변수였으면 대시보드가
    재시작될 때마다(watchdog이 죽은 프로세스를 재시작하는 경우 포함) 잊어버려서,
    이미 오늘 시작했는데도 재시작 직후 또 시작을 시도하게 된다(2026-07-26, 실제로
    이 문제 때문에 당일 재시작 전에 미리 오늘 날짜를 심어둬야 했음)."""
    path = _strategy_auto_start_marker_path(state_root, strategy)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read().strip() or None


def _write_strategy_auto_start_last_success(state_root: str, strategy: str, date_str: str) -> None:
    path = _strategy_auto_start_marker_path(state_root, strategy)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(date_str)


def _strategy_auto_start_due(now: datetime, last_success_date: str | None) -> bool:
    """평일이고, 오늘 아직 자동시작을 성공(또는 이미 실행 중으로 확인)시킨 적 없고,
    지정 시각을 지났으면 True (단위 테스트 대상 순수 함수)."""
    if now.weekday() >= 5:
        return False
    if last_success_date == now.date().isoformat():
        return False
    return (now.hour, now.minute) >= (STRATEGY_AUTO_START_HOUR, STRATEGY_AUTO_START_MINUTE)


def _strategy_auto_start_scheduler_loop(state_root: str, strategy: str) -> None:
    """대시보드가 켜져 있는 평일 아침, 지정 시각(기본 07:50)이 지나면 전략을 스스로
    시작한다 — top35_job.start_daily_scheduler와 같은 이유(이 PC는 Windows 작업
    스케줄러 등록이 UAC로 막혀있어 대시보드 프로세스 안에서 자체 스케줄링).

    한 번 성공(또는 이미 실행 중 확인)하면 그날은 다시 건드리지 않는다 — 사용자가
    낮에 수동으로 "중지"를 누른 경우까지 자동으로 재시작하면 수동 중지가 무의미해지므로,
    top35_job과 동일하게 "실패 시에만 그날 안에서 재시도" 원칙을 따른다(성공 판정
    자체가 크래시 후 재시작까지는 보장하지 않음 — 필요해지면 별도로 요청할 것)."""
    while True:
        try:
            now = datetime.now()
            last_success_date = _read_strategy_auto_start_last_success(state_root, strategy)
            if is_strategy_running(state_root, strategy):
                _write_strategy_auto_start_last_success(state_root, strategy, now.date().isoformat())
            elif _strategy_auto_start_due(now, last_success_date):
                if start_strategy(state_root, strategy):
                    _write_strategy_auto_start_last_success(state_root, strategy, now.date().isoformat())
        except Exception:
            pass  # 상시 스케줄러 — 한 사이클 실패해도 다음 사이클에 계속
        time.sleep(STRATEGY_AUTO_START_SCHEDULER_POLL_SECONDS)


def start_strategy_auto_start_scheduler(state_root: str, strategy: str = STRATEGY_AUTO_START_STRATEGY) -> threading.Thread:
    thread = threading.Thread(target=_strategy_auto_start_scheduler_loop, args=(state_root, strategy), daemon=True)
    thread.start()
    return thread


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

    def _sell_risk_decision(self, strategy: str, code: str, quantity: int) -> risk_manager.RiskDecision:
        """매도도 risk_manager.check_order()를 거치게 한다 — 지금은 check_order가
        side=="sell"이면 rule_id=sell_always_allowed로 무조건 승인하지만, 대시보드가
        승인 경로 자체를 우회하지 않아야 향후 매도측 리스크 룰이 추가돼도 이 라우트가
        자동으로 적용받는다(감사 지적사항). 킬 스위치는 사람이 누르는 긴급 수동
        오버라이드라 이 경로에서 의도적으로 제외한다(/api/kill-switch/*는 그대로 직접 실행)."""
        risk_state = risk_manager.load_state(self._strategy_path(strategy, "risk_state"))
        config = load_strategy_config(self._strategy_path(strategy, "config"))
        total_capital_krw = config.get("total_capital_krw", 10_000_000)
        portfolio = risk_manager.PortfolioState(risk_state=risk_state, total_capital_krw=total_capital_krw)
        order = risk_manager.OrderRequest(code=code, side="sell", quantity=quantity, price=0.0)
        return risk_manager.check_order(order, portfolio)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/market-snapshot":
            self._send_json(get_market_snapshot(self.kiwoom_appkey, self.kiwoom_secretkey, self.kiwoom_is_mock))
        elif parsed.path == "/api/account-snapshot":
            self._send_json(get_account_snapshot(self.kiwoom_appkey, self.kiwoom_secretkey, self.kiwoom_is_mock))
        elif parsed.path == "/api/sell-all-status":
            self._send_json(sell_all_job.get_status())
        elif parsed.path == "/api/nasdaq-drop-monitor-status":
            # nasdaq_drop_monitor는 state/{strategy}/ 규칙을 그대로 따르는 별도
            # 유틸리티(전략1~4처럼 strategy_catalog에 등록된 "전략"은 아님)라
            # is_strategy_running을 그대로 재사용할 수 있다 — 폴더 이름만 다르게 넘긴다.
            self._send_json({
                "running": is_strategy_running(self.state_root, os.path.basename(NASDAQ_DROP_MONITOR_STATE_DIR)),
            })
        elif parsed.path == "/api/dashboard-monitor-status":
            self._send_json({
                "running": is_strategy_running(self.state_root, os.path.basename(DASHBOARD_MONITOR_STATE_DIR)),
            })
        elif parsed.path == "/api/trading-value-ranking":
            window = query.get("window", ["extended"])[0]
            if window not in ("regular", "extended"):
                self._send_json({"error": "window는 regular 또는 extended만 허용됩니다"}, status=400)
            else:
                self._send_json(get_trading_value_ranking(self.kiwoom_appkey, self.kiwoom_secretkey, self.kiwoom_is_mock, window))
        elif parsed.path == "/api/strategies":
            strategies = list_strategies(self.state_root)
            self._send_json({
                "strategies": strategies,
                "selected": self._selected_strategy(query),
                "running": {name: is_strategy_running(self.state_root, name) for name in strategies},
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
            limit = int(query.get("limit", ["200"])[0])
            signal_paths = {s: self._strategy_path(s, "signals") for s in list_strategies(self.state_root)}
            self._send_json(load_all_signal_history(signal_paths, limit=limit))
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
        elif parsed.path == "/ranking.html":
            self._send_static("ranking.html")
        else:
            self.send_response(404)
            self.end_headers()

    def _origin_is_trusted(self) -> bool:
        """이 서버는 인증이 없어 상태 변경 라우트(매도/킬스위치/전략 시작-중지 등)가
        누구나 호출 가능 — 같은 브라우저에 열린 다른 탭(악성 페이지)이 CSRF로 이 API를
        조용히 호출하는 걸 막기 위해, Origin 헤더가 있는데 이 서버 자신(Host)과 다르면
        거부한다. curl 등 브라우저가 아닌 클라이언트는 Origin을 안 보내므로 그대로 통과."""
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        host = self.headers.get("Host", "")
        return origin in (f"http://{host}", f"https://{host}")

    def do_POST(self) -> None:
        if not self._origin_is_trusted():
            self._send_json({"ok": False, "message": "허용되지 않은 요청 출처입니다"}, status=403)
            return
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
            strategy = self._selected_strategy(query)
            decision = self._sell_risk_decision(strategy, "ALL", 0)
            if not decision.approved:
                self._send_json({"started": False, "reason": decision.reason}, status=403)
            else:
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
                strategy = self._selected_strategy(query)
                decision = self._sell_risk_decision(strategy, code, quantity)
                if not decision.approved:
                    self._send_json({"ok": False, "message": decision.reason}, status=403)
                else:
                    try:
                        result = sell_order.sell_one(self.kiwoom_appkey, self.kiwoom_secretkey, self.kiwoom_is_mock, code, quantity)
                        ok = result.get("return_code") == 0
                        self._send_json({"ok": ok, "message": result.get("return_msg", "")}, status=200 if ok else 502)
                    except Exception as exc:
                        self._send_json({"ok": False, "message": str(exc)}, status=502)
        elif parsed.path == "/api/strategy/start":
            strategy = self._selected_strategy(query)
            if start_strategy(self.state_root, strategy):
                self._send_json({"started": True})
            else:
                self._send_json({"started": False, "reason": "이미 실행 중입니다"}, status=409)
        elif parsed.path == "/api/strategy/stop":
            strategy = self._selected_strategy(query)
            stop_control.request_stop(os.path.join(self.state_root, strategy, stop_control.DEFAULT_STOP_FLAG_FILENAME))
            self._send_json({"stopped": True})
        else:
            self.send_response(404)
            self.end_headers()

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(_json_safe(payload), ensure_ascii=False).encode("utf-8")
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
    host: str = "127.0.0.1",
) -> None:
    """host:port에서 대시보드 서버를 기동한다(블로킹). Ctrl+C로 중단.

    host="127.0.0.1"(기본값)은 이 PC에서만 접속 가능 — 모바일 등 다른 기기에서
    접속하려면 host="0.0.0.0"으로 모든 인터페이스에 바인딩해야 한다. 이 대시보드는
    로그인 등 인증이 전혀 없고 일괄매도/개별매도 버튼이 실주문을 내므로, 0.0.0.0으로
    띄울 땐 신뢰할 수 있는 사설망(가정용 와이파이, Tailscale 같은 개인 VPN)에서만
    접근 가능하게 방화벽/네트워크를 제한해야 한다 — 공인 IP에 그대로 노출하면 안 된다.
    """
    server = build_dashboard_server(
        state_root, results_dir,
        kiwoom_appkey, kiwoom_secretkey, kiwoom_is_mock, port=port, host=host,
    )
    if kiwoom_appkey and kiwoom_secretkey:
        # 브라우저 탭 없이도 08:00~09:00 사이 "extended" 조회가 자연히 한 번은 일어나게
        # 해서, 거래대금 랭킹의 "장중"(regular) 베이스라인이 사람이 그 시간에 대시보드를
        # 열어봤는지에 의존하지 않게 한다(trading_value_ranking.py 모듈 docstring 참고).
        start_ranking_background_poller(kiwoom_appkey, kiwoom_secretkey, kiwoom_is_mock)
        # 매일 장 마감 후(기본 15:40) top35 업데이트를 스스로 트리거 — cli.py의
        # update-top35 docstring이 안내하는 "OS 스케줄러 등록"이 이 PC에선 UAC로
        # 막혀 있어(top35_job.start_daily_scheduler 참고), 대신 이미 상시 실행 중인
        # 대시보드 서버 프로세스 안에서 자체 스케줄링한다.
        top35_job.start_daily_scheduler(kiwoom_appkey, kiwoom_secretkey, kiwoom_is_mock)
        # 매일 아침(기본 07:50, 평일만) strategy_1 실전매매를 스스로 시작하는 기능 —
        # 잠정 비활성화(2026-07-26). risk-agent 점검에서 trading_loop.py/
        # oversold_trading_loop.py의 실제 매수 진입이 risk_manager.check_order()를
        # 아예 거치지 않는다는 게 발견됨(손절가 없는 진입 거부, risk_limits.yaml의
        # 한도들이 전부 미적용). 그 연결 작업이 끝나고 검증되기 전까지는 사람이 매일
        # 직접 "시작"을 눌러야 한다 — 그게 사실상 마지막 확인 단계였다.
        # start_strategy_auto_start_scheduler(state_root)
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    print(f"대시보드 서버 시작: http://{display_host}:{port} (Ctrl+C로 중단)", flush=True)
    if host == "0.0.0.0":
        print("0.0.0.0에 바인딩됨 — 신뢰할 수 있는 네트워크(가정용 와이파이/개인 VPN)에서만 접근하세요.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
