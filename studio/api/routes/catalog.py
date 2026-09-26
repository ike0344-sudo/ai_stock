"""조립기 메뉴 재료와 종목 API (설계서 §4.1): `/api/meta/indicators`·`/strategies` · `/api/stocks` · `/api/stocks/{code}/bars`.

지표 카탈로그는 도메인(`studio.domain.conditions.catalog`)이 단일 출처 — 화면 조립기 메뉴·풀이 문장·검증이 같은 정의를 쓴다.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
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


TTL_SECONDS = 300.0  # 데이터 범위·보관 기간 스캔 결과(파일 목록 스캔, 첫 호출 3~5초). 데이터는 하루 한 번 바뀐다 — 아래 _ttl 이 낡은 값을 바로 주고 뒤에서 갱신하므로 길어도 안 낡는다
_LOCK = threading.Lock()
_log = logging.getLogger(__name__)


def _ttl(svc: Services, key: Any, fn: Any) -> Any:
    """Services 객체마다(서버·테스트가 서로 안 섞이게) 결과를 재사용. 처음 한 번만 기다리고, TTL 이 지나면 낡은 값을 바로 돌려주며 뒤 스레드가 한 번만 갱신한다(사용자가 스캔을 기다리지 않게)."""
    with _LOCK:
        cache = svc.__dict__.setdefault("_ttl_cache", {})
        busy = svc.__dict__.setdefault("_ttl_busy", set())
        hit = cache.get(key)
        now = time.monotonic()
        if hit and now - hit[0] < TTL_SECONDS:
            return hit[1]
        if hit:
            if key not in busy:
                busy.add(key)
                threading.Thread(target=_refresh, args=(svc, key, fn), name=f"ttl-refresh-{key}", daemon=True).start()
            return hit[1]
    val = fn()  # 값이 아직 없을 때만 동기 계산
    with _LOCK:
        cache[key] = (time.monotonic(), val)
    return val


def _refresh(svc: Services, key: Any, fn: Any) -> None:
    try:
        val = fn()
        with _LOCK:
            svc.__dict__["_ttl_cache"][key] = (time.monotonic(), val)
    except Exception:  # noqa: BLE001 — 갱신 실패는 낡은 값을 그대로 쓰고 다음 요청이 다시 시도한다(조용히 삼키지 않고 로그)
        _log.warning("캐시 갱신 실패 %s — 이전 값 유지", key, exc_info=True)
    finally:
        with _LOCK:
            svc.__dict__["_ttl_busy"].discard(key)


def warm_caches(svc: Services) -> None:
    """서버가 뜬 직후 데이터 범위 스캔을 미리 해 둔다 — 첫 화면이 3초 기다리지 않게(실패해도 서버는 산다, 첫 요청이 다시 계산)."""
    try:
        _ranges(svc)
    except Exception:  # noqa: BLE001
        _log.warning("데이터 범위 미리 채우기 실패 — 첫 요청이 계산한다", exc_info=True)


def _ranges(svc: Services) -> dict:
    """데이터 범위(날짜 튜플) — 60초 캐시. 봉 API 도 같은 값을 써서 요청마다 3초씩 스캔하지 않는다."""
    return _ttl(svc, "ranges_raw", lambda: svc.market_data().data_ranges())


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
    return {"data": {k: [str(a), str(b)] for k, (a, b) in _ranges(svc).items()}}


@router.get("/meta/intraday-sources")
def intraday_sources(start: dt.date, end: dt.date, svc: Services = Depends(get_services)) -> dict[str, Any]:
    """분봉·체결 사용 가능 기간과 종목 수 — 분봉 출처(통합/KRX)를 고를 때 보여 준다."""
    if end < start:
        raise ApiError(400, "VALIDATION_ERROR", "end 가 start 보다 이르다", {"fieldErrors": {"end": "start 이후여야 함"}})
    return {"data": _ttl(svc, ("sources", start, end), lambda: stock_service.intraday_sources(svc.market_data(), start, end))}


@router.get("/stocks/names")
def stock_names(codes: str = Query("", max_length=4000), svc: Services = Depends(get_services)) -> dict[str, Any]:
    """종목코드(쉼표 구분, 최대 300개) → 종목명 — 화면이 코드만 들고 있을 때(종목 지정 목록 등) 이름으로 바꿔 보이려고. 이름을 모르는 코드는 빠진다."""
    lst = [c.strip() for c in codes.split(",") if c.strip()][:300]
    return {"data": stock_service.names_of(svc.market_data(), lst)}


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
        return {"data": stock_service.bars(svc.market_data(), code, interval, start, end, source, _ranges(svc))}
    except stock_service.StockNotFound:
        raise not_found("그 봉 데이터가 없는 종목") from None
    except stock_service.BarsNotSupported as exc:
        raise ApiError(422, "MODE_NOT_SUPPORTED", str(exc)) from None
