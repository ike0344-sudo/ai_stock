"""로컬에 이미 있는 전 종목의 일봉/1분봉을 증분 갱신한다.

    python backfill_universe.py              # 밀린 종목만 (기본)
    python backfill_universe.py --all        # 최신인 종목도 겹쳐받기
    python backfill_universe.py --limit=50   # 앞 50종목만 (시험용)
    python backfill_universe.py --codes=A,B  # 이 종목들만 (--codes @파일 = 줄마다 종목코드)
    python backfill_universe.py --stop-at 08:10   # 그 시각(지금 이후 처음 오는)이 지나면 새 종목을 시작하지 않고 정상 종료

update-top35는 "오늘 기준 top35"만 받는다. 그래서 어제 top10이었지만 오늘은 아닌
종목이 계속 밀리고, 며칠 지나면 그날 데이터가 있는 종목이 수십 개로 줄어든다.
reach20_condition_scan은 데이터가 있는 종목끼리만 대금 순위를 매기므로, 빈 자리로
엉뚱한 종목이 top10에 들어간다(2026-07-20~08-11 구간에서 실제로 발생).

## 소피증권 유니버스를 같이 본다

밀린 종목을 **분봉 폴더**로 골랐더니, 분봉이 없는 종목은 일봉도 영영 안 받았다 —
9/2 남화토건이 8/21 일봉으로 판정돼 10일 신고가에 별표가 안 떴다(6종목이 12일째).
소피증권이 신고가·전일종가를 재는 종목(universe.csv)은 일봉이 밀리면 화면이 곧장
틀리므로, 분봉 목록과 합쳐서 고른다.

## 일봉 폴더 전체를 본다 (2026-09-25)

풀에 **일봉 폴더**도 넣었다. 분봉 폴더 ∪ 소피증권 유니버스만 보면 일봉만 있는 종목 367개(08-31 에
한 번 받고 방치된 종목들)를 아무 경로도 갱신하지 않는다 — "로컬에 있는 전 종목"이라는 이 스크립트의
목적에서 벗어난 결함이었다. 대신 `state/datahub/inactive_codes.json`(거래정지·상장폐지)은 뺀다 —
받을 수 없는 종목을 매번 다시 두드려 봐야 시간만 쓴다.

## 기준일은 거래일 달력으로

"밀림"의 기준일은 `datahub.calendar` 의 **마감이 확정된 가장 최근 거래일**(거래일 16시 이후면 오늘,
아니면 직전 거래일)이다. 예전엔 달력일 `오늘-1` 이라 월요일 아침·휴장일에 이미 최신인 2,210종목을
전부 밀림으로 보고 3시간 넘게 헛돌았다(2026-09-25 추석 휴장일, 새 데이터 0).

## 증분이 안 되면 통째로 다시 받는다

거래정지 등으로 load_history 가 최근 구간을 아예 안 주는 종목이 있다(아이티켐은
4/2 이후가 안 나온다). 증분 뒤에도 날짜가 그대로면 refetch_daily 의 전체 재수집으로
한 번 더 시도한다 — 그쪽 엔드포인트는 그 구간을 준다.

## 쓰기 관문
공유 데이터(일봉·분봉 CSV)를 쓰므로 `datahub.write("daily_minute")` 안에서 돈다 — 다른 쓰기 작업과
겹치지 않고, 장부(state/datahub)에 남는다. 밀린 종목 판정도 잠금을 잡은 뒤에 한다(기다린 사이
다른 작업이 이미 받아 뒀을 수 있다).

한 종목당 API 호출이 2~3회라 600종목이면 30분 이상 걸린다. 중간에 끊겨도 이미 받은
종목은 파일에 남으므로 다시 돌리면 이어서 진행된다(밀린 종목만 고르기 때문).
"""
import csv
import os
import shutil
import sys
import time
from datetime import date, datetime, timedelta

import pandas as pd
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backtesting.updater import update_daily, update_minute
from datahub import write
from datahub.calendar import Calendar
from datahub.locks import deadline_from
from datahub.status import inactive_codes
from kiwoom_client import KiwoomClient, batch_keys

DAILY_DIR = "data/stocks/daily"
MINUTE_DIR = "data/stocks/minute"
LOG = "backfill_universe.log"
OVERLAP_DAYS = 5
# 소피증권이 판정에 쓰는 종목 목록. 돌아가는 앱(dist) 것을 먼저 본다.
UNIVERSE_CSV = ("kospi-theme-engine/dist/data/reference/universe.csv",
                "kospi-theme-engine/data/reference/universe.csv")


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


def universe_codes() -> set[str]:
    """소피증권이 신고가·전일종가를 재는 종목. 없으면 빈 집합(그 앱을 안 쓰는 PC)."""
    for rel in UNIVERSE_CSV:
        if os.path.exists(rel):
            with open(rel, encoding="utf-8-sig", newline="") as fh:
                return {r["code"] for r in csv.DictReader(fh) if r.get("code")}
    return set()


def settled_target(now: datetime | None = None) -> date:
    """밀림 판정 기준일 — 마감이 확정된 가장 최근 거래일(달력일 오늘-1 이 아니다)."""
    return Calendar().settled_day(now or datetime.now())


def stale_codes(target: date, force_all: bool) -> tuple[list[str], set[str]]:
    """(받을 종목, 그중 일봉이 밀린 종목).

    풀 = 분봉 폴더 ∪ 소피증권 유니버스 ∪ 일봉 폴더 − 거래 중단(inactive_codes.json).
    분봉은 있는 파일만 갱신한다 — 없는 종목까지 받으면 2.6GB 캐시가 통째로 늘어난다.
    일봉은 소피증권 유니버스와 일봉 폴더 전체를 챙긴다.
    """
    minute = sorted(f[:-4] for f in os.listdir(MINUTE_DIR) if f.endswith(".csv"))
    daily = [f[:-4] for f in os.listdir(DAILY_DIR) if f.endswith(".csv")] if os.path.isdir(DAILY_DIR) else []
    dead = set(inactive_codes())
    pool = sorted((set(minute) | universe_codes() | set(daily)) - dead)
    minute = [c for c in minute if c not in dead]
    if force_all:
        return pool, set(pool)
    def old(d: str, c: str) -> bool:
        return (last_date(os.path.join(d, f"{c}.csv")) or date(2000, 1, 1)) < target
    daily_late = {c for c in pool if old(DAILY_DIR, c)}
    minute_late = {c for c in minute if old(MINUTE_DIR, c)}
    return sorted(daily_late | minute_late), daily_late


def full_refetch(client, code: str, path: str) -> bool:
    """증분으로 못 채운 일봉을 통째로 다시 받는다. 채웠으면 True.

    이력이 짧아지면 쓰지 않는다 — 과거를 잃는 쪽이 며칠 밀린 것보다 나쁘다.
    """
    from refetch_daily import fetch

    try:
        df = fetch(client, code, max_pages=3)
    except Exception as e:                              # noqa: BLE001
        log(f"  {code} 전체 재수집 실패: {type(e).__name__}: {str(e)[:80]}")
        return False
    if df is None or df.empty:
        return False
    try:
        old_rows = len(pd.read_csv(path)) if os.path.exists(path) else 0
    except (OSError, ValueError):
        old_rows = 0
    if len(df) < old_rows:
        return False
    df.to_csv(path)
    return True


def _arg(name: str) -> str | None:
    """`--name=값` 또는 `--name 값`."""
    for i, a in enumerate(sys.argv):
        if a.startswith(f"--{name}="):
            return a.split("=", 1)[1]
        if a == f"--{name}" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def parse_codes(spec: str) -> list[str]:
    """`A,B` 또는 `@파일`(줄마다 하나, # 주석 허용). **순서를 지킨다**(중복만 뺀다) — 허브가 "소피증권 유니버스 먼저"로
    정렬해 넘기므로 시간 제한(--stop-at)에 걸려도 급한 종목이 먼저 받아진다."""
    if spec.startswith("@"):
        with open(spec[1:], encoding="utf-8-sig") as fh:
            items = [ln.split("#")[0].strip() for ln in fh]
    else:
        items = spec.split(",")
    return list(dict.fromkeys(c.strip() for c in items if c.strip()))


def main() -> None:
    load_dotenv()
    limit = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), None)
    codes_spec, stop_at = _arg("codes"), _arg("stop-at")
    deadline = deadline_from(stop_at) if stop_at else None
    detail = {"mode": "codes" if codes_spec else ("all" if "--all" in sys.argv else "stale"),
              "stop_at": stop_at}
    with write("daily_minute", writer="backfill_universe", detail=detail) as w:
        run_backfill(w, limit, parse_codes(codes_spec) if codes_spec else None, deadline)


def run_backfill(w, limit, only_codes, deadline) -> None:
    target = settled_target()      # 마감이 확정된 가장 최근 거래일 — 장중·휴장일이면 직전 거래일

    if only_codes is not None:
        codes, daily_late = only_codes, set(only_codes)     # 지정한 종목은 일봉도 무조건 갱신
    else:
        codes, daily_late = stale_codes(target, "--all" in sys.argv)
    if limit:
        codes = codes[:limit]
    w.detail["codes"] = len(codes)
    log("=" * 50)
    log(f"백필 시작: {len(codes)}종목 (기준일 {target})")
    if not codes:
        log("밀린 종목 없음")
        return

    client = KiwoomClient(*batch_keys(),
                          is_mock=os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true")
    ok = fail = 0
    started = time.time()
    rescued = []
    deferred = 0
    for i, code in enumerate(codes, 1):
        if deadline is not None and datetime.now() >= deadline:
            deferred = len(codes) - (i - 1)
            log(f"--stop-at {deadline:%m-%d %H:%M} 도달 — 남은 {deferred}종목은 다음 회차로 미룸 (정상 종료)")
            break
        dpath = os.path.join(DAILY_DIR, f"{code}.csv")
        mpath = os.path.join(MINUTE_DIR, f"{code}.csv")
        try:
            if code in daily_late:
                update_daily(client, code, dpath, overlap_days=OVERLAP_DAYS)
                # 증분이 아무것도 못 가져오는 종목이 있다(거래정지 등). 조용히 두면
                # 그 종목만 옛날 일봉으로 신고가가 매겨진다.
                if (last_date(dpath) or date(2000, 1, 1)) < target and full_refetch(client, code, dpath):
                    rescued.append(code)
            m = (update_minute(client, code, mpath, overlap_days=OVERLAP_DAYS)
                 if os.path.exists(mpath) else None)
            ok += 1
            if i % 25 == 0 or i == len(codes):
                rate = (time.time() - started) / i
                stamp = f"~{m.index.max():%m-%d}" if m is not None and not m.empty else "일봉만"
                log(f"[{i}/{len(codes)}] {code} {stamp} "
                    f"| 성공 {ok} 실패 {fail} | 남은 {int(rate*(len(codes)-i)/60)}분")
        except Exception as e:
            fail += 1
            log(f"[{i}/{len(codes)}] {code} 실패: {str(e)[:120]}")
        w.progress(i, len(codes))

    if rescued:
        log(f"증분이 안 돼 통째로 다시 받은 종목 {len(rescued)}개: {', '.join(rescued[:10])}")
    still = [c for c in daily_late if (last_date(os.path.join(DAILY_DIR, f"{c}.csv"))
                                       or date(2000, 1, 1)) < target]
    if still:
        log(f"아직도 일봉이 밀린 종목 {len(still)}개: {', '.join(sorted(still)[:10])}")
    w.result(ok=ok, fail=fail, deferred=deferred, rescued=len(rescued), still_late=len(still))
    log(f"백필 완료: 성공 {ok} 실패 {fail} 미룸 {deferred} ({(time.time()-started)/60:.1f}분)")


def demo() -> None:
    """last_date가 파일 끝에서 날짜를 제대로 뽑는지 - 여기가 틀리면 전 종목을 다시 받는다.
    그리고 밀린 종목 고르기 - 여기가 틀리면 일부 종목이 조용히 안 받아진다."""
    p = "state/_backfill_demo.csv"
    os.makedirs("state", exist_ok=True)
    open(p, "w", encoding="utf-8").write(
        "date,open,high,low,close,volume\n"
        "2026-08-10 09:00:00,1,1,1,1,1\n2026-08-11 15:30:00,1,1,1,1,1\n")
    assert last_date(p) == date(2026, 8, 11), last_date(p)
    os.remove(p)
    assert last_date("없는파일.csv") is None

    open("state/_backfill_codes.txt", "w", encoding="utf-8").write("B # 주석" + chr(10) + "A" + chr(10) * 2)
    assert parse_codes("@state/_backfill_codes.txt") == ["B", "A"] and parse_codes("C, A, C") == ["C", "A"]
    os.remove("state/_backfill_codes.txt")

    global DAILY_DIR, MINUTE_DIR, UNIVERSE_CSV
    keep = (DAILY_DIR, MINUTE_DIR, UNIVERSE_CSV)
    root = "state/_backfill_demo"
    shutil.rmtree(root, ignore_errors=True)
    DAILY_DIR, MINUTE_DIR = f"{root}/daily", f"{root}/minute"
    os.makedirs(DAILY_DIR); os.makedirs(MINUTE_DIR)
    UNIVERSE_CSV = (f"{root}/universe.csv",)
    try:
        def bar(d, code, day):
            with open(os.path.join(d, f"{code}.csv"), "w", encoding="utf-8") as fh:
                fh.write("date,open,high,low,close,volume" + chr(10)
                         + f"{day} 09:00:00,1,1,1,1,1" + chr(10))
        bar(DAILY_DIR, "AAA", "2026-08-21")     # 분봉이 없고 일봉만 밀렸다 (남화토건)
        bar(DAILY_DIR, "BBB", "2026-09-02")     # 일봉은 최신, 분봉만 밀렸다
        bar(MINUTE_DIR, "BBB", "2026-08-21")
        bar(DAILY_DIR, "CCC", "2026-09-02")     # 둘 다 최신 - 안 받는다
        bar(MINUTE_DIR, "CCC", "2026-09-02")
        with open(f"{root}/universe.csv", "w", encoding="utf-8") as fh:
            fh.write("code,name" + chr(10) + "AAA,가" + chr(10) + "BBB,나" + chr(10) + "CCC,다" + chr(10))
        codes, daily_late = stale_codes(date(2026, 9, 2), force_all=False)
        assert codes == ["AAA", "BBB"], codes
        assert daily_late == {"AAA"}, daily_late
    finally:
        shutil.rmtree(root, ignore_errors=True)
        DAILY_DIR, MINUTE_DIR, UNIVERSE_CSV = keep
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
