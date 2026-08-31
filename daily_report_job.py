"""클린20 리포트를 매일 최신으로 유지하는 파이프라인 (1~4단계).

    python daily_report_job.py            # 전체 실행
    python daily_report_job.py --skip-data  # 데이터 수집 빼고 재계산만

  1) 거래대금 top35 증분 수집 (backtesting.cli update-top35)
  2) 코스피/코스닥 지수 일봉·분봉 증분 수집  <- update-top35가 안 건드리는 부분
  3) reach20_condition_scan (피처) -> reach20_path_drawdown (라벨)
  4) clean20_report (HTML)

스케줄링은 이 스크립트가 하지 않는다. nasdaq_monitor_watchdog.ps1이 이미 5분마다
깨어나므로 거기서 하루 한 번 호출한다 - 스케줄러 프로세스를 새로 띄우지 않기 위함.
아티팩트 재배포(5단계)는 사람이 세션에서 해야 하므로 여기 없다.
"""
import os
import subprocess
import sys
import time
from datetime import date

import pandas as pd
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backtesting.data_loader import _pages_to_dataframe
from backtesting.updater import _load_existing, _merge_dedupe_save
from kiwoom_client import KiwoomClient

STATE_DIR = "state/daily_report"
LOG = "daily_report_job.log"
INDEXES = {"001": "코스피", "101": "코스닥"}
MINUTE_PAGES = 15   # 1페이지 ≈ 2.3거래일. 연휴로 며칠 밀려도 메우도록 여유를 둔다
STEPS = [
    ([sys.executable, "reach20_condition_scan.py", "--top=20"], "피처 재계산", {}),
    ([sys.executable, "reach20_path_drawdown.py", "--top=10"], "경로/라벨 재계산", {}),
    # 4조건 1번이 09:30 등락률이라 이 파일이 없으면 새 날짜가 전부 미달로 잡힌다
    ([sys.executable, "reach20_condition_scan.py", "--top=20"], "09:30 피처 재계산",
     {"SCAN_CUTOFF": "0930"}),
    ([sys.executable, "clean20_report.py"], "HTML 재생성", {}),
]


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def update_indexes(client: KiwoomClient) -> None:
    """지수 일봉/분봉 증분 갱신. update-top35는 개별 종목만 받아서 여기가 비면
    코스피60 열과 일 단위 지표가 과거에 머문다."""
    for code, name in INDEXES.items():
        for kind, path, pages in [
            ("daily", f"data/index/daily/{code}.csv",
             client.get_index_daily_chart_pages(code, max_pages=2)),
            ("minute", f"data/index/minute/{code}.csv",
             client.get_index_minute_chart_pages(code, tic_scope="1", max_pages=MINUTE_PAGES)),
        ]:
            fresh = _pages_to_dataframe(pages, is_minute=(kind == "minute"))
            if fresh.empty:
                log(f"  {name} {kind}: 신규 없음")
                continue
            merged = _merge_dedupe_save(_load_existing(path), fresh, path)
            log(f"  {name} {kind}: ~{merged.index.max():%Y-%m-%d} ({len(merged)}행)")


def run(cmd: list[str], label: str, env_extra: dict | None = None) -> bool:
    log(f"{label} 시작")
    env = {**os.environ, **(env_extra or {})}
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    tail = (r.stdout or "").strip().splitlines()[-3:]
    for t in tail:
        log(f"  {t}")
    if r.returncode != 0:
        log(f"{label} 실패 (exit {r.returncode}): {(r.stderr or '')[-500:]}")
        return False
    log(f"{label} 완료")
    return True


def main() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    started = time.time()
    pd.Series({"started_at": started}).to_json(f"{STATE_DIR}/last_run_started.json")
    log("=" * 60)
    log(f"일일 갱신 시작 ({date.today()})")

    ok = True
    if "--skip-data" not in sys.argv:
        # top35는 "오늘 새로 진입한 종목"을 유니버스에 넣는 역할, 백필은 나머지 전 종목을
        # 최신으로 유지하는 역할. 백필이 없으면 며칠 만에 그날 데이터 보유 종목이 수십 개로
        # 줄어 대금 순위가 가짜가 된다(2026-07-20~08-11 구간에서 실제로 발생).
        ok = run([sys.executable, "-m", "backtesting.cli", "update-top35"], "top35 증분 수집")
        ok = run([sys.executable, "backfill_universe.py"], "전 종목 증분 갱신") and ok
        try:
            load_dotenv()
            log("지수 증분 수집 시작")
            update_indexes(KiwoomClient(
                os.environ["KIWOOM_APPKEY"], os.environ["KIWOOM_SECRETKEY"],
                is_mock=os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true"))
            log("지수 증분 수집 완료")
        except Exception as e:                      # 지수가 실패해도 종목 기반 재계산은 의미가 있다
            log(f"지수 증분 수집 실패(계속 진행): {e}")

        # 일봉이 갱신된 직후에 120일 신고가를 다시 뽑는다 — 순서가 바뀌면 하루 낡은
        # 고가로 거래대금 상위 화면에 별표가 붙는다. 실패해도 뒤 단계는 계속 돈다
        # (별표가 하루 낡을 뿐, 리포트 파이프라인과는 무관하다).
        try:
            import build_high120
            rows, skipped = build_high120.build()
            log(f"120일 신고가 갱신 완료 ({len(rows)}종목, 봉 부족 제외 {skipped})")
        except Exception as e:
            log(f"120일 신고가 갱신 실패: {type(e).__name__}: {e}")

    for cmd, label, env_extra in STEPS:
        if not run(cmd, label, env_extra):
            ok = False
            break                                   # 앞 단계가 깨지면 뒤는 낡은 입력으로 도는 셈

    took = time.time() - started
    pd.Series({"finished_at": time.time(), "ok": ok, "took_sec": round(took)}
              ).to_json(f"{STATE_DIR}/last_run_finished.json")
    log(f"일일 갱신 {'완료' if ok else '실패'} ({took/60:.1f}분)")
    sys.exit(0 if ok else 1)


def demo() -> None:
    """상태 파일 왕복 - 워치독이 이 값으로 중복 실행을 막는다."""
    os.makedirs(STATE_DIR, exist_ok=True)
    p = f"{STATE_DIR}/_demo.json"
    pd.Series({"finished_at": 1.5, "ok": True}).to_json(p)
    back = pd.read_json(p, typ="series")
    assert back["finished_at"] == 1.5 and bool(back["ok"]) is True, back.to_dict()
    os.remove(p)
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
