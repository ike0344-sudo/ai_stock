"""Feature 저장 (명세 §39 성능 원칙).

## 왜 1초 전부를 저장하지 않는가 — 계산해보면 나온다

1초 격자 23,401칸 × Feature 80개 × 3,903 종목·일 × 8바이트 = **약 58GB**.
디스크도 문제지만 이후 모든 분석이 I/O에 묶인다.

**그래서 격자 간격(step)을 설정으로 받고 기본 10초로 둔다**:
- 10초 간격 → 2,341칸 → **약 2.9GB**(float32 기준), 1/20
- 선행 연구도 10초 격자를 썼고, 10~60초짜리 반응을 잡는 데 충분했다
  (1분 격자로는 못 잡는다는 것이 실측으로 확인됨)
- **더 촘촘히 봐야 할 구간이 나오면 그때 step=1로 다시 만든다.** 지금 다 만들어 두는 것은
  쓰지도 않을 58GB를 만드는 일이다.

float32로 저장한다 — Feature는 비율·속도라 float64 정밀도가 필요 없고 용량이 절반이다.
(누적 거래대금만은 원 단위가 커서 float64를 유지한다.)
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

KEEP_F64 = {"t_sec", "cum_value", "cum_volume", "cum_trades"}


def downcast(df: pl.DataFrame) -> pl.DataFrame:
    """정밀도가 필요 없는 컬럼만 float32로 — 용량 절반."""
    return df.with_columns([
        pl.col(c).cast(pl.Float32) for c in df.columns
        if c not in KEEP_F64 and df.schema[c] in (pl.Float64,)
    ])


def sample_grid(df: pl.DataFrame, step: int) -> pl.DataFrame:
    """step초 간격으로 솎는다. step=1이면 그대로."""
    if step <= 1:
        return df
    return df.filter(pl.col("t_sec") % step == 0)


def write(df: pl.DataFrame, root: str | Path, symbol: str, date: str) -> Path:
    p = Path(root) / f"symbol={symbol}" / f"{date}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(p, compression="zstd")
    return p


def scan(root: str | Path, symbols: list[str] | None = None,
         dates: list[str] | None = None) -> pl.LazyFrame:
    root = Path(root)
    pats = [f"symbol={s}" for s in symbols] if symbols else ["symbol=*"]
    paths = []
    for s in pats:
        paths += [p for d in (dates or ["*"]) for p in root.glob(f"{s}/{d}.parquet")]
    if not paths:
        raise FileNotFoundError(f"Feature 파일이 없다: {root}")
    return pl.scan_parquet(sorted(paths))
