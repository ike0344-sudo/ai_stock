"""수집 정책 — 지금 이 수집을 해도 되는가 (설계 §2.4.6, 테스트 H5).

시간대는 소피증권 `config.yaml` 의 `market.open/close/connect_from/connect_to` 를 따른다.
주말·휴장일은 "야간"과 같다(소피증권이 장이 없으니 REST 한도를 다툴 일이 없다).

판정만 한다(순수 함수) — 막는 건 허브 API, 경고만 하는 건 `gate.write()`.
"""
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from . import catalog
from .calendar import Calendar

SOPHIE_CONFIG = "kospi-theme-engine/config.yaml"
LIGHT_MAX_CODES = 20                      # 종목 지정 21개부터 대량
STOP_MARGIN_MIN = 10                      # 야간 작업은 소피증권이 붙기 10분 전(connect_from - 10분)에 스스로 멈춘다

# 대량 / 소량 / 로컬(API 호출 없음)
_HEAVY_MODES = {"collect_minute_al": {"sophie_baseline", "all_cached", "deep_archive"},
                "collect_daily": {"stale", "all"}}
WINDOWS = ("market", "sophie_live", "night", "holiday")


def batch_keys_configured(env: dict | None = None) -> bool:
    """배치 앱키(KIWOOM_BATCH_*)가 설정돼 있나. 환경변수에 없으면 저장소 `.env` 에서 **이름과 값이 있는지만** 본다 —
    허브 서버는 실계좌 키를 자식 프로세스에 물려주지 않으려고 .env 를 환경에 올리지 않는다(값은 읽어 쓰지 않는다)."""
    env = os.environ if env is None else env
    if env.get("KIWOOM_BATCH_APPKEY") and env.get("KIWOOM_BATCH_SECRETKEY"):
        return True
    try:
        text = (catalog.root() / ".env").read_text(encoding="utf-8-sig")
    except OSError:
        return False
    return all(re.search(rf"^\s*{k}\s*=\s*\S", text, re.M) for k in ("KIWOOM_BATCH_APPKEY", "KIWOOM_BATCH_SECRETKEY"))


@dataclass
class Hours:
    connect_from: str
    open: str
    close: str
    connect_to: str
    source: str = SOPHIE_CONFIG


def sophie_hours() -> Hours:
    """소피증권 설정의 운영 시간. 못 읽으면 문서에 적힌 기본값(09:00/15:30/08:20/20:10)."""
    try:
        m = yaml.safe_load((catalog.root() / SOPHIE_CONFIG).read_text(encoding="utf-8"))["market"]
        f = lambda k: str(m[k])[:5]
        return Hours(f("connect_from"), f("open"), f("close"), f("connect_to"))
    except (OSError, KeyError, TypeError, yaml.YAMLError):
        return Hours("08:20", "09:00", "15:30", "20:10", source="기본값(설정을 못 읽음)")


def _t(hhmm: str) -> tuple[int, int]:
    h, m = hhmm.split(":")
    return int(h), int(m)


def window(now: datetime, hours: Hours | None = None, cal: Calendar | None = None) -> str:
    """market(정규장) / sophie_live(소피증권 가동, 정규장 밖) / night / holiday(주말·휴장일)."""
    hours = hours or sophie_hours()
    cal = cal or Calendar()
    if not cal.is_trading_day(now.date()):
        return "holiday"
    hm = (now.hour, now.minute)
    if _t(hours.open) <= hm < _t(hours.close):
        return "market"
    if _t(hours.connect_from) <= hm < _t(hours.connect_to):
        return "sophie_live"
    return "night"


def weight(kind: str, mode: str | None = None, n_codes: int = 0) -> str:
    """heavy / light / local(API 호출 없음)."""
    if kind == "archive_minute_al":
        return "local"
    if kind == "collect_ticks":
        return "heavy"
    if mode in _HEAVY_MODES.get(kind, ()):
        return "heavy"
    return "heavy" if n_codes > LIGHT_MAX_CODES else "light"


def at_today(now: datetime, hhmm: str) -> datetime:
    h, m = _t(hhmm)
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


def stop_at(hours: Hours | None = None) -> str:
    """야간 수집기 `--stop-at`: connect_from - 10분 (기본 08:10)."""
    h, m = _t((hours or sophie_hours()).connect_from)
    t = timedelta(hours=h, minutes=m) - timedelta(minutes=STOP_MARGIN_MIN)
    return f"{int(t.total_seconds() // 3600):02d}:{int(t.total_seconds() % 3600 // 60):02d}"


def is_night_start(now: datetime, hours: Hours | None = None, cal: Calendar | None = None) -> bool:
    """예약·일정 작업은 야간(주말·휴장일 포함) 구간에서만 시작한다."""
    return window(now, hours, cal) in ("night", "holiday")


def cpu_workers(win: str, cpu_count: int | None = None) -> int:
    """그리드 병렬 수: 소피증권 가동 시간 cpu//4, 야간·휴장 cpu//2 (최소 1)."""
    n = cpu_count or os.cpu_count() or 2
    return max(1, n // (4 if win in ("market", "sophie_live") else 2))


@dataclass
class Decision:
    weight: str
    window: str
    decision: str                      # allow_now / needs_confirm / schedule_only
    suggest_at: datetime | None
    reason: str
    warnings: list[str] = field(default_factory=list)
    busy: bool = False                 # 허브 수집이 이미 1개 돌고 있다 -> 409 COLLECT_BUSY


def decide(kind: str, mode: str | None = None, n_codes: int = 0, now: datetime | None = None,
           hours: Hours | None = None, cal: Calendar | None = None, hub_busy: bool = False,
           env: dict | None = None) -> Decision:
    now = now or datetime.now()
    hours = hours or sophie_hours()
    win = window(now, hours, cal)
    w = weight(kind, mode, n_codes)
    connect_to = at_today(now, hours.connect_to)
    warnings: list[str] = []
    env = os.environ if env is None else env

    if w == "local" or win in ("night", "holiday"):
        d, at, why = "allow_now", None, ("API 를 안 쓰는 로컬 작업" if w == "local"
                                         else "소피증권이 가동 중이 아닌 시간(야간·주말·휴장일)")
    elif win == "market":
        if w == "heavy":
            d, at = "schedule_only", connect_to
            why = f"소피증권 정규장 시간 — 대량 수집은 장 마감 뒤({hours.connect_to}) 예약만 됩니다"
        else:
            d, at, why = "needs_confirm", None, "소피증권 정규장 시간 — 소량 수집은 확인 후 가능합니다"
    else:  # sophie_live
        if w == "heavy":
            d, at = "needs_confirm", connect_to
            why = f"소피증권 가동 시간(REST 한도 공유) — 확인 후 실행하거나 {hours.connect_to} 예약하세요"
        else:
            d, at, why = "allow_now", None, "소피증권 가동 시간이지만 소량이라 바로 가능합니다"

    if kind == "collect_minute_al" and at_today(now, "20:00") > now and win != "holiday":
        warnings.append("오늘 통합 분봉은 NXT 마감(20:00) 전이면 잘립니다 — 다음 갱신 때 다시 받아집니다")
    if w != "local" and not batch_keys_configured(env):
        warnings.append("배치 앱키(KIWOOM_BATCH_*)가 없습니다 — 실시간 키로 수집하면 소피증권 실시간과 세션·한도를 다툽니다")
    if w == "heavy" and win in ("market", "sophie_live"):
        warnings.append("REST 한도는 앱키를 나눠도 계정 단위로 공유됩니다")
    if hub_busy and w != "local":
        warnings.append("허브 수집이 이미 1개 실행 중입니다 — 동시에 1개만 돕니다")
    return Decision(w, win, d, at, why, warnings, busy=hub_busy and w != "local")
