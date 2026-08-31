"""auto_develop의 기준선(baseline_metrics.json)을 현재 데이터로 다시 세운다.

    python rebaseline.py            # 백필이 끝날 때까지 기다렸다 실행
    python rebaseline.py --now      # 기다리지 않고 바로

기존 기준선은 commit 2ca81bc, 스캔 구간 ~2026-07-15에서 만들어졌다. 그 뒤 데이터가
늘어나(백필로 ~2026-08-11까지) 지금은 auto_develop이 서로 다른 구간을 비교하고 있다.
실제로 2026-08-10 사이클이 "기준선이 낡았다"고 스스로 note에 적고 반려했다.

이 스크립트는 검증 3종을 돌려 원본 출력을 state/auto_develop/rebaseline_*.txt에 남긴다.
JSON으로 옮기는 건 사람(또는 클로드)이 출력을 읽고 하는 게 안전하다 - 지표 이름과
스키마가 auto_develop_prompt.md의 판정 기준과 정확히 맞아야 하기 때문이다.
"""
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT_DIR = "state/auto_develop"
STEPS = [
    ("strategy1", [sys.executable, "-m", "backtesting.validate_strategy1"]),
    ("strategy2", [sys.executable, "-m", "backtesting.validate_strategy2"]),
    ("pytest", [sys.executable, "-m", "pytest", "tests/", "-q"]),
]
POLL_SEC = 60
BACKFILL_LOG = "backfill_universe.log"
STALE_MIN = 15        # 로그가 이만큼 안 움직이면 백필이 죽은 것으로 본다


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open("rebaseline.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def backfill_running() -> bool:
    """백필 로그로 판정한다. 프로세스 조회(PowerShell)를 쓰다가 백그라운드 환경에서
    호출이 실패해 '안 돌고 있다'로 잘못 읽은 적이 있다(2026-08-11, 절반만 채워진
    데이터로 기준선을 잴 뻔했다). 파일은 어느 환경에서나 똑같이 읽힌다.

    끝났다고 보는 조건은 둘 중 하나 - 마지막 줄이 완료 문구이거나, 로그가
    STALE_MIN 이상 갱신되지 않음(프로세스가 죽은 경우). 판단이 안 되면 '돌고 있다'로
    본다 - 잘못 기다리는 건 시간만 쓰지만 잘못 진행하면 기준선이 통째로 틀어진다.
    """
    if not os.path.exists(BACKFILL_LOG):
        return False
    try:
        with open(BACKFILL_LOG, encoding="utf-8") as f:
            last = [ln for ln in f.read().splitlines() if ln.strip()][-1]
        if "백필 완료" in last or "밀린 종목 없음" in last:
            return False
        return (time.time() - os.path.getmtime(BACKFILL_LOG)) / 60 < STALE_MIN
    except Exception as exc:
        log(f"백필 상태 확인 실패({exc}) — 계속 대기")
        return True


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    if "--now" not in sys.argv:
        while backfill_running():
            log("백필 진행 중 — 대기")
            time.sleep(POLL_SEC)
        log("백필 종료 확인")

    started = time.time()
    for name, cmd in STEPS:
        log(f"{name} 시작")
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        path = os.path.join(OUT_DIR, f"rebaseline_{name}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write((r.stdout or "") + "\n===== STDERR =====\n" + (r.stderr or ""))
        log(f"{name} 종료 (exit {r.returncode}, {(time.time()-t0)/60:.1f}분) -> {path}")

    log(f"전체 완료 ({(time.time()-started)/60:.1f}분). "
        f"{OUT_DIR}/rebaseline_*.txt 를 읽고 baseline_metrics.json을 갱신할 것")


def demo() -> None:
    """출력 경로 규칙 - 단계 이름이 그대로 파일명에 들어가야 나중에 찾을 수 있다."""
    names = [n for n, _ in STEPS]
    assert names == ["strategy1", "strategy2", "pytest"], names
    assert os.path.join(OUT_DIR, "rebaseline_pytest.txt").endswith("rebaseline_pytest.txt")
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
