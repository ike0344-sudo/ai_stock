"""조정 한 번이 끝나는 데(러닝 고점 -> 조정 -> 그 고점 재돌파) 몇 분 걸렸나.

reach20_path_drawdown.py는 조정의 *깊이*만 재고 시간은 안 남긴다. 여기서는 같은
에피소드 정의를 쓰되 세 구간의 소요 시간을 잰다.

    고점 --(하락)--> 저점 --(반등)--> 고점 재돌파
    |___________ 왕복 ___________|

"1분봉에서 고가갱신" = 조정 시작 고점을 다시 넘은 첫 봉. 재돌파에 실패한 채 경로가
끝나는 구간은 애초에 에피소드로 안 잡히므로(walk_path와 동일) 전부 완결된 조정이다.

경로는 09:00 ~ 최초 +20% 터치까지만 본다. 봉 간격은 인덱스 차가 아니라 타임스탬프
차로 잰다 - 거래 없는 분은 1분봉이 통째로 빠져 있어서 인덱스로 세면 짧게 나온다.

    python pullback_recovery_minutes.py            # 리포트 184건 기준
    python pullback_recovery_minutes.py --all      # +20% 도달 전체로 넓혀서 비교
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import load
from clean20_list import select

MINUTE_DIR = "data/stocks/minute"
DAILY_DIR = "data/stocks/daily"
EPISODE_MIN = 1.0  # reach20_path_drawdown.py와 동일 - 이보다 얕은 흔들림은 조정이 아님
DEPTH_BANDS = [(1, 2), (2, 3), (3, 5), (5, 99)]
QUANTILES = (0.25, 0.50, 0.75, 0.90)


def episodes(bars: pd.DataFrame, pc: float) -> list[dict]:
    """09:00~최초 +20% 터치 경로에서 조정 에피소드를 시간과 함께 뽑는다.
    walk_path와 같은 규칙: 러닝 고점에서 EPISODE_MIN 이상 밀렸다가 그 고점을 다시
    넘으면 1회. 신고가 봉의 저가는 조정에 안 넣는다(그 1분 안의 왕복일 뿐)."""
    high, low, ts = bars["high"].to_numpy(), bars["low"].to_numpy(), bars.index
    hit = np.flatnonzero(high >= pc * 1.20)
    if hit.size == 0:
        return []
    end = int(hit[0])

    out = []
    peak, peak_i = high[0], 0
    trough, trough_i = peak, 0
    for i in range(1, end + 1):
        if low[i] < trough:
            trough, trough_i = low[i], i
        if high[i] > peak:
            depth = (peak - trough) / peak * 100
            if depth >= EPISODE_MIN:
                minutes = lambda a, b: (ts[b] - ts[a]).total_seconds() / 60
                out.append({
                    "depth_pct": depth,
                    "level_pct": (peak / pc - 1) * 100,  # 조정이 시작된 고점의 전일比 위치
                    "fall_min": minutes(peak_i, trough_i),
                    "rebound_min": minutes(trough_i, i),
                    "round_min": minutes(peak_i, i),
                })
            peak, peak_i = high[i], i
            trough, trough_i = peak, i
    return out


def collect(cases: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for code, g in cases.groupby("stock_code"):
        daily_path = os.path.join(DAILY_DIR, f"{code}.csv")
        minute_path = os.path.join(MINUTE_DIR, f"{code}.csv")
        if not (os.path.exists(daily_path) and os.path.exists(minute_path)):
            continue
        daily = pd.read_csv(daily_path, index_col=0, parse_dates=True).sort_index()
        prev_close = daily["close"].shift(1)
        minute = pd.read_csv(minute_path, index_col=0, parse_dates=True).sort_index()

        for date in g["date"]:
            pc = prev_close.get(date)
            if pd.isna(pc) or not pc:
                continue
            bars = minute[minute.index.normalize() == date]
            if bars.empty:
                continue
            for ep in episodes(bars, float(pc)):
                rows.append({"date": date, "stock_code": code, **ep})
    return pd.DataFrame(rows)


def line(label: str, s: pd.Series) -> None:
    s = s.dropna()
    if s.empty:
        print(f"{label:>26}{'표본 없음':>50}")
        return
    print(f"{label:>26}" + "".join(f"{s.quantile(q):>10.0f}분" for q in QUANTILES)
          + f"{s.mean():>10.1f}분")


def report(ep: pd.DataFrame, cases: pd.DataFrame, label: str) -> None:
    print("=" * 88)
    print(f"조정 -> 고가갱신까지 걸린 시간   [{label}]")
    print("=" * 88)
    days = ep.groupby(["date", "stock_code"]).size()
    print(f"케이스 {len(cases)}건 중 조정이 잡힌 {len(days)}건, 조정 {len(ep)}회"
          f" (케이스당 중앙 {days.median():.0f}회)")
    print(f"기간   {cases['date'].min().date()} ~ {cases['date'].max().date()}")

    print("\n" + "-" * 88)
    print(f"{'':>26}{'25%':>11}{'중앙':>11}{'75%':>11}{'90%':>11}{'평균':>11}")
    print("-" * 88)
    line("고점->저점 (하락)", ep["fall_min"])
    line("저점->재돌파 (반등)", ep["rebound_min"])
    line("고점->재돌파 (왕복)", ep["round_min"])

    print("\n" + "-" * 88)
    print("조정 깊이별 왕복 시간")
    print("-" * 88)
    print(f"{'':>26}{'n':>11}{'중앙':>11}{'75%':>11}{'90%':>11}{'최대':>11}")
    for lo, hi in DEPTH_BANDS:
        s = ep[(ep["depth_pct"] >= lo) & (ep["depth_pct"] < hi)]["round_min"]
        if s.empty:
            continue
        name = f"{lo}~{hi}%" if hi < 99 else f"{lo}% 이상"
        print(f"{name:>26}{len(s):>11}{s.median():>10.0f}분{s.quantile(.75):>10.0f}분"
              f"{s.quantile(.90):>10.0f}분{s.max():>10.0f}분")

    print("\n" + "-" * 88)
    print("조정이 시작된 고점의 전일比 위치별 왕복 시간")
    print("-" * 88)
    print(f"{'':>26}{'n':>11}{'중앙':>11}{'75%':>11}{'90%':>11}{'깊이중앙':>11}")
    for lo, hi in [(0, 10), (10, 15), (15, 20)]:
        s = ep[(ep["level_pct"] >= lo) & (ep["level_pct"] < hi)]
        if s.empty:
            continue
        print(f"{f'+{lo}~{hi}%':>26}{len(s):>11}{s['round_min'].median():>10.0f}분"
              f"{s['round_min'].quantile(.75):>10.0f}분{s['round_min'].quantile(.90):>10.0f}분"
              f"{s['depth_pct'].median():>10.1f}%")

    within = [(3, ), (5, ), (10, ), (20, ), (30, )]
    print("\n" + "-" * 88)
    print("N분 안에 고가갱신이 나온 비율 (누적)")
    print("-" * 88)
    for (n,) in within:
        print(f"{f'{n}분 이내':>26}{(ep['round_min'] <= n).mean() * 100:>10.1f}%"
              f"   (반등 구간만: {(ep['rebound_min'] <= n).mean() * 100:.1f}%)")


def demo() -> None:
    """episodes()가 조정 1회와 그 소요 시간을 제대로 집어내는지 자체검증."""
    idx = pd.date_range("2026-01-02 09:00", periods=6, freq="1min")
    # 100 -> 110(고점) -> 104(저점, -5.5%) -> 111(재돌파) -> 120(+20% 터치)
    bars = pd.DataFrame({"high": [100, 110, 106, 104, 111, 120],
                         "low": [99, 108, 105, 104, 106, 112]}, index=idx)
    eps = episodes(bars, 100.0)
    assert len(eps) == 1, eps
    e = eps[0]
    assert abs(e["depth_pct"] - (110 - 104) / 110 * 100) < 1e-9, e
    assert (e["fall_min"], e["rebound_min"], e["round_min"]) == (2, 1, 3), e
    assert episodes(bars.assign(high=[100] * 6), 100.0) == []   # +20% 미도달이면 빈 목록
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()

    if "--all" in sys.argv:
        df = load()
        cases, label = df[df["reached"]].copy(), "대금 top10 · +20% 도달 전체"
    else:
        cases, _ = select(dd=5.0, max_gap=15.0)
        label = "리포트 게재 케이스(낙폭 5% 이내 · 갭 15% 미만)"
    report(collect(cases), cases, label)
