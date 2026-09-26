"""표준 parquet 로더 (Polars, lazy 우선).

명세 §39대로 Polars를 쓰고, **가능한 한 `scan_parquet`(lazy)로 읽어** 필요한 컬럼·행만
디스크에서 꺼낸다. 전체를 메모리에 올리면 종목·일이 늘수록 바로 막힌다.

정규장 필터는 **여기서 선택**한다(ingest는 표시만 했다). 기본값은 `regular_only=True`다 —
시간외를 실수로 섞는 사고가 실제로 있었기 때문에 **안전한 쪽을 기본값**으로 둔다.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

from .schema import SESSION_REGULAR


def _paths(root: str | Path, symbols: list[str] | None, dates: list[str] | None) -> list[Path]:
    root = Path(root)
    syms = [f"symbol={s}" for s in symbols] if symbols else ["symbol=*"]
    out: list[Path] = []
    for s in syms:
        pat = f"{s}/*.parquet" if not dates else None
        if dates:
            out += [p for d in dates for p in root.glob(f"{s}/{d}.parquet")]
        else:
            out += list(root.glob(pat))
    return sorted(out)


def scan(root: str | Path, symbols: list[str] | None = None, dates: list[str] | None = None,
         regular_only: bool = True) -> pl.LazyFrame:
    """LazyFrame 반환. 실제 읽기는 `.collect()` 시점에 일어난다."""
    paths = _paths(root, symbols, dates)
    if not paths:
        raise FileNotFoundError(f"읽을 파일이 없다: root={root} symbols={symbols} dates={dates}")
    lf = pl.scan_parquet(paths)
    if regular_only:
        lf = lf.filter(pl.col("session") == SESSION_REGULAR)
    return lf


def load(root: str | Path, symbols: list[str] | None = None, dates: list[str] | None = None,
         regular_only: bool = True, columns: list[str] | None = None) -> pl.DataFrame:
    lf = scan(root, symbols, dates, regular_only)
    if columns:
        lf = lf.select(columns)
    return lf.collect()


def load_stock_day(root: str | Path, symbol: str, date: str,
                   regular_only: bool = True) -> pl.DataFrame:
    """한 종목·일. 시간순(seq 오름차순)이 보장된다."""
    return load(root, [symbol], [date], regular_only).sort("seq")


def available(root: str | Path) -> pl.DataFrame:
    """보유 현황 — 종목별 날짜 수, 전체 날짜 범위. 무결성 검사·리포트에서 쓴다."""
    rows = []
    for p in sorted(Path(root).glob("symbol=*/*.parquet")):
        rows.append({"symbol": p.parent.name.split("=", 1)[1], "date": p.stem})
    if not rows:
        return pl.DataFrame(schema={"symbol": pl.Utf8, "date": pl.Utf8})
    return pl.DataFrame(rows).sort(["symbol", "date"])
