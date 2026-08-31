"""경로 최대낙폭이 임계값 이내인 +20% 도달 케이스 목록.

python clean20_list.py --dd=4.5          # <=4.5%
python clean20_list.py --dd=4.5 --band=4 # 4~4.5% 구간만
python clean20_list.py --dd=4.5 --late   # 10시 이후 도달(매수 판단 가능)만
python clean20_list.py --dd=4.5 --all    # 갭 직행 포함 전부
python clean20_list.py --maxgap=99       # 시가갭 상한 해제
"""
import os
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import load

DD = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--dd=")), 4.5))
BAND = next((float(a.split("=")[1]) for a in sys.argv if a.startswith("--band=")), None)
MAX_GAP = next((float(a.split("=")[1]) for a in sys.argv if a.startswith("--maxgap=")), 15.0)
MIN_MINUTES = 3  # 갭으로 09:03 이내 직행 = 경로 없음


FEATURES_0930 = "results/reach20_features_0930.csv"


def ret_at_0930(d: pd.DataFrame) -> pd.Series:
    """09:30 시점 등락률(전일종가 대비). reach20_condition_scan을 SCAN_CUTOFF=0930으로
    돌려 만든 파일에서 (날짜, 종목)으로 붙인다. 09:30 대금 top20에 없던 종목은 값이
    없는데, 그때는 확인 불가이므로 조건 미달로 본다(NaN >= 7 은 False)."""
    if not os.path.exists(FEATURES_0930):
        return pd.Series(float("nan"), index=d.index)
    f = pd.read_csv(FEATURES_0930, parse_dates=["date"], dtype={"stock_code": str})
    f = f[f["rank_10am"] <= 20]
    m = dict(zip(zip(f["date"], f["stock_code"]), f["ret_at_10_pct"]))
    return pd.Series([m.get(k, float("nan")) for k in zip(d["date"], d["stock_code"])],
                     index=d.index)


def day_close_ret(d: pd.DataFrame) -> pd.Series:
    """전일종가 대비 당일 종가 등락률. 일봉에서 직접 읽는다."""
    out = pd.Series(index=d.index, dtype=float)
    for code, g in d.groupby("stock_code"):
        path = os.path.join("data/stocks/daily", f"{code}.csv")
        if not os.path.exists(path):
            continue
        daily = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
        ret = (daily["close"] / daily["close"].shift(1) - 1) * 100
        out.loc[g.index] = g["date"].map(ret).values
    return out


def select(dd: float = DD, band: float | None = BAND,
           max_gap: float = MAX_GAP) -> tuple[pd.DataFrame, int]:
    """조건에 맞는 케이스와, 시가갭 상한으로 제외된 건수를 반환한다.
    clean20_report.py가 같은 모집단으로 HTML을 굽기 위해 main()에서 떼어냈다."""
    df = load()
    d = df[df["reached"] & (df["max_dd_pct"] <= dd)].copy()
    if band is not None:
        d = d[d["max_dd_pct"] > band]
    # 갭이 이만큼 뜨면 시초에 이미 +20% 근처라 경로가 없다 - 손절선 근거로 못 쓴다
    n_gap = int((d["open_gap_pct"] >= max_gap).sum())
    d = d[d["open_gap_pct"] < max_gap]
    d["real"] = d["minutes_to_20"] > MIN_MINUTES
    d["late"] = d["real"] & (d["t20_time"] > "10:00")
    # 1번 조건만 09:30 기준 - 10시엔 이미 많이 오른 뒤라 변별력이 떨어진다는 판단.
    # 나머지 셋(레인지/대금/신고가)은 그대로 10:00 확정값이다.
    d["ret_at_0930_pct"] = ret_at_0930(d)
    d["rule4"] = ((d["ret_at_0930_pct"] >= 7) & (d["pos_in_range_10"] >= 0.8)
                  & (d["value_vs_20d_avg"] >= 1.5) & (d["high_vs_20d_high_pct"] >= 0))
    d["close_ret_pct"] = day_close_ret(d)   # 전일종가 대비 당일 종가
    return d, n_gap


def main() -> None:
    d, n_gap = select()
    df = load()
    rng = f"{BAND:g}~{DD:g}%" if BAND is not None else f"<= {DD:g}%"
    print(f"경로 최대낙폭 {rng} & +20% 도달 : {len(d)}건 / 전체 도달 {int(df['reached'].sum())}건"
          f" ({len(d)/df['reached'].sum()*100:.1f}%)")
    print(f"  시가갭 {MAX_GAP:g}% 이상 {n_gap}건 제외 -> {len(d)}건")
    print(f"  갭 직행(경로없음) {int((~d['real']).sum())}건 추가 제외 -> {int(d['real'].sum())}건,"
          f" 그중 10시 이후 도달 {int(d['late'].sum())}건")

    show = d[d["late"]] if "--late" in sys.argv else (d if "--all" in sys.argv else d[d["real"]])
    cols = ["date", "stock_code", "name", "open_gap_pct", "ret_at_10_pct",
            "max_dd_to_10_pct", "max_dd_pct", "close_ret_pct", "t20_time",
            "minutes_to_20", "rank_10am", "rule4"]
    pd.set_option("display.width", 200)
    print()
    print(show[cols].sort_values("date").to_string(
        index=False, formatters={"date": lambda x: x.strftime("%y-%m-%d")},
        float_format=lambda v: f"{v:5.1f}"))

    out = f"results/clean20_dd{DD:g}_list.csv"
    d[cols + ["real", "late"]].sort_values("date", ascending=False).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n종목 빈도: " + "  ".join(f"{n} {c}" for n, c in d[d['real']]['name'].value_counts().head(8).items()))
    print(f"원본: {out}")


if __name__ == "__main__":
    main()
