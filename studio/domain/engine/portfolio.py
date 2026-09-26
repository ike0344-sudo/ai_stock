"""일봉 포트폴리오 엔진 — 설계서 §3.5 봉 안 처리 순서 1~9 (일반 모드).

입력: Panel + 진입/청산 bool 표(index=날짜, columns=종목코드 — **봉 t 종가 기준 신호**) + 규칙 dataclass.
신호는 다음 봉 시가에 체결된다. 엔진은 Spec·조건식을 모른다.

봉 t 에서 하는 일(순서 고정):
  1 전 봉 청산 신호·이월된 청산을 시가에 체결   2 전 봉 진입 후보를 순위대로 시가에 체결
  3 보유 종목 갭 손절/익절(시가)   4 봉 안 손절/익절/트레일링(선 가격)   5 트레일링 고점·MFE/MAE 갱신(판정 뒤)
  6 보유기간 종가 청산   9 종가 평가(MTM).   (7 분봉 eod 는 intraday 모듈 몫)
청산 확장(studio-conditions c2): 분할 익절(조각 = 같은 entry_id·slice 로 남는 Trade 행) · 종가 확인 익절(close) · 트레일링 발동 조건 ·
본전 손절 · 포지션(pos) 조건 청산(봉 t 종가 평가 → 다음 봉 시가, `pos_exit` 계획을 5·6 뒤에 보유 종목마다 부른다).
트레일링 발동·본전 이동은 고점 갱신(5)과 같은 자리에서 — **다음 봉부터** 적용(봉 안 순서를 모르므로 이 봉 판정엔 안 쓴다).
상하한가로 잠긴 가격에는 체결 안 됨 — 매수는 그날 취소(upper_limit), 매도는 다음 봉으로 이월.

거래 불가 봉: 시가가 NaN 이거나 거래량이 0(거래정지 — 일봉 캐시는 정지일을 직전 종가로 채우고 거래량 0)이면
그 봉엔 체결하지 않는다(매수 no_data, 청산·판정은 다음 거래 가능 봉으로).

알려진 근사: ① 봉 안 순서 미상(same_bar_policy) ② 거래량 한도는 전 봉(신호 봉) 거래량 기준
(전 봉 거래량 결측/0 이면 한도 0 → volume_cap 으로 막는다) ③ 체결가는 호가단위로 반올림하지 않는다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ..costs import CostModel
from ..market_rules import is_price_limit_locked
from ..models import BacktestResult, ExitReason, Fill, Panel, Position, Trade
from .fills import ExitRules, FillRules, downside_line, entry_levels, entry_lines, judge_gap, judge_intrabar, level_qty
from .intraday import SessionRules

SIZINGS = ("equal_slot_fixed", "equal_slot_compound", "fixed_amount", "risk_pct")
RANKS = ("value", "change_pct", "random", "none")


@dataclass(frozen=True)
class PortfolioRules:
    initial_capital: float = 10_000_000
    max_positions: int = 5
    sizing: str = "equal_slot_fixed"
    fixed_amount: float | None = None
    risk_pct: float | None = None  # 평가금 대비 1회 손절 시 손실 % (손절선 필수)
    max_weight_pct: float | None = None  # 한 종목 상한 (평가금 대비 %)
    rank_by: str = "value"  # 진입 후보가 슬롯보다 많을 때 우선순위 — 전 봉 거래대금 큰 순 / 전 봉 등락률 큰 순 / 무작위 / 열 순서
    random_seed: int = 42

    def __post_init__(self) -> None:
        if self.sizing not in SIZINGS:
            raise ValueError(f"sizing: {self.sizing!r}")
        if self.rank_by not in RANKS:
            raise ValueError(f"rank_by: {self.rank_by!r}")
        if self.max_positions < 1:
            raise ValueError("max_positions >= 1")
        if self.sizing == "fixed_amount" and not self.fixed_amount:
            raise ValueError("fixed_amount 사이징엔 fixed_amount 가 필요")
        if self.sizing == "risk_pct" and not self.risk_pct:
            raise ValueError("risk_pct 사이징엔 risk_pct 가 필요")


def _aligned(df: pd.DataFrame | None, like: pd.DataFrame, fill) -> np.ndarray:
    if df is None:
        return np.full(like.shape, fill)
    return df.reindex(index=like.index, columns=like.columns).fillna(fill).to_numpy()


def run_portfolio(
    panel: Panel,
    entries: pd.DataFrame,
    exits: pd.DataFrame | None,
    costs: CostModel,
    exit_rules: ExitRules,
    fill_rules: FillRules,
    portfolio: PortfolioRules,
    session: SessionRules | None = None,
    pos_exit: Any = None,
) -> BacktestResult:
    if portfolio.sizing == "risk_pct" and exit_rules.stop_loss_pct is None:
        raise ValueError("risk_pct 사이징은 stop_loss_pct 가 있어야 한다")

    idx, codes = panel.close.index, list(panel.close.columns)
    n, m = panel.close.shape
    O = _aligned(panel.open, panel.close, np.nan).astype(float)
    H = _aligned(panel.high, panel.close, np.nan).astype(float)
    L = _aligned(panel.low, panel.close, np.nan).astype(float)
    C = panel.close.to_numpy(dtype=float)
    V = _aligned(panel.volume, panel.close, 0.0).astype(float)
    VAL = _aligned(panel.value, panel.close, 0.0).astype(float)
    PC = _aligned(panel.prev_close, panel.close, np.nan).astype(float)
    ENT = _aligned(entries, panel.close, False).astype(bool)
    EXT = _aligned(exits, panel.close, False).astype(bool)

    tradable = ~np.isnan(O) & (V > 0)
    if session is not None:  # 분봉: EOD 이후 봉은 거래 불가(15:30 종가 단일가 봉 등) — 신호·MTM 만 흐른다
        tradable &= ~session.after_eod[:, None]
    valid_close = ~np.isnan(C)
    last_valid = np.where(valid_close.any(axis=0), n - 1 - np.argmax(valid_close[::-1], axis=0), -1)
    rng = np.random.default_rng(portfolio.random_seed)

    cash = float(portfolio.initial_capital)
    last_close = np.full(m, np.nan)
    pos: dict[int, Position] = {}
    ext: dict[int, list] = {}  # c -> [entry_ref, max_high, min_low]
    pending: dict[int, ExitReason] = {}  # 잠겨서 이월된 청산
    pstate: dict[int, dict] = {}  # 보유 종목별 pos 조건 상태(pos_exit 이 있을 때)
    pos_sig: set[int] = set()  # 전 봉 종가에 pos 청산 조건이 참이었던 종목 → 이 봉 시가에 판다
    tp_close: dict[int, int] = {}  # 종가 확인 익절: 전 봉 종가가 넘은 선 개수(앞에서부터) → 이 봉 시가에 판다
    next_entry_id = 0
    if pos_exit is not None and tuple(pos_exit.shape) != (n, m):
        raise ValueError(f"pos_exit 표 모양 {tuple(pos_exit.shape)} 이 패널 {(n, m)} 과 다르다")
    bar_min = getattr(pos_exit, "bar_minutes", None)
    trades: list[Trade] = []
    fills: list[Fill] = []
    skipped = {"slots_full": 0, "cash": 0, "upper_limit": 0, "volume_cap": 0, "no_data": 0}
    eq_rows: list[tuple] = []
    diag = {"carried_exits": 0, "end_of_data": [], "entry_signals": int(ENT.sum())}

    comm = costs.commission_rate

    def mtm() -> float:
        return sum(p.qty * last_close[c] for c, p in pos.items() if not np.isnan(last_close[c]))

    def close_pos(c: int, i: int, ref: float, reason: ExitReason, full_bar: bool, qty: int | None = None) -> None:
        """전량(qty=None 이거나 보유 수량 이상) 또는 일부(분할 익절 조각)를 판다 — 일부면 포지션은 남는다."""
        nonlocal cash
        p = pos[c]
        e = ext[c]
        full = qty is None or qty >= p.qty
        q = p.qty if full else qty
        if full_bar:  # 이 봉을 보유한 것으로 센다 — 고저도 MFE/MAE 에 반영 (봉 안 순서 미상 — 약간 과대)
            e[1], e[2] = max(e[1], H[i, c]), min(e[2], L[i, c])
        price = costs.sell_price(ref)
        gross_amt = price * q
        commission, tax = gross_amt * comm, gross_amt * costs.tax_rate
        cash += gross_amt - commission - tax
        held = p.bars_held + (1 if full_bar else 0)
        sell_slip = (ref - price) * q
        fills.append(Fill(idx[i], codes[c], "sell", q, price, ref, commission, tax, sell_slip, reason.value))
        entry_comm = p.entry_costs if full else p.entry_costs * q / p.qty  # 매수 수수료는 판 수량만큼 나눠 싣는다
        gross = (price - p.entry_price) * q
        total_comm = entry_comm + commission
        net = gross - total_comm - tax
        p.slices += 1
        trades.append(Trade(
            code=codes[c], entry_ts=p.entry_ts, entry_price=p.entry_price, exit_ts=idx[i], exit_price=price,
            qty=q, gross_pnl=gross, commission=total_comm, tax=tax, slippage_cost=sell_slip + (p.entry_price - e[0]) * q, net_pnl=net,
            net_pct=net / (p.entry_price * q), exit_reason=reason, bars_held=held,
            mfe_pct=(e[1] / p.entry_price - 1) * 100, mae_pct=(e[2] / p.entry_price - 1) * 100,
            entry_id=p.entry_id, slice=p.slices,
        ))
        if full:
            pos.pop(c)
            ext.pop(c)
            pending.pop(c, None)
            pstate.pop(c, None)
            tp_close.pop(c, None)
            pos_sig.discard(c)
        else:
            p.entry_costs -= entry_comm
            p.qty -= q

    def sell_levels(c: int, i: int, k: int, ref_of, full_bar: bool) -> None:
        """앞에서 k 개 익절 선을 차례로 판다(남은 수량 × 비율). ref_of(선 가격) = 체결 기준가. 잠겼으면 그 선은 건너뛴다(선이 남아 다음 봉에 다시 판정)."""
        p = pos[c]
        done = 0
        for _ in range(k):
            px, fr = p.tp_levels[done]
            ref = ref_of(px)
            if is_price_limit_locked(ref, PC[i, c]):
                break
            done += 1
            q = level_qty(p.qty, fr)
            close_pos(c, i, ref, ExitReason.TARGET, full_bar, q)
            if c not in pos:  # 전량 소진
                return
        del p.tp_levels[:done]

    def try_sell(c: int, i: int, ref: float, reason: ExitReason, full_bar: bool) -> bool:
        """잠겼으면 이월하고 False."""
        if is_price_limit_locked(ref, PC[i, c]):
            pending[c] = reason
            diag["carried_exits"] += 1
            return False
        close_pos(c, i, ref, reason, full_bar)
        return True

    def _levels_bar(c: int, i: int, p: Position, held: bool):
        """분할 익절 선이 있는 종목의 갭·봉 안 판정. 익절 선은 그 자리에서 조각으로 팔고(남은 수량 × 비율),
        전량 청산이 필요하면 (기준가, 사유) 를 돌려준다(손절·트레일링). 손절선과 익절 선이 한 봉에 다 닿으면 same_bar_policy —
        stop_first: 전량 손절 / target_first: 선에 닿은 만큼 먼저 팔고, 남은 수량은 그 봉 손절선(닿았으면)에 판다."""
        line, why = downside_line(p, exit_rules)
        if held:  # 갭 — 시가가 이미 손절선 아래면 전량 시가 청산, 선 위면 넘은 선들을 시가에
            if line is not None and O[i, c] <= line:
                return O[i, c], why
            k = sum(1 for px, _ in p.tp_levels if O[i, c] >= px)
            if k:
                sell_levels(c, i, k, lambda px: O[i, c], full_bar=True)
                if c not in pos:
                    return None
        reached = sum(1 for px, _ in p.tp_levels if H[i, c] >= px)
        down = line is not None and L[i, c] <= line
        if reached and not (down and fill_rules.same_bar_policy == "stop_first"):
            sell_levels(c, i, reached, lambda px: px, full_bar=True)
            if c not in pos:
                return None
        return (line, why) if down else None

    for i in range(n):
        equity_prev = cash + mtm()  # 전 봉 종가 평가금 — 사이징 기준(당일 값 안 씀)
        blocked: set[int] = set()

        # 1 — 전 봉 청산 신호 + 이월분, 시가 체결
        if i > 0:
            for c in list(pos):
                reason = pending.get(c) or (ExitReason.SIGNAL if (EXT[i - 1, c] or c in pos_sig) else None)
                if reason is None:
                    if c in tp_close and tradable[i, c]:  # 종가 확인 익절 — 전 봉 종가가 선을 넘었다: 시가에 그 선(들)만큼
                        sell_levels(c, i, tp_close.pop(c), lambda px: O[i, c], full_bar=False)
                    continue
                if not tradable[i, c]:
                    pending[c] = reason  # 거래정지·결측 — 다음 봉으로
                    blocked.add(c)
                elif not try_sell(c, i, O[i, c], reason, full_bar=False):
                    blocked.add(c)
        pos_sig = set()
        held_before = set(pos)

        # 2 — 전 봉 진입 후보, 순위 순
        if i > 0:
            cand = np.flatnonzero(ENT[i - 1] & ~EXT[i - 1]) if (
                session is None or session.day_id[i] == session.day_id[i - 1]) else np.array([], dtype=int)  # 분봉: 날 경계 넘는 체결 없음
            cand = np.array([c for c in cand if c not in pos], dtype=int)
            if cand.size:
                if portfolio.rank_by == "value":
                    cand = cand[np.argsort(-VAL[i - 1, cand], kind="stable")]
                elif portfolio.rank_by == "change_pct":  # 전 봉 종가 등락률(전일 종가 대비) 큰 순
                    chg = C[i - 1, cand] / PC[i - 1, cand] - 1
                    cand = cand[np.argsort(-np.nan_to_num(chg, nan=-np.inf), kind="stable")]
                elif portfolio.rank_by == "random":
                    cand = rng.permutation(cand)
                for k, c in enumerate(cand):
                    o = O[i, c]
                    if not tradable[i, c]:
                        skipped["no_data"] += 1
                        continue
                    if len(pos) >= portfolio.max_positions:
                        skipped["slots_full"] += len(cand) - k
                        break
                    if is_price_limit_locked(o, PC[i, c]):
                        skipped["upper_limit"] += 1
                        continue
                    price = costs.buy_price(o)
                    qty = _size(portfolio, exit_rules, equity_prev, cash, price, comm)
                    if qty <= 0:
                        skipped["cash"] += 1
                        continue
                    if fill_rules.volume_cap_pct is not None:
                        qty = min(qty, int(V[i - 1, c] * fill_rules.volume_cap_pct / 100))  # 전 봉(신호 봉) 거래량 — 체결 봉 값은 시가에 모른다
                        if qty <= 0:
                            skipped["volume_cap"] += 1
                            continue
                    commission = price * qty * comm
                    cash -= price * qty + commission
                    stop, target, peak = entry_lines(price, exit_rules)
                    pos[c] = Position(codes[c], qty, idx[i], price, stop, target, peak, 0, commission,
                                      entry_id=next_entry_id, tp_levels=entry_levels(price, exit_rules),
                                      trail_on=exit_rules.trail_activate_pct is None)
                    next_entry_id += 1
                    if pos_exit is not None:
                        pstate[c] = pos_exit.new_state()
                    ext[c] = [o, -math.inf, math.inf]
                    fills.append(Fill(idx[i], codes[c], "buy", qty, price, o, commission, 0.0,
                                      (price - o) * qty, "entry"))

        # 3·4 — 갭, 봉 안 손절/익절/트레일링 (이번 시가에 산 종목도 4 는 판정)
        for c in list(pos):
            if c in blocked or not tradable[i, c] or np.isnan(H[i, c]) or np.isnan(L[i, c]):
                continue
            p = pos[c]
            if p.tp_levels and exit_rules.take_profit_mode == "intrabar":
                hit = _levels_bar(c, i, p, c in held_before)
                if c not in pos:
                    continue
            else:
                hit = judge_gap(O[i, c], p, exit_rules) if c in held_before else None
                if hit is None:
                    hit = judge_intrabar(H[i, c], L[i, c], p, exit_rules, fill_rules.same_bar_policy)
            if hit is not None:
                if not try_sell(c, i, hit[0], hit[1], full_bar=True):
                    blocked.add(c)

        # 5·6 — 남은 종목: 트레일링 고점·MFE/MAE 갱신(판정 뒤), 보유기간
        for c in list(pos):
            p = pos[c]
            if not (np.isnan(H[i, c]) or np.isnan(L[i, c])):
                if p.trail_peak is not None:
                    p.trail_peak = max(p.trail_peak, H[i, c])
                ext[c][1], ext[c][2] = max(ext[c][1], H[i, c]), min(ext[c][2], L[i, c])
                # 트레일링 발동·본전 이동 — 최고 수익률(고가 기준, 이 봉 포함)이 문턱을 넘었으면 **다음 봉부터** 적용
                if not p.trail_on and ext[c][1] >= p.entry_price * (1 + exit_rules.trail_activate_pct / 100):
                    p.trail_on = True
                if (exit_rules.breakeven_after_pct is not None and (p.stop is None or p.stop < p.entry_price)
                        and ext[c][1] >= p.entry_price * (1 + exit_rules.breakeven_after_pct / 100)):
                    p.stop = p.entry_price
            if c in blocked or not tradable[i, c] or np.isnan(C[i, c]):
                continue
            held = p.bars_held + 1
            if exit_rules.max_holding_bars is not None and held >= exit_rules.max_holding_bars:
                if not try_sell(c, i, C[i, c], ExitReason.TIME, full_bar=True):
                    p.bars_held = held
                    blocked.add(c)
                continue
            p.bars_held = held
            if p.tp_levels and exit_rules.take_profit_mode == "close":  # 종가가 넘은 선 개수 — 다음 봉 시가에 판다
                k = sum(1 for px, _ in p.tp_levels if C[i, c] >= px)
                if k:
                    tp_close[c] = k

        # 분봉 EOD 봉 — 남은 포지션을 이 봉 종가에 청산(잠김이면 이월 → 다음 날 첫 봉)
        if session is not None and session.eod_bar[i]:
            for c in list(pos):
                if c not in blocked and tradable[i, c] and not np.isnan(C[i, c]):
                    try_sell(c, i, C[i, c], ExitReason.EOD, full_bar=True)

        # 데이터 끝 — 그 종목 마지막 봉이면 종가 청산(잠김 무시: 데이터가 없어 이월할 다음 봉이 없다)
        for c in list(pos):
            if last_valid[c] == i:
                diag["end_of_data"].append(codes[c])
                close_pos(c, i, C[i, c], ExitReason.END_OF_DATA, full_bar=True)

        # 7b — pos 조건 청산: 남은 보유 종목마다 봉 t 종가 기준으로 평가(신호는 다음 봉 시가에 체결) — 매 보유 봉 불러야 상태(cross·hold)가 이어진다
        if pos_exit is not None:
            for c in list(pos):
                if c in blocked or not tradable[i, c] or np.isnan(C[i, c]):
                    continue
                p = pos[c]
                mx = ext[c][1]
                vals = {"return_pct": (C[i, c] / p.entry_price - 1) * 100, "bars_held": float(p.bars_held),
                        "minutes_held": p.bars_held * bar_min if bar_min else float("nan"),
                        "max_return_pct": (mx / p.entry_price - 1) * 100 if mx > -math.inf else float("nan"),
                        "drawdown_pct": (1 - C[i, c] / mx) * 100 if mx > 0 else float("nan"),
                        "entry_price": p.entry_price}
                if pos_exit.decide(i, c, pstate[c], vals):
                    pos_sig.add(c)

        # 9 — 종가 평가
        ok = ~np.isnan(C[i])
        last_close[ok] = C[i][ok]
        pv = mtm()
        eq_rows.append((idx[i], cash, pv, cash + pv, len(pos)))

    equity = pd.DataFrame(eq_rows, columns=["ts", "cash", "positions_value", "equity", "n_positions"])
    return BacktestResult(trades=trades, equity=equity, fills=fills, skipped=skipped, diagnostics=diag)


def _size(pr: PortfolioRules, ex: ExitRules, equity_prev: float, cash: float, price: float, comm: float) -> int:
    """사이징 4종 → 수량. 전부 max_weight_pct·가용 현금으로 상한. 수수료까지 감당되는 수량만."""
    if pr.sizing == "equal_slot_fixed":
        amount = pr.initial_capital / pr.max_positions
    elif pr.sizing == "equal_slot_compound":
        amount = equity_prev / pr.max_positions
    elif pr.sizing == "fixed_amount":
        amount = pr.fixed_amount
    else:  # risk_pct: 손절 시 손실 = 평가금 × risk%
        risk_per_share = price * ex.stop_loss_pct / 100
        amount = math.floor(equity_prev * pr.risk_pct / 100 / risk_per_share) * price
    if pr.max_weight_pct is not None:
        amount = min(amount, equity_prev * pr.max_weight_pct / 100)
    amount = min(amount, cash)
    return int(amount // (price * (1 + comm)))
