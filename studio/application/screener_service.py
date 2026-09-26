"""오늘 조건에 맞는 종목 — `POST /api/conditions/preview` (설계서 §4.2, §5.4 "[오늘 조건 맞는 종목]").

**최신 거래일 기준**: 그날 종가까지 알 수 있는 진입 조건을 평가해 신호가 켜진 종목을 돌려준다(체결·수익 계산 없음 —
"이 조건이 오늘 어떤 종목을 잡는가"를 눈으로 확인하는 용도). 일봉 모드(daily_single·daily_portfolio)만 — 분봉·틱은 module-6.
유니버스는 백테스트와 같은 규칙(`eligible_codes`)과 거래대금 순위(`value_rank`)를 그대로 쓴다.
조건식이면 진입 조건의 **피연산자 값**(예: 종가 12,300 > 20일 최고가 12,000)도 붙인다. 기존 전략은 신호 여부만.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from studio.domain.conditions.ast import Condition, ConstOperand, Group, iter_conditions
from studio.domain.conditions.evaluator import _operand, evaluate_group
from studio.domain.conditions.indicators import gap_columns, value_rank
from studio.domain.narration import _operand as narrate_operand
from studio.domain.spec import BuilderStrategy, LegacyStrategy, Spec, bind_params

from .backtest_service import WARMUP_BARS, BacktestError, ModeNotSupportedError, eligible_codes
from .ports import LegacyStrategies, MarketData

DAILY_MODES = ("daily_single", "daily_portfolio")


def _operand_values(entry: Group, panel: Any, market: Any, code: str, row: pd.Timestamp) -> list[dict[str, Any]]:
    """진입 조건마다 왼쪽·오른쪽 피연산자의 그날 값."""
    gaps = gap_columns(panel.close)
    out = []
    for c in iter_conditions(entry):
        vals = []
        for op in (c.left, c.right):
            if isinstance(op, ConstOperand):
                v: Any = float(op.value)
            else:
                frame = _operand(op, panel, market, gaps)
                v = float(frame.at[row, code]) if isinstance(frame, pd.DataFrame) else float(frame)
            vals.append(None if (isinstance(v, float) and not np.isfinite(v)) else v)
        out.append({"text": _cond_text(c), "left": vals[0], "right": vals[1]})
    return out


def _cond_text(c: Condition) -> str:
    sym = {"gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "cross_above": "↗ 상향 돌파", "cross_below": "↘ 하향 돌파"}[c.op]
    return f"{narrate_operand(c.left, '일')} {sym} {narrate_operand(c.right, '일')}"


def preview(spec: Spec, market_data: MarketData, legacy: LegacyStrategies | None = None, limit: int = 50) -> dict[str, Any]:
    if spec.mode not in DAILY_MODES:
        raise ModeNotSupportedError(f"'{spec.mode}' 모드의 오늘 종목 미리보기는 아직 지원하지 않는다(일봉 모드만)")
    bound = bind_params(spec)
    strat = bound.strategy
    if isinstance(strat, LegacyStrategy) and legacy is None:
        raise BacktestError("기존 전략을 쓰려면 legacy 어댑터가 필요하다")
    ranges = market_data.data_ranges()
    last_day = ranges["daily"][1]
    want = list(bound.universe.codes) if bound.universe.type == "codes" else None
    panel = market_data.load_panel(last_day, last_day, WARMUP_BARS, want)
    if panel.close.empty:
        raise BacktestError("최신 일봉이 없다")
    codes, ustats = eligible_codes(bound, market_data.stock_info(), market_data.mega_cap_codes(), list(panel.close.columns))
    if not codes:
        raise BacktestError("유니버스에 종목이 없다 (조건·제외 규칙 확인)")
    day = panel.close.index[-1]
    sub = type(panel)(*(getattr(panel, k)[codes] for k in ("open", "high", "low", "close", "volume", "value", "prev_close")))
    market = market_data.index_frames()
    if isinstance(strat, BuilderStrategy):
        entry = evaluate_group(strat.entry, sub, market=market)
        if bound.market_filter is not None:
            entry = entry & evaluate_group(bound.market_filter, sub, market=market)
    else:
        entry = legacy.evaluate(strat.name, strat.params, sub).entry
        if bound.market_filter is not None:
            entry = entry & evaluate_group(bound.market_filter, sub, market=market)
    rank = value_rank(sub.value, bound.universe.lookback_days)
    if bound.universe.type == "top_value":
        entry = entry & (rank <= bound.universe.n)
    hit = entry.loc[day]
    matched = [c for c in codes if bool(hit.get(c, False))]
    info = market_data.stock_info()
    rows = []
    for c in matched:
        close = float(sub.close.at[day, c])
        prev = float(sub.prev_close.at[day, c]) if pd.notna(sub.prev_close.at[day, c]) else None
        row: dict[str, Any] = {
            "code": c, "name": (info["name"].get(c) if c in info.index else None), "close": close,
            "change_pct": ((close / prev - 1) * 100) if prev else None,
            "value": float(sub.value.at[day, c]), "value_rank": (int(rank.at[day, c]) if pd.notna(rank.at[day, c]) else None),
        }
        if isinstance(strat, BuilderStrategy):
            row["operands"] = _operand_values(strat.entry, sub, market, c, day)
        rows.append(row)
    rows.sort(key=lambda r: -r["value"])
    return {"date": str(day.date()), "universe_size": len(codes), "matched": len(rows), "rows": rows[:limit],
            "truncated": len(rows) > limit, "universe_excluded": ustats}
