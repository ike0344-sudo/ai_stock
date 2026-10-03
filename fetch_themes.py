"""네이버 금융 테마 -> 종목 매핑을 data/themes.csv로 수집한다.

    python fetch_themes.py                 # 전체 수집(테마 목록 -> 테마별 구성종목) -> data/themes.csv
    python fetch_themes.py 다른/경로.csv    # 다른 파일로 저장(옛 표와 비교할 때)
    python fetch_themes.py --demo          # 파싱 자체검증(네트워크 없음)

키움 ka10099의 upName은 KRX 표준 대분류라 "화학"까지만 내려간다 - 한국콜마가
화장품이라는 정보가 없다. 네이버 테마는 장세 테마(화장품, 로봇, 전선)라 결이 맞다.

종목:테마는 1:N이다. 랭킹 표에는 대표 하나만 쓰므로 theme_size(그 테마의 구성종목
수)를 같이 저장해둔다 - 작은 테마일수록 구체적이라 대표로 뽑는다("화장품" 10종목 vs
"중국_소비재 확대" 12종목이면 앞쪽). 뽑는 규칙 자체는 쓰는 쪽(trading_value_ranking)에
있고 이 파일은 원본을 그대로 담는다.

2026-10-03: 옛 페이지(finance.naver.com/sise/theme.naver)가 새 사이트(stock.naver.com, 화면을 자바스크립트로 그림)로
넘어가 HTML 에 테마 링크가 없다 — 8/29 뒤로 0개를 받고 있었다. 새 사이트가 쓰는 JSON API 를 그대로 받는다.
  목록     https://m.stock.naver.com/api/stocks/theme?page=N&pageSize=100        groups[{no, name, totalCount, ...}], totalCount 264
  구성종목 https://m.stock.naver.com/api/stocks/theme/{no}?page=N&pageSize=100   stocks[{itemCode, stockName, ...}]
파싱이 없어 쪽당 수 ms — 시간은 전부 '남의 서버 사이 띄우기' 0.3초다.
"""
import csv
import json
import os
import sys
import time
import urllib.request

LIST_URL = "https://m.stock.naver.com/api/stocks/theme?page={page}&pageSize=100"
DETAIL_URL = "https://m.stock.naver.com/api/stocks/theme/{no}?page={page}&pageSize=100"
OUT_PATH = "data/themes.csv"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://stock.naver.com/"}
DELAY_SECONDS = 0.3          # 남의 서버다 - 순차로, 사이를 띄우고 받는다
MAX_PAGES = 20
PAGE_SIZE = 100


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))


def parse_themes(doc: dict) -> list[tuple[str, str]]:
    """목록 응답 -> [(테마번호, 테마명)]."""
    return [(str(g["no"]), str(g["name"]).strip()) for g in doc.get("groups") or [] if g.get("no") and g.get("name")]


def parse_stocks(doc: dict) -> list[tuple[str, str]]:
    """구성종목 응답 -> [(종목코드, 종목명)]. 6자리 코드만, 중복 없이."""
    seen, out = set(), []
    for s in doc.get("stocks") or []:
        code = str(s.get("itemCode") or "")
        if len(code) == 6 and code not in seen:
            seen.add(code)
            out.append((code, str(s.get("stockName") or "").strip()))
    return out


def fetch_stocks(no: str) -> list[tuple[str, str]]:
    """한 테마의 구성종목 전부 — 100개 넘는 테마면 다음 쪽까지(지금 가장 큰 테마는 70개 안팎)."""
    stocks: list[tuple[str, str]] = []
    for page in range(1, 6):
        part = parse_stocks(_get_json(DETAIL_URL.format(no=no, page=page)))
        stocks.extend(part)
        if len(part) < PAGE_SIZE:
            break
    return stocks


def collect() -> list[dict]:
    themes: list[tuple[str, str]] = []
    for page in range(1, MAX_PAGES + 1):
        try:
            found = parse_themes(_get_json(LIST_URL.format(page=page)))
        except urllib.error.HTTPError as e:         # 마지막 쪽 다음은 빈 목록이 아니라 404 가 온다
            if e.code == 404:
                break
            raise
        new = [t for t in found if t[0] not in {x[0] for x in themes}]
        print(f"  목록 {page}쪽: 테마 {len(new)}개", flush=True)
        themes.extend(new)
        if len(found) < PAGE_SIZE or not new:
            break
        time.sleep(DELAY_SECONDS)

    rows = []
    for i, (no, name) in enumerate(themes, 1):
        try:
            stocks = fetch_stocks(no)
        except Exception as e:                       # 한 테마가 깨져도 나머지는 건진다
            print(f"  [{i}/{len(themes)}] {name}: 실패 {type(e).__name__}", flush=True)
            continue
        rows.extend({"stock_code": c, "name": n, "theme": name,
                     "theme_no": no, "theme_size": len(stocks)} for c, n in stocks)
        if i % 25 == 0 or i == len(themes):
            print(f"  [{i}/{len(themes)}] {name} ({len(stocks)}종목) · 누적 {len(rows)}행", flush=True)
        time.sleep(DELAY_SECONDS)
    return rows


def main(out_path: str = OUT_PATH) -> None:
    print("네이버 테마 수집 시작")
    rows = collect()
    if not rows:
        sys.exit("수집된 행이 없다 - API 응답 구조가 바뀌었는지 확인 필요")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["stock_code", "name", "theme", "theme_no", "theme_size"])
        w.writeheader()
        w.writerows(rows)
    codes = {r["stock_code"] for r in rows}
    themes = {r["theme"] for r in rows}
    print(f"저장: {out_path} · {len(rows)}행 · 종목 {len(codes)}개 · 테마 {len(themes)}개")


def demo() -> None:
    """파싱만 자체검증 - 네트워크를 타지 않는다."""
    list_doc = {"groups": [{"no": 330, "name": " 화장품 "}, {"no": 178, "name": "해운"}, {"no": None, "name": "깨진 것"}]}
    assert parse_themes(list_doc) == [("330", "화장품"), ("178", "해운")], parse_themes(list_doc)
    detail_doc = {"stocks": [{"itemCode": "161890", "stockName": "한국콜마"}, {"itemCode": "161890", "stockName": "한국콜마"},
                             {"itemCode": "003350", "stockName": "한국화장품제조"}, {"itemCode": "KR7005930003", "stockName": "이상한 코드"}]}
    assert parse_stocks(detail_doc) == [("161890", "한국콜마"), ("003350", "한국화장품제조")], parse_stocks(detail_doc)
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main(next((a for a in sys.argv[1:] if not a.startswith("--")), OUT_PATH))
