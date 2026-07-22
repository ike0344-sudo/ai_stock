"""매 1분봉을 매수 시점으로 가정하고 -손절%/+익절% 중 무엇을 먼저 만나는지 스캔.

특정 전략 신호가 아니라 "언제 샀으면 좋았을지"를 사후적으로 찾는 용도.
당일 청산을 가정해 다음 날로는 넘어가지 않는다.
"""
import numpy as np
import pandas as pd


def scan_bracket_zones(
    candles: pd.DataFrame,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> pd.DataFrame:
    """candles(OHLC, 분봉)의 각 행을 매수 시점으로 가정해 결과를 스캔한다.

    같은 봉에서 손절가/익절가를 동시에 건드리면(고가·저가 둘 다 임계 통과) 봉 내부의
    실제 순서를 알 수 없으므로 보수적으로 손절이 먼저 발생한 것으로 처리한다.
    당일 마감까지 어느 쪽도 안 만나면 마감가로 마킹(outcome="none")한다.

    반환 컬럼: entry_time, entry_price, outcome("win"/"loss"/"none"),
    exit_time, exit_price, realized_pct
    """
    closes = candles["close"].to_numpy(dtype=float)
    lows = candles["low"].to_numpy(dtype=float)
    highs = candles["high"].to_numpy(dtype=float)
    times = candles.index
    days = candles.index.normalize().to_numpy()

    n = len(candles)
    records = []

    for i in range(n):
        entry_price = closes[i]
        stop_price = entry_price * (1 - stop_loss_pct)
        target_price = entry_price * (1 + take_profit_pct)
        day = days[i]

        outcome = "none"
        exit_idx = None

        for j in range(i + 1, n):
            if days[j] != day:
                break
            if lows[j] <= stop_price:
                outcome = "loss"
                exit_idx = j
                break
            if highs[j] >= target_price:
                outcome = "win"
                exit_idx = j
                break

        if outcome == "none":
            same_day_idx = np.where(days == day)[0]
            last_idx = same_day_idx[-1]
            if last_idx > i:
                exit_idx = last_idx

        if exit_idx is not None:
            if outcome == "loss":
                exit_price = stop_price
            elif outcome == "win":
                exit_price = target_price
            else:
                exit_price = closes[exit_idx]
            exit_time = times[exit_idx]
            realized_pct = (exit_price / entry_price - 1) * 100
        else:
            exit_price = None
            exit_time = None
            realized_pct = None

        records.append(
            {
                "entry_time": times[i],
                "entry_price": entry_price,
                "outcome": outcome,
                "exit_time": exit_time,
                "exit_price": exit_price,
                "realized_pct": realized_pct,
            }
        )

    return pd.DataFrame(records)


def summarize_zones(outcomes: pd.DataFrame, bucket_minutes: int = 30) -> pd.DataFrame:
    """entry_time을 시각(시:분) 구간으로 묶어 구간별 승률/평균 실현수익률을 집계한다.

    여러 종목의 scan_bracket_zones() 결과를 concat해서 넘기면 종목 간 교차 집계도 된다.
    """
    if outcomes.empty:
        return pd.DataFrame(columns=["time_bucket", "n", "win_rate_pct", "avg_realized_pct"])

    df = outcomes.copy()
    minutes_since_midnight = df["entry_time"].dt.hour * 60 + df["entry_time"].dt.minute
    bucket_start = (minutes_since_midnight // bucket_minutes) * bucket_minutes
    df["time_bucket"] = bucket_start.apply(lambda m: f"{m // 60:02d}:{m % 60:02d}")

    grouped = df.groupby("time_bucket").agg(
        n=("outcome", "count"),
        wins=("outcome", lambda s: (s == "win").sum()),
        avg_realized_pct=("realized_pct", "mean"),
    )
    grouped["win_rate_pct"] = grouped["wins"] / grouped["n"] * 100
    grouped = grouped.drop(columns="wins").reset_index()
    return grouped.sort_values("time_bucket").reset_index(drop=True)
