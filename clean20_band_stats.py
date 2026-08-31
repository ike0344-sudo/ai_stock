"""clean20 목록(낙폭 5% 이내 +20% 도달 184건)의 전일比 0~10% / 10~20% 구간 조정폭.

reach20_band_drawdown.py와 같은 에피소드 정의를 쓰되, 모집단을 표에 실린
케이스로 한정한다. 구간은 조정이 시작된 러닝 고점의 전일比 위치로 나눈다.

경로는 09:00 ~ 최초 +20% 터치까지만 본다(그 뒤 되밀림은 진입 판단과 무관).
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIST_CSV = "results/clean20_dd5_list.csv"
MINUTE_DIR = "data/stocks/minute"
DAILY_DIR = "data/stocks/daily"
EPISODE_MIN = 1.0                      # 1% 미만은 1분봉 노이즈로 보고 제외
BANDS = [(0.0, 10.0), (10.0, 20.0)]
STOPS = (2, 3, 4, 5, 7)


def episodes(bars: pd.DataFrame, pc: float) -> list[dict]:
    """09:00~최초 +20%까지의 조정 에피소드. 고점 갱신으로 한 구간이 닫힌다."""
    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()
    hit = np.flatnonzero(high >= pc * 1.20)
    if hit.size == 0:
        return []
    end = int(hit[0])
    h, l = high[: end + 1], low[: end + 1]

    out = []
    peak, trough, ti = h[0], h[0], 0     # 신고가 봉의 저가는 조정으로 세지 않는다

    def push(recovered: bool) -> None:
        depth = (peak - trough) / peak * 100
        if depth >= EPISODE_MIN:
            out.append({
                "depth_pct": depth,
                "peak_lv_pct": (peak / pc - 1) * 100,
                "trough_lv_pct": (trough / pc - 1) * 100,
                "time": bars.index[ti].strftime("%H:%M"),
                "recovered": recovered,
            })

    for i in range(1, len(h)):
        if l[i] < trough:
            trough, ti = l[i], i
        if h[i] > peak:
            push(True)
            peak, trough, ti = h[i], h[i], i
    push(False)
    return out


def build() -> pd.DataFrame:
    lst = pd.read_csv(LIST_CSV, parse_dates=["date"], dtype={"stock_code": str})
    rows = []
    for i, (code, g) in enumerate(lst.groupby("stock_code"), 1):
        print(f"\r[{i}/{lst['stock_code'].nunique()}] {code}", end="", file=sys.stderr)
        dpath = os.path.join(DAILY_DIR, f"{code}.csv")
        mpath = os.path.join(MINUTE_DIR, f"{code}.csv")
        if not (os.path.exists(dpath) and os.path.exists(mpath)):
            continue
        prev_close = pd.read_csv(dpath, index_col=0, parse_dates=True).sort_index()["close"].shift(1)
        minute = pd.read_csv(mpath, index_col=0, parse_dates=True).sort_index()
        want = dict(zip(g["date"], g["name"]))
        for date, bars in minute.groupby(minute.index.normalize()):
            if date not in want:
                continue
            pc = prev_close.get(date, np.nan)
            if pd.isna(pc) or pc <= 0:
                continue
            for e in episodes(bars, float(pc)):
                rows.append({"date": date, "stock_code": code, "name": want[date], **e})
    print(file=sys.stderr)
    return pd.DataFrame(rows)


def qline(label: str, s: pd.Series) -> None:
    s = s.dropna()
    if s.empty:
        print(f"{label:>22}      (표본 없음)")
        return
    print(f"{label:>22}" + "".join(f"{s.quantile(q):>9.1f}%" for q in (.10, .25, .50, .75, .90))
          + f"{s.mean():>9.1f}%{s.max():>9.1f}%")


def band_report(ep: pd.DataFrame, n_cases: int, lo: float, hi: float) -> None:
    b = ep[(ep["peak_lv_pct"] >= lo) & (ep["peak_lv_pct"] < hi)]
    print("\n" + "-" * 96)
    print(f"■ 전일比 +{lo:g}~{hi:g}% 구간에서 시작된 조정")
    print("-" * 96)
    if b.empty:
        print("  표본 없음")
        return
    deepest = b.groupby(["date", "stock_code"])["depth_pct"].max()
    print(f"에피소드 {len(b):,}회 · 이 구간을 지난 케이스 {len(deepest)}건"
          f" (전체 {n_cases}건의 {len(deepest)/n_cases*100:.0f}%) · 케이스당 {len(b)/len(deepest):.1f}회")
    print(f"\n{'':>22}{'10%':>10}{'25%':>10}{'중앙':>10}{'75%':>10}{'90%':>10}{'평균':>10}{'최대':>10}")
    qline("조정 깊이(고점比)", b["depth_pct"])
    qline("케이스별 최대 조정", deepest)
    qline("조정 시작 고점(전일比)", b["peak_lv_pct"])
    qline("조정 저점(전일比)", b["trough_lv_pct"])
    print(f"\n손절 폭별 생존율 ({len(deepest)}건 기준)")
    print("  " + "   ".join(f"-{s}%: {(deepest <= s).mean()*100:4.0f}%" for s in STOPS))
    print(f"조정 후 그 고점 재돌파 {b['recovered'].mean()*100:.0f}%"
          f" · 저점 시각 최빈 {b['time'].str[:2].mode().iat[0]}시")


def main() -> None:
    ep = build()
    key = ["date", "stock_code"]
    n = ep.groupby(key).ngroups
    print("=" * 96)
    print("표에 실린 케이스의 가격 구간별 조정폭 (09:00 ~ 최초 +20% 터치 경로)")
    print("=" * 96)
    lst = pd.read_csv(LIST_CSV, dtype={"stock_code": str})
    print(f"목록 {len(lst)}건 중 조정 에피소드가 잡힌 케이스 {n}건, 에피소드 {len(ep):,}회")
    print(f"조정 정의: 러닝 고점에서 1% 이상 밀린 구간. 구간 분류는 조정이 시작된 고점의 전일比 위치")

    for lo, hi in BANDS:
        band_report(ep, n, lo, hi)

    print("\n" + "-" * 96)
    print("두 구간 직접 비교 (케이스별 최대 조정)")
    print("-" * 96)
    print(f"{'구간':>12}{'케이스':>8}{'중앙':>9}{'75%':>9}{'90%':>9}{'최대':>9}{'-3%생존':>10}{'-5%생존':>10}")
    for lo, hi in BANDS:
        b = ep[(ep["peak_lv_pct"] >= lo) & (ep["peak_lv_pct"] < hi)]
        if b.empty:
            continue
        d = b.groupby(["date", "stock_code"])["depth_pct"].max()
        print(f"{f'+{lo:g}~{hi:g}%':>12}{len(d):>8}{d.median():>8.1f}%{d.quantile(.75):>8.1f}%"
              f"{d.quantile(.90):>8.1f}%{d.max():>8.1f}%{(d <= 3).mean()*100:>9.0f}%{(d <= 5).mean()*100:>9.0f}%")

    print("\n" + "-" * 96)
    print("5%p 세부 구간")
    print("-" * 96)
    cut = pd.cut(ep["peak_lv_pct"], [0, 5, 10, 15, 20, 100], right=False)
    print(f"{'구간':>12}{'에피소드':>9}{'깊이중앙':>10}{'깊이90%':>10}{'저점중앙(전일比)':>17}")
    for k, g in ep.groupby(cut, observed=True):
        rng = f"{k.left:g}~{k.right:g}%" if k.right <= 20 else f"{k.left:g}%+"
        print(f"{rng:>12}{len(g):>9}{g['depth_pct'].median():>9.1f}%"
              f"{g['depth_pct'].quantile(.90):>9.1f}%{g['trough_lv_pct'].median():>16.1f}%")

    ep.to_csv("results/clean20_band_episodes.csv", index=False, encoding="utf-8-sig")
    print("\n원본: results/clean20_band_episodes.csv")


def demo() -> None:
    """에피소드 검출 자체검증."""
    idx = pd.date_range("2026-01-02 09:00", periods=7, freq="1min")
    bars = pd.DataFrame(
        {"open": [103, 104, 102, 106, 110, 115, 119],
         "high": [105, 105, 103, 108, 112, 117, 121],
         "low": [102, 101, 101, 105, 109, 114, 118],
         "close": [104, 102, 103, 107, 111, 116, 120]}, idx)
    e = episodes(bars, 100.0)
    assert len(e) == 1, e
    assert abs(e[0]["depth_pct"] - (105 - 101) / 105 * 100) < 1e-9
    assert abs(e[0]["peak_lv_pct"] - 5.0) < 1e-9 and e[0]["recovered"]
    assert episodes(bars, 1000.0) == []          # +20% 미도달이면 경로 없음
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()
    main()
