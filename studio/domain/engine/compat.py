"""호환 모드 — 기존 `backtesting.simulator.run` 을 줄 단위로 재현 (설계서 §3.6, 패리티 P1·P3).

새 엔진의 일반 모드와 규칙이 다르다(슬리피지 비율만, 복리·현금 제약 없음, 손절/익절 없음).
기존 연구 19건과 숫자를 잇기 위한 것이라, **기존 코드의 버릇까지 그대로** 둔다:
  · 신호는 봉 t 종가 → 다음 봉 시가 체결, 대기 신호는 잠기지 않은 봉에서 적용 여부와 무관하게 소거
  · 전일 종가 = candles 안 일자별 마지막 종가의 shift(1) (Panel.prev_close 를 쓰지 않는다)
  · Trade.slippage 는 기존과 같이 **진입 쪽만**(entry_price×qty×rate) — 청산 슬리피지는 안 넣는다.
    (pnl 에는 체결가에 이미 반영돼 있어 영향 없음. 정보용 칸이라 기존 값 그대로 재현.)
신호 입력은 Signal enum 또는 "buy"/"sell"/"hold" 문자열 Series (도메인은 backtesting 을 import 못 한다).
"""
from __future__ import annotations

import pandas as pd

from ..market_rules import is_price_limit_locked
from ..models import Trade

DEFAULT_TAX_RATE = 0.0023

_BUY, _SELL = "buy", "sell"


def _norm(sig) -> str | None:
    v = getattr(sig, "value", sig)
    return v if v in (_BUY, _SELL) else None


def prev_day_close(candles: pd.DataFrame) -> pd.Series:
    """일자별 전일 종가 — candles 안의 그 이전 거래일이 없으면 NaN(잠김 판정 안 함)."""
    return candles.groupby(candles.index.normalize())["close"].last().shift(1)


def run_compat(
    candles: pd.DataFrame,
    signals: pd.Series,
    commission_rate: float,
    slippage_rate: float,
    initial_capital: float,
    stock_code: str = "",
    force_eod_close: bool = False,
    tax_rate: float = DEFAULT_TAX_RATE,
) -> list[Trade]:
    """한 종목·한 번에 하나의 전액 포지션. 끝까지 보유 중인 거래는 exit=None 으로 남는다(규칙 7)."""
    index = candles.index
    n = len(candles)
    opens = candles["open"].to_numpy(dtype=float)
    closes = candles["close"].to_numpy(dtype=float)
    day_arr = index.normalize().to_numpy()
    prev_close_arr = prev_day_close(candles).reindex(index.normalize()).to_numpy(dtype=float)
    sig_arr = signals.reindex(index).to_numpy()  # 라벨 기준 정렬 — 위치로 맞추면 신호가 밀린다

    trades: list[Trade] = []
    # open: [entry_i, entry_price, qty, entry_commission, entry_slippage]
    op: list | None = None
    pending: str | None = None

    def settle(i: int, exit_price: float) -> None:
        nonlocal op
        e_i, e_px, qty, e_comm, e_slip = op
        exit_comm = exit_price * qty * commission_rate
        tax = exit_price * qty * tax_rate
        gross = (exit_price - e_px) * qty
        pnl = gross - (e_comm + exit_comm + tax)
        trades.append(Trade(
            code=stock_code, entry_ts=index[e_i], entry_price=e_px, exit_ts=index[i], exit_price=exit_price,
            qty=qty, gross_pnl=gross, commission=e_comm + exit_comm, tax=tax, slippage_cost=e_slip,
            net_pnl=pnl, net_pct=pnl / (e_px * qty), exit_reason=None, bars_held=i - e_i + 1,
            mfe_pct=None, mae_pct=None,
        ))
        op = None

    for i in range(n):
        open_px, close_px, prev_close = opens[i], closes[i], prev_close_arr[i]
        is_last_of_day = force_eod_close and (i == n - 1 or day_arr[i + 1] != day_arr[i])

        if pending is not None and not is_price_limit_locked(open_px, prev_close):  # 규칙 4·5
            if pending == _BUY and op is None:
                entry_price = open_px * (1 + slippage_rate)  # 규칙 1
                qty = int(initial_capital // entry_price)  # 규칙 2
                if qty > 0:
                    op = [i, entry_price, qty, entry_price * qty * commission_rate,
                          entry_price * qty * slippage_rate]
            elif pending == _SELL and op is not None:
                settle(i, open_px * (1 - slippage_rate))
            pending = None

        if is_last_of_day and op is not None:  # 규칙 6
            if not is_price_limit_locked(close_px, prev_close):
                settle(i, close_px * (1 - slippage_rate))
                pending = None
            continue  # 잠김이면 보류 — 어느 쪽이든 그 봉 새 신호는 무시

        s = _norm(sig_arr[i])
        if s is not None:
            pending = s

    if op is not None:  # 규칙 7 — 미청산
        e_i, e_px, qty, e_comm, e_slip = op
        trades.append(Trade(
            code=stock_code, entry_ts=index[e_i], entry_price=e_px, exit_ts=None, exit_price=None, qty=qty,
            gross_pnl=None, commission=e_comm, tax=0.0, slippage_cost=e_slip, net_pnl=None, net_pct=None,
            exit_reason=None, bars_held=n - e_i, mfe_pct=None, mae_pct=None,
        ))
    return trades


def legacy_slots(trades: list[Trade], initial_capital: float = 10_000_000,
                 max_positions: int = 5) -> dict:
    """`portfolio_sim.simulate_slot_portfolio` 재현(P3). 완결 거래(net_pct 있는)만 후보.

    기존 구현은 `DataFrame.sort_values("entry_time")`(quicksort, 동률 순서 비보장)를 쓴다 —
    같은 호출을 그대로 써서 동률(같은 날 진입)의 채택 순서까지 똑같이 맞춘다.
    반환: final_capital, taken(입력 순서 기준 bool 리스트, 후보 index 로 대응), n_taken, n_skipped
    """
    cands = [(k, t) for k, t in enumerate(trades) if t.net_pct is not None]
    slot_size = initial_capital / max_positions
    taken = [False] * len(trades)
    if not cands:
        return {"final_capital": initial_capital, "taken": taken, "n_taken": 0, "n_skipped": 0,
                "slot_size": slot_size}
    df = pd.DataFrame({
        "entry_time": [t.entry_ts for _, t in cands],
        "exit_time": [t.exit_ts for _, t in cands],
        "pct": [t.net_pct for _, t in cands],
        "src": [k for k, _ in cands],
    }).sort_values("entry_time")
    free_at = [pd.Timestamp.min] * max_positions
    total = 0.0
    n_taken = 0
    for row in df.itertuples(index=False):
        slot = next((j for j, f in enumerate(free_at) if f <= row.entry_time), None)
        if slot is None:
            continue
        free_at[slot] = row.exit_time
        total += slot_size * row.pct
        taken[row.src] = True
        n_taken += 1
    return {"final_capital": initial_capital + total, "taken": taken, "n_taken": n_taken,
            "n_skipped": len(cands) - n_taken, "slot_size": slot_size}
