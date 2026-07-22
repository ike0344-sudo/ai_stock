"""breakout_reversal.detect_entries의 기본 조건 위에 추가로 걸 수 있는 진입 필터들.

각 필터는 1분봉 인덱스와 동일한 pd.Series[bool]을 반환하므로, detect_entries의
결과와 단순히 AND 결합하면 된다.
"""
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
    """
    minute_dates = minute_candles.index.normalize()
    return pd.Series([regime_by_day.get(d, False) for d in minute_dates], index=minute_candles.index)


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
