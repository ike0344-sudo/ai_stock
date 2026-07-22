"""동시보유 한도를 반영한 현실적 포트폴리오 시뮬레이션.

거래별 진입/청산 시각과 순손익률만 주어지면, 정해진 개수의 동시보유 슬롯으로
실제 계좌가 어떻게 움직였을지 시간순(이벤트 기반)으로 재현한다. 자금이 무제한이라고
가정하지 않는다 — 슬롯이 이미 다 찬 시점에 새 신호가 오면 그 신호는 놓친 것으로
처리한다. 슬롯 크기는 initial_capital / max_concurrent_positions로 고정한다
(재투자 복리 없음 — 슬롯 크기가 개별 거래 손익에 따라 요동치지 않도록).
"""
from dataclasses import dataclass

import pandas as pd


@dataclass
class SlotTrade:
    code: object
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    pct: float
    taken: bool
    profit: float


@dataclass
class PortfolioResult:
    initial_capital: float
    max_concurrent_positions: int
    slot_size: float
    trades: list
    final_capital: float

    @property
    def taken_trades(self) -> list:
        return [t for t in self.trades if t.taken]

    @property
    def skipped_count(self) -> int:
        return sum(1 for t in self.trades if not t.taken)


def simulate_slot_portfolio(
    candidates: pd.DataFrame,
    initial_capital: float = 10_000_000,
    max_concurrent_positions: int = 5,
) -> PortfolioResult:
    """candidates: entry_time/exit_time/pct(+선택적으로 code) 컬럼을 가진 DataFrame.

    entry_time 순으로 처리하며, 그 시점에 이미 청산(exit_time <= entry_time)된
    슬롯이 하나라도 있으면 그 신호를 채택하고, 전부 사용 중이면 건너뛴다.
    """
    slot_size = initial_capital / max_concurrent_positions

    if candidates.empty:
        return PortfolioResult(
            initial_capital=initial_capital, max_concurrent_positions=max_concurrent_positions,
            slot_size=slot_size, trades=[], final_capital=initial_capital,
        )

    sorted_candidates = candidates.sort_values("entry_time")
    slot_free_at = [pd.Timestamp.min] * max_concurrent_positions

    trades: list = []
    total_profit = 0.0

    for _, row in sorted_candidates.iterrows():
        entry_time, exit_time, pct = row["entry_time"], row["exit_time"], row["pct"]
        code = row.get("code")

        free_slot_idx = next((i for i, free_at in enumerate(slot_free_at) if free_at <= entry_time), None)

        if free_slot_idx is None:
            trades.append(SlotTrade(code, entry_time, exit_time, pct, taken=False, profit=0.0))
            continue

        profit = slot_size * pct
        slot_free_at[free_slot_idx] = exit_time
        total_profit += profit
        trades.append(SlotTrade(code, entry_time, exit_time, pct, taken=True, profit=profit))

    return PortfolioResult(
        initial_capital=initial_capital, max_concurrent_positions=max_concurrent_positions,
        slot_size=slot_size, trades=trades, final_capital=initial_capital + total_profit,
    )


def monthly_profit_breakdown(result: PortfolioResult) -> pd.DataFrame:
    taken = result.taken_trades
    if not taken:
        return pd.DataFrame(columns=["month", "n_trades", "profit"])

    df = pd.DataFrame([{"entry_time": t.entry_time, "profit": t.profit} for t in taken])
    df["month"] = df["entry_time"].dt.to_period("M")
    grouped = df.groupby("month")["profit"].agg(["sum", "count"]).reset_index()
    grouped.columns = ["month", "profit", "n_trades"]
    return grouped[["month", "n_trades", "profit"]]
