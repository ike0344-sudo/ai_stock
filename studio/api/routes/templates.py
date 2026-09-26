"""조건 템플릿(문장 빈칸 채우기) API — 설계서 §5.5(c10). 문장 카드 목록·만들기·되돌리기는 도메인(`conditions/templates.py`)이 하고 여기는 얇다.

GET  /api/meta/condition-templates?mode=&bar_minutes=&source=&q=   분류별(q = 검색어: 지표 이름·문장·설명·태그, 낱말 모두 포함) 문장 목록(빈칸·선택지 켜짐/꺼짐+이유·기본 문장). mode: daily_single|daily_portfolio|intraday|tick
POST /api/meta/condition-templates/build   {id, values?, mode, bar_minutes?, source?} → {condition, sentence, values}  (빈칸 오류는 400 fieldErrors{빈칸이름: 쉬운 말})
POST /api/meta/condition-templates/match   {conditions:[…], mode, bar_minutes?} → 조건마다 {id, category, values, sentence} 또는 null(문장에 안 맞음 → 화면은 풀이 문장 + [고급에서 편집])
명세에는 조건 AST 만 들어간다(템플릿 id 는 메타) — 결과 재현은 AST 기준이다.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from studio.domain.conditions import templates as T

from ..errors import ApiError, not_found

router = APIRouter(prefix="/api/meta/condition-templates")
MODES = ("daily_single", "daily_portfolio", "intraday", "tick")
BAR_MINUTES = (1, 3, 5, 10, 15, 30, 60)
MAX_MATCH = 200


def _opts(mode: Any, bar_minutes: Any, source: Any) -> tuple[str, int, str]:
    errs = {}
    if mode not in MODES:
        errs["mode"] = " / ".join(MODES) + " 중 하나"
    try:
        bm = int(bar_minutes)
    except (TypeError, ValueError):
        bm = -1
    if bm not in BAR_MINUTES:
        errs["bar_minutes"] = " / ".join(map(str, BAR_MINUTES)) + " 중 하나"
    if source not in ("al", "krx"):
        errs["source"] = "al 또는 krx"
    if errs:
        raise ApiError(400, "VALIDATION_ERROR", "요청 값이 올바르지 않음", {"fieldErrors": errs})
    return mode, bm, source


async def _body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError:
        raise ApiError(400, "VALIDATION_ERROR", "JSON 본문이 아님") from None
    if not isinstance(body, dict):
        raise ApiError(400, "VALIDATION_ERROR", "본문은 JSON 객체여야 함")
    return body


@router.get("")
def list_templates(mode: str = "daily_portfolio", bar_minutes: str = "5", source: str = "al", q: str = "") -> dict[str, Any]:
    mode, bm, source = _opts(mode, bar_minutes, source)
    if len(q) > 100:
        raise ApiError(400, "VALIDATION_ERROR", "검색어는 100자 이하", {"fieldErrors": {"q": "100자 이하"}})
    return {"data": {"mode": mode, "bar_minutes": bm, "source": source,
                     "categories": [{"key": k, "label": v} for k, v in T.CATEGORIES.items()],
                     "templates": T.describe(mode, bar_minutes=bm, source=source, q=q)}}


@router.post("/build")
async def build(request: Request) -> dict[str, Any]:
    body = await _body(request)
    mode, bm, source = _opts(body.get("mode", "daily_portfolio"), body.get("bar_minutes", 5), body.get("source", "al"))
    values = body.get("values", {})
    if not isinstance(body.get("id"), str) or not isinstance(values, dict):
        raise ApiError(400, "VALIDATION_ERROR", "본문은 {id, values?, mode} 형식이어야 함", {"fieldErrors": {"id": "필수(문자열)"}})
    try:
        return {"data": T.build_card(body["id"], values, mode=mode, bar_minutes=bm, source=source)}
    except KeyError:
        raise not_found("없는 조건 문장") from None
    except T.TemplateError as exc:
        raise ApiError(400, "VALIDATION_ERROR", exc.message, {"fieldErrors": {exc.slot or "id": exc.message}}) from None


@router.post("/match")
async def match(request: Request) -> dict[str, Any]:
    body = await _body(request)
    mode, bm, _ = _opts(body.get("mode", "daily_portfolio"), body.get("bar_minutes", 5), "al")
    conds = body.get("conditions")
    if not isinstance(conds, list) or len(conds) > MAX_MATCH or not all(isinstance(c, dict) for c in conds):
        raise ApiError(400, "VALIDATION_ERROR", f"conditions 는 조건 객체 목록(최대 {MAX_MATCH}개)이어야 함", {"fieldErrors": {"conditions": "필수(목록)"}})
    out: list[dict[str, Any] | None] = []
    for c in conds:
        try:
            m = T.match(c, mode)
        except (KeyError, TypeError, ValueError):   # 모양이 이상한 조건(없는 지표 이름 등)은 문장에 안 맞는 것으로 — 화면은 풀이 문장으로 보여준다
            m = None
        if m is None:
            out.append(None)
            continue
        tid, values = m
        t = T.BY_ID[tid]
        out.append({"id": tid, "category": t.category, "values": values, "sentence": T.sentence(t, values, mode, bm)})
    return {"data": out}
