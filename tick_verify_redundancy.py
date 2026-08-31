"""완료된 틱 파일 전체에서 open=high=low=cur_prc, pred_pre_sig 상수, pred_pre가
cur_prc에서 유도 가능한지(파일 내 cur_prc-pred_pre가 상수) 전수 검증한다. 하나라도
어긋나면 그 파일 경로를 보고한다 — 어긋나는 게 있으면 그 컬럼은 압축에서 못 뺀다.
"""
import glob
import json
import os

import pandas as pd

TICK_DIR = "data/stocks/tick"

files = sorted(glob.glob(f"{TICK_DIR}/*/*.csv"))
print(f"검사 대상 {len(files)}개 파일", flush=True)

violations = []
for i, f in enumerate(files, 1):
    d = pd.read_csv(f, dtype={"cntr_tm": str})
    ohlc_ok = (d["open_pric"] == d["cur_prc"]).all() and \
              (d["high_pric"] == d["cur_prc"]).all() and \
              (d["low_pric"] == d["cur_prc"]).all()
    if not ohlc_ok:
        violations.append((f, "open/high/low != cur_prc"))
        continue

    sig_ok = d["pred_pre_sig"].nunique() == 1
    if not sig_ok:
        violations.append((f, f"pred_pre_sig 불일치 {d['pred_pre_sig'].unique().tolist()}"))
        continue

    diff = d["cur_prc"] - d["pred_pre"]
    ref_ok = diff.nunique() == 1
    if not ref_ok:
        violations.append((f, f"cur_prc-pred_pre 불일치, 고유값 {diff.nunique()}개"))
        continue

    date_prefix_ok = d["cntr_tm"].str[:8].nunique() == 1
    if not date_prefix_ok:
        violations.append((f, "cntr_tm 날짜 접두 불일치"))
        continue

    if i % 20 == 0:
        print(f"  {i}/{len(files)} 검사 완료, 위반 {len(violations)}건", flush=True)

print(f"\n전체 {len(files)}개 파일 검사 완료, 위반 {len(violations)}건")
if violations:
    for f, reason in violations:
        print(f"  위반: {f} - {reason}")
else:
    print("전부 통과 - open=high=low=cur_prc 100%, pred_pre_sig/기준가 파일당 상수 확인됨")

with open("_tick_verify_result.json", "w", encoding="utf-8") as fp:
    json.dump({"checked": len(files), "violations": violations}, fp, ensure_ascii=False, indent=2)
