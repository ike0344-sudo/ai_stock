"""조건검색 레시피 — `GET /api/meta/recipes` (설계서 studio-conditions §4·§5.4 "레시피").

레시피 = 이름 붙은 진입·청산 조건 묶음(분류·설명·쓸 수 있는 모드 포함). 화면이 불러오면 조건 행으로 풀린다.
서버가 아직 모르는 재료(`needs`)를 쓰는 레시피는 **숨기지 않고** 이유와 함께 `available=false` 로 내보낸다 — 지원되면 저절로 켜진다.
"""
from __future__ import annotations

from typing import Any

from .capabilities import capabilities, unmet_needs

CATEGORY_ORDER = ("신고가", "이동평균", "거래량·거래대금", "갭", "보조지표", "분봉", "테마")


def list_recipes(raw: list[dict[str, Any]], indicators: dict[str, Any], ops: list[str]) -> list[dict[str, Any]]:
    caps = capabilities()
    out = []
    for r in raw:
        missing = unmet_needs(list(r.get("needs") or []), caps, indicators, ops)
        out.append({**r, "available": not missing, "unavailable_reason": ("서버가 아직 지원하지 않는다: " + ", ".join(missing)) if missing else None})
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    return sorted(out, key=lambda r: (order.get(r["category"], 99), not r["available"], r["title"]))
