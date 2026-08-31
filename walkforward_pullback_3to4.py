"""눌림 3~4% 필터의 워크포워드 검증.

results/pullback_before_10_events.csv(= pullback_before_10_stats.py 산출물)를 재사용해
데이터 재수집 없이 시간분할 검증만 수행한다.

두 가지를 분리해서 본다:
  [A] 고정규칙 검증 — "눌림 3~4%"를 미리 정해진 룰로 보고 분기별로 우위가 재현되나
  [B] 앵커드 워크포워드 — 과거 구간에서 최고 밴드를 *선택*하고 다음 구간에서 검증.
      전체 표본에서 3~4%가 1등이었다는 사실 자체가 선택편향이므로 [B]가 본 검증이다.
"""
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EVENTS = "results/pullback_before_10_events.csv"
BINS = [0, 1, 2, 3, 4, 5, 7, 10, 100]
MIN_TRAIN_N = 40  # 이보다 표본이 적은 밴드는 학습구간에서 선택 후보로 안 쓴다
BAND = (3.0, 4.0)


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z, p = 1.96, k / n
    d = 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / d
    m = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return (max(0.0, c - m) * 100, min(1.0, c + m) * 100)


def load_core() -> pd.DataFrame:
    ev = pd.read_csv(EVENTS, parse_dates=["date"])
    core = ev[ev["bars_before_10"] > 0].copy()  # 시가갭 즉시 +10%는 눌림 구간 없음
    core["quarter"] = core["date"].dt.to_period("Q")
    core["bucket"] = pd.cut(core["max_dd_before_10_pct"], BINS, right=False)
    core["in_band"] = core["max_dd_before_10_pct"].between(BAND[0], BAND[1], inclusive="left")
    core["early"] = core["t10_time"].str[:2].isin(("09", "10"))
    return core.sort_values("date")


def fixed_rule(core: pd.DataFrame) -> None:
    print("=" * 84)
    print(f"[A] 고정규칙: 눌림 {BAND[0]:g}~{BAND[1]:g}% vs 나머지 — 분기별 재현성")
    print("=" * 84)
    print(f"{'분기':>9}{'밴드n':>7}{'밴드+20%':>10}{'95%CI':>14}"
          f"{'나머지n':>8}{'나머지+20%':>11}{'배수':>7}{'종가승률':>9}{'종가중앙':>9}")
    wins = 0
    for q, g in core.groupby("quarter", observed=True):
        b, o = g[g["in_band"]], g[~g["in_band"]]
        if len(b) == 0 or len(o) == 0:
            continue
        bk, ok = int(b["reached_20"].sum()), int(o["reached_20"].sum())
        br, orr = bk / len(b), ok / len(o)
        lo, hi = wilson(bk, len(b))
        wins += br > orr
        print(f"{str(q):>9}{len(b):>7}{br*100:>9.1f}%{f'[{lo:.0f}-{hi:.0f}]':>14}"
              f"{len(o):>8}{orr*100:>10.1f}%{br/orr if orr else float('nan'):>6.2f}x"
              f"{(b['close_ret_after_10_pct']>0).mean()*100:>8.1f}%"
              f"{b['close_ret_after_10_pct'].median():>8.2f}%")
    n_q = core["quarter"].nunique()
    print(f"\n밴드가 우위인 분기: {wins}/{n_q}  (동전던지기 기대값 {n_q/2:.1f})")

    from scipy.stats import binomtest, fisher_exact

    b, o = core[core["in_band"]], core[~core["in_band"]]
    bk, ok = int(b["reached_20"].sum()), int(o["reached_20"].sum())
    odds, p = fisher_exact([[bk, len(b) - bk], [ok, len(o) - ok]])
    sign_p = binomtest(wins, n_q, 0.5, alternative="greater").pvalue
    print(f"통합 Fisher exact p = {p:.4g}  odds ratio = {odds:.2f}  "
          f"달성률 {bk/len(b)*100:.1f}% vs {ok/len(o)*100:.1f}%")
    print(f"분기 부호검정(단측)  p = {sign_p:.4g}  <- 매 분기 독립적으로 재현되는지")


def anchored_walkforward(core: pd.DataFrame) -> None:
    print("\n" + "=" * 84)
    print("[B] 앵커드 워크포워드: 이전 구간 전체로 최고 밴드 선택 -> 다음 분기에서 검증")
    print("=" * 84)
    quarters = sorted(core["quarter"].unique())
    print(f"{'검증분기':>10}{'학습n':>7}{'선택밴드':>11}{'학습률':>8}"
          f"{'검증n':>7}{'검증률':>8}{'해당분기베이스':>12}{'초과':>8}{'3~4%선택':>9}")
    excess, picks_34 = [], 0
    for i in range(1, len(quarters)):
        train = core[core["quarter"].isin(quarters[:i])]
        test = core[core["quarter"] == quarters[i]]
        if test.empty:
            continue
        stats = train.groupby("bucket", observed=True)["reached_20"].agg(["sum", "count"])
        cand = stats[stats["count"] >= MIN_TRAIN_N]
        if cand.empty:
            print(f"{str(quarters[i]):>10}{len(train):>7}{'표본부족':>11}")
            continue
        rate = cand["sum"] / cand["count"]
        pick = rate.idxmax()
        picked = test[test["bucket"] == pick]
        base = test["reached_20"].mean()
        if len(picked) == 0:
            continue
        oos = picked["reached_20"].mean()
        excess.append(oos - base)
        is_34 = pick.left == BAND[0] and pick.right == BAND[1]
        picks_34 += is_34
        label = f"{pick.left:g}~{pick.right:g}%" if pick.right < 100 else f"{pick.left:g}%+"
        print(f"{str(quarters[i]):>10}{len(train):>7}{label:>11}{rate.max()*100:>7.1f}%"
              f"{len(picked):>7}{oos*100:>7.1f}%{base*100:>11.1f}%"
              f"{(oos-base)*100:>+7.1f}%{'O' if is_34 else 'X':>9}")
    if excess:
        e = np.array(excess) * 100
        print(f"\n선택밴드가 3~4%였던 횟수 : {picks_34}/{len(excess)}")
        print(f"OOS 초과달성률 평균      : {e.mean():+.1f}%p  (중앙 {np.median(e):+.1f}%p, "
              f"양수 {int((e>0).sum())}/{len(e)}회)")
        print("판정: " + ("학습에서 고른 밴드가 미래에도 우위 — 약하지만 재현성 있음"
                        if e.mean() > 0 and (e > 0).sum() > len(e) / 2
                        else "학습에서 고른 밴드가 미래에는 우위 없음 — 과최적화(표본노이즈)"))


def band_rank_stability(core: pd.DataFrame) -> None:
    print("\n" + "=" * 84)
    print("[C] 밴드별 +20% 달성률 순위가 분기마다 유지되나 (숫자=해당분기 순위, n<20은 -)")
    print("=" * 84)
    tbl = {}
    for q, g in core.groupby("quarter", observed=True):
        r = g.groupby("bucket", observed=True)["reached_20"].agg(["sum", "count"])
        r = r[r["count"] >= 20]
        rate = (r["sum"] / r["count"]).sort_values(ascending=False)
        tbl[str(q)] = {b: i + 1 for i, b in enumerate(rate.index)}
    buckets = pd.cut(core["max_dd_before_10_pct"], BINS, right=False).cat.categories
    print(f"{'밴드':>10}" + "".join(f"{q:>10}" for q in tbl))
    for b in buckets:
        row = [tbl[q].get(b) for q in tbl]
        if all(v is None for v in row):
            continue
        label = f"{b.left:g}~{b.right:g}%" if b.right < 100 else f"{b.left:g}%+"
        print(f"{label:>10}" + "".join(f"{(str(v) if v else '-'):>10}" for v in row))


def combined(core: pd.DataFrame) -> None:
    from scipy.stats import binomtest, fisher_exact

    print("\n" + "=" * 84)
    print("[D] 눌림 3~4% + (+10% 도달 09~10시) 결합 검증")
    print("=" * 84)
    groups = {
        "전체(베이스)": core,
        "눌림 3~4%만": core[core["in_band"]],
        "09~10시만": core[core["early"]],
        "둘 다": core[core["in_band"] & core["early"]],
        "둘 다 아님": core[~core["in_band"] & ~core["early"]],
    }
    base = core["reached_20"].mean()
    print(f"{'조건':>14}{'n':>7}{'비중':>8}{'+20%':>8}{'95%CI':>13}{'베이스比':>9}"
          f"{'MFE중앙':>9}{'종가중앙':>9}{'종가승률':>9}")
    for label, g in groups.items():
        if len(g) == 0:
            continue
        k = int(g["reached_20"].sum())
        lo, hi = wilson(k, len(g))
        print(f"{label:>14}{len(g):>7}{len(g)/len(core)*100:>7.1f}%{k/len(g)*100:>7.1f}%"
              f"{f'[{lo:.0f}-{hi:.0f}]':>13}{k/len(g)/base:>8.2f}x"
              f"{g['mfe_after_10_pct'].median():>8.1f}%"
              f"{g['close_ret_after_10_pct'].median():>8.2f}%"
              f"{(g['close_ret_after_10_pct']>0).mean()*100:>8.1f}%")

    # 두 조건이 서로 독립인가 — 겹침이 단순 중복이면 결합 이득이 없다
    both = core[core["in_band"] & core["early"]]
    rest = core[~(core["in_band"] & core["early"])]
    bk, rk = int(both["reached_20"].sum()), int(rest["reached_20"].sum())
    odds, p = fisher_exact([[bk, len(both) - bk], [rk, len(rest) - rk]])
    print(f"\n결합 vs 나머지: {bk/len(both)*100:.1f}% vs {rk/len(rest)*100:.1f}%  "
          f"Fisher p = {p:.4g}  odds = {odds:.2f}")
    single_lift = (core[core["in_band"]]["reached_20"].mean() / base) * (
        core[core["early"]]["reached_20"].mean() / base)
    actual = both["reached_20"].mean() / base
    print(f"두 필터 단독배수의 곱 {single_lift:.2f}x vs 실제 결합배수 {actual:.2f}x "
          f"(실제/곱 = {actual/single_lift:.2f})")
    print("  1.0 근처면 두 조건이 서로 독립적인 정보, 1.0보다 낮으면 정보가 겹친다는 뜻")

    print("\n" + "-" * 84)
    print("분기별 재현성 (결합 조건)")
    print("-" * 84)
    print(f"{'분기':>9}{'n':>6}{'+20%':>8}{'95%CI':>13}{'분기베이스':>10}{'초과':>8}"
          f"{'MFE중앙':>9}{'MAE중앙':>9}{'종가중앙':>9}{'종가승률':>9}")
    wins = 0
    for q, g in core.groupby("quarter", observed=True):
        c = g[g["in_band"] & g["early"]]
        if len(c) == 0:
            continue
        k = int(c["reached_20"].sum())
        lo, hi = wilson(k, len(c))
        qb = g["reached_20"].mean()
        wins += k / len(c) > qb
        print(f"{str(q):>9}{len(c):>6}{k/len(c)*100:>7.1f}%{f'[{lo:.0f}-{hi:.0f}]':>13}"
              f"{qb*100:>9.1f}%{(k/len(c)-qb)*100:>+7.1f}%"
              f"{c['mfe_after_10_pct'].median():>8.1f}%{c['mae_after_10_pct'].median():>8.1f}%"
              f"{c['close_ret_after_10_pct'].median():>8.2f}%"
              f"{(c['close_ret_after_10_pct']>0).mean()*100:>8.1f}%")
    n_q = core["quarter"].nunique()
    sign_p = binomtest(wins, n_q, 0.5, alternative="greater").pvalue
    print(f"\n베이스 초과 분기 {wins}/{n_q}  부호검정 단측 p = {sign_p:.4g}")
    print(f"진입빈도: 결합 조건 {len(both):,}건 / {core['date'].nunique()}거래일 = "
          f"{len(both)/core['date'].nunique():.2f}건/일")


def demo() -> None:
    """분할/선택 로직 자체검증 — 미래 데이터가 학습에 새면 여기서 걸린다."""
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-05", "2025-05-05", "2025-08-05"]),
            "max_dd_before_10_pct": [3.5, 3.5, 3.5],
            "reached_20": [True, False, True],
            "bars_before_10": [10, 10, 10],
            "close_ret_after_10_pct": [1.0, -1.0, 2.0],
        }
    )
    df["quarter"] = df["date"].dt.to_period("Q")
    quarters = sorted(df["quarter"].unique())
    assert len(quarters) == 3, quarters
    train = df[df["quarter"].isin(quarters[:1])]
    assert len(train) == 1 and train["date"].max() < df[df["quarter"] == quarters[1]]["date"].min()
    assert pd.cut([3.5], BINS, right=False)[0].left == 3
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()
    core = load_core()
    print(f"분석 이벤트 {len(core):,}건  {core['date'].min().date()} ~ {core['date'].max().date()}"
          f"  ({core['quarter'].nunique()}분기)\n")
    fixed_rule(core)
    anchored_walkforward(core)
    band_rank_stability(core)
    combined(core)
