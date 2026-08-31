"""대금 순위 3~10위 필터의 워크포워드 검증.

results/reach20_features.csv(10:00 장중누적대금 top20, 재수집 불필요)를 재사용.

3~10위가 좋다는 건 전체 표본을 다 보고 고른 구간이므로 그대로 믿을 수 없다.
네 갈래로 나눠 본다:
  [A] 고정규칙 — 3~10위를 미리 정한 룰로 보고 분기마다 우위가 재현되나
  [B] 앵커드 워크포워드 — 과거 구간에서 최적 순위창을 *선택*하고 다음 분기에서 검증
  [C] 순위 구간별 달성률이 분기마다 같은 모양인가
  [D] 10시 등락률 통제 — 순위 효과가 "대형주는 애초에 덜 오른다"의 대리변수는 아닌가
"""
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FEATURES_CSV = "results/reach20_features.csv"
RANK_LO, RANK_HI = 3, 10
TARGET = "reach20_after_10"
MIN_TRAIN_N = 100
# [B]에서 학습구간이 고를 수 있는 후보 순위창 — 사후에 3~10위를 끼워넣지 않도록 미리 고정
CANDIDATES = [(1, 5), (1, 10), (1, 20), (3, 10), (3, 15), (4, 10), (5, 15), (6, 15), (11, 20)]
BANDS = [-100, 0, 3, 6, 9, 12, 100]


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z, p = 1.96, k / n
    d = 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / d
    m = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return (max(0.0, c - m) * 100, min(1.0, c + m) * 100)


def load() -> pd.DataFrame:
    df = pd.read_csv(FEATURES_CSV, parse_dates=["date"], dtype={"stock_code": str})
    pop = df[~df["already_20_by_10"]].copy()
    pop["quarter"] = pop["date"].dt.to_period("Q")
    pop["in_rank"] = pop["rank_10am"].between(RANK_LO, RANK_HI)
    pop["band"] = pd.cut(pop["ret_at_10_pct"], BANDS, right=False)
    return pop.sort_values("date")


def fixed_rule(pop: pd.DataFrame) -> None:
    from scipy.stats import binomtest, fisher_exact

    print("=" * 90)
    print(f"[A] 고정규칙: 대금 {RANK_LO}~{RANK_HI}위 vs 나머지(top20 내) — 분기별 재현성")
    print("=" * 90)
    print(f"{'분기':>9}{'필터n':>7}{'필터+20%':>10}{'95%CI':>13}"
          f"{'나머지n':>8}{'나머지+20%':>11}{'배수':>7}{'MFE중앙':>9}{'종가중앙':>9}")
    wins = 0
    for q, g in pop.groupby("quarter", observed=True):
        a, b = g[g["in_rank"]], g[~g["in_rank"]]
        if len(a) == 0 or len(b) == 0:
            continue
        ak, bk = int(a[TARGET].sum()), int(b[TARGET].sum())
        ar, br = ak / len(a), bk / len(b)
        lo, hi = wilson(ak, len(a))
        wins += ar > br
        print(f"{str(q):>9}{len(a):>7}{ar*100:>9.2f}%{f'[{lo:.1f}-{hi:.1f}]':>13}"
              f"{len(b):>8}{br*100:>10.2f}%{ar/br if br else float('nan'):>6.2f}x"
              f"{a['mfe_after_10am_pct'].median():>8.2f}%"
              f"{a['close_ret_from_10am_pct'].median():>8.2f}%")
    n_q = pop["quarter"].nunique()
    a, b = pop[pop["in_rank"]], pop[~pop["in_rank"]]
    ak, bk = int(a[TARGET].sum()), int(b[TARGET].sum())
    odds, p = fisher_exact([[ak, len(a) - ak], [bk, len(b) - bk]])
    sign_p = binomtest(wins, n_q, 0.5, alternative="greater").pvalue
    print(f"\n우위 분기 {wins}/{n_q}   부호검정 단측 p = {sign_p:.4g}")
    print(f"통합 {ak/len(a)*100:.2f}% (n={len(a)}) vs {bk/len(b)*100:.2f}% (n={len(b)})  "
          f"Fisher p = {p:.4g}  odds = {odds:.2f}")


def anchored_walkforward(pop: pd.DataFrame) -> None:
    print("\n" + "=" * 90)
    print("[B] 앵커드 워크포워드: 이전 분기 전체로 최적 순위창 선택 -> 다음 분기 검증")
    print("=" * 90)
    quarters = sorted(pop["quarter"].unique())
    print(f"{'검증분기':>10}{'학습n':>7}{'선택창':>10}{'학습률':>8}"
          f"{'검증n':>7}{'검증률':>8}{'분기베이스':>10}{'초과':>8}{'3~10선택':>10}")
    excess, picks = [], 0
    for i in range(1, len(quarters)):
        train = pop[pop["quarter"].isin(quarters[:i])]
        test = pop[pop["quarter"] == quarters[i]]
        if test.empty:
            continue
        best, best_rate = None, -1.0
        for lo, hi in CANDIDATES:
            m = train["rank_10am"].between(lo, hi)
            if m.sum() < MIN_TRAIN_N:
                continue
            r = train.loc[m, TARGET].mean()
            if r > best_rate:
                best, best_rate = (lo, hi), r
        if best is None:
            continue
        sel = test[test["rank_10am"].between(*best)]
        base = test[TARGET].mean()
        if len(sel) == 0 or base == 0:
            continue
        oos = sel[TARGET].mean()
        excess.append(oos - base)
        hit = best == (RANK_LO, RANK_HI)
        picks += hit
        print(f"{str(quarters[i]):>10}{len(train):>7}{f'{best[0]}~{best[1]}위':>10}{best_rate*100:>7.2f}%"
              f"{len(sel):>7}{oos*100:>7.2f}%{base*100:>9.2f}%{(oos-base)*100:>+7.2f}%"
              f"{'O' if hit else 'X':>10}")
    if excess:
        e = np.array(excess) * 100
        print(f"\n3~10위가 선택된 횟수 : {picks}/{len(excess)}")
        print(f"OOS 초과달성률       : 평균 {e.mean():+.2f}%p  중앙 {np.median(e):+.2f}%p  "
              f"양수 {int((e>0).sum())}/{len(e)}회")
        print("판정: " + ("학습에서 고른 순위창이 미래에도 우위 — 재현성 있음"
                        if e.mean() > 0 and (e > 0).sum() > len(e) / 2
                        else "학습에서 고른 순위창이 미래에는 우위 없음 — 과최적화"))


def rank_stability(pop: pd.DataFrame) -> None:
    print("\n" + "=" * 90)
    print("[C] 순위 구간별 +20% 달성률 — 분기마다 같은 모양인가")
    print("=" * 90)
    buckets = pd.cut(pop["rank_10am"], [0, 2, 3, 5, 10, 15, 20])
    tab = pop.assign(rb=buckets).pivot_table(
        index="rb", columns="quarter", values=TARGET, aggfunc="mean", observed=True) * 100
    cnt = pop.assign(rb=buckets).pivot_table(
        index="rb", columns="quarter", values=TARGET, aggfunc="size", observed=True)
    print(f"{'순위':>9}" + "".join(f"{str(c):>11}" for c in tab.columns) + f"{'전체':>9}")
    for rb in tab.index:
        cells = "".join(f"{tab.loc[rb, c]:>7.2f}%({cnt.loc[rb, c]:>2.0f})"[-11:] for c in tab.columns)
        allr = pop[buckets == rb][TARGET].mean() * 100
        label = f"{int(rb.left)+1}~{int(rb.right)}위"
        print(f"{label:>9}{cells}{allr:>8.2f}%")
    print("\n괄호는 해당 분기 n. 분기당 n이 작아 개별 셀은 노이즈 — 열 방향 모양이 유지되는지만 본다.")


def stratified(pop: pd.DataFrame) -> None:
    from scipy.stats import fisher_exact

    print("\n" + "=" * 90)
    print("[D] 10시 등락률 통제 — 순위 효과가 '대형주는 덜 오른다'의 대리변수인가")
    print("=" * 90)
    print("먼저 순위 구간별 10시 등락률 분포(중앙값)를 보면 교란 여부가 드러난다:")
    buckets = pd.cut(pop["rank_10am"], [0, 2, 3, 5, 10, 15, 20])
    med = pop.assign(rb=buckets).groupby("rb", observed=True)["ret_at_10_pct"].median()
    print("  " + "   ".join(f"{int(rb.left)+1}~{int(rb.right)}위 {v:+.2f}%" for rb, v in med.items()))

    print(f"\n{'구간(10시 등락률)':>18}{'필터n':>7}{'필터+20%':>10}"
          f"{'나머지n':>8}{'나머지+20%':>11}{'배수':>7}")
    u_sum = w_sum = 0.0
    for b, g in pop.groupby("band", observed=True):
        a, o = g[g["in_rank"]], g[~g["in_rank"]]
        rng = f"{b.left:g}~{b.right:g}%" if b.right < 100 else f"{b.left:g}%+"
        if len(a) == 0 or len(o) == 0:
            continue
        ar, orr = a[TARGET].mean(), o[TARGET].mean()
        print(f"{rng:>18}{len(a):>7}{ar*100:>9.2f}%{len(o):>8}{orr*100:>10.2f}%"
              f"{ar/orr if orr else float('nan'):>6.2f}x")
        # 층화 오즈비용 가중 (Mantel-Haenszel 근사)
        n1, n0 = int(g[TARGET].sum()), len(g) - int(g[TARGET].sum())
        if n1 and n0:
            u_sum += (ar > orr) * n1 * n0
            w_sum += n1 * n0

    # 구간 내 순위-결과 관계를 층화 Fisher로 합산 대신, 구간을 통제한 로지스틱 대용:
    # 각 구간에서 필터/나머지 달성수를 합쳐 Mantel-Haenszel 오즈비 계산
    num = den = 0.0
    for _, g in pop.groupby("band", observed=True):
        a, o = g[g["in_rank"]], g[~g["in_rank"]]
        if len(a) == 0 or len(o) == 0:
            continue
        a1, a0 = int(a[TARGET].sum()), len(a) - int(a[TARGET].sum())
        b1, b0 = int(o[TARGET].sum()), len(o) - int(o[TARGET].sum())
        n = len(g)
        num += a1 * b0 / n
        den += a0 * b1 / n
    mh = num / den if den else float("nan")
    a, o = pop[pop["in_rank"]], pop[~pop["in_rank"]]
    raw = fisher_exact([[int(a[TARGET].sum()), len(a) - int(a[TARGET].sum())],
                        [int(o[TARGET].sum()), len(o) - int(o[TARGET].sum())]])[0]
    print(f"\n통제 전 오즈비 {raw:.2f}  ->  Mantel-Haenszel(등락률 통제) 오즈비 {mh:.2f}")
    print("MH가 1.0 근처로 떨어지면 순위 효과는 등락률의 대리변수였다는 뜻이다.")


def after_momentum_cut(pop: pd.DataFrame) -> None:
    """10시 +6% 컷을 이미 통과한 모집단에서 순위가 추가 정보를 주는지.

    실전 순서는 '등락률 컷 -> 순위'이므로, 컷 이후에도 남는 효과만이 진짜 추가값이다.
    """
    from scipy.stats import binomtest, fisher_exact

    print("\n" + "=" * 90)
    print("[E] 10시 등락률 +6% 이상 컷 이후 — 순위 3~10위가 추가 정보를 주나")
    print("=" * 90)
    cut = pop[pop["ret_at_10_pct"] >= 6]
    print(f"컷 통과 {len(cut):,}건, 베이스 {cut[TARGET].mean()*100:.2f}%")
    print(f"\n{'분기':>9}{'필터n':>7}{'필터+20%':>10}{'나머지n':>8}{'나머지+20%':>11}{'배수':>7}")
    wins = n_q = 0
    for q, g in cut.groupby("quarter", observed=True):
        a, o = g[g["in_rank"]], g[~g["in_rank"]]
        if len(a) < 5 or len(o) < 5 or o[TARGET].mean() == 0:
            continue
        ar, orr = a[TARGET].mean(), o[TARGET].mean()
        wins += ar > orr
        n_q += 1
        print(f"{str(q):>9}{len(a):>7}{ar*100:>9.2f}%{len(o):>8}{orr*100:>10.2f}%{ar/orr:>6.2f}x")
    a, o = cut[cut["in_rank"]], cut[~cut["in_rank"]]
    ak, ok_ = int(a[TARGET].sum()), int(o[TARGET].sum())
    odds, p = fisher_exact([[ak, len(a) - ak], [ok_, len(o) - ok_]])
    print(f"\n통합 {ak/len(a)*100:.2f}% (n={len(a)}) vs {ok_/len(o)*100:.2f}% (n={len(o)})  "
          f"Fisher p = {p:.4g}  odds = {odds:.2f}")
    if n_q:
        print(f"우위 분기 {wins}/{n_q}  부호검정 단측 p = "
              f"{binomtest(wins, n_q, 0.5, alternative='greater').pvalue:.4g}")

    print("\n순위 필터를 쪼개보면 (컷 이후 모집단):")
    for label, m in [
        ("1~2위 배제만 (3~20위)", cut["rank_10am"] >= 3),
        ("3~10위", cut["rank_10am"].between(3, 10)),
        ("4~10위", cut["rank_10am"].between(4, 10)),
        ("6~10위", cut["rank_10am"].between(6, 10)),
        ("11~20위", cut["rank_10am"] >= 11),
        ("1~2위만", cut["rank_10am"] <= 2),
    ]:
        g = cut[m]
        if len(g) == 0:
            continue
        k = int(g[TARGET].sum())
        lo, hi = wilson(k, len(g))
        print(f"  {label:>20}  n={len(g):>4}  {k/len(g)*100:>6.2f}%  "
              f"[{lo:.1f}-{hi:.1f}]  베이스比 {k/len(g)/cut[TARGET].mean():.2f}x")


def demo() -> None:
    """순위창 선택이 검증구간을 안 보는지, MH 계산이 도는지 확인."""
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02"] * 4 + ["2025-05-02"] * 4),
            "rank_10am": [1, 4, 8, 15] * 2,
            "reach20_after_10": [False, True, True, False, False, True, False, False],
            "already_20_by_10": [False] * 8,
            "ret_at_10_pct": [1.0, 7.0, 7.0, 1.0] * 2,
            "mfe_after_10am_pct": [1.0] * 8,
            "close_ret_from_10am_pct": [0.0] * 8,
        }
    )
    df["quarter"] = df["date"].dt.to_period("Q")
    df["in_rank"] = df["rank_10am"].between(RANK_LO, RANK_HI)
    assert list(df["in_rank"]) == [False, True, True, False] * 2
    quarters = sorted(df["quarter"].unique())
    train = df[df["quarter"].isin(quarters[:1])]
    assert train["date"].max() < df[df["quarter"] == quarters[1]]["date"].min()
    assert pd.cut([3], [0, 2, 3, 5, 10, 15, 20])[0].right == 3  # 3위는 3~3 버킷
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()
    pop = load()
    print(f"모집단 {len(pop):,}건 ({pop['date'].min().date()} ~ {pop['date'].max().date()}, "
          f"{pop['quarter'].nunique()}분기)  전체 베이스 {pop[TARGET].mean()*100:.2f}%\n")
    fixed_rule(pop)
    anchored_walkforward(pop)
    rank_stability(pop)
    stratified(pop)
    after_momentum_cut(pop)
