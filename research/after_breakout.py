"""240일 신고가 돌파 뒤 '더 간' 종목은 어떻게 올라갔나 (사용자 2026-10-04). breakout_shapes 의 돌파 329건을 돌파 후 20거래일로 나눈다.

    python research/after_breakout.py      # → results/breakout_shapes/05~07_*.png + 통계

- 더 감 = 돌파 후 20거래일 안 종가 최고가 옛 고점 +20% 이상 · 되밀림 = 10거래일 뒤 종가가 옛 고점 아래 · 그 사이 = 보통
- 되돌림(리테스트) = 돌파 다음 날 ~ 최고 종가 날 사이 최저가가 옛 고점의 몇 % 위/아래까지 내려왔나
"""
from __future__ import annotations

import importlib.util
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
spec = importlib.util.spec_from_file_location("bs", "research/breakout_shapes.py")
bs = importlib.util.module_from_spec(spec); spec.loader.exec_module(bs)
plt.rcParams["font.family"] = "Malgun Gothic"; plt.rcParams["axes.unicode_minus"] = False
OUT, N = bs.OUT, 20
GROUP_COLOR = {"더 감": "#d0332f", "보통": "#e0a500", "되밀림": "#1462c9"}


def main():
    events = bs.load_events()
    rows, keep = [], []
    for e in events:
        r = bs.analyze(e)
        if r["outcome"] != "돌파":
            continue
        d, i = e["d"], e["i"]
        H, b = d.h240[i], i + r["days"]
        if b + N >= len(d):
            continue
        f = d.iloc[b + 1:b + 1 + N]
        peak_i = f.close.idxmax()
        peak = f.close.max() / H - 1
        grp = "더 감" if peak >= 0.20 else ("되밀림" if d.close[b + 10] < H else "보통")
        to_peak = d.loc[b + 1:peak_i]
        x = dict(name=r["name"], date=r["date"], grp=grp, peak=peak * 100, peak_day=int(peak_i - b),
                 bo_over=(d.close[b] / H - 1) * 100,                                 # 돌파일 종가가 옛 고점보다 몇 % 위
                 next1=(d.close[b + 1] / d.close[b] - 1) * 100,                      # 돌파 다음 날
                 first3=(d.close[b + 3] / d.close[b] - 1) * 100,
                 retest=(to_peak.low.min() / H - 1) * 100,                           # 최고점 전까지 옛 고점 쪽으로 얼마나 내려왔나
                 below_ma5=int((to_peak.close < to_peak.ma5).sum()),                 # 최고점 전까지 5일선 아래 마감한 날 수
                 up_days=float((f.close.iloc[:10].diff().fillna(f.close.iloc[0] - d.close[b]) > 0).mean() * 100),
                 bo_vol=d.volume[b] / d.volume[i], after_vol=f.volume.iloc[:5].mean() / d.volume[b],
                 gaps=int((f.open.iloc[:10].values > d.high.iloc[b:b + 10].values).sum()))  # 전날 고가 위로 갭 시작한 날(10일)
        rows.append(x); keep.append((e, r, x))
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    print(df.grp.value_counts().to_string())
    g = df.groupby("grp").agg(건수=("name", "size"), 돌파일_고점위=("bo_over", "median"), 다음날=("next1", "median"),
                              사흘=("first3", "median"), 최고점까지날=("peak_day", "median"), 되돌림=("retest", "median"),
                              오일선아래날=("below_ma5", "median"), 상승일비율=("up_days", "median"),
                              돌파일거래량배=("bo_vol", "median"), 이후5일거래량=("after_vol", "median"), 갭상승날=("gaps", "median"))
    print(g.round(2).to_string())
    up = df[df.grp == "더 감"]
    print("\n[더 감] 되돌림 분포", pd.cut(up.retest, [-50, -3, 0, 3, 8, 100]).value_counts().sort_index().to_string())
    print("[더 감] 다음 날 상승 비율", (up.next1 > 0).mean().round(2), " / 되밀림", (df[df.grp == '되밀림'].next1 > 0).mean().round(2))
    print("[더 감] 최고점 전 5일선 아래 마감 0일 비율", (up.below_ma5 == 0).mean().round(2))
    df.to_csv(f"{OUT}/after_breakout.csv", index=False, encoding="utf-8-sig")

    # 그림 1: 돌파일 기준 경로(그룹별 중앙값)
    fig, ax = plt.subplots(figsize=(9, 4.8)); xs = np.arange(-5, N + 1)
    for grp, col in GROUP_COLOR.items():
        m = np.array([(e["d"].close.iloc[e["i"] + r["days"] - 5:e["i"] + r["days"] + N + 1].values / e["d"].h240[e["i"]] - 1) * 100
                      for e, r, x in keep if x["grp"] == grp])
        if not len(m):
            continue
        ax.fill_between(xs, np.percentile(m, 25, axis=0), np.percentile(m, 75, axis=0), color=col, alpha=0.10, lw=0)
        ax.plot(xs, np.median(m, axis=0), color=col, lw=2, label=f"{grp} ({len(m)}건)")
    ax.axhline(0, color=bs.INK, lw=0.8, ls="--"); ax.axvline(0, color=bs.MUTED, lw=0.8)
    ax.set_xlabel("돌파일로부터 거래일"); ax.set_ylabel("옛 고점 대비 종가 (%)")
    ax.set_title("신고가 돌파 뒤 경로 — 더 감 / 보통 / 되밀림 (중앙값, 띠 = 가운데 50%)", loc="left", fontsize=11)
    ax.grid(axis="y", color=bs.GRID, lw=0.6); ax.legend(frameon=False, fontsize=9)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout(); fig.savefig(f"{OUT}/05_after_breakout_path.png", dpi=150); plt.close(fig)

    # 그림 2·3: 더 감 / 되밀림 실제 일봉(최근 12개)
    for grp, fn in (("더 감", "06_examples_더감.png"), ("되밀림", "07_examples_되밀림.png")):
        ex = sorted([k for k in keep if k[2]["grp"] == grp], key=lambda k: k[2]["date"])[-12:]
        fig, axes = plt.subplots(3, 4, figsize=(14, 8.4))
        for ax, (e, r, x) in zip(axes.flat, ex):
            b = e["i"] + r["days"]
            bs.candles(ax, e["d"], e["i"] - 10, min(b + N, len(e["d"]) - 1), e["d"].h240[e["i"]], e["i"], b,
                       f"{x['name']} {x['date']} · 최고 +{x['peak']:.0f}%({x['peak_day']}일) · 되돌림 {x['retest']:+.1f}%")
        for ax in axes.flat[len(ex):]:
            ax.axis("off")
        fig.suptitle(f"신고가 돌파 뒤 — {grp}  (파란 띠 = 기준봉, 빨간 점선 = 옛 고점, 노랑 5일선·보라 20일선)", x=0.01, ha="left", fontsize=11)
        fig.tight_layout(); fig.savefig(f"{OUT}/{fn}", dpi=130); plt.close(fig)


if __name__ == "__main__":
    main()
