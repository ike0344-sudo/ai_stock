"""통합 분봉 보관소 (설계 §2.4.10, 테스트 H7·H8).

`fetch_minute` 은 통합 분봉 캐시를 갱신마다 최근 20거래일로 통째로 교체한다 — 이력이 사라진다.
보관소는 교체 직전에 `보관소 ∪ 기존 캐시 ∪ 새 봉` 을 합쳐 남겨 두는 누적본이다.

- 같은 분(인덱스)은 **나중에 넘긴 것이 이긴다**(늦게 받은 봉이 정정·완성본).
- 행 수는 절대 줄지 않는다(줄면 저장하지 않고 예외).
- 날짜를 인덱스로 저장한다(_resample_minute 이 index.normalize() 로 날짜별로 자른다).
- `merge` 는 잠금을 잡지 않는다 — 호출자(fetch_minute·CLI)가 이미 `write("minute_al")` 안에 있다.
"""
import os
from pathlib import Path

import pandas as pd

from . import catalog

COLS = ["open", "high", "low", "close", "volume"]


def archive_path(code: str) -> Path:
    return catalog.path("minute_al_archive", code=code)


def cache_path(code: str) -> Path:
    return catalog.path("minute_al", code=code)


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    df = df[COLS].copy()
    df.index = pd.to_datetime(df.index).astype("datetime64[ns]")   # pandas 버전마다 [us]/[ns] 가 갈린다 — 고정
    df.index.name = "date"
    return df


def read_cache(code: str) -> pd.DataFrame | None:
    p = cache_path(code)
    if not p.is_file():
        return None
    return _norm(pd.read_csv(p, index_col="date", parse_dates=True))


def read(code: str, start=None, end=None) -> pd.DataFrame:
    """보관소 봉. 없으면 빈 표. start/end 는 날짜(포함)."""
    p = archive_path(code)
    if not p.is_file():
        return pd.DataFrame(columns=COLS, index=pd.DatetimeIndex([], name="date"))
    df = pd.read_parquet(p)
    if start is not None:
        df = df[df.index >= pd.Timestamp(start)]
    if end is not None:
        df = df[df.index < pd.Timestamp(end) + pd.Timedelta(days=1)]
    return df


def merge(code: str, *frames: pd.DataFrame | None) -> dict:
    """보관소에 frames(앞 -> 뒤, 뒤가 이김)를 합쳐 저장한다. {'before','after'} 행 수를 돌려준다."""
    p = archive_path(code)
    old = pd.read_parquet(p) if p.is_file() else None
    parts = ([_norm(old)] if old is not None else []) + [_norm(f) for f in frames if f is not None and len(f)]
    before = 0 if old is None else len(old)
    if not parts:
        return {"before": before, "after": before}
    df = pd.concat(parts)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    if len(df) < before:
        raise RuntimeError(f"{code}: 병합 후 행이 줄었다({before} -> {len(df)}) — 저장하지 않는다")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    df.to_parquet(tmp, compression="zstd")
    os.replace(tmp, p)
    return {"before": before, "after": len(df)}


def archive_all(codes: list[str] | None = None, only_stale: bool = True, progress=None) -> dict:
    """캐시 파일들을 보관소에 병합(종목 하나씩 — 메모리에 한꺼번에 올리지 않는다).

    only_stale: 캐시 mtime ≤ 보관소 mtime 이면 이미 병합된 것으로 보고 건너뛴다(안전망 재실행이 빠르게).
    """
    cache_dir = cache_path("x").parent
    todo = sorted(codes) if codes else sorted(p.stem for p in cache_dir.glob("*.csv"))
    stats = {"codes": len(todo), "merged": 0, "skipped": 0, "failed": [], "rows_before": 0, "rows_after": 0}
    for i, code in enumerate(todo, 1):
        try:
            cp, ap = cache_path(code), archive_path(code)
            if only_stale and ap.is_file() and cp.is_file() and cp.stat().st_mtime <= ap.stat().st_mtime:
                stats["skipped"] += 1
            else:
                r = merge(code, read_cache(code))
                stats["merged"] += 1
                stats["rows_before"] += r["before"]
                stats["rows_after"] += r["after"]
        except Exception as exc:                       # 한 종목이 깨져도 나머지는 계속
            stats["failed"].append(f"{code}: {type(exc).__name__}: {exc}"[:200])
        if progress:
            progress(i, len(todo))
    return stats
