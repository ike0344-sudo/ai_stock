"""MarketData 구현 — 일봉·지수·종목 정보를 datahub 카탈로그 경로로 읽는다 (설계서 §2.2(e), §2.3).

일봉  `daily_all_cache`(=backtesting.daily_cache.load_daily_all) — 캐시가 원본 CSV 보다 낡으면 그 함수가 다시 만든다.
지수  `index` — `data/index/{kind}/{code}.csv` (catalog.path("index", kind=..., code=...))
이름  `reference_static`(stock_names.json, also=sectors.csv)   시장 `sophie_reference`/universe.csv(market 열)
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from backtesting.daily_cache import load_daily_all
from data_exclude import MEGA_CAP_EXCLUDE
from datahub import catalog
from studio.domain.models import Panel

_INDEX_CODES = {"kospi": "001", "kosdaq": "101"}


def _index_csv(name: str) -> Path:
    """지수 csv 경로 — 카탈로그 `index` = `data/index/{kind}/{code}.csv`."""
    return catalog.path("index", kind="daily", code=_INDEX_CODES[name])


_FALLBACK = object()


def _fast_tick_day(code: str, day: dt.date, prev_close: float | None):
    """`intraday_data.load_ticks`+`load_tick_day` 의 parquet 전용 빠른 판 — 같은 규칙을 벡터로:
    시각 문자열 → 초, 원본이 역시간순인지 검사(어긋남 > max(5행, 5%) 이면 공식 로더가 예외를 던지도록 넘김), 행 뒤집기(같은 초 안 실제 순서),
    어긋남이 있으면 초 단위 안정 정렬, 정규장(09:00:00~15:30:00) 필터, sec = 09:00:00 기준 격자 초. 파일이 없거나 parquet 이 아니면 _FALLBACK."""
    import numpy as np
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    from studio.domain.conditions.tick import TickDay
    path = catalog.path("tick_al", code=code, date=day.isoformat())
    if not path.is_file():
        return _FALLBACK
    t = pq.read_table(path, columns=["time", "cur_prc", "trde_qty"], use_threads=False)  # 작은 파일(2만 행)은 스레드 풀 기동이 읽기보다 비싸다(11ms→1.7ms)
    tm = pc.cast(t.column("time"), "int64").to_numpy()  # "095959" → 95959 (앞자리 0 은 숫자 비교에 영향 없음: 6자리로 채운 문자열 비교와 같다)
    n = len(tm)
    prc, qty = t.column("cur_prc"), t.column("trde_qty")
    if not (pc.is_valid(prc).to_numpy(zero_copy_only=False).all() and str(prc.type).startswith("int")
            and str(qty.type).startswith("int")):
        return _FALLBACK
    inv = int((tm[:-1] < tm[1:]).sum()) if n > 1 else 0
    if inv > max(5, 0.05 * n):
        return _FALLBACK  # 공식 로더가 ValueError 로 거부한다
    tm = tm[::-1]
    prc = np.abs(prc.to_numpy()[::-1]).astype("int64")
    qty = np.abs(qty.to_numpy()[::-1]).astype("int64")
    sec = (tm // 10000) * 3600 + ((tm // 100) % 100) * 60 + tm % 100
    if inv:
        o = np.argsort(sec, kind="stable")
        sec, prc, qty = sec[o], prc[o], qty[o]
    m = (sec >= 9 * 3600) & (sec <= 15 * 3600 + 30 * 60)
    if not m.any():
        return None
    return TickDay(code, day, (sec[m] - 9 * 3600).astype("int64"), prc[m], qty[m], prev_close)


class LocalMarketData:
    def __init__(self) -> None:
        self._daily: pd.DataFrame | None = None
        self._index: dict[str, pd.DataFrame] | None = None
        self._info: pd.DataFrame | None = None
        self._mcov: dict[str, dict[str, tuple[dt.date, dt.date]]] = {}  # 출처별 종목 커버리지 캐시
        self._close_idx: dict[str, tuple[int, int]] | None = None  # 종목 → (시작, 끝) 위치, 아래 두 배열은 (종목, 날짜) 정렬
        self._close_dates = self._close_vals = None

    # ---- 일봉
    def _all_daily(self) -> pd.DataFrame:
        if self._daily is None:
            d = load_daily_all(
                daily_dir=str(catalog.path("daily", code="X").parent),
                cache_path=str(catalog.path("daily_all_cache")),
            ).copy()
            d["date"] = pd.to_datetime(d["date"])
            self._daily = d
        return self._daily

    def load_panel(self, start: dt.date, end: dt.date, warmup_bars: int,
                   codes: Sequence[str] | None = None) -> Panel:
        d = self._all_daily()
        if codes is not None:
            d = d[d["code"].isin(list(codes))]
        end_ts = pd.Timestamp(end)
        dates = np.sort(d["date"].unique())
        dates = dates[dates <= end_ts.to_datetime64()]
        first = int(np.searchsorted(dates, pd.Timestamp(start).to_datetime64(), side="left"))
        lo = dates[max(0, first - warmup_bars)] if len(dates) else end_ts
        d = d[(d["date"] >= lo) & (d["date"] <= end_ts)]

        def wide(col: str) -> pd.DataFrame:
            return d.pivot(index="date", columns="code", values=col).astype(float)

        close = wide("close")
        volume = wide("volume")
        # 거래정지일은 캐시가 직전 종가로 채우고 거래량 0 — 그래도 종목별 직전 유효 종가를 기준가로 쓴다
        prev_close = close.ffill().shift(1)
        return Panel(wide("open"), wide("high"), wide("low"), close, volume, close * volume, prev_close)

    # ---- 지수
    def index_frames(self) -> dict[str, pd.DataFrame]:
        if self._index is None:
            out = {}
            for name in _INDEX_CODES:
                df = pd.read_csv(_index_csv(name), encoding="utf-8-sig")
                df["date"] = pd.to_datetime(df["date"])
                out[name] = df.set_index("date").sort_index()
            self._index = out
        return self._index

    # ---- 종목 정보
    def stock_info(self) -> pd.DataFrame:
        if self._info is None:
            ref = catalog.dataset("reference_static")
            names = json.loads(catalog.path("reference_static").read_text(encoding="utf-8"))
            info = pd.DataFrame({"name": pd.Series(names)})
            sect = next((catalog.root() / p for p in ref.also if p.endswith("sectors.csv")), None)
            if sect is not None and sect.exists():
                info["sector"] = pd.read_csv(sect, dtype=str, encoding="utf-8-sig").set_index("stock_code")["sector"]
            else:
                info["sector"] = np.nan
            uni = self._universe_csv()
            info["market"] = uni.set_index("code")["market"] if uni is not None else np.nan
            self._info = info
        return self._info

    @staticmethod
    def _universe_csv() -> pd.DataFrame | None:
        ds = catalog.dataset("sophie_reference")
        for base in [ds.path, *ds.also]:  # 기본 → dist 사본 순
            f = catalog.root() / base / "universe.csv"
            if f.exists():
                return pd.read_csv(f, dtype=str, encoding="utf-8-sig")
        return None

    def mega_cap_codes(self) -> frozenset[str]:
        return frozenset(MEGA_CAP_EXCLUDE)

    # ---- 분봉·체결 (intraday_data 로더에 위임)
    def minute_panel(self, codes: Sequence[str], start: dt.date, end: dt.date, bar_minutes: int, source: str = "al") -> Panel:
        from . import intraday_data as I
        return I.load_minute_panel_wide(codes, start, end, bar_minutes, "regular", daily=self._all_daily(), strict=False,
                                        source=source)  # 출처는 항상 호출자(spec.intraday.source)가 명시 — 패널과 커버리지가 같은 출처

    def _minute_cov(self, source: str) -> dict[str, tuple[dt.date, dt.date]]:
        """그 출처의 종목별 (첫 날, 끝 날) — `minute_availability` (파일 전체를 안 읽는다), 출처별로 한 번."""
        if source not in self._mcov:
            from . import intraday_data as I
            av = I.minute_availability(source)
            self._mcov[source] = {c: (r["first"], r["last"]) for c, r in av.iterrows()}
        return self._mcov[source]

    def minute_coverage(self, codes: Sequence[str], source: str = "al") -> dict[str, tuple[dt.date, dt.date]]:
        cov = self._minute_cov(source)
        return {c: cov[c] for c in codes if c in cov}

    def tick_codes(self) -> list[str]:
        base = catalog.path("tick_al", code="X", date="x").parent.parent
        return sorted(p.name for p in base.iterdir() if p.is_dir()) if base.is_dir() else []

    def tick_days(self, code: str) -> list[dt.date]:
        from . import intraday_data as I
        return I.tick_days(code)

    def _prev_close(self, code: str, day: dt.date) -> float | None:
        """day 보다 앞선 마지막 일봉 종가(D−1) — `intraday_data.prev_close_of` 와 같은 값. 그쪽은 호출마다 일봉 전체(170만 행)를
        걸러 종목 하나의 표를 만든다(57ms/호출 — 틱 모드 B 프로파일에서 40%) → 종목별 (날짜, 종가) 구간을 한 번만 색인해 이분탐색."""
        if self._close_idx is None:
            d = self._all_daily()[["code", "date", "close"]]
            d = d[d["close"].notna()].sort_values(["code", "date"], kind="stable")
            codes = d["code"].to_numpy()
            starts = np.r_[0, np.flatnonzero(codes[1:] != codes[:-1]) + 1]
            ends = np.r_[starts[1:], len(codes)]
            self._close_dates = d["date"].to_numpy(dtype="datetime64[ns]")
            self._close_vals = d["close"].to_numpy(dtype=float)
            self._close_idx = {codes[a]: (int(a), int(b)) for a, b in zip(starts, ends)}
        rng = self._close_idx.get(code)
        if rng is None:
            return None
        a, b = rng
        i = int(np.searchsorted(self._close_dates[a:b], np.datetime64(pd.Timestamp(day), "ns"), side="left")) - 1
        return float(self._close_vals[a + i]) if i >= 0 else None

    def tick_day(self, code: str, day: dt.date):
        """하루치 `TickDay`. parquet 은 필요한 열(time·cur_prc·trde_qty)만 읽어 벡터로 풀고(공식 로더와 배열이 같음 — 테스트가 실제 파일로
        대조), csv·이상 자료형·역시간 검사 실패 같은 경우는 공식 로더(`intraday_data.load_tick_day`)로 넘긴다."""
        from . import intraday_data as I
        prev = self._prev_close(code, day)
        try:
            fast = _fast_tick_day(code, day, prev)
        except Exception:  # noqa: BLE001 — 빠른 길은 최적화일 뿐: 무엇이든 어긋나면 공식 로더가 판단(예외 포함)한다
            fast = _FALLBACK
        if fast is not _FALLBACK:
            return fast
        return I.load_tick_day(code, day, prev, strict=False)

    # ---- 데이터 범위
    def data_ranges(self) -> dict[str, tuple[dt.date, dt.date]]:
        d = self._all_daily()["date"]
        out = {"daily": (d.min().date(), d.max().date())}
        for name, df in self.index_frames().items():
            out[name] = (df.index.min().date(), df.index.max().date())
        for src in ("al", "krx"):  # 분봉 범위 키는 출처별(spec.validate_against 가 intraday.source 로 고른다)
            cov = self._minute_cov(src)
            if cov:
                out[f"minute_{src}"] = (min(a for a, _ in cov.values()), max(b for _, b in cov.values()))
        tdays = [d for c in self.tick_codes() for d in self.tick_days(c)]
        if tdays:
            out["tick_al"] = (min(tdays), max(tdays))
        return out
