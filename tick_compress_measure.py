"""실제 175개 파일 전체로 (1) 압축 가능성 재검증 (2) 압축->복원 round-trip 완전일치
(3) CSV/Parquet 용량 비교를 한 번에 한다. 아무것도 지우지 않는다(_tmp_compress_test/
아래에만 씀, data/ 는 안 건드림)."""
import glob
import os

import pandas as pd

from tick_compress import RAW_COLUMNS, compress, decompress, verify_losslessness

TICK_DIR = "data/stocks/tick"
TMP_DIR = "_tmp_compress_test"
os.makedirs(TMP_DIR, exist_ok=True)

files = sorted(glob.glob(f"{TICK_DIR}/*/*.csv"))
print(f"대상 {len(files)}개 파일", flush=True)

raw_total = 0
csv_compact_total = 0
parquet_compact_total = 0
mismatches = []
verify_failures = []

for i, f in enumerate(files, 1):
    code = os.path.basename(os.path.dirname(f))
    date_str = os.path.basename(f)[:-4]
    raw = pd.read_csv(f)
    raw_total += os.path.getsize(f)

    reason = verify_losslessness(raw)
    if reason:
        verify_failures.append((f, reason))
        continue

    compact, ref_price = compress(raw)

    # CSV 왕복
    csv_path = f"{TMP_DIR}/{code}_{date_str}.csv"
    compact.assign(ref_price=ref_price).to_csv(csv_path, index=False)
    csv_compact_total += os.path.getsize(csv_path)
    reread_csv = pd.read_csv(csv_path)
    restored_csv = decompress(reread_csv[["time", "cur_prc", "trde_qty"]], date_str, int(reread_csv["ref_price"].iloc[0]))

    # Parquet 왕복 — ref_price는 컬럼이 아니라 파케이 스키마 메타데이터로 넣는다
    # (매 행 반복 안 해도 됨 — CSV와 달리 파케이는 파일 레벨 key-value 메타데이터를
    # 네이티브로 지원한다).
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq_path = f"{TMP_DIR}/{code}_{date_str}.parquet"
    table = pa.Table.from_pandas(compact, preserve_index=False)
    table = table.replace_schema_metadata({b"ref_price": str(ref_price).encode()})
    pq.write_table(table, pq_path)
    parquet_compact_total += os.path.getsize(pq_path)

    reread_table = pq.read_table(pq_path)
    ref_from_meta = int(reread_table.schema.metadata[b"ref_price"])
    reread_pq = reread_table.to_pandas()
    restored_pq = decompress(reread_pq, date_str, ref_from_meta)

    for restored, tag in [(restored_csv, "csv"), (restored_pq, "parquet")]:
        for col in RAW_COLUMNS:
            a = raw[col].astype("int64")
            b = restored[col].astype("int64")
            if not (a.values == b.values).all():
                mismatches.append((f, tag, col))
                break

    os.remove(csv_path)
    os.remove(pq_path)

    if i % 20 == 0:
        print(f"  {i}/{len(files)} 처리", flush=True)

print(f"\n검증 실패(압축 불가로 판정, 원본 유지 대상): {len(verify_failures)}건")
for f, r in verify_failures:
    print(f"  {f}: {r}")

print(f"\nround-trip 불일치: {len(mismatches)}건")
for f, tag, col in mismatches[:20]:
    print(f"  {f} [{tag}] {col}")

n_ok = len(files) - len(verify_failures)
print(f"\n=== 용량 비교 (압축 성공한 {n_ok}개 파일 기준) ===")
print(f"원본(8컬럼 CSV) 총합: {raw_total/1e6:.2f} MB")
print(f"압축 CSV(4컬럼) 총합: {csv_compact_total/1e6:.2f} MB  ({csv_compact_total/raw_total*100:.1f}%)")
print(f"압축 Parquet(3컬럼+메타) 총합: {parquet_compact_total/1e6:.2f} MB  ({parquet_compact_total/raw_total*100:.1f}%)")
