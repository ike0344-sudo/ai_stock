"""인포스탁 특징테마 뉴스 수집 — 매일경제 톡속보 목록 맨 위 글을 받아 data/news/infostock/{날짜}.json 에 넣는다.

    python scripts/collect_infostock_news.py --session am     # 오전장 글이어야 저장. 아직 아니면 종료코드 2
    python scripts/collect_infostock_news.py --session pm
    python scripts/collect_infostock_news.py                  # 최신 글이 오늘 것이면 세션 상관없이 저장

허브 일정(news_am 11:35 · news_pm 14:55)이 돌린다. 2 는 "아직 안 올라옴"이라 허브가 10분 뒤 다시 시도한다.
글 보기 페이지는 로그인 벽이라 **그날 못 받으면 영영 없다** — 재시도가 중요하다.
파싱은 kospi-theme-engine/app/ingest/infostock_news.py 하나를 쓴다(소피증권 화면과 같은 읽기).
저장은 데이터 허브 쓰기 관문(gate.write) 안에서만.
"""
import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
KTE = ROOT / "kospi-theme-engine"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(KTE))
from datahub import catalog, gate  # noqa: E402

from app.ingest import infostock_news as nw  # noqa: E402

SEOUL = ZoneInfo("Asia/Seoul")


def _names() -> "tuple[list[str], dict[str, str]]":
    ref = KTE / "data" / "reference"
    themes = {r["theme"] for r in csv.DictReader(open(ref / "themes.csv", encoding="utf-8-sig"))}
    codes = {r["name"]: r["code"] for r in csv.DictReader(open(ref / "universe.csv", encoding="utf-8-sig"))}
    # 원본(대형주 포함) 테마 이름도 — 뉴스는 대형주 테마명을 그대로 쓴다
    src = ROOT / "data" / "themes.csv"
    if src.exists():
        themes |= {r["theme"] for r in csv.DictReader(open(src, encoding="utf-8-sig"))}
    return sorted(themes), codes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", choices=["am", "pm"], default="")
    ap.add_argument("--allow-past", action="store_true", help="최신 글이 오늘 것이 아니어도 그 날짜 파일에 저장(첫 수집·점검용)")
    a = ap.parse_args()
    today = datetime.now(SEOUL).strftime("%Y-%m-%d")
    got = nw.fetch_latest()
    if got is None:
        print("목록을 못 읽었다", flush=True)
        return 1
    themes, codes = _names()
    art = nw.parse_article(*got, theme_names=themes, stock_codes=codes)
    print(f"최신 글 {art.post_id} {art.title} · 게시 {art.posted} · 세션 {art.session or '?'}", flush=True)
    if (art.date != today and not a.allow_past) or (a.session and art.session != a.session):
        print(f"아직 {a.session or '오늘'} 글이 아니다 — 나중에 다시", flush=True)
        return 2
    path = Path(str(catalog.path("infostock_news", date=art.date)))
    with gate.write("infostock_news", writer="infostock_collect",
                    detail={"day": art.date, "session": art.session, "post": art.post_id}):
        nw.merge_into(path, art)
    unknown = [t for t in art.strong + art.weak + [t for b in art.blocks for t in b.themes] if t.startswith("?")]
    print(f"저장 {path.name} [{art.session}] 강세 {len(art.strong)} · 약세 {len(art.weak)} · 특징 테마 {len(art.blocks)}블록 "
          f"· 특징주 {len(art.features)} · 모르는 테마 이름 {len(unknown)}{': ' + ', '.join(unknown[:5]) if unknown else ''}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
