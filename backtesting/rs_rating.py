"""RS 점수 — 코스피·코스닥 보통주·우선주. lead 편지 2026-09-28(사용자 요청 + 17:35·18:15·18:30·18:40 보완).

    python -m backtesting.rs_rating                 # 전 기간(2019~) 다시 계산 → data/cache/rs_rating.parquet 등
    python -m backtesting.rs_rating --rank-today     # 오늘(마지막 거래일) 순위표·상위2%만 → results/rs_rank/*
    python -m backtesting.rs_rating --build-market-cache  # data/cache/rs_market.json 갱신(코드→시장, 한 번만 — universe.csv 밖 코드 보충용, 09-28 22:00 편지)
    python -m backtesting.rs_shares                  # 상장주식수 캐시 갱신(따로, 한 번만 — 지금은 공식에 안 씀, 아래 참고)

## 정의 — **18:15 편지로 공식이 바뀌었다**(스탁이지 실제 값 2,580종목을 받아 대조한 결과, `results/stockeasy_rs_fit.py`)
- **RS1M·RS3M·RS6M** = R21·R63·R126(각 기간 **단독** 수익률, 오늘 종가÷n거래일전 종가−1)의 그날 단면 백분위 1~99.
  스탁이지와 스피어만 상관 RS1M 0.983·RS3M 0.976·RS6M 0.844(직접 재현·확인함, 아래 §검증). **핵심은 1M·3M**(18:30 편지) — 6M 은
  상관이 낮아도(0.84~0.85) **더 맞추는 작업은 안 한다**(과최적화 우려, 18:30 편지가 18:15 편지의 2·3번을 취소).
- **종합 RS** = **겹치지 않는 분기 수익률 가중** — 최근 63일(q1)·63~126일 전(q2)·126~189일 전(q3)·189~252일 전(q4) 각 구간의
  단독 수익률에 0.4·0.2·0.2·0.2 가중 뒤 백분위. 스탁이지 상관 0.849(옛 오닐식 0.4R63+0.2R126+0.2R189+0.2R252 은 0.766 — **버림**).
- **모집단**: 코스피+코스닥 보통주·우선주, ETF·ETN·스팩만 이름 휴리스틱으로 제외. **시가총액 필터는 안 쓴다**
  (17:35 편지에서 넣었다가 18:15 편지가 취소 — 스탁이지도 2,580종목 전부에 점수가 있고 2,000억은 화면 필터일 뿐이었다,
  실제로 대조해서 확인). `rs_shares.py`/`population_mask()` 는 남겨 두되(다른 용도로 필요할 수 있어) 기본 파이프라인에서는 안 부른다.
- 6M·12M·종합이 1M·3M 보다 덜 맞는 원인(18:15 편지 2번 — 원인만, 수정 안 함): **가장 유력한 후보는 원본이 수정주가가 아니라는 것**
  — 하루 ±40% 넘는 변동(분할·병합 흔적)이 있는 9종목만 따로 보면 오차 평균 65.8점, 나머지는 12.3점으로 5배 넘게 차이난다(직접 확인,
  `results/stockeasy_rs_fit.py` 3차 출력). 기간이 길수록 그런 사건이 낄 확률이 높아 원본 그대로면 구조적으로 안 맞는다.
- 상장 n 거래일이 안 된 종목은 그 R_n(따라서 그 값)이 NaN.

## MTT(미너비니 트렌드 템플릿, 17:35 편지 4번) — 순위표에만, 8개 표준 기준
종가>SMA150·SMA200 / SMA150>SMA200 / SMA200 이 21거래일 전보다 위(1개월 상승) / SMA50>SMA150·SMA200 / 종가>SMA50 /
종가 ≥ 52주(252거래일) 저가×1.30 / 종가 ≥ 52주 고가×0.75(=고가 대비 25% 이내) / 종합 RS ≥ 70. 8개 중 충족 개수 + 전부 충족 여부.

## 상위 2% (18:40 편지) — RS1M·RS3M 기준, 순위로 자름(점수 아님, 동률 때문에 어긋날 수 있어서)
그날 점수 받은 종목 수 × 2% 를 **내림**한 인원(둘 다 최소 1명) 각각 뽑아 합집합. 구분 칸 = "둘 다"/"3M만"/"1M만".
정렬: 둘 다 → 3M만 → 1M만, 그 안에서 RS_3M 내림차순(18:40 편지 그대로).

## 출력
- `data/cache/rs_rating.parquet`(종합, 분기 가중) · `rs_1m/rs_3m/rs_6m/rs_12m.parquet`(기간별, 12m 은 이번 라운드에서 안 씀 — 하위호환용으로 남김).
- `data/cache/rs_raw.parquet`: 종합 원점수(분기 가중 합, float).
- `results/rs_rank/YYYY-MM-DD.csv`: 순위(**RS_3M 내림차순 — 18:30 편지**)·코드·이름·시장·RS(종합)·RS_1M/3M/6M/12M·R63/126/189/252·MTT충족수·MTT전부·종가.
- `results/rs_rank/YYYY-MM-DD_top2.csv` · `static/dashboard/rs_top2.json`(같은 내용, 화면용): 코드·이름·시장·RS1M·RS3M·RS6M·RS종합·종가·등락률·거래대금·구분.
- `results/rs_rank/coverage.csv`: 날짜별 그날 점수를 받은 종목 수(구멍 확인용, 종합 RS 기준).
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd

from backtesting.daily_cache import load_daily_all
from backtesting.screener import _is_excluded_instrument
from datahub import catalog, write

N_LIST = (63, 126, 189, 252)
PERIODS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}  # 09-28 17:35 편지 2번
MIN_MARKET_CAP = 200_000_000_000  # 2,000억 (09-28 17:35 편지 3번)
NAMES_PATH = "data/stock_names.json"
UNIVERSE_CSV = "kospi-theme-engine/data/reference/universe.csv"  # market 열 — 아래 note 참고(로컬 전용, 키움 호출 없음)
SHARES_CACHE = "data/cache/rs_shares.json"  # backtesting.rs_shares 가 만듦(한 번만 — 매 빌드마다 안 다시 받음)
RS_PATH = "data/cache/rs_rating.parquet"
RAW_PATH = "data/cache/rs_raw.parquet"
PERIOD_PATH = {k: f"data/cache/rs_{k}.parquet" for k in PERIODS}
RANK_DIR = "results/rs_rank"
MARKET_KO = {"거래소": "코스피", "코스닥": "코스닥"}
MARKET_CACHE = "data/cache/rs_market.json"  # universe.csv 밖 코드(조일알미늄 등 — 소피증권 참조 유니버스 밖) 보충용, fetch_market_from_kiwoom 가 만듦
THEME_GROUP_CSV = "data/theme_group_map.csv"  # 소피증권 테마 — RS·신고가 섹터로는 안 씀(아래 참고)
SECTORS_STOCKEASY_CSV = "data/sectors_stockeasy.csv"  # RS·신고가 화면 섹터(대분류)·세부섹터(중분류) 유일한 출처, 09-28 22:45 편지
MTT_LABELS = ["종가>SMA150&200", "SMA150>SMA200", "SMA200 1개월 상승", "SMA50>SMA150&200",
             "종가>SMA50", "52주저가+30%↑", "52주고가-25%↓", "종합RS≥70"]


def load_names(path: str = NAMES_PATH) -> dict[str, str]:
    return json.loads(open(path, encoding="utf-8").read())


def excluded_codes(names: dict[str, str]) -> set[str]:
    """ETF·ETN·스팩 — 이름 휴리스틱(우선주는 여기서 안 걸린다, 별도 목록 없음)."""
    return {c for c, n in names.items() if _is_excluded_instrument(n)}


def _wide(field: str, daily_dir: str | None = None, cache_path: str | None = None) -> pd.DataFrame:
    """일봉(있는 것만, 새로 안 받음) → 넓은 표(index=date, columns=code). ETF/ETN/스팩 제외."""
    kw = {}
    if daily_dir:
        kw["daily_dir"] = daily_dir
    if cache_path:
        kw["cache_path"] = cache_path
    df = load_daily_all(**kw)
    names = load_names()
    excl = excluded_codes(names)
    df = df[~df["code"].isin(excl)].copy()
    df["date"] = pd.to_datetime(df["date"])
    return df.pivot(index="date", columns="code", values=field).sort_index()


def wide_close(daily_dir: str | None = None, cache_path: str | None = None) -> pd.DataFrame:
    return _wide("close", daily_dir, cache_path)


def wide_high_low(daily_dir: str | None = None, cache_path: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """MTT(52주 고가·저가)용 — close 와 같은 코드·일정으로 다시 pivot(간단함 우선, load_daily_all 이 이미 캐시라 빠름)."""
    return _wide("high", daily_dir, cache_path), _wide("low", daily_dir, cache_path)


def wide_volume(daily_dir: str | None = None, cache_path: str | None = None) -> pd.DataFrame:
    """상위 2% 표의 거래대금(종가×거래량 근사, 이 저장소 관례)용."""
    return _wide("volume", daily_dir, cache_path)


def period_raw(close: pd.DataFrame, n: int) -> pd.DataFrame:
    """기간별 원점수(1M/3M/6M 등) = 그 기간 단독 수익률 Rn(가중 없음, 겹치는 누적)."""
    return close / close.shift(n) - 1


def quarter_returns(close: pd.DataFrame) -> dict[int, pd.DataFrame]:
    """겹치지 않는 분기 수익률 q1(최근 63일)·q2(63~126일 전)·q3(126~189일 전)·q4(189~252일 전).
    qi = close.shift(63*(i-1)) / close.shift(63*i) − 1(18:15 편지 3차 실험 — `results/stockeasy_rs_fit.py` 재현)."""
    return {i: close.shift(63 * (i - 1)) / close.shift(63 * i) - 1 for i in (1, 2, 3, 4)}


def raw_score(close: pd.DataFrame) -> pd.DataFrame:
    """종합 원점수 = 0.4q1+0.2q2+0.2q3+0.2q4(겹치지 않는 분기 가중 — 18:15 편지, 옛 오닐식 대체)."""
    q = quarter_returns(close)
    return 0.4 * q[1] + 0.2 * q[2] + 0.2 * q[3] + 0.2 * q[4]


def load_shares(path: str = SHARES_CACHE) -> dict[str, int]:
    if not os.path.isfile(path):
        return {}
    return {k: int(v) for k, v in json.loads(open(path, encoding="utf-8").read()).items()}


def population_mask(close: pd.DataFrame, shares: dict[str, int] | None = None) -> pd.DataFrame:
    """시가총액 ≥ 2,000억 인 (날짜,종목) 만 True — RS 백분위 모집단(09-28 17:35 편지 3번). 상장주식수 모르면 False(모집단 밖)."""
    shares = load_shares() if shares is None else shares
    sh = pd.Series({c: shares.get(c, np.nan) for c in close.columns}, index=close.columns)
    cap = close.mul(sh, axis=1)
    return (cap >= MIN_MARKET_CAP).fillna(False)


def percentile_1_99(raw: pd.DataFrame, pop: pd.DataFrame | None = None) -> pd.DataFrame:
    """그날 단면 백분위 1~99(99=상위 1%). `pop`(bool, 같은 모양)이 있으면 True 인 칸만 모집단 — 나머지는 값이 있어도 NaN."""
    x = raw.where(pop) if pop is not None else raw
    pct = x.rank(axis=1, pct=True, method="average")  # (0,1], 동률은 평균 순위
    return np.ceil(pct * 99).clip(lower=1, upper=99)


def rs_score(raw: pd.DataFrame, pop: pd.DataFrame | None = None) -> pd.DataFrame:
    return percentile_1_99(raw, pop)


def fetch_market_from_kiwoom() -> dict[str, str]:
    """ka10099 시장별 목록(코스피·코스닥) 한 번씩 — 코드→시장. `rs_shares.fetch_from_kiwoom` 과 같은 배치 키·읽기 전용 호출
    (주문 아님, 계좌 무관). 소피증권 universe.csv 밖 코드(우선주·그 유니버스 밖 소형주)를 채우는 용도라 값이 있으면 캐시에 저장해 두고 재사용한다."""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.getcwd(), ".env"))
    from kiwoom_client import KiwoomClient, batch_keys
    key, sec = batch_keys()
    if not key or not sec:
        return {}
    client = KiwoomClient(key, sec, is_mock=os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true")
    out: dict[str, str] = {}
    for market_type, label in (("0", "코스피"), ("10", "코스닥")):
        for item in client.get_stock_list(market_type):
            code = (item.get("code") or "").strip()
            if code:
                out[code] = label
    return out


def build_market_cache(path: str = MARKET_CACHE) -> dict[str, str]:
    m = fetch_market_from_kiwoom()
    if m:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        json.dump(m, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(tmp, path)
    return m


def market_of(names: dict[str, str]) -> dict[str, str]:
    """코드→코스피/코스닥. 1순위 소피증권 `universe.csv`(로컬, 키움 호출 없음), 거기 없는 코드(우선주·유니버스 밖 소형주 —
    조일알미늄·상상인증권 등, 09-28 22:00 편지)는 `MARKET_CACHE`(키움 ka10099 배치, `build_market_cache()` 로 미리 만듦)로 채운다.
    둘 다 없는 코드만 빈 값(이 표는 표시용 — RS 점수 자체는 이 표와 무관)."""
    out: dict[str, str] = {}
    if os.path.isfile(UNIVERSE_CSV):
        u = pd.read_csv(UNIVERSE_CSV, dtype=str, encoding="utf-8-sig")
        out = {row["code"]: MARKET_KO.get(row["market"], row["market"]) for _, row in u.iterrows()}
    if os.path.isfile(MARKET_CACHE):
        cache = json.loads(open(MARKET_CACHE, encoding="utf-8").read())
        for code, mkt in cache.items():
            out.setdefault(code, mkt)
    return out


def load_theme_groups(path: str = THEME_GROUP_CSV) -> dict[str, str]:
    """소피증권 테마(kospi-theme-engine) — **RS·신고가 화면 섹터로는 안 쓴다**(09-28 22:45 편지로 취소, `sectors_stockeasy`로 교체).
    소피증권 쪽 테마 관리는 완전히 별개 용도라 이 함수 자체는 남겨 둔다(안 읽지도 안 고치지도 않는 소피증권 원본 파일을 가리킴)."""
    if not os.path.isfile(path):
        return {}
    g = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    return dict(zip(g["code"], g["group"]))


def load_sectors_stockeasy(path: str = SECTORS_STOCKEASY_CSV) -> tuple[dict[str, str], dict[str, str]]:
    """스탁이지 섹터 분류(코드→대분류, 코드→중분류) — 09-28 22:45 편지, RS·신고가 화면 섹터의 유일한 출처.
    없는 코드(신규상장 등)는 화면에서 "미분류"로 보인다(이 함수는 빈 문자열 없이 그냥 안 채움)."""
    if not os.path.isfile(path):
        return {}, {}
    s = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    return dict(zip(s["code"], s["sector"])), dict(zip(s["code"], s["sub_sector"]))


def sector_rs_median(rs_day: pd.Series, sector_of: dict[str, str]) -> dict[str, float]:
    """섹터(대분류)→그 섹터 종목들의 RS종합 중앙값(그날 점수 있는 전 종목 기준, 09-28 22:45 편지 — 칩 색용)."""
    df = pd.DataFrame({"code": rs_day.index, "rs": rs_day.values})
    df["sector"] = df["code"].map(sector_of)
    df = df.dropna(subset=["rs", "sector"])
    if df.empty:
        return {}
    return df.groupby("sector")["rs"].median().round(1).to_dict()


SECTOR_MIN_MEMBERS = 3      # 세부섹터는 종목이 이보다 적으면 순위가 한두 종목에 휘둘린다 — 뺀다
SECTOR_STRONG_RS = 80


def sector_rs_table(b: dict, day: pd.Timestamp, level: str = "sector") -> list[dict]:
    """섹터 RS(10-01 사용자) — 오닐 업종 RS 식: 섹터 소속 종목 원점수의 **중앙값**을 섹터의 원점수로 보고,
    그날 섹터들끼리 백분위 1~99 로 매긴다(종목 RS 와 같은 0.4q1+0.2q2+0.2q3+0.2q4·1M/3M/6M 단독 수익률).
    중앙값이라 한 종목 급등이 섹터 점수를 끌고 가지 못한다. 1주(5거래일)·1달(21거래일) 전 점수도 같이 줘서 오르는 섹터를 보이게 한다.
    level: "sector"(대분류) / "sub_sector"(세부섹터). ETF·ETN·스팩 제외, 분류 없는 종목 제외."""
    close, rs = b["close"], b["rs"]
    names = load_names()
    sectors, subs = load_sectors_stockeasy()
    group_of = sectors if level == "sector" else subs
    ex = excluded_codes(names)                      # 한 번만 — 컴프리헨션 안에서 부르면 종목 수만큼 다시 계산한다
    codes = [c for c in close.columns if c in group_of and c not in ex]
    i = close.index.get_loc(day)
    days = {"now": day, "w1": close.index[max(0, i - 5)], "m1": close.index[max(0, i - 21)]}
    raws = {"rs": raw_score(close[codes]), **{k: period_raw(close[codes], PERIODS[k]) for k in ("1m", "3m", "6m")}}
    grp = pd.Series({c: group_of[c] for c in codes})

    def group_rank(raw: pd.DataFrame, d: pd.Timestamp) -> pd.Series:
        med = raw.loc[d].groupby(grp).median()
        n = raw.loc[d].groupby(grp).count()
        med = med[n >= (SECTOR_MIN_MEMBERS if level == "sub_sector" else 1)].dropna()
        return np.ceil(med.rank(pct=True) * 99).clip(1, 99)

    now = {k: group_rank(r, day) for k, r in raws.items()}
    w1, m1 = group_rank(raws["rs"], days["w1"]), group_rank(raws["rs"], days["m1"])
    rs_now = rs.loc[day].reindex(codes)
    out = []
    for g in now["rs"].sort_values(ascending=False).index:
        members = rs_now[grp == g].dropna()
        top = members.sort_values(ascending=False).head(3)
        out.append({
            "섹터": g, **({"대분류": sectors.get(grp[grp == g].index[0])} if level == "sub_sector" else {}),
            "종목수": int((grp == g).sum()), "rs": int(now["rs"][g]),
            "rs_1m": _int_or_none(now["1m"].get(g)), "rs_3m": _int_or_none(now["3m"].get(g)), "rs_6m": _int_or_none(now["6m"].get(g)),
            "rs_1w_ago": _int_or_none(w1.get(g)), "rs_1m_ago": _int_or_none(m1.get(g)),
            "강한종목비율": round(float((members >= SECTOR_STRONG_RS).mean()) * 100, 1) if len(members) else None,
            "대표": [{"코드": c, "이름": names.get(c, c), "rs": int(v)} for c, v in top.items()],
        })
    return out


def avg_value(close: pd.DataFrame, volume: pd.DataFrame, day: pd.Timestamp, n: int) -> pd.Series:
    """기준일(당일 포함) 최근 n일 평균 거래대금(원) — 09-28 22:10 편지. 종가×거래량의 n일 평균."""
    value = close * volume
    return value.rolling(n).mean().loc[day]


def build() -> dict:
    """전체 계산 — close/high/low/volume, 종합 raw/rs(분기 가중), 기간별 rs(1m/3m/6m/12m).
    18:15 편지로 시총 모집단 필터를 뺐다(스탁이지 대조 결과 — docstring 참고) — `population_mask()` 는 남겨 두되 여기선 안 쓴다(pop=None)."""
    close = wide_close()
    high, low = wide_high_low()
    volume = wide_volume()
    raw = raw_score(close)
    rs = rs_score(raw, None)
    period_rs = {k: percentile_1_99(period_raw(close, n), None) for k, n in PERIODS.items()}
    return {"close": close, "high": high, "low": low, "volume": volume, "raw": raw, "rs": rs, "period_rs": period_rs}


def coverage(rs: pd.DataFrame) -> pd.DataFrame:
    return rs.notna().sum(axis=1).rename("n_scored").to_frame()


def mtt(b: dict, day: pd.Timestamp | None = None) -> pd.DataFrame:
    """미너비니 트렌드 템플릿 8개 — `day`(기본 마지막 거래일) 한 날짜만(순위표용, 전 기간 저장 안 함).
    이동평균·52주 고저가 부족(상장 200~252거래일 미만)이면 그 종목은 NaN(0/8 로 잘못 표시 안 함)."""
    close, high, low, rs = b["close"], b["high"], b["low"], b["rs"]
    day = pd.Timestamp(day) if day is not None else close.index[-1]
    sma50, sma150, sma200 = close.rolling(50).mean(), close.rolling(150).mean(), close.rolling(200).mean()
    c, s50, s150, s200 = close.loc[day], sma50.loc[day], sma150.loc[day], sma200.loc[day]
    s200_1m_ago = sma200.shift(21).loc[day]
    hi52, lo52 = high.rolling(252).max().loc[day], low.rolling(252).min().loc[day]
    r = rs.loc[day]
    checks = pd.DataFrame({
        "c1_close_above_150_200": (c > s150) & (c > s200),
        "c2_150_above_200": s150 > s200,
        "c3_200_up_1m": s200 > s200_1m_ago,
        "c4_50_above_150_200": (s50 > s150) & (s50 > s200),
        "c5_close_above_50": c > s50,
        "c6_above_52w_low_30pct": c >= lo52 * 1.30,
        "c7_within_52w_high_25pct": c >= hi52 * 0.75,  # 고가 대비 25% 이내(=고가의 75% 이상) — 처음엔 부등호가 반대였다(테스트가 잡음)
        "c8_rs_ge_70": r >= 70,
    })
    ok = s200.notna() & s150.notna() & s50.notna() & hi52.notna() & lo52.notna()
    count = checks.sum(axis=1).where(ok)
    return pd.DataFrame({"mtt_count": count, "mtt_all": (count == 8)})


def save(b: dict) -> None:
    """허브 관문을 지나 저장 — 잠금 `rs_rating`(catalog.yaml). 종합 RS·원점수·기간별 RS 전부 한 트랜잭션."""
    os.makedirs(os.path.dirname(RS_PATH), exist_ok=True)
    os.makedirs(RANK_DIR, exist_ok=True)
    rs, raw = b["rs"], b["raw"]
    with write("rs_rating", writer="rs_rating.build", detail={"rows": len(rs), "codes": rs.shape[1]}):
        rs.astype("Int8").to_parquet(RS_PATH)
        raw.astype("float32").to_parquet(RAW_PATH)
        for k, df in b["period_rs"].items():
            df.astype("Int8").to_parquet(PERIOD_PATH[k])
        coverage(rs).to_csv(f"{RANK_DIR}/coverage.csv")


def write_daily_rank(b: dict, day: pd.Timestamp | None = None) -> str:
    """`day`(기본 마지막 거래일) 순위표 저장."""
    close, raw, rs, period_rs = b["close"], b["raw"], b["rs"], b["period_rs"]
    day = pd.Timestamp(day) if day is not None else rs.index[-1]
    if day not in rs.index:
        raise ValueError(f"{day.date()} 는 일봉에 없는 날")
    names = load_names()
    markets = market_of(names)
    m = mtt(b, day)
    order_col = period_rs["3m"].loc[day].dropna().sort_values(ascending=False)  # 순위표 기본 정렬 RS_3M(18:30 편지) — RS(종합) 없어도 뺴지 않는다
    rows = []
    for rank, (code, _score3m) in enumerate(order_col.items(), 1):
        score = rs.loc[day, code]
        rows.append({
            "순위": rank, "코드": code, "이름": names.get(code, ""), "시장": markets.get(code, ""),
            "RS": _int_or_none(score),
            "RS_1M": _int_or_none(period_rs["1m"].loc[day, code]), "RS_3M": _int_or_none(period_rs["3m"].loc[day, code]),
            "RS_6M": _int_or_none(period_rs["6m"].loc[day, code]), "RS_12M": _int_or_none(period_rs["12m"].loc[day, code]),
            "R63": _pct(close, raw, code, day, 63), "R126": _pct(close, raw, code, day, 126),
            "R189": _pct(close, raw, code, day, 189), "R252": _pct(close, raw, code, day, 252),
            "MTT충족수": _int_or_none(m.loc[code, "mtt_count"]) if code in m.index else None,
            "MTT전부": bool(m.loc[code, "mtt_all"]) if code in m.index and pd.notna(m.loc[code, "mtt_count"]) else None,
            "종가": close.loc[day, code],
        })
    out = pd.DataFrame(rows)
    os.makedirs(RANK_DIR, exist_ok=True)
    path = f"{RANK_DIR}/{day.date().isoformat()}.csv"
    with write("rs_rating", writer="rs_rating.rank", detail={"date": str(day.date()), "n": len(out)}):
        out.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _int_or_none(v) -> int | None:
    return None if pd.isna(v) else int(v)


def _pct(close: pd.DataFrame, raw: pd.DataFrame, code: str, day: pd.Timestamp, n: int) -> float | None:
    idx = close.index.get_loc(day)
    if idx - n < 0:
        return None
    c0, cn = close.iloc[idx][code], close.iloc[idx - n][code]
    return None if pd.isna(c0) or pd.isna(cn) or cn == 0 else round(float(c0 / cn - 1), 4)


TOP2_PATH = f"{RANK_DIR}/{{day}}_top2.csv"
TOP2_JSON = "static/dashboard/rs_top2.json"
TOP2_FRACTION = 0.02


def top2_codes(period_rs: dict[str, pd.DataFrame], day: pd.Timestamp) -> tuple[set[str], set[str], int, int]:
    """RS_1M·RS_3M 각각 **순위**(점수 아님 — 동률 때문에 98점이 2%를 넘을 수 있어서, 18:40 편지) 상위 2% 코드 집합 + 그날 인원(최소 1명)."""
    out = {}
    for k in ("1m", "3m"):
        s = period_rs[k].loc[day].dropna().sort_values(ascending=False)
        n = max(1, int(len(s) * TOP2_FRACTION))
        out[k] = (set(s.index[:n]), n)
    return out["1m"][0], out["3m"][0], out["1m"][1], out["3m"][1]


def top2_table(b: dict, day: pd.Timestamp | None = None) -> pd.DataFrame:
    """상위 2%(1M·3M) 합집합 표 — 구분(둘 다/3M만/1M만), 정렬 둘 다→3M만→1M만·그 안에서 RS_3M 내림차순(18:40 편지).
    09-28 22:00·22:10 편지: 섹터·시가총액(가능하면)·평균거래대금(5·20·60일) 칸 추가. 22:45 편지로 섹터 출처를 스탁이지 분류로 교체(세부섹터도 추가)."""
    close, volume, rs, period_rs = b["close"], b["volume"], b["rs"], b["period_rs"]
    day = pd.Timestamp(day) if day is not None else rs.index[-1]
    c1, c3, n1, n3 = top2_codes(period_rs, day)
    codes = c1 | c3
    names = load_names()
    markets = market_of(names)
    sectors, sub_sectors = load_sectors_stockeasy()
    shares = load_shares()
    prev = close.shift(1).loc[day]
    av5, av20, av60 = avg_value(close, volume, day, 5), avg_value(close, volume, day, 20), avg_value(close, volume, day, 60)
    rows = []
    for code in codes:
        group = "둘 다" if (code in c1 and code in c3) else ("3M만" if code in c3 else "1M만")
        chg = (close.loc[day, code] / prev[code] - 1) * 100 if code in prev.index and pd.notna(prev.get(code)) and prev[code] else None
        val = close.loc[day, code] * volume.loc[day, code] if code in volume.columns else None
        cap = close.loc[day, code] * shares[code] if code in shares and pd.notna(close.loc[day, code]) else None
        rows.append({
            "코드": code, "이름": names.get(code, ""), "시장": markets.get(code, ""),
            "섹터": (sectors.get(code) or "미분류"), "세부섹터": (sub_sectors.get(code) or "미분류"),
            "RS1M": _int_or_none(period_rs["1m"].loc[day, code]), "RS3M": _int_or_none(period_rs["3m"].loc[day, code]),
            "RS6M": _int_or_none(period_rs["6m"].loc[day, code]), "RS종합": _int_or_none(rs.loc[day, code]),
            "종가": close.loc[day, code], "등락률": round(chg, 2) if chg is not None else None,
            "거래대금": None if val is None or pd.isna(val) else int(val),
            "평균대금5": _int_or_none(av5.get(code)), "평균대금20": _int_or_none(av20.get(code)), "평균대금60": _int_or_none(av60.get(code)),
            "시가총액": None if cap is None or pd.isna(cap) else int(cap), "구분": group,
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    order = {"둘 다": 0, "3M만": 1, "1M만": 2}
    out["_o"] = out["구분"].map(order)
    out = out.sort_values(["_o", "RS3M"], ascending=[True, False]).drop(columns="_o").reset_index(drop=True)
    out.attrs["n1"], out.attrs["n3"] = n1, n3
    return out


def write_top2(b: dict, day: pd.Timestamp | None = None) -> str:
    """상위 2% csv + 화면용 json(같은 내용) — 8765 는 정적 파일만 읽으므로 재기동 없이 매일 갱신된다(18:40 편지)."""
    day = pd.Timestamp(day) if day is not None else b["rs"].index[-1]
    out = top2_table(b, day)
    path = TOP2_PATH.format(day=day.date().isoformat())
    os.makedirs(RANK_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(TOP2_JSON), exist_ok=True)
    sectors, _ = load_sectors_stockeasy()
    payload = {"date": day.date().isoformat(), "n1m": out.attrs.get("n1", 0), "n3m": out.attrs.get("n3", 0),
              "sector_rs": sector_rs_median(b["rs"].loc[day], sectors),
              "sector_table": {"sector": sector_rs_table(b, day, "sector"), "sub_sector": sector_rs_table(b, day, "sub_sector")},
              "rows": json.loads(out.to_json(orient="records", force_ascii=False))}
    with write("rs_rating", writer="rs_rating.top2", detail={"date": str(day.date()), "n": len(out)}):
        out.to_csv(path, index=False, encoding="utf-8-sig")
        tmp = f"{TOP2_JSON}.tmp"
        json.dump(payload, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, TOP2_JSON)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rank-today", action="store_true", help="전체 재계산 없이 오늘 순위표만(캐시 파일에 안 씀, 순위표만 새로)")
    ap.add_argument("--build-market-cache", action="store_true", help="data/cache/rs_market.json 갱신(키움 ka10099, 읽기 전용) 만 하고 끝")
    a = ap.parse_args()
    if a.build_market_cache:
        m = build_market_cache()
        print(f"저장: {MARKET_CACHE} — {len(m)}종목")
        return
    b = build()
    if a.rank_today:
        path = write_daily_rank(b)
        path2 = write_top2(b)
        print(f"저장: {path} · {path2} ({int(b['rs'].iloc[-1].notna().sum())}종목)")
        return
    save(b)
    path = write_daily_rank(b)
    path2 = write_top2(b)
    print(f"저장: {RS_PATH}({b['rs'].shape}) · {RAW_PATH} · 기간별 4개 · {path} · {path2} · {RANK_DIR}/coverage.csv")


if __name__ == "__main__":
    main()
