"""CSV → parquet 전환이 값을 바꾸지 않았는지 대조한다.

사용: python tools/verify_parquet_migration.py data/stocks/minute

왜 필요한가: 형식만 바꿨는데 값이 달라지는 사고는 **에러 없이 조용히** 일어난다.
실제로 겪은 것들 — pandas가 매번 타입을 추측하다 바뀌는 것, 인덱스가 컬럼으로
풀려 날짜 경계가 깨지는 것(그러면 전날 15:29와 다음날 09:00이 한 봉에 섞인다).

**표본이 아니라 전수로 돈다.** 눈으로 안 보이는 종류라 몇 개만 봐선 의미가 없다.
"""
from __future__ import annotations

import os
import sys

import pandas as pd


def check(csv_path: str, pq_path: str) -> str | None:
    """다르면 이유 문자열, 같으면 None."""
    a = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    b = pd.read_parquet(pq_path)
    if not isinstance(b.index, pd.DatetimeIndex):
        return f"인덱스가 날짜가 아님({b.index.dtype}) — 날짜별 리샘플이 조용히 깨진다"
    if len(a) != len(b):
        return f"행 수 {len(a)} != {len(b)}"
    if list(a.columns) != list(b.columns):
        return f"컬럼 {list(a.columns)} != {list(b.columns)}"
    try:
        pd.testing.assert_frame_equal(a, b, check_dtype=False)
    except AssertionError as e:
        return str(e).split("\n")[0]
    return None


def main(root: str) -> int:
    pairs = []
    for dirpath, _, names in os.walk(root):
        for n in names:
            if n.endswith(".parquet"):
                csv = os.path.join(dirpath, n[:-8] + ".csv")
                if os.path.exists(csv):
                    pairs.append((csv, os.path.join(dirpath, n)))
    if not pairs:
        print(f"{root}: CSV와 parquet이 둘 다 있는 파일이 없다. "
              f"(원본 CSV를 지웠다면 대조할 기준이 없는 것이다)")
        return 1

    bad, sc, sp = [], 0, 0
    for csv, pq in pairs:
        sc += os.path.getsize(csv)
        sp += os.path.getsize(pq)
        why = check(csv, pq)
        if why:
            bad.append((os.path.basename(pq), why))

    print(f"대조 {len(pairs):,}쌍 · 불일치 {len(bad)}건")
    print(f"용량 {sc/1e9:.2f}GB → {sp/1e9:.2f}GB ({100*(1-sp/sc):.0f}% 절감)")
    for name, why in bad[:20]:
        print(f"  불일치 {name}: {why}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "data/stocks/minute"))
