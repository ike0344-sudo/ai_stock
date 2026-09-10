"""52주 신고가+골든크로스 — 연 단위 여러 구간 x 대조군 3종 x 청산규칙 3종.
lead 지시 2건을 누적 반영:
  1) 2026-09-02 1차: "이번 1년이 강세장이라서"인지 가르려고 연 단위로 늘림.
  2) 2026-09-02 2차(§3 인정): "신호종목 단순보유" 대조군은 진입필터 성능을
     대조군에 심어놓는 것과 같아 구조적으로 부풀려진다는 지적을 인정하고,
     신호와 무관한 대조군(3조+ 유니버스 동일가중, 코스피지수)을 추가.
     동시에 청산규칙을 3갈래(현행/손절만/청산없음)로 격리해 "+24% 상한이
     범인인지" 가른다.

`newhigh52w_golden_cross.py`의 진입/신호 로직은 하나도 안 바꾼다. `simulate_trades`에
stop_pct/target_pct 선택 인자만 추가(기본값은 기존 -8%/+24% 그대로, 하위호환) —
청산 세 갈래는 그 인자로만 만든다, 새 청산 분기 없음.

2025-09~2026-08 구간의 **(a) 현행 청산**만 재계산 안 하고 기존 산출물
(`results/newhigh52w_golden_cross_*.csv`)을 그대로 읽는다. (b)/(c) 청산과
새 대조군 2종은 이번에 처음 계산하는 값이라 그 구간도 새로 돌린다.

실행: python -m backtesting.newhigh52w_yearly_windows
"""
import os

import numpy as np
import pandas as pd

import backtesting.newhigh52w_golden_cross as m

# 2020-05 시작(52주=252거래일 룩백 확보), 매년 5월~익년4월. 2025-09~2026-08은
# 기존 산출물 재사용 대상이라 별도 처리 - 그 사이 2025-05~2025-08(4개월)은
# 어느 구간에도 안 들어간다(1차 라운드부터 있던 공백, 지시 그대로 유지).
NEW_WINDOWS = [
    ("2020-05-01", "2021-04-30"),
    ("2021-05-01", "2022-04-30"),
    ("2022-05-01", "2023-04-30"),
    ("2023-05-01", "2024-04-30"),
    ("2024-05-01", "2025-04-30"),
]
REUSED_WINDOW = ("2025-09-01", "2026-08-31")
REUSED_TRADES_CSV = {
    "5_20": "results/newhigh52w_golden_cross_5_20.csv",
    "20_60": "results/newhigh52w_golden_cross_20_60.csv",
}

# (b)/(c)는 lead 2차 지시 B항. stop_pct/target_pct = None -> 그 경계 비활성화(무한대).
EXIT_VARIANTS = {
    "a_stop8_target24": (0.08, 0.24),   # 현행(1차 라운드와 동일)
    "b_stop8_notarget": (0.08, None),   # 손절만, 익절 상한 없음
    "c_no_exit": (None, None),          # 청산 없음 - 구간 끝까지 보유
}

INDEX_CSV = "data/index/daily/001.csv"


def _codes_over_cap(panel_raw: pd.DataFrame, shares: pd.Series, window_start: str) -> list[str]:
    """window_start 이후 가장 이른 거래일 종가 x 현재 shares 로 3조 필터 통과 종목코드
    (단일 시점 근사 - shares는 현재 스냅샷 한 장, 과거로 갈수록 오차 커짐, 1차 보고서에 명시됨)."""
    day = panel_raw.loc[panel_raw["date"] >= window_start, "date"]
    if day.empty:
        return []
    first_date = day.min()
    row = panel_raw[panel_raw["date"] == first_date]
    caps = row["close"].to_numpy() * shares.reindex(row["code"]).to_numpy()
    return row.loc[caps >= m.MARKET_CAP_MIN, "code"].tolist()


def cap_breadth(panel_raw: pd.DataFrame, shares: pd.Series, window_start: str) -> int:
    return len(_codes_over_cap(panel_raw, shares, window_start))


def universe_buy_and_hold(panel_raw: pd.DataFrame, shares: pd.Series, window_start: str) -> tuple[float, int]:
    """신규 대조군②(lead 2차지시 A-2): 구간 시작일 3조+ 유니버스 전체 동일가중 buy&hold.
    `buy_and_hold_control`(신호종목용과 동일 함수)을 그대로 재사용 - 새 수익률 계산 로직 없음."""
    codes = _codes_over_cap(panel_raw, shares, window_start)
    if not codes:
        return float("nan"), 0
    return m.buy_and_hold_control(panel_raw, codes)


_INDEX_DF = None


def kospi_index_return(start: str, end: str) -> float:
    """신규 대조군③(lead 2차지시 A-3). 지수데이터가 구간 시작보다 늦게 시작하면
    추정하지 않고 NaN(없음)으로 둔다 - 문자 그대로 "없으면 없다고 비워라"."""
    global _INDEX_DF
    if _INDEX_DF is None:
        _INDEX_DF = pd.read_csv(INDEX_CSV)
    if _INDEX_DF["date"].min() > start:
        return float("nan")
    sub = _INDEX_DF[(_INDEX_DF["date"] >= start) & (_INDEX_DF["date"] <= end)].sort_values("date")
    if sub.empty:
        return float("nan")
    return float(sub["close"].iloc[-1] / sub["close"].iloc[0] - 1)


def stats_from_trades(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"n": 0, "win_rate": float("nan"), "net_mean": float("nan"),
                "stop": 0, "target": 0, "expiry": 0}
    reason_counts = trades["exit_reason"].value_counts().to_dict()
    return {
        "n": len(trades), "win_rate": float((trades["net_pct"] > 0).mean()),
        "net_mean": float(trades["net_pct"].mean()),
        "stop": reason_counts.get("stop", 0) + reason_counts.get("stop_both", 0),
        "target": reason_counts.get("target", 0), "expiry": reason_counts.get("expiry", 0),
    }


def _row_with_controls(trades: pd.DataFrame, panel_raw: pd.DataFrame, univ_ret: float, univ_n: int,
                        kospi_ret: float) -> dict:
    stats = stats_from_trades(trades)
    if trades.empty:
        ctrl_ret, ctrl_n = float("nan"), 0
    else:
        ctrl_ret, ctrl_n = m.buy_and_hold_control(panel_raw, trades["code"].unique().tolist())

    def _excess(bench):
        return stats["net_mean"] - bench if not (np.isnan(stats["net_mean"]) or np.isnan(bench)) else float("nan")

    return {
        **stats,
        "ctrl_signal_ret": ctrl_ret, "ctrl_signal_n": ctrl_n, "excess_vs_signal": _excess(ctrl_ret),
        "ctrl_universe_ret": univ_ret, "ctrl_universe_n": univ_n, "excess_vs_universe": _excess(univ_ret),
        "kospi_ret": kospi_ret, "excess_vs_kospi": _excess(kospi_ret),
    }


def run_window_full(start: str, end: str, shares: pd.Series,
                     reused_a_csvs: dict[str, str] | None = None) -> list[dict]:
    m.PERIOD_START, m.PERIOD_END = start, end
    panel_raw = m.load_panel()
    panel = m.add_features(panel_raw)

    cap_n = cap_breadth(panel_raw, shares, start)
    univ_ret, univ_n = universe_buy_and_hold(panel_raw, shares, start)
    kospi_ret = kospi_index_return(start, end)

    rows = []
    for def_name in m.GOLDEN_CROSS_DEFS:
        for variant_name, (stop_pct, target_pct) in EXIT_VARIANTS.items():
            reused = bool(reused_a_csvs) and variant_name == "a_stop8_target24"
            if reused:
                trades = pd.read_csv(reused_a_csvs[def_name], dtype={"code": str})
            else:
                trades = m.simulate_trades(panel, shares, def_name, stop_pct=stop_pct, target_pct=target_pct)
            row = {"start": start, "end": end, "def": def_name, "variant": variant_name,
                   "reused": reused, "cap_universe_n": cap_n,
                   **_row_with_controls(trades, panel_raw, univ_ret, univ_n, kospi_ret)}
            row["_trades"] = trades  # 롤링윈도 스크립트(newhigh52w_rolling_windows.py)의 손실통계용,
            rows.append(row)         # 이 모듈 자신의 CSV/출력에는 안 씀(main()에서 드롭)
    return rows


def main():
    shares = m.load_shares()
    rows = []
    for start, end in NEW_WINDOWS:
        print(f"[{start}~{end}] 실행...", flush=True)
        rows += run_window_full(start, end, shares)
    print(f"[{REUSED_WINDOW[0]}~{REUSED_WINDOW[1]}] (a)청산은 기존 산출물 재사용, "
          f"(b)/(c)청산·신규대조군은 새로 계산...", flush=True)
    rows += run_window_full(*REUSED_WINDOW, shares, reused_a_csvs=REUSED_TRADES_CSV)

    df = pd.DataFrame(rows).drop(columns=["_trades"])
    os.makedirs("results", exist_ok=True)
    df.to_csv("results/newhigh52w_exit_isolation.csv", index=False)

    for _, r in df.iterrows():
        kospi = f"{r['kospi_ret']*100:.1f}%" if not np.isnan(r["kospi_ret"]) else "N/A"
        thin = " [표본얇음]" if r["n"] <= 5 else ""
        print(f"{r['start']}~{r['end']} [{r['def']}/{r['variant']}] n={r['n']}{thin} "
              f"승률={r['win_rate']*100:.1f}% net평균={r['net_mean']*100:.3f}% "
              f"손절/익절/만료={r['stop']}/{r['target']}/{r['expiry']} | "
              f"대조군(신호종목)={r['ctrl_signal_ret']*100:.3f}% 초과={r['excess_vs_signal']*100:.3f}%p | "
              f"대조군(유니버스,n={r['ctrl_universe_n']})={r['ctrl_universe_ret']*100:.3f}% "
              f"초과={r['excess_vs_universe']*100:.3f}%p | 코스피={kospi} "
              f"{'재사용' if r['reused'] else ''}", flush=True)

    return df


if __name__ == "__main__":
    main()
