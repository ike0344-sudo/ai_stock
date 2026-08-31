"""5년치 일봉으로 국면 효과가 재현되는지 - 1년치 결론의 표본을 늘려본다.

    python regime5y.py

1분봉은 API 보유 이력이 1년뿐이라 클린20(경로 낙폭)은 5년치를 못 만든다. 대신
일봉만으로 되는 대리 지표를 쓴다.

  모집단 : 그날 거래대금(종가x거래량) 상위 10 종목
  결과   : 그중 당일 고가가 전일종가 대비 +20% 이상인 종목이 하나라도 있나
           (클린20의 필요조건. 경로가 깨끗했는지는 일봉으로 알 수 없다)
  국면   : 코스피 일봉 이평 - 15분 60봉/120봉(2.3일/4.6일)에 대응하는 짧은 축부터
           긴 축까지 사다리로 놓고 어느 시간축에서 효과가 나오는지 본다

한계 두 개를 안고 읽어야 한다.
  - 생존편향: 지금 유니버스에 있는 606종목만 본다(상장폐지/편입 전 종목 없음)
  - 일봉 대금 순위는 10:00 장중 순위와 다르다
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import wilson

DAILY_DIR = "data/stocks/daily"
INDEX = "data/index/daily/001.csv"
TOP_N = 10
CACHE = "results/regime5y_days.csv"
PAIRS = [(3, 5), (5, 10), (5, 20), (10, 20), (20, 60)]


def build_days() -> pd.DataFrame:
    if os.path.exists(CACHE):
        return pd.read_csv(CACHE, index_col=0, parse_dates=True)

    val, hit20 = {}, {}
    for f in glob.glob(os.path.join(DAILY_DIR, "*.csv")):
        try:
            d = pd.read_csv(f, index_col=0, parse_dates=True).sort_index()
        except Exception:
            continue
        if len(d) < 30:
            continue
        v = d["close"] * d["volume"]
        r = d["high"] / d["close"].shift(1) - 1
        code = os.path.basename(f)[:-4]
        val[code] = v
        hit20[code] = r >= 0.20

    V = pd.DataFrame(val).sort_index()
    H = pd.DataFrame(hit20).reindex_like(V).fillna(False)
    # 그날 대금 상위 TOP_N만 남기고 그 안에서 +20% 도달 종목 수를 센다
    rank = V.rank(axis=1, ascending=False, method="first")
    top = rank <= TOP_N
    out = pd.DataFrame({
        "n_top": top.sum(axis=1),
        "n_reach": (top & H).sum(axis=1),
        "top_value_eok": V.where(top).sum(axis=1) / 1e8,
    })
    out = out[out["n_top"] >= TOP_N]
    out["hit"] = out["n_reach"] > 0
    out.to_csv(CACHE, encoding="utf-8-sig")
    return out


def regimes(idx: pd.Series) -> pd.DataFrame:
    """이평 사다리. 판정은 전일 종가까지만 써서 당일 정보가 안 새게 한다."""
    out = {}
    for s, l in PAIRS:
        ma_s, ma_l = idx.rolling(s).mean().shift(1), idx.rolling(l).mean().shift(1)
        prev = idx.shift(1)
        out[f"align_{s}_{l}"] = np.where(ma_s > ma_l, "정배열", "역배열")
        out[f"above_{s}"] = np.where(prev > ma_s, "위", "아래")
    return pd.DataFrame(out, index=idx.index)


def line(label: str, g: pd.DataFrame, base: float) -> None:
    k, n = int(g["hit"].sum()), len(g)
    if n < 20:
        print(f"{label:>20}{n:>7}   표본부족")
        return
    lo, hi = wilson(k, n)
    print(f"{label:>20}{n:>7}{k/n*100:>8.0f}%{k/n/base:>8.2f}x{g['n_reach'].mean():>9.2f}"
          f"{f'[{lo:.0f}-{hi:.0f}]':>11}")


def main() -> None:
    d = build_days()
    idx = pd.read_csv(INDEX, index_col=0, parse_dates=True).sort_index()["close"]
    d = d.join(regimes(idx), how="inner").dropna()
    base = d["hit"].mean()

    print("=" * 74)
    print(f"5년치 일봉 대리분석  |  {d.index.min().date()} ~ {d.index.max().date()} {len(d)}거래일")
    print(f"  +20% 도달 종목이 하루라도 있던 날 {int(d['hit'].sum())} ({base*100:.0f}%)")
    print("=" * 74)

    print(f"\n{'구간':>20}{'일수':>7}{'적중':>8}{'배수':>8}{'도달종목/일':>9}{'95%CI':>11}")
    for s, l in PAIRS:
        print(f"\n-- 이평 {s}일 vs {l}일 --")
        for t in ("정배열", "역배열"):
            line(f"{t}", d[d[f"align_{s}_{l}"] == t], base)
        for p in ("위", "아래"):
            line(f"지수 {s}일선 {p}", d[d[f"above_{s}"] == p], base)

    print("\n" + "-" * 74)
    print("연도별로 재현되나 (이평 5일 vs 20일 기준)")
    print("-" * 74)
    print(f"{'연도':>8}{'일수':>7}{'전체':>8}{'정배열':>9}{'역배열':>9}{'차이':>8}")
    for y, g in d.groupby(d.index.year):
        if len(g) < 60:
            continue
        up = g[g["align_5_20"] == "정배열"]["hit"].mean() * 100
        dn = g[g["align_5_20"] == "역배열"]["hit"].mean() * 100
        print(f"{y:>8}{len(g):>7}{g['hit'].mean()*100:>7.0f}%{up:>8.0f}%{dn:>8.0f}%{up-dn:>+7.0f}%p")

    print("\n" + "-" * 74)
    print("1년치 구간(2025-07~2026-07)이 5년 평균과 얼마나 달랐나")
    print("-" * 74)
    recent = d.loc["2025-07-01":"2026-07-16"]
    older = d.loc[:"2025-06-30"]
    print(f"{'':>16}{'적중률':>9}{'정배열 비중':>12}{'top10 대금(억)':>15}")
    for lab, g in [("최근 1년", recent), ("이전 4년", older)]:
        print(f"{lab:>16}{g['hit'].mean()*100:>8.0f}%"
              f"{(g['align_5_20'] == '정배열').mean()*100:>11.0f}%{g['top_value_eok'].median():>15.0f}")


def demo() -> None:
    """이평 판정에 당일 종가가 안 섞이는지 - shift(1)이 빠지면 룩어헤드가 된다."""
    s = pd.Series([1.0, 2, 3, 4, 5], index=pd.date_range("2026-01-01", periods=5))
    ma = s.rolling(2).mean().shift(1)
    assert pd.isna(ma.iloc[1]), ma.tolist()
    assert ma.iloc[2] == 1.5, ma.tolist()      # 3일차 판정은 1,2일 평균
    print("demo ok")


if __name__ == "__main__":
    demo() if "--demo" in sys.argv else main()
