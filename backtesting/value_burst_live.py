"""거래대금 폭발 장중 실시간 — 대시보드 서버 안에서 60초마다 통합 거래대금 상위(ka10032, stex_tp=3)를 받아
야간에 만든 종목별 비교 기준(state/value_burst_refs.json)과 비교한다. 사용자 2026-10-06("실시간으로 해줘").

- 등급 판정은 야간 value_burst.tiers_of 와 같은 규칙: 오늘 장중 누적 통합 대금 vs 어제까지의 역대/4년/1년 최대·1년 최대의 70%,
  평소 대비 = 1,000억↑ + 어제까지 20일 평균의 2.5배↑ + 등락 +7%↑. 기준은 어젯밤 값 그대로라 미래 정보가 섞이지 않는다.
- 대상은 거래대금 상위 MAX_PAGES 쪽(약 200종목)뿐 — 1,000억 폭발은 거의 다 이 안이지만 '1년 유의미'(300억~) 같은 작은 건은 빠질 수 있다.
- 장중 고가를 모르므로 240일 고점 판정은 현재가로만 한다(현재가 > 옛 고점이면 '돌파 중', 확정은 밤 갱신).
토큰: 순위 폴러와 같은 KiwoomClient(_get_client) — 새로 발급하면 같은 앱키의 소피증권 토큰이 무효(shared-appkey-token).
REST: 1분에 MAX_PAGES 회 — 순위 폴러(초당 1회) 대비 작다.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, time as dtime

from .afterhours_ranking import _get_client
from .screener import top_by_trading_value
from .value_burst import NEAR, REFS_PATH, SPIKE_CHG, SPIKE_EOK, SPIKE_MULT, MIN_EOK

logger = logging.getLogger(__name__)
POLL_SECONDS = 60
MAX_PAGES = 4
ACTIVE_FROM, ACTIVE_TO = dtime(8, 0), dtime(20, 5)   # 통합(NXT 포함) 시간 + 마감 여유
_lock = threading.Lock()
_state: dict = {"rows": [], "as_of": None, "date": None, "error": None}
_refs: dict = {"mtime": None, "data": {}}


def _load_refs() -> dict:
    import os
    try:
        m = os.path.getmtime(REFS_PATH)
    except OSError:
        return {}
    if _refs["mtime"] != m:
        _refs.update(mtime=m, data=json.load(open(REFS_PATH, encoding="utf-8")))
    return _refs["data"]


def tier_of(val: float, chg: float, ref: dict) -> str | None:
    """오늘 장중 누적 대금(억)·등락(%)으로 등급. 야간 tiers_of 와 같은 순서(높은 등급이 이긴다)."""
    if val > ref["all"]:
        return "역대"
    if val > ref["y4"]:
        return "4년"
    if val > ref["y1"]:
        return "1년"
    if val >= NEAR * ref["y1"]:
        return "1년 유의미"
    if val >= SPIKE_EOK and ref["avg20"] and val >= SPIKE_MULT * ref["avg20"] and chg >= SPIKE_CHG * 100:
        return "평소 대비"
    return None


def build_rows(ranking: list[dict], refs: dict) -> list[dict]:
    codes, out = refs.get("codes", {}), []
    for r in ranking:
        ref = codes.get(r["stock_code"])
        val = r["trading_value"] / 1e8
        if ref is None or val < MIN_EOK:
            continue
        t = tier_of(val, r["change_rate"], ref)
        if t is None:
            continue
        base = {"역대": ref["all"], "4년": ref["y4"], "평소 대비": ref["avg20"]}.get(t, ref["y1"])
        price = r["current_price"]
        out.append({"코드": r["stock_code"], "이름": ref["n"], "섹터": ref["s"], "세부섹터": ref["ss"],
                    "rs": ref["rs"], "rs_1m": ref["rs1"], "섹터rs": refs.get("sec_rs", {}).get(ref["s"]),
                    "세부섹터rs": refs.get("sub_rs", {}).get(ref["ss"]),
                    "등급": t, "대금": round(val), "비교대금": base, "배수": round(val / base, 2) if base else None,
                    "평균대금": ref["avg20"],
                    "등락": r["change_rate"], "현재가": price, "h_al": ref["h_al"], "h_krx": ref["h_krx"],
                    **{f"ma{n}": round((s + price) / int(n), 1) for n, s in (ref.get("ms") or {}).items()}})
    return out


def refresh(appkey: str, secretkey: str, is_mock: bool) -> None:
    client = _get_client(appkey, secretkey, is_mock)
    df = top_by_trading_value(client, top_n=MAX_PAGES * 100, max_pages=MAX_PAGES)   # 통합(stex_tp=3) 기본
    rows = build_rows(df.to_dict("records"), _load_refs())
    with _lock:
        _state.update(rows=rows, as_of=datetime.now().strftime("%H:%M:%S"), date=datetime.now().date().isoformat(), error=None)


def _is_market_day(d) -> bool:
    try:
        from datahub.calendar import Calendar
        return Calendar().is_trading_day(d)
    except Exception:  # noqa: BLE001 — 달력을 못 읽으면 주말만 거른다
        return d.weekday() < 5


def snapshot() -> dict:
    now = datetime.now()
    with _lock:
        out = dict(_state)
    out["active"] = ACTIVE_FROM <= now.time() <= ACTIVE_TO and _is_market_day(now.date())
    if out.get("date") != now.date().isoformat():
        out["rows"] = []                       # 어제 장중 결과는 오늘 것이 아니다
    out["refs_date"] = _refs["data"].get("date")
    return out


def _loop(appkey: str, secretkey: str, is_mock: bool) -> None:
    while True:
        now = datetime.now()
        if ACTIVE_FROM <= now.time() <= ACTIVE_TO and _is_market_day(now.date()):
            try:
                refresh(appkey, secretkey, is_mock)
            except Exception as e:
                logger.warning("거래대금 폭발 장중 조회 실패", exc_info=True)
                with _lock:
                    _state["error"] = f"{type(e).__name__}: {e}"
        time.sleep(POLL_SECONDS)


def start_background_poller(appkey: str, secretkey: str, is_mock: bool) -> threading.Thread:
    t = threading.Thread(target=_loop, args=(appkey, secretkey, is_mock), name="value-burst-live", daemon=True)
    t.start()
    return t


def demo() -> None:
    ref = {"all": 5000, "y4": 3000, "y1": 2000, "avg20": 200, "n": "x", "s": "s", "ss": "ss", "rs": 90, "rs1": 80, "h_al": 100, "h_krx": 100}
    assert tier_of(6000, 1, ref) == "역대" and tier_of(2500, 1, ref) == "1년" and tier_of(1500, 1, ref) == "1년 유의미"
    assert tier_of(1200, 8, {**ref, "y1": 5000}) == "평소 대비" and tier_of(1200, 5, {**ref, "y1": 5000}) is None
    rows = build_rows([{"stock_code": "A", "trading_value": 2500e8, "change_rate": 9.0, "current_price": 120}], {"codes": {"A": ref}})
    assert rows[0]["등급"] == "1년" and rows[0]["배수"] == 1.25
    print("demo ok")


if __name__ == "__main__":
    demo()
