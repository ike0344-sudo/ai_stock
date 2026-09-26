"""ORB x RVOL 연구 — 보조 진단(참고용, 사전등록에 없음, 기각조건 판정에 미사용).

시간대별/거래대금 구간별 성과를 기존 롤링-T0 연구(precursor_master)와 비교하기 위한
탐색적 진단. 이 스크립트의 출력은 최종 채택/기각 판정에 쓰지 않는다.
"""
import sys

import pandas as pd

sys.path.insert(0, ".")
from backtesting.qtai_orb_rvol_analyze import MAIN_HORIZON, split_by_date, summarize  # noqa: E402


def bucket(m):
    if m < 600:
        return "09:15-10:00"
    if m < 660:
        return "10:00-11:00"
    if m < 750:
        return "11:00-12:30"
    if m < 840:
        return "12:30-14:00"
    if m < 900:
        return "14:00-15:00"
    return "15:00-15:30"


def main():
    df = pd.read_csv("results/qtai_orb_rvol_signals.csv", low_memory=False, dtype={"symbol": str})
    sub = df[df["orn"] == 15].copy()
    splits = split_by_date(sub)
    oos = splits["OOS"].copy()
    is_df = splits["IS"]

    oos["time_bucket"] = oos["t0_mod"].apply(bucket)
    rows = []
    for tb, g in oos.groupby("time_bucket"):
        s = summarize(g, MAIN_HORIZON)
        s["bucket"] = tb
        rows.append(s)
    tb_df = pd.DataFrame(rows).sort_values("bucket")
    print("=== OOS 시간대별 (ORN=15, 60분 horizon) ===")
    print(tb_df[["bucket", "n", "win_rate", "mean_gross", "mean_net"]].to_string(index=False))

    qs = is_df["cum_value_today"].quantile([0.25, 0.5, 0.75]).to_numpy()
    print(f"\nIS 거래대금 quantile 경계(원): {qs}")

    def qbucket(v):
        if v <= qs[0]:
            return "Q1(최소)"
        if v <= qs[1]:
            return "Q2"
        if v <= qs[2]:
            return "Q3"
        return "Q4(최대)"

    oos["value_q"] = oos["cum_value_today"].apply(qbucket)
    rows = []
    for vb, g in oos.groupby("value_q"):
        s = summarize(g, MAIN_HORIZON)
        s["bucket"] = vb
        rows.append(s)
    vb_df = pd.DataFrame(rows).sort_values("bucket")
    print("\n=== OOS 거래대금 구간별 (IS 경계 기준, ORN=15) ===")
    print(vb_df[["bucket", "n", "win_rate", "mean_gross", "mean_net"]].to_string(index=False))

    print("\nrvol_norm describe (전체 신호):")
    print(df["rvol_norm"].describe())
    print("\nor_range_pct describe (전체 신호):")
    print(df["or_range_pct"].describe())

    print("\nrvol_norm과 60분 gross수익 Spearman IC(ORN=15, IS):")
    ic = is_df["rvol_norm"].corr(is_df["ret_60m"], method="spearman")
    print(f"  IS: {ic:.4f}")
    ic_oos = splits["OOS"]["rvol_norm"].corr(splits["OOS"]["ret_60m"], method="spearman")
    print(f"  OOS: {ic_oos:.4f}")
    ic_or = is_df["or_range_pct"].corr(is_df["ret_60m"], method="spearman")
    print(f"  or_range_pct IS: {ic_or:.4f}")


if __name__ == "__main__":
    main()
