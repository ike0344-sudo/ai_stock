"""콘솔/CSV/차트 출력.

Design: docs/02-design/features/strategy-backtesting.design.md §4.1, §5
"""
import mplfinance as mpf
import pandas as pd

from .types import GridSearchResult, Trade


def _oos_alpha_pct(result: GridSearchResult) -> float:
    """OOS 수익률 - 같은 구간 매수 후 보유 수익률 (벤치마크 대비 초과수익).

    raw 수익률만 보면 "시장이 올라서 번 것"과 "전략이 잘해서 번 것"을 구분 못 한다
    (실제 백테스트에서 MA 크로스오버가 OOS +160%를 냈지만 같은 구간 매수 후 보유가
    +285%라 사실은 시장을 못 따라간 사례로 발견됨).
    """
    return result.out_of_sample.total_return_pct - result.benchmark_oos_return_pct


def rank_results(results: list[GridSearchResult]) -> list[GridSearchResult]:
    """거래가 있는 조합을 우선하고, 그 안에서는 벤치마크 대비 초과수익(alpha) 내림차순으로 정렬.

    거래 0건인 조합은 수익률이 0%가 되어 실제로 수익 난 조합과 동률/역전될 수 있다
    (실제 API로 여러 종목을 돌리다 발견 — 거래 없는 조합이 '최고'로 뽑혀 차트 생성이
    크래시했었음). summarize()의 표 순서와 plot 대상 선정이 이 함수 하나로 일치한다.
    """
    return sorted(
        results,
        key=lambda r: (r.out_of_sample.num_trades > 0, _oos_alpha_pct(r)),
        reverse=True,
    )


def summarize(results: list[GridSearchResult]) -> pd.DataFrame:
    ranked = rank_results(results)
    rows = [
        {
            "stock_code": r.stock_code,
            "strategy": r.strategy_name,
            "params": r.params,
            "is_return_pct": r.in_sample.total_return_pct,
            "is_mdd_pct": r.in_sample.max_drawdown_pct,
            "oos_return_pct": r.out_of_sample.total_return_pct,
            "oos_mdd_pct": r.out_of_sample.max_drawdown_pct,
            "oos_win_rate_pct": r.out_of_sample.win_rate_pct,
            "oos_sharpe": r.out_of_sample.sharpe_ratio,
            "oos_num_trades": r.out_of_sample.num_trades,
            "benchmark_oos_return_pct": r.benchmark_oos_return_pct,
            "alpha_oos_pct": _oos_alpha_pct(r),
        }
        for r in ranked
    ]
    return pd.DataFrame(rows)


def print_summary(df: pd.DataFrame) -> None:
    if df.empty:
        print("결과 없음")
        return

    for _, row in df.iterrows():
        print(
            f"[{row['strategy']}] {row['stock_code']} {row['params']} "
            f"IS: {row['is_return_pct']:+.2f}% (MDD {row['is_mdd_pct']:.2f}%)  "
            f"OOS: {row['oos_return_pct']:+.2f}% (MDD {row['oos_mdd_pct']:.2f}%)  "
            f"B&H: {row['benchmark_oos_return_pct']:+.2f}%  alpha: {row['alpha_oos_pct']:+.2f}%  "
            f"trades={row['oos_num_trades']}"
        )

    best = df.iloc[0]
    print(f"\nBest (by OOS alpha vs buy-and-hold): [{best['strategy']}] {best['stock_code']} {best['params']}")


def save_csv(df: pd.DataFrame, path: str) -> None:
    df.to_csv(path, index=False)


def _find_candle_timestamp(candles: pd.DataFrame, target_date, prefer: str):
    """target_date(date)에 해당하는 캔들 중 첫/마지막을 찾는다.

    일봉은 하루 1개 캔들이라 first==last. 분봉(데이트레이딩)은 entry가 그날 어느
    분봉인지 정확히 알 수 없어 첫 캔들로 근사하고, EOD 강제 청산 특성상 exit는
    그날 마지막 캔들과 정확히 일치한다.
    """
    matches = candles.index[candles.index.normalize() == pd.Timestamp(target_date)]
    if len(matches) == 0:
        return None
    return matches[0] if prefer == "first" else matches[-1]


def plot_best(candles: pd.DataFrame, trades: list[Trade], title: str, save_path: str | None = None) -> None:
    buy_markers = pd.Series(float("nan"), index=candles.index)
    sell_markers = pd.Series(float("nan"), index=candles.index)

    for trade in trades:
        entry_ts = _find_candle_timestamp(candles, trade.entry_date, prefer="first")
        if entry_ts is not None:
            buy_markers.loc[entry_ts] = candles.loc[entry_ts, "low"] * 0.995

        if trade.exit_date is not None:
            exit_ts = _find_candle_timestamp(candles, trade.exit_date, prefer="last")
            if exit_ts is not None:
                sell_markers.loc[exit_ts] = candles.loc[exit_ts, "high"] * 1.005

    # 마커가 전부 NaN인 addplot을 넘기면 mplfinance가 빈 배열에 대해 max()를 호출해
    # 크래시함 (실제 API로 거래 0건인 조합을 그려보다가 발견). 유효 값이 있을 때만 추가.
    addplots = []
    if buy_markers.notna().any():
        addplots.append(mpf.make_addplot(buy_markers, type="scatter", marker="^", color="red", markersize=100))
    if sell_markers.notna().any():
        addplots.append(mpf.make_addplot(sell_markers, type="scatter", marker="v", color="blue", markersize=100))

    plot_kwargs = {"type": "candle", "volume": True, "style": "charles", "title": title}
    if addplots:
        plot_kwargs["addplot"] = addplots
    if save_path:
        plot_kwargs["savefig"] = save_path
    mpf.plot(candles, **plot_kwargs)
