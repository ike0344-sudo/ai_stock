"""종목 검색·차트 봉 — `/api/stocks` (설계서 §4.1, §5.4 조건 편집기 종목 지정·결과의 거래 캔들 서랍).

일봉(`1d`)과 분봉(`1m`~`60m`, 출처 al=통합|krx)을 준다. 봉은 미래 정보와 무관한 **과거 그대로의 값**이다.
분봉의 시각 `t` 는 봉 **끝** 시각이다(로더 규약). 체결(틱) 봉은 없다 — 틱 거래의 캔들은 1분봉으로 본다.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

import pandas as pd

from .ports import MarketData

CODE_RE = re.compile(r"^[0-9A-Z]{6}$")
MAX_BARS = 6000
MINUTE_RE = re.compile(r"^(1|3|5|10|15|30|60)m$")
MAX_MINUTE_DAYS = 45  # 분봉 한 번에 받는 달력일 상한(응답 크기)
SOURCES = ("al", "krx")


class StockNotFound(Exception):
    pass


class BarsNotSupported(Exception):
    pass


def search(md: MarketData, q: str, limit: int = 20) -> list[dict[str, Any]]:
    """이름 부분 일치 또는 코드 앞 일치. 정확히 일치하는 것을 먼저."""
    q = (q or "").strip()
    if not q:
        return []
    info = md.stock_info()
    needle = q.lower()
    name = info["name"].fillna("").astype(str)
    hit = info[name.str.lower().str.contains(re.escape(needle)) | info.index.to_series().str.lower().str.startswith(needle)]
    hit = hit.assign(_exact=(hit.index.to_series().str.lower() == needle) | (name.loc[hit.index].str.lower() == needle),
                     _name=name.loc[hit.index]).sort_values(["_exact", "_name"], ascending=[False, True])
    return [{"code": c, "name": r["name"] if isinstance(r["name"], str) else None,
             "sector": r.get("sector") if isinstance(r.get("sector"), str) else None,
             "market": r.get("market") if isinstance(r.get("market"), str) else None}
            for c, r in hit.head(limit).iterrows()]


def _minute_bars(md: MarketData, code: str, bar_minutes: int, start: dt.date | None, end: dt.date | None, source: str) -> dict[str, Any]:
    if source not in SOURCES:
        raise BarsNotSupported(f"분봉 출처는 {SOURCES} 중 하나: {source!r}")
    rng = md.data_ranges().get(f"minute_{source}")
    if rng is None:
        raise StockNotFound(code)
    hi = min(end or rng[1], rng[1])
    lo = max(start or hi - dt.timedelta(days=5), rng[0], hi - dt.timedelta(days=MAX_MINUTE_DAYS))
    panel = md.minute_panel([code], lo, hi, bar_minutes, source)
    if code not in panel.close.columns:
        raise StockNotFound(code)
    df = pd.DataFrame({k: getattr(panel, k)[code] for k in ("open", "high", "low", "close", "volume")}).dropna(subset=["close"]).tail(MAX_BARS)
    info = md.stock_info()
    return {
        "code": code, "name": info["name"].get(code) if code in info.index else None, "interval": f"{bar_minutes}m", "source": source,
        "bars": [{"t": i.strftime("%Y-%m-%d %H:%M"), "o": float(r.open), "h": float(r.high), "l": float(r.low), "c": float(r.close),
                  "v": float(r.volume)} for i, r in df.iterrows()],
    }


def intraday_sources(md: MarketData, start: dt.date, end: dt.date) -> dict[str, Any]:
    """분봉·체결 사용 가능 기간 — [start, end] 를 출처별로 몇 종목이 덮는가(전 기간 보유 full · 일부만 partial). 화면이 출처를 고를 근거."""
    codes = list(md.stock_info().index)
    ranges = md.data_ranges()
    minute: dict[str, Any] = {}
    for src in SOURCES:
        cov = md.minute_coverage(codes, src)
        full = sum(1 for a, b in cov.values() if a <= start and b >= end)
        overlap = sum(1 for a, b in cov.values() if a <= end and b >= start)
        rng = ranges.get(f"minute_{src}")
        minute[src] = {"total": len(cov), "full": full, "partial": overlap - full, "range": [str(rng[0]), str(rng[1])] if rng else None}
    tcodes = md.tick_codes()
    days = sorted({d for c in tcodes for d in md.tick_days(c)})
    return {"minute": minute, "tick": {"codes": len(tcodes), "days": len(days), "first": str(days[0]) if days else None,
                                       "last": str(days[-1]) if days else None, "days_in_range": sum(1 for d in days if start <= d <= end)}}


def bars(md: MarketData, code: str, interval: str, start: dt.date | None, end: dt.date | None, source: str = "al") -> dict[str, Any]:
    m = MINUTE_RE.fullmatch(interval)
    if m:
        return _minute_bars(md, code, int(m.group(1)), start, end, source)
    if interval != "1d":
        raise BarsNotSupported(f"'{interval}' 봉은 지원하지 않는다(1d · 1m·3m·5m·10m·15m·30m·60m)")
    ranges = md.data_ranges()["daily"]
    lo, hi = start or ranges[0], min(end or ranges[1], ranges[1])
    panel = md.load_panel(lo, hi, 0, [code])
    if code not in panel.close.columns:
        raise StockNotFound(code)
    df = pd.DataFrame({k: getattr(panel, k)[code] for k in ("open", "high", "low", "close", "volume")}).dropna(subset=["close"])
    df = df[(df.index >= pd.Timestamp(lo)) & (df.index <= pd.Timestamp(hi))].tail(MAX_BARS)
    info = md.stock_info()
    return {
        "code": code, "name": info["name"].get(code) if code in info.index else None, "interval": interval,
        "bars": [{"t": str(i.date()), "o": float(r.open), "h": float(r.high), "l": float(r.low), "c": float(r.close),
                  "v": float(r.volume)} for i, r in df.iterrows()],
    }
