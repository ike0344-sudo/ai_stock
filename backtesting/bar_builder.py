"""틱 원본(tick_store.read_ticks)으로부터 임의 주기 OHLCV 봉을 생성한다.

data-agent.md 섹션 3의 봉 생성 규칙을 따른다:
- 봉 timestamp는 봉 시작 시각 기준 (label="left").
- 체결 없는 구간은 봉을 만들지 않는다 (forward-fill 없음) — dropna로 빈 버킷 제거.
- origin="start_day"로 자정 기준 정렬해 09:00/09:15 같은 정각 경계에 봉이 떨어지게 한다
  (첫 틱 시각을 origin으로 쓰면 09:00:01 등에 밀려 정각 경계가 어긋난다).
"""
import pandas as pd

BAR_COLUMNS = ["open", "high", "low", "close", "volume"]


def build_bars(ticks: pd.DataFrame, interval: str, trading_date: str) -> pd.DataFrame:
    """ticks: tick_store.read_ticks()의 반환 형식(price, cum_volume, time_hms, bid).
    interval: pandas resample 규칙 문자열(예: "1min", "15min").
    trading_date: tick_store와 동일한 "YYYY-MM-DD" 형식 — time_hms(HHMMSS)와 결합해
    실제 timestamp를 만드는 데 쓰인다(틱 자체엔 날짜가 없음)."""
    if ticks.empty:
        return pd.DataFrame(columns=BAR_COLUMNS)

    df = ticks.copy()
    df.index = pd.to_datetime(trading_date + " " + df["time_hms"], format="%Y-%m-%d %H%M%S")

    # cum_volume은 당일 누적치라 틱 간 diff로 실제 체결량을 구한다. 첫 틱은 비교 대상이
    # 없어 diff가 NaN이 되는데, realtime_feed.CandleAggregator와 동일하게 0으로 처리한다
    # (첫 틱 이전의 누적치를 모르므로 그 틱만의 체결량을 알 수 없음 — 과대산정 방지).
    volume = df["cum_volume"].diff().fillna(0).clip(lower=0)

    resampled = pd.DataFrame({
        "open": df["price"], "high": df["price"], "low": df["price"], "close": df["price"],
        "volume": volume,
    }).resample(interval, origin="start_day", closed="left", label="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    })
    return resampled.dropna(subset=["open"])
