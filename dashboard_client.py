"""[0184] 거래대금상위 랭킹을 크롬/엣지 없이 별도 네이티브 창으로 띄우는 독립 실행 프로그램.

기본 동작(서버 없이): 이 PC 로컬(127.0.0.1)에 읽기 전용 미니 서버를 자체적으로 띄우고
그걸 그대로 pywebview 창에 띄운다 — 다른 PC나 항상 켜진 서버에 의존하지 않는다.
각 컴퓨터는 자기 .env(KIWOOM_APPKEY/KIWOOM_SECRETKEY)로 키움 API를 직접 호출한다.
main dashboard_server.py의 전체 핸들러(매도 주문 등 실거래 라우트 포함)는 절대 쓰지
않는다 — 여러 PC에 흩어져 상시 실행되는 앱에 실주문 가능한 서버를 얹는 건 위험하다.

--url을 지정하면 예전처럼 이미 켜져 있는 원격 dashboard_server를 그대로 보는 모드로
동작한다 (이 경우 이 PC에는 .env가 필요 없다).

사용법:
    python dashboard_client.py                              # 독립 실행 (기본)
    python dashboard_client.py --url http://<원격_IP>:8765/ranking.html  # 원격 서버 보기

빌드(다른 PC에 Python 없이 배포):
    pip install pywebview pyinstaller
    pyinstaller --onefile --windowed dashboard_client.py
    dist/dashboard_client.exe 와 그 PC용 .env(KIWOOM_APPKEY/KIWOOM_SECRETKEY)를 같이 배포
"""
import argparse
import ctypes
import json
import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import webview
from dotenv import load_dotenv

from backtesting.trading_value_ranking import get_ranking, start_background_poller
from kiwoom_client import KiwoomClient

# PyInstaller onefile로 빌드하면 CWD가 "어디서 더블클릭했는지"에 따라 제멋대로라
# trading_value_ranking.py가 쓰는 상대경로 state/regular_session_baseline.json이
# 엉뚱한(보통 빈) 폴더를 가리켜 "장중" 베이스라인을 영영 못 찾는 문제가 있었다(실측).
# exe/스크립트 자신의 위치를 기준으로 고정한다.
APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
STATIC_DIR = Path(__file__).parent / "static" / "dashboard"
CONFIG_PATH = APP_DIR / "dashboard_client_config.json"
CONTENT_TYPES = {"ranking.html": "text/html; charset=utf-8", "style.css": "text/css; charset=utf-8"}


class _RankingOnlyHandler(BaseHTTPRequestHandler):
    """읽기 전용: 랭킹 조회 API + 정적 파일 2개뿐, 주문/계좌 라우트는 아예 없다."""

    appkey = secretkey = ""
    is_mock = True

    def log_message(self, *args) -> None:
        pass  # 콘솔에 요청 로그 스팸 안 남김

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/trading-value-ranking":
            window = parse_qs(parsed.query).get("window", ["extended"])[0]
            data = get_ranking(self.appkey, self.secretkey, self.is_mock, window)
            self._send_json(data)
        elif parsed.path in ("/", "/ranking.html"):
            self._send_static("ranking.html")
        elif parsed.path == "/style.css":
            self._send_static("style.css")
        else:
            self.send_response(404)
            self.end_headers()

    def _send_json(self, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, filename: str) -> None:
        path = STATIC_DIR / filename
        if not path.exists():
            self.send_response(404)
            self.end_headers()
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES[filename])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _preflight_error(appkey: str, secretkey: str, is_mock: bool) -> str | None:
    """토큰 발급을 한 번 미리 시도해, 데이터가 계속 빈 채로만 보이는(원인 불명) 상황을
    막는다 — 원격 PC에서 문제가 생기면 화면 밖에서(콘솔도 없는 --windowed 빌드라)
    원인을 알 방법이 없었다(실측: "장중/전체 둘 다 안 됨"만 보고받고 원인 특정 불가)."""
    if not (appkey and secretkey):
        return ".env에 KIWOOM_APPKEY/KIWOOM_SECRETKEY가 없습니다"
    try:
        KiwoomClient(appkey, secretkey, is_mock).issue_token()
        return None
    except Exception as e:
        return f"키움 API 연결 실패: {e}"


def _start_local_server(appkey: str, secretkey: str, is_mock: bool) -> str:
    """127.0.0.1의 빈 포트에 읽기 전용 랭킹 서버를 띄우고 그 URL을 반환한다."""
    handler_cls = type("BoundRankingHandler", (_RankingOnlyHandler,), {
        "appkey": appkey, "secretkey": secretkey, "is_mock": is_mock,
    })
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    error = _preflight_error(appkey, secretkey, is_mock)
    if appkey and secretkey and not error:
        # "장중"(regular) 순위는 09:00 장 시작 직전 누적치를 베이스라인으로 빼는
        # 방식이라, 이 앱이 매일 08:00~09:00 사이에 한 번은 켜져 있어야 그날의
        # 베이스라인을 스스로 잡는다 — 켜져 있지 않았던 날은 "장중"이 "전체"(누적)와
        # 똑같이 나온다(API 자체가 과거 시점 조회를 지원하지 않아 그날은 복구 불가,
        # trading_value_ranking.py 모듈 docstring 참고). 다음날부터는 이 앱을 08시
        # 이전에 켜두면 정상화된다.
        start_background_poller(appkey, secretkey, is_mock)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/ranking.html"
    if error:
        url += f"?error={quote(error)}"
    return url


def _load_url() -> str | None:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("url")
    return None


def _save_url(url: str) -> None:
    CONFIG_PATH.write_text(json.dumps({"url": url}, ensure_ascii=False, indent=2), encoding="utf-8")


def _warn_if_no_webview2() -> None:
    """WebView2 런타임(또는 .NET 4.6.2+)이 없으면 pywebview가 조용히 구식 mshtml로
    폴백하는데, ranking.html의 fetch/템플릿 리터럴이 그 위에서 전혀 안 돌아 빈 흰
    화면만 뜬다(실측) — --windowed 빌드라 사용자는 원인을 알 방법이 없다. 창을
    띄우기 전에 렌더러를 먼저 확인해 알아볼 수 있는 메시지박스로 알려준다."""
    if sys.platform != "win32":
        return
    try:
        from webview.platforms.winforms import renderer
    except Exception:
        return  # 감지 실패는 기존 동작(그냥 창 띄우기)을 막지 않는다
    if renderer != "mshtml":
        return
    ctypes.windll.user32.MessageBoxW(
        0,
        "Microsoft Edge WebView2 Runtime이 설치돼 있지 않아 화면이 비어 보입니다.\n"
        "Microsoft 공식 사이트에서 'WebView2 Runtime'을 검색해 설치한 뒤 다시 실행하세요.",
        "[0184] 거래대금상위 - 실행 환경 확인 필요",
        0x10,  # MB_ICONERROR
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", help="이미 켜져 있는 원격 dashboard_server를 보려면 그 ranking.html URL 지정 (생략 시 독립 실행)")
    args = parser.parse_args()

    os.chdir(APP_DIR)  # 상태 파일(state/...)이 exe 위치 기준 고정 폴더에 쌓이게
    # --windowed 빌드는 콘솔이 없어 pywebview가 내는 경고(예: WebView2 런타임이
    # 없어 구식 mshtml로 폴백했다는 경고)를 볼 방법이 없다 — 파일로라도 남긴다.
    logging.basicConfig(filename=str(APP_DIR / "dashboard_client.log"), level=logging.WARNING, encoding="utf-8")
    saved_url = _load_url()
    if args.url:
        _save_url(args.url)
        url = args.url
    elif saved_url:
        url = saved_url
    else:
        load_dotenv(APP_DIR / ".env")
        url = _start_local_server(
            os.environ.get("KIWOOM_APPKEY", ""),
            os.environ.get("KIWOOM_SECRETKEY", ""),
            os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true",
        )

    _warn_if_no_webview2()
    webview.create_window("[0184] 거래대금상위", url, width=900, height=700)
    webview.start()


if __name__ == "__main__":
    main()
