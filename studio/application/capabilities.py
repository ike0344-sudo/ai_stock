"""서버가 지금 무엇을 이해하는가 — 조건식 확장(studio-conditions c1·c2·c3)이 들어오는 대로 화면이 저절로 켜지게 한다.

화면이 "서버가 모르는 칸"을 보내면 검증 오류가 나므로, 새 칸(시간 단위 `tf`·`hold`·`negate`·`pos` 피연산자·청산 규칙 새 칸)은
**모델에 실제로 있을 때만** 켠다. 모델 정의를 직접 들여다보므로(introspection) 이 파일은 c1·c2 가 어떻게 구현되든 고칠 것이 없다.
"""
from __future__ import annotations

from typing import Any, Iterable, get_args

from studio.domain.conditions import ast, catalog
from studio.domain.spec import Exits

# 설계서 studio-conditions §3.1 — 카탈로그가 자기 목록(TIMEFRAMES)을 주면 그것을, 없으면 이 목록을 쓴다
DEFAULT_TIMEFRAMES = ("bar", "m1", "m3", "m5", "m10", "m15", "m30", "m60", "daily_prev", "daily_live")


def ops() -> list[str]:
    """조건 모델이 실제로 받는 연산자(Literal) — c1 이 새 연산자를 넣으면 저절로 늘어난다."""
    return list(get_args(ast.Condition.model_fields["op"].annotation))


def capabilities(route_paths: Iterable[str] = ()) -> dict[str, Any]:
    """route_paths: 이 서버에 실제로 붙은 경로들 — 수식 저장소(/api/formulas)가 있는지 알려 준다(없으면 화면이 요청조차 안 보낸다)."""
    ind_fields = set(ast.IndOperand.model_fields)
    kinds = ["field", "ind", "market", "const"] + [k for k, cls in (("expr", "ExprOperand"), ("pos", "PosOperand")) if hasattr(ast, cls)]
    return {
        "timeframes": list(getattr(catalog, "TIMEFRAMES", DEFAULT_TIMEFRAMES)) if "tf" in ind_fields else None,
        "condition_fields": [f for f in ("hold",) if f in ast.Condition.model_fields],
        "group_fields": [f for f in ("negate",) if f in ast.Group.model_fields],
        "operand_kinds": kinds,
        "pos_names": list(getattr(catalog, "POS_NAMES", ())) if "pos" in kinds else [],
        "formulas": any(p.startswith("/api/formulas") for p in route_paths),
        "exit_fields": sorted(set(Exits.model_fields) - {"stop_loss_pct", "take_profit_pct", "trailing_stop_pct", "max_holding_bars"}),
    }


def unmet_needs(needs: list[str], caps: dict[str, Any], indicators: dict[str, Any], ops: list[str]) -> list[str]:
    """레시피가 요구하는 것 중 서버가 아직 못 하는 것(사람 말). 비면 쓸 수 있다."""
    out: list[str] = []
    for n in needs:
        kind, _, arg = n.partition(":")
        if kind == "timeframes" and caps["timeframes"] is None:
            out.append("시간 단위 선택(일봉 지표를 분봉에서 쓰기)")
        elif kind == "indicator" and not (arg in indicators and indicators[arg].compute):
            out.append(f"지표 '{arg}'")
        elif kind == "op" and arg not in ops:
            out.append(f"연산자 '{arg}'")
        elif kind == "pos" and "pos" not in caps["operand_kinds"]:
            out.append("포지션 피연산자")
        elif kind == "exit_field" and arg not in caps["exit_fields"]:
            out.append(f"청산 규칙 '{arg}'")
    return out
