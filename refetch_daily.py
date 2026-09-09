"""일봉을 수정주가 기준으로 **통째로 다시 받는다** — 액면분할/병합 이음매 제거용.

    python refetch_daily.py              # 전 종목
    python refetch_daily.py --codes 001210,196170

기존 캐시는 분할/병합 전 구간이 조정되지 않은 채 남아 있다(금호전기 7/9 에서 5배
이음매가 확인됐다). 그 상태로 N일 신고가를 재면 창 안에 기준이 다른 가격이 섞여
판정이 통째로 틀린다.

**병합하지 않고 덮어쓴다.** 옛 행을 남기면 조정된 새 행과 기준이 섞여 같은 문제가
그대로 남는다. 다만 새로 받은 이력이 기존보다 **짧으면 건너뛴다** — 과거를 잃는 쪽이
이음매보다 나쁘다.
"""
import argparse
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent
DAILY = ROOT / "data" / "stocks" / "daily"


def _client():
    from dotenv import load_dotenv
    from kiwoom_client import KiwoomClient, batch_keys

    load_dotenv(ROOT / ".env")
    key, secret = batch_keys()
    if not key or not secret:
        raise SystemExit("KIWOOM_APPKEY / KIWOOM_SECRETKEY 가 .env에 없습니다")
    return KiwoomClient(key, secret,
                        is_mock=os.environ.get("KIWOOM_IS_MOCK", "false").lower() == "true")


def fetch(client, code: str, max_pages: int) -> pd.DataFrame | None:
    from fetch_chart import find_records

    rows = []
    for page in client.get_daily_chart_pages(code, max_pages=max_pages):
        for r in find_records(page):
            try:
                rows.append({
                    "date": datetime.strptime(str(r["dt"]).strip()[:8], "%Y%m%d"),
                    # 가격의 +/- 는 방향 표시라 abs() 로 벗긴다 (키움 관례)
                    "open": abs(int(r["open_pric"])), "high": abs(int(r["high_pric"])),
                    "low": abs(int(r["low_pric"])), "close": abs(int(r["cur_prc"])),
                    "volume": int(r["trde_qty"]),
                })
            except (KeyError, ValueError):
                continue
    if not rows:
        return None
    return pd.DataFrame(rows).drop_duplicates("date").set_index("date").sort_index()


def main() -> None:
    ap = argparse.ArgumentParser(description="일봉 수정주가 재수집")
    ap.add_argument("--codes", default="")
    ap.add_argument("--max-pages", type=int, default=3, help="1페이지 ≈ 600행")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args()

    codes = ([c.strip() for c in args.codes.split(",") if c.strip()]
             or sorted(p.stem for p in DAILY.glob("*.csv")))
    if args.limit:
        codes = codes[:args.limit]

    if not args.no_backup and not args.codes:
        bak = DAILY.parent / f"daily_backup_{datetime.now():%Y%m%d_%H%M}"
        if not bak.exists():
            print(f"백업 {bak.name} …", flush=True)
            shutil.copytree(DAILY, bak)

    client = _client()
    print(f"{len(codes)}종목 · 종목당 최대 {args.max_pages}페이지 "
          f"(예상 {len(codes)*args.max_pages*1.1/60:.0f}분)", flush=True)
    ok = short = fail = 0
    shorts = []
    t0 = time.monotonic()
    for i, code in enumerate(codes, 1):
        path = DAILY / f"{code}.csv"
        try:
            old = len(pd.read_csv(path)) if path.is_file() else 0
        except (OSError, ValueError):
            old = 0
        try:
            df = fetch(client, code, args.max_pages)
        except Exception as e:
            print(f"  [{i}] {code} 실패 — {type(e).__name__}: {str(e)[:70]}", flush=True)
            fail += 1
            continue
        if df is None or df.empty:
            fail += 1
            continue
        if len(df) < old:
            short += 1
            shorts.append((code, old, len(df)))
            continue                       # 과거를 잃느니 이음매를 남긴다
        df.to_csv(path)
        ok += 1
        if i % 100 == 0:
            el = time.monotonic() - t0
            print(f"  [{i}/{len(codes)}] 교체 {ok} · {el/60:.1f}분 경과 "
                  f"· 남은 예상 {el/i*(len(codes)-i)/60:.0f}분", flush=True)
    print(f"완료: 교체 {ok} · 이력이 짧아 건너뜀 {short} · 실패 {fail} "
          f"· {(time.monotonic()-t0)/60:.1f}분")
    for c, o, n in shorts[:20]:
        print(f"  건너뜀 {c}: 기존 {o}행 > 새로 {n}행")


if __name__ == "__main__":
    main()
