"""breakout_reversal.detect_entries의 기본 조건 위에 추가로 걸 수 있는 진입 필터들.

각 필터는 1분봉 인덱스와 동일한 pd.Series[bool]을 반환하므로, detect_entries의
결과와 단순히 AND 결합하면 된다.
"""
import os

import duckdb
import numpy as np
import pandas as pd

from .data_loader import _resample_minute


def n_day_high_filter(minute_candles: pd.DataFrame, daily_candles: pd.DataFrame, n: int) -> pd.Series:
    """당일을 제외한 직전 n거래일의 최고가(daily high)보다 현재 종가가 높으면 True
    (= 신고가 돌파). daily_candles는 date-indexed 일봉(data/stocks/daily/*.csv 형식).
    """
    n_day_high_ref = daily_candles["high"].shift(1).rolling(n).max()

    minute_dates = minute_candles.index.normalize()
    ref_per_minute = minute_dates.map(n_day_high_ref)
    ref_per_minute = pd.Series(ref_per_minute, index=minute_candles.index, dtype=float)

    return (minute_candles["close"] > ref_per_minute).fillna(False)


def _day_return(minute_candles: pd.DataFrame, daily_candles: pd.DataFrame) -> pd.Series:
    """전일 종가 대비 당일(현재 시점까지) 상승률. daily_candles의 당일 행은 shift(1)
    덕분에 참조에서 제외되고 오직 "전일 종가"만 참조하므로 미래 데이터 누수가 없다.
    """
    prev_close = daily_candles["close"].shift(1)

    minute_dates = minute_candles.index.normalize()
    ref_per_minute = minute_dates.map(prev_close)
    ref_per_minute = pd.Series(ref_per_minute, index=minute_candles.index, dtype=float)

    return (minute_candles["close"] - ref_per_minute) / ref_per_minute


def day_return_filter(minute_candles: pd.DataFrame, daily_candles: pd.DataFrame, threshold: float) -> pd.Series:
    """전일 종가 대비 당일 상승률이 threshold 이상이면 True."""
    return (_day_return(minute_candles, daily_candles) >= threshold).fillna(False)


def day_return_ceiling_filter(minute_candles: pd.DataFrame, daily_candles: pd.DataFrame, threshold: float) -> pd.Series:
    """전일 종가 대비 당일 상승률이 threshold 미만이면 True — 이미 과도하게 오른
    (상한가 근접 등) 종목을 진입 대상에서 제외하는 용도. 값을 알 수 없으면(전일
    데이터 없음) 보수적으로 제외(False) 처리한다.
    """
    return (_day_return(minute_candles, daily_candles) < threshold).fillna(False)


def intraday_new_high_filter(minute_candles: pd.DataFrame) -> pd.Series:
    """당일 장중 누적 고가를 그 시점에 경신(또는 동률)하는 캔들이면 True (당일 신고가).

    일자 경계를 넘어 누적되지 않도록 날짜별로 그룹핑해 cummax를 계산한다. 미래
    데이터 누수 없음 — 각 시점까지의 자기 자신 데이터만 사용.
    """
    parts = []
    for _, day_df in minute_candles.groupby(minute_candles.index.normalize()):
        running_high = day_df["high"].cummax()
        parts.append(day_df["high"] >= running_high)
    if not parts:
        return pd.Series(dtype=bool)
    return pd.concat(parts).reindex(minute_candles.index)


# ponytail: scan_all_trades 프로파일링(2026-08-30, backtest-agent 실측)에서
# detect_final_entries가 전체의 67%를 먹었고 그중에서도 이 조건류(당일 누적 고가
# cummax)가 종목마다 반복 호출되는 게 비용이었다 - 판단로직은 위 pandas 버전과
# 완전히 동일(당일 리셋 cummax), SQL로는 종목×날짜별 파티션 윈도우함수 하나면 끝나서
# 포팅 실험 대상 1순위로 골랐다. detect_final_entries에 아직 연결 안 함(조건 하나만
# 먼저 검증하고 승인받은 뒤 다음 조건으로 넘어가기로 함 - state/agent_reports/
# backtest-agent_20260830-083548.md 참고). 지금은 이 함수 단독으로만 쓸 수 있다.
def intraday_new_high_filter_batch_duckdb(data_dir: str = "data") -> dict[str, pd.Series]:
    """intraday_new_high_filter를 로컬 유니버스 전체 종목에 대해 한 번의 DuckDB
    쿼리로 계산한다 - 종목별로 반복 호출하는 대신 전부 한 번에. 반환값은
    {code: pd.Series[bool]}(minute_candles.index와 같은 타임스탬프 인덱스) - 기존
    intraday_new_high_filter(minute_candles) 한 종목 호출 결과와 값이 완전히 같아야
    한다 (tests/backtesting/test_entry_filters.py::
    test_intraday_new_high_filter_batch_duckdb_matches_pandas_version 참고).
    """
    minute_glob = os.path.join(data_dir, "stocks", "minute", "*.csv").replace("\\", "/")
    query = f"""
    SELECT
        parse_filename(filename, true) AS code,
        date AS ts,
        high >= MAX(high) OVER (
            PARTITION BY parse_filename(filename, true), date::DATE ORDER BY date
            ROWS UNBOUNDED PRECEDING
        ) AS is_new_high
    FROM read_csv('{minute_glob}', filename=true, union_by_name=true)
    ORDER BY code, ts
    """
    result = duckdb.sql(query).df()
    result["ts"] = pd.to_datetime(result["ts"])
    return {
        code: group.set_index("ts")["is_new_high"].astype(bool)
        for code, group in result.groupby("code")
    }


def no_prior_drawdown_filter(minute_candles: pd.DataFrame, drawdown_threshold: float = 0.05) -> pd.Series:
    """당일 장중 고점(누적 최고가) 대비 종가 하락폭이 drawdown_threshold 이상이었던
    적이 한 번이라도 있으면, 그 시점부터 당일 나머지 구간은 계속 False (제외).

    "한 번 깨지면 그날은 계속 제외"라는 sticky 조건 — 되돌림이 이미 한번 크게
    나온 종목은 모멘텀이 훼손됐다고 보고 그날 남은 시간은 재진입 후보에서 뺀다.
    """
    parts = []
    for _, day_df in minute_candles.groupby(minute_candles.index.normalize()):
        running_peak = day_df["high"].cummax()
        drawdown = (running_peak - day_df["close"]) / running_peak
        ever_triggered = (drawdown >= drawdown_threshold).cummax()
        parts.append(~ever_triggered)
    if not parts:
        return pd.Series(dtype=bool)
    return pd.concat(parts).reindex(minute_candles.index)


# ponytail: intraday_new_high_filter_batch_duckdb와 같은 이유·같은 패턴(scan_all_trades
# 프로파일링에서 detect_final_entries가 67% - backtest-agent_20260830-083548.md).
# 판단로직은 위 pandas 버전과 동일 - "당일 누적 고점 대비 하락폭이 한 번이라도
# threshold를 넘으면 그 날은 계속 False"를 윈도우함수 두 겹(고점 cummax ->
# 하락폭 판정 -> 판정의 cummax)으로 그대로 옮겼다.
def no_prior_drawdown_filter_batch_duckdb(
    data_dir: str = "data", drawdown_threshold: float = 0.05
) -> dict[str, pd.Series]:
    """no_prior_drawdown_filter를 로컬 유니버스 전체 종목에 대해 한 번의 DuckDB
    쿼리로 계산한다. 반환값은 {code: pd.Series[bool]} - 기존
    no_prior_drawdown_filter(minute_candles, drawdown_threshold) 종목별 호출 결과와
    값이 완전히 같아야 한다(tests/backtesting/test_entry_filters.py::
    test_no_prior_drawdown_filter_batch_duckdb_matches_pandas_version 참고).
    detect_final_entries에는 아직 연결하지 않았다 - 조건 단위 검증만 마친 상태.
    """
    minute_glob = os.path.join(data_dir, "stocks", "minute", "*.csv").replace("\\", "/")
    query = f"""
    WITH minute AS (
        SELECT
            parse_filename(filename, true) AS code,
            date AS ts,
            date::DATE AS d,
            high,
            close
        FROM read_csv('{minute_glob}', filename=true, union_by_name=true)
    ),
    peaked AS (
        SELECT code, ts, d, close,
            MAX(high) OVER (PARTITION BY code, d ORDER BY ts ROWS UNBOUNDED PRECEDING) AS running_peak
        FROM minute
    ),
    flagged AS (
        SELECT code, ts, d,
            CASE WHEN (running_peak - close) / running_peak >= {drawdown_threshold} THEN 1 ELSE 0 END AS triggered
        FROM peaked
    )
    SELECT code, ts,
        MAX(triggered) OVER (PARTITION BY code, d ORDER BY ts ROWS UNBOUNDED PRECEDING) = 0 AS not_triggered
    FROM flagged
    ORDER BY code, ts
    """
    result = duckdb.sql(query).df()
    result["ts"] = pd.to_datetime(result["ts"])
    return {
        code: group.set_index("ts")["not_triggered"].astype(bool)
        for code, group in result.groupby("code")
    }


def compute_index_regime_by_day(
    index_minute_candles: pd.DataFrame, ma_period: int = 60, resample_minutes: int = 15
) -> dict:
    """지수 1분봉을 resample_minutes 단위로 재표본화한 뒤 ma_period기간 이동평균을 계산.

    이동평균 자체는 날짜 경계를 넘어 연속으로 계산한다 — 60기간 15분봉 이평선은
    거래일 하나로는 못 채우고 원래 여러 거래일에 걸쳐 있는 지표이므로, 다른
    필터들과 달리 day-reset을 하지 않는 게 맞다. 그 위에서 "그날 첫 봉(09시 기준)의
    종가가 그 시점 이평선 위였는지"만 날짜별로 뽑아 dict로 반환한다 — 하루 동안은
    이 판단을 그대로 쓰고 장중 재평가는 하지 않는 단순한 레짐 필터.
    """
    resampled = _resample_minute(index_minute_candles, resample_minutes)
    closes = resampled["close"]
    above = closes > closes.rolling(ma_period).mean()  # 이평선 미형성 구간(NaN)은 비교 시 자동으로 False

    result: dict = {}
    for date, day_group in above.groupby(above.index.normalize()):
        result[date] = bool(day_group.iloc[0]) if not day_group.empty else False
    return result


def market_regime_filter(minute_candles: pd.DataFrame, regime_by_day: dict) -> pd.Series:
    """compute_index_regime_by_day가 만든 날짜별 판단을 종목 분봉 인덱스에 broadcast.

    regime_by_day에 없는 날짜(이평선 계산에 필요한 이력 부족 등)는 보수적으로 False.

    day별 값은 하루 안에서 항상 같으므로(고유 날짜만 조회하고 분봉 개수만큼 broadcast),
    분봉 하나하나(수만~수십만 개)를 파이썬 루프로 도는 대신 고유 날짜(수백 개)만 조회한다
    — 값은 원래 루프와 동일, 조회 횟수만 준다 (2026-08-29 실측: 40종목 1.74s -> 대부분
    DatetimeIndex를 원소 단위로 iterate하며 Timestamp를 매번 박싱하는 비용이었다).
    """
    minute_dates = minute_candles.index.normalize()
    day_codes, unique_days = pd.factorize(minute_dates)
    day_flags = np.fromiter((regime_by_day.get(d, False) for d in unique_days), dtype=bool, count=len(unique_days))
    return pd.Series(day_flags[day_codes], index=minute_candles.index)


def top_return_rank1_filter(minute_candles: pd.DataFrame, code: str, rank1_by_minute: dict) -> pd.Series:
    """universe.intraday_top_n_return_rank1_by_minute가 만든 {타임스탬프: 그 시점 1등
    종목코드} 매핑을, market_regime_filter와 같은 방식으로 종목별 분봉 인덱스에
    broadcast한다. 그 시점의 1등이 이 code가 아니거나(다른 코드) 그 시점 자체가
    매핑에 없으면(예: 그날 이 종목이 상위권 유니버스가 아니었음) False.
    """
    return pd.Series(
        [rank1_by_minute.get(ts) == code for ts in minute_candles.index], index=minute_candles.index
    )


def time_of_day_filter(minute_candles: pd.DataFrame, start_time: str, end_time: str) -> pd.Series:
    """진입 시각이 [start_time, end_time]("HH:MM" 문자열) 범위 안이면 True."""
    times = minute_candles.index.time
    start = pd.Timestamp(start_time).time()
    end = pd.Timestamp(end_time).time()
    return pd.Series((times >= start) & (times <= end), index=minute_candles.index)


def combine_and(*conditions: pd.Series) -> pd.Series:
    result = conditions[0]
    for cond in conditions[1:]:
        result = result & cond
    return result
