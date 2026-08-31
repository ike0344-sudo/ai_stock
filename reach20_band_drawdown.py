"""대금순위 top10 + 당일 +20% 도달 종목의 "가격 구간별" 조정 깊이 통계 (손절선 산정용).

reach20_path_drawdown.py와 같은 모집단이지만 조정을 전일比 가격 밴드로 나눠 본다.
기본 밴드: 전일比 +7~17%, +14~24%. (조정 에피소드의 시작 고점이 밴드 안이면 그 밴드 소속)

조정 에피소드 = 러닝 고점에서 밀렸다가 그 고점을 다시 넘을 때까지의 1구간.
마지막에 고점 갱신 없이 끝난 미완성 구간도 포함(회복 실패로 표시).

두 가지 범위를 각각 낸다:
  경로  = 09:00 ~ 최초 +20% 터치 (아직 안 팔았을 때 견뎌야 하는 조정)
  전일  = 09:00 ~ 장 마감 (+20% 이후 되밀림까지 포함, +20~24% 밴드는 여기서만 관측됨)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FEATURES_CSV = "results/reach20_features.csv"
MINUTE_DIR = "data/stocks/minute"
DAILY_DIR = "data/stocks/daily"
TOP_N = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--top=")), 10))
BANDS = [tuple(map(float, b.split("-"))) for b in
         next((a.split("=")[1] for a in sys.argv if a.startswith("--bands=")), "7-17,14-24").split(",")]
OUT = f"results/reach20_band_episodes_top{TOP_N}.csv"
EPISODE_MIN = 1.0  # 이보다 얕은 흔들림은 1분봉 노이즈로 보고 세지 않는다
STOPS = (2, 3, 4, 5, 7, 10)


def episodes(bars: pd.DataFrame, pc: float) -> list[dict] | None:
    """당일 전체 경로의 조정 에피소드. +20% 미달이면 None."""
    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()
    hit = np.flatnonzero(high >= pc * 1.20)
    if hit.size == 0:
        return None
    t20 = int(hit[0])

    out = []
    # 신고가 봉의 저가로 trough를 채우면 그 봉 자체 range가 가짜 조정이 된다 -> 고점 이후 봉만 본다.
    peak, trough, trough_i = high[0], high[0], 0

    def push(recovered: bool) -> None:
        depth = (peak - trough) / peak * 100
        if depth >= EPISODE_MIN:
            out.append({
                "depth_pct": depth,
                "peak_lv_pct": (peak / pc - 1) * 100,
                "trough_lv_pct": (trough / pc - 1) * 100,
                "trough_time": bars.index[trough_i].strftime("%H:%M"),
                "recovered": recovered,
                "before_20": trough_i <= t20,
            })

    for i in range(1, len(high)):
        if low[i] < trough:
            trough, trough_i = low[i], i
        if high[i] > peak:
            push(True)
            peak, trough, trough_i = high[i], high[i], i
    push(False)
    return out


def build() -> pd.DataFrame:
    feat = pd.read_csv(FEATURES_CSV, parse_dates=["date"], dtype={"stock_code": str})
    feat = feat[feat["rank_10am"] <= TOP_N]
    print(f"대금 top{TOP_N} 종목-일자 {len(feat):,}건 스캔", file=sys.stderr)

    rows = []
    n_codes = feat["stock_code"].nunique()
    for i, (code, g) in enumerate(feat.groupby("stock_code"), 1):
        print(f"\r[{i}/{n_codes}] {code}", end="", file=sys.stderr)
        dpath, mpath = os.path.join(DAILY_DIR, f"{code}.csv"), os.path.join(MINUTE_DIR, f"{code}.csv")
        if not (os.path.exists(dpath) and os.path.exists(mpath)):
            continue
        prev_close = pd.read_csv(dpath, index_col=0, parse_dates=True).sort_index()["close"].shift(1)
        minute = pd.read_csv(mpath, index_col=0, parse_dates=True).sort_index()

        wanted = dict(zip(g["date"], g["name"]))
        for date, bars in minute.groupby(minute.index.normalize()):
            if date not in wanted or date not in prev_close.index:
                continue
            pc = prev_close.loc[date]
            if pd.isna(pc) or pc <= 0:
                continue
            eps = episodes(bars, float(pc))
            if not eps:
                continue
            for e in eps:
                rows.append({"date": date, "stock_code": code, "name": wanted[date], **e})
    print(file=sys.stderr)
    return pd.DataFrame(rows)


def qline(label: str, s: pd.Series) -> None:
    s = s.dropna()
    if s.empty:
        print(f"{label:>22}      (표본 없음)")
        return
    print(f"{label:>22}" + "".join(f"{s.quantile(q):>9.1f}%" for q in (0.10, 0.25, 0.50, 0.75, 0.90))
          + f"{s.mean():>9.1f}%{s.max():>9.1f}%")


def band_report(ep: pd.DataFrame, n_cases: int, lo: float, hi: float, scope: str) -> None:
    b = ep[(ep["peak_lv_pct"] >= lo) & (ep["peak_lv_pct"] < hi)]
    print("\n" + "-" * 96)
    print(f"■ 전일比 +{lo:g}~{hi:g}% 구간의 조정   [{scope}]")
    print("-" * 96)
    if b.empty:
        print("  표본 없음")
        return
    cases = b.groupby(["date", "stock_code"])
    deepest = cases["depth_pct"].max()
    print(f"에피소드 {len(b):,}회 / 이 구간을 지난 케이스 {len(deepest):,}건"
          f" (+20% 달성 {n_cases:,}건의 {len(deepest)/n_cases*100:.0f}%)"
          f" · 케이스당 {len(b)/len(deepest):.1f}회")
    print(f"\n{'':>22}{'10%':>10}{'25%':>10}{'중앙':>10}{'75%':>10}{'90%':>10}{'평균':>10}{'최대':>10}")
    qline("조정 깊이(고점比)", b["depth_pct"])
    qline("케이스별 최대 조정", deepest)
    qline("조정 시작 고점(전일比)", b["peak_lv_pct"])
    qline("조정 저점(전일比)", b["trough_lv_pct"])

    print(f"\n손절 폭별 생존율 (그 구간 고점에서 -X% 손절, 케이스 {len(deepest):,}건 기준)")
    for s in STOPS:
        surv = (deepest <= s).mean() * 100
        print(f"  -{s:>2}% : 생존 {surv:5.1f}%   이탈 {100-surv:5.1f}%")
    rec = b["recovered"].mean() * 100
    print(f"\n조정 후 그 고점을 다시 넘긴 비율 {rec:.1f}%   "
          f"저점 시각 최빈 {b['trough_time'].str[:2].mode().iat[0]}시")


def report(ep: pd.DataFrame) -> None:
    key = ["date", "stock_code"]
    n_cases = ep.groupby(key).ngroups
    print("=" * 96)
    print(f"대금순위 top{TOP_N} & 당일 +20% 도달 종목의 구간별 조정 깊이")
    print("=" * 96)
    print(f"기간   : {ep['date'].min().date()} ~ {ep['date'].max().date()} ({ep['date'].nunique()}일)")
    print(f"케이스 : {n_cases:,}건 ({ep['stock_code'].nunique()}종목), 조정 에피소드 {len(ep):,}회")
    print(f"밴드   : " + ", ".join(f"+{lo:g}~{hi:g}%" for lo, hi in BANDS)
          + "  (조정 시작 고점의 전일比 위치로 분류, 1% 미만 흔들림 제외)")

    for scope, sel in [("경로: 09:00 ~ 최초 +20% 터치", ep[ep["before_20"]]),
                       ("전일: 09:00 ~ 장 마감", ep)]:
        n = sel.groupby(key).ngroups
        print("\n" + "=" * 96)
        print(f"[{scope}]  케이스 {n:,}건")
        print("=" * 96)
        for lo, hi in BANDS:
            band_report(sel, n, lo, hi, scope.split(":")[0])


def demo() -> None:
    """에피소드 검출·밴드 분류 자체검증."""
    idx = pd.date_range("2026-01-02 09:00", periods=7, freq="1min")
    # 전일종가 100: 108고점 -> 104저점(3.70% 조정, peak_lv +8%) -> 신고가 -> 121터치 -> 115되밀림
    bars = pd.DataFrame(
        {"open":  [106, 107, 105, 110, 115, 120, 118],
         "high":  [108, 108, 106, 112, 117, 121, 119],
         "low":   [105, 104, 104, 109, 114, 118, 115],
         "close": [107, 105, 106, 111, 116, 120, 116]},
        index=idx,
    )
    eps = episodes(bars, 100.0)
    assert eps is not None and len(eps) == 2, eps
    first = eps[0]
    assert abs(first["depth_pct"] - (108 - 104) / 108 * 100) < 1e-9, first
    assert abs(first["peak_lv_pct"] - 8.0) < 1e-9 and first["recovered"] and first["before_20"]
    last = eps[1]  # +21% 고점 -> 115 되밀림, 회복 실패, +20% 이후
    assert not last["recovered"] and not last["before_20"], last
    assert abs(last["depth_pct"] - (121 - 115) / 121 * 100) < 1e-9, last
    # 밴드 분류: 7~17에 첫 조정만, 14~24에 마지막 조정만
    df = pd.DataFrame(eps)
    assert ((df["peak_lv_pct"] >= 7) & (df["peak_lv_pct"] < 17)).tolist() == [True, False]
    assert ((df["peak_lv_pct"] >= 14) & (df["peak_lv_pct"] < 24)).tolist() == [False, True]
    assert episodes(bars, 1000.0) is None  # +20% 미달이면 모집단 밖
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()
    if "--reuse" in sys.argv and os.path.exists(OUT):
        ep = pd.read_csv(OUT, parse_dates=["date"], dtype={"stock_code": str})
    else:
        ep = build()
        ep.to_csv(OUT, index=False, encoding="utf-8-sig")
    report(ep)
    print(f"\n원본: {OUT}")
