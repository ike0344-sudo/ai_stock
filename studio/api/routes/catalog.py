"""조립기 메뉴 재료와 종목 API (설계서 §4.1): `/api/meta/indicators`·`/strategies` · `/api/stocks` · `/api/stocks/{code}/bars`.

지표 카탈로그는 도메인(`studio.domain.conditions.catalog`)이 단일 출처 — 화면 조립기 메뉴·풀이 문장·검증이 같은 정의를 쓴다.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, Query

from studio.application import stock_service
from studio.application.services import Services
from studio.domain.conditions import catalog as cat

from ..deps import get_services
from ..errors import ApiError, not_found

router = APIRouter(prefix="/api")


def _param(p: cat.ParamDef) -> dict[str, Any]:
    return {"name": p.name, "kind": p.kind, "default": p.default, "lo": p.lo, "hi": p.hi,
            "choices": list(p.choices) if p.choices else None, "label": p.label_ko}


@router.get("/meta/indicators")
def indicators() -> dict[str, Any]:
    return {"data": {
        "indicators": [{"name": d.name, "label": d.label_ko, "desc": d.desc_ko, "params": [_param(p) for p in d.params],
                        "modes": list(d.modes), "timing": d.timing_ko, "compute": d.compute} for d in cat.INDICATORS.values()],
        "fields": list(cat.FIELDS), "modes": list(cat.MODES), "ops": ["gt", "gte", "lt", "lte", "cross_above", "cross_below"],
        "market": {"indexes": list(cat.MARKET_INDEXES), "names": list(cat.MARKET_NAMES)},
        "tick_catalog": cat.TICK_CATALOG, "n_range": [cat.N_MIN, cat.N_MAX],
    }}


@router.get("/meta/strategies")
def strategies(svc: Services = Depends(get_services)) -> dict[str, Any]:
    return {"data": svc.legacy_catalog()}


@router.get("/meta/data-ranges")
def data_ranges(svc: Services = Depends(get_services)) -> dict[str, Any]:
    """기간 선택기용 — 데이터셋별 (가장 이른 날, 가장 늦은 날). 일봉·코스피·코스닥 지수."""
    return {"data": {k: [str(a), str(b)] for k, (a, b) in svc.market_data().data_ranges().items()}}


@router.get("/meta/intraday-sources")
def intraday_sources(start: dt.date, end: dt.date, svc: Services = Depends(get_services)) -> dict[str, Any]:
    """분봉·체결 사용 가능 기간과 종목 수 — 분봉 출처(통합/KRX)를 고를 때 보여 준다."""
    if end < start:
        raise ApiError(400, "VALIDATION_ERROR", "end 가 start 보다 이르다", {"fieldErrors": {"end": "start 이후여야 함"}})
    return {"data": stock_service.intraday_sources(svc.market_data(), start, end)}


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
