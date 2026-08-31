"""진입/청산 튜닝 말고 다른 축에서 엣지를 찾는다.

지금까지 700조합 넘게 진입·손절만 돌렸지만 기대값은 0.4~0.5%에서 안 움직였다.
파라미터가 아니라 축이 잘못됐다는 뜻이다. 여기서 보는 네 가지는 전부
"언제 거래하지 말아야 하나"와 "언제까지 들고 있나"에 관한 것이다.

H1 시장 국면   그날 시장이 좋은가. 유니버스 전체 일간 등락률의 중앙값·상승비율로 잰다.
H2 후보 밀집   그날 후보가 몇 개인가. 여러 개 = 시장이 뜨겁다는 신호일 수 있다.
H3 오버나이트  15:20 청산 대신 익일 시가까지 들고 가면.
H4 오전 구조   09:00~10:00 안에서 신고가를 몇 번 갱신했나, 거래량이 줄며 눌렸나.

전략은 앞서 최적으로 나온 것으로 고정: 사다리 -1%/돌파+0.3, 당일고점 -5% 트레일.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pullback_ladder_backtest import ENTRY_MIN, EXIT_MIN, candidates
from exit_sweep import simulate

DAILY_DIR = "data/stocks/daily"
MINUTE_DIR = "data/stocks/minute"
CAPITAL = 60_000_000
PLAN = {"market": 0.0, "dips": [(0.5, 1.0)], "breakout": 0.5, "bo_buf": 0.3}
TRAIL = 5.0


def market_breadth() -> pd.DataFrame:
    """유니버스 전체의 일간 등락률로 만든 시장 국면 지표(전일까지 정보만 쓰는 열도 함께)."""
    rets = {}
    files = [f for f in os.listdir(DAILY_DIR) if f.endswith(".csv")]
    for i, f in enumerate(files, 1):
        print(f"\r시장지표 [{i}/{len(files)}]", end="", file=sys.stderr)
        d = pd.read_csv(os.path.join(DAILY_DIR, f), index_col=0, parse_dates=True).sort_index()
        rets[f[:-4]] = d["close"].pct_change() * 100
    print(file=sys.stderr)
    R = pd.DataFrame(rets)
    mk = pd.DataFrame({
        "mkt_ret": R.median(axis=1),
        "mkt_up": (R > 0).mean(axis=1) * 100,
    })
    mk["mkt_ret_5d"] = mk["mkt_ret"].rolling(5).mean()
    # 전일까지의 국면 — 아침에 알 수 있는 값
    mk["prev_5d"] = mk["mkt_ret_5d"].shift(1)
    mk["prev_ret"] = mk["mkt_ret"].shift(1)
    return mk


def morning_shape(bars: pd.DataFrame) -> dict:
    """09:00~10:00 구조. 전부 10:00에 확정된다."""
    mins = bars.index.hour * 60 + bars.index.minute
    am = bars[mins < ENTRY_MIN]
    if len(am) < 30:
        return {}
    h = am["high"].to_numpy(); v = am["volume"].to_numpy().astype(float)
    peak = -np.inf; n_new = 0
    for x in h:
        if x > peak:
            n_new += 1
            peak = x
    n = len(am)
    return {
        "n_newhigh": n_new,                                   # 신고가 갱신 횟수
        "vol_fade": v[-20:].sum() / max(v[:20].sum(), 1),      # 후반20분/초반20분 거래량
        "late_share": v[n // 2:].sum() / max(v.sum(), 1),      # 후반 거래량 비중
    }


def build() -> pd.DataFrame:
    cand = candidates()
    mk = market_breadth()
    rows = []
    for i, (code, g) in enumerate(cand.groupby("stock_code"), 1):
        print(f"\r[{i}/{cand['stock_code'].nunique()}] {code}", end="", file=sys.stderr)
        mpath = os.path.join(MINUTE_DIR, f"{code}.csv")
        dpath = os.path.join(DAILY_DIR, f"{code}.csv")
        if not (os.path.exists(mpath) and os.path.exists(dpath)):
            continue
        daily = pd.read_csv(dpath, index_col=0, parse_dates=True).sort_index()
        nxt_open = daily["open"].shift(-1)
        minute = pd.read_csv(mpath, index_col=0, parse_dates=True).sort_index()
        want = set(g["date"])
        for date, bars in minute.groupby(minute.index.normalize()):
            if date not in want:
                continue
            r = simulate(bars, PLAN, TRAIL, None, None, None, None)
            if r is None:
                continue
            shape = morning_shape(bars)
            mins = bars.index.hour * 60 + bars.index.minute
            seg = bars[(mins >= ENTRY_MIN) & (mins <= EXIT_MIN)]
            close = float(seg["close"].iloc[-1])
            nx = nxt_open.get(date, np.nan)
            rows.append({
                "date": date, "code": code,
                "ret": r,
                "overnight": (nx / close - 1) * 100 if pd.notna(nx) else np.nan,
                **shape,
                **{k: mk[k].get(date, np.nan) for k in ["mkt_ret", "mkt_up", "prev_5d", "prev_ret"]},
            })
    print(file=sys.stderr)
    df = pd.DataFrame(rows)
    df["n_same_day"] = df.groupby("date")["code"].transform("size")
    return df


def slice_table(df: pd.DataFrame, col: str, label: str, bins: int = 4) -> None:
    s = df[col].dropna()
    if s.nunique() < bins:
        q = df[col]
    else:
        q = pd.qcut(df[col], bins, duplicates="drop")
    print(f"\n{label}")
    print(f"{'구간':>22}{'n':>6}{'승률':>8}{'기대값':>9}{'월환산(6천만)':>14}")
    for k, gg in df.groupby(q, observed=True):
        rng = f"{k.left:.2f} ~ {k.right:.2f}" if hasattr(k, "left") else str(k)
        per_month = gg["ret"].sum() / df["date"].dt.to_period("M").nunique() * CAPITAL / 100 / 1e4
        print(f"{rng:>22}{len(gg):>6}{(gg['ret'] > 0).mean()*100:>7.1f}%"
              f"{gg['ret'].mean():>8.2f}%{per_month:>12,.0f}만")


def main() -> None:
    df = build()
    n_month = df["date"].dt.to_period("M").nunique()
    base = df["ret"].mean()
    print("=" * 92)
    print(f"엣지 탐색 — 후보 {len(df)}건 / {df['date'].nunique()}일 / {n_month}개월")
    print(f"기준 전략(사다리 -1/돌파, 트레일 -5%) 기대값 {base:.2f}%/건")
    print("=" * 92)

    print("\n" + "-" * 92)
    print("[H1] 시장 국면 — 그날/전날 시장이 좋으면 다른가")
    print("-" * 92)
    slice_table(df, "mkt_ret", "당일 유니버스 등락률 중앙값 (사후 — 참고용)")
    slice_table(df, "prev_ret", "전일 시장 등락률 (아침에 알 수 있음)")
    slice_table(df, "prev_5d", "전일까지 5일 시장 추세 (아침에 알 수 있음)")

    print("\n" + "-" * 92)
    print("[H2] 후보 밀집 — 그날 후보 수")
    print("-" * 92)
    slice_table(df, "n_same_day", "같은 날 후보 개수")

    print("\n" + "-" * 92)
    print("[H3] 오버나이트 — 15:20 청산 대신 익일 시가까지")
    print("-" * 92)
    ov = df["overnight"].dropna()
    print(f"익일 시가 갭: 중앙 {ov.median():+.2f}%  평균 {ov.mean():+.2f}%  "
          f"양(+) 비율 {(ov > 0).mean()*100:.0f}%")
    both = df.dropna(subset=["overnight"])
    print(f"당일청산 기대값 {both['ret'].mean():.2f}%  →  "
          f"익일시가 청산 기대값 {(both['ret'] + both['overnight']).mean():.2f}%")
    win = both[both["ret"] > 0]; lose = both[both["ret"] <= 0]
    print(f"  이긴 날만 넘겼다면 {win['overnight'].mean():+.2f}%p  "
          f"진 날만 넘겼다면 {lose['overnight'].mean():+.2f}%p")

    print("\n" + "-" * 92)
    print("[H4] 오전 구조 — 09:00~10:00 안에서 어떻게 움직였나")
    print("-" * 92)
    slice_table(df, "n_newhigh", "09~10시 신고가 갱신 횟수")
    slice_table(df, "vol_fade", "거래량 후반20분/초반20분")
    slice_table(df, "late_share", "후반 30분 거래량 비중")

    df.to_csv("results/edge_hunt.csv", index=False, encoding="utf-8-sig")
    print("\n원본: results/edge_hunt.csv")


if __name__ == "__main__":
    main()
