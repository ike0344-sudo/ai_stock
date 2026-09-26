"""분봉 CSV -> parquet(zstd) 전환. 원본 CSV는 지우지 않는다.

    python tools/convert_minute_to_parquet.py data/stocks/minute

왜 분봉만인가: 파일이 3.1MB대라 parquet이 확실히 유리하다(용량 81%↓, 읽기 2.8배).
**일봉(55KB)·월봉(13KB)은 오히려 5~10배 느리다** — 메타데이터 오버헤드가 본문보다
커서다. 그래서 여기 경로를 넓히지 말 것.

지켜야 할 것 두 가지:
1. **인덱스(날짜)를 보존한다.** `data_loader._resample_minute`이 `df.index.normalize()`
   로 날짜별로 잘라 리샘플하므로, 인덱스를 컬럼으로 풀어 저장하면 하루 경계가 깨져
   전날 15:29 와 다음날 09:00 이 한 봉에 섞인다. `to_parquet`은 인덱스를 보존한다.
2. **원자적으로 쓴다.** `_read_local`이 parquet을 **CSV보다 먼저** 보기 때문에,
   쓰다 만 parquet이 남으면 멀쩡한 CSV를 두고 깨진 파일을 읽게 된다.
   임시파일에 쓴 뒤 os.replace 로 교체한다(같은 볼륨에서 원자적).

원본 CSV는 남긴다 — 전수 대조(tools/verify_parquet_migration.py)의 기준이고,
데이터 보존 원칙과도 맞는다.
"""
from __future__ import annotations

import os
import sys
import time

import pandas as pd

COMPRESSION = "zstd"   # 절감률 실측이 zstd 기준이다. 바꾸면 수치가 달라진다.


def convert_one(csv_path: str) -> tuple[bool, str]:
    """(바꿨나, 사유). 이미 최신 parquet이 있으면 건너뛴다(재실행 가능)."""
    pq_path = csv_path[:-4] + ".parquet"
    if os.path.exists(pq_path) and os.path.getmtime(pq_path) >= os.path.getmtime(csv_path):
        return False, "이미 최신"

    df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    if not isinstance(df.index, pd.DatetimeIndex):
        return False, f"인덱스가 날짜가 아님({df.index.dtype}) — 건너뜀"

    tmp = pq_path + ".tmp"
    df.to_parquet(tmp, compression=COMPRESSION)
    # 디스크에 실제로 쓰인 것을 다시 읽어 확인한 뒤에만 자리에 넣는다.
    back = pd.read_parquet(tmp)
    if len(back) != len(df) or list(back.columns) != list(df.columns) \
            or not isinstance(back.index, pd.DatetimeIndex):
        os.remove(tmp)
        return False, "round-trip 확인 실패 — 건너뜀"
    os.replace(tmp, pq_path)
    return True, ""


def main(root: str) -> int:
    csvs = sorted(
        os.path.join(dp, n)
        for dp, _, names in os.walk(root) for n in names if n.endswith(".csv")
    )
    if not csvs:
        print(f"{root}: CSV가 없다")
        return 1

    t0 = time.time()
    done = skipped = 0
    failed: list[tuple[str, str]] = []
    for i, csv in enumerate(csvs, 1):
        try:
            changed, why = convert_one(csv)
        except Exception as exc:                      # 한 파일 때문에 전체를 멈추지 않는다
            failed.append((os.path.basename(csv), f"{type(exc).__name__}: {exc}"))
            continue
        if changed:
            done += 1
        else:
            skipped += 1
            if why not in ("이미 최신",):
                failed.append((os.path.basename(csv), why))
        if i % 100 == 0 or i == len(csvs):
            el = time.time() - t0
            print(f"  {i}/{len(csvs)}  변환 {done} 건너뜀 {skipped} 실패 {len(failed)}  "
                  f"경과 {el/60:.1f}분", flush=True)

    sc = sum(os.path.getsize(c) for c in csvs)
    sp = sum(os.path.getsize(c[:-4] + ".parquet") for c in csvs
             if os.path.exists(c[:-4] + ".parquet"))
    print(f"\n변환 {done} · 건너뜀 {skipped} · 실패 {len(failed)}")
    print(f"용량 CSV {sc/1e9:.2f}GB -> parquet {sp/1e9:.2f}GB ({100*(1-sp/max(sc,1)):.0f}% 절감)")
    print("원본 CSV는 지우지 않았다 — 전수 대조의 기준이다.")
    for name, why in failed[:20]:
        print(f"  실패 {name}: {why}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "data/stocks/minute"))
