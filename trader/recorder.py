"""호가·체결 원본 수집기 — 매매 데스크와 따로 도는 프로세스(11-02 사용자 "데스크 수정해야 할 때 못 하는 게 문제").

데스크를 다시 켜도 수집이 안 끊긴다. 받는 것·파일은 trader/rec.py 그대로(data/stocks/live_al/{code}/{date}.jsonl.gz).
종목 = 고른 종목(state/trader/watch.json) + 살아 있는 예약 + 신고대금(1000억 이상) 다음 10거래일 — 1분마다 다시 읽는다.
앱키는 데스크와 같은 것(TRADER_APPKEY, 없으면 배치 키). 주문체결(00)은 구독 안 한다(데스크 몫).
수집기가 잠금을 잡고 쓰는 동안 state/trader/rec_alive 를 2초마다 건드리고, 데스크는 그동안 저장을 넘긴다 — 수집기가 죽으면 데스크가 15초 안에 이어 쓴다.
실행: python -m trader.recorder
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime

from dotenv import load_dotenv

from . import feed, rec

STATE = rec.ROOT / "state" / "trader"


def _read(name: str, default):
    try:
        return json.loads((STATE / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def codes() -> list[str]:
    plans = [p["code"] for p in _read("plans.json", []) if p.get("active")]
    return sorted(set(_read("watch.json", [])) | set(plans) | set(rec.today_codes()))


def main() -> None:
    load_dotenv(rec.ROOT / ".env")
    from datahub.calendar import Calendar
    from kiwoom_client import KiwoomClient
    key, sec = os.environ.get("TRADER_APPKEY", "").strip(), os.environ.get("TRADER_SECRETKEY", "").strip()
    mock = os.environ.get("TRADER_IS_MOCK", "1").strip() != "0"
    if not (key and sec):                                            # 데스크와 같게 — 매매 키 받기 전엔 배치 키(desk.Desk.__init__)
        key, sec = os.environ.get("KIWOOM_BATCH_APPKEY", "").strip(), os.environ.get("KIWOOM_BATCH_SECRETKEY", "").strip()
        mock = os.environ.get("KIWOOM_IS_MOCK", "true").strip().lower() in ("1", "true", "yes")
    cal, td = Calendar(), {}

    def is_active(now: datetime) -> bool:
        d = now.date()
        if d not in td:
            td.clear()
            td[d] = cal.is_trading_day(d)
        return td[d] and (7 * 60 + 50) <= now.hour * 60 + now.minute < 20 * 60 + 5

    rec.OWNER, feed.ORDERS = True, False
    cs = codes()
    rec.codes = set(cs)
    feed.set_codes(cs)
    feed.start(KiwoomClient(key, sec, is_mock=mock), is_active, None)
    rec.start(is_active)
    print(f"{datetime.now():%H:%M:%S} 수집기 시작 · {len(cs)}종목", flush=True)
    while True:
        time.sleep(60)
        try:
            cs = codes()
            rec.codes = set(cs)
            feed.set_codes(cs)
        except Exception as e:                                       # noqa: BLE001 — 목록 못 읽으면 앞 목록 그대로
            print(f"{datetime.now():%H:%M:%S} 종목 목록 오류: {e}", flush=True)
        st = feed.status()
        print(f"{datetime.now():%H:%M:%S} 연결 {st['connected']} · {st['codes']}종목 · 저장 {rec.stat['rows']}줄 · 잠금 {bool(rec.stat.get('in'))}"
              + (f" · 오류 {st['err'] or rec.stat['err']}" if st["err"] or rec.stat["err"] else ""), flush=True)


if __name__ == "__main__":
    main()
