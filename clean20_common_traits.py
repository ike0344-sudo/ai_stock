"""경로 최대낙폭 <=4%로 +20%까지 간 케이스들의 공통점 추출.

대상은 clean20_conditions의 라벨을 --dd=4로 다시 잡은 것.
갭으로 09:03 이내에 +20%를 찍은 케이스는 "경로"가 없어 낙폭이 0으로 찍히므로 제외한다.

공통점 = 대상군 안에서 몰려 있고(coverage), 비교군에는 덜 나타나는(specificity) 특징.
둘 다 안 보면 "대금 top10은 원래 다 그렇다"를 공통점으로 착각하게 된다.
"""
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import FEATURES, auc, load, wilson

MAX_DD = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--dd=")), 4))
MIN_MINUTES = 3  # 이보다 빨리 +20%면 갭 직행 — 경로 없음

# (컬럼, 표시명, 조건식, 라벨) — 대상군 사분위를 보고 고른 후보 공통점
TRAITS = [
    ("open_gap_pct", "시가 갭", lambda s: (s >= -2) & (s <= 8), "-2 ~ +8%"),
    ("ret_at_10_pct", "10시 등락률", lambda s: s >= 5, ">= 5%"),
    ("pos_in_range_10", "10시 레인지 위치", lambda s: s >= 0.7, ">= 0.7"),
    ("upper_wick_ratio", "10시 윗꼬리", lambda s: s <= 0.3, "<= 0.3"),
    ("max_dd_to_10_pct", "10시까지 눌림", lambda s: s <= 5, "<= 5%"),
    ("first5_value_share", "첫 5분 대금비중", lambda s: s <= 0.15, "<= 0.15"),
    ("value_vs_20d_avg", "대금/20일평균", lambda s: (s >= 1) & (s <= 4), "1 ~ 4배"),
    ("prev_day_ret_pct", "전일 등락률", lambda s: (s >= -3) & (s <= 8), "-3 ~ +8%"),
    ("d5_ret_pct", "최근 5일 수익률", lambda s: s <= 20, "<= 20%"),
    ("high_vs_20d_high_pct", "10시고가/20일고가", lambda s: s >= 0, "돌파"),
    ("atr20_pct", "20일 ATR", lambda s: s <= 10, "<= 10%"),
    ("price_log", "주가", lambda s: s >= np.log10(10000), ">= 1만원"),
]


def dist(label: str, tgt: pd.DataFrame, cmp_: pd.DataFrame) -> None:
    print(f"{'피처':>22}{'AUC':>7}{'25%':>9}{'중앙':>9}{'75%':>9}   |{'비교군 중앙':>11}")
    rows = sorted(FEATURES, key=lambda x: -abs(auc(tgt[x[0]], cmp_[x[0]]) - 0.5))
    for col, name in rows:
        s, c = tgt[col].dropna(), cmp_[col].dropna()
        au = auc(s, c)
        star = " ***" if abs(au - 0.5) >= 0.15 else (" *" if abs(au - 0.5) >= 0.08 else "")
        print(f"{name:>22}{au:>7.3f}{s.quantile(.25):>9.2f}{s.median():>9.2f}"
              f"{s.quantile(.75):>9.2f}   |{c.median():>11.2f}{star}")


def traits(tgt: pd.DataFrame, cmp_: pd.DataFrame, cmp_name: str) -> None:
    print(f"{'공통점 후보':>22}{'조건':>12}{'대상 충족':>10}{'':>2}{cmp_name+' 충족':>12}{'배수':>8}")
    for col, name, fn, cond in TRAITS:
        a, b = fn(tgt[col]).mean() * 100, fn(cmp_[col]).mean() * 100
        mark = " <=" if a >= 80 and a / max(b, 1e-9) >= 1.3 else ""
        print(f"{name:>22}{cond:>12}{a:>9.0f}%{'':>2}{b:>11.0f}%{a/max(b,1e-9):>7.2f}x{mark}")
    print("  <= : 대상군 80% 이상이 충족하면서 비교군 대비 1.3배 이상 — 진짜 공통점")


def main() -> None:
    df = load()
    df["clean4"] = df["reached"] & (df["max_dd_pct"] <= MAX_DD)
    real = df["clean4"] & (df["minutes_to_20"] > MIN_MINUTES)
    tgt = df[real]
    late = df[real & (df["t20_time"] > "10:00")]
    dirty = df[df["reached"] & (df["max_dd_pct"] > MAX_DD)]
    rest = df[~df["reached"]]

    print("=" * 92)
    print(f"경로 최대낙폭 <= {MAX_DD:g}%로 +20% 도달한 케이스의 공통점")
    print("=" * 92)
    print(f"대상   : {len(tgt)}건 (갭 직행 {int((df['clean4'] & ~real).sum())}건 제외)"
          f"  중 10시 이후 도달 {len(late)}건")
    print(f"비교군 : 지저분 도달 {len(dirty)}건 / 미도달 {len(rest):,}건")

    print("\n" + "-" * 92)
    print("[1] 분포 비교 — vs 지저분 도달 (같은 +20%인데 흔들린 케이스)")
    print("-" * 92)
    dist("지저분", tgt, dirty)

    print("\n" + "-" * 92)
    print("[2] 분포 비교 — vs 미도달 (top10에는 들었지만 +20% 못 간 케이스)")
    print("-" * 92)
    dist("미도달", tgt, rest)

    print("\n" + "-" * 92)
    print("[3] 공통점 체크리스트 (대상군 내 충족 비율)")
    print("-" * 92)
    traits(tgt, dirty, "지저분")
    print()
    traits(tgt, rest, "미도달")

    print("\n" + "-" * 92)
    print("[4] 장중 경로의 공통점")
    print("-" * 92)
    for col, name, unit in [("minutes_to_20", "+20%까지 소요", "분"), ("n_ep_ge3", "3%+ 조정 횟수", "회")]:
        s, d = tgt[col], dirty[col]
        print(f"{name:>16} : 대상 중앙 {s.median():>5.0f}{unit} (25~75% {s.quantile(.25):.0f}~{s.quantile(.75):.0f})"
              f"   지저분 중앙 {d.median():>5.0f}{unit}")
    hours = tgt["t20_time"].str[:2].value_counts().sort_index()
    print(f"{'+20% 도달 시각':>16} : " + "  ".join(f"{h}시 {v}건" for h, v in hours.items()))
    print(f"{'요일':>16} : " + "  ".join(
        f"{d} {v}건" for d, v in tgt["date"].dt.strftime("%a").value_counts().items()))

    print("\n" + "-" * 92)
    print("[5] 종목 쏠림 — 이 패턴이 잘 나오는 종목이 따로 있나")
    print("-" * 92)
    top10_days = df.groupby("stock_code").size()
    hits = tgt.groupby("stock_code").size()
    names = df.drop_duplicates("stock_code").set_index("stock_code")["name"]
    tbl = pd.DataFrame({"hits": hits, "top10_days": top10_days}).dropna()
    tbl = tbl[tbl["hits"] >= 2].assign(rate=lambda x: x["hits"] / x["top10_days"] * 100)
    tbl["name"] = names
    print(f"반복 등장 종목 {len(tbl)}개 / 전체 {tgt['stock_code'].nunique()}개 종목")
    print(f"{'종목':>18}{'클린4회':>8}{'top10일':>9}{'비율':>8}")
    for code, r in tbl.sort_values("hits", ascending=False).head(12).iterrows():
        print(f"{r['name']:>18}{int(r['hits']):>8}{int(r['top10_days']):>9}{r['rate']:>7.0f}%")
    base = len(tgt) / len(df) * 100
    print(f"\n전체 기준선 {base:.1f}% (top10 등장일 대비 클린4 발생률)")


def demo() -> None:
    """조건식·집계 자체검증."""
    s = pd.Series([-3.0, 0.0, 5.0, 9.0])
    fn = dict((c, f) for c, _, f, _ in TRAITS)["open_gap_pct"]
    assert fn(s).tolist() == [False, True, True, False]
    assert abs(auc(pd.Series([2, 3]), pd.Series([0, 1])) - 1.0) < 1e-9
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()
    main()
