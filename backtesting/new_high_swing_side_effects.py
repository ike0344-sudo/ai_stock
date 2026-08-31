"""new_high_swing 가설의 부수효과 검증 — strategy-agent가 가설이 예측하는 부수효과를
정리해 넘긴 것을 여기서 판정한다. 홀드아웃(마지막 20%)은 열지 않는다.

daily_walk_forward.py의 안전한 패턴(_simulate_stock — 종목당 한 번만 시뮬레이션,
IS/OOS나 폴드 경계에서 이중진입/미청산 유실이 없음)을 그대로 재사용한다. 신규
시뮬레이션 로직은 없다 — 여기서 새로 만든 건 진입 시점 피처(변동성 수축비, 거래량비)
추출과 청산 후 조정구간 거래량 관찰뿐이다. grid_search.run_rule_based는 애초 감사에서
찾은 이중진입 버그가 있던 경로라 의도적으로 안 쓴다(지금은 고쳤지만, daily_walk_forward
쪽이 이미 검증된 경로라 그대로 재사용).

실행: python -m backtesting.new_high_swing_side_effects
"""
from datetime import timedelta

import numpy as np
import pandas as pd

from . import daily_walk_forward as dwf
from .strategies.new_high_swing import NewHighSwing
from .strategies.vcp_breakout import VcpBreakout


def _trades_with_entry_index(df: pd.DataFrame, n_day_high: int, entry_start, entry_end, horizon_end) -> list[dict]:
    """NewHighSwing(n_day_high)의 거래 + 진입시점 피처(변동성 수축비, 거래량비) +
    청산까지의 일별 OHLCV(조정구간 거래량 분석용)를 한 종목분 반환."""
    strategy = NewHighSwing()
    trades = dwf._simulate_stock(df, strategy, {"n_day_high": n_day_high}, entry_start, entry_end, horizon_end)

    # VcpBreakout과 완전히 같은 공식(재사용) — "이게 VcpBreakout의 운명을 결정한다"는
    # 판정이므로 내 임의의 변동성 정의가 아니라 VcpBreakout 자신의 정의를 그대로 써야 한다.
    daily_range_pct = (df["high"] - df["low"]) / df["close"]
    short_avg = daily_range_pct.shift(1).rolling(VcpBreakout.CONTRACTION_SHORT_DAYS).mean()
    long_avg = daily_range_pct.shift(1).rolling(VcpBreakout.CONTRACTION_LONG_DAYS).mean()
    contraction_ratio = short_avg / long_avg  # 낮을수록 "수축"

    avg_volume = df["volume"].shift(1).rolling(NewHighSwing.VOLUME_LOOKBACK_DAYS).mean()
    volume_ratio = df["volume"] / avg_volume

    out = []
    for t in trades:
        if t.pnl is None:
            continue
        entry_ts = pd.Timestamp(t.entry_date)
        if entry_ts not in df.index:
            continue
        path = df.loc[str(t.entry_date):str(t.exit_date)]
        if len(path) < 2:
            continue
        running_peak = path["close"].cummax()
        in_pullback = path["close"] < running_peak
        pullback_volume = path.loc[in_pullback, "volume"]
        entry_volume = path["volume"].iloc[0]

        out.append({
            "code": "", "entry_date": t.entry_date, "exit_date": t.exit_date,
            "pnl_pct": t.pnl_pct * 100,
            "contraction_ratio": contraction_ratio.get(entry_ts, np.nan),
            "volume_ratio": volume_ratio.get(entry_ts, np.nan),
            "n_pullback_days": int(in_pullback.sum()),
            "pullback_avg_volume": float(pullback_volume.mean()) if not pullback_volume.empty else np.nan,
            "entry_volume": float(entry_volume),
            "avg_volume_20d": float(avg_volume.get(entry_ts, np.nan)),
        })
    return out


def collect_trades(universe: dict[str, pd.DataFrame], n_day_high: int, entry_start, entry_end, horizon_end) -> pd.DataFrame:
    rows = []
    for code, df in universe.items():
        for r in _trades_with_entry_index(df, n_day_high, entry_start, entry_end, horizon_end):
            r["code"] = code
            rows.append(r)
    return pd.DataFrame(rows)


def side_effect_3_volatility_contraction(trades: pd.DataFrame) -> None:
    """[최우선] 돌파 시점 변동성(수축비)이 낮을수록 성과가 좋아야 한다 — VcpBreakout의
    존재 이유. 중앙값으로 상/하위 분할."""
    t = trades.dropna(subset=["contraction_ratio"])
    median = t["contraction_ratio"].median()
    low = t[t["contraction_ratio"] <= median]   # 수축(변동성 낮음)
    high = t[t["contraction_ratio"] > median]   # 비수축(변동성 높음)

    print("\n=== [최우선] 부수효과3: 변동성 수축(낮을수록 좋아야 함) ===")
    print(f"표본 {len(t)}건, 수축비 중앙값 {median:.3f}")
    print(f"{'구분':10s} {'거래수':>6s} {'승률%':>7s} {'평균%/거래':>10s}")
    for label, g in [("낮음(수축)", low), ("높음(비수축)", high)]:
        wr = (g['pnl_pct'] > 0).mean() * 100 if len(g) else float('nan')
        print(f"{label:10s} {len(g):>6d} {wr:>7.1f} {g['pnl_pct'].mean():>10.3f}")

    verdict = "부합" if (low['pnl_pct'].mean() > high['pnl_pct'].mean()) and ((low['pnl_pct']>0).mean() > (high['pnl_pct']>0).mean()) else "불일치"
    print(f"판정: {verdict} (수축 낮은 쪽이 승률·평균수익 둘 다 높아야 부합)")


def side_effect_1_volume_quartiles(trades: pd.DataFrame) -> None:
    """[2순위] 진입일 거래량/20일평균을 1.5~2/2~3/3+로 나눠 평균 보유기간수익률이
    단조증가해야 한다."""
    t = trades.dropna(subset=["volume_ratio"]).copy()
    bins = [1.5, 2, 3, np.inf]
    labels = ["1.5~2배", "2~3배", "3배+"]
    t["bucket"] = pd.cut(t["volume_ratio"], bins=bins, labels=labels, right=False)

    print("\n=== [2순위] 부수효과1: 진입일 거래량배율 -> 보유기간수익률 단조증가? ===")
    print(f"{'구간':10s} {'거래수':>6s} {'평균%/거래':>10s}")
    means = []
    for label in labels:
        g = t[t["bucket"] == label]
        m = g["pnl_pct"].mean() if len(g) else float("nan")
        means.append(m)
        print(f"{label:10s} {len(g):>6d} {m:>10.3f}")

    monotonic = all(means[i] <= means[i + 1] for i in range(len(means) - 1)) if not any(pd.isna(means)) else False
    verdict = "부합" if monotonic else "불일치"
    print(f"판정: {verdict} (단조증가 여부 그대로 - 안 나오면 '새 자금 유입 확인'이 아니라 다른 걸 잡고 있다는 뜻)")


def side_effect_2_n_day_high_grid(universe: dict, entry_start, entry_end, horizon_end) -> None:
    """[3순위] n_day_high=20/60/120 — 승률·평균수익은 120>60>20, 신호빈도는 반대로
    단조감소해야 한다. 좋은 N을 고르는 게 아니라 방향이 미리 예측된 가설 검증이다."""
    print("\n=== [3순위] 부수효과2: n_day_high 20/60/120 방향성 검증(채택 아님) ===")
    print(f"{'N':>5s} {'거래수':>7s} {'승률%':>7s} {'평균%/거래':>10s}")
    stats = {}
    for n in (20, 60, 120):
        rows = []
        for code, df in universe.items():
            for r in _trades_with_entry_index(df, n, entry_start, entry_end, horizon_end):
                rows.append(r)
        df_n = pd.DataFrame(rows)
        wr = (df_n["pnl_pct"] > 0).mean() * 100 if len(df_n) else 0.0
        avg = df_n["pnl_pct"].mean() if len(df_n) else 0.0
        stats[n] = {"n_trades": len(df_n), "win_rate": wr, "avg_pct": avg}
        print(f"{n:>5d} {len(df_n):>7d} {wr:>7.1f} {avg:>10.3f}")

    win_rate_order = stats[120]["win_rate"] > stats[60]["win_rate"] > stats[20]["win_rate"]
    avg_order = stats[120]["avg_pct"] > stats[60]["avg_pct"] > stats[20]["avg_pct"]
    freq_order = stats[20]["n_trades"] > stats[60]["n_trades"] > stats[120]["n_trades"]
    both_perf = win_rate_order and avg_order
    verdict = "부합" if (both_perf and freq_order) else ("불일치" if not (win_rate_order or avg_order or freq_order) else "판정불가(일부만 부합)")
    print(f"승률 120>60>20: {win_rate_order} / 평균%/거래 120>60>20: {avg_order} / 빈도 20>60>120: {freq_order}")
    print(f"판정: {verdict} (예측 방향이 어긋나거나 무작위면 오버행 소진이 아니라 최근 상승모멘텀을 잡고 있다는 뜻)")


def side_effect_4_pullback_volume(trades: pd.DataFrame) -> None:
    """[4순위] 돌파 후 조정구간(종가가 진입 후 러닝고점 밑)에서 거래량이 진입일/20일
    평균보다 줄어야 한다. 급증하며 빠지는 사례가 많으면 가설 기각."""
    t = trades[trades["n_pullback_days"] > 0].dropna(subset=["pullback_avg_volume", "avg_volume_20d"])

    vs_entry_spike = (t["pullback_avg_volume"] > t["entry_volume"]).mean() * 100
    vs_20d_spike = (t["pullback_avg_volume"] > t["avg_volume_20d"]).mean() * 100

    print("\n=== [4순위] 부수효과4: 조정구간 거래량 감소해야 함 ===")
    print(f"조정구간이 있었던 거래 {len(t)}건")
    print(f"조정구간 평균거래량 > 진입일 거래량인 비중: {vs_entry_spike:.1f}%")
    print(f"조정구간 평균거래량 > 20일 평균거래량인 비중: {vs_20d_spike:.1f}%")
    verdict = "불일치" if vs_20d_spike > 50 else "부합"
    print(f"판정: {verdict} (20일 평균 대비 급증 비중이 과반이면 기각)")


def main() -> None:
    universe = dwf.load_universe(dwf.DATA_DIR)
    overall_start, overall_end, holdout_start = dwf.compute_holdout_start(universe)
    horizon_end = holdout_start - timedelta(days=1)
    print(f"유니버스 {len(universe)}종목, 홀드아웃 {holdout_start}~{overall_end}은 열지 않음")
    print(f"검증 구간: {overall_start} ~ {horizon_end}")

    trades60 = collect_trades(universe, 60, overall_start, horizon_end, horizon_end)
    print(f"n_day_high=60 거래 {len(trades60)}건 수집")

    side_effect_3_volatility_contraction(trades60)
    side_effect_1_volume_quartiles(trades60)
    side_effect_2_n_day_high_grid(universe, overall_start, horizon_end, horizon_end)
    side_effect_4_pullback_volume(trades60)


if __name__ == "__main__":
    main()
