"""서비스 테스트용 MarketData 대역 — 합성 일봉(랜덤워크)을 메모리에서 준다."""
import datetime as dt

import numpy as np
import pandas as pd

from studio.domain.models import Panel

CODES = ["000010", "000020", "000030", "000045", "000050", "000060", "000070", "005930"]
NAMES = {"000010": "가나다", "000020": "라마바스팩", "000030": "사아자", "000045": "가나다우B",
         "000050": "성우", "000060": "차카타", "000070": "파하", "005930": "삼성전자"}


def make_panel(n: int = 400, seed: int = 1, trend: float = 0.0005, codes=CODES) -> Panel:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n)
    o, h, l, c, v = ({} for _ in range(5))
    for code in codes:
        close = 10_000 * np.exp(np.cumsum(rng.normal(trend, 0.02, n)))
        op = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.005, n))
        o[code], c[code] = op, close
        h[code] = np.maximum(op, close) * (1 + rng.uniform(0, 0.01, n))
        l[code] = np.minimum(op, close) * (1 - rng.uniform(0, 0.01, n))
        v[code] = rng.integers(100_000, 1_000_000, n).astype(float)
    f = lambda d: pd.DataFrame(d, index=idx)  # noqa: E731
    close, vol = f(c), f(v)
    return Panel(f(o), f(h), f(l), close, vol, close * vol, close.ffill().shift(1))


class FakeMarketData:
    def __init__(self, panel: Panel | None = None, *, kospi: bool = True):
        self.panel = panel or make_panel()
        idx = self.panel.close.index
        self._index = {k: pd.DataFrame({"close": np.linspace(300_000, 330_000, len(idx))}, index=idx)
                       for k in ("kospi", "kosdaq")} if kospi else {}
        self.info = pd.DataFrame({
            "name": pd.Series(NAMES), "sector": "업종", "market": "거래소"})
        self.info.loc["000030", "market"] = "코스닥"

    def load_panel(self, start, end, warmup_bars, codes=None):
        p = self.panel
        idx = p.close.index
        first = int(np.searchsorted(idx, pd.Timestamp(start), side="left"))
        keep = (np.arange(len(idx)) >= max(0, first - warmup_bars)) & (idx <= pd.Timestamp(end))
        cols = list(codes) if codes is not None else list(p.close.columns)
        cols = [c for c in cols if c in p.close.columns]
        return Panel(*(getattr(p, k).loc[keep, cols] for k in
                       ("open", "high", "low", "close", "volume", "value", "prev_close")))

    def index_frames(self):
        return self._index

    def stock_info(self):
        return self.info

    def mega_cap_codes(self):
        return frozenset({"005930"})

    def data_ranges(self):
        idx = self.panel.close.index
        r = (idx[0].date(), idx[-1].date())
        return {"daily": r, "kospi": r, "kosdaq": r}


def spec_dict(**over) -> dict:
    """close 가 20일 최고가를 넘으면 진입, 10일 최저가 아래면 청산 — 기본 포트폴리오 스모크용."""
    hi = {"kind": "ind", "name": "highest", "params": {"src": "high", "n": 20}}
    lo = {"kind": "ind", "name": "lowest", "params": {"src": "low", "n": 10}}
    close = {"kind": "field", "name": "close"}
    d = {
        "version": 1, "name": "테스트", "mode": "daily_portfolio",
        "period": {"start": "2022-12-01", "end": "2023-07-31"},
        "universe": {"type": "all", "exclude": ["spac", "preferred", "mega_cap"]},
        "strategy": {"source": "builder",
                     "entry": {"logic": "all", "items": [{"left": close, "op": "gt", "right": hi}]},
                     "exit": {"logic": "any", "items": [{"left": close, "op": "lt", "right": lo}]}},
        "exits": {}, "portfolio": {"max_positions": 3}, "fills": {"volume_cap_pct": None},
    }
    d.update(over)
    return d


def dates(s: str) -> dt.date:
    return dt.date.fromisoformat(s)
