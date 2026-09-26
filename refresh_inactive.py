"""거래 중단(거래정지·상장폐지) 종목 목록을 키움 종목정보(ka10099)로 다시 쓴다 — 주 1회.

    python refresh_inactive.py

후보 = 일봉·분봉이 기준일(최빈 최신일)보다 밀린 종목. 그중 종목정보 목록에 없으면 상장폐지, state/auditInfo 에
'거래정지'가 있으면 거래정지. `state/datahub/inactive_codes.json` 을 통째로 쓴다(정지가 풀린 종목은 빠진다).
목록이 8일 넘게 안 갱신되면 허브는 이 목록을 믿지 않는다(`status.inactive_codes`).
API 호출은 종목정보 2번(코스피·코스닥)뿐이다. 데이터 파일은 안 건드린다.
"""
import os
import sys
from collections import Counter
from datetime import date

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from datahub import status
from kiwoom_client import KiwoomClient, batch_keys


def main() -> None:
    load_dotenv()
    client = KiwoomClient(*batch_keys(), is_mock=os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true")
    stock_list = {}
    for market in ("0", "10"):
        for r in client.get_stock_list(market):
            stock_list[r["code"]] = r
    if len(stock_list) < 3000:
        raise SystemExit(f"종목정보가 너무 적다({len(stock_list)}) — 목록을 쓰지 않는다")
    late: set[str] = set()
    for ds in ("daily", "minute_krx"):
        dates = status.latest_dates(ds)
        ref = Counter(dates.values()).most_common(1)[0][0]
        late |= {c for c, d in dates.items() if d < ref}
    codes = status.write_inactive(stock_list, sorted(late), date.today())
    print(f"후보 {len(late)}종목 → 거래 중단 {len(codes)} ({dict(Counter(v['reason'] for v in codes.values()))})")


if __name__ == "__main__":
    main()
