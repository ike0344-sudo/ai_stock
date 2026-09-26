"""거래일 달력 (설계 §2.4.1, 테스트 H6).

지나간 날 = 코스피 지수 일봉에 봉이 있는 날, 그 뒤(앞날) = 평일 - 카탈로그 휴장일.
지수가 아직 안 쌓인 최근 며칠(예: 어젯밤 갱신 전)도 앞날 규칙으로 판정되므로,
연휴는 카탈로그 `holidays` 에 있어야 밀림으로 오판하지 않는다.
"""
import csv
from datetime import date, datetime, timedelta

from . import catalog


def _load_index_dates() -> set[date]:
    p = catalog.root() / catalog.load().calendar.source
    if not p.is_file():
        return set()
    with p.open(encoding="utf-8-sig", newline="") as fh:
        rows = csv.reader(fh)
        next(rows, None)                                   # 헤더
        return {date.fromisoformat(r[0][:10]) for r in rows if r and r[0][:4].isdigit()}


class Calendar:
    def __init__(self, index_dates: set[date] | None = None, holidays: set[date] | None = None):
        self.index_dates = _load_index_dates() if index_dates is None else index_dates
        self.holidays = ({date.fromisoformat(h) for h in catalog.load().calendar.holidays}
                         if holidays is None else holidays)
        self.last_index_date = max(self.index_dates) if self.index_dates else None

    def is_trading_day(self, d: date) -> bool:
        if d in self.index_dates:
            return True
        if self.last_index_date is not None and d < self.last_index_date:
            return False                                   # 지나간 날인데 지수 봉이 없다 = 휴장
        return d.weekday() < 5 and d not in self.holidays

    def prev_trading_day(self, d: date) -> date:
        d -= timedelta(days=1)
        while not self.is_trading_day(d):
            d -= timedelta(days=1)
        return d

    def next_trading_day(self, d: date) -> date:
        d += timedelta(days=1)
        while not self.is_trading_day(d):
            d += timedelta(days=1)
        return d

    def trading_days(self, start: date, end: date) -> list[date]:
        return [start + timedelta(days=i) for i in range((end - start).days + 1)
                if self.is_trading_day(start + timedelta(days=i))]

    def settled_day(self, now: datetime, close_hour: int = 16) -> date:
        """마감이 확정된 가장 최근 거래일 — 거래일 close_hour 시 이후면 오늘, 아니면(장중·휴장·주말) 직전 거래일.
        달력일 `오늘-1` 을 쓰면 월요일 아침·휴장일에 전 종목이 밀림으로 보인다."""
        d = now.date()
        return d if self.is_trading_day(d) and now.hour >= close_hour else self.prev_trading_day(d)
