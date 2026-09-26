"""분봉·틱 서비스 테스트용 MarketData 대역 — **체결에서 분봉을 만든다**(그래서 틱 기준가 == 봉 기준가여야 정밀화가 검증된다)."""
import datetime as dt

import numpy as np
import pandas as pd

from studio.domain.conditions.tick import TickDay
from studio.domain.models import Panel

from .fakes import CODES, FakeMarketData, make_panel

SESSION = 23400  # 09:00:00 ~ 15:30:00


def make_ticks(seed: int, n: int = 1500, base: float = 20_000, drift: float = 0.0):
    rng = np.random.default_rng(seed)
    sec = np.sort(rng.integers(0, SESSION, n))
    step = rng.normal(drift, 0.0012, n)
    prc = np.round(base * np.exp(np.cumsum(step)) / 10) * 10
    qty = rng.integers(1, 300, n)
    return sec.astype("int64"), prc.astype(float), qty.astype("int64")


def bars_from_ticks(sec, prc, qty, bar_minutes: int):
    """정규장 봉 끝 라벨(09:05, 09:10 …) 별 OHLCV — 체결 없는 봉은 생략(로더도 NaN)."""
    step = bar_minutes * 60
    out = {}
    for b in range(0, SESSION, step):
        m = (sec >= b) & (sec < b + step)
        if m.any():
            p = prc[m]
            out[b + step] = (p[0], p.max(), p.min(), p[-1], float(qty[m].sum()))
    return out


class IntradayFake(FakeMarketData):
    """일봉(make_panel) + 마지막 `n_days` 거래일의 체결·분봉. 분봉은 같은 체결에서 만든다."""

    def __init__(self, n_days: int = 12, codes=CODES[:5], bar_minutes: int = 5, seed: int = 7, drift: float = 0.0,
                 panel: Panel | None = None):
        super().__init__(panel or make_panel(n=300, seed=3, codes=list(CODES)))
        self.bar_minutes = bar_minutes
        idx = self.panel.close.index
        self.days = list(idx[-n_days:])
        self.tick_codes_ = list(codes)
        self.ticks: dict[tuple[str, dt.date], tuple] = {}
        for ci, c in enumerate(codes):
            for di, d in enumerate(self.days):
                self.ticks[(c, d.date())] = make_ticks(seed * 1000 + ci * 100 + di, base=float(self.panel.close[c].loc[d]) or 20_000,
                                                       drift=drift)
        self._minute_cache: dict[int, Panel] = {}

    # ---- 분봉
    def _build_minute(self, codes, bm) -> Panel:
        cols = {}
        for c in codes:
            rows = {}
            for d in self.days:
                t = self.ticks.get((c, d.date()))
                if t is None:
                    continue
                for end_sec, v in bars_from_ticks(*t, bm).items():
                    rows[d + pd.Timedelta(seconds=9 * 3600 + end_sec)] = v
                # 15:30 종가 단일가 봉 — 끝 라벨 15:30+bm (data-agent 로더와 같은 규약)
                last = t[1][-1]
                rows[d + pd.Timedelta(seconds=9 * 3600 + SESSION + bm * 60)] = (last, last, last, last, 5000.0)
            if rows:
                cols[c] = pd.DataFrame.from_dict(rows, orient="index", columns=["open", "high", "low", "close", "volume"]).sort_index()
        if not cols:
            e = pd.DataFrame(index=pd.DatetimeIndex([]))
            return Panel(e, e, e, e, e, e, e)
        idx = sorted(set().union(*[df.index for df in cols.values()]))
        wide = {k: pd.DataFrame({c: df[k] for c, df in cols.items()}, index=pd.DatetimeIndex(idx)) for k in
                ("open", "high", "low", "close", "volume")}
        close = wide["close"]
        dclose = self.panel.close
        prev = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        day_of = close.index.normalize()
        for d in day_of.unique():
            pos = dclose.index.searchsorted(d, side="left") - 1
            if pos >= 0:
                prev.loc[day_of == d, :] = dclose.iloc[pos].reindex(close.columns).to_numpy()
        return Panel(wide["open"], wide["high"], wide["low"], close, wide["volume"], close * wide["volume"], prev)

    def minute_panel(self, codes, start, end, bar_minutes, source="al"):
        assert bar_minutes == self.bar_minutes
        self.last_source = source
        codes = [c for c in codes if c in self.tick_codes_]
        p = self._build_minute(codes, bar_minutes)
        if p.close.empty:
            return p
        keep = (p.close.index >= pd.Timestamp(start)) & (p.close.index < pd.Timestamp(end) + pd.Timedelta(days=1))
        return Panel(*(getattr(p, k).loc[keep] for k in ("open", "high", "low", "close", "volume", "value", "prev_close")))

    def minute_coverage(self, codes, source="al"):
        return {c: (self.days[0].date(), self.days[-1].date()) for c in codes if c in self.tick_codes_}

    # ---- 체결
    def tick_codes(self):
        return list(self.tick_codes_)

    def tick_days(self, code):
        return sorted(d for (c, d) in self.ticks if c == code)

    def tick_day(self, code, day):
        t = self.ticks.get((code, day))
        if t is None:
            return None
        dclose = self.panel.close[code]
        prev = dclose[dclose.index < pd.Timestamp(day)]
        return TickDay(code, day, t[0], t[1], t[2], float(prev.iloc[-1]) if len(prev) else None)

    def data_ranges(self):
        r = super().data_ranges()
        r["minute_al"] = (self.days[0].date(), self.days[-1].date())
        r["minute_krx"] = (self.days[0].date(), self.days[-1].date())
        r["tick_al"] = (self.days[0].date(), self.days[-1].date())
        return r
