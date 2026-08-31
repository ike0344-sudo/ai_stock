"""관성 재측정 — 수급이 붙은 순간만, 평균이 아니라 꼬리까지.

    python momentum_scan2.py

1차(momentum_scan.py)는 380만 개 전체 평균이라 관성이 묻혔다. 여기서는 두 가지를 고친다.
  1) 그 15분봉에 거래대금이 실제로 실린 순간만 본다 (한산한 시간대 제외)
  2) 평균만이 아니라 상위 10%와 "+2% 이상 갈 확률"을 같이 본다 —
     관성은 가끔 크게 가는 성질이라 평균으로만 재면 안 보인다
"""
import glob
import os
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MINUTE_DIR = "data/stocks/minute"
FWD_BARS = 4
MA = 60
MIN_VALUE = 1_000_000_000      # 15분봉 거래대금 10억 — 수급이 붙은 순간만
BANDS = [(-99, 0, "음수"), (0, 2, "0~2%"), (2, 4, "2~4%"), (4, 6, "4~6%"),
         (6, 8, "6~8%"), (8, 10, "8~10%"), (10, 999, "10%+")]


def scan_one(path: str) -> pd.DataFrame | None:
    try:
        m = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
    except (OSError, ValueError, pd.errors.ParserError):
        return None
    if "close" not in m or "volume" not in m or len(m) < 2000:
        return None
    g = m.resample("15min").agg({"close": "last", "volume": "sum"}).dropna()
    if len(g) < MA + FWD_BARS + 10:
        return None
    g["value"] = g["close"] * g["volume"]
    g["ma"] = g["close"].rolling(MA).mean()
    d = g.dropna(subset=["ma"]).copy()
    d["gap"] = (d["close"] / d["ma"] - 1) * 100
    d["day"] = d.index.normalize()
    d["hour"] = d.index.hour
    d["fwd"] = (d.groupby("day")["close"].shift(-FWD_BARS) / d["close"] - 1) * 100
    d = d.dropna(subset=["fwd"])
    return d[d["value"] >= MIN_VALUE][["gap", "fwd", "hour"]]


def table(d: pd.DataFrame, title: str) -> None:
    print()
    print(f"{title} — 관측 {len(d):,}")
    print(f"{'이격':<10}{'관측수':>9}{'평균':>9}{'중앙':>8}{'상위10%':>9}{'+2%확률':>9}{'상승':>7}")
    for lo, hi, lab in BANDS:
        x = d[(d["gap"] >= lo) & (d["gap"] < hi)]["fwd"]
        if len(x) < 200:
            continue
        print(f"  {lab:<8}{len(x):>9,}{x.mean():>8.3f}%{x.median():>7.3f}%"
              f"{x.quantile(.9):>8.2f}%{(x >= 2).mean() * 100:>8.1f}%{(x > 0).mean() * 100:>6.0f}%")


def main() -> None:
    files = sorted(glob.glob(os.path.join(MINUTE_DIR, "*.csv")))
    parts = []
    for i, f in enumerate(files, 1):
        out = scan_one(f)
        if out is not None and len(out):
            parts.append(out)
        if i % 300 == 0:
            print(f"  {i}/{len(files)}")
    d = pd.concat(parts, ignore_index=True)
    table(d, f"거래대금 {MIN_VALUE / 1e8:.0f}억 이상 15분봉만")
    table(d[d["hour"] < 10], "그중 09:00~10:00")
    table(d[d["hour"] >= 13], "그중 13:00 이후")

    hi = d[d["gap"] >= 6]["fwd"]
    lo = d[(d["gap"] >= 0) & (d["gap"] < 6)]["fwd"]
    print()
    print(f"이격 6%+ {len(hi):,}개 · 평균 {hi.mean():+.3f}% · +2%확률 {(hi >= 2).mean() * 100:.1f}%")
    print(f"이격 0~6% {len(lo):,}개 · 평균 {lo.mean():+.3f}% · +2%확률 {(lo >= 2).mean() * 100:.1f}%")


if __name__ == "__main__":
    main()
