"""장중 52주 신고가 실시간 — 키움 ka10016(신고저가요청)을 대시보드 서버 안에서 60초마다 조회한다(10-01 사용자 요청).

야간 갱신(new_high.py)은 하루 한 번 일봉으로 만든다 — 장중엔 어제 상태라 그날 신고가가 안 보였다.
여기는 키움이 판정한 "지금 250일 신고가를 찍은 종목"을 받아 메모리에 들고, 화면(newhigh.html #new)이
야간 데이터(섹터·RS·시총)와 합쳐 보여준다. 판정 기준은 키움 것(장중 고가 기준, 통합 시세)이라 야간 일봉 판정과
하루 안에서 조금 다를 수 있다 — 화면에 '장중(키움)'으로 따로 표시한다.

토큰: 거래대금 순위 폴러와 같은 KiwoomClient 를 쓴다(_get_client) — 새 토큰을 발급하면 같은 앱키를 쓰는
소피증권 토큰이 무효가 된다(shared-appkey-token). REST 예산: 1분에 1~3회(페이지 수)라 순위 폴러(초당 1회) 대비 미미하다.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, time as dtime

from .afterhours_ranking import _get_client
from backtesting.screener import _is_excluded_instrument

logger = logging.getLogger(__name__)

POLL_SECONDS = 60
DAILY_DIR = "data/stocks/daily"
ACTIVE_FROM, ACTIVE_TO = dtime(8, 0), dtime(20, 5)   # 통합(NXT 포함) 시간 + 마감 여유
MAX_PAGES = 5
BODY = {
    "mrkt_tp": "000",            # 전체(코스피+코스닥)
    "ntl_tp": "1",               # 1: 신고가
    "high_low_close_tp": "1",    # 1: 고저 기준(장중 고가) — 2 는 종가 기준
    "stk_cnd": "0", "trde_qty_tp": "00000", "crd_cnd": "0", "updown_incls": "1",
    "dt": "250",                 # 250일 = 52주
    "stex_tp": "3",              # 3: 통합(KRX+NXT)
}

_lock = threading.Lock()
_state: dict = {"rows": [], "as_of": None, "error": None, "quotes": {}, "quotes_as_of": None, "quote_error": None}


def _num(v) -> float | None:
    try:
        return abs(float(str(v).replace(",", "").strip() or "nan"))
    except ValueError:
        return None


def stock_universe() -> set[str]:
    """일봉이 있는 종목(= 주식). 이름 휴리스틱이 '1Q 머니마켓액티브' 같은 액티브 ETF 를 못 걸러서(10-01 실측) 유니버스로 거른다."""
    try:
        return {f[:-4] for f in os.listdir(DAILY_DIR) if f.endswith(".csv")}
    except OSError:
        return set()


def parse(payload: dict, universe: set[str] | None = None) -> list[dict]:
    """ka10016 응답의 ntl_pric 행 → 화면용 dict. 가격 칸은 '+12000' 처럼 부호가 붙어 와서 절댓값을 쓴다."""
    rows = []
    for it in payload.get("ntl_pric") or []:
        code = str(it.get("stk_cd", "")).split("_")[0].strip()
        name = str(it.get("stk_nm", "")).strip()
        if not code or _is_excluded_instrument(name) or (universe is not None and code not in universe):
            continue
        try:
            rate = float(str(it.get("flu_rt", "0")).replace("+", "") or 0)
        except ValueError:
            rate = None
        rows.append({"코드": code, "이름": name, "현재가": _num(it.get("cur_prc")), "등락률": rate,
                     "당일고가": _num(it.get("high_pric")), "당일저가": _num(it.get("low_pric")),
                     "거래량": _num(it.get("trde_qty"))})
    return rows


def refresh(appkey: str, secretkey: str, is_mock: bool) -> None:
    client = _get_client(appkey, secretkey, is_mock)
    pages = client._paginate("ka10016", BODY, "/api/dostk/stkinfo", MAX_PAGES)
    seen, rows, uni = set(), [], stock_universe()
    for p in pages:
        for r in parse(p, uni or None):
            if r["코드"] not in seen:
                seen.add(r["코드"])
                rows.append(r)
    with _lock:
        _state.update(rows=rows, as_of=datetime.now().strftime("%H:%M:%S"), date=datetime.now().date().isoformat(), error=None)


# ---- 감시 종목 시세(ka10095 관심종목정보) — 신고가 후보·신고가 장부의 장중 반영용 ----
# 감시 = 어제 종가가 120일 고가의 76% 이상인 종목(상한가 +30% 로 하루에 120일 고가에 닿을 수 있는 범위, 약 470종목).
# 52주 후보(고가까지 20% 이내)는 전부 이 안에 든다(10-01 실측: 후보 197 중 밖 0). ka10016 에 잡힌 종목은 따로 더한다.
QUOTE_CHUNK = 50
WATCH_RATIO = 0.76
_refs: dict = {"date": None, "codes": {}}


def _load_refs() -> dict:
    """어제까지 일봉으로 종목별 52주·120일 고가와 전일 종가. 하루 한 번(약 6초)."""
    from backtesting import rs_rating as R
    close, (high, _) = R.wide_close(), R.wide_high_low()
    names = R.load_names()
    ex = R.excluded_codes(names)
    h52, h120, last = high.iloc[-250:].max(), high.iloc[-120:].max(), close.iloc[-1]
    out = {}
    for c in close.columns:
        if c in ex or last.get(c) != last.get(c) or h120.get(c) != h120.get(c):
            continue
        out[c] = {"name": names.get(c, c), "h52": float(h52[c]), "h120": float(h120[c]),  # 신규상장주는 상장 이후 최고가(장부 기준과 같다)
                  "prev": float(last[c]), "watch": bool(last[c] >= h120[c] * WATCH_RATIO)}
    return out


def parse_quotes(payload: dict) -> dict:
    out = {}
    for it in payload.get("atn_stk_infr") or []:
        code = str(it.get("stk_cd", "")).split("_")[0].strip()
        price, qty = _num(it.get("cur_prc")), _num(it.get("trde_qty"))
        try:
            rate = float(str(it.get("flu_rt", "0")).replace("+", "") or 0)
        except ValueError:
            rate = None
        if code and price:
            out[code] = {"price": price, "chg": rate, "high": _num(it.get("high_pric")), "low": _num(it.get("low_pric")),
                         "value": price * qty if qty else None}
    return out


def refresh_quotes(appkey: str, secretkey: str, is_mock: bool) -> None:
    today = datetime.now().date().isoformat()
    if _refs["date"] != today:
        _refs.update(codes=_load_refs(), date=today)
    refs = _refs["codes"]
    with _lock:
        extra = [r["코드"] for r in _state["rows"]]
    codes = list(dict.fromkeys([c for c, v in refs.items() if v["watch"]] + [c for c in extra if c in refs]))
    client = _get_client(appkey, secretkey, is_mock)
    quotes = {}
    for i in range(0, len(codes), QUOTE_CHUNK):
        payload = client.request_tr("ka10095", {"stk_cd": "|".join(codes[i:i + QUOTE_CHUNK])}, path="/api/dostk/stkinfo")
        if payload.get("return_code") not in (0, None):
            raise RuntimeError(f"ka10095 {payload.get('return_code')}: {payload.get('return_msg')}")
        quotes.update(parse_quotes(payload))
    for c, q in quotes.items():
        q.update(name=refs[c]["name"], h52=refs[c]["h52"], h120=refs[c]["h120"]) if c in refs else None
    with _lock:
        _state.update(quotes=quotes, quotes_as_of=datetime.now().strftime("%H:%M:%S"), quote_error=None, quotes_date=today,
                      watch_n=len(codes))


def snapshot() -> dict:
    """화면이 읽는 지점 — API 를 안 친다. 장 밖이면 active=False 로 마지막 결과를 그대로 준다."""
    now = datetime.now()
    with _lock:
        out = dict(_state)
    out["active"] = ACTIVE_FROM <= now.time() <= ACTIVE_TO and now.weekday() < 5
    today = now.date().isoformat()
    if out.get("date") and out["date"] != today:
        out["rows"] = []                               # 어제 장중 결과는 오늘 신고가가 아니다
    if out.get("quotes_date") != today:
        out["quotes"] = {}
    return out


def _loop(appkey: str, secretkey: str, is_mock: bool) -> None:
    while True:
        now = datetime.now()
        if now.weekday() < 5 and ACTIVE_FROM <= now.time() <= ACTIVE_TO:
            try:
                refresh(appkey, secretkey, is_mock)
            except Exception as e:
                logger.warning("장중 신고가 조회 실패", exc_info=True)
                with _lock:
                    _state["error"] = f"{type(e).__name__}: {e}"
            try:
                refresh_quotes(appkey, secretkey, is_mock)
            except Exception as e:
                logger.warning("감시 종목 시세 조회 실패", exc_info=True)
                with _lock:
                    _state["quote_error"] = f"{type(e).__name__}: {e}"
        time.sleep(POLL_SECONDS)


def start_background_poller(appkey: str, secretkey: str, is_mock: bool) -> threading.Thread:
    t = threading.Thread(target=_loop, args=(appkey, secretkey, is_mock), name="newhigh-live", daemon=True)
    t.start()
    return t
