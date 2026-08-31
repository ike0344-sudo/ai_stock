"""거래대금이 분산되면 못 가는가 - 집중도 검증.

가설: 그날 대금이 한 종목에 쏠리면 가고, top20에 고르게 퍼지면 아무도 못 간다.

    python clean20_concentration.py

절대 대금(cum_value_eok)은 이미 AUC 0.477로 무의미하다고 나왔다. 여기서 보는 건
'그날 대금 풀에서 이 종목이 몇 %를 먹었나'라는 상대 몫과, 하루 전체의 쏠림 정도다.
1차 관문(10시 등락률>=7% & 레인지 위치>=0.8, 클린20 24%)을 통과한 뒤에도 갈리는지가
핵심 - 거기서 안 갈리면 집중도는 이야깃거리일 뿐 매매 규칙이 못 된다.
"""
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import auc, load, wilson

MAX_GAP = 15.0
# 대금 상위에 상시 상주하는 대형주 - 클린20을 거의 안 만들면서 쏠림 지표만 왜곡한다.
# 이름을 박지 않고 "몇 %의 날에 top20으로 등장했나"로 잡는다.
RESIDENT_PCT = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--resident=")), 20))


def residents(df: pd.DataFrame) -> pd.Index:
    freq = df.groupby("stock_code")["date"].nunique() / df["date"].nunique() * 100
    return freq[freq >= RESIDENT_PCT].index


def add_shares(df: pd.DataFrame) -> pd.DataFrame:
    """종목별 '그날 top20 대금 합에서 차지하는 몫'과 하루 집중도 지표."""
    total = df.groupby("date")["cum_value_eok"].transform("sum")
    df["share"] = df["cum_value_eok"] / total
    df["share_vs_top1"] = df["cum_value_eok"] / df.groupby("date")["cum_value_eok"].transform("max")

    day = df.groupby("date").apply(lambda g: pd.Series({
        "total_eok": g["cum_value_eok"].sum(),
        "top1_share": g["share"].max(),
        "top3_share": g["share"].nlargest(3).sum(),
        "hhi": (g["share"] ** 2).sum(),
    }), include_groups=False)
    return df.join(day, on="date")


def quintiles(df: pd.DataFrame, col: str, name: str, target: str, unit: str = "") -> None:
    q = pd.qcut(df[col], 5, duplicates="drop")
    base = df[target].mean()
    print(f"\n{name}")
    print(f"{'구간':>24}{'n':>7}{'적중':>7}{'비율':>8}{'배수':>8}{'95% CI':>13}")
    for b, g in df.groupby(q, observed=True):
        k, n = int(g[target].sum()), len(g)
        lo, hi = wilson(k, n)
        print(f"{f'{b.left:.3g} ~ {b.right:.3g}{unit}':>24}{n:>7}{k:>7}{k/n*100:>7.1f}%"
              f"{k/n/base:>7.2f}x{f'[{lo:.0f}-{hi:.0f}]':>13}")


def report() -> None:
    df = add_shares(load())
    df["case"] = df["clean"] & (df["open_gap_pct"] < MAX_GAP)

    day = df.groupby("date").agg(hit=("case", "any"), **{
        c: (c, "first") for c in ["total_eok", "top1_share", "top3_share", "hhi"]})
    print("=" * 74)
    print(f"거래대금 집중도와 클린20  |  {len(day)}거래일 · top20 종목-일자 {len(df):,}건")
    print("=" * 74)
    print(f"기준선: 케이스 나온 날 {day['hit'].mean()*100:.0f}% · 종목 단위 클린20 {df['case'].mean()*100:.2f}%")

    print("\n" + "-" * 74)
    print("[1] 하루 단위 - 쏠린 날에 케이스가 나오나")
    print("-" * 74)
    for col, name, unit in [("top1_share", "1위 대금 몫(top20 합 대비)", ""),
                            ("top3_share", "상위 3종목 몫", ""),
                            ("hhi", "HHI(몫 제곱합, 클수록 쏠림)", ""),
                            ("total_eok", "top20 대금 총합(억)", "")]:
        quintiles(day, col, name, "hit", unit)

    print("\n" + "-" * 74)
    print("[2] 종목 단위 - 그날 대금 풀에서 자기 몫")
    print("-" * 74)
    live = df[~df["already_20_by_10"]]
    for col, name in [("share", "자기 대금 몫"), ("share_vs_top1", "1위 대비 대금 비율")]:
        quintiles(live, col, name, "case")
    print(f"\n{'AUC':>24}{'':>7}")
    for col, name in [("share", "자기 대금 몫"), ("share_vs_top1", "1위 대비 대금 비율"),
                      ("cum_value_eok", "절대 대금(억)"), ("hhi", "그날 HHI"),
                      ("top1_share", "그날 1위 몫")]:
        print(f"{name:>24}{auc(live[live['case']][col], live[~live['case']][col]):>8.3f}")

    print("\n" + "-" * 74)
    print("[3] 1차 관문 통과(10시 등락>=7% & 레인지>=0.8) 이후에도 갈리나  <- 핵심")
    print("-" * 74)
    gate = live[(live["ret_at_10_pct"] >= 7) & (live["pos_in_range_10"] >= 0.8)]
    print(f"관문 통과 {len(gate)}건 중 클린20 {int(gate['case'].sum())}건 = {gate['case'].mean()*100:.1f}%")
    for col, name in [("share", "자기 대금 몫"), ("share_vs_top1", "1위 대비 대금 비율"),
                      ("value_vs_20d_avg", "대금/20일평균"), ("hhi", "그날 HHI"),
                      ("rank_10am", "대금 순위")]:
        quintiles(gate, col, name, "case")

    print("\n" + "-" * 74)
    print("컷별 비교 (관문 통과분에 추가로 걸었을 때)")
    print("-" * 74)
    base = gate["case"].mean()
    print(f"{'추가 컷':>28}{'n':>7}{'클린':>7}{'비율':>8}{'배수':>8}")
    for label, m in {
        "없음(관문만)": pd.Series(True, index=gate.index),
        "대금 1위": gate["rank_10am"] == 1,
        "대금 top3": gate["rank_10am"] <= 3,
        "자기 몫 >= 10%": gate["share"] >= 0.10,
        "1위 대비 >= 50%": gate["share_vs_top1"] >= 0.5,
        "대금/20일평균 >= 1.5": gate["value_vs_20d_avg"] >= 1.5,
        "그날 HHI 상위 절반": gate["hhi"] >= gate["hhi"].median(),
    }.items():
        n, k = int(m.sum()), int(gate.loc[m, "case"].sum())
        print(f"{label:>28}{n:>7}{k:>7}{k/n*100 if n else 0:>7.1f}%{(k/n/base) if n else 0:>7.2f}x")

    resident_report(load())


def resident_report(raw: pd.DataFrame) -> None:
    """상주 대형주를 빼고 다시 잰 쏠림 - '얼마나 쏠려야 가는가'."""
    res = residents(raw)
    names = raw[raw["stock_code"].isin(res)].groupby("stock_code")["name"].first()
    df = add_shares(raw[~raw["stock_code"].isin(res)].copy())
    df["case"] = df["clean"] & (df["open_gap_pct"] < MAX_GAP)
    day = df.groupby("date").agg(hit=("case", "any"), n_case=("case", "sum"), **{
        c: (c, "first") for c in ["total_eok", "top1_share", "top3_share", "hhi"]})

    print("\n" + "=" * 74)
    print(f"[4] 상주 대형주 {len(res)}종목 제외 후 다시 잰 쏠림 (등장률 >= {RESIDENT_PCT:g}%)")
    print("=" * 74)
    print("제외: " + ", ".join(names.tolist()))
    print(f"남은 풀 {len(df):,}건 · 하루 평균 {len(df)/len(day):.1f}종목 · "
          f"케이스 {int(df['case'].sum())}건 · 케이스 나온 날 {day['hit'].mean()*100:.0f}%")

    for col, name in [("top1_share", "1위 대금 몫(풀 합 대비)"), ("hhi", "HHI"),
                      ("top3_share", "상위 3종목 몫")]:
        quintiles(day, col, name, "hit")

    print("\n실제로 간 종목이 그날 풀에서 먹은 몫")
    print(f"{'':>24}{'n':>7}{'중앙':>9}{'25%':>9}{'75%':>9}")
    for label, g in [("클린20 종목", df[df["case"]]),
                     ("관문통과 실패", df[(df["ret_at_10_pct"] >= 7)
                                     & (df["pos_in_range_10"] >= 0.8) & ~df["case"]])]:
        q = g["share"].quantile([0.25, 0.5, 0.75])
        print(f"{label:>24}{len(g):>7}{q[0.5]*100:>8.1f}%{q[0.25]*100:>8.1f}%{q[0.75]*100:>8.1f}%")

    # 대형주가 그날 top10 대금을 얼마나 빨아갔나 - 나머지가 마르는지 직접 본다
    tot = raw.groupby("date")["cum_value_eok"].sum()
    res_share = raw[raw["stock_code"].isin(res)].groupby("date")["cum_value_eok"].sum() / tot
    day["res_share"] = day.index.map(res_share).fillna(0)
    quintiles(day, "res_share", "상주 대형주가 먹은 대금 비중", "hit")

    print("\n1위 몫 구간별 - 그날 케이스 건수까지")
    print(f"{'1위 몫':>16}{'일수':>7}{'적중일':>8}{'비율':>8}{'케이스':>8}{'일당':>8}")
    for lo, hi in [(0, .25), (.25, .30), (.30, .35), (.35, .40), (.40, 1)]:
        m = (day["top1_share"] >= lo) & (day["top1_share"] < hi)
        n = int(m.sum())
        if not n:
            continue
        k, c = int(day.loc[m, "hit"].sum()), int(day.loc[m, "n_case"].sum())
        print(f"{f'{lo*100:.0f}~{hi*100:.0f}%':>16}{n:>7}{k:>8}{k/n*100:>7.0f}%{c:>8}{c/n:>8.2f}")


def demo() -> None:
    """share/HHI 계산 검증 - 하루 두 종목이 3:1이면 몫은 0.75/0.25, HHI는 0.625."""
    d = pd.DataFrame({"date": [pd.Timestamp("2026-01-02")] * 2, "cum_value_eok": [300.0, 100.0]})
    out = add_shares(d)
    assert list(out["share"].round(4)) == [0.75, 0.25], out["share"].tolist()
    assert list(out["share_vs_top1"].round(4)) == [1.0, 0.3333]
    assert abs(out["hhi"].iloc[0] - 0.625) < 1e-9, out["hhi"].iloc[0]
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        report()
