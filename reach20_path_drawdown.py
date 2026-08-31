"""+20% 도달 경로(09:00 -> 최초 +20% 터치)의 조정 깊이 통계.

모집단은 reach20_features.csv(10:00 장중누적대금 top20)에서 당일 +20%를 찍은 케이스.
경로를 러닝 고점 기준으로 걸으면서 조정 에피소드를 하나씩 잡아낸다.

조정 에피소드 정의: 러닝 고점에서 EPISODE_MIN 이상 밀렸다가 그 고점을 다시 넘어서면
1회로 센다. 마지막에 고점 갱신 없이 +20%를 찍으면 그 미완성 구간도 포함한다.

낙폭은 09:00 첫 봉의 저가를 제외하고 잰다(그 1분 안의 왕복은 실제 손절이 아니다).
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SUF = "" if os.environ.get("SCAN_CUTOFF", "1000") == "1000" else f'_{os.environ["SCAN_CUTOFF"]}'
FEATURES_CSV = f"results/reach20_features{SUF}.csv"
MINUTE_DIR = "data/stocks/minute"
DAILY_DIR = "data/stocks/daily"
OUT = f"results/reach20_path_drawdown{SUF}.csv"  # --top!=20이면 접미사가 붙는다
TOP_N = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--top=")), 20))
EPISODE_MIN = 1.0  # 이보다 얕은 흔들림은 조정으로 세지 않는다(1분봉 노이즈)
TRAILING_STOPS = (2, 3, 4, 5, 7, 10)


def walk_path(bars: pd.DataFrame, pc: float) -> dict | None:
    """09:00 ~ 최초 +20% 터치까지 걸으면서 조정 에피소드를 수집."""
    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()
    hit = np.flatnonzero(high >= pc * 1.20)
    if hit.size == 0:
        return None
    end = int(hit[0])
    path_high, path_low = high[: end + 1], low[: end + 1]

    episodes = []  # (깊이%, 시작고점의 전일比 수준%, 저점 인덱스)
    # 신고가 시점의 저점을 그 봉의 저가로 두면 1분봉 자체 range가 가짜 조정으로 잡힌다.
    # 조정은 "고점 이후 봉들"의 저가로만 채운다.
    peak = path_high[0]
    trough = peak
    trough_i = 0
    for i in range(1, len(path_high)):
        if path_low[i] < trough:
            trough = path_low[i]
            trough_i = i
        if path_high[i] > peak:
            depth = (peak - trough) / peak * 100
            if depth >= EPISODE_MIN:
                episodes.append((depth, (peak / pc - 1) * 100, trough_i))
            peak = path_high[i]
            trough = peak
            trough_i = i
    # 고점 갱신 없이 +20%로 직행한 마지막 구간
    depth = (peak - trough) / peak * 100
    if depth >= EPISODE_MIN:
        episodes.append((depth, (peak / pc - 1) * 100, trough_i))

    # 러닝 고점 대비 최대 낙폭 — 트레일링 손절 사이징에 쓰는 값.
    # 09:00 첫 봉의 저가는 빼고 잰다. 동시호가 직후 1분은 고가~저가 폭이 커서
    # 실제로 겪지 않은 손절을 만들어낸다(그 1분 안의 왕복일 뿐). 고가는 그대로 살려
    # 러닝 고점에는 반영한다.
    running_peak = np.maximum.accumulate(path_high)
    max_dd = (float(((running_peak[1:] - path_low[1:]) / running_peak[1:]).max()) * 100
              if len(path_low) > 1 else 0.0)

    depths = [e[0] for e in episodes]
    zone_lo = [e[0] for e in episodes if e[1] < 10]   # 전일비 +10% 미만 구간의 조정
    zone_hi = [e[0] for e in episodes if e[1] >= 10]  # +10~20% 구간의 조정
    return {
        "t20_time": bars.index[end].strftime("%H:%M"),
        "minutes_to_20": int((bars.index[end] - bars.index[0]).total_seconds() // 60),
        "bars_to_20": end + 1,
        "max_dd_pct": max_dd,
        "n_episodes": len(depths),
        "n_ep_ge2": sum(d >= 2 for d in depths),
        "n_ep_ge3": sum(d >= 3 for d in depths),
        "n_ep_ge5": sum(d >= 5 for d in depths),
        "deepest_ep_pct": max(depths) if depths else 0.0,
        "median_ep_pct": float(np.median(depths)) if depths else 0.0,
        "deepest_ep_level_pct": max(episodes)[1] if episodes else np.nan,
        "dd_below_10_pct": max(zone_lo) if zone_lo else 0.0,
        "dd_above_10_pct": max(zone_hi) if zone_hi else 0.0,
        "has_ep_above_10": bool(zone_hi),
    }


def build() -> pd.DataFrame:
    feat = pd.read_csv(FEATURES_CSV, parse_dates=["date"], dtype={"stock_code": str})
    feat = feat[feat["rank_10am"] <= TOP_N]
    print(f"top20 종목-일자 {len(feat):,}건에서 경로 추적", file=sys.stderr)

    rows = []
    for i, (code, g) in enumerate(feat.groupby("stock_code"), 1):
        print(f"\r[{i}/{feat['stock_code'].nunique()}] {code}", end="", file=sys.stderr)
        daily = pd.read_csv(os.path.join(DAILY_DIR, f"{code}.csv"), index_col=0, parse_dates=True).sort_index()
        prev_close = daily["close"].shift(1)
        minute = pd.read_csv(os.path.join(MINUTE_DIR, f"{code}.csv"), index_col=0, parse_dates=True).sort_index()

        wanted = dict(zip(g["date"], g["name"]))
        for date, bars in minute.groupby(minute.index.normalize()):
            if date not in wanted or date not in prev_close.index:
                continue
            pc = prev_close.loc[date]
            if pd.isna(pc) or pc <= 0:
                continue
            res = walk_path(bars, float(pc))
            if res is None:
                continue
            rows.append({"date": date, "stock_code": code, "name": wanted[date], **res})
    print(file=sys.stderr)
    return pd.DataFrame(rows)


def report(df: pd.DataFrame) -> None:
    qs = (0.10, 0.25, 0.50, 0.75, 0.90)

    def line(label: str, s: pd.Series, unit: str = "%") -> None:
        s = s.dropna()
        print(f"{label:>28}" + "".join(f"{s.quantile(q):>9.1f}{unit}" for q in qs)
              + f"{s.mean():>9.1f}{unit}")

    print("=" * 96)
    print(f"대금 상위 {TOP_N} 중 +20% 달성 종목의 경로 조정 깊이 (09:00 ~ 최초 +20% 터치)")
    print("=" * 96)
    print(f"기간   : {df['date'].min().date()} ~ {df['date'].max().date()} ({df['date'].nunique()}일)")
    print(f"케이스 : {len(df):,}건 ({df['stock_code'].nunique()}종목)")
    early = (df["t20_time"] <= "10:00").sum()
    print(f"         10시 이전 도달 {early}건 ({early/len(df)*100:.0f}%), 이후 {len(df)-early}건")

    print("\n" + "-" * 96)
    print("[1] 조정 깊이 분포")
    print("-" * 96)
    print(f"{'':>28}{'10%':>10}{'25%':>10}{'중앙':>10}{'75%':>10}{'90%':>10}{'평균':>10}")
    line("경로 최대낙폭(러닝고점比)", df["max_dd_pct"])
    line("가장 깊은 조정 1회", df["deepest_ep_pct"])
    line("조정들의 중앙값(케이스별)", df["median_ep_pct"])
    line("전일比 +10% 미만 구간 최대", df["dd_below_10_pct"])
    line("전일比 +10~20% 구간 최대", df["dd_above_10_pct"])

    print("\n" + "-" * 96)
    print("[2] 조정 횟수 (1% 이상을 1회로 셈)")
    print("-" * 96)
    for col, label in [("n_episodes", "1% 이상"), ("n_ep_ge2", "2% 이상"),
                       ("n_ep_ge3", "3% 이상"), ("n_ep_ge5", "5% 이상")]:
        c = df[col]
        print(f"{label:>10} 조정 : 중앙 {c.median():.0f}회  평균 {c.mean():4.1f}회  "
              f"0회 {(c == 0).mean()*100:4.1f}%  1회 {(c == 1).mean()*100:4.1f}%  "
              f"2회 {(c == 2).mean()*100:4.1f}%  3회+ {(c >= 3).mean()*100:4.1f}%")
    print(f"\n+10% 넘긴 뒤에도 1% 이상 조정을 겪은 비율: {df['has_ep_above_10'].mean()*100:.1f}%")
    print(f"도달 소요시간: 중앙 {df['minutes_to_20'].median():.0f}분  "
          f"(25% {df['minutes_to_20'].quantile(.25):.0f}분, 75% {df['minutes_to_20'].quantile(.75):.0f}분)")

    print("\n" + "-" * 96)
    print("[3] 트레일링 손절을 걸었다면 +20% 도달 전에 털렸을 비율")
    print("-" * 96)
    print("  (러닝 고점 대비 -X%에서 손절, 09:00부터 보유 가정 — 손절 사이징 근거)")
    for stop in TRAILING_STOPS:
        out = (df["max_dd_pct"] > stop).mean() * 100
        print(f"  트레일링 -{stop:>2}%  : {out:5.1f}% 이탈  ->  {100-out:5.1f}% 생존")

    print("\n" + "-" * 96)
    print("[4] 가장 깊은 조정이 발생한 가격대 (전일比)")
    print("-" * 96)
    lvl = pd.cut(df["deepest_ep_level_pct"], [-100, 0, 3, 6, 10, 15, 20, 100], right=False)
    for b, g in df.groupby(lvl, observed=True):
        rng = f"{b.left:g}~{b.right:g}%" if b.right < 100 else f"{b.left:g}%+"
        print(f"{rng:>12}  n={len(g):>4} ({len(g)/len(df)*100:4.1f}%)  "
              f"그때 조정 깊이 중앙 {g['deepest_ep_pct'].median():.1f}%")

    print("\n" + "-" * 96)
    print("[5] 분기별 안정성 (경로 최대낙폭)")
    print("-" * 96)
    q = df["date"].dt.to_period("Q")
    print(f"{'분기':>9}{'n':>6}{'중앙':>9}{'75%':>9}{'90%':>9}{'-4%이탈':>10}{'-7%이탈':>10}")
    for p, g in df.groupby(q, observed=True):
        print(f"{str(p):>9}{len(g):>6}{g['max_dd_pct'].median():>8.1f}%"
              f"{g['max_dd_pct'].quantile(.75):>8.1f}%{g['max_dd_pct'].quantile(.90):>8.1f}%"
              f"{(g['max_dd_pct']>4).mean()*100:>9.1f}%{(g['max_dd_pct']>7).mean()*100:>9.1f}%")


def demo() -> None:
    """에피소드 검출·최대낙폭 자체검증."""
    idx = pd.date_range("2026-01-02 09:00", periods=7, freq="1min")
    # 전일종가 100: 105고점 -> 101저점(3.81% 조정) -> 신고가 -> 118저점 없이 121터치
    bars = pd.DataFrame(
        {
            "open": [103, 104, 102, 106, 110, 115, 119],
            "high": [105, 105, 103, 108, 112, 117, 121],
            "low": [102, 101, 101, 105, 109, 114, 118],
            "close": [104, 102, 103, 107, 111, 116, 120],
        },
        index=idx,
    )
    r = walk_path(bars, 100.0)
    assert r is not None and r["bars_to_20"] == 7, r
    assert r["n_episodes"] == 1, r["n_episodes"]
    assert abs(r["deepest_ep_pct"] - (105 - 101) / 105 * 100) < 1e-9, r["deepest_ep_pct"]
    assert abs(r["max_dd_pct"] - (105 - 101) / 105 * 100) < 1e-9, r["max_dd_pct"]
    # 09:00 첫 봉 저가는 낙폭에서 빠진다 — 첫 봉을 깊게 파도 결과가 변하면 안 된다
    deep = bars.copy()
    deep.iloc[0, deep.columns.get_loc("low")] = 80
    r2 = walk_path(deep, 100.0)
    assert abs(r2["max_dd_pct"] - r["max_dd_pct"]) < 1e-9, r2["max_dd_pct"]
    assert r["dd_above_10_pct"] == 0.0 and r["dd_below_10_pct"] > 0
    assert walk_path(bars, 1000.0) is None  # +20% 미달이면 경로 없음
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()
    if TOP_N != 20:
        OUT = OUT.replace(".csv", f"_top{TOP_N}.csv")
    if "--reuse" in sys.argv and os.path.exists(OUT):
        df = pd.read_csv(OUT, parse_dates=["date"], dtype={"stock_code": str})
    else:
        df = build()
        df.to_csv(OUT, index=False, encoding="utf-8-sig")
    report(df)
    print(f"\n원본: {OUT}")
