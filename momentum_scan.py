"""종목 15분봉에서 60선 이격이 클수록 관성이 붙는가.

    python momentum_scan.py

사용자 관찰: "15분봉 60선 대비 6% 이상 이격에서 관성이 나온다."

재는 방법 — 각 15분봉 시점에서 이격을 구하고, 그 뒤 4봉(1시간) 뒤 종가 수익률을 본다.
관성이 있다면 이격이 클수록 이후 수익률이 높아야 한다. 반대로 평균회귀면 이격이 클수록
이후가 나빠진다. 어느 쪽인지 데이터가 답한다.

**같은 날 안에서만** 앞을 본다. 날을 넘기면 종가~시가 갭이 섞여 장중 관성이 아니라
오버나이트 수익률을 재게 된다.
"""
import glob
import os
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MINUTE_DIR = "data/stocks/minute"
FWD_BARS = 4              # 4봉 = 1시간
MA = 60                   # 60봉 = 15시간 ≈ 2.3거래일
BANDS = [(-99, 0, "이격 음수"), (0, 2, "0~2%"), (2, 4, "2~4%"), (4, 6, "4~6%"),
         (6, 8, "6~8%"), (8, 10, "8~10%"), (10, 999, "10%+")]


def scan_one(path: str) -> pd.DataFrame | None:
    try:
        m = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
    except (OSError, ValueError, pd.errors.ParserError):
        return None
    if "close" not in m or len(m) < 2000:
        return None
    k = m["close"].resample("15min").last().dropna()
    if len(k) < MA + FWD_BARS + 10:
        return None

    ma = k.rolling(MA).mean()
    d = pd.DataFrame({"close": k, "ma": ma}).dropna()
    d["gap"] = (d["close"] / d["ma"] - 1) * 100
    d["day"] = d.index.normalize()
    # 같은 날 안에서만 앞을 본다 — 날이 바뀌면 NaN이 되어 자동으로 빠진다.
    d["fwd"] = (d.groupby("day")["close"].shift(-FWD_BARS) / d["close"] - 1) * 100
    return d.dropna(subset=["fwd"])[["gap", "fwd"]]


def main() -> None:
    files = sorted(glob.glob(os.path.join(MINUTE_DIR, "*.csv")))
    print(f"종목 {len(files)}개 스캔")
    parts, done = [], 0
    for i, f in enumerate(files, 1):
        out = scan_one(f)
        if out is not None and len(out):
            parts.append(out)
            done += 1
        if i % 200 == 0:
            print(f"  {i}/{len(files)} · 유효 {done}")
    d = pd.concat(parts, ignore_index=True)
    print(f"관측 {len(d):,}개 (15분봉 시점) · 종목 {done}개\n")

    base = d["fwd"].mean()
    print(f"{'이격 구간':<12}{'관측수':>10}{'1시간 뒤 평균':>13}{'중앙값':>9}{'상승비율':>9}{'기준대비':>9}")
    for lo, hi, lab in BANDS:
        g = d[(d["gap"] >= lo) & (d["gap"] < hi)]
        if len(g) < 100:
            continue
        print(f"  {lab:<10}{len(g):>10,}{g['fwd'].mean():>12.3f}%{g['fwd'].median():>8.3f}%"
              f"{(g['fwd'] > 0).mean() * 100:>8.0f}%{g['fwd'].mean() - base:>+8.3f}%")
    print(f"\n전체 평균 {base:+.3f}% · 상승비율 {(d['fwd'] > 0).mean() * 100:.0f}%")

    # 관성이 있다면 이격이 커질수록 이후 수익률이 올라가야 한다. 6% 위/아래로 갈라 확인.
    hi = d[d["gap"] >= 6]["fwd"]
    lo = d[(d["gap"] >= 0) & (d["gap"] < 6)]["fwd"]
    print(f"\n이격 6%+ {len(hi):,}개 평균 {hi.mean():+.3f}% · "
          f"0~6% {len(lo):,}개 평균 {lo.mean():+.3f}% · 차이 {hi.mean() - lo.mean():+.3f}%p")


if __name__ == "__main__":
    main()
