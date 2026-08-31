"""소피증권(kospi-theme-engine) 실시간 체결 웹소켓 피드가 살아있는지 결과 기준으로
확인한다. dashboard_monitor.py와 같은 발상(분리된 프로세스, 상태 전이 시점에만 알림)
이지만 확인 방식이 다르다 — 8770 포트가 열려 있는지가 아니라 **엔진이 실제로 틱을
받고 있는지**를 본다.

**"6일간 죽어있었다"는 앞선 진단은 오진이었다(2026-08-30 정정)** — 사용자가 장중이
아닐 때 직접 끈다. dist/logs/(비-dist logs/가 아니라)를 다시 확인해보니 8/24~8/30
매일 정상적으로 켜고 껐다. 그래서 이 감시는 **장중(09:00~15:30 KST)에만** 판정한다.
장외에 꺼져 있는 건 정상이라 그때는 무조건 healthy로 본다 — "포트 응답"이 아니라
"장중에 실제로 데이터가 들어오는지"만 본다는 원래 요구사항 그대로다.

app.engine.runner._run()이 30초마다 찍는 "가동 중 · 틱 N · 종목 M · 테마 K" 로그
줄을 결과 신호로 쓴다 — 별도 API를 새로 만들지 않고 이미 있는 걸 읽기만 한다.
    - 장중인데 이 줄 자체가 안 찍힌 지 오래됐다 = 앱이 안 켜져 있거나 죽음
    - 장중인데 줄은 찍히는데 틱 카운터가 안 늚 = 웹소켓은 붙었지만 데이터가 안 옴
    - 장외에는 위 둘 다 안 본다(꺼져 있는 게 정상이므로)

로그 경로는 **dist/logs/app.log** 다 — kospi-theme-engine/CLAUDE.md의 경고대로
logs/(소스 실행용)는 배포본 실행 중엔 안 갱신된다. `app/paths.py:base_dir()`가
frozen 여부로 기준 폴더를 가른다(exe 폴더 vs 저장소 루트) — logs/가 8/22·8/25에서
멈춰 보인 건 그 디렉터리가 그 이후로 안 쓰였을 뿐, dist/logs/는 오늘까지 계속
갱신되고 있었다(2026-08-30 재확인, 8/24~8/30 매일 수십~백여 회 연결 기록 있음).

**두 번째 감시(2026-08-30 추가): 중복 실행 감지.** "떠 있다"와 "제대로 동작한다"가
다르다는 게 여기서도 반복됐다 — 사용자가 소피증권을 실수로 두 번 띄운 걸 발견했는데,
두 번째 인스턴스가 8770을 못 받고도 9시간 넘게 CPU를 낭비하고 있었다(`count_ai_stock_instances`
참고). 이 검사는 장중 게이트가 없다 — 낭비는 언제 나든 문제이므로 상시 확인한다.
"""
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import psutil

from .heartbeat import write_heartbeat
from .notifier import (
    notify_sophie_duplicate_process,
    notify_sophie_duplicate_resolved,
    notify_sophie_feed_down,
    notify_sophie_feed_recovered,
)
from .stop_control import clear_stop_flag, is_stop_requested

SOPHIE_EXE_NAME = "ai_stock.exe"

SEOUL = ZoneInfo("Asia/Seoul")

DEFAULT_STATE_DIR = "state/sophie_feed_monitor"
DEFAULT_STOP_FLAG_PATH = "state/sophie_feed_monitor/stop_requested.json"
DEFAULT_LOG_PATH = "kospi-theme-engine/dist/logs/app.log"

LOG_STALE_SECONDS = 180.0    # 30초 주기 하트비트가 이만큼 안 찍히면 이상
TICK_STALL_SECONDS = 180.0   # 장중에 틱이 이만큼 안 늘면 이상

_HEARTBEAT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s.*가동 중 · 틱 (\d+)"
)


def is_market_hours(now: datetime) -> bool:
    """평일 09:00~15:30 KST. 공휴일 캘린더는 안 본다 — 휴장일엔 이 함수가 True를
    잘못 돌려줄 수 있는데, 그날은 어차피 앱을 안 켤 테니 "장중인데 하트비트 없음"
    경고가 한 번 뜨는 것뿐이다(사람이 보고 무시하면 됨, 자동 억제는 과설계)."""
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 <= minutes <= 15 * 60 + 30


def find_last_heartbeat(log_path: str, tail_bytes: int = 65536) -> tuple[datetime, int] | None:
    """로그 끝 tail_bytes만 읽어 마지막 '가동 중 · 틱 N' 줄을 찾는다. 전체를 읽으면
    수 MB짜리 로그를 매 사이클(30초) 파싱하게 된다."""
    if not os.path.exists(log_path):
        return None
    size = os.path.getsize(log_path)
    with open(log_path, "rb") as f:
        f.seek(max(0, size - tail_bytes))
        chunk = f.read().decode("utf-8", errors="replace")
    last = None
    for line in chunk.splitlines():
        m = _HEARTBEAT_RE.search(line)
        if m:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=SEOUL)
            last = (ts, int(m.group(2)))
    return last


def check_feed_health(
    log_path: str,
    prev_tick: int | None,
    prev_tick_seen_at: float | None,
    now: datetime | None = None,
) -> tuple[bool, str, int | None, float | None]:
    """결과 기준 1회 판정. prev_tick/prev_tick_seen_at은 이전 호출이 돌려준 값을
    그대로 다음 호출에 넘겨야 하는 상태다(호출부가 들고 있는다).

    반환: (healthy, reason, new_prev_tick, new_prev_tick_seen_at)
    """
    now = now or datetime.now(SEOUL)
    if not is_market_hours(now):
        # 장외엔 꺼져 있는 게 정상 — 판정 자체를 안 한다. prev_tick 상태는 그대로
        # 들고 있다가 장이 열리면 그때 새 값과 비교한다(전날 값과 달라 자연히 갱신됨).
        return True, "", prev_tick, prev_tick_seen_at

    found = find_last_heartbeat(log_path)
    if found is None:
        return (False, "장중인데 app.log에서 '가동 중' 하트비트를 못 찾음(앱을 아직 안 켰거나 죽음)",
                prev_tick, prev_tick_seen_at)

    ts, tick = found
    age = (now - ts).total_seconds()
    if age > LOG_STALE_SECONDS:
        return False, f"장중인데 로그 하트비트가 {age:.0f}초째 안 찍힘(앱이 멈췄거나 죽음)", prev_tick, prev_tick_seen_at

    if tick != prev_tick:
        return True, "", tick, time.monotonic()

    if prev_tick_seen_at is not None:
        stalled_for = time.monotonic() - prev_tick_seen_at
        if stalled_for > TICK_STALL_SECONDS:
            return (False, f"장중인데 틱 카운터가 {stalled_for:.0f}초째 {tick}에서 안 늚(웹소켓 끊김/세션 충돌 의심)",
                    tick, prev_tick_seen_at)

    return True, "", tick, prev_tick_seen_at


def count_ai_stock_instances() -> int:
    """ai_stock.exe **논리적** 인스턴스 수. 그냥 프로세스 개수를 세면 항상 틀린다 —
    PyInstaller onefile은 정상 실행 1개가 부트스트랩+워커 프로세스 쌍(부모-자식)으로
    떠서 OS 프로세스 2개로 보인다(2026-08-30 실측, 정상 단일실행도 2개였다). 그래서
    "부모가 ai_stock.exe가 아닌" 프로세스(=그 인스턴스의 루트)만 센다.

    2026-08-30 실측 사고: 진짜 중복 실행(20:48/20:50, 73초 간격)이 있었는데 두 번째
    인스턴스가 8770을 못 받고도(Windows ThreadingHTTPServer의 SO_REUSEADDR 특성상
    바인드 자체는 예외 없이 "성공"으로 로그돼 기존 안전장치가 못 잡았다) 9시간 넘게
    CPU를 낭비했다. 사용자가 눈으로 발견하기 전까지 아무 알림도 없었다."""
    procs = {p.pid: p.info for p in psutil.process_iter(["pid", "ppid", "name"]) if p.info["name"] == SOPHIE_EXE_NAME}
    roots = [pid for pid, info in procs.items() if info["ppid"] not in procs]
    return len(roots)


def run_sophie_feed_monitor_loop(
    bot_token: str,
    chat_id: str,
    log_path: str = DEFAULT_LOG_PATH,
    poll_interval_seconds: float = 30.0,
    state_dir: str = DEFAULT_STATE_DIR,
    stop_flag_path: str | None = None,
) -> None:
    """dashboard_monitor.py의 run_dashboard_monitor_loop와 같은 뼈대(상태 전이 시점에만
    알림, 사이클 예외가 나도 계속, 하트비트는 사이클 전후 모두 찍음) — 확인 대상만
    HTTP 응답에서 로그 기반 결과 신호로 바뀌었다."""
    stop_flag_path = stop_flag_path or DEFAULT_STOP_FLAG_PATH
    clear_stop_flag(stop_flag_path)
    write_heartbeat(state_dir)

    healthy = True
    prev_tick: int | None = None
    prev_tick_seen_at: float | None = None
    no_duplicate = True  # 장중 게이트와 별개 상태 — 중복 실행은 시간대 무관하게 문제다
    while not is_stop_requested(stop_flag_path):
        try:
            ok, reason, prev_tick, prev_tick_seen_at = check_feed_health(log_path, prev_tick, prev_tick_seen_at)
            if healthy and not ok:
                notify_sophie_feed_down(reason, bot_token, chat_id)
                healthy = False
            elif not healthy and ok:
                notify_sophie_feed_recovered(bot_token, chat_id)
                healthy = True

            count = count_ai_stock_instances()
            if no_duplicate and count > 1:
                notify_sophie_duplicate_process(count, bot_token, chat_id)
                no_duplicate = False
            elif not no_duplicate and count <= 1:
                notify_sophie_duplicate_resolved(bot_token, chat_id)
                no_duplicate = True
        except Exception as exc:
            print(f"소피증권 피드 감시 사이클 오류(계속 진행): {exc}", flush=True)

        write_heartbeat(state_dir)
        time.sleep(poll_interval_seconds)
