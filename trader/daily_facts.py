"""매수 조건 중 '하루 한 번 계산하면 되는 것' — 로컬 통합 일봉·테마·시장·상장주식수에서 계산한다(키움 조회 없음).

정의는 −8% 눌림 규칙(pullback_candidates.py, 10-01 사용자 확정·검증)과 같다:
- 장대양봉: 고가 +20%↑ · 종가 +15%↑ · 대금(종가×거래량) 1,500억↑ (ETF·ETN·스팩 제외)
- 같은 테마 동반: 80종목 이하 테마에서 다른 종목이 최근 10거래일 안 +10% 마감한 수(테마 여럿이면 가장 많은 테마)
- 장대양봉 매수 창: 장대양봉 다음 날부터 5거래일, 그날 고가 −8% 에 '처음' 닿을 때 — 이미 닿았으면 창이 닫힌다
- 52주 돌파폭: 장대양봉일 고가 ÷ 그 전날까지 52주(250거래일) 고가 − 1

일봉이 '직전 거래일'까지 안 와 있으면(백필 전) 계산하지 않는다 — 낡은 값으로 사면 안 된다.
"""
from __future__ import annotations

import json
import math
import threading
from datetime import date, timedelta

import pandas as pd

BIG_HIGH, BIG_CLOSE, BIG_VALUE = 0.20, 0.15, 1500e8
ENTRY_WIN, DIP, THEME_MAX, MOVER = 5, 0.08, 80, 0.10

_facts: dict = {"asof": None, "codes": {}, "err": None, "building": False}
_lock = threading.Lock()


def prev_trading_day(today: date) -> date:
    from backtesting.value_burst_live import _is_market_day
    d = today - timedelta(days=1)
    while not _is_market_day(d):
        d -= timedelta(days=1)
    return d


def compute(close: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame, vol: pd.DataFrame,
            themes: pd.DataFrame, market: dict, shares: dict) -> dict:
    """마지막 날(=직전 거래일) 기준 종목별 사실. 넓은 표는 index=날짜, columns=코드."""
    pc = close.shift(1)
    big = (high / pc - 1 >= BIG_HIGH) & (close / pc - 1 >= BIG_CLOSE) & (close * vol >= BIG_VALUE)
    up10 = (close / pc - 1 >= MOVER).astype(int).rolling(10, min_periods=1).max().astype(bool)
    hi52 = high.shift(1).rolling(250, min_periods=1).max()
    th = themes[themes.theme_size <= THEME_MAX]
    themes_of = th.groupby("stock_code").theme.apply(list).to_dict()
    members = th.groupby("theme").stock_code.apply(list).to_dict()
    up_sets: dict = {}

    def movers(code: str, day) -> int:
        if day not in up_sets:
            row = up10.loc[day]
            up_sets[day] = set(row.index[row.values])
        ups = up_sets[day]
        return max((sum(1 for m in members[t] if m != code and m in ups) for t in themes_of.get(code, [])), default=0)

    idx, last = close.index, close.index[-1]
    window = idx[-ENTRY_WIN:]                                  # 장대양봉일이 이 안이면 오늘이 매수 창 안(다음 날부터 5거래일)
    out = {}
    for c in close.columns:
        f = {"market": market.get(c), "shares": shares.get(c), "hi52": _f(high[c].iloc[-250:].max()), "movers": movers(c, last)}
        days = [d for d in window if bool(big.at[d, c])]
        if days:
            d = days[-1]
            i, bh = idx.get_loc(d), float(high.at[d, c])
            h52 = hi52.at[d, c]
            f["big"] = {"date": d.date().isoformat(), "high": bh,
                        "break52": None if pd.isna(h52) or not h52 else round((bh / h52 - 1) * 100, 2),
                        "movers": movers(c, d),
                        "touched": bool((low[c].iloc[i + 1:] <= bh * (1 - DIP)).any())}
        out[c] = f
    return out


def _f(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def build(today: date | None = None) -> None:
    """하루 한 번(데스크 시작·날짜 바뀜) 백그라운드로. 9초쯤 걸린다(10-19 실측, 2,519종목 × 1,836일)."""
    today = today or date.today()
    with _lock:
        if _facts["building"] or _facts.get("for") == today:
            return
        _facts["building"] = True
    try:
        from backtesting import rs_rating as R
        close, (high, low), vol = R.wide_close(), R.wide_high_low(), R.wide_volume()
        want = prev_trading_day(today)
        close, high, low, vol = (x.loc[: pd.Timestamp(want)] for x in (close, high, low, vol))
        got = close.index[-1].date()
        if got != want:
            raise RuntimeError(f"통합 일봉이 {got} 까지라 {want} 기준 조건을 계산하지 않습니다 — 일봉 백필 뒤 다시 켜 주세요")
        themes = pd.read_csv("data/themes.csv", dtype={"stock_code": str}, encoding="utf-8-sig")
        market = json.load(open("data/cache/rs_market.json", encoding="utf-8"))
        try:
            shares = json.load(open("data/cache/rs_shares.json", encoding="utf-8"))
        except OSError:
            shares = {}
        codes = compute(close, high, low, vol, themes, market, shares)
        with _lock:
            _facts.update(asof=got.isoformat(), codes=codes, err=None)
    except Exception as e:                                        # noqa: BLE001 — 실패하면 해당 조건만 '계산 불가'로 남는다
        with _lock:
            _facts.update(err=f"{type(e).__name__}: {e}", codes={})
    finally:
        with _lock:
            _facts["building"], _facts["for"] = False, today


def get(code: str) -> dict:
    return _facts["codes"].get(code, {})


def status() -> dict:
    return {"asof": _facts["asof"], "err": _facts["err"], "building": _facts["building"], "n": len(_facts["codes"])}
