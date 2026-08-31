import glob
import os

import pandas as pd

DAILY_DIR = "data/stocks/daily"
MIN_DIR = "data/stocks/minute"
MIN_START = "2025-07-01"  # 분봉 수집 시작 시점 이전 일봉은 애초에 비교 대상 아님

min_files = {os.path.basename(f)[:-4] for f in glob.glob(MIN_DIR + "/*.csv")}
daily_files = sorted(glob.glob(DAILY_DIR + "/*.csv"))
print(f"대상 {len(daily_files)}개 종목 (분봉 보유 {len(min_files)}개) 스캔 시작", flush=True)

rows = []
for i, f in enumerate(daily_files, 1):
    code = os.path.basename(f)[:-4]
    if code not in min_files:
        continue
    try:
        d = pd.read_csv(f, parse_dates=["date"])
        d = d[d["date"] >= MIN_START]
        if d.empty:
            continue
        m = pd.read_csv(f"{MIN_DIR}/{code}.csv", parse_dates=["date"])
        m["d"] = m["date"].dt.strftime("%Y-%m-%d")
        msum = m.groupby("d")["volume"].sum()
    except Exception as exc:
        print(f"  읽기실패 {code}: {exc}")
        continue

    for _, r in d.iterrows():
        ds = r["date"].strftime("%Y-%m-%d")
        daily_vol = r["volume"]
        min_vol = int(msum.get(ds, 0))
        if daily_vol <= 0:
            continue
        ratio = min_vol / daily_vol
        rows.append((code, ds, daily_vol, min_vol, ratio))
    if i % 200 == 0:
        print(f"  {i}/{len(daily_files)}", flush=True)

out = pd.DataFrame(rows, columns=["code", "date", "daily_volume", "minute_volume_sum", "ratio"])
out.to_csv("_dq_volume_mismatch_all.csv", index=False, encoding="utf-8-sig")
print(f"\n전체 종목-일 {len(out)}건 비교 완료 -> _dq_volume_mismatch_all.csv")

# 검증: 006040 2026-07-01 이 걸리는지
chk = out[(out.code == "006040") & (out.date == "2026-07-01")]
print("\n=== 검증 (006040 2026-07-01) ===")
print(chk.to_string(index=False))

flagged = out[out["ratio"] < 0.5].sort_values("ratio")
print(f"\n=== ratio<0.5 (일봉거래량 대비 분봉합계 절반 미만 - 진짜 수집실패 후보) 총 {len(flagged)}건 ===")
print("고유 종목수:", flagged["code"].nunique())
flagged.to_csv("_dq_real_gaps.csv", index=False, encoding="utf-8-sig")
print(flagged.head(30).to_string(index=False))
