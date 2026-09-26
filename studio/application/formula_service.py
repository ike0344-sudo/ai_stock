"""사용자 수식 서비스 — 검사(`check`)·저장·불러오기 (설계서 §3.5·§4). 해석은 domain/formula.py, 저장은 FormulaStore 포트.

`check` 는 두 단계다: ① 문법·이름·범위(FormulaError — 줄·칸·예상) ② 나온 AST 가 명세 형식(`Group`)에 맞는지(pydantic —
시간 단위·산술 같은 새 칸을 AST 가 아직 못 받으면 여기서 걸린다). 저장은 ① 을 통과해야 하고, 불러올 때는 **컴파일된 AST 를 함께**
돌려준다 — 화면이 그걸 명세에 박아 넣어서, 수식 파일이 나중에 바뀌어도 옛 실행 결과는 그대로다(§3.5).
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol

from pydantic import ValidationError

from studio.domain.conditions.ast import Group
from studio.domain.conditions.formula import FormulaError, compile_formula
from studio.domain.narration import narrate_group


class FormulaNotFound(Exception):
    pass


class FormulaStore(Protocol):
    def list(self) -> list[dict[str, Any]]: ...

    def get(self, name: str) -> dict[str, Any]: ...

    def put(self, name: str, text: str, description: str = "") -> dict[str, Any]: ...

    def delete(self, name: str) -> None: ...


def check(text: Any, unit: str = "일") -> dict[str, Any]:
    """{ok, ast, error, errors, narration}. 문법 오류는 error(줄·칸·예상), 형식 오류는 errors[](경로·메시지). 항상 값을 돌려준다.
    narration(풀이 문장)은 만들 수 없으면 None — 풀이 실패는 검사 실패가 아니다. unit: 일봉 "일" · 분봉·틱 "봉"."""
    try:
        ast = {**compile_formula(text), "formula": text}  # 원문도 같이 — 명세에 박으면 재현된다(평가·해시는 무시, Group.formula)
    except FormulaError as exc:
        return {"ok": False, "ast": None, "error": exc.to_dict(), "errors": [], "narration": None}
    try:
        group = Group.model_validate(ast)
    except ValidationError as exc:
        errs = [{"path": ".".join(str(p) for p in e.get("loc", ())), "message": str(e.get("msg", "")).removeprefix("Value error, ")}
                for e in exc.errors(include_url=False, include_context=False, include_input=False)]
        return {"ok": False, "ast": ast, "error": None, "errors": errs, "narration": None}
    try:
        text_ko: str | None = narrate_group(group, unit)
    except Exception:  # 풀이 문장 규칙이 새 칸(시간 단위 등)을 아직 못 다루는 경우
        text_ko = None
    return {"ok": True, "ast": ast, "error": None, "errors": [], "narration": text_ko}


def save(store: FormulaStore, name: str, text: str, description: str = "") -> dict[str, Any]:
    """문법이 맞는 수식만 저장한다(형식 검증은 명세에 넣을 때 다시 한다). 문법 오류는 FormulaError 를 그대로 올린다."""
    compile_formula(text)
    return store.put(name, text, description)


def load(store: FormulaStore, name: str) -> dict[str, Any]:
    """저장된 수식 + 지금 코드로 컴파일한 AST. 카탈로그가 바뀌어 더는 안 되는 옛 수식은 ast=None + error."""
    rec = dict(store.get(name))
    res = check(rec["text"])
    rec.update(ast=res["ast"], error=res["error"], errors=res["errors"])
    return rec


def list_all(store: FormulaStore) -> list[Mapping[str, Any]]:
    return store.list()
