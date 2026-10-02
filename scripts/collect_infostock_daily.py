"""인포스탁 "데일리 테마"(장 마감 뒤 16:59쯤 올라오는 그날 특징 테마 글) 수집 → data/news/infostock_daily/{날짜}.json

    python scripts/collect_infostock_daily.py                 # 최신 글들 중 아직 없는 날짜 저장. 오늘 글이 아직 없으면 종료코드 2
    python scripts/collect_infostock_daily.py --since 2026-05-08   # 그 날짜까지 거슬러 백필(이미 있는 날짜는 건너뜀)
    python scripts/collect_infostock_daily.py --all                # API 가 주는 끝까지 백필

출처: 사용자가 알려준 https://infostock.co.kr/Theme/DailyFeaturedTheme 가 쓰는 공개 API(kospi-theme-engine/app/ingest/infostock_daily.py).
허브 일정 news_daily(거래일 17:30, 10분 뒤 재시도 5번)가 돌린다. 저장은 허브 쓰기 관문 안에서만. 원문(content)도 함께 남긴다 —
파서가 좋아지면 다시 읽을 수 있게(소피증권 데이터는 지우지 않는다).
"""
import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
KTE = ROOT / "kospi-theme-engine"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(KTE))
from datahub import catalog, gate  # noqa: E402

from app.ingest import infostock_daily as idl  # noqa: E402

SEOUL = ZoneInfo("Asia/Seoul")


def _names() -> "tuple[list[str], dict[str, str]]":
    ref = KTE / "data" / "reference"
    themes = {r["theme"] for r in csv.DictReader(open(ref / "themes.csv", encoding="utf-8-sig"))}
    codes = {r["name"]: r["code"] for r in csv.DictReader(open(ref / "universe.csv", encoding="utf-8-sig"))}
    src = ROOT / "data" / "themes.csv"
    if src.exists():
        themes |= {r["theme"] for r in csv.DictReader(open(src, encoding="utf-8-sig"))}
    return sorted(themes), codes


def _save(items: list, themes, codes, force: bool = False) -> "list[str]":
    saved = []
    for it in items:
        d = idl.parse_item(it, themes, codes)
        path = Path(str(catalog.path("infostock_daily_theme", date=d.date)))
        if path.exists() and not force:
            continue
        doc = d.to_dict()
        doc["raw"] = {"id": it.get("id"), "sendDate": it.get("sendDate"), "sendTime": it.get("sendTime"),
                      "title": it.get("title"), "content": it.get("content")}
        with gate.write("infostock_daily_theme", writer="infostock_daily_collect", detail={"day": d.date, "post": d.post_id}):
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(path)
        unk = [t for s in d.sections for t in s.themes if t.startswith("?") and t != "?표"]
        print(f"저장 {path.name} · 구역 {len(d.sections)} · 서술 종목 {sum(len(s.stocks) for s in d.sections)} · 표 {sum(len(s.table) for s in d.sections)}행"
              f"{' · 모르는 묶음 ' + ', '.join(unk) if unk else ''}", flush=True)
        saved.append(d.date)
    return saved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="", help="이 날짜(YYYY-MM-DD)까지 거슬러 백필")
    ap.add_argument("--all", action="store_true", help="API 끝까지 백필")
    ap.add_argument("--force", action="store_true", help="이미 있는 날짜도 다시 저장")
    a = ap.parse_args()
    themes, codes = _names()
    if a.all or a.since:
        since = a.since or "1900-01-01"
        items = idl.fetch_back_to(since, max_pages=200 if a.all else 40)
        print(f"받은 글 {len(items)}개 ({min(i['sendDate'] for i in items)}~{max(i['sendDate'] for i in items)})" if items else "받은 글 없음", flush=True)
        saved = _save(items, themes, codes, a.force)
        print(f"새로 저장 {len(saved)}일", flush=True)
        return 0
    today = datetime.now(SEOUL).strftime("%Y%m%d")
    items, _ = idl.fetch_page(5)
    latest = max((i["sendDate"] for i in items), default="")
    print(f"최신 글 {latest} (오늘 {today})", flush=True)
    saved = _save(items, themes, codes, a.force)
    if latest < today and Path(str(catalog.path("infostock_daily_theme", date=f"{today[:4]}-{today[4:6]}-{today[6:]}"))).exists() is False:
        print("오늘 글이 아직 없다 — 나중에 다시", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
