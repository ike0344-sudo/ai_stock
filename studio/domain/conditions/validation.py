"""조건 그룹 검증 — 모드·시간 단위·역할(진입/청산/시장 필터/사전 필터) 규칙. 설계 studio-conditions §3.1·§3.2·§6.

`Spec._check` 가 그룹마다 `validate_group` 을 부른다(오류는 ValueError → 400 VALIDATION_ERROR 의 fieldErrors). 규칙:
  · 일봉 모드(daily_single·daily_portfolio): 시간 단위는 bar 뿐.
  · 분봉 모드(intraday, tick 의 분봉 정밀화): mN 은 **실행 봉 길이의 배수이면서 더 긴 것**만, daily_prev·daily_live 는 일봉 지표.
    daily_live 는 catalog live=True 지표만(AST 가 지표 단위로 이미 막음), **거래량·거래대금 계열은 KRX 분봉에서만**(통합 분봉 + KRX 일봉을 섞으면 20~40% 부풀려짐).
  · 사전 필터(일봉 D−1 조건): 시간 단위 없음(일봉 그대로).
  · `pos`(포지션) 피연산자는 **청산 조건에서만** — 보유 전엔 값이 없어 진입·시장 필터·사전 필터에 쓰면 오류.
지표가 그 모드를 지원하는지(`IndicatorDef.modes`)도 여기서 본다(시간 단위가 일봉이면 일봉 모드 기준으로).
"""
from __future__ import annotations

from .ast import ExprOperand, FieldOperand, Group, IndOperand, PosOperand
from .catalog import INDICATORS, MINUTE_TIMEFRAMES

ROLES = ("entry", "exit", "market_filter", "prefilter")
_ROLE_KO = {"entry": "진입", "exit": "청산", "market_filter": "시장 필터", "prefilter": "사전 필터"}
_DAILY_MODES = ("daily_single", "daily_portfolio")


_ROLE_PATH = {"entry": "strategy.entry", "exit": "strategy.exit", "market_filter": "market_filter", "prefilter": "intraday.prefilter"}


def _walk(g: Group, path: str):
    """(경로, 잎 피연산자) — 경로는 명세 JSON 위치(예 `strategy.entry.items.0.left`, expr 안은 `.left.right` 처럼 이어짐)."""
    from .ast import Condition
    for i, it in enumerate(g.items):
        p = f"{path}.items.{i}"
        if isinstance(it, Group):
            yield from _walk(it, p)
        else:
            assert isinstance(it, Condition)
            for side in ("left", "right"):
                op = getattr(it, side)
                if op is not None:
                    yield from _leaves(op, f"{p}.{side}")


def _leaves(op, path: str):
    if isinstance(op, ExprOperand):
        yield from _leaves(op.left, path + ".left")
        yield from _leaves(op.right, path + ".right")
    else:
        yield path, op


def validate_group(g: Group, role: str, *, mode: str, bar_minutes: int = 5, source: str = "al") -> None:
    """오류 메시지는 `[strategy.entry.items.0.left] …` 로 **명세 JSON 경로**를 앞에 붙인다 — 화면이 그 조건 행을 빨갛게 한다."""
    if role not in ROLES:
        raise ValueError(f"role: {role!r}")
    intraday_run = mode in ("intraday", "tick")
    em = "daily_portfolio" if role == "prefilter" else ("intraday" if intraday_run else mode)
    for path, op in _walk(g, _ROLE_PATH[role]):
        try:
            _check_operand(op, role, em, intraday_run, bar_minutes, source)
        except ValueError as e:
            raise ValueError(f"[{path}] {e}") from None


def _check_operand(op, role: str, em: str, intraday_run: bool, bar_minutes: int, source: str) -> None:
    if isinstance(op, PosOperand):
        if role != "exit":
            raise ValueError(f"포지션 값(pos.{op.name})은 청산 조건에서만 쓸 수 있다 — {_ROLE_KO[role]} 조건에는 보유 종목이 없어 값이 없다")
        return
    if not isinstance(op, (FieldOperand, IndOperand)):
        return
    tf = op.tf
    name = op.name
    label = f"지표 '{name}'" if isinstance(op, IndOperand) else f"가격 '{name}'"
    if tf != "bar":
        if role == "prefilter":
            raise ValueError(f"사전 필터는 일봉(D−1) 조건이라 시간 단위를 쓸 수 없다({label}: {tf})")
        if not intraday_run:
            raise ValueError(f"{label} 에 시간 단위 '{tf}' — 일봉 모드에서는 시간 단위를 쓸 수 없다(bar 만). 시간 단위는 분봉 모드에서 고를 수 있다")
        if tf in MINUTE_TIMEFRAMES:
            n = MINUTE_TIMEFRAMES[tf]
            if n % bar_minutes or n <= bar_minutes:
                raise ValueError(f"{label} 의 시간 단위 '{tf}': 실행 봉({bar_minutes}분)의 배수이면서 더 긴 분봉만 쓸 수 있다"
                                 f"(가능: {[k for k, v in MINUTE_TIMEFRAMES.items() if v % bar_minutes == 0 and v > bar_minutes]})")
        if tf == "daily_live":
            volume_based = (INDICATORS[name].volume_based if isinstance(op, IndOperand) else name in ("volume", "value"))
            if volume_based and source != "krx":
                raise ValueError(f"{label} 의 일봉 장중(daily_live) — 거래량·거래대금 계열 일봉 실시간은 KRX 분봉에서만 쓸 수 있다"
                                 "(통합 분봉과 KRX 일봉을 섞으면 20~40% 부풀려진다). intraday.source 를 'krx' 로 하거나 일봉 전일(daily_prev)을 써라")
    # 지표가 이 (시간 단위별) 모드를 지원하나
    if isinstance(op, IndOperand):
        gm = "daily_portfolio" if tf in ("daily_prev", "daily_live") else em
        if gm not in INDICATORS[name].modes:
            raise ValueError(f"지표 '{name}' 는 '{gm}' 조건에서 쓸 수 없음 (가능: {list(INDICATORS[name].modes)})")
