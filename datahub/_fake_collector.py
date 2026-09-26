"""가짜 수집기 — `STUDIO_FAKE_COLLECTORS=1` 일 때 `datahub.jobs` 가 실제 수집기 대신 돌린다(테스트·시연, API 호출 없음).

    python -m datahub._fake_collector daily|ticks|compact|minute [실제 수집기와 같은 인자]

진짜와 같이 `datahub.write` 관문 안에서 돌아 잠금·장부·진행 기록이 그대로 남는다.
체결(`ticks`)은 [start, end] 거래일 × 종목 목록으로 빈 csv 를 만든다 — 상태 재계산이 "수집됨"으로 보게.
시험용 조절(환경변수): `FAKE_TICK_DEFER=n` 뒤쪽 n종목을 --stop-at 으로 미룬 것처럼, `FAKE_TICK_FAIL=A,B` 이 종목은 못 받은 것처럼,
`FAKE_SLEEP=초` 관문 안에서 머무는 시간.
"""
import argparse
import os
import sys
import time
from datetime import date

from . import catalog
from .calendar import Calendar
from .gate import write


def _codes(spec: str) -> list[str]:
    if spec.startswith("@"):
        return [ln.split("#")[0].strip() for ln in open(spec[1:], encoding="utf-8-sig") if ln.split("#")[0].strip()]
    return [c for c in spec.split(",") if c]


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("kind")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--codes", default="")
    ap.add_argument("--stop-at")
    ap.add_argument("--concurrency")
    ap.add_argument("--batch-key", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--tick-dir")
    ap.add_argument("--main-progress")
    a, rest = ap.parse_known_args(argv)
    for r in rest:                                   # --codes=A,B 형태(daily)
        if r.startswith("--codes="):
            a.codes = r.split("=", 1)[1]
    sleep = float(os.environ.get("FAKE_SLEEP", "0"))
    if a.kind == "compact":
        print("압축 없음(가짜)")
        return 0
    lock = {"daily": "daily_minute", "ticks": "tick_al", "minute": "minute_al"}[a.kind]
    codes = _codes(a.codes) if a.codes else []
    with write(lock, writer=f"fake_{a.kind}", detail={"codes": len(codes)}) as w:
        if a.kind == "ticks":
            defer = int(os.environ.get("FAKE_TICK_DEFER", "0"))
            fail = {c for c in os.environ.get("FAKE_TICK_FAIL", "").split(",") if c}
            done_codes = codes[: len(codes) - defer] if defer else codes
            days = Calendar().trading_days(date.fromisoformat(a.start), date.fromisoformat(a.end))
            for i, c in enumerate(done_codes, 1):
                if c not in fail:
                    for d in days:
                        p = catalog.path("tick_al", code=c, date=d.isoformat()).with_suffix(".csv")
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_text("time,cur_prc,trde_qty,pred_pre_sig\n", encoding="utf-8")
                w.progress(i, len(codes))
            if defer:
                print(f"--stop-at {a.stop_at} 도달 — {defer}종목은 미룸(done 에 안 넣음, 다음 회차가 이어받음)", flush=True)
        else:
            for i in range(1, 4):
                w.progress(i, 3)
        time.sleep(sleep)
    print("완료(가짜)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
