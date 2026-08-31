"""폰에서 다우 추세 화면을 보게 서버를 띄운다(읽기 전용).

    python dow_mobile_serve.py             # 같은 WiFi에서 접속 (LAN 주소 출력)
    python dow_mobile_serve.py --tunnel    # + Cloudflare 터널로 외부 공개, 주소는 텔레그램

포트 8771. **8765(트레이딩 대시보드)에는 절대 얹지 않는다** — 거기엔 계좌 손익·주문·
킬스위치가 붙어 있어 공개 URL 뒤에 두면 전부 노출된다(kospi-theme-engine/app/web/mobile.py
가 같은 이유로 8770을 따로 쓴다). 여기서 내보내는 건 시세 분석 결과뿐이고 쓰기 경로가 없다.

접속할 때마다 HTML을 다시 만들어서 항상 최신 캐시를 반영한다.
"""
import os, re, socket, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, ".")
import importlib
import dow_mobile
import dow_signal
import dow_structure

PORT = 8771
# 장중에는 이 주기로 데이터를 다시 받고 큰 화면을 다시 굽는다. 폰 화면은 요청마다
# 새로 그리므로 파일만 새로우면 바로 반영된다.
REFRESH_SEC = 60
REFRESH_HOURS = (8, 20)        # 통합 세션(08:00~20:00). 그 밖에는 값이 안 움직인다
DOW_CODES = ("000660", "005930")
REFRESH_LOG = Path("dow_refresh.log")
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
CLOUDFLARED = (r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
               r"C:\Program Files\cloudflared\cloudflared.exe")


def _run(args: list[str]) -> bool:
    """한 단계를 돌린다. 실패해도 서버는 계속 간다 — 갱신이 멎는 것보다 화면이
    안 뜨는 것이 훨씬 나쁘다."""
    try:
        r = subprocess.run([sys.executable, *args], capture_output=True, text=True,
                           timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        _log(f"{args[0]} 실패: {type(exc).__name__} {exc}")
        return False
    if r.returncode != 0:
        _log(f"{args[0]} 실패(코드 {r.returncode}): {(r.stderr or '').strip()[:200]}")
        return False
    return True


def _log(line: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with REFRESH_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {line}\n")
    except OSError:
        pass


def refresher() -> None:
    """데이터를 받아 두 화면을 최신으로 유지한다.

    받는 것: 통합 15분봉(fetch_combined_15min) + 일봉(short_check). 정규 분봉
    (data/stocks/minute)은 top35 일일 작업이 채우므로 여기서 건드리지 않는다 —
    같은 파일을 두 곳에서 쓰면 반쯤 쓰인 파일을 읽게 된다.

    마지막에 큰 화면(dow_interactive)을 다시 굽는다. 폰 화면은 요청마다 새로
    그리므로 따로 할 일이 없다.
    """
    while True:
        now = time.localtime()
        weekday = now.tm_wday < 5
        in_hours = REFRESH_HOURS[0] <= now.tm_hour < REFRESH_HOURS[1]
        if weekday and in_hours:
            ok = _run(["fetch_combined_15min.py", *DOW_CODES])
            ok = _run(["short_check.py", *DOW_CODES]) and ok
            if _run(["dow_interactive.py"]):
                _log(f"갱신 완료{'' if ok else ' (일부 실패)'}")
        time.sleep(REFRESH_SEC)


def lan_ip() -> str:
    """외부로 나가는 인터페이스의 주소. hostname 조회는 VPN/가상 어댑터를 집어올 때가 있다."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):                      # 액세스 로그로 콘솔을 채우지 않는다
        pass

    def do_GET(self):                               # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/desktop", "/desktop/", "/dow_interactive.html"):
            # 큰 화면은 plotly 인라인(약 5MB)이라 매 요청 생성하지 않고 파일을 그대로 보낸다.
            # dow_interactive.py 를 다시 돌리면 갱신된다(소피증권의 /desktop 과 같은 관례).
            try:
                body = Path("static/dashboard/dow_interactive.html").read_bytes()
            except OSError:
                self.send_error(503, "dow_interactive.html not built")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path not in ("/", "/index.html", "/dow_mobile.html"):
            self.send_error(404)
            return
        try:
            # 모듈까지 다시 읽는다 — 안 그러면 코드를 고쳐도 서버를 재시작해야 반영된다.
            # **의존 모듈이 먼저다.** dow_mobile 만 다시 읽으면 그 안의
            # `from dow_structure import ...` 가 메모리에 남은 옛 dow_structure 를 보고,
            # 새로 만든 이름은 "cannot import name" 으로 깨진다(실측: pick_leg).
            for _m in (dow_signal, dow_structure, dow_mobile):
                importlib.reload(_m)
            body = dow_mobile.build().encode("utf-8")
        except Exception as exc:
            body = f"<pre>생성 실패: {exc}</pre>".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):                              # noqa: N802  쓰기 경로를 만들지 않는다
        self.send_error(405)


def start_tunnel():
    exe = next((p for p in CLOUDFLARED if os.path.exists(p)), None) or __import__("shutil").which("cloudflared")
    if not exe:
        print("cloudflared가 없어 터널을 건너뜁니다.", flush=True)
        return
    log = Path("dow_tunnel.log")
    proc = subprocess.Popen([exe, "tunnel", "--url", f"http://127.0.0.1:{PORT}"],
                            stdout=log.open("w", encoding="utf-8"), stderr=subprocess.STDOUT)
    for _ in range(90):
        time.sleep(1)
        hits = URL_RE.findall(log.read_text(encoding="utf-8", errors="replace")) if log.exists() else []
        if hits:
            url = hits[-1]
            print(f"외부 주소  {url}", flush=True)
            try:
                from dotenv import load_dotenv
                from backtesting.notifier import INFO, send_telegram
                load_dotenv(".env")
                send_telegram(f"📈 다우 추세 화면\n{url}",
                              os.environ.get("TELEGRAM_BOT_TOKEN", ""),
                              os.environ.get("TELEGRAM_CHAT_ID", ""), level=INFO)
            except Exception as exc:
                print("텔레그램 발송 실패:", exc, flush=True)
            return proc
    print("터널 주소를 못 받았습니다. dow_tunnel.log 확인.", flush=True)
    return proc


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"폰 화면 :  http://{lan_ip()}:{PORT}/         (같은 WiFi)", flush=True)
    print(f"큰 화면 :  http://{lan_ip()}:{PORT}/desktop", flush=True)
    if "--no-refresh" not in sys.argv:
        threading.Thread(target=refresher, name="refresher", daemon=True).start()
        print(f"자동 갱신 :  {REFRESH_SEC}초마다 (평일 "
              f"{REFRESH_HOURS[0]:02d}:00~{REFRESH_HOURS[1]:02d}:00) · {REFRESH_LOG}",
              flush=True)
    if "--tunnel" in sys.argv:
        threading.Thread(target=start_tunnel, daemon=True).start()
    print("Ctrl+C 로 종료", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def demo():
    """라우팅 규칙만 검사 — 서버를 띄우지 않는다."""
    ok = ("/", "/index.html", "/dow_mobile.html", "/?x=1", "/desktop", "/dow_interactive.html")
    bad = ("/secret", "/../.env", "/api/state")
    check = lambda p: p.split("?")[0] in ("/", "/index.html", "/dow_mobile.html",
                                          "/desktop", "/desktop/", "/dow_interactive.html")
    assert all(check(p) for p in ok), [p for p in ok if not check(p)]
    assert not any(check(p) for p in bad), [p for p in bad if check(p)]
    assert "plotly" not in dow_mobile.build().lower()
    print("demo ok: 폰/큰화면 경로만 통과, 쓰기 경로 없음")


if __name__ == "__main__":
    demo() if "--demo" in sys.argv else main()
