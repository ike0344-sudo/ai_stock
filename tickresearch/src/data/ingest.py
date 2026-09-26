"""원본 체결 parquet → 표준 스키마 parquet 변환 (Phase 1).

원본은 이미 parquet이지만 그대로 쓰지 않는다 — 이유는 `schema.py` 상단 참고
(역시간순·HHMMSS 문자열·API 관례 컬럼명·side 없음).

## 설계 결정 3가지 (나중에 왜 이렇게 했는지 묻지 않도록 기록)

1. **정규장 필터를 여기서 하지 않는다.** `session` 컬럼으로 표시만 하고 전부 남긴다.
   원본 수집 시점에 "시간외도 나중에 쓸모 있을 수 있어 버리지 않는다"고 결정했고,
   자르는 건 소비하는 쪽(분석)의 책임이다. **단 표시를 안 하면 사고가 나므로 반드시 남긴다.**
2. **시간 오름차순으로 저장한다.** 원본이 역순이라 분석마다 뒤집는 비용이 반복된다.
   같은 초 안의 순서도 보존한다 — 원본을 통째로 뒤집으면 같은 초 안의 순서도 올바르게
   시간순이 된다(앞선 연구에서 tie-break 오류로 45.7%가 틀렸던 사고가 있었다).
   보존 결과를 `seq`(0부터 증가)로 박아둔다.
3. **side는 tick rule 추정이고 그 사실을 `side_source`에 남긴다.** 첫 체결은 직전 가격이
   없어 UNKNOWN이다. 보합(가격 동일)은 직전 방향을 계승한다(표준 0-tick rule).
"""
from __future__ import annotations

import os
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq

from .schema import (
    REQUIRED_RAW_COLUMNS,
    SESSION_CLOSE,
    SESSION_OPEN,
    SESSION_POST,
    SESSION_PRE,
    SESSION_REGULAR,
    SIDE_BUY,
    SIDE_SELL,
    SIDE_SOURCE_TICK_RULE,
    SIDE_UNKNOWN,
    TICK_SCHEMA,
    validate_schema,
)


def read_ref_price(path: str | Path) -> int | None:
    """파일 메타데이터의 `ref_price`(전일 종가). 실측 결과 일봉 전일종가와 8/8 일치했다.

    없으면 None — 등락률 기준이 없다는 뜻이므로 호출자가 판단한다(조용히 0으로 채우지 않는다).
    """
    md = pq.ParquetFile(str(path)).metadata.metadata or {}
    raw = md.get(b"ref_price")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _tick_rule_side(price: pl.Series) -> pl.Series:
    """직전 체결 대비 가격 방향으로 매수/매도 추정(0-tick rule).

    상승=BUY, 하락=SELL, 보합=직전 방향 계승, 첫 체결=UNKNOWN.
    호가가 없어 Lee-Ready 본래 방식(호가 중간값 비교)은 불가능하다 — 그래서 추정이고,
    `side_source`에 그 사실을 남긴다.
    """
    diff = price.diff()
    raw = (
        pl.when(diff > 0).then(pl.lit(SIDE_BUY))
        .when(diff < 0).then(pl.lit(SIDE_SELL))
        .otherwise(pl.lit(None, dtype=pl.Utf8))
    )
    df = pl.select(raw.alias("s"))
    # 보합(null)은 직전 방향 계승 → 그래도 남는 선두 null은 UNKNOWN
    return df.select(pl.col("s").forward_fill().fill_null(SIDE_UNKNOWN))["s"]


def normalize(raw: pl.DataFrame, symbol: str, date: str, ref_price: int | None) -> pl.DataFrame:
    """원본 DataFrame → 표준 스키마. 원본은 **시간 역순**이라는 전제로 뒤집는다."""
    missing = [c for c in REQUIRED_RAW_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(f"{symbol} {date}: 원본 컬럼 누락 {missing} (실제 컬럼={raw.columns})")
    if raw.is_empty():
        return pl.DataFrame(schema=TICK_SCHEMA)

    # 뒤집기만으로는 부족하다 — 실측(2026-09-24): 원본 24,144행 중 **역순 위반이 2곳**
    # 있었다(0.008%, 위반 지점 간격 5,700으로 API 페이지 경계로 추정). 뒤집은 뒤
    # **안정 정렬(stable)**까지 해야 0곳이 된다. 안정 정렬이어야 같은 초 안의 순서
    # (뒤집기로 확보한 것)가 보존된다 — 불안정 정렬을 쓰면 45.7%가 틀렸던 그 사고가 재발한다.
    t = pl.col("time").cast(pl.Utf8).str.zfill(6)
    df = raw.reverse().with_columns(
        pl.concat_str([pl.lit(date), pl.lit(" "), t]).str.to_datetime("%Y-%m-%d %H%M%S").alias("timestamp"),
        pl.lit(symbol).alias("symbol"),
        pl.col("cur_prc").cast(pl.Int64).alias("price"),
        pl.col("trde_qty").cast(pl.Int64).alias("volume"),
    ).sort("timestamp", maintain_order=True).with_columns(
        (pl.col("price") * pl.col("volume")).alias("trade_value"),
        pl.int_range(pl.len(), dtype=pl.Int64).alias("seq"),   # 정렬 **후** 부여
        pl.lit(ref_price, dtype=pl.Int64).alias("ref_price"),
        pl.lit(SIDE_SOURCE_TICK_RULE).alias("side_source"),
    )
    hhmmss = df["timestamp"].dt.strftime("%H:%M:%S")
    df = df.with_columns(
        pl.when(hhmmss < SESSION_OPEN).then(pl.lit(SESSION_PRE))
        .when(hhmmss > SESSION_CLOSE).then(pl.lit(SESSION_POST))
        .otherwise(pl.lit(SESSION_REGULAR)).alias("session"),
        _tick_rule_side(df["price"]).alias("side"),
    )
    out = df.select(list(TICK_SCHEMA.keys()))
    validate_schema(out)
    return out


def ingest_file(src: str | Path, out_root: str | Path, overwrite: bool = False) -> dict:
    """원본 파일 하나를 표준 parquet으로 변환. 경로에서 symbol/date를 읽는다."""
    src = Path(src)
    symbol, date = src.parent.name, src.stem
    dst = Path(out_root) / f"symbol={symbol}" / f"{date}.parquet"
    if dst.exists() and not overwrite:
        return {"symbol": symbol, "date": date, "rows": 0, "skipped": True}

    ref = read_ref_price(src)
    df = normalize(pl.read_parquet(src), symbol, date, ref)
    dst.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(dst, compression="zstd")
    return {
        "symbol": symbol, "date": date, "rows": len(df), "skipped": False,
        "ref_price": ref, "regular_rows": int((df["session"] == SESSION_REGULAR).sum()),
    }


def ingest_all(src_root: str | Path, out_root: str | Path, overwrite: bool = False,
               progress_every: int = 500) -> dict:
    src_root = Path(src_root)
    files = sorted(src_root.glob("*/*.parquet"))
    stats = {"files": len(files), "ingested": 0, "skipped": 0, "rows": 0,
             "regular_rows": 0, "no_ref_price": 0, "errors": []}
    for i, f in enumerate(files, 1):
        try:
            r = ingest_file(f, out_root, overwrite)
        except Exception as exc:                       # 조용히 넘기지 않는다 — 목록으로 남긴다
            stats["errors"].append(f"{f}: {exc}")
            continue
        if r["skipped"]:
            stats["skipped"] += 1
        else:
            stats["ingested"] += 1
            stats["rows"] += r["rows"]
            stats["regular_rows"] += r["regular_rows"]
            if r.get("ref_price") is None:
                stats["no_ref_price"] += 1
        if progress_every and i % progress_every == 0:
            print(f"  {i}/{len(files)} · 변환 {stats['ingested']} · 건너뜀 {stats['skipped']}", flush=True)
    return stats
