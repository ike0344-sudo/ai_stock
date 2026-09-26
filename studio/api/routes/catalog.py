"""조립기 메뉴 재료와 종목 API (설계서 §4.1): `/api/meta/indicators`·`/strategies` · `/api/stocks` · `/api/stocks/{code}/bars`.

지표 카탈로그는 도메인(`studio.domain.conditions.catalog`)이 단일 출처 — 화면 조립기 메뉴·풀이 문장·검증이 같은 정의를 쓴다.
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from studio.application import recipes as recipe_service
from studio.application import stock_service
from studio.application.capabilities import capabilities, ops
from studio.application.services import Services
from studio.domain.conditions import catalog as cat

from ..deps import get_services
from ..errors import ApiError, not_found

router = APIRouter(prefix="/api")


def _param(p: cat.ParamDef) -> dict[str, Any]:
    return {"name": p.name, "kind": p.kind, "default": p.default, "lo": p.lo, "hi": p.hi,
            "choices": list(p.choices) if p.choices else None, "label": p.label_ko}


TTL_SECONDS = 60.0  # 데이터 범위·보관 기간 스캔 결과를 잠깐 들고 있는다 — 매 요청 3~5초(파일 목록 스캔)라 화면이 느리다. 야간 갱신은 1분 늦어도 무방하다


def _ttl(svc: Services, key: Any, fn: Any) -> Any:
    """Services 객체마다(서버·테스트가 서로 안 섞이게) 결과를 TTL 동안 재사용."""
    cache = svc.__dict__.setdefault("_ttl_cache", {})
    hit = cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < TTL_SECONDS:
        return hit[1]
    val = fn()
    cache[key] = (now, val)
    return val


def _route_paths(app: Any) -> list[str]:
    """이 서버에 실제로 붙은 경로 — FastAPI 버전에 따라 include_router 가 경로 없는 껍데기(`original_router` 를 품은)로 들어와 둘 다 본다."""
    out: list[str] = []
    for r in app.routes:
        if getattr(r, "path", None):
            out.append(r.path)
        for sub in getattr(getattr(r, "original_router", None), "routes", []) or []:
            if getattr(sub, "path", None):
                out.append(sub.path)
    return out


def _indicator(d: cat.IndicatorDef) -> dict[str, Any]:
    """기본 칸 + 확장 칸(분류 키·한글 분류명·정의 식·예시·일봉 실시간 지원 live·거래량 계열 volume_based)."""
    out = {"name": d.name, "label": d.label_ko, "desc": d.desc_ko, "params": [_param(p) for p in d.params],
           "modes": list(d.modes), "timing": d.timing_ko, "compute": d.compute}
    for key in ("category", "definition", "example", "live", "volume_based"):  # backtest-agent 확정 칸(c1 편지 2026-09-26)
        v = getattr(d, key, None)
        if v is not None:
            out[key] = v
    lr = getattr(d, "live_reason_ko", None)  # 일봉 실시간을 왜 못 쓰나(빈 문자열 = 조건 없이 지원)
    if lr:
        out["live_reason"] = lr
    cats = getattr(cat, "CATEGORIES", {})
    if getattr(d, "category", None) in cats:
        out["category_ko"] = cats[d.category]
    return out


@router.get("/meta/indicators")
def indicators(request: Request) -> dict[str, Any]:
    return {"data": {
        "indicators": [_indicator(d) for d in cat.INDICATORS.values()],
        "fields": list(cat.FIELDS), "modes": list(cat.MODES), "ops": ops(),
        "market": {"indexes": list(cat.MARKET_INDEXES), "names": list(cat.MARKET_NAMES)},
        "tick_catalog": cat.TICK_CATALOG, "n_range": [cat.N_MIN, cat.N_MAX],
        "categories": [{"key": k, "label": v} for k, v in getattr(cat, "CATEGORIES", {}).items()],
        "capabilities": capabilities(_route_paths(request.app)),
    }}


@router.get("/meta/recipes")
def recipes(svc: Services = Depends(get_services)) -> dict[str, Any]:
    """조건검색 레시피 — 서버가 아직 못 쓰는 재료가 든 것은 available=false + 이유로 내보낸다."""
    return {"data": recipe_service.list_recipes(svc.recipes(), dict(cat.INDICATORS), ops())}


@router.get("/meta/strategies")
def strategies(svc: Services = Depends(get_services)) -> dict[str, Any]:
    return {"data": svc.legacy_catalog()}


@router.get("/meta/data-ranges")
def data_ranges(svc: Services = Depends(get_services)) -> dict[str, Any]:
    """기간 선택기용 — 데이터셋별 (가장 이른 날, 가장 늦은 날). 일봉·코스피·코스닥 지수."""
    return {"data": _ttl(svc, "ranges", lambda: {k: [str(a), str(b)] for k, (a, b) in svc.market_data().data_ranges().items()})}


@router.get("/meta/intraday-sources")
def intraday_sources(start: dt.date, end: dt.date, svc: Services = Depends(get_services)) -> dict[str, Any]:
    """분봉·체결 사용 가능 기간과 종목 수 — 분봉 출처(통합/KRX)를 고를 때 보여 준다."""
    if end < start:
        raise ApiError(400, "VALIDATION_ERROR", "end 가 start 보다 이르다", {"fieldErrors": {"end": "start 이후여야 함"}})
    return {"data": _ttl(svc, ("sources", start, end), lambda: stock_service.intraday_sources(svc.market_data(), start, end))}


@router.get("/stocks")
def search_stocks(q: str = Query("", max_length=40), limit: int = Query(20, ge=1, le=50),
                  svc: Services = Depends(get_services)) -> dict[str, Any]:
    return {"data": stock_service.search(svc.market_data(), q, limit)}


@router.get("/stocks/{code}/bars")
def stock_bars(code: str, interval: str = Query("1d", max_length=8), start: dt.date | None = None,
               end: dt.date | None = None, source: str = Query("al", max_length=4), svc: Services = Depends(get_services)) -> dict[str, Any]:
    if not stock_service.CODE_RE.fullmatch(code):
        raise not_found()
    try:
        return {"data": stock_service.bars(svc.market_data(), code, interval, start, end, source)}
    except stock_service.StockNotFound:
        raise not_found("그 봉 데이터가 없는 종목") from None
    except stock_service.BarsNotSupported as exc:
        raise ApiError(422, "MODE_NOT_SUPPORTED", str(exc)) from None
