"""틱 엔진 — 모드 B(틱 조건 진입 시뮬레이션)와 모드 A(분봉 체결가를 체결 데이터로 정밀화). 설계서 §3.5·§3.7·§8.8 C4.

## 모드 B — 틱 조건 진입 (`simulate_tick_days`)
신호(조건식 쪽 `conditions/tick.py`)는 신호 초 s 와 그 **다음** 체결(`entry_sec > signal_sec`)의 가격을 준다. 여기서는:
  · 진입 = 그 체결가에 슬리피지(비용 모델). 갭시작 종목·상하한가에 잠긴 진입가는 안 산다.
  · 청산 = 진입 뒤 **틱 순서대로** 처음 닿는 것 — 손절선·트레일링선(고점은 직전 틱까지)·익절선·`time_stop_sec` 경과 첫 체결·`eod_time` 이하 마지막 체결.
    틱은 순서가 있어서 봉 안 경로 문제(손절/익절 동시) 자체가 없다. 청산가 = 그 틱의 체결가(손절은 선보다 나쁘게 뚫릴 수 있다) ∓ 슬리피지.
  · 슬롯(`max_positions`)·현금·사이징 4종은 일봉 엔진과 같다. 우선순위는 **진입 시각 순**(같은 초면 종목코드 순) — rank_by 는 무시한다.
  · 하루 안에 다 청산한다(EOD). 그래서 자금은 날마다 새로 시작한다(복리는 전날 평가금).
근사·한계(결과에 경고로 남긴다): 거래량 한도 미적용, 청산가가 상하한가에 잠겨도 그 가격으로 청산(다음 날로 못 넘김), 같은 초 안 체결 순서는
원본 그대로(일부 파일은 어긋남), `bars_held` 는 **초**.

## 모드 A — 분봉 체결 정밀화 (`refine_fills`)
분봉 엔진 결과의 각 거래에서 봉 기준가(진입=다음 봉 시가, 손절·익절=선, 종가청산=봉 종가)를 그 시점의 실제 체결가로 바꿔 본다:
  · 진입·시그널 청산: 봉이 끝난 시각 T 이후 첫 체결(`sec >= T`).
  · 선 청산: 그 봉 안에서 선을 처음 넘은 체결(손절·트레일링 `price <= 선`, 익절 `price >= 선`) — 갭이면 선보다 나쁜(좋은) 체결가.
  · 종가 청산(보유기간·EOD): 그 봉의 마지막 체결.
매매별로 봉 기준가 / 틱 기준가 / 차이(%)를 표시한다(SC-7). 슬리피지·수수료는 두 쪽 모두 같은 비용 모델로 얹어 순손익을 다시 계산한다.
"""
from __future__ import annotations

import datetime as dt
import heapq
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..costs import CostModel
from ..market_rules import is_price_limit_locked
from ..models import BacktestResult, ExitReason, Fill, Trade
from .curve import CurveEmitter
from .fills import ExitRules
from .portfolio import PortfolioRules, _size

SESSION_OPEN_SEC = 9 * 3600  # 틱 sec 0 = 09:00:00


def hms_to_sec(s: str) -> int:
    """'15:19:59' → 09:00:00 기준 격자 초(하루 시각 − 09:00:00)."""
    p = [int(x) for x in s.split(":")]
    p += [0] * (3 - len(p))
    return p[0] * 3600 + p[1] * 60 + p[2] - SESSION_OPEN_SEC


@dataclass(frozen=True, eq=False)
class TickRules:
    time_stop_sec: int | None = 600
    eod_time: str = "15:19:59"
    exclude_gap_open_pct: float | None = 5.0  # 서비스가 쓴다(엔진은 후보만 받는다)


@dataclass(frozen=True, eq=False)
class Candidate:
    """한 종목·하루의 틱 배열과 그 안의 진입 신호 하나."""

    code: str
    day: dt.date
    sec: np.ndarray
    prc: np.ndarray
    prev_close: float | None
    signal_sec: int
    entry_idx: int  # 진입 체결의 틱 인덱스(신호 초보다 엄격히 뒤)


def _trigger(prc: np.ndarray, sec: np.ndarray, j0: int, entry_fill: float, rules: ExitRules,
             tr: TickRules) -> tuple[int, ExitReason]:
    """진입 틱 j0 다음 틱부터 처음 닿는 청산 조건의 틱 인덱스와 사유."""
    n = len(prc)
    eod_sec = hms_to_sec(tr.eod_time)
    k_eod = int(np.searchsorted(sec, eod_sec, side="right")) - 1  # eod 이하 마지막 체결
    k_eod = max(k_eod, j0)
    best, reason = k_eod, ExitReason.EOD
    if j0 + 1 >= n or k_eod <= j0:
        return k_eod, ExitReason.EOD
    seg = prc[j0 + 1: k_eod + 1].astype(float)
    off = j0 + 1
    if tr.time_stop_sec is not None:
        k = int(np.searchsorted(sec, sec[j0] + tr.time_stop_sec, side="left"))
        if off <= k <= best:
            best, reason = k, ExitReason.TIME
    stop = entry_fill * (1 - rules.stop_loss_pct / 100) if rules.stop_loss_pct is not None else -np.inf
    if rules.trailing_stop_pct is not None:
        peak = np.maximum.accumulate(np.concatenate(([entry_fill], seg)))[:-1]  # 직전 틱까지의 고점(판정 뒤 갱신)
        trail = peak * (1 - rules.trailing_stop_pct / 100)
    else:
        trail = np.full(len(seg), -np.inf)
    line = np.maximum(stop, trail)
    down = np.flatnonzero(seg <= line)
    if len(down) and off + down[0] <= best:
        i = off + int(down[0])
        best = i
        reason = ExitReason.TRAILING if (rules.trailing_stop_pct is not None and trail[down[0]] > stop) else ExitReason.STOP
    if rules.take_profit_pct is not None:
        target = entry_fill * (1 + rules.take_profit_pct / 100)
        up = np.flatnonzero(seg >= target)
        if len(up) and off + up[0] <= best:
            best, reason = off + int(up[0]), ExitReason.TARGET
    return best, reason


def simulate_tick_days(
    days: dict[dt.date, list[Candidate]], all_days: list[dt.date], cost: CostModel, exit_rules: ExitRules,
    portfolio: PortfolioRules, tr: TickRules, curve=None,
) -> BacktestResult:
    """날짜별 후보 → 시간순으로 슬롯·현금을 따라가며 진입·청산. all_days = 평가금 곡선에 넣을 모든 날(거래 없는 날 포함)."""
    cash_cap = float(portfolio.initial_capital)
    equity = cash_cap
    trades: list[Trade] = []
    fills: list[Fill] = []
    skipped = {"slots_full": 0, "cash": 0, "upper_limit": 0, "volume_cap": 0, "no_data": 0}
    diag = {"exit_at_limit": 0, "no_entry_after_eod": 0}
    eq_rows = []
    eod_sec = hms_to_sec(tr.eod_time)
    comm = cost.commission_rate
    emitter = CurveEmitter(curve, len(all_days)) if curve is not None else None  # 진행 중 중간 곡선(읽기만 — 결과 불변)
    for k_day, day in enumerate(all_days):
        equity_start = equity
        cash = equity
        cands = sorted(days.get(day, []), key=lambda c: (int(c.sec[c.entry_idx]), c.code))
        active: list[tuple[int, int, float, float]] = []  # (exit_sec, seq, 회수 현금(매도 대금−비용), 순손익) 힙 — 청산 시각 순
        seq = 0
        for c in cands:
            t = int(c.sec[c.entry_idx])
            while active and active[0][0] <= t:  # 이 진입 시각까지 끝난 포지션의 현금 회수
                _, _, back, pnl = heapq.heappop(active)
                cash += back
                equity += pnl
            if t >= eod_sec:
                diag["no_entry_after_eod"] += 1
                continue
            ref = float(c.prc[c.entry_idx])
            if c.prev_close and is_price_limit_locked(ref, c.prev_close):
                skipped["upper_limit"] += 1
                continue
            if len(active) >= portfolio.max_positions:
                skipped["slots_full"] += 1
                continue
            price = cost.buy_price(ref)
            qty = _size(portfolio, exit_rules, equity_start if portfolio.sizing == "equal_slot_compound" else equity_start,
                        cash, price, comm)
            if qty <= 0:
                skipped["cash"] += 1
                continue
            buy_comm = price * qty * comm
            cash -= price * qty + buy_comm
            k, reason = _trigger(c.prc, c.sec, c.entry_idx, price, exit_rules, tr)
            xref = float(c.prc[k])
            xprice = cost.sell_price(xref)
            sell_amt = xprice * qty
            sell_comm, tax = sell_amt * comm, sell_amt * cost.tax_rate
            if c.prev_close and is_price_limit_locked(xref, c.prev_close):
                diag["exit_at_limit"] += 1
            gross = (xprice - price) * qty
            net = gross - buy_comm - sell_comm - tax
            path = c.prc[c.entry_idx: k + 1].astype(float)
            ts0 = pd.Timestamp(day) + pd.Timedelta(seconds=SESSION_OPEN_SEC + t)
            ts1 = pd.Timestamp(day) + pd.Timedelta(seconds=SESSION_OPEN_SEC + int(c.sec[k]))
            slip = (price - ref) * qty + (xref - xprice) * qty
            trades.append(Trade(
                code=c.code, entry_ts=ts0, entry_price=price, exit_ts=ts1, exit_price=xprice, qty=qty, gross_pnl=gross,
                commission=buy_comm + sell_comm, tax=tax, slippage_cost=slip, net_pnl=net, net_pct=net / (price * qty),
                exit_reason=reason, bars_held=int(c.sec[k]) - t, mfe_pct=(path.max() / price - 1) * 100,
                mae_pct=(path.min() / price - 1) * 100))
            fills.append(Fill(ts0, c.code, "buy", qty, price, ref, buy_comm, 0.0, (price - ref) * qty, "entry"))
            fills.append(Fill(ts1, c.code, "sell", qty, xprice, xref, sell_comm, tax, (xref - xprice) * qty, reason.value))
            seq += 1
            heapq.heappush(active, (int(c.sec[k]), seq, sell_amt - sell_comm - tax, net))
        while active:  # 남은 포지션 정리(전부 EOD 이하에서 끝난다)
            _, _, back, pnl = heapq.heappop(active)
            cash += back
            equity += pnl
        eq_rows.append((pd.Timestamp(day), equity, 0.0, equity, 0))
        if emitter is not None:
            emitter.emit(k_day, pd.Timestamp(day), equity, equity, 0, len(trades), fills)
    eq = pd.DataFrame(eq_rows, columns=["ts", "cash", "positions_value", "equity", "n_positions"])
    trades.sort(key=lambda t: (t.entry_ts, t.code))
    fills.sort(key=lambda f: (f.ts, f.side != "sell", f.code))
    return BacktestResult(trades=trades, equity=eq, fills=fills, skipped=skipped, diagnostics=diag)


# ---------------------------------------------------------------------------- 모드 A — 정밀화


@dataclass
class RefinedFill:
    bar_ref: float
    tick_ref: float | None  # None = 그 봉 구간의 체결을 못 찾음(틱 없음·선을 안 넘음)
    note: str = ""

    @property
    def diff_pct(self) -> float | None:
        return None if self.tick_ref is None else (self.tick_ref / self.bar_ref - 1) * 100


def _first_at_or_after(sec: np.ndarray, prc: np.ndarray, t: int) -> float | None:
    j = int(np.searchsorted(sec, t, side="left"))
    return float(prc[j]) if j < len(sec) else None


def _last_before(sec: np.ndarray, prc: np.ndarray, t: int) -> float | None:
    j = int(np.searchsorted(sec, t, side="left")) - 1
    return float(prc[j]) if j >= 0 else None


def refine_entry(sec: np.ndarray, prc: np.ndarray, bar_start_sec: int, bar_ref: float) -> RefinedFill:
    return RefinedFill(bar_ref, _first_at_or_after(sec, prc, bar_start_sec), "봉 끝 이후 첫 체결")


def refine_exit(sec: np.ndarray, prc: np.ndarray, reason: ExitReason, bar_start_sec: int, bar_end_sec: int,
                bar_ref: float, line: float | None) -> RefinedFill:
    """청산 정밀화. 사유별로 봉 기준가에 대응하는 체결을 찾는다(모듈 docstring). line = 봉 엔진이 쓴 기준가(선/시가/종가)."""
    if reason in (ExitReason.STOP, ExitReason.TRAILING, ExitReason.TARGET) and line is not None:
        lo, hi = np.searchsorted(sec, [bar_start_sec, bar_end_sec], side="left")
        seg = prc[lo:hi].astype(float)
        hit = np.flatnonzero(seg <= line if reason != ExitReason.TARGET else seg >= line)
        # 갭으로 봉 시가가 이미 선을 넘었으면 봉 엔진은 시가에 체결 — 그 첫 체결(hit[0]==0)이 대응한다
        return RefinedFill(bar_ref, float(seg[hit[0]]) if len(hit) else None, "선을 처음 넘은 체결")
    if reason in (ExitReason.TIME, ExitReason.EOD, ExitReason.END_OF_DATA):
        return RefinedFill(bar_ref, _last_before(sec, prc, bar_end_sec), "봉의 마지막 체결")
    return RefinedFill(bar_ref, _first_at_or_after(sec, prc, bar_start_sec), "봉 끝 이후 첫 체결")  # 시그널 청산 = 다음 봉 시가


def repriced_net(cost: CostModel, qty: int, entry_ref: float, exit_ref: float) -> tuple[float, float]:
    """기준가(슬리피지 전) 두 개로 순손익(원)과 순수익률(소수)을 다시 계산 — 봉 쪽·틱 쪽에 같은 비용 모델을 얹기 위해."""
    p0, p1 = cost.buy_price(entry_ref), cost.sell_price(exit_ref)
    c0, c1 = p0 * qty * cost.commission_rate, p1 * qty * cost.commission_rate
    net = (p1 - p0) * qty - c0 - c1 - p1 * qty * cost.tax_rate
    return net, net / (p0 * qty)
