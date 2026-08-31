"""대금 상위 20 종목의 +20% 도달 조건 탐색 (10:00 시점 의사결정 기준).

기존 분석들과 다른 점 두 가지:
  1) 모집단이 "+10% 도달 이벤트"가 아니라 top20 종목-일자 전체다.
  2) top20을 09:00~10:00 *장중 누적 거래대금*으로 매긴다. 종일 거래대금으로 매기면
     +20% 급등 자체가 거래대금을 밀어올려 순위에 결과가 새어든다(룩어헤드).

모든 피처는 10:00까지의 정보로만 계산하고, 타깃은 10:00 이후 고가가 전일종가 대비
+20%에 닿는지다. 10:00 전에 이미 +20%를 찍은 케이스는 예측 대상이 아니므로 분리한다.
"""
import os
import sys
from datetime import time as dtime

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOP_N = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--top=")), 20))
CUT = os.environ.get("SCAN_CUTOFF", "1000")   # "0930"이면 09:30 기준으로 전부 다시 잰다
SUF = "" if CUT == "1000" else f"_{CUT}"
CUTOFF = dtime(int(CUT[:2]), int(CUT[2:]))
MINUTE_DIR = "data/stocks/minute"
DAILY_DIR = "data/stocks/daily"
OUT = f"results/reach20_features{SUF}.csv"
# 정상일은 570~600종목이 잡힌다. 절반 아래로 떨어지면 수집이 밀린 날로 보고 버린다.
MIN_POOL = 300

# (컬럼, 표시명, 방향힌트) — 방향은 리포트 해석용 주석일 뿐 계산에 안 쓴다
FEATURES = [
    ("ret_at_10_pct", "10시 등락률(전일比)"),
    ("high_at_10_pct", "10시까지 고가(전일比)"),
    ("open_gap_pct", "시가 갭"),
    ("cum_value_eok", "10시까지 누적대금(억)"),
    ("value_vs_prev_day", "10시대금/전일종일대금"),
    ("value_vs_20d_avg", "10시대금/20일평균대금"),
    ("max_dd_to_10_pct", "10시까지 최대눌림"),
    ("pos_in_range_10", "10시 종가의 당일레인지 위치"),
    ("upper_wick_ratio", "10시까지 윗꼬리 비율"),
    ("first5_value_share", "첫 5분 대금 비중"),
    ("prev_day_ret_pct", "전일 등락률"),
    ("d5_ret_pct", "최근 5일 수익률"),
    ("high_vs_20d_high_pct", "10시고가/20일고가"),
    ("atr20_pct", "20일 ATR%"),
    ("price_log", "주가(log10)"),
]


def build() -> pd.DataFrame:
    names = dict(
        zip(*pd.read_csv("data/universe.csv", dtype={"stock_code": str})[["stock_code", "name"]].values.T)
    )
    codes = sorted(f[:-4] for f in os.listdir(MINUTE_DIR) if f.endswith(".csv"))
    rows = []
    for i, code in enumerate(codes, 1):
        dpath = os.path.join(DAILY_DIR, f"{code}.csv")
        if not os.path.exists(dpath):
            continue
        print(f"\r[{i}/{len(codes)}] {code}", end="", file=sys.stderr)

        daily = pd.read_csv(dpath, index_col=0, parse_dates=True).sort_index()
        prev_close = daily["close"].shift(1)
        prev_ret = daily["close"].pct_change().shift(1) * 100
        prev_value = (daily["close"] * daily["volume"]).shift(1)
        avg_value_20 = (daily["close"] * daily["volume"]).rolling(20).mean().shift(1)
        # 20일 고가/ATR은 "전일까지"만 — shift(1)로 당일 정보 차단
        high_20 = daily["high"].rolling(20).max().shift(1)
        tr = pd.concat(
            [
                daily["high"] - daily["low"],
                (daily["high"] - daily["close"].shift(1)).abs(),
                (daily["low"] - daily["close"].shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr20 = (tr.rolling(20).mean() / daily["close"]).shift(1) * 100
        d5 = (daily["close"] / daily["close"].shift(5) - 1).shift(1) * 100

        minute = pd.read_csv(os.path.join(MINUTE_DIR, f"{code}.csv"), index_col=0, parse_dates=True)
        minute = minute.sort_index()
        for date, bars in minute.groupby(minute.index.normalize()):
            if date not in prev_close.index:
                continue
            pc = prev_close.loc[date]
            if pd.isna(pc) or pc <= 0 or pd.isna(avg_value_20.loc[date]) or avg_value_20.loc[date] <= 0:
                continue
            am = bars[bars.index.time <= CUTOFF]
            pm = bars[bars.index.time > CUTOFF]
            if len(am) < 5 or len(pm) < 5:
                continue

            value = (am["close"] * am["volume"]).sum()
            if value <= 0:
                continue
            hi, lo = float(am["high"].max()), float(am["low"].min())
            peak = am["high"].cummax()
            rng = hi - lo
            rows.append(
                {
                    "date": date,
                    "stock_code": code,
                    "name": names.get(code, ""),
                    "cum_value_eok": value / 1e8,
                    "ret_at_10_pct": float(am["close"].iloc[-1] / pc - 1) * 100,
                    "high_at_10_pct": (hi / pc - 1) * 100,
                    "open_gap_pct": float(am["open"].iloc[0] / pc - 1) * 100,
                    "value_vs_prev_day": value / prev_value.loc[date] if prev_value.loc[date] > 0 else np.nan,
                    "value_vs_20d_avg": value / avg_value_20.loc[date],
                    "max_dd_to_10_pct": float(((peak - am["low"]) / peak).max()) * 100,
                    "pos_in_range_10": (float(am["close"].iloc[-1]) - lo) / rng if rng > 0 else 0.5,
                    "upper_wick_ratio": (hi - float(am["close"].iloc[-1])) / rng if rng > 0 else 0.0,
                    "first5_value_share": float((am["close"] * am["volume"]).iloc[:5].sum()) / value,
                    "prev_day_ret_pct": prev_ret.loc[date],
                    "d5_ret_pct": d5.loc[date],
                    "high_vs_20d_high_pct": (hi / high_20.loc[date] - 1) * 100,
                    "atr20_pct": atr20.loc[date],
                    "price_log": np.log10(pc),
                    "already_20_by_10": hi >= pc * 1.20,
                    "reach20_after_10": float(pm["high"].max()) >= pc * 1.20,
                    "mfe_after_10am_pct": float(pm["high"].max() / am["close"].iloc[-1] - 1) * 100,
                    "close_ret_from_10am_pct": float(bars["close"].iloc[-1] / am["close"].iloc[-1] - 1) * 100,
                }
            )
    print(file=sys.stderr)
    df = pd.DataFrame(rows)
    # 그날 데이터가 있는 종목이 너무 적으면 순위 자체가 가짜가 된다 — 수집이 밀린 날엔
    # 빈 자리로 엉뚱한 종목이 top10에 밀려 들어온다(실제로 2026-07-20~08-11 구간에서
    # 45~95종목만 남아 970억짜리가 10위로 잡혔다). 그런 날은 통째로 버린다.
    pool = df.groupby("date")["stock_code"].transform("size")
    thin = df.loc[pool < MIN_POOL, "date"].nunique()
    if thin:
        bad = sorted(df.loc[pool < MIN_POOL, "date"].unique())
        print(f"\n경고: 모집단 {MIN_POOL}종목 미만인 {thin}일 제외 "
              f"({bad[0]:%Y-%m-%d} ~ {bad[-1]:%Y-%m-%d}) — 데이터 수집 확인 필요",
              file=sys.stderr)
    df = df[pool >= MIN_POOL].copy()

    # 장중 누적대금 기준 그날 상위 TOP_N만 — 여기서 비로소 "대금 순위 20위" 모집단이 된다
    df["rank_10am"] = df.groupby("date")["cum_value_eok"].rank(ascending=False, method="first")
    return df[df["rank_10am"] <= TOP_N].copy()


def auc(x: pd.Series, y: pd.Series) -> float:
    """Mann-Whitney AUC — 단조변환에 불변이라 스케일 다른 피처끼리 비교 가능."""
    m = x.notna()
    x, y = x[m], y[m]
    if y.nunique() < 2:
        return 0.5
    r = x.rank()
    n1 = int(y.sum())
    n0 = len(y) - n1
    return (r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z, p = 1.96, k / n
    d = 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / d
    m = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return (max(0.0, c - m) * 100, min(1.0, c + m) * 100)


def report(df: pd.DataFrame) -> None:
    print("=" * 92)
    print(f"대금 상위 {TOP_N}(10:00 장중누적 기준) 종목-일자의 +20% 도달 조건 탐색")
    print("=" * 92)
    print(f"기간          : {df['date'].min().date()} ~ {df['date'].max().date()} "
          f"({df['date'].nunique()}거래일, {df['stock_code'].nunique()}종목)")
    print(f"모집단        : {len(df):,}건 (하루 최대 {TOP_N}건)")
    pre = int(df["already_20_by_10"].sum())
    print(f"10시 전 +20%  : {pre:,}건 ({pre/len(df)*100:.1f}%) — 예측 대상 아님, 제외")

    pop = df[~df["already_20_by_10"]].copy()
    y = pop["reach20_after_10"]
    base = y.mean()
    print(f"분석 대상     : {len(pop):,}건,  10시 이후 +20% 도달 {int(y.sum()):,}건 "
          f"= 베이스레이트 {base*100:.2f}%")

    print("\n" + "-" * 92)
    print("[1] 단변량 판별력 (AUC 순) — Q1=하위20%, Q5=상위20% 구간의 +20% 도달률")
    print("-" * 92)
    print(f"{'피처':>26}{'AUC':>7}{'Q1':>7}{'Q2':>7}{'Q3':>7}{'Q4':>7}{'Q5':>7}{'Q5/Q1':>8}")
    scored = sorted(FEATURES, key=lambda f: -abs(auc(pop[f[0]], y) - 0.5))
    for col, label in scored:
        a = auc(pop[col], y)
        try:
            q = pd.qcut(pop[col], 5, labels=False, duplicates="drop")
        except ValueError:
            continue
        rates = pop.groupby(q, observed=True)["reach20_after_10"].mean() * 100
        cells = "".join(f"{rates.get(i, float('nan')):>6.1f}%" for i in range(5))
        r1, r5 = rates.get(0, np.nan), rates.get(4, np.nan)
        ratio = r5 / r1 if r1 and r1 > 0 else np.nan
        print(f"{label:>26}{a:>7.3f}{cells}{ratio:>7.2f}x")
    print("\nAUC 0.5=무정보. 0.60 이상이면 단독으로 쓸 만한 신호, 0.55 미만은 사실상 노이즈.")

    print("\n" + "-" * 92)
    print("[2] 상위 피처 조합 — 상위 40% 동시 충족")
    print("-" * 92)
    top3 = [c for c, _ in scored[:3]]
    labels = {c: l for c, l in FEATURES}
    masks = {}
    for col in top3:
        a = auc(pop[col], y)
        thr = pop[col].quantile(0.60 if a > 0.5 else 0.40)
        masks[col] = pop[col] >= thr if a > 0.5 else pop[col] <= thr
        print(f"  {labels[col]}: {'>=' if a > 0.5 else '<='} {thr:.2f} (AUC {a:.3f})")
    print(f"\n{'조건':>44}{'n':>7}{'+20%':>8}{'95%CI':>13}{'배수':>7}{'MFE중앙':>9}")
    combos = [(labels[top3[0]], masks[top3[0]])]
    if len(top3) > 1:
        m2 = masks[top3[0]] & masks[top3[1]]
        combos.append((f"{labels[top3[0]]} + {labels[top3[1]]}", m2))
        if len(top3) > 2:
            combos.append(("위 둘 + " + labels[top3[2]], m2 & masks[top3[2]]))
    combos.insert(0, ("(없음) 전체", pd.Series(True, index=pop.index)))
    for label, m in combos:
        g = pop[m]
        if len(g) == 0:
            continue
        k = int(g["reach20_after_10"].sum())
        lo, hi = wilson(k, len(g))
        print(f"{label:>44}{len(g):>7}{k/len(g)*100:>7.2f}%{f'[{lo:.1f}-{hi:.1f}]':>13}"
              f"{k/len(g)/base:>6.2f}x{g['mfe_after_10am_pct'].median():>8.2f}%")

    print("\n" + "-" * 92)
    print("[3] 최종 조합의 분기별 재현성")
    print("-" * 92)
    final = combos[-1][1]
    print(f"{'분기':>9}{'n':>6}{'+20%':>8}{'분기베이스':>10}{'배수':>7}{'MFE중앙':>9}{'종가중앙':>9}")
    pop = pop.assign(quarter=pop["date"].dt.to_period("Q"), sel=final)
    wins = 0
    for q, g in pop.groupby("quarter", observed=True):
        s = g[g["sel"]]
        qb = g["reach20_after_10"].mean()
        if len(s) == 0 or qb == 0:
            continue
        r = s["reach20_after_10"].mean()
        wins += r > qb
        print(f"{str(q):>9}{len(s):>6}{r*100:>7.2f}%{qb*100:>9.2f}%{r/qb:>6.2f}x"
              f"{s['mfe_after_10am_pct'].median():>8.2f}%{s['close_ret_from_10am_pct'].median():>8.2f}%")
    print(f"\n베이스 초과 분기 {wins}/{pop['quarter'].nunique()}")


def stratified(df: pd.DataFrame) -> None:
    """10시 등락률(= +20%까지 남은 거리)을 통제한 뒤 남는 신호만 본다.

    등락률 AUC 0.92는 "이미 많이 오른 종목이 +20%에 가깝다"는 동어반복에 가깝다.
    같은 등락률 구간 안에서 갈리는 피처가 있어야 진짜 조건이다.
    """
    pop = df[~df["already_20_by_10"]].copy()
    bands = [-100, 0, 3, 6, 9, 12, 100]
    pop["band"] = pd.cut(pop["ret_at_10_pct"], bands, right=False)
    labels = {c: l for c, l in FEATURES}

    print("\n" + "-" * 92)
    print("[4] 10시 등락률 통제 후 층화 AUC — 같은 상승률 구간 안에서 갈리는 피처")
    print("-" * 92)
    print(f"{'구간(10시 등락률)':>18}{'n':>7}{'+20%':>8}", end="")
    others = [c for c, _ in FEATURES if c not in ("ret_at_10_pct", "high_at_10_pct")]
    print()
    for b, g in pop.groupby("band", observed=True):
        k = int(g["reach20_after_10"].sum())
        rng = f"{b.left:g}~{b.right:g}%" if b.right < 100 else f"{b.left:g}%+"
        print(f"{rng:>18}{len(g):>7}{k/len(g)*100:>7.2f}%")

    # 층화 AUC: 구간별 U통계량을 합산해 구간 효과를 제거
    print(f"\n{'피처':>26}{'층화AUC':>9}{'단순AUC':>9}{'차이':>8}")
    rows = []
    for col in others:
        u_sum = w_sum = 0.0
        for _, g in pop.groupby("band", observed=True):
            y = g["reach20_after_10"]
            n1, n0 = int(y.sum()), len(y) - int(y.sum())
            if n1 == 0 or n0 == 0:
                continue
            u_sum += auc(g[col], y) * n1 * n0
            w_sum += n1 * n0
        if w_sum == 0:
            continue
        sa = u_sum / w_sum
        pa = auc(pop[col], pop["reach20_after_10"])
        rows.append((abs(sa - 0.5), col, sa, pa))
    for _, col, sa, pa in sorted(rows, reverse=True):
        print(f"{labels[col]:>26}{sa:>9.3f}{pa:>9.3f}{sa-pa:>+8.3f}")
    print("\n층화AUC가 0.5로 붕괴하면 그 피처는 '많이 올랐다'의 대리변수였을 뿐이다.")

    print("\n" + "-" * 92)
    print("[5] 구간별로 최상위 층화 피처의 상위40% vs 하위60% 도달률")
    print("-" * 92)
    best = sorted(rows, reverse=True)[0]
    col, sa = best[1], best[2]
    print(f"기준 피처: {labels[col]} (층화AUC {sa:.3f}, {'높을수록' if sa > 0.5 else '낮을수록'} 유리)\n")
    print(f"{'구간':>12}{'선택n':>7}{'선택+20%':>10}{'제외n':>7}{'제외+20%':>10}{'배수':>7}")
    for b, g in pop.groupby("band", observed=True):
        thr = g[col].quantile(0.60 if sa > 0.5 else 0.40)
        m = g[col] >= thr if sa > 0.5 else g[col] <= thr
        s, o = g[m], g[~m]
        if len(s) == 0 or len(o) == 0 or o["reach20_after_10"].mean() == 0:
            continue
        sr, orr = s["reach20_after_10"].mean(), o["reach20_after_10"].mean()
        rng = f"{b.left:g}~{b.right:g}%" if b.right < 100 else f"{b.left:g}%+"
        print(f"{rng:>12}{len(s):>7}{sr*100:>9.2f}%{len(o):>7}{orr*100:>9.2f}%{sr/orr:>6.2f}x")


def demo() -> None:
    """AUC와 시점차단 로직 자체검증."""
    y = pd.Series([True, True, False, False])
    assert auc(pd.Series([4.0, 3.0, 2.0, 1.0]), y) == 1.0
    assert auc(pd.Series([1.0, 2.0, 3.0, 4.0]), y) == 0.0
    assert abs(auc(pd.Series([3.0, 2.0, 4.0, 1.0]), y) - 0.5) < 1e-9  # 양성 3,2 / 음성 4,1 -> 무정보
    assert abs(auc(pd.Series([1.0, 3.0, 2.0, 4.0]), y) - 0.25) < 1e-9
    idx = pd.date_range("2026-01-02 09:00", periods=90, freq="1min")
    bars = pd.DataFrame({"high": 1.0, "low": 1.0, "close": 1.0, "open": 1.0, "volume": 1}, index=idx)
    am = bars[bars.index.time <= CUTOFF]
    assert am.index.max().strftime("%H:%M") == "10:00" and len(am) == 61, len(am)
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()
    if "--reuse" in sys.argv and os.path.exists(OUT):
        df = pd.read_csv(OUT, parse_dates=["date"], dtype={"stock_code": str})
        # 저장된 CSV는 top20까지 담겨 있어 그 이하 N은 필터만으로 재현된다(그 이상은 재빌드 필요)
        df = df[df["rank_10am"] <= TOP_N]
    else:
        df = build()
        df.to_csv(OUT, index=False, encoding="utf-8-sig")
    report(df)
    stratified(df)
    print(f"\n원본: {OUT}")
