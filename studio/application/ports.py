"""응용 계층이 바깥(파일·기존 코드)에 요구하는 것 — Protocol 만. 구현은 studio.infrastructure (§9.3).

MarketData      일봉 패널·지수·종목 정보·데이터 범위 (파일은 datahub 카탈로그 경로로 읽는다)
LegacyStrategies 기존 전략 8종 — backtesting 을 아는 쪽(infrastructure)이 구현
RunStore        results/studio/<run_id>/ 저장·조회
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

import pandas as pd

from studio.domain.conditions.evaluator import Evaluation
from studio.domain.models import Panel
from studio.domain.spec import Spec


class MarketData(Protocol):
    def load_panel(self, start: dt.date, end: dt.date, warmup_bars: int,
                   codes: Sequence[str] | None = None) -> Panel:
        """end 이하 일봉 패널 — start 이전 warmup_bars 봉(있는 만큼)을 앞에 붙여서.
        prev_close 는 종목별 직전 유효 종가(거래정지일을 건너뜀). codes=None 이면 전 종목."""

    def index_frames(self) -> Mapping[str, pd.DataFrame]:
        """{'kospi': df, 'kosdaq': df} — close 열은 저장값 그대로(×100 스케일)."""

    def stock_info(self) -> pd.DataFrame:
        """index=종목코드, 열 name·sector·market('거래소'/'코스닥'/NaN)."""

    def mega_cap_codes(self) -> frozenset[str]: ...

    def data_ranges(self) -> dict[str, tuple[dt.date, dt.date]]:
        """{'daily', 'kospi', 'kosdaq', 'minute_al', 'minute_krx', 'tick_al'} → (가장 이른 날, 가장 늦은 날). 분봉·체결은 종목마다 기간이
        다르므로 전 종목의 가장 이른/늦은 날이다 — 실제로 쓴 (날짜,종목) 커버리지는 minute_coverage·tick_days 로 따로 본다."""

    # ---- 분봉·체결 (module-6) — 통합(AL) 보관소·체결. 없는 종목·날은 조용히 채우지 않고 빠진다.
    def minute_panel(self, codes: Sequence[str], start: dt.date, end: dt.date, bar_minutes: int, source: str = "al") -> Panel:
        """분봉 Panel(출처 source = "al"(통합, NXT 포함) | "krx"(KRX 전용, 긴 과거·NXT 체결 빠짐) — 섞지 않는다; index=봉 끝 시각·여러 날, columns=분봉이 있는 종목, prev_close=그 날 전일 종가, value=종가×거래량 근사)."""

    def minute_coverage(self, codes: Sequence[str], source: str = "al") -> dict[str, tuple[dt.date, dt.date]]:
        """그 출처의 종목별 분봉 보관 기간(첫 날, 끝 날) — 보관소에 없는 종목은 빠진다."""

    def tick_codes(self) -> list[str]:
        """체결 파일이 있는 종목."""

    def tick_days(self, code: str) -> list[dt.date]:
        """그 종목의 체결 파일이 있는 날(오름차순)."""

    def tick_day(self, code: str, day: dt.date) -> Any:
        """하루치 `TickDay`(conditions.tick) — 정규장 체결이 없으면 None. prev_close = 일봉 D−1 종가."""


class LegacyStrategies(Protocol):
    def evaluate(self, name: str, params: dict[str, Any] | None, panel: Panel) -> Evaluation:
        """기존 전략 → 진입/청산 bool 표 (BUY→진입, SELL→청산)."""

    def signals(self, name: str, params: dict[str, Any] | None, panel: Panel) -> pd.DataFrame:
        """기존 전략 신호 표('buy'/'sell'/'hold') — 호환 모드용."""


@dataclass
class RunRecord:
    """한 번의 실행 결과 묶음 — 저장·조회의 단위."""

    spec: Spec  # 실행한 원본(변수 칸이 채워지지 않은) 명세
    meta: dict[str, Any]
    summary: dict[str, Any]
    trades: pd.DataFrame
    equity: pd.DataFrame
    run_id: str | None = None
    warnings: list[str] = field(default_factory=list)
    grid: pd.DataFrame | None = None  # 최적화·워크포워드: 조합 표 → grid.parquet
    folds: Any = None  # 워크포워드: 폴드 상세(JSON 직렬화 가능) → folds.json


class TradingCalendar(Protocol):
    def trading_days(self, start: dt.date, end: dt.date) -> list[dt.date]:
        """[start, end] 안의 거래일(휴장일 제외) — 검증 구간 분할은 이 거래일 수 기준이다."""


class HoldoutLedger(Protocol):
    """홀드아웃 열람 기록(results/studio/holdout_ledger.json). structure_hash 별로 쌓는다."""

    def history(self, structure_hash: str) -> list[dict[str, Any]]: ...

    def family_history(self, family_hash: str) -> list[dict[str, Any]]: ...

    def record_open(self, structure_hash: str, entry: dict[str, Any]) -> int:
        """열람 기록을 추가하고 이 구조의 몇 번째 열람인지(1부터) 돌려준다."""


class RunStore(Protocol):
    def save(self, record: RunRecord, run_id: str | None = None) -> str: ...

    def load(self, run_id: str) -> RunRecord: ...

    def list_ids(self) -> list[str]: ...
