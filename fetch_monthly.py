"""전 종목 월봉을 받아 캐시한다 — 역사적(상장 이후) 신고가 판정용.

    python fetch_monthly.py                # 아직 없는 종목만
    python fetch_monthly.py --all          # 전부 다시
    python fetch_monthly.py --codes 005930,000660

일봉 캐시는 대부분 2024-02 부터라 2.5년치뿐이다. "완전 신고가"(상장 이후 최고가)는
그걸로 판정할 수 없다. 월봉은 1페이지가 240행=20년이라 종목당 1~2번만 부르면 된다 —
같은 기간을 일봉으로 받으면 종목당 10페이지라 전 종목이면 몇 시간이 걸린다.

수정주가(upd_stkpc_tp="1")로 받으므로 액면분할 전 고가와 지금 가격을 그대로 비교할 수 있다.
"""
import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "stocks" / "monthly"
SRC = ROOT / "data" / "stocks" / "daily"       # 대상 종목은 일봉 캐시 기준


def _client():
    from dotenv import load_dotenv
    from kiwoom_client import KiwoomClient

    load_dotenv(ROOT / ".env")
    key, secret = os.environ.get("KIWOOM_APPKEY"), os.environ.get("KIWOOM_SECRETKEY")
    if not key or not secret:
        raise SystemExit("KIWOOM_APPKEY / KIWOOM_SECRETKEY 가 .env에 없습니다")
    return KiwoomClient(key, secret,
                        is_mock=os.environ.get("KIWOOM_IS_MOCK", "false").lower() == "true")


def fetch(client, code: str, max_pages: int) -> pd.DataFrame | None:
    from fetch_chart import find_records

    rows = []
    for page in client.get_monthly_chart_pages(code, max_pages=max_pages):
        for r in find_records(page):
            try:
                rows.append({
                    "date": datetime.strptime(str(r["dt"]).strip()[:8], "%Y%m%d"),
                    # 가격 필드의 +/- 는 방향 표시라 abs() 로 벗긴다 (키움 관례)
                    "open": abs(int(r["open_pric"])), "high": abs(int(r["high_pric"])),
                    "low": abs(int(r["low_pric"])), "close": abs(int(r["cur_prc"])),
                    "volume": int(r["trde_qty"]),
                    # 월봉은 거래대금을 그대로 준다 — 종가×거래량으로 근사할 필요가 없다
                    "value": int(r.get("trde_prica", 0) or 0),
                })
            except (KeyError, ValueError):
                continue
    if not rows:
        return None
    return pd.DataFrame(rows).drop_duplicates("date").set_index("date").sort_index()


def main() -> None:
    ap = argparse.ArgumentParser(description="전 종목 월봉 수집")
    ap.add_argument("--all", action="store_true", help="이미 받은 종목도 다시 받는다")
    ap.add_argument("--codes", default="", help="쉼표로 구분한 종목코드만")
    ap.add_argument("--max-pages", type=int, default=2, help="1페이지 = 240행 = 20년")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    codes = ([c.strip() for c in args.codes.split(",") if c.strip()]
             or sorted(p.stem for p in SRC.glob("*.csv")))
    if not args.all and not args.codes:
        codes = [c for c in codes if not (OUT / f"{c}.csv").is_file()]
    if args.limit:
        codes = codes[:args.limit]
    if not codes:
        print("받을 종목이 없습니다 (--all 로 전부 다시)")
        return

    client = _client()
    print(f"{len(codes)}종목 · 종목당 최대 {args.max_pages}페이지 "
          f"(예상 {len(codes)*args.max_pages*1.1/60:.0f}분)", flush=True)
    ok = fail = 0
    t0 = time.monotonic()
    for i, code in enumerate(codes, 1):
        try:
            df = fetch(client, code, args.max_pages)
        except Exception as e:                     # 한 종목 실패로 전체를 멈추지 않는다
            print(f"  [{i}/{len(codes)}] {code} 실패 — {type(e).__name__}: {str(e)[:80]}", flush=True)
            fail += 1
            continue
        if df is None or df.empty:
            fail += 1
            continue
        df.to_csv(OUT / f"{code}.csv")
        ok += 1
        if i % 50 == 0:
            el = time.monotonic() - t0
            print(f"  [{i}/{len(codes)}] {ok}개 저장 · {el/60:.1f}분 경과 "
                  f"· 남은 예상 {el/i*(len(codes)-i)/60:.0f}분", flush=True)
    print(f"완료: {ok}종목 저장, 실패 {fail} · {(time.monotonic()-t0)/60:.1f}분")


if __name__ == "__main__":
    main()
