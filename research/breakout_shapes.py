"""거래대금 폭발 → 240일 신고가 돌파 종목은 어떤 일봉 모양으로 가나 (사용자 2026-10-04). 그림 + 통계.

    python research/breakout_shapes.py      # → results/breakout_shapes/*.png, summary.csv

## 사건 (거래대금 폭발 화면과 같은 재료)
- 그날 통합 실거래대금이 역대/4년/1년 최대(backtesting.value_burst.tiers_of) + 1,000억 이상 + KRX 종가 +7% 이상
- 그날 고가가 직전 240일 고점(옛 고점) 아래, 종가 기준 옛 고점까지 25% 이내. 같은 종목 20거래일 안 중복은 첫 사건만.
## 결과 (폭발 다음 날부터 20거래일)
- 돌파 = 종가가 옛 고점 위로 마감한 날이 있음 · 터치만 = 고가만 닿음 · 실패 = 못 닿음
## 돌파 종목 모양 분류 (폭발일 ~ 돌파 전날)
- 직행: 3거래일 안 돌파 · 얕은 눌림: 폭발일 저가를 안 깨고 돌파 · 깊은 눌림: 폭발일 저가를 깼다가 돌파
"""
from __future__ import annotations

import glob
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from backtesting.value_burst import tiers_of  # noqa: E402
from backtesting import rs_rating as R  # noqa: E402

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False
OUT = "results/breakout_shapes"
UP, DOWN, INK, MUTED, GRID = "#d0332f", "#1462c9", "#17181c", "#6b7280", "#e5e7eb"
OUTCOME_COLOR = {"돌파": "#d0332f", "터치만": "#e0a500", "실패": "#1462c9"}
WIN = 20


def load_events() -> list[dict]:
    names = R.load_names()
    out = []
    for f in sorted(glob.glob("data/stocks/daily_al/*.csv")):
        code = os.path.basename(f)[:6]
        kp = f"data/stocks/daily/{code}.csv"
        if not os.path.exists(kp) or code in R.excluded_codes(names):
            continue
        a = pd.read_csv(f, dtype={"date": str}).dropna(subset=["value_mw"]).sort_values("date").reset_index(drop=True)
        if len(a) < 300:
            continue
        d = pd.read_csv(kp)
        d["d8"] = d.date.str.replace("-", "")
        t = tiers_of(a.value_mw / 100)
        d["val"] = d.d8.map(dict(zip(a.date, a.value_mw / 100)))
        d["tier"] = d.d8.map(dict(zip(a.date, t)))
        d["chg"] = d.close / d.close.shift(1) - 1
        d["h240"] = d.high.shift(1).rolling(240).max()
        for w in (5, 10, 20):
            d[f"ma{w}"] = d.close.rolling(w).mean()
        m = (d.tier.isin(["역대", "4년", "1년"]) & (d.val >= 1000) & (d.chg >= 0.07) & (d.high < d.h240)
             & (d.close >= d.h240 * 0.75))
        last = -99
        for i in d.index[m]:
            if i - last <= WIN or i + WIN >= len(d) or i < 30:
                continue
            last = i
            out.append(dict(code=code, name=names.get(code, code), i=i, d=d))
    return out


def analyze(ev: dict) -> dict:
    d, i = ev["d"], ev["i"]
    H = d.h240[i]
    fut = d.iloc[i + 1:i + 1 + WIN]
    bo = fut.index[fut.close > H]
    touch = fut.index[fut.high >= H]
    outcome = "돌파" if len(bo) else ("터치만" if len(touch) else "실패")
    r = dict(code=ev["code"], name=ev["name"], date=d.date[i], tier=d.tier[i], val=d.val[i], chg=d.chg[i] * 100,
             left=(1 - d.close[i] / H) * 100, outcome=outcome,
             ma20_up=bool(d.ma20[i - 1] > d.ma20[i - 6]),            # 폭발 전날 20일선이 5일 전보다 높다(올라가는 중)
             above20=bool(d.close[i - 1] > d.ma20[i - 1]))           # 폭발 전날 종가가 20일선 위
    end = bo[0] if len(bo) else i + WIN  # 돌파 전날까지(실패는 20일 전체)를 '눌림 구간'으로 본다
    seg = d.loc[i + 1:end - 1] if end > i + 1 else d.loc[i + 1:i]
    lows = seg.low if len(seg) else pd.Series([d.close[i]])
    r["pull"] = (lows.min() / d.close[i] - 1) * 100            # 폭발일 종가 대비 가장 깊은 눌림
    r["held_low"] = bool(lows.min() >= d.low[i])
    r["held_body"] = bool(lows.min() >= (d.open[i] + d.close[i]) / 2)
    r["vol_dry"] = seg.volume.mean() / d.volume[i] if len(seg) else np.nan  # 눌림 구간 평균 거래량 ÷ 폭발일
    r["ma_touched"] = next((f"{w}일선" for w in (5, 10, 20) if len(seg) and (seg.low <= seg[f"ma{w}"]).any()), "안 닿음")
    if outcome == "돌파":
        b = bo[0]
        r["days"] = int(b - i)
        r["bo_chg"] = d.chg[b] * 100
        r["bo_gap"] = (d.open[b] / d.close[b - 1] - 1) * 100
        r["bo_vol"] = d.volume[b] / d.volume[i]
        r["r10"] = (d.close[min(b + 10, len(d) - 1)] / d.close[b] - 1) * 100
        r["hold10"] = bool(d.close[min(b + 10, len(d) - 1)] > H)
        r["shape"] = "직행" if r["days"] <= 3 else ("얕은 눌림" if r["held_low"] else "깊은 눌림")
    return r


def candles(ax, d: pd.DataFrame, i0: int, i1: int, H: float, burst: int, bo: int | None, title: str):
    seg = d.loc[i0:i1]
    x = np.arange(len(seg))
    up = (seg.close >= seg.open).values
    col = np.where(up, UP, DOWN)
    ax.vlines(x, seg.low, seg.high, color=col, lw=0.8)
    ax.bar(x, (seg.close - seg.open).abs().clip(lower=seg.close * 0.002), bottom=np.minimum(seg.open, seg.close), color=col, width=0.7)
    ax.plot(x, seg.ma5.values, color="#e0a500", lw=0.9)
    ax.plot(x, seg.ma20.values, color="#7c5cff", lw=0.9)
    ax.axhline(H, color=UP, ls="--", lw=0.9)
    ax.axvspan(burst - i0 - 0.5, burst - i0 + 0.5, color="#2f6fed", alpha=0.12, lw=0)
    if bo is not None:
        ax.annotate("돌파", (bo - i0, d.high[bo]), xytext=(0, 6), textcoords="offset points", ha="center", fontsize=7, color=UP)
    ax.set_title(title, fontsize=8, color=INK, loc="left")
    ax.set_xticks([]); ax.tick_params(labelsize=6, colors=MUTED)
    ax.ticklabel_format(axis="y", style="plain", useOffset=False)
    for s in ax.spines.values():
        s.set_visible(False)
    vax = ax.inset_axes([0, 0, 1, 0.18])
    vax.bar(x, seg.volume, color=col, width=0.7, alpha=0.45)
    vax.axis("off")
    lo, hi = seg.low.min(), max(seg.high.max(), H)
    ax.set_ylim(lo - (hi - lo) * 0.3, hi + (hi - lo) * 0.08)
    ax.set_yticks([t for t in ax.get_yticks() if lo <= t <= hi])  # 거래량 자리(아래 여백)에 가격 눈금이 안 찍히게


def path_matrix(events, rows, align: str, lo: int, hi: int) -> dict[str, np.ndarray]:
    """가격 ÷ 옛 고점, align='burst' 면 폭발일=0, 'bo' 면 돌파일=0."""
    mats = {}
    for ev, r in zip(events, rows):
        d, i = ev["d"], ev["i"]
        H = d.h240[i]
        z = i + r["days"] if align == "bo" else i
        if align == "bo" and r["outcome"] != "돌파":
            continue
        if z + lo < 0 or z + hi >= len(d):
            continue
        mats.setdefault(r["outcome"], []).append((d.close.iloc[z + lo:z + hi + 1].values / H - 1) * 100)
    return {k: np.array(v) for k, v in mats.items()}


def main():
    os.makedirs(OUT, exist_ok=True)
    events = load_events()
    rows = [analyze(e) for e in events]
    df = pd.DataFrame(rows)
    df.to_csv(f"{OUT}/summary.csv", index=False, encoding="utf-8-sig")
    print("사건", len(df)); print(df.outcome.value_counts().to_string())

    # 1) 폭발일 기준 평균 경로(결과별 중앙값 + 사분위 띠)
    lo, hi = -20, WIN
    mats = path_matrix(events, rows, "burst", lo, hi)
    fig, ax = plt.subplots(figsize=(9, 4.8))
    xs = np.arange(lo, hi + 1)
    for k in ("돌파", "터치만", "실패"):
        if k not in mats:
            continue
        m = mats[k]
        ax.fill_between(xs, np.percentile(m, 25, axis=0), np.percentile(m, 75, axis=0), color=OUTCOME_COLOR[k], alpha=0.12, lw=0)
        ax.plot(xs, np.median(m, axis=0), color=OUTCOME_COLOR[k], lw=2, label=f"{k} ({len(m)}건)")
    ax.axhline(0, color=INK, lw=0.8, ls="--"); ax.axvline(0, color=MUTED, lw=0.8)
    ax.text(lo + 0.3, 0.6, "옛 고점(폭발일 기준 240일 고점)", fontsize=8, color=INK)
    ax.set_xlabel("폭발일로부터 거래일"); ax.set_ylabel("옛 고점 대비 종가 (%)")
    ax.set_title("거래대금 폭발 전후 종가 경로 — 결과별 중앙값(띠 = 가운데 50%)", loc="left", fontsize=11)
    ax.grid(axis="y", color=GRID, lw=0.6); ax.legend(frameon=False, fontsize=9)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout(); fig.savefig(f"{OUT}/01_path_by_outcome.png", dpi=150); plt.close(fig)

    # 2) 돌파일 기준 경로(돌파 종목만, 모양별)
    succ = [(e, r) for e, r in zip(events, rows) if r["outcome"] == "돌파"]
    fig, ax = plt.subplots(figsize=(9, 4.8))
    xs = np.arange(-15, 21)
    shape_color = {"직행": "#d0332f", "얕은 눌림": "#e0a500", "깊은 눌림": "#7c5cff"}
    for sh, colr in shape_color.items():
        ms = [(e["d"].close.iloc[e["i"] + r["days"] - 15:e["i"] + r["days"] + 21].values / e["d"].h240[e["i"]] - 1) * 100
              for e, r in succ if r["shape"] == sh and e["i"] + r["days"] + 20 < len(e["d"]) and e["i"] + r["days"] - 15 >= 0]
        if not ms:
            continue
        m = np.array(ms)
        ax.fill_between(xs, np.percentile(m, 25, axis=0), np.percentile(m, 75, axis=0), color=colr, alpha=0.10, lw=0)
        ax.plot(xs, np.median(m, axis=0), color=colr, lw=2, label=f"{sh} ({len(m)}건)")
    ax.axhline(0, color=INK, lw=0.8, ls="--"); ax.axvline(0, color=MUTED, lw=0.8)
    ax.set_xlabel("돌파일로부터 거래일"); ax.set_ylabel("옛 고점 대비 종가 (%)")
    ax.set_title("돌파 종목 — 돌파일 전후 종가 경로(모양별 중앙값)", loc="left", fontsize=11)
    ax.grid(axis="y", color=GRID, lw=0.6); ax.legend(frameon=False, fontsize=9)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout(); fig.savefig(f"{OUT}/02_path_after_breakout.png", dpi=150); plt.close(fig)

    # 3) 모양별 실제 일봉 예시(최근 순 12개씩)
    for sh in ("직행", "얕은 눌림", "깊은 눌림"):
        ex = sorted([(e, r) for e, r in succ if r["shape"] == sh], key=lambda x: x[1]["date"])[-12:]
        if not ex:
            continue
        fig, axes = plt.subplots(3, 4, figsize=(14, 8.4))
        for ax, (e, r) in zip(axes.flat, ex):
            b = e["i"] + r["days"]
            candles(ax, e["d"], e["i"] - 25, min(b + 15, len(e["d"]) - 1), e["d"].h240[e["i"]], e["i"], b,
                    f"{r['name']} {r['date']} · {r['days']}일 만에 돌파 · 눌림 {r['pull']:.1f}%")
        for ax in axes.flat[len(ex):]:
            ax.axis("off")
        fig.suptitle(f"돌파 종목 일봉 — {sh}  (파란 띠 = 폭발일, 빨간 점선 = 옛 고점, 노랑 5일선·보라 20일선)", x=0.01, ha="left", fontsize=11)
        fig.tight_layout(); fig.savefig(f"{OUT}/03_examples_{sh.replace(' ', '')}.png", dpi=130); plt.close(fig)

    # 4) 실패 예시(비교용)
    ex = sorted([(e, r) for e, r in zip(events, rows) if r["outcome"] == "실패"], key=lambda x: x[1]["date"])[-12:]
    fig, axes = plt.subplots(3, 4, figsize=(14, 8.4))
    for ax, (e, r) in zip(axes.flat, ex):
        candles(ax, e["d"], e["i"] - 25, e["i"] + WIN, e["d"].h240[e["i"]], e["i"], None,
                f"{r['name']} {r['date']} · 고점까지 {r['left']:.1f}% · 눌림 {r['pull']:.1f}%")
    fig.suptitle("실패 종목 일봉(20일 안에 옛 고점 못 닿음) — 비교용", x=0.01, ha="left", fontsize=11)
    fig.tight_layout(); fig.savefig(f"{OUT}/04_examples_fail.png", dpi=130); plt.close(fig)

    # 통계
    pd.set_option("display.width", 220)
    g = df.groupby("outcome").agg(건수=("code", "size"), 고점까지=("left", "median"), 폭발일등락=("chg", "median"),
                                   눌림=("pull", "median"), 저가지킴=("held_low", "mean"), 몸통절반지킴=("held_body", "mean"),
                                   거래량감소=("vol_dry", "median"), 전날20선위=("above20", "mean"), 이십일선상승=("ma20_up", "mean"))
    print(g.round(2).to_string())
    s = df[df.outcome == "돌파"]
    print(s.groupby("shape").agg(건수=("code", "size"), 걸린날=("days", "median"), 눌림=("pull", "median"), 거래량감소=("vol_dry", "median"),
                                 돌파일등락=("bo_chg", "median"), 돌파일갭=("bo_gap", "median"), 돌파일거래량배=("bo_vol", "median"),
                                 돌파후10일=("r10", "median"), 열흘뒤고점위=("hold10", "mean")).round(2).to_string())
    print(s.ma_touched.value_counts().to_string())
    print(df.groupby(pd.cut(df.left, [0, 5, 10, 15, 25])).outcome.value_counts(normalize=True).unstack().round(2).to_string())
    print(df.groupby(["ma20_up", "above20"]).outcome.value_counts(normalize=True).unstack().round(2).to_string())
    print(df.groupby(["ma20_up", "above20"]).size().to_string())


if __name__ == "__main__":
    main()
