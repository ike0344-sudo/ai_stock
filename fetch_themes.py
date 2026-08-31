"""네이버 금융 테마 -> 종목 매핑을 data/themes.csv로 수집한다.

    python fetch_themes.py            # 전체 수집(테마 목록 -> 테마별 구성종목)
    python fetch_themes.py --demo     # 파싱 자체검증(네트워크 없음)

키움 ka10099의 upName은 KRX 표준 대분류라 "화학"까지만 내려간다 - 한국콜마가
화장품이라는 정보가 없다. 네이버 테마는 장세 테마(화장품, 로봇, 전선)라 결이 맞다.

종목:테마는 1:N이다. 랭킹 표에는 대표 하나만 쓰므로 theme_size(그 테마의 구성종목
수)를 같이 저장해둔다 - 작은 테마일수록 구체적이라 대표로 뽑는다("화장품" 10종목 vs
"중국_소비재 확대" 12종목이면 앞쪽). 뽑는 규칙 자체는 쓰는 쪽(trading_value_ranking)에
있고 이 파일은 원본을 그대로 담는다.
"""
import csv
import os
import re
import sys
import time
import urllib.request

LIST_URL = "https://finance.naver.com/sise/theme.naver?&page={page}"
DETAIL_URL = "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no={no}"
OUT_PATH = "data/themes.csv"
HEADERS = {"User-Agent": "Mozilla/5.0"}
DELAY_SECONDS = 0.3          # 남의 서버다 - 순차로, 사이를 띄우고 받는다
MAX_PAGES = 20

THEME_RE = re.compile(r'/sise/sise_group_detail\.naver\?type=theme&no=(\d+)"[^>]*>([^<]+)<')
STOCK_RE = re.compile(r'/item/main\.naver\?code=(\d{6})"[^>]*>([^<]+)<')


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(req, timeout=20).read().decode("euc-kr", "replace")


def parse_themes(html: str) -> list[tuple[str, str]]:
    """테마 목록 페이지 -> [(테마번호, 테마명)]. 같은 테마가 두 번 걸리는 링크가 있어 중복을 없앤다."""
    seen, out = set(), []
    for no, name in THEME_RE.findall(html):
        if no not in seen:
            seen.add(no)
            out.append((no, name.strip()))
    return out


def parse_stocks(html: str) -> list[tuple[str, str]]:
    """테마 상세 페이지 -> [(종목코드, 종목명)]."""
    seen, out = set(), []
    for code, name in STOCK_RE.findall(html):
        if code not in seen:
            seen.add(code)
            out.append((code, name.strip()))
    return out


def collect() -> list[dict]:
    themes: list[tuple[str, str]] = []
    for page in range(1, MAX_PAGES + 1):
        found = parse_themes(_get(LIST_URL.format(page=page)))
        new = [t for t in found if t[0] not in {x[0] for x in themes}]
        print(f"  목록 {page}쪽: 테마 {len(new)}개", flush=True)
        if not new:
            break
        themes.extend(new)
        time.sleep(DELAY_SECONDS)

    rows = []
    for i, (no, name) in enumerate(themes, 1):
        try:
            stocks = parse_stocks(_get(DETAIL_URL.format(no=no)))
        except Exception as e:                       # 한 테마가 깨져도 나머지는 건진다
            print(f"  [{i}/{len(themes)}] {name}: 실패 {type(e).__name__}", flush=True)
            continue
        rows.extend({"stock_code": c, "name": n, "theme": name,
                     "theme_no": no, "theme_size": len(stocks)} for c, n in stocks)
        if i % 25 == 0 or i == len(themes):
            print(f"  [{i}/{len(themes)}] {name} ({len(stocks)}종목) · 누적 {len(rows)}행", flush=True)
        time.sleep(DELAY_SECONDS)
    return rows


def main() -> None:
    print("네이버 테마 수집 시작")
    rows = collect()
    if not rows:
        sys.exit("수집된 행이 없다 - 페이지 구조가 바뀌었는지 확인 필요")
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["stock_code", "name", "theme", "theme_no", "theme_size"])
        w.writeheader()
        w.writerows(rows)
    codes = {r["stock_code"] for r in rows}
    themes = {r["theme"] for r in rows}
    print(f"저장: {OUT_PATH} · {len(rows)}행 · 종목 {len(codes)}개 · 테마 {len(themes)}개")


def demo() -> None:
    """파싱만 자체검증 - 네트워크를 타지 않는다."""
    list_html = ('<a href="/sise/sise_group_detail.naver?type=theme&no=330">화장품</a>'
                 '<a href="/sise/sise_group_detail.naver?type=theme&no=330">화장품</a>'
                 '<a href="/sise/sise_group_detail.naver?type=theme&no=178">해운</a>')
    assert parse_themes(list_html) == [("330", "화장품"), ("178", "해운")], parse_themes(list_html)
    detail_html = ('<a href="/item/main.naver?code=161890">한국콜마</a>'
                   '<a href="/item/main.naver?code=161890">한국콜마</a>'
                   '<a href="/item/main.naver?code=003350">한국화장품제조</a>')
    assert parse_stocks(detail_html) == [("161890", "한국콜마"), ("003350", "한국화장품제조")]
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
