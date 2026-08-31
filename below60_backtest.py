"""코스피 15분 60선 아래인 날만 골라 매매하면 어떤가.

    python below60_backtest.py                # 10:00 진입
    SCAN_CUTOFF=0930 python below60_backtest.py   # 09:30 진입

below60_traits.py에서 나온 60선 아래 클린20의 특징(갭 크고, 저가주, 대금 3배, 15분 만에
도달)을 진입 규칙으로 바꿔 실제 손익을 잰다. 60선 판정은 진입 시각 이전에 닫힌 15분봉
까지만 써서 룩어헤드가 없다.
"""
import os
import sys
from itertools import product

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pullback_ladder_backtest as L
from clean20_conditions import wilson
from clean20_report import kospi_above_60

TRAILS = [3.0, 4.0, 5.0, 7.0, 10.0]
CACHE = f"results/below60_trades{'' if os.environ.get('SCAN_CUTOFF','1000')=='1000' else '_0930'}.csv"
KEEP = ["open_gap_pct", "ret_at_10_pct", "value_vs_20d_avg", "high_vs_20d_high_pct",
        "max_dd_to_10_pct", "pos_in_range_10", "first5_value_share", "price_log",
        "cum_value_eok", "rank_10am"]


def below60_by_day() -> pd.Series:
    """진입 시각 이전에 닫힌 15분봉 기준 '60선 아래' 여부. 09:45봉은 09:59에 확정되므로
    10:00 진입이면 그게 마지막, 09:30 진입이면 09:15봉이 마지막이다."""
    above = kospi_above_60().dropna()
    cut = pd.Timestamp(f"{L._CUT[:2]}:{L._CUT[2:]}").time()
    a = above[above.index.time < cut]
    return ~a.groupby(a.index.normalize()).last().astype(bool)


def trades() -> pd.DataFrame:
    if os.path.exists(CACHE):
        return pd.read_csv(CACHE, parse_dates=["date"], dtype={"code": str})

    L.DAY_PEAK, L.DAY_CUT, L.KDQ_MIN, L.KDQ_930, L.RULE4 = True, 0.0, 0.0, 0.0, False
    cand = L.candidates()                       # 3배제까지 적용된 모집단
    plan = L.PLANS[L.ENTRY_PLAN]
    rows = []
    for code, g in cand.groupby("stock_code"):
        path = os.path.join(L.MINUTE_DIR, f"{code}.csv")
        if not os.path.exists(path):
            continue
        minute = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
        keep = g.set_index("date")
        for date, bars in minute.groupby(minute.index.normalize()):
            if date not in keep.index:
                continue
            r = {"date": date, "code": code}
            for t in TRAILS:
                out = L.simulate(bars, plan, t)
                r[f"t{t:g}"] = np.nan if out is None else out[0]
            row = keep.loc[date]
            for c in KEEP:
                r[c] = float(row[c])
            rows.append(r)

    t = pd.DataFrame(rows).dropna(subset=["t5"])
    # map은 object dtype을 돌려줘서 ~ 연산이 비트반전(-1/-2)이 된다 - bool로 캐스팅 필수
    t["below60"] = t["date"].map(below60_by_day()).fillna(False).astype(bool)
    t["price"] = 10 ** t["price_log"]
    t.to_csv(CACHE, index=False, encoding="utf-8-sig")
    return t


def line(label: str, r: pd.Series) -> None:
    if len(r) == 0:
        print(f"{label:>26}{0:>7}")
        return
    lo, hi = wilson(int((r > 0).sum()), len(r))
    print(f"{label:>26}{len(r):>7}{r.mean():>8.2f}%{(r > 0).mean()*100:>7.0f}%"
          f"{r.sum():>8.0f}%{f'[{lo:.0f}-{hi:.0f}]':>11}")


def main() -> None:
    t = trades()
    lo, up = t[t["below60"]], t[~t["below60"]]
    print("=" * 76)
    print(f"60선 아래 매매  |  진입 {L._CUT[:2]}:{L._CUT[2:]} · 후보 {len(t)}건 "
          f"(아래 {len(lo)} · 위 {len(up)})")
    print("=" * 76)

    print(f"\n[1] 60선 위/아래 그대로 비교")
    print(f"{'':>26}{'건수':>7}{'건당':>8}{'승률':>7}{'누적':>8}{'승률CI':>11}")
    for tr in TRAILS:
        c = f"t{tr:g}"
        line(f"아래 -{tr:g}%", lo[c])
        line(f"위   -{tr:g}%", up[c])
    if len(lo) == 0:
        return

    best = max(TRAILS, key=lambda tr: lo[f"t{tr:g}"].sum())
    col = f"t{best:g}"
    print(f"\n[2] 60선 아래 + 특징 필터 하나씩 (트레일 -{best:g}%)")
    print(f"{'':>26}{'건수':>7}{'건당':>8}{'승률':>7}{'누적':>8}{'승률CI':>11}")
    line("없음", lo[col])
    filters = {
        "시가갭 >=4%": lo["open_gap_pct"] >= 4,
        "시가갭 >=6%": lo["open_gap_pct"] >= 6,
        "주가 <2만원": lo["price"] < 20000,
        "주가 <3만원": lo["price"] < 30000,
        "대금 >=20일평균 2.5배": lo["value_vs_20d_avg"] >= 2.5,
        "대금 >=20일평균 3배": lo["value_vs_20d_avg"] >= 3,
        "20일고가 +10% 이상": lo["high_vs_20d_high_pct"] >= 10,
        "레인지 위치 >=0.8": lo["pos_in_range_10"] >= 0.8,
        "등락률 >=10%": lo["ret_at_10_pct"] >= 10,
    }
    for label, m in filters.items():
        line(label, lo.loc[m, col])

    print(f"\n[3] 조합 (트레일 -{best:g}%)")
    print(f"{'':>26}{'건수':>7}{'건당':>8}{'승률':>7}{'누적':>8}{'승률CI':>11}")
    g46 = lo["open_gap_pct"] >= 4
    p2 = lo["price"] < 20000
    v25 = lo["value_vs_20d_avg"] >= 2.5
    for label, m in {"갭>=4 + 저가주": g46 & p2,
                     "갭>=4 + 대금>=2.5": g46 & v25,
                     "저가주 + 대금>=2.5": p2 & v25,
                     "셋 다": g46 & p2 & v25}.items():
        line(label, lo.loc[m, col])

    print(f"\n[4] 같은 조합을 60선 '위'에 걸면 (대조군, 트레일 -{best:g}%)")
    print(f"{'':>26}{'건수':>7}{'건당':>8}{'승률':>7}{'누적':>8}{'승률CI':>11}")
    line("갭>=4 + 대금>=2.5", up.loc[(up["open_gap_pct"] >= 4) & (up["value_vs_20d_avg"] >= 2.5), col])
    line("전체", up[col])


def demo() -> None:
    """below60은 '위' 판정의 반대여야 한다 - 부호가 뒤집히면 결론이 정반대가 된다."""
    a = pd.Series([True, False], index=pd.to_datetime(["2026-01-02", "2026-01-05"]))
    assert (~a).tolist() == [False, True]
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
