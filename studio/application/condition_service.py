"""명세 검증 — `POST /api/conditions/validate` (설계서 §4.1, §5.4 "[검증] 오류 목록", §8.4 #8).

오류마다 **경로**를 돌려줘서 화면이 조건 행을 강조한다: `strategy.entry.items.0.left.name` 처럼 점으로 이은 위치.
pydantic 의 판별 태그(`builder`·`ind`·`Condition` 등)는 사용자에게 의미가 없어 경로에서 뺀다.
형식이 맞으면 의미 검사(변수 기본값 범위·데이터 기간)까지 하고, 통과하면 풀이 문장을 붙인다.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from studio.domain.narration import narrate
from studio.domain.spec import Spec, bind_params, validate_against

from .ports import MarketData

_TAGS = {"builder", "legacy", "field", "ind", "market", "const"}  # 판별 유니온 태그 — 실제 키 이름과 겹치지 않는다
_WRAPPER = re.compile(r"^(function-(after|before|wrap|plain)|list|dict|tuple|union)\[")  # pydantic 이 끼우는 내부 표지
_BRANCH = re.compile(r"(Condition|Group)\]$")


def _raw_at(raw: Any, loc: tuple[Any, ...]) -> Any:
    cur = raw
    for part in loc:
        try:
            cur = cur[part]
        except (KeyError, IndexError, TypeError):
            return None
    return cur


def _wrong_branch(loc: tuple[Any, ...], raw: Any) -> bool:
    """`Condition | Group` 유니온은 두 갈래를 다 시도해서 **틀린 갈래의 오류도** 낸다("Field required: logic" 같은 잡음).
    입력에 `logic` 키가 있으면 그룹, 아니면 조건으로 보고 반대 갈래 오류를 버린다."""
    for i, part in enumerate(loc):
        m = _BRANCH.search(part) if isinstance(part, str) and _WRAPPER.match(part) else None
        if m:
            item = _raw_at(raw, loc[:i])
            is_group = isinstance(item, dict) and "logic" in item
            if (m.group(1) == "Group") != is_group:
                return True  # 중첩 그룹이면 갈래 표지가 여러 개 — 하나라도 어긋나면 잡음
    return False


def _clean_loc(loc: tuple[Any, ...]) -> list[Any]:
    return [p for p in loc if not (isinstance(p, str) and (p in _TAGS or _WRAPPER.match(p)))]


def _message(msg: str) -> str:
    for prefix in ("Value error, ", "Assertion failed, "):
        if msg.startswith(prefix):
            return msg[len(prefix):]
    return msg


def field_errors(exc: ValidationError, raw: Any = None) -> list[dict[str, Any]]:
    """pydantic 오류 → {path, loc, message}. raw(요청 본문)가 있으면 유니온의 틀린 갈래 오류를 걸러낸다."""
    out = []
    for e in exc.errors(include_url=False, include_context=False, include_input=False):
        full = tuple(e.get("loc", ()))
        if raw is not None and _wrong_branch(full, raw):
            continue
        loc = _clean_loc(full)
        msg = _message(str(e.get("msg", "")))
        if not loc:  # 모델 전체 검사(Spec._check)의 오류는 위치가 없다 — 메시지 머리의 [경로] 나 칸 이름으로 짐작해 화면이 강조할 자리를 준다
            loc, msg = _split_bracket(msg)
            if not loc:
                loc = _infer_loc(msg)
        out.append({"path": ".".join(str(p) for p in loc), "loc": loc, "message": msg})
    return out


_HEAD_PATH = re.compile(r"^((?:strategy|period|universe|exits|portfolio|costs|fills|intraday|tick|compat|market_filter|validation)"
                        r"(?:\.[A-Za-z_]+)*)")
_PARAM_NAME = re.compile(r"^변수 '([A-Za-z_][A-Za-z0-9_]*)'")


_BRACKET = re.compile(r"^\[([^\]]+)\]\s*")


def _split_bracket(msg: str) -> tuple[list[Any], str]:
    """조건식 검증은 오류 머리에 명세 경로를 붙여 준다(`[strategy.entry.items.0.right] …`, c1 확정) — 경로를 떼어 loc 으로, 메시지는 본문만."""
    m = _BRACKET.match(msg)
    if not m:
        return [], msg
    return [int(p) if p.isdigit() else p for p in m.group(1).split(".")], msg[m.end():]


def _infer_loc(msg: str) -> list[Any]:
    m = _PARAM_NAME.match(msg)
    if m:
        return ["params", m.group(1)]
    m = _HEAD_PATH.match(msg)
    return m.group(1).split(".") if m else []


def validate_spec(raw: Any, market_data: MarketData | None = None) -> dict[str, Any]:
    """{ok, errors[], warnings[], narration}. 데이터 기간 검사는 market_data 가 있을 때만."""
    try:
        spec = Spec.model_validate(raw)
    except ValidationError as exc:
        return {"ok": False, "errors": field_errors(exc, raw), "warnings": [], "narration": None}
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    try:
        bound = bind_params(spec)  # 변수 기본값을 채워 다시 검증
    except (ValueError, ValidationError) as exc:
        if isinstance(exc, ValidationError):
            errs = field_errors(exc)
            return {"ok": False, "errors": errs or [{"path": "params", "loc": ["params"], "message": str(exc)}], "warnings": [], "narration": None}
        loc, msg = _split_bracket(str(exc))
        return {"ok": False, "errors": [{"path": ".".join(str(p) for p in (loc or ["params"])), "loc": loc or ["params"], "message": msg}],
                "warnings": [], "narration": None}
    if market_data is not None:
        try:
            for p in validate_against(bound, market_data.data_ranges()):
                (errors if p.severity == "error" else warnings).append(
                    {"path": "period", "loc": ["period"], "dataset": p.dataset, "message": p.message})
        except Exception as exc:  # 데이터 범위를 못 읽어도 형식 검사 결과는 준다
            warnings.append({"path": "period", "loc": ["period"], "dataset": "daily", "message": f"데이터 범위 확인 실패: {exc}"})
    try:
        text = narrate(spec)
    except Exception:  # 풀이 실패는 검증 실패가 아니다
        text = None
    return {"ok": not errors, "errors": errors, "warnings": warnings, "narration": text}
