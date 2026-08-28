"""소피증권 모바일 화면(8770)을 Cloudflare Tunnel 로 외부에 연다.

    python tunnel_job.py

무료 quick tunnel 은 **띄울 때마다 주소가 바뀐다.** 그래서 이 스크립트가 하는 일은
셋이다 — cloudflared 를 붙들고, 주소가 바뀌면 텔레그램으로 알리고, 죽으면 다시 띄운다.
주소를 사람이 로그에서 찾아 읽어야 한다면 자동화한 의미가 없다.

스케줄링은 하지 않는다. nasdaq_monitor_watchdog.ps1 이 5분마다 깨어나 하트비트를 보고
살려주므로(daily_report_job.py 와 같은 규약), 여기서는 하트비트만 남긴다.

**8765(트레이딩 대시보드)를 절대 가리키지 말 것.** 거기엔 계좌 손익·주문·킬스위치가
붙어 있다. 8770 은 조회 전용이라 공개 URL 뒤에 두어도 새어 나갈 것이 없다.
"""
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backtesting.heartbeat import write_heartbeat
from backtesting.notifier import INFO, send_telegram

STATE_DIR = "state/tunnel"
URL_FILE = Path(STATE_DIR) / "url.txt"
LOG_PATH = Path("kospi-theme-engine/logs/cloudflared.log")
LOCAL_URL = "http://127.0.0.1:8770"

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
CLOUDFLARED_CANDIDATES = (
    r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
    r"C:\Program Files\cloudflared\cloudflared.exe",
)
URL_WAIT_SECONDS = 90          # 터널이 주소를 뱉을 때까지. 망이 느리면 30초 넘게 걸린다
HEARTBEAT_EVERY = 20


def cloudflared_path() -> str | None:
    found = shutil.which("cloudflared")
    if found:
        return found
    return next((p for p in CLOUDFLARED_CANDIDATES if os.path.exists(p)), None)


def read_url(since: float) -> str | None:
    """로그에서 터널 주소를 찾는다. **이번에 띄운 것만** 본다 —
    파일이 남아 있으면 어제 주소를 새 주소로 착각한다."""
    try:
        if LOG_PATH.stat().st_mtime < since:
            return None
        text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    hits = URL_RE.findall(text)
    return hits[-1] if hits else None


def announce(url: str) -> None:
    """주소가 바뀌었을 때만 보낸다. 매번 보내면 알림이 무의미해진다."""
    previous = URL_FILE.read_text(encoding="utf-8").strip() if URL_FILE.is_file() else ""
    if previous == url:
        return
    URL_FILE.parent.mkdir(parents=True, exist_ok=True)
    URL_FILE.write_text(url, encoding="utf-8")

    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("텔레그램 설정이 없어 주소만 저장했습니다:", url, flush=True)
        return
    send_telegram("\n".join([
        "📱 소피증권 주소가 바뀌었습니다",
        f"폰 화면  {url}",
        f"큰 화면  {url}/desktop",
        "",
        "아이디 sophie · 비밀번호는 .env 의 SOPHIE_WEB_PASSWORD",
    ]), token, chat, level=INFO)
    print("새 주소 통보:", url, flush=True)


def run_once(exe: str) -> None:
    """터널 하나를 띄우고 죽을 때까지 붙들고 있는다."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    # 로그를 비우고 시작한다 — 지난 실행의 주소가 남아 있으면 그걸 새 주소로 읽는다.
    try:
        LOG_PATH.write_text("", encoding="utf-8")
    except OSError:
        pass
    # --protocol http2: 기본값 quic 은 UDP:7844 세션을 붙들고 있는데, 공유기/ISP 의
    # NAT 가 유휴 UDP 매핑을 몇 분 만에 버린다. 그러면 "no recent network activity" 로
    # 끊기고 재연결이 반복된다(8/26 로그 실측 — 60초~5분마다). http2 는 TCP:443 이라
    # NAT 가 끊지 않는다. 처리량은 quic 보다 조금 낮지만 조회 전용 화면엔 무관하다.
    # --ha-connections 는 넣어도 소용없다. 4 를 줘도 로그의 파싱 결과가 1 로 돌아온다
    # (계정 없는 quick tunnel 이라 그런 것으로 보인다, 8/26 실측). 이름 있는 터널로
    # 옮기면 그때 다시 시도해 볼 것.
    proc = subprocess.Popen(
        [exe, "tunnel", "--url", LOCAL_URL, "--protocol", "http2",
         "--logfile", str(LOG_PATH), "--loglevel", "info"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    print("cloudflared 시작 pid", proc.pid, flush=True)

    url, deadline = None, time.time() + URL_WAIT_SECONDS
    while time.time() < deadline and proc.poll() is None:
        url = read_url(started)
        if url:
            announce(url)
            break
        write_heartbeat(STATE_DIR)
        time.sleep(2)
    if not url:
        print("주소를 못 받았습니다 — 터널을 접고 다시 시도합니다", flush=True)
        proc.terminate()

    while proc.poll() is None:
        write_heartbeat(STATE_DIR)
        time.sleep(HEARTBEAT_EVERY)
    print("cloudflared 종료 (코드", proc.returncode, ")", flush=True)


def main() -> None:
    load_dotenv()
    exe = cloudflared_path()
    if not exe:
        print("cloudflared 를 찾을 수 없습니다 — winget install --id Cloudflare.cloudflared")
        raise SystemExit(1)
    print("cloudflared:", exe, flush=True)
    while True:
        run_once(exe)
        # 곧바로 다시 띄우면 망이 끊긴 동안 초당 재시도가 된다. 텔레그램도 그만큼 운다.
        write_heartbeat(STATE_DIR)
        time.sleep(15)


if __name__ == "__main__":
    main()
