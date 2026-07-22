"""strategies와 ml 양쪽에서 재사용하는 기술적 지표 계산 함수."""
import pandas as pd


def compute_rsi(closes: pd.Series, period: int) -> pd.Series:
    """단순이동평균 기반 RSI (Wilder 방식 아님)."""
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    # avg_loss == 0 (연속 상승만 있는 구간)이면 RS가 무한대이므로 관례상 RSI=100으로 처리
    return rsi.where(avg_loss != 0, 100.0)
