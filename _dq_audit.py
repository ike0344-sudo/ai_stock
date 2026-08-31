import glob
import os
from collections import defaultdict

import pandas as pd

ROOT = "data/stocks"
MIN_DIR = f"{ROOT}/minute"
DAILY_DIR = f"{ROOT}/daily"

# ---------- Task 1: 결측 구간 (전 종목) ----------
counts: dict[str, dict] = {}
files = sorted(glob.glob(MIN_DIR + "/*.csv"))
print(f"분봉 파일 {len(files)}개 스캔 시작", flush=True)
for i, f in enumerate(files, 1):
    code = os.path.basename(f)[:-4]
    try:
        df = pd.read_csv(f, usecols=["date"], parse_dates=["date"])
    except Exception as exc:
        print(f"  읽기실패 {code}: {exc}")
        continue
    d = df["date"].dt.date
    counts[code] = d.value_counts().to_dict()
    if i % 200 == 0:
        print(f"  {i}/{len(files)}", flush=True)

day_max: dict = defaultdict(int)
for code, dc in counts.items():
    for date, c in dc.items():
        if c > day_max[date]:
            day_max[date] = c

rows = []
for code, dc in counts.items():
    for date, c in dc.items():
        rows.append((code, date, c, day_max[date]))
df_all = pd.DataFrame(rows, columns=["code", "date", "count", "day_max"])
df_all["ratio"] = df_all["count"] / df_all["day_max"]

print("\n=== 하루 평균 분봉수 분포 (종목-일 단위, 전체) ===")
print(df_all["count"].describe())

stock_avg = df_all.groupby("code")["count"].mean().sort_values()
print("\n=== 종목별 평균 분봉수 최하위 20 ===")
print(stock_avg.head(20))

stock_median = df_all.groupby("code")["count"].median()
severe = df_all[df_all["ratio"] < 0.5].copy()
severe = severe.merge(stock_median.rename("own_median"), on="code")
severe["own_ratio"] = severe["count"] / severe["own_median"]
severe["type"] = severe["own_ratio"].apply(
    lambda r: "collection-gap-like" if r < 0.5 else "chronic-low-liquidity-like"
)
severe = severe.sort_values("ratio")
print(f"\n=== ratio<0.5 (그날 시장 최대 대비 절반 미만) 총 {len(severe)}건 ===")
print(severe["type"].value_counts())
severe.to_csv("_dq_missing_minutes.csv", index=False, encoding="utf-8-sig")
print("전체 목록 -> _dq_missing_minutes.csv")

gap_only = severe[severe["type"] == "collection-gap-like"].sort_values("ratio")
print(f"\n=== collection-gap-like 상위 30건 (own_median 대비도 낮음 = 수집 결손 의심) ===")
print(gap_only.head(30).to_string(index=False))

# ---------- Task 2: 액면분할/병합 미반영 의심 갭 ----------
daily_files = sorted(glob.glob(DAILY_DIR + "/*.csv"))
print(f"\n일봉 파일 {len(daily_files)}개 스캔 시작", flush=True)
gap_rows = []
for f in daily_files:
    code = os.path.basename(f)[:-4]
    try:
        d = pd.read_csv(f, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    except Exception as exc:
        print(f"  읽기실패 {code}: {exc}")
        continue
    d["prev_close"] = d["close"].shift(1)
    d["gap_pct"] = (d["open"] - d["prev_close"]) / d["prev_close"] * 100
    flagged = d[d["gap_pct"].abs() >= 40]
    for _, r in flagged.iterrows():
        gap_rows.append((code, r["date"].date(), r["prev_close"], r["open"], round(r["gap_pct"], 2)))

gap_df = pd.DataFrame(gap_rows, columns=["code", "date", "prev_close", "open", "gap_pct"])
print(f"\n=== |시가갭| >= 40% 인 종목-일 총 {len(gap_df)}건 ===")

trades_path = "results/strategy1_trades_full.csv"
if os.path.isfile(trades_path):
    tr = pd.read_csv(trades_path, usecols=["code", "entry_time"], parse_dates=["entry_time"])
    tr["code"] = tr["code"].astype(str).str.zfill(6)
    tr["date"] = tr["entry_time"].dt.date
    traded_codes = set(tr["code"])
    traded_pairs = set(zip(tr["code"], tr["date"]))
    gap_df["code"] = gap_df["code"].astype(str)
    gap_df["ever_traded_strategy1"] = gap_df["code"].isin(traded_codes)
    gap_df["exact_date_traded"] = list(zip(gap_df["code"], gap_df["date"]))
    gap_df["exact_date_traded"] = gap_df["exact_date_traded"].apply(lambda p: p in traded_pairs)
else:
    print(f"  경고: {trades_path} 없음 - 백테스트 포함 여부 확인 못함")
    gap_df["ever_traded_strategy1"] = None
    gap_df["exact_date_traded"] = None

gap_df.to_csv("_dq_split_gaps.csv", index=False, encoding="utf-8-sig")
print(gap_df.sort_values("gap_pct", key=lambda s: s.abs(), ascending=False).to_string(index=False))
print("전체 목록 -> _dq_split_gaps.csv")
