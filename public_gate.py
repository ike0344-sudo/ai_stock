"""8765 대시보드에서 순위 두 화면만 밖으로 내보내는 문지기(기본 8766).

    python public_gate.py [--port 8766]

8765 에는 계좌·주문·킬스위치가 인증 없이 붙어 있어 터널로 직접 열면 안 된다.
여기는 아래 ALLOWED 경로만 8765 에서 받아 그대로 돌려주고 나머지는 전부 404 다.
GET 만 받는다 — 주문 라우트(POST)는 애초에 통과할 길이 없다.

관리자 화면: http://127.0.0.1:8766/admin (이 PC 에서만 열린다)

접속 기록: 화면(.html)을 열 때마다 logs/public_gate_access.tsv 에 한 줄
(시각·접속자 IP·화면·브라우저). 1초마다 도는 데이터 폴링은 안 남긴다.
    python public_gate.py --stats          # 오늘 몇 명·몇 번
    python public_gate.py --stats 2026-09-28
"""
import argparse
import collections
import datetime as dt
import html
import json
import queue
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

UPSTREAM = "http://127.0.0.1:8765"
ALLOWED = {
    "/ranking.html", "/afterhours.html", "/style.css",
    "/api/trading-value-ranking", "/api/afterhours-ranking",
}
ACCESS_LOG = Path(__file__).parent / "logs" / "public_gate_access.tsv"
_log_lock = threading.Lock()
# 지금 보고 있는 사람: 화면이 1~3초마다 데이터를 당기므로 ONLINE_SEC 안에 당긴 IP 를 접속 중으로 본다.
# 메모리에만 둔다(재시작하면 비지만 몇 초 뒤 다시 찬다). 브라우저 탭을 뒤로 숨기면 폴링이 느려져 빠질 수 있다.
ONLINE_SEC = 15
_online: dict[str, dict] = {}   # ip -> {since, last, page, agent}
PAGE_OF_API = {"/api/trading-value-ranking": "당일 순위", "/api/afterhours-ranking": "애프터장"}


def touch(ip: str, path: str, agent: str) -> None:
    now = time.time()
    with _log_lock:
        s = _online.get(ip)
        if not s or now - s["last"] > 60:   # 1분 넘게 끊겼으면 새로 들어온 것으로
            s = _online[ip] = {"since": now}
        s.update(last=now, page=PAGE_OF_API[path], agent=agent)


def online_now() -> list[tuple[str, dict]]:
    now = time.time()
    with _log_lock:
        return sorted(((ip, dict(s)) for ip, s in _online.items() if now - s["last"] <= ONLINE_SEC),
                      key=lambda kv: kv[1]["since"])


def record(ip: str, path: str, agent: str) -> None:
    ACCESS_LOG.parent.mkdir(exist_ok=True)
    line = "\t".join((dt.datetime.now().isoformat(timespec="seconds"), ip, path, agent.replace("\t", " "))) + "\n"
    with _log_lock, ACCESS_LOG.open("a", encoding="utf-8") as f:
        f.write(line)


def load_rows() -> list[list[str]]:
    if not ACCESS_LOG.exists():
        return []
    return [r for r in (l.rstrip("\n").split("\t") for l in ACCESS_LOG.open(encoding="utf-8")) if len(r) == 4]


GEO_CACHE = Path(__file__).parent / "logs" / "public_gate_geo.json"
_geo: dict[str, str] = json.loads(GEO_CACHE.read_text(encoding="utf-8")) if GEO_CACHE.exists() else {}
_geo_queue: "queue.Queue[str]" = queue.Queue()
COUNTRY_KO = {"South Korea": "한국", "United States": "미국", "Japan": "일본", "China": "중국"}


def _geo_worker() -> None:
    """ip-api.com(무료, 분당 45회)로 한 IP 씩 천천히 조회해 파일에 쌓는다. 한 번 찾은 IP 는 다시 안 묻는다."""
    while True:
        ip = _geo_queue.get()
        if ip in _geo:
            continue
        try:
            with urllib.request.urlopen(f"http://ip-api.com/json/{ip}?fields=status,country,regionName,city,isp,mobile,proxy,hosting",
                                        timeout=10) as r:
                d = json.load(r)
            if d.get("status") == "success":
                tags = [t for t, on in (("휴대폰망", d.get("mobile")), ("VPN/프록시", d.get("proxy")), ("서버", d.get("hosting"))) if on]
                place = ", ".join(x for x in (d.get("city"), d.get("regionName"), COUNTRY_KO.get(d.get("country"), d.get("country"))) if x)
                _geo[ip] = f"{place} · {d.get('isp', '')}" + (f" ({', '.join(tags)})" if tags else "")
            else:
                _geo[ip] = "알 수 없음"
            with _log_lock:
                GEO_CACHE.write_text(json.dumps(_geo, ensure_ascii=False, indent=0), encoding="utf-8")
        except OSError:
            pass  # 다음에 관리 화면을 열 때 다시 줄을 선다
        time.sleep(1.5)


def geo(ip: str) -> str:
    if ip == "로컬":
        return "이 PC"
    if ip not in _geo:
        _geo_queue.put(ip)
        return "조회 중…"
    return _geo[ip]


def browser(agent: str) -> str:
    a = agent.lower()
    kind = "휴대폰" if ("mobile" in a or "android" in a or "iphone" in a) else "PC"
    for key, name in (("kakaotalk", "카카오톡"), ("telegram", "텔레그램 미리보기"), ("edg", "엣지"),
                      ("samsungbrowser", "삼성 인터넷"), ("chrome", "크롬"), ("safari", "사파리"), ("firefox", "파이어폭스")):
        if key in a:
            return f"{name} · {kind}"
    return f"기타 · {kind}"


def tunnel_url() -> str:
    log = Path(__file__).parent / "state" / "tunnel" / "public_gate_cloudflared.log"
    if not log.exists():
        return ""
    found = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", log.read_text(encoding="utf-8", errors="replace"))
    return found[-1] if found else ""


_alive_cache: dict[str, tuple[float, bool]] = {}


def tunnel_alive(url: str) -> bool:
    """로그의 마지막 주소가 지금도 살아 있는지 — 터널이 죽어도 로그엔 옛 주소가 남는다.
    관리자 화면이 5초마다 새로고침하므로 60초 동안 결과를 재사용한다."""
    hit = _alive_cache.get(url)
    # 막 켠 터널은 DNS 가 퍼지기 전 몇 초간 안 열린다 — '꺼짐'은 10초만 믿는다
    if hit and time.time() - hit[0] < (60 if hit[1] else 10):
        return hit[1]
    try:
        with urllib.request.urlopen(url + "/ranking.html", timeout=4) as r:
            ok = r.status == 200
    except Exception:
        ok = False
    _alive_cache[url] = (time.time(), ok)
    return ok


def tunnel_links(url: str) -> str:
    e = html.escape
    if not url:
        return "<b>터널 꺼짐</b>"
    links = " · ".join(f'<a href="{e(url)}{p}" target="_blank">{e(url)}{p}</a>'
                       for p in ("/ranking.html", "/afterhours.html"))
    if tunnel_alive(url):
        return f'<span style="color:#1b7a3f">● 접속 가능</span> {links}'
    return f'<b style="color:#c62828">● 터널 꺼짐</b> <span class="dim">(마지막 주소: {e(url)} — 지금은 안 열림)</span>'


def admin_html(day: str) -> str:
    """관리자 화면. 로컬 열람(자기 확인)은 사람 수에서 뺀다."""
    e = html.escape
    rows = [r for r in load_rows() if r[1] != "로컬"]
    days = collections.OrderedDict()
    for r in rows:
        days.setdefault(r[0][:10], []).append(r)
    today = [r for r in rows if r[0].startswith(day)]
    per_ip: dict[str, list[list[str]]] = {}
    for r in today:
        per_ip.setdefault(r[1], []).append(r)
    url = tunnel_url()
    live = [(ip, s) for ip, s in online_now() if ip != "로컬"]
    live_rows = "".join(
        f"<tr><td>{e(ip)}</td><td>{e(geo(ip))}</td><td>{s['page']}</td><td>{time.strftime('%H:%M:%S', time.localtime(s['since']))}</td>"
        f"<td>{int((time.time() - s['since']) // 60)}분</td><td>{e(browser(s['agent']))}</td></tr>"
        for ip, s in live)

    day_rows = "".join(
        f'<tr><td><a href="/admin?day={d}">{d}</a></td><td>{len({r[1] for r in rs})}</td><td>{len(rs)}</td></tr>'
        for d, rs in reversed(list(days.items())[-30:]))
    ip_rows = "".join(
        f"<tr><td>{e(ip)}</td><td>{e(geo(ip))}</td><td>{len(rs)}</td><td>{rs[0][0][11:]}</td><td>{rs[-1][0][11:]}</td>"
        f"<td>{e(', '.join(sorted({r[2] for r in rs})))}</td><td>{e(browser(rs[-1][3]))}</td></tr>"
        for ip, rs in sorted(per_ip.items(), key=lambda kv: -len(kv[1])))
    recent = "".join(
        f"<tr><td>{r[0][11:]}</td><td>{e(r[1])}</td><td>{e(geo(r[1]))}</td><td>{e(r[2])}</td><td>{e(browser(r[3]))}</td></tr>"
        for r in reversed(today[-100:]))
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="5"><title>공개 화면 접속 관리</title>
<style>
body{{font-family:system-ui,'Malgun Gothic',sans-serif;margin:18px;color:#14120e;background:#fff}}
h1{{font-size:1.1rem}} h2{{font-size:.95rem;margin-top:22px}}
.big{{display:flex;gap:28px;margin:8px 0}} .big b{{font-size:1.6rem;display:block}}
table{{border-collapse:collapse;font-size:.85rem;font-variant-numeric:tabular-nums}}
th,td{{padding:4px 10px;border-bottom:1px solid #e2ded4;text-align:left}} th{{background:#f0efec}}
.dim{{color:#5c584e;font-size:.8rem}} code{{background:#f7f7f5;padding:2px 5px}}
</style></head><body>
<h1>공개 화면 접속 관리 <span class="dim">(이 PC에서만 열림 · 5초마다 새로고침)</span></h1>
<p>공개 주소: {tunnel_links(url)}</p>
<div class="big"><div style="color:#1b7a3f">지금 보는 중<b>{len(live)}명</b></div><div>{e(day)} 접속자<b>{len(per_ip)}명</b></div><div>화면 열람<b>{len(today)}회</b></div></div>
<p class="dim">이 PC에서 직접 연 것은 세지 않습니다. 텔레그램 미리보기(링크를 보낼 때 텔레그램이 한 번 열어 봄)는 사람이 아닙니다.</p>
<h2>지금 보는 중 <span class="dim">(최근 {ONLINE_SEC}초 안에 화면이 데이터를 받아간 사람)</span></h2>
<table><tr><th>IP</th><th>위치 · 통신사</th><th>보는 화면</th><th>들어온 시각</th><th>머문 시간</th><th>브라우저</th></tr>{live_rows or '<tr><td colspan=6>없음</td></tr>'}</table>
<h2>접속자별 ({e(day)})</h2>
<table><tr><th>IP</th><th>위치 · 통신사</th><th>열람</th><th>첫 접속</th><th>마지막</th><th>본 화면</th><th>브라우저</th></tr>{ip_rows or '<tr><td colspan=7>없음</td></tr>'}</table>
<h2>날짜별 (최근 30일)</h2>
<table><tr><th>날짜</th><th>접속자</th><th>열람</th></tr>{day_rows or '<tr><td colspan=3>없음</td></tr>'}</table>
<h2>최근 접속 100건 ({e(day)})</h2>
<table><tr><th>시각</th><th>IP</th><th>위치 · 통신사</th><th>화면</th><th>브라우저</th></tr>{recent or '<tr><td colspan=5>없음</td></tr>'}</table>
</body></html>"""


def stats(day: str) -> None:
    rows = [r for r in load_rows() if r[0].startswith(day)]
    per_ip = collections.Counter(r[1] for r in rows)
    print(f"{day}: 접속자 {len(per_ip)}명 · 화면 열람 {len(rows)}회")
    for ip, n in per_ip.most_common():
        first = next(r[0][11:] for r in rows if r[1] == ip)
        print(f"  {ip:<40} {n:>4}회  첫 접속 {first}")


class Gate(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        path = parts.path
        if path == "/admin":
            # 방문자 IP 가 보이는 화면 — 터널로 온 요청(CF-Connecting-IP 있음)은 막는다
            if self.headers.get("CF-Connecting-IP") or not self.headers.get("Host", "").startswith("127.0.0.1"):
                self.send_error(404)
                return
            day = parse_qs(parts.query).get("day", [dt.date.today().isoformat()])[0]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                day = dt.date.today().isoformat()
            body = admin_html(day).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.endswith(".html") or path == "/":
            # 터널로 오면 원래 주소는 CF-Connecting-IP 에 있다(연결 자체는 cloudflared=127.0.0.1)
            record(self.headers.get("CF-Connecting-IP") or "로컬", path, self.headers.get("User-Agent", ""))
        if path in ("/", "/index.html"):  # 메인 대시보드 링크는 순위 화면으로 돌린다
            self.send_response(302)
            self.send_header("Location", "/ranking.html")
            self.end_headers()
            return
        if path in PAGE_OF_API:
            touch(self.headers.get("CF-Connecting-IP") or "로컬", path, self.headers.get("User-Agent", ""))
        if path not in ALLOWED:
            self.send_error(404)
            return
        try:
            with urllib.request.urlopen(UPSTREAM + self.path, timeout=20) as r:
                body, ctype, status = r.read(), r.headers.get("Content-Type", ""), r.status
        except urllib.error.HTTPError as e:
            body, ctype, status = e.read(), e.headers.get("Content-Type", ""), e.code
        except OSError:
            self.send_error(502, "대시보드 응답 없음")
            return
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--stats", nargs="?", const=dt.date.today().isoformat(), help="그날 접속 요약만 출력")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.stats:
        stats(args.stats)
        raise SystemExit
    port = args.port
    threading.Thread(target=_geo_worker, daemon=True).start()
    print(f"공개 문지기 http://127.0.0.1:{port}/ranking.html", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Gate).serve_forever()
