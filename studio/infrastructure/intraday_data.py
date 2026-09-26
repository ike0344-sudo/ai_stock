"""분봉·체결 로더 — 스튜디오 엔진(분봉 2단계·틱 모드)이 읽는 입구 (설계서 §3.7 시점 규칙, §3.2 intraday·tick, §8.7 P8).

`market_data.py`(일봉·지수)와 나란히 있지만 별개 파일이다. 카탈로그 경로만 쓴다: 분봉 `minute_al_archive`(통합 KRX+NXT),
체결 `tick_al`(통합), 일봉 `daily_all_cache`(순위 재료). 계층 규칙(§9.3): domain·datahub 읽기 API·`backtesting.daily_cache` 만 import.

## 분봉 출처 — `source="al"`(기본) | `"krx"` (2026-09-25 추가, 기본값은 09-26 사용자 결정으로 통합)
- **기본은 통합(al)**: 사용자 규칙(2026-09-01) "체결·분봉·거래대금은 통합(KRX+NXT)만, 예외 없음". **krx 는 사용자가 명시적으로 고를 때만** — 통합 보관소가 짧은(종목별 1~2개월) 대신 긴 과거가 필요할 때의 선택지.
- **krx**(선택) = 기존 `data/stocks/minute`(카탈로그 `minute_krx`, **KRX 전용**): 1,055종목, 2025-07-01 부터(520여 종목은 2025-07~08 시작, 1,044종목이 2026-09-23 까지), 긴 과거용.
- **al**(기본) = 통합 보관소 `minute_al_archive`(KRX+NXT): 2,041종목이지만 종목별 보관 기간이 1~2개월(소수만 1년) — 최근·NXT 포함 분석용.
- 반환 모양(열·라벨·정규장 규칙·자료형)은 두 출처가 같다. 리샘플은 같은 함수(P8)를 탄다.
- **차이(2026-08-25~09-23, 실제 5종목 비교)**: KRX 분봉은 **NXT 체결이 빠져** 정규장 거래량이 통합보다 낮다 — 월 합계 KRX/통합 = 삼성전자 0.76·NAVER 0.81·알테오젠 0.62·SK스퀘어 0.94·LS ELECTRIC 0.68
  (일별 0.53~0.89), 첫 봉 09:00 은 0.88, **15:30 종가 단일가 봉은 1.00(동일)**. 가격은 같은 종목이라 거의 같다: 공통 봉에서 종가 일치 78~87%,
  차이 중앙값 0bp·상위 1% 10~25bp, 통합의 고가 ≥ KRX 고가·저가 ≤ KRX 저가가 **100%**(통합이 NXT 체결만큼 범위가 넓다). → 거래량·거래대금 조건은 출처를 섞지 말 것.
- KRX 봉 라벨: 09:00~15:19 매분 + **15:30**(종가 단일가) + 15:35(소량 시간외) — 15:20~15:29 는 동시호가라 봉이 없다(통합도 같다). 정규장 필터 `09:00 ≤ t ≤ 15:30` 은 두 출처에 같이 맞는다.
- **krx 는 `session="regular"` 만**: KRX 파일에는 2026-09-14 부터 NXT 애프터 봉(16:00~19:59)이 **최근 며칠에만** 섞여 있어(갱신기가 그렇게 받았다) 정규장 밖은 날짜마다 다르다.
- 파일 형식: CSV 가 원본이고 parquet 사본이 함께 있을 수 있다 — parquet 이 CSV 보다 새것일 때만 parquet 을 읽는다(`_read_local` 과 같은 규칙, 낡은 사본이 조용히 읽히는 사고 방지).
- 기간 확인: `minute_coverage(code, source)`(종목별 첫·끝) · `minute_availability(source)`(전 종목 표) · `minute_sources_for_range(start, end)`("이 기간은 출처별로 몇 종목이 덮나").

## 분봉 — 기본은 정규장(09:00~15:30)
통합(AL) 분봉은 NXT 프리마켓(08:00~)·애프터마켓(~20:00)까지 담는다(하루 약 650분, 정규장 391분). 그런데 전략·비용·신호 규칙은 전부
KRX 정규장 기준으로 정의돼 있어 시간외 봉이 섞이면 (1) 리샘플 마지막 봉이 시간외를 삼키고 (2) 하루 첫 봉·시가가 08:00 으로 잡힌다.
그래서 기본 `session="regular"`(봉 라벨 09:00 ≤ t ≤ 15:30 — 15:30 은 종가 단일가 체결 봉), 시간외까지 필요하면 `session="full"`.
(통합 분봉의 정규장 구간에는 NXT 체결이 함께 들어 있다 — KRX 전용 `minute_krx` 와 거래량이 다르다. 거래대금 신호는 통합 기준이 규칙이다.)

리샘플은 기존 `backtesting.data_loader._resample_minute` 와 **같은 규칙**(하루 단위, 그날 첫 봉을 기준점 origin 으로)이다 — P8 이 두 결과의
동일성을 고정한다. 코드는 그 함수를 import 하지 않고(계층 규칙) 같은 8줄을 여기 둔다. 결과 자료형도 같다: 1분은 int64, **2분 이상은 리샘플이 빈 버킷에 NaN 을 거치므로 open·high·low·close 가 float64(값은 정수)**, volume 은 int64. 분봉에는 거래대금 열이 없다(`value` 를 종가×거래량으로
어림하면 분 단위에서는 크게 틀린다 — 필요하면 호출자가 명시적으로 근사한다).

## 체결 — 오름차순, 같은 초 순서 보존
원본(`ka10079`)은 **역시간순**(최신이 앞)이고 같은 초의 여러 체결도 그 안에서 역순이다. 시각으로 정렬하면 같은 초 안의 순서가 정렬 알고리즘에
맡겨지므로, **행 순서를 통째로 뒤집는다**(뒤집으면 실제 체결 순서). 원본이 역시간순인지 검사한다 — 시각이 커지는 곳이 max(5행, 5%) 를 넘으면 예외(오름차순으로 저장된 파일 등 조용히 틀린 순서로 백테스트하지 않게).
**실제 파일에는 어긋난 곳이 있다**(실측: 체결 4,423파일 중 1,762개(40%), 파일당 대개 1~26곳·최대 232곳/40,243행(278470 09-18) — 오름차순 저장 파일이라면 수만 곳이다) — 그 정도는 `to_grid` 와 똑같이 초 단위로 안정 정렬해 읽는다. 열은 `price`(체결가, 절댓값)·`qty`(체결량)·`sig`(대비기호 1상한 2상승 3보합 4하한 5하락)·`sec`(자정 후 초),
인덱스는 `ts`(같은 값이 여럿일 수 있는 DatetimeIndex, 오름차순 안정).

## 엔진·조건식 입력 계약에 맞춘 얇은 진입점 (strategy-agent 2026-09-25 "module-6 조건식 함수 서명")
- `load_tick_day(code, day)` → `TickDay`(sec = 09:00:00 기준 격자 초 0..23400, 시간순 — `_precursor_fastpath.to_grid` 의 tick_sec·tick_prc·tick_qty 와 **같은 배열**, 테스트로 확인).
- `load_minute_panel_wide(codes, start, end, bar_minutes)` → `Panel`(index = **봉 끝 시각**, columns = 종목코드, prev_close = 그날의 전일 종가(일봉 D−1), value = 종가×거래량).

## 범위 밖 요청은 조용히 비지 않는다
보관소·체결 파일이 요청 기간을 덮지 못하면 `DataRangeError`(속성 `available`: 가진 범위)를 던진다. 빈 표가 조용히 돌아가 "거래 0건" 백테스트가
나오는 사고를 막는다. 부분 데이터가 필요하면 `strict=False`.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Collection, Iterable

import numpy as np
import pandas as pd

from datahub import catalog
from datahub import minute_al_archive
from studio.domain.conditions.tick import TickDay
from studio.domain.models import Panel

MAX_DISORDER_ROWS, MAX_DISORDER_SHARE = 5, 0.05     # 이보다 많이 어긋난 파일은 역시간순 가정이 깨진 것(예: 오름차순 저장) — 거부
BAR_MINUTES = (1, 3, 5, 10, 15, 30, 60)
REGULAR_OPEN, REGULAR_CLOSE = dt.time(9, 0), dt.time(15, 30)
MINUTE_COLS = ["open", "high", "low", "close", "volume"]
TICK_COLS = ["price", "qty", "sig", "sec"]


class DataRangeError(ValueError):
    """요청 기간·날짜를 데이터가 덮지 못한다. `available` = 가진 범위(없으면 None) — 호출자가 사용자에게 그대로 보여 준다."""

    def __init__(self, what: str, requested: tuple, available: tuple | None):
        self.what, self.requested, self.available = what, requested, available
        have = f"{available[0]} ~ {available[1]}" if available else "없음"
        super().__init__(f"{what}: 요청 {requested[0]} ~ {requested[1]} 을(를) 덮지 못함 — 가진 범위 {have}")


@dataclass(frozen=True)
class Coverage:
    first: pd.Timestamp
    last: pd.Timestamp

    @property
    def dates(self) -> tuple[dt.date, dt.date]:
        return self.first.date(), self.last.date()


# ============================================================ 분봉


def resample_minutes(df: pd.DataFrame, target_minutes: int) -> pd.DataFrame:
    """1분봉 → target_minutes. `backtesting.data_loader._resample_minute` 와 **같은 결과**(값·인덱스·자료형, P8): 하루 단위로 나누고
    그날 첫 봉을 기준점(origin)으로 버킷을 만든다. 그 함수는 하루마다 pandas resample 을 부르느라 종목 200개×60일에 45초가 걸려,
    같은 규칙을 한 번의 groupby 로 옮겼다(버킷 = (봉 시각 − 그날 첫 봉) // N분, 라벨 = 첫 봉 + 버킷×N분, 빈 버킷은 생기지 않는다).
    자료형까지 같게: 원본은 하루 안에 **빈 버킷이 하나라도 있으면** 그 하루가 NaN 을 거쳐 float64 가 되고, concat 하면 전체가 float64 가 된다."""
    if df.empty or target_minutes <= 1:
        return df
    idx = df.index
    day = idx.normalize()
    first = pd.Series(idx, index=idx).groupby(day).transform("first")
    bucket = ((idx - pd.DatetimeIndex(first)) // pd.Timedelta(minutes=1)) // target_minutes
    label = pd.DatetimeIndex(first) + pd.to_timedelta(bucket * target_minutes, unit="min")
    g = df.groupby(label)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last(),
                        "volume": g["volume"].sum()})
    out.index.name = df.index.name
    last_bucket = pd.Series(bucket, index=idx).groupby(day).transform("max")
    expected = int((pd.Series(last_bucket).groupby(day).first() + 1).sum())      # 하루의 첫~끝 버킷 수의 합
    if expected > len(out):
        out[["open", "high", "low", "close"]] = out[["open", "high", "low", "close"]].astype("float64")
    return out


def session_filter(df: pd.DataFrame, session: str) -> pd.DataFrame:
    if session == "full":
        return df
    if session != "regular":
        raise ValueError(f"session 은 regular|full: {session!r}")
    keep = np.array([REGULAR_OPEN <= x <= REGULAR_CLOSE for x in df.index.time], dtype=bool)   # 빈 리스트로 df[[]] 를 하면 열 선택이 된다
    return df.loc[keep]


SOURCES = ("krx", "al")
DEFAULT_SOURCE = "al"           # 통합(KRX+NXT) — 2026-09-01 사용자 규칙 "통합(AL)만, 예외 없음". "krx" 는 사용자가 고를 때만(긴 과거 2025-07~)


def _check_source(source: str | None, session: str = "regular") -> str:
    source = source or DEFAULT_SOURCE
    if source not in SOURCES:
        raise ValueError(f"source 는 {SOURCES} 중 하나: {source!r}")
    if source == "krx" and session != "regular":
        raise ValueError("krx 출처는 session='regular' 만 — KRX 분봉 파일의 정규장 밖 봉(NXT 애프터 16:00~)은 최근 며칠에만 섞여 있어 날짜마다 다르다")
    return source


def _krx_file(code: str):
    """KRX 분봉 파일. parquet 이 있고 CSV 보다 새것(같거나 나중)이면 parquet, 아니면 CSV — `backtesting.data_loader._read_local` 과 같은 규칙
    (갱신기는 CSV 에만 쓰므로 parquet 만 우선하면 낡은 사본이 조용히 읽힌다)."""
    csv = catalog.path("minute_krx", code=code)
    pq = csv.with_suffix(".parquet")
    if pq.is_file() and (not csv.is_file() or pq.stat().st_mtime >= csv.stat().st_mtime):
        return pq
    return csv if csv.is_file() else None


def _empty_minutes() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="int64") for c in MINUTE_COLS}, index=pd.DatetimeIndex([], name="date"))


def _read_minute(code: str, source: str) -> pd.DataFrame:
    """그 출처의 1분봉 전체(오름차순·중복 없음, 인덱스 `date`, 열 MINUTE_COLS). 없으면 빈 표."""
    if source == "al":
        return minute_al_archive.read(code)
    f = _krx_file(code)
    if f is None:
        return _empty_minutes()
    if f.suffix == ".parquet":
        df = pd.read_parquet(f)
    else:                                                        # pyarrow 엔진이 5배 빠르다(11.7만 행 0.10초 → 0.02초) — 종목 수백 개를 읽는 사전 필터가 이 시간에 좌우된다
        df = pd.read_csv(f, engine="pyarrow")
        df = df.set_index(pd.to_datetime(df.iloc[:, 0])).drop(columns=df.columns[0])
    df.index = pd.DatetimeIndex(df.index).astype("datetime64[ns]")
    df.index.name = "date"
    df = df[MINUTE_COLS]
    if not df.index.is_monotonic_increasing:
        df = df.sort_index(kind="stable")               # 안정 정렬 — 같은 시각이 둘이면 파일에서 뒤에 있는 행이 뒤에 남아 keep="last" 가 그 행을 고른다
    if not df.index.is_unique:
        df = df[~df.index.duplicated(keep="last")]
    return df


def _span(code: str, source: str) -> Coverage | None:
    """첫·끝 시각만(파일 전체를 읽지 않는다): CSV 는 첫 줄·끝 줄, parquet 은 통계."""
    f = _krx_file(code) if source == "krx" else minute_al_archive.archive_path(code)
    if f is None or not f.is_file():
        return None
    if f.suffix == ".csv":
        with open(f, "rb") as fh:
            fh.readline()
            first = fh.readline().decode("utf-8", errors="ignore").split(",")[0]
            fh.seek(max(0, f.stat().st_size - 300))
            tail = fh.read().decode("utf-8", errors="ignore").strip().splitlines()
        if not first or not tail or not tail[-1][:4].isdigit():
            return None
        return Coverage(pd.Timestamp(first), pd.Timestamp(tail[-1].split(",")[0]))
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(f)
    i = pf.schema_arrow.names.index("date")
    st = [pf.metadata.row_group(g).column(i).statistics for g in range(pf.metadata.num_row_groups)]
    return Coverage(pd.Timestamp(min(x.min for x in st)), pd.Timestamp(max(x.max for x in st))) if st else None


def minute_coverage(code: str, source: str | None = None) -> Coverage | None:
    """그 출처가 그 종목에 대해 가진 첫·끝 시각. 파일이 없으면 None."""
    return _span(code, _check_source(source))


def minute_availability(source: str | None = None, codes: Iterable[str] | None = None) -> pd.DataFrame:
    """출처별 사용 가능 기간 표 — 인덱스 code, 열 first·last(datetime.date). 엔진·화면이 "이 기간은 어느 출처로 몇 종목"을 보여주는 재료.
    codes 를 주지 않으면 그 출처의 파일이 있는 종목 전부."""
    source = _check_source(source)
    if codes is None:
        base = catalog.path("minute_al_archive" if source == "al" else "minute_krx", code="x").parent
        codes = sorted({p.stem for p in base.glob("*.parquet")} | ({p.stem for p in base.glob("*.csv")} if source == "krx" else set()))
    rows = {}
    for c in codes:
        cv = _span(c, source)
        if cv is not None:
            rows[c] = (cv.first.date(), cv.last.date())
    return pd.DataFrame(list(rows.values()), index=pd.Index(list(rows), name="code"), columns=["first", "last"])


def minute_sources_for_range(start: dt.date, end: dt.date, codes: Iterable[str] | None = None) -> dict[str, dict[str, int]]:
    """[start, end] 를 출처별로 몇 종목이 덮는가: {출처: {total(파일 있는 종목), full(전 기간 보유), partial(일부만)}}."""
    out = {}
    for src in SOURCES:
        av = minute_availability(src, codes)
        full = int(((av["first"] <= start) & (av["last"] >= end)).sum()) if len(av) else 0
        overlap = int(((av["first"] <= end) & (av["last"] >= start)).sum()) if len(av) else 0
        out[src] = {"total": len(av), "full": full, "partial": overlap - full}
    return out


def load_minute_bars(code: str, start: dt.date, end: dt.date, bar_minutes: int = 1, session: str = "regular",
                     strict: bool = True, source: str | None = None) -> pd.DataFrame:
    """[start, end](양 끝 포함, 날짜 단위) 분봉. 인덱스 `date`(DatetimeIndex 오름차순), 열 open·high·low·close·volume(int64).
    source: "al"(기본, 통합 보관소) | "krx"(선택, 긴 과거). 반환 모양·라벨 규칙은 두 출처가 같다.
    strict=True 면 그 출처가 기간을 덮지 못할 때 DataRangeError(첫 날이 부분일 수 있어 "첫 봉 날짜 ≤ start 이고 끝 봉 날짜 ≥ end" 로 판정)."""
    if bar_minutes not in BAR_MINUTES:
        raise ValueError(f"bar_minutes 는 {BAR_MINUTES} 중 하나: {bar_minutes}")
    source = _check_source(source, session)
    full = _read_minute(code, source)                         # 파일을 한 번만 읽는다(범위 판정과 자르기에 같은 표)
    cov = Coverage(full.index.min(), full.index.max()) if len(full) else None
    if strict and (cov is None or start < cov.dates[0] or end > cov.dates[1]):
        raise DataRangeError(f"분봉[{source}] {code}", (start, end), cov.dates if cov else None)
    if cov is None:
        return _empty_minutes()
    df = full[(full.index >= pd.Timestamp(start)) & (full.index < pd.Timestamp(end) + pd.Timedelta(days=1))]
    df = resample_minutes(session_filter(df, session), bar_minutes)
    return df[MINUTE_COLS]


def load_minute_panel(codes: Iterable[str], start: dt.date, end: dt.date, bar_minutes: int = 1, session: str = "regular",
                      strict: bool = False, source: str | None = None) -> dict[str, pd.DataFrame]:
    """종목별 분봉 표. 기간 안에 봉이 하나도 없는 종목은 결과에서 뺀다(strict=True 면 범위 밖 종목에서 DataRangeError)."""
    out = {}
    for c in dict.fromkeys(codes):
        df = load_minute_bars(c, start, end, bar_minutes, session, strict, source)
        if len(df):
            out[c] = df
    return out


# ============================================================ 사전 필터 재료 (분봉 2단계)


def top_value_by_date(dates: Iterable[dt.date], n: int, *, exclude: Collection[str] = (), codes: Collection[str] | None = None,
                      daily: pd.DataFrame | None = None) -> dict[dt.date, list[str]]:
    """날짜 d 의 "그날 거래대금 상위 n" = **d 이전 마지막 거래일(D−1)** 의 거래대금(종가×거래량) 상위 n 종목, 큰 순서.
    같은 날 종가·거래량으로 뽑으면 장중 진입 시점엔 모르는 값을 쓰는 미래참조라 D−1 순위만 쓴다(`daily_top_n_from_local` 과 같은 규칙).
    일봉에 d 이전 날짜가 없으면 그 날짜는 결과에서 빠진다. exclude 는 제외(초대형주·스팩 등), codes 가 있으면 그 안에서만 고른다."""
    if daily is None:
        from backtesting.daily_cache import load_daily_all
        daily = load_daily_all(daily_dir=str(catalog.path("daily", code="X").parent), cache_path=str(catalog.path("daily_all_cache")))
    df = daily[["code", "date", "close", "volume"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    dates = list(dates)
    if dates:                                             # 필요한 창(직전 거래일이 들어올 만큼 15일 여유)만 정렬한다 — 전 이력을 매번 정렬하면 4초
        df = df[(df["date"] >= pd.Timestamp(min(dates)) - pd.Timedelta(days=15)) & (df["date"] <= pd.Timestamp(max(dates)))]
    if exclude:
        df = df[~df["code"].isin(set(exclude))]
    if codes is not None:
        df = df[df["code"].isin(set(codes))]
    df["tv"] = df["close"] * df["volume"]
    top = df.sort_values("tv", ascending=False, kind="stable").groupby("date").head(n)     # 동점은 원래 순서(코드 순) 유지
    ranked = {d.date(): list(g["code"]) for d, g in top.groupby("date", sort=True)}
    days = sorted(ranked)
    import bisect
    out = {}
    for d in dates:
        i = bisect.bisect_left(days, d) - 1
        if i >= 0:
            out[d] = ranked[days[i]]
    return out


def prefiltered_minute_days(start: dt.date, end: dt.date, top_n: int, bar_minutes: int = 5, session: str = "regular", *,
                            exclude: Collection[str] = (), codes: Collection[str] | None = None,
                            daily: pd.DataFrame | None = None, source: str | None = None) -> dict[dt.date, dict[str, pd.DataFrame]]:
    """분봉 2단계용: {날짜: {종목: 그날 분봉}} — 각 날짜의 D−1 거래대금 상위 top_n 종목만.
    필요한 종목의 분봉을 **한 번씩만** 읽고 리샘플한 뒤 날짜별로 자른다. 그날 분봉이 없는 종목은 그 날짜에서 빠진다."""
    dates = [d for d in pd.bdate_range(start, end).date]
    ranked = top_value_by_date(dates, top_n, exclude=exclude, codes=codes, daily=daily)
    need = sorted({c for v in ranked.values() for c in v})
    panel = load_minute_panel(need, start, end, bar_minutes, session, strict=False, source=source)
    days_of = {c: {d: g for d, g in ((k.date(), v) for k, v in df.groupby(df.index.normalize()))} for c, df in panel.items()}
    out: dict[dt.date, dict[str, pd.DataFrame]] = {}
    for d, cs in ranked.items():
        day = {c: days_of[c][d] for c in cs if c in days_of and d in days_of[c]}
        if day:
            out[d] = day
    return out


# ============================================================ 체결


def tick_days(code: str) -> list[dt.date]:
    """그 종목의 체결 파일이 있는 날짜(오름차순). 압축 전 csv 도 센다."""
    d = catalog.path("tick_al", code=code, date="x").parent
    if not d.is_dir():
        return []
    return sorted({dt.date.fromisoformat(p.name[:10]) for p in d.iterdir() if p.suffix in (".parquet", ".csv") and p.name[:4].isdigit()})


def _read_tick_file(code: str, day: dt.date) -> pd.DataFrame | None:
    base = catalog.path("tick_al", code=code, date=day.isoformat())
    if base.is_file():
        return pd.read_parquet(base)
    csv = base.with_suffix(".csv")
    if csv.is_file():                                     # 압축 전 원본 — 시각의 앞자리 0 을 잃지 않게 문자열로
        return pd.read_csv(csv, dtype=str, encoding="utf-8-sig")
    return None


def load_ticks(code: str, day: dt.date, session: str = "regular", strict: bool = True) -> pd.DataFrame:
    """하루치 체결, 오름차순(원본의 행 순서를 뒤집어 같은 초 안의 실제 순서를 보존). 열 price·qty·sig·sec, 인덱스 ts.
    파일이 없으면 strict 일 때 DataRangeError(가진 날짜 범위), 아니면 빈 표."""
    raw = _read_tick_file(code, day)
    if raw is None:
        days = tick_days(code)
        if strict:
            raise DataRangeError(f"체결 {code}", (day, day), (days[0], days[-1]) if days else None)
        return _empty_ticks()
    t = raw["time"].astype(str).str.zfill(6)
    inversions = int((t.iloc[:-1].values < t.iloc[1:].values).sum()) if len(t) > 1 else 0
    if inversions > max(MAX_DISORDER_ROWS, MAX_DISORDER_SHARE * len(t)):
        raise ValueError(f"체결 {code} {day}: 원본이 역시간순이 아니다(시각이 커지는 곳 {inversions}/{len(t)}) — 같은 초 순서를 믿을 수 없어 읽지 않는다")
    raw = raw.iloc[::-1].reset_index(drop=True)          # 뒤집기 = 실제 체결 순서
    t = t.iloc[::-1].reset_index(drop=True)
    sec = t.str[0:2].astype("int32") * 3600 + t.str[2:4].astype("int32") * 60 + t.str[4:6].astype("int32")
    if inversions:                                       # 실제 파일에 몇 줄 어긋난 곳이 있다(000150 2026-09-22: 3만 행 중 4곳, 09:00:30~35 근처) —
        o = np.argsort(sec.to_numpy(), kind="stable")    # `_precursor_fastpath.to_grid` 와 똑같이 초 단위로 안정 정렬(같은 초는 뒤집은 순서 유지)
        raw, sec = raw.iloc[o].reset_index(drop=True), sec.iloc[o].reset_index(drop=True)
    df = pd.DataFrame({"price": pd.to_numeric(raw["cur_prc"]).abs().astype("int64"),
                       "qty": pd.to_numeric(raw["trde_qty"]).abs().astype("int64"),
                       "sig": pd.to_numeric(raw["pred_pre_sig"]).astype("int64"),
                       "sec": sec.astype("int32")})
    df.index = pd.DatetimeIndex(pd.Timestamp(day) + pd.to_timedelta(df["sec"].astype("int64"), unit="s"), name="ts")
    if session == "regular":
        df = df[(df["sec"] >= 9 * 3600) & (df["sec"] <= 15 * 3600 + 30 * 60)]
    elif session != "full":
        raise ValueError(f"session 은 regular|full: {session!r}")
    return df[TICK_COLS]


def _empty_ticks() -> pd.DataFrame:
    df = pd.DataFrame({"price": pd.Series(dtype="int64"), "qty": pd.Series(dtype="int64"), "sig": pd.Series(dtype="int64"),
                       "sec": pd.Series(dtype="int32")})
    df.index = pd.DatetimeIndex([], name="ts")
    return df


def load_ticks_range(code: str, start: dt.date, end: dt.date, session: str = "regular", strict: bool = True) -> pd.DataFrame:
    """[start, end] 체결을 날짜 순으로 이어 붙인 표(오름차순). 그 종목의 체결 파일이 있는 날만 읽는다(휴장일은 파일이 없는 게 정상).
    strict 면 기간이 파일 범위를 벗어날 때 DataRangeError — 주말·휴장일 구멍은 오류가 아니다."""
    days = tick_days(code)
    if strict and (not days or start < days[0] or end > days[-1]):
        raise DataRangeError(f"체결 {code}", (start, end), (days[0], days[-1]) if days else None)
    parts = [load_ticks(code, d, session, strict=False) for d in days if start <= d <= end]
    return pd.concat(parts) if parts else _empty_ticks()


# ============================================================ 조건식 계약 모양 (TickDay · 분봉 Panel)


def _daily_close_wide(daily: pd.DataFrame | None, codes: Collection[str]) -> pd.DataFrame:
    if daily is None:
        from backtesting.daily_cache import load_daily_all
        daily = load_daily_all(daily_dir=str(catalog.path("daily", code="X").parent), cache_path=str(catalog.path("daily_all_cache")))
    d = daily[daily["code"].isin(set(codes))][["code", "date", "close"]].copy()
    d["date"] = pd.to_datetime(d["date"])
    return d.pivot(index="date", columns="code", values="close").sort_index().astype(float)


def prev_close_of(code: str, day: dt.date, daily: pd.DataFrame | None = None) -> float | None:
    """day 보다 앞선 마지막 일봉의 종가(D−1). 없으면 None."""
    w = _daily_close_wide(daily, [code])
    if code not in w.columns:
        return None
    s = w[code].dropna()
    s = s[s.index < pd.Timestamp(day)]
    return float(s.iloc[-1]) if len(s) else None


def load_tick_day(code: str, day: dt.date, prev_close: float | None = None, strict: bool = True) -> TickDay | None:
    """하루치 체결 → 조건식이 받는 `TickDay`. sec 는 09:00:00 = 0 … 15:30:00 = 23400 의 격자 초(정규장만), 시간순(같은 초는 체결 순서).
    정규장에 체결이 없으면 None(`to_grid` 와 같음). 파일이 없으면 strict 일 때 DataRangeError. prev_close 는 호출자가 준다(`prev_close_of`)."""
    t = load_ticks(code, day, "regular", strict)
    if t.empty:
        return None
    return TickDay(code, day, (t["sec"].to_numpy().astype("int64") - 9 * 3600), t["price"].to_numpy(), t["qty"].to_numpy(), prev_close)


def load_tick_days(code: str, start: dt.date, end: dt.date, daily: pd.DataFrame | None = None, strict: bool = True) -> list[TickDay]:
    """[start, end] 의 TickDay 목록(파일이 있는 날만, 날짜 순) — prev_close(D−1 종가)를 일봉에서 채운다."""
    days = [d for d in tick_days(code) if start <= d <= end]
    if strict and (not tick_days(code) or start < tick_days(code)[0] or end > tick_days(code)[-1]):
        raise DataRangeError(f"체결 {code}", (start, end), (tick_days(code)[0], tick_days(code)[-1]) if tick_days(code) else None)
    w = _daily_close_wide(daily, [code])
    col = w[code].dropna() if code in w.columns else pd.Series(dtype=float)
    out = []
    for d in days:
        prev = col[col.index < pd.Timestamp(d)]
        td = load_tick_day(code, d, float(prev.iloc[-1]) if len(prev) else None, strict=False)
        if td is not None:
            out.append(td)
    return out


def load_minute_panel_wide(codes: Iterable[str], start: dt.date, end: dt.date, bar_minutes: int = 5, session: str = "regular",
                           daily: pd.DataFrame | None = None, strict: bool = False, source: str | None = None) -> Panel:
    """분봉 `Panel`(조건식 계약): index = **봉 끝 시각**(봉 시작 + bar_minutes — 봉이 끝난 시점에야 그 봉을 안다), 여러 날, columns = 종목코드(분봉이 있는 종목만, 요청 순서),
    open·high·low·close·volume(체결 없는 봉은 NaN — 신호 없음), value = 종가×거래량(**분 단위 근사** — 계약이 그렇게 정했다),
    prev_close = 그 날의 전일 종가(일봉 D−1, 하루 안에서 상수; 일봉이 없으면 NaN).
    정규장 마지막 봉(15:30 종가 단일가)의 끝 라벨은 15:30+bar_minutes(예: 5분봉 15:35) — 엔진이 eod_time 으로 자른다."""
    panel = load_minute_panel(codes, start, end, bar_minutes, session, strict, source)
    cols = list(panel)
    step = pd.Timedelta(minutes=bar_minutes)

    def wide(col: str) -> pd.DataFrame:
        if not cols:
            return pd.DataFrame(index=pd.DatetimeIndex([], name="date"), columns=[], dtype=float)
        w = pd.concat({c: df[col].astype(float) for c, df in panel.items()}, axis=1).sort_index()
        w.index = w.index + step
        w.index.name = "date"
        return w[cols]

    o, h, l, c, v = (wide(k) for k in ("open", "high", "low", "close", "volume"))
    prev = pd.DataFrame(np.nan, index=c.index, columns=cols)
    if cols and len(c):
        dc = _daily_close_wide(daily, cols)
        day_of = (c.index - step).normalize()                # 그 봉이 속한 날(봉 시작 기준 — 끝 라벨이 자정을 넘는 일은 없다)
        dd = dc.index.values
        for day in day_of.unique():
            i = int(np.searchsorted(dd, day.to_datetime64(), side="left")) - 1
            if i >= 0:
                row = dc.iloc[i].reindex(cols)
                prev.loc[day_of == day, :] = row.to_numpy()
    return Panel(open=o, high=h, low=l, close=c, volume=v, value=c * v, prev_close=prev)
