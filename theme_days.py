"""테마가 형성된 날에 클린20이 잘 나오나.

    python theme_days.py

테마 라벨은 없으니 업종(ka10099의 upName)을 대리 지표로 쓴다 - "로봇"/"전선" 같은
장중 테마와 업종이 정확히 겹치진 않지만, 같은 업종 여러 종목이 동시에 대금 상위에
올라온 날은 대체로 테마가 돈 날이다.

테마 강도 정의(전부 10:00에 확정):
    동반    - 그날 top10에서 한 업종이 차지한 최대 종목 수
    동반강세 - 그 업종 종목 중 10시 등락률 +7% 이상인 수
"""
import os
import sys

import pandas as pd
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import load, wilson
from kiwoom_client import KiwoomClient

SECTOR_CACHE = "data/sectors.csv"
MAX_GAP = 15.0


def sectors(refresh: bool = False) -> pd.Series:
    """종목코드 -> 업종명. ka10099를 거래소/코스닥 두 번 불러 캐시한다."""
    if os.path.exists(SECTOR_CACHE) and not refresh:
        s = pd.read_csv(SECTOR_CACHE, dtype=str)
        return s.set_index("stock_code")["sector"]

    load_dotenv()
    client = KiwoomClient(os.environ["KIWOOM_APPKEY"], os.environ["KIWOOM_SECRETKEY"],
                          is_mock=os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true")
    rows = []
    for market in ("0", "10"):
        for r in client.get_stock_list(market):
            rows.append({"stock_code": r["code"], "sector": r.get("upName") or "기타"})
    df = pd.DataFrame(rows).drop_duplicates("stock_code")
    df.to_csv(SECTOR_CACHE, index=False, encoding="utf-8-sig")
    return df.set_index("stock_code")["sector"]


def build() -> pd.DataFrame:
    df = load()
    df["sector"] = df["stock_code"].map(sectors()).fillna("미상")
    df["case"] = df["clean"] & (df["open_gap_pct"] < MAX_GAP)
    df["strong"] = df["ret_at_10_pct"] >= 7

    # 종목별: 그날 같은 업종 동료가 몇 명 더 있었나 / 그중 강세는 몇 명인가
    grp = df.groupby(["date", "sector"])
    df["peers"] = grp["stock_code"].transform("size") - 1
    df["peers_strong"] = grp["strong"].transform("sum") - df["strong"].astype(int)
    return df


def rate(g: pd.DataFrame, label: str, target: str, base: float) -> None:
    n, k = len(g), int(g[target].sum())
    if n == 0:
        print(f"{label:>22}{0:>7}")
        return
    lo, hi = wilson(k, n)
    print(f"{label:>22}{n:>7}{k:>7}{k/n*100:>7.1f}%{k/n/base:>7.2f}x{f'[{lo:.0f}-{hi:.0f}]':>13}")


def main() -> None:
    df = build()
    day = df.groupby("date").agg(hit=("case", "any"), n_case=("case", "sum"))
    day["max_peers"] = df.groupby(["date", "sector"]).size().groupby("date").max()
    day["max_strong"] = df[df["strong"]].groupby(["date", "sector"]).size().groupby("date").max()
    day["max_strong"] = day["max_strong"].fillna(0)

    print("=" * 72)
    print(f"테마(업종 동반) 형성일과 클린20  |  {len(day)}거래일 · 케이스 {int(day['n_case'].sum())}건")
    print("=" * 72)
    print(f"업종 {df['sector'].nunique()}개 · 미상 {(df['sector'] == '미상').sum()}건")

    base = day["hit"].mean()
    print(f"\n[1] 하루 단위 - 같은 업종이 top10에 몇 개나 올라왔나 (기준선 {base*100:.0f}%)")
    print(f"{'구간':>22}{'일수':>7}{'적중':>7}{'비율':>8}{'배수':>7}{'95%CI':>13}")
    for lo, hi, lab in [(1, 2, "동반 없음(1개)"), (2, 3, "2개 동반"), (3, 4, "3개 동반"), (4, 99, "4개+ 동반")]:
        rate(day[(day["max_peers"] >= lo) & (day["max_peers"] < hi)], lab, "hit", base)
    print()
    for lo, hi, lab in [(0, 1, "강세 동반 0"), (1, 2, "강세 1개"), (2, 3, "강세 2개 동반"), (3, 99, "강세 3개+ 동반")]:
        rate(day[(day["max_strong"] >= lo) & (day["max_strong"] < hi)], lab, "hit", base)

    live = df[~df["already_20_by_10"]]
    b2 = live["case"].mean()
    print(f"\n[2] 종목 단위 - 같은 업종 동료 수 (기준선 {b2*100:.2f}%)")
    print(f"{'구간':>22}{'n':>7}{'클린':>7}{'비율':>8}{'배수':>7}{'95%CI':>13}")
    for lo, hi, lab in [(0, 1, "동료 0"), (1, 2, "동료 1"), (2, 99, "동료 2+")]:
        rate(live[(live["peers"] >= lo) & (live["peers"] < hi)], lab, "case", b2)
    print()
    for lo, hi, lab in [(0, 1, "강세 동료 0"), (1, 2, "강세 동료 1"), (2, 99, "강세 동료 2+")]:
        rate(live[(live["peers_strong"] >= lo) & (live["peers_strong"] < hi)], lab, "case", b2)

    gate = live[(live["ret_at_10_pct"] >= 7) & (live["pos_in_range_10"] >= 0.8)]
    b3 = gate["case"].mean()
    print(f"\n[3] 관문 통과 후에도 갈리나 (관문 {len(gate)}건, 클린 {b3*100:.1f}%)  <- 핵심")
    print(f"{'구간':>22}{'n':>7}{'클린':>7}{'비율':>8}{'배수':>7}{'95%CI':>13}")
    for lo, hi, lab in [(0, 1, "동료 0"), (1, 2, "동료 1"), (2, 99, "동료 2+")]:
        rate(gate[(gate["peers"] >= lo) & (gate["peers"] < hi)], lab, "case", b3)
    print()
    for lo, hi, lab in [(0, 1, "강세 동료 0"), (1, 99, "강세 동료 1+")]:
        rate(gate[(gate["peers_strong"] >= lo) & (gate["peers_strong"] < hi)], lab, "case", b3)

    print("\n[4] 클린20이 많이 나온 업종 (상위 10)")
    s = df.groupby("sector").agg(n=("case", "size"), k=("case", "sum"))
    s = s[s["n"] >= 30].assign(rate=lambda x: x["k"] / x["n"] * 100).sort_values("rate", ascending=False)
    print(f"{'업종':>22}{'등장':>7}{'클린':>7}{'비율':>8}")
    for name, r in s.head(10).iterrows():
        print(f"{name:>22}{int(r['n']):>7}{int(r['k']):>7}{r['rate']:>7.1f}%")


def demo() -> None:
    """peers/peers_strong가 자기 자신을 빼는지 - 안 빼면 동료 0인 종목이 1로 잡힌다."""
    df = pd.DataFrame({"date": [1, 1, 1], "sector": ["A", "A", "B"], "stock_code": list("xyz"),
                       "strong": [True, True, False]})
    grp = df.groupby(["date", "sector"])
    peers = grp["stock_code"].transform("size") - 1
    ps = grp["strong"].transform("sum") - df["strong"].astype(int)
    assert peers.tolist() == [1, 1, 0], peers.tolist()
    assert ps.tolist() == [1, 1, 0], ps.tolist()
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
