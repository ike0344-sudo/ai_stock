"""눌림 사다리 진입의 파라미터 최적화.

구조는 사용자 설계 그대로 고정한다.
  1차: 러닝 고점 대비 -d1% 지정가
  2차: -d2% 지정가 (없을 수도 있음)
  3차: 눌림 시작 고점을 되찾을 때(+buf% 확인) 시장가. 못 되찾으면 미체결.
  손절: 러닝 고점 대비 -stop% 전량. 미체결분은 현금(0% 수익).

여기서 d1 / d2 / buf / stop / 레그 비중을 스윕한다.
비교 기준선은 10:00 전량 진입 + 트레일 -5%.
"""
import os
import sys
from itertools import product

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pullback_ladder_backtest import COST_PCT, candidates, simulate

RULE4 = "--rule4" in sys.argv
D1 = [1.0, 1.5, 2.0, 3.0]
D2 = [None, 3.0, 4.0, 5.0]
BUF = [0.0, 0.3]                     # 돌파 확인 여유
STOPS = [4.0, 5.0, 6.0, 7.0]
# (이름, 1차, 2차, 돌파) 비중 — 2차가 없으면 그 몫을 나머지에 균등 배분
WEIGHTS = [
    ("균등", 1 / 3, 1 / 3, 1 / 3),
    ("돌파중심", 0.25, 0.25, 0.50),
    ("눌림중심", 0.35, 0.35, 0.30),
]


def plans():
    for d1, d2, buf, (wn, w1, w2, wb) in product(D1, D2, BUF, WEIGHTS):
        if d2 is not None and d2 <= d1 + 0.4:
            continue
        dips = [(w1, d1)] if d2 is None else [(w1, d1), (w2, d2)]
        wbo = wb + (w2 if d2 is None else 0.0)     # 2차 없으면 그 몫을 돌파로
        s = sum(w for w, _ in dips) + wbo
        dips = [(w / s, d) for w, d in dips]
        yield {
            "label": f"-{d1:g}" + (f"/-{d2:g}" if d2 else "") + f"/돌파+{buf:g} {wn}",
            "d2": d2, "market": 0.0, "dips": dips, "breakout": wbo / s, "bo_buf": buf,
        }


def main() -> None:
    cand = candidates()
    combos = list(plans())
    keys = [(p["label"], s) for p in combos for s in STOPS if s > (p["d2"] or p["dips"][0][1]) + 0.4]
    print(f"후보 {len(cand)}건 × 조합 {len(keys)}개", file=sys.stderr)

    res = {k: [] for k in keys}
    legs = {k: [] for k in keys}
    base = []
    byplan = {p["label"]: p for p in combos}

    for i, (code, g) in enumerate(cand.groupby("stock_code"), 1):
        print(f"\r[{i}/{cand['stock_code'].nunique()}] {code}", end="", file=sys.stderr)
        path = os.path.join("data/stocks/minute", f"{code}.csv")
        if not os.path.exists(path):
            continue
        minute = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
        want = set(g["date"])
        for date, bars in minute.groupby(minute.index.normalize()):
            if date not in want:
                continue
            b = simulate(bars, {"market": 1.0, "dips": [], "breakout": 0.0}, 5.0)
            if b is None:
                continue
            base.append(b[0])
            for label, stop in keys:
                out = simulate(bars, byplan[label], stop)
                if out is not None:
                    res[(label, stop)].append(out[0])
                    legs[(label, stop)].append(out[1])
    print(file=sys.stderr)

    a0 = np.array(base)
    rows = []
    for k, v in res.items():
        a = np.array(v); lg = np.array(legs[k]); tr = a[lg > 0]
        if len(a) == 0:
            continue
        rows.append({
            "안": k[0], "손절": k[1], "진입": (lg > 0).mean() * 100,
            "레그": lg[lg > 0].mean() if (lg > 0).any() else 0,
            "승률": (tr > 0).mean() * 100 if len(tr) else 0,
            "기대값": a.mean(), "평균손": tr[tr <= 0].mean() if (tr <= 0).any() else 0,
            "최악": a.min(), "MDD": (np.maximum.accumulate(np.cumsum(a)) - np.cumsum(a)).max(),
            "누적": a.sum(),
        })
    df = pd.DataFrame(rows)
    df["효율"] = df["기대값"] / df["MDD"].clip(lower=1)   # 자본곡선 낙폭 1%p당 기대값

    print("=" * 112)
    print(f"눌림 사다리 파라미터 스윕  ({'3배제+4조건' if RULE4 else '3배제'} 후보 {len(a0)}건, 비용 {COST_PCT}%)")
    print(f"기준선 = 10:00 전량 진입 + 트레일 -5% : 기대값 {a0.mean():.2f}%  "
          f"최악 {a0.min():.1f}%  MDD {(np.maximum.accumulate(np.cumsum(a0)) - np.cumsum(a0)).max():.1f}%p")
    print("=" * 112)

    def show(title, d):
        print(f"\n{title}")
        print(f"{'설계':>26}{'손절':>6}{'진입':>7}{'레그':>6}{'승률':>7}{'기대값':>8}"
              f"{'평균손':>8}{'최악':>7}{'MDD':>8}{'누적':>8}")
        for _, r in d.iterrows():
            print(f"{r['안']:>26}{r['손절']:>5.0f}%{r['진입']:>6.0f}%{r['레그']:>6.2f}"
                  f"{r['승률']:>6.1f}%{r['기대값']:>7.2f}%{r['평균손']:>7.2f}%"
                  f"{r['최악']:>6.1f}%{r['MDD']:>7.1f}%{r['누적']:>7.0f}%")

    show("[기대값 상위 10]", df.sort_values("기대값", ascending=False).head(10))
    show("[자본곡선 효율(기대값/MDD) 상위 10]", df.sort_values("효율", ascending=False).head(10))
    show("[사용자 원안 -2/-4/돌파 균등]",
         df[df["안"].str.startswith("-2/-4/돌파+0 균등")].sort_values("손절"))

    print("\n" + "-" * 112)
    print("파라미터별 평균 기대값 (다른 값은 평균 처리 — 어느 축이 성과를 만드는지)")
    print("-" * 112)
    df["d1"] = df["안"].str.extract(r"^-([\d.]+)").astype(float)
    df["d2"] = df["안"].str.extract(r"^-[\d.]+/-([\d.]+)").astype(float)
    df["buf"] = df["안"].str.extract(r"돌파\+([\d.]+)").astype(float)
    df["w"] = df["안"].str.split().str[-1]
    for col, lab in [("d1", "1차 눌림 깊이"), ("d2", "2차 눌림 깊이"), ("buf", "돌파 확인폭"),
                     ("손절", "손절폭"), ("w", "비중 배분")]:
        g = df.groupby(col, dropna=False)["기대값"].agg(["mean", "count"])
        print(f"{lab:>14} : " + "   ".join(
            f"{('없음' if pd.isna(k) else k)}={v['mean']:+.2f}%" for k, v in g.iterrows()))


if __name__ == "__main__":
    main()
