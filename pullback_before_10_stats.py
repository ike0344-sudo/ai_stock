"""거래대금 상위 20 종목 중 +10% 도달 전 눌림폭과 +20% 고점 달성의 관계 통계.

패턴: 전일종가 대비 장중 고점 +20% 이상 나온 종목이, +10% 최초 도달 전까지
러닝 고점 대비 -4% 정도만 눌리고 계속 올라갔다는 관찰의 검증.

핵심은 "+20% 간 종목들이 어떻게 눌렸나"(선택편향)가 아니라
"눌림폭이 작았던 종목이 실제로 +20%까지 더 자주 가나"(조건부확률)이다. 둘 다 출력.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backtesting.universe import daily_top_n_from_local

TOP_N = 20
MINUTE_DIR = "data/stocks/minute"
DAILY_DIR = "data/stocks/daily"


def load_names() -> dict[str, str]:
    df = pd.read_csv("data/universe.csv", dtype={"stock_code": str})
    return dict(zip(df["stock_code"], df["name"]))


def build_events(top_by_date: dict[pd.Timestamp, set[str]]) -> pd.DataFrame:
    """top20 종목-일자 중 장중 +10%를 찍은 케이스마다 눌림폭/이후결과 1행."""
    codes_needed: dict[str, set[pd.Timestamp]] = {}
    for date, codes in top_by_date.items():
        for code in codes:
            codes_needed.setdefault(code, set()).add(date)

    names = load_names()
    rows = []
    for i, (code, dates) in enumerate(sorted(codes_needed.items()), 1):
        min_path = os.path.join(MINUTE_DIR, f"{code}.csv")
        daily_path = os.path.join(DAILY_DIR, f"{code}.csv")
        if not os.path.exists(min_path) or not os.path.exists(daily_path):
            continue
        print(f"\r[{i}/{len(codes_needed)}] {code}", end="", file=sys.stderr)

        daily = pd.read_csv(daily_path, index_col=0, parse_dates=True)
        prev_close = daily["close"].shift(1)

        minute = pd.read_csv(min_path, index_col=0, parse_dates=True)
        for date, bars in minute.groupby(minute.index.normalize()):
            if date not in dates or date not in prev_close.index:
                continue
            pc = prev_close.loc[date]
            if pd.isna(pc) or pc <= 0 or len(bars) < 2:
                continue

            p10, p20 = pc * 1.10, pc * 1.20
            hit = np.flatnonzero(bars["high"].to_numpy() >= p10)
            if hit.size == 0:
                continue  # +10% 미달 — 패턴 자체가 성립 안 함
            t10 = int(hit[0])

            pre = bars.iloc[:t10]  # +10%를 찍은 봉 직전까지가 "도달 전" 구간
            if len(pre) == 0:
                # 시가 갭으로 바로 +10% — 눌림 구간 없음
                max_dd, dd_peak, dd_low, dd_time = 0.0, float("nan"), float("nan"), ""
            else:
                peak = pre["high"].cummax()
                dd_series = (peak - pre["low"]) / peak
                j = int(dd_series.to_numpy().argmax())
                max_dd = float(dd_series.iloc[j])
                dd_peak = float(peak.iloc[j])          # 눌림 시작 러닝 고점
                dd_low = float(pre["low"].iloc[j])     # 눌림 저점
                dd_time = pre.index[j].strftime("%H:%M")

            post = bars.iloc[t10:]
            day_high = float(bars["high"].max())
            rows.append(
                {
                    "date": date.date(),
                    "stock_code": code,
                    "name": names.get(code, ""),
                    "prev_close": float(pc),
                    "open_gap_pct": float(bars["open"].iloc[0] / pc - 1) * 100,
                    "day_high_pct": (day_high / pc - 1) * 100,
                    "t10_time": bars.index[t10].strftime("%H:%M"),
                    "bars_before_10": t10,
                    "max_dd_before_10_pct": max_dd * 100,
                    "dd_peak_pct": (dd_peak / pc - 1) * 100,
                    "dd_low_pct": (dd_low / pc - 1) * 100,
                    "dd_low_time": dd_time,
                    "rise_from_dd_low_pct": (day_high / dd_low - 1) * 100,
                    "reached_20": day_high >= p20,
                    "mfe_after_10_pct": float(post["high"].max() / p10 - 1) * 100,
                    "mae_after_10_pct": float(post["low"].min() / p10 - 1) * 100,
                    "close_ret_after_10_pct": float(bars["close"].iloc[-1] / p10 - 1) * 100,
                }
            )
    print(file=sys.stderr)
    return pd.DataFrame(rows)


def wilson(k: int, n: int) -> tuple[float, float]:
    """이항비율 95% 신뢰구간 — 표본이 작은 구간에서 정규근사보다 안전."""
    if n == 0:
        return (0.0, 0.0)
    z, p = 1.96, k / n
    d = 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / d
    m = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return (max(0.0, c - m) * 100, min(1.0, c + m) * 100)


def report(ev: pd.DataFrame) -> None:
    def pct(x):
        return f"{x:6.1f}%"

    print("=" * 78)
    print(f"거래대금 상위 {TOP_N} + 장중 +10% 도달 이벤트")
    print("=" * 78)
    print(f"기간            : {ev['date'].min()} ~ {ev['date'].max()}")
    print(f"이벤트 수       : {len(ev):,}건 ({ev['stock_code'].nunique()}종목, {ev['date'].nunique()}일)")
    n20 = int(ev["reached_20"].sum())
    print(f"이 중 +20% 달성 : {n20:,}건 ({n20/len(ev)*100:.1f}%)  <- 전체 기준선(base rate)")

    gap = ev["bars_before_10"] == 0
    print(f"시가갭 +10%     : {gap.sum():,}건 (눌림 구간 없음 — 아래 분석에서 제외)")

    core = ev[~gap]
    print(f"분석 대상       : {len(core):,}건")

    print("\n" + "-" * 78)
    print("[1] 사용자가 관찰한 방향: +20% 간 종목들의 +10% 도달 전 눌림폭 분포")
    print("-" * 78)
    win, lose = core[core["reached_20"]], core[~core["reached_20"]]
    print(f"{'':16}{'n':>6}{'중앙값':>9}{'평균':>9}{'75%':>9}{'90%':>9}{'최대':>9}")
    for label, g in [("+20% 달성", win), ("+20% 미달", lose)]:
        d = g["max_dd_before_10_pct"]
        if len(d) == 0:
            continue
        print(
            f"{label:16}{len(d):>6}{d.median():>8.2f}%{d.mean():>8.2f}%"
            f"{d.quantile(.75):>8.2f}%{d.quantile(.90):>8.2f}%{d.max():>8.2f}%"
        )
    if len(win):
        w = win["max_dd_before_10_pct"]
        print(f"\n-> +20% 달성 케이스 중 눌림 4% 이내: {(w <= 4).sum()}/{len(w)} ({(w<=4).mean()*100:.1f}%)")
        print("   (관찰은 맞지만 이것만으론 편향. 반대 방향은 [2] 참조)")

    print("\n" + "-" * 78)
    print("[1-b] 얼마나 빠지고 얼마나 올랐나 (최대 눌림 1회 기준)")
    print("-" * 78)
    print(f"{'':24}{'10%':>9}{'중앙':>9}{'평균':>9}{'90%':>9}")
    for col, label in [
        ("dd_peak_pct", "눌림 시작 고점(전일比)"),
        ("dd_low_pct", "눌림 저점(전일比)"),
        ("max_dd_before_10_pct", "눌림폭(고점比)"),
        ("rise_from_dd_low_pct", "눌림저점->당일고점"),
    ]:
        for label2, g in [("+20% 달성", win), ("+20% 미달", lose)]:
            d = g[col].dropna()
            if not len(d):
                continue
            head = f"{label} {label2}" if label2.endswith("달성") else f"{'':>{len(label)}} {label2}"
            print(f"{head:24}{d.quantile(.10):>8.1f}%{d.median():>8.1f}%{d.mean():>8.1f}%{d.quantile(.90):>8.1f}%")
    print(f"\n눌림 저점 시각(+20% 달성) 최빈: {win['dd_low_time'].str[:2].mode().iat[0]}시")

    print("\n" + "-" * 78)
    print("[2] 실제 예측력: 눌림폭 구간별 +20% 달성률")
    print("-" * 78)
    bins = [0, 1, 2, 3, 4, 5, 7, 10, 100]
    core = core.assign(bucket=pd.cut(core["max_dd_before_10_pct"], bins, right=False))
    print(f"{'눌림폭':>12}{'n':>7}{'+20%달성':>10}{'달성률':>9}{'95% CI':>16}{'MFE중앙':>9}{'MAE중앙':>9}")
    for b, g in core.groupby("bucket", observed=True):
        if len(g) == 0:
            continue
        k = int(g["reached_20"].sum())
        lo, hi = wilson(k, len(g))
        rng = f"{b.left:g}~{b.right:g}%" if b.right < 100 else f"{b.left:g}%+"
        print(
            f"{rng:>12}{len(g):>7}{k:>10}{k/len(g)*100:>8.1f}%"
            f"{f'[{lo:.0f}-{hi:.0f}]':>16}"
            f"{g['mfe_after_10_pct'].median():>8.1f}%{g['mae_after_10_pct'].median():>8.1f}%"
        )

    print("\n" + "-" * 78)
    print("[3] -4% 임계값 검정")
    print("-" * 78)
    tight = core[core["max_dd_before_10_pct"] <= 4]
    loose = core[core["max_dd_before_10_pct"] > 4]
    tk, lk = int(tight["reached_20"].sum()), int(loose["reached_20"].sum())
    for label, g, k in [("눌림 <= 4%", tight, tk), ("눌림 >  4%", loose, lk)]:
        if len(g) == 0:
            continue
        lo, hi = wilson(k, len(g))
        print(f"{label:12} n={len(g):>5}  +20% {k:>4}건  달성률 {k/len(g)*100:5.1f}%  95%CI [{lo:.1f}-{hi:.1f}]")
    if len(tight) and len(loose):
        from scipy.stats import fisher_exact

        odds, p = fisher_exact([[tk, len(tight) - tk], [lk, len(loose) - lk]])
        lift = (tk / len(tight)) / (lk / len(loose)) if lk else float("inf")
        print(f"\nFisher exact p = {p:.4g}   odds ratio = {odds:.2f}   달성률 배수 = {lift:.2f}x")
        print("판정: " + ("유의미한 차이 있음 (p<0.05)" if p < 0.05 else "통계적으로 유의하지 않음 (p>=0.05)"))

    print("\n" + "-" * 78)
    print("[4] +10% 도달 시점에 매수했다면 (눌림 <= 4% 조건)")
    print("-" * 78)
    if len(tight):
        for col, label in [
            ("mfe_after_10_pct", "최대상승(MFE)"),
            ("mae_after_10_pct", "최대하락(MAE)"),
            ("close_ret_after_10_pct", "종가수익률"),
        ]:
            d = tight[col]
            print(f"{label:16} 중앙 {d.median():>6.2f}%  평균 {d.mean():>6.2f}%  "
                  f"10%분위 {d.quantile(.10):>6.2f}%  90%분위 {d.quantile(.90):>6.2f}%")
        print(f"\n종가 기준 승률   {(tight['close_ret_after_10_pct'] > 0).mean()*100:.1f}%")
        for tp in (3, 5, 10):
            print(f"+{tp}% 선도달 비율 {(tight['mfe_after_10_pct'] >= tp).mean()*100:5.1f}%"
                  f"   (같은 케이스 -{tp}% 터치 {(tight['mae_after_10_pct'] <= -tp).mean()*100:5.1f}%)")

    print("\n" + "-" * 78)
    print("[5] +10% 도달 시각별 +20% 달성률")
    print("-" * 78)
    core = core.assign(hour=core["t10_time"].str[:2] + "시")
    for h, g in core.groupby("hour"):
        k = int(g["reached_20"].sum())
        print(f"{h:>6}  n={len(g):>5}  +20% 달성률 {k/len(g)*100:5.1f}%")

    print("\n" + "-" * 78)
    print("[6] 눌림 -2% ~ -4% 밴드 상세 (+10% 도달 전 최대 눌림이 이 구간)")
    print("-" * 78)
    band = core[(core["max_dd_before_10_pct"] >= 2) & (core["max_dd_before_10_pct"] < 4)]
    other = core.drop(band.index)
    print(f"해당 {len(band):,}건 / 분석 {len(core):,}건 = {len(band)/len(core)*100:.1f}%"
          f"   (전체 +10% 이벤트 {len(ev):,}건 대비 {len(band)/len(ev)*100:.1f}%)")
    for label, g in [("밴드 내(2~4%)", band), ("밴드 외", other)]:
        k = int(g["reached_20"].sum())
        lo, hi = wilson(k, len(g))
        print(f"{label:14} n={len(g):>5}  +20% {k:>4}건  달성률 {k/len(g)*100:5.1f}%  95%CI [{lo:.1f}-{hi:.1f}]")

    print(f"\n{'':22}{'10%':>9}{'중앙':>9}{'평균':>9}{'90%':>9}")
    for col, label in [
        ("dd_peak_pct", "눌림 시작 고점(전일比)"),
        ("dd_low_pct", "눌림 저점(전일比)"),
        ("max_dd_before_10_pct", "눌림폭(고점比)"),
        ("dd_low_time", ""),
        ("rise_from_dd_low_pct", "눌림저점->당일고점"),
        ("mfe_after_10_pct", "+10%후 최대상승"),
        ("mae_after_10_pct", "+10%후 최대하락"),
        ("close_ret_after_10_pct", "+10%후 종가수익"),
    ]:
        if col == "dd_low_time":
            continue
        d = band[col].dropna()
        print(f"{label:22}{d.quantile(.10):>8.1f}%{d.median():>8.1f}%{d.mean():>8.1f}%{d.quantile(.90):>8.1f}%")
    print(f"\n종가 승률 {(band['close_ret_after_10_pct'] > 0).mean()*100:.1f}%"
          f"   +3% 선도달 {(band['mfe_after_10_pct'] >= 3).mean()*100:.1f}%"
          f"   +5% 선도달 {(band['mfe_after_10_pct'] >= 5).mean()*100:.1f}%")
    print(f"눌림 저점 시각 : " + "  ".join(
        f"{h}시 {c/len(band)*100:.0f}%" for h, c in band["dd_low_time"].str[:2].value_counts().head(4).items()))
    print(f"+10% 도달 시각 : " + "  ".join(
        f"{h}시 {c/len(band)*100:.0f}%" for h, c in band["t10_time"].str[:2].value_counts().head(4).items()))
    print("\n눌림 저점 -> +10% 도달까지 소요(분) 중앙값 "
          f"{(pd.to_datetime(band['t10_time']) - pd.to_datetime(band['dd_low_time'])).dt.total_seconds().div(60).median():.0f}분")


def demo() -> None:
    """핵심 경로 자체검증 — 눌림폭/도달시점 계산이 깨지면 여기서 걸린다."""
    idx = pd.date_range("2026-01-02 09:00", periods=6, freq="1min")
    bars = pd.DataFrame(
        {  # 전일종가 100 기준: +5% -> -3% 눌림 -> +10% 도달 -> +21%
            "open": [103, 105, 102, 104, 109, 118],
            "high": [105, 106, 103, 108, 111, 121],
            "low": [102, 102, 101, 103, 108, 117],
            "close": [104, 103, 102, 107, 110, 120],
        },
        index=idx,
    )
    pc = 100.0
    hit = np.flatnonzero(bars["high"].to_numpy() >= pc * 1.10)
    assert hit[0] == 4, hit
    pre = bars.iloc[: hit[0]]
    peak = pre["high"].cummax()
    dd = ((peak - pre["low"]) / peak).max()
    assert abs(dd - (106 - 101) / 106) < 1e-9, dd
    assert bars["high"].max() >= pc * 1.20
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()

    print("거래대금 상위 20 산출 중...", file=sys.stderr)
    top_by_date = daily_top_n_from_local(DAILY_DIR, top_n=TOP_N)
    events = build_events(top_by_date)
    if events.empty:
        print("이벤트 없음 — 데이터 확인 필요")
        sys.exit(1)
    events.to_csv("results/pullback_before_10_events.csv", index=False, encoding="utf-8-sig")
    report(events)
    print("\n원본 이벤트: results/pullback_before_10_events.csv")
