"""실시간 체결(0B)·호가(0D) 원본 저장 — 고른 종목 + 최근 신고대금 종목(11-01 사용자 "신고대금 종목 호가데이터도 같이 수집").

저장 체결(ka10079)엔 매수·매도 표시가 없고 호가는 과거 조회가 안 된다 → 데스크가 이미 받는 실시간을 그대로 남긴다.
데스크 앱키(TRADER_APPKEY) 연결 하나로 받으니 소피증권·배치 앱키와 안 부딪힌다. 받는 시간 = 데스크 실시간 시간(07:50~20:05).
파일: data/stocks/live_al/{code}/{date}.jsonl.gz — 한 줄 {"t": 받은 시각(초), "k": "0B"|"0D", "v": 원본 values}. 2초마다 gzip 덧붙임.
허브 관문(datahub.write "live_al")은 그날 첫 기록부터 20:05(또는 날짜 바뀜)까지 한 번 잡는다 — 데스크를 다시 켜면 장부에 새 실행으로 남아 빈 구간이 보인다.
"""
from __future__ import annotations

import gzip
import json
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "stocks" / "live_al"
DAYS_AFTER = 10                                      # 신고대금 다음 거래일부터 10거래일(11-01 사용자 "나오면 10일간")
MIN_EOK = 1000                                       # 기준일(신고대금 날) 통합 대금 1000억 이상만(11-02 사용자)

codes: set[str] = set()                              # 저장할 종목 — desk(또는 recorder)가 정한다
OWNER = False                                        # True = 따로 도는 수집기(trader/recorder.py) — 살아 있다는 표시를 남긴다
ALIVE = ROOT / "state" / "trader" / "rec_alive"      # 수집기가 2초마다 건드림 — 15초 안이면 데스크는 저장을 넘긴다
_chk = [0.0, False]
_q: list = []
_qlock = threading.Lock()
_thread: threading.Thread | None = None
stat = {"rows": 0, "err": None, "day": None}


def recent_value_codes(today: date | None = None) -> list[str]:
    """오늘이 신고대금(통합) 날 다음 1~10거래일 안인 종목 — 그 신고대금 날 통합 대금 MIN_EOK 억 이상만. 신고대금 날은 장부가 그날 밤에 생겨 다음 거래일부터 잡힌다."""
    from datahub.calendar import Calendar
    from . import backtest as B
    today = today or date.today()
    cal, d = Calendar(), today
    for _ in range(DAYS_AFTER):
        d = cal.prev_trading_day(d)
    ev = B.events(d.isoformat(), (today - timedelta(days=1)).isoformat(), 0, "aft", "all")
    rows = json.loads((B.ROOT / "static" / "dashboard" / "value_ledger.json").read_text(encoding="utf-8"))["rows"]
    big = {(x[0], x[1]) for x in rows if (x[3] or 0) >= MIN_EOK}    # x[3] = 그날 통합 대금(억)
    return sorted({c for dd, c, _, _ in ev if (dd, c) in big})


_today: dict = {}


def today_codes() -> list[str]:
    """recent_value_codes 를 하루 한 번만(장부는 밤에 갱신된다)."""
    d = date.today()
    if _today.get("d") != d:
        try:
            _today.update(d=d, codes=recent_value_codes(d))
        except Exception as e:                                       # noqa: BLE001 — 장부 못 읽어도 고른 종목은 저장
            stat["err"], _today["codes"] = f"신고대금 목록: {e}"[:200], _today.get("codes", [])
            _today["d"] = d
    return _today["codes"]


def _yield() -> bool:
    """데스크 쪽: 따로 도는 수집기가 살아 있으면 저장을 넘긴다 — 수집기가 죽으면 15초 안에 데스크가 다시 저장(11-02 사용자 "데스크 고칠 때 수집이 끊기면 안 돼").
    ponytail: 넘겨받는 순간 2초 남짓 두 쪽이 같이 써 겹칠 수 있다 — 겹침이 분석에 걸리면 (t, 13 누적량)으로 중복 지우기."""
    if OWNER:
        return False
    now = time.time()
    if now - _chk[0] > 2:
        try:
            _chk[:] = [now, now - ALIVE.stat().st_mtime < 15]
        except OSError:
            _chk[:] = [now, False]
    return _chk[1]


def put(kind: str, code: str, values: dict) -> None:
    if OWNER and not stat.get("in"):                                  # 수집기는 잠금을 잡은 동안만 모은다 — 데스크가 쓰는 중에 쌓았다 나중에 겹쳐 쓰지 않게
        return
    if code in codes and kind in ("0B", "0D") and not _yield():
        with _qlock:
            _q.append((round(time.time(), 3), kind, code, values))


def flush(base: Path = DIR) -> int:
    with _qlock:
        items, _q[:] = list(_q), []
    if not items:
        return 0
    by = defaultdict(list)
    for t, k, c, v in items:
        by[(c, datetime.fromtimestamp(t).date().isoformat())].append(json.dumps({"t": t, "k": k, "v": v}, ensure_ascii=False))
    for (c, d), lines in by.items():
        p = base / c / f"{d}.jsonl.gz"
        p.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(p, "at", encoding="utf-8") as f:              # gzip 덧붙이기 = 멤버가 이어 붙어도 한 파일로 읽힌다
            f.write("\n".join(lines) + "\n")
    stat["rows"] += len(items)
    return len(items)


def _loop(is_active) -> None:
    from datahub import write
    while True:
        try:
            if not (is_active(datetime.now()) and (_q or OWNER)):
                time.sleep(2)
                continue
            day = date.today()
            with write("live_al", writer="trader_rec" if OWNER else "trader_desk", detail={"codes": len(codes)}) as w:
                stat["day"], stat["in"] = day.isoformat(), True
                try:
                    while is_active(datetime.now()) and date.today() == day:
                        flush()
                        if OWNER:
                            ALIVE.touch()                             # 잠금을 잡고 쓰는 동안만 '살아 있음' — 못 잡고 기다리는 동안은 데스크가 계속 쓴다
                        time.sleep(2)
                finally:
                    stat["in"] = False
                flush()
                w.result(rows=stat["rows"], codes=len(codes))
        except Exception as e:                                       # noqa: BLE001 — 저장 오류로 데스크가 멈추면 안 된다
            stat["err"] = f"{type(e).__name__}: {e}"[:200]
            time.sleep(10)


def start(is_active) -> None:
    global _thread
    if _thread is None:
        _thread = threading.Thread(target=_loop, args=(is_active,), daemon=True, name="rec")
        _thread.start()


if __name__ == "__main__":                                           # 자체 점검: 고른 종목만·두 종류만 저장, gzip 덧붙여도 다 읽힘
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    codes.update({"263860"})
    put("0B", "263860", {"10": "26650", "15": "+5"}); put("0D", "263860", {"41": "26700"}); put("0B", "005930", {"10": "1"}); put("00", "263860", {})
    assert flush(tmp) == 2
    put("0B", "263860", {"10": "26600", "15": "-3"}); flush(tmp)
    f = next(tmp.glob("263860/*.jsonl.gz"))
    rows = [json.loads(x) for x in gzip.open(f, "rt", encoding="utf-8")]
    assert [r["k"] for r in rows] == ["0B", "0D", "0B"] and rows[2]["v"]["15"] == "-3", rows
    assert not (tmp / "005930").exists()
    print("ok", len(rows), "줄 ·", len(recent_value_codes()), "신고대금 종목")
