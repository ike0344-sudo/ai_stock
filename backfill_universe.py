"""로컬에 이미 있는 전 종목의 일봉/1분봉을 증분 갱신한다.

    python backfill_universe.py              # 밀린 종목만 (기본)
    python backfill_universe.py --all        # 최신인 종목도 겹쳐받기
    python backfill_universe.py --limit=50   # 앞 50종목만 (시험용)

update-top35는 "오늘 기준 top35"만 받는다. 그래서 어제 top10이었지만 오늘은 아닌
종목이 계속 밀리고, 며칠 지나면 그날 데이터가 있는 종목이 수십 개로 줄어든다.
reach20_condition_scan은 데이터가 있는 종목끼리만 대금 순위를 매기므로, 빈 자리로
엉뚱한 종목이 top10에 들어간다(2026-07-20~08-11 구간에서 실제로 발생).

한 종목당 API 호출이 2~3회라 600종목이면 30분 이상 걸린다. 중간에 끊겨도 이미 받은
종목은 파일에 남으므로 다시 돌리면 이어서 진행된다(밀린 종목만 고르기 때문).
"""
import os
import sys
import time
from datetime import date, timedelta

import pandas as pd
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backtesting.updater import update_daily, update_minute
from kiwoom_client import KiwoomClient

DAILY_DIR = "data/stocks/daily"
MINUTE_DIR = "data/stocks/minute"
LOG = "backfill_universe.log"
OVERLAP_DAYS = 5


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def last_date(path: str) -> date | None:
    """파일 끝 한 줄만 읽어 마지막 날짜를 본다 - 600개를 통째로 파싱하면 느리다."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - 200))
            tail = f.read().decode("utf-8", errors="ignore").strip().splitlines()
        return pd.Timestamp(tail[-1][:10]).date()
    except Exception:
        return None


def stale_codes(target: date, force_all: bool) -> list[str]:
    codes = sorted(f[:-4] for f in os.listdir(MINUTE_DIR) if f.endswith(".csv"))
    if force_all:
        return codes
    return [c for c in codes
            if (last_date(os.path.join(MINUTE_DIR, f"{c}.csv")) or date(2000, 1, 1)) < target]


def main() -> None:
    load_dotenv()
    limit = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), None)
    # 오늘 장중이면 오늘치는 어차피 미완성이라 "전 거래일까지" 채워졌으면 최신으로 본다
    target = date.today() if time.localtime().tm_hour >= 16 else date.today() - timedelta(days=1)

    codes = stale_codes(target, "--all" in sys.argv)
    if limit:
        codes = codes[:limit]
    log("=" * 50)
    log(f"백필 시작: {len(codes)}종목 (기준일 {target})")
    if not codes:
        log("밀린 종목 없음")
        return

    client = KiwoomClient(os.environ["KIWOOM_APPKEY"], os.environ["KIWOOM_SECRETKEY"],
                          is_mock=os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true")
    ok = fail = 0
    started = time.time()
    for i, code in enumerate(codes, 1):
        try:
            update_daily(client, code, os.path.join(DAILY_DIR, f"{code}.csv"),
                         overlap_days=OVERLAP_DAYS)
            m = update_minute(client, code, os.path.join(MINUTE_DIR, f"{code}.csv"),
                              overlap_days=OVERLAP_DAYS)
            ok += 1
            if i % 25 == 0 or i == len(codes):
                rate = (time.time() - started) / i
                log(f"[{i}/{len(codes)}] {code} ~{m.index.max():%m-%d} "
                    f"| 성공 {ok} 실패 {fail} | 남은 {int(rate*(len(codes)-i)/60)}분")
        except Exception as e:
            fail += 1
            log(f"[{i}/{len(codes)}] {code} 실패: {str(e)[:120]}")

    log(f"백필 완료: 성공 {ok} 실패 {fail} ({(time.time()-started)/60:.1f}분)")


def demo() -> None:
    """last_date가 파일 끝에서 날짜를 제대로 뽑는지 - 여기가 틀리면 전 종목을 다시 받는다."""
    p = "state/_backfill_demo.csv"
    os.makedirs("state", exist_ok=True)
    open(p, "w", encoding="utf-8").write(
        "date,open,high,low,close,volume\n"
        "2026-08-10 09:00:00,1,1,1,1,1\n2026-08-11 15:30:00,1,1,1,1,1\n")
    assert last_date(p) == date(2026, 8, 11), last_date(p)
    os.remove(p)
    assert last_date("없는파일.csv") is None
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
