"""다우 사다리 차트 — 이탈선(큰 눈금) / 저점 다지기 / 관문 사다리(작은 눈금)를 한 장에.

    python dow_ladder_chart.py            # 000660, 005930
    python dow_ladder_chart.py --demo
"""
import sys, numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.family"] = "Malgun Gothic"; plt.rcParams["axes.unicode_minus"] = False
sys.path.insert(0, ".")
from dow_signal import load

def load_bars(code, tf):
    """tf='D'면 일봉, '30T'/'60T'면 1분봉을 리샘플한 분봉."""
    if tf == "D":
        return load(code)
    m = pd.read_csv(f"data/stocks/minute/{code}.csv", parse_dates=["date"])
    g = m.set_index("date").resample(tf).agg(open=("open", "first"), high=("high", "max"),
                                             low=("low", "min"), close=("close", "last"),
                                             volume=("volume", "sum")).dropna()
    return g.reset_index()


def atr_pct(df, n=20):
    tr = np.maximum(df.high - df.low, np.maximum((df.high - df.close.shift()).abs(),
                                                 (df.low - df.close.shift()).abs()))
    return float((tr.rolling(n).mean() / df.close * 100).iloc[-1])


def swings_hl(df, pct):
    """고가/저가 기준 스윙. 종가만 보면 일중 진짜 고·저점을 놓친다(변동성 큰 종목에서 특히).
    반환: (확정 고점들, 확정 저점들) — 마지막 미확정 극점은 제외."""
    hi, lo = df.high.values, df.low.values
    highs, lows, ext, dirn = [], [], hi[0], 1
    for i in range(1, len(hi)):
        if dirn > 0:
            if hi[i] > ext: ext = hi[i]
            elif (lo[i] / ext - 1) * 100 <= -pct: highs.append(ext); ext, dirn = lo[i], -1
        else:
            if lo[i] < ext: ext = lo[i]
            elif (hi[i] / ext - 1) * 100 >= pct: lows.append(ext); ext, dirn = hi[i], 1
    return highs, lows


def swings(close, pct):
    """확정된 (고점들, 저점들). 마지막 미확정 극점은 제외."""
    highs, lows, ext, dirn = [], [], close[0], 1
    for c in close[1:]:
        if dirn > 0:
            if c > ext: ext = c
            elif (c / ext - 1) * 100 <= -pct: highs.append(ext); ext, dirn = c, -1
        else:
            if c < ext: ext = c
            elif (c / ext - 1) * 100 >= pct: lows.append(ext); ext, dirn = c, 1
    return highs, lows

def ladder(df, gates=(5, 8, 12), exit_pct=20, base_pct=8, top_n=4):
    """관문 사다리 / 이탈선 / 최근 저점열."""
    c = df.close.values; cur = c[-1]
    # ponytail: ATR이 10%인 종목에서 3~4% 눈금은 노이즈 저점을 잡는다. 눈금은 ATR 이상으로.
    raw = sorted({h for p in gates for h in swings(c, p)[0] if h > cur})
    gate = []                                  # 2% 이내로 붙은 관문은 하나로 합친다
    for g in raw:
        if not gate or g / gate[-1] - 1 > 0.02:
            gate.append(g)
    gate = gate[:top_n]
    _, lows20 = swings(c, exit_pct)
    _, lowsB = swings(c, base_pct)
    return cur, gate, (lows20[-1] if lows20 else None), lowsB[-3:]

def draw(ax, code, name, tf="D", months=4, bars=200, scales=None):
    full = load_bars(code, tf)
    df = (full[full.date >= full.date.max() - pd.DateOffset(months=months)] if tf == "D"
          else full.tail(bars)).reset_index(drop=True)
    df = df.dropna(subset=["open", "high", "low", "close"])
    # ponytail: ATR 자동 산출은 일봉에서 이탈선이 -96%까지 밀려 못 쓴다(확정 저점이 몇 년 전 것).
    #           타임프레임별 고정 눈금이 안전하다. 종목 성격이 바뀌면 여기만 손보면 된다.
    if scales is None:
        scales = (dict(gates=(5, 8, 12), exit_pct=20, base_pct=8) if tf == "D"
                  else dict(gates=(1.5, 2.5, 4), exit_pct=8, base_pct=2.5))
    cur, gates, exit_line, base = ladder(full, **scales)
    # 봉차트 (한국식: 상승 빨강 / 하락 파랑)
    step = (matplotlib.dates.date2num(df.date.iloc[-1]) - matplotlib.dates.date2num(df.date.iloc[0])) / max(len(df), 1)
    w = step * 0.62
    for r in df.itertuples():
        up = r.close >= r.open
        col = "#d92b2b" if up else "#1f6fd0"
        ax.vlines(r.date, r.low, r.high, color=col, lw=.9, zorder=3)
        ax.add_patch(plt.Rectangle((matplotlib.dates.date2num(r.date) - w/2, min(r.open, r.close)),
                                   w, max(abs(r.close - r.open), 1e-9), facecolor=col,
                                   edgecolor=col, lw=.6, zorder=4))
    x0, x1 = df.date.iloc[0], df.date.iloc[-1]

    for g in gates:                                   # 관문 사다리
        ax.axhline(g, color="#e67e22", ls="--", lw=1.1, alpha=.9, zorder=6)
        ax.text(x1, g, f"  {g/10000:,.0f}만 ({(g/cur-1)*100:+.0f}%)", va="center",
                fontsize=9, color="#d35400", fontweight="bold")
    if exit_line:                                     # 이탈선
        ax.axhline(exit_line, color="#8e44ad", ls="-", lw=2, zorder=6)
        ax.text(x0, exit_line, f" 이탈선 {exit_line/10000:,.0f}만 ({(exit_line/cur-1)*100:+.0f}%)",
                va="bottom", fontsize=10, color="#8e44ad", fontweight="bold")
    for i, lv in enumerate(base):                     # 저점 다지기
        d = df.date[df.close.sub(lv).abs().idxmin()] if (df.close.sub(lv).abs().min() < lv*0.004) else None
        if d is None: continue
        ax.plot(d, lv, "^", color="#1f7a3f", ms=13, zorder=8)
        ax.annotate(f"{lv/10000:,.0f}만", (d, lv), xytext=(0, -20), textcoords="offset points",
                    ha="center", fontsize=9.5, color="#1f7a3f", fontweight="bold")
    rising = all(b < a for b, a in zip(base, base[1:]))
    ax.axhline(cur, color="#0b7285", lw=1.2, alpha=.75, zorder=6)
    ax.plot(x1, cur, "o", color="#0b7285", ms=13, zorder=8)
    tflabel = {"D": "일봉", "30min": "30분봉", "60min": "60분봉"}.get(tf, tf)
    ax.set_title("%s [%s]  %s   저점 %s   %s" % (name, tflabel, f"{cur:,.0f}", ' → '.join(f'{b/10000:,.1f}만' for b in base), '다지기 진행(저점 상승)' if rising else '다지기 미완(저점 하락)'), fontsize=11.5, fontweight="bold", pad=8, loc="left")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v/10000:,.0f}만")
    ax.grid(alpha=.22); [ax.spines[s].set_visible(False) for s in ("top", "right")]
    ax.set_xlim(x0, x1 + pd.Timedelta(days=int((x1-x0).days*0.13)))
    return cur, gates, exit_line, rising

def bar(ax, cur, gates, exit_line, name):
    """이탈선 ↔ 관문 사이 현재 위치 바."""
    hi = gates[-1] if gates else cur * 1.2
    ax.barh(0, hi - exit_line, left=exit_line, height=.34, color="#ecf0f1")
    ax.barh(0, cur - exit_line, left=exit_line, height=.34, color="#aed6f1")
    ax.plot(cur, 0, "o", color="#2980b9", ms=15, zorder=5)
    ax.text(cur, .3, f"{name} {cur/10000:,.0f}만", ha="center", fontsize=10,
            fontweight="bold", color="#2980b9")
    ax.plot(exit_line, 0, "|", color="#8e44ad", ms=26, mew=3)
    ax.text(exit_line, -.42, f"이탈 {exit_line/10000:,.0f}만", ha="center", fontsize=9, color="#8e44ad")
    for g in gates:
        ax.plot(g, 0, "|", color="#e67e22", ms=22, mew=2.5)
        ax.text(g, -.42, f"{g/10000:,.0f}만", ha="center", fontsize=9, color="#d35400")
    ax.set_ylim(-.75, .62); ax.axis("off")

def demo():
    c = np.array([100, 120, 90, 110, 95, 130, 100, 115, 105, 118], float)
    h, l = swings(c, 10)
    assert h and l, (h, l)
    assert max(h) <= c.max() and min(l) >= c.min()
    print("demo ok:", h, l)

def main():
    codes = [("000660", "SK하이닉스"), ("005930", "삼성전자")]
    fig = plt.figure(figsize=(19, 13)); fig.patch.set_facecolor("white")
    gs = fig.add_gridspec(4, 2, height_ratios=[3, .7, 3, .7], hspace=.45, wspace=.13)
    for i, (code, name) in enumerate(codes):
        cur, gates, ex, _ = draw(fig.add_subplot(gs[i*2, 0]), code, name, "D", months=4)
        bar(fig.add_subplot(gs[i*2+1, 0]), cur, gates, ex, name + " 일봉")
        cur2, gates2, ex2, _ = draw(fig.add_subplot(gs[i*2, 1]), code, name, "30min", bars=140)
        bar(fig.add_subplot(gs[i*2+1, 1]), cur2, gates2, ex2, name + " 30분봉")
    fig.suptitle("다우 사다리 — 왼쪽 일봉 / 오른쪽 30분봉 | 보라=이탈선  주황=관문  초록=확정 저점 (눈금은 각 봉의 ATR에 맞춤)",
                 fontsize=14, fontweight="bold", y=.955)
    plt.savefig("dow_ladder.png", dpi=130, bbox_inches="tight", facecolor="white")
    print("saved dow_ladder.png")

if __name__ == "__main__":
    demo() if "--demo" in sys.argv else main()
