"""진입 시점(entry_idx)까지의 데이터만으로 '이 진입이 결국 익절까지 갈지'를 예측하는
ML 필터.

breakout_reversal.detect_entries가 잡아낸 후보 진입 중 예측 성공확률이 낮은 것을
걸러내, 진입 조건 자체의 승률/평균손익이 아니라 손익비(평균이익/평균손실)를
끌어올리는 것이 목적이다. 여기서 쓰는 모든 피처는 entry_idx 시점까지의 데이터로만
계산되어 미래 데이터 누수가 없다. 라벨은 simulate_trade_path의
exit_reason(take_profit=1, 그 외=0)을 그대로 쓴다.
"""
from dataclasses import dataclass

import joblib
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, HistGradientBoostingClassifier, RandomForestClassifier

from .breakout_reversal import TradePath
from .indicators import compute_rsi

FEATURE_COLUMNS = [
    "trade_value_ratio", "return_pct", "momentum_5min", "momentum_10min",
    "volatility_10min", "volume_ratio", "rsi_14", "minutes_since_open",
    "n_day_high_distance",
]

# hist_gradient_boosting: LightGBM과 같은 히스토그램 기반 gradient boosting 구현.
# 이 환경(Windows+Python 3.14)에서 실제 lightgbm 패키지의 네이티브 DLL 로딩이
# Windows 보안정책(WinError 4551)에 막혀 대신 채택 — 알고리즘 계열은 동일하고
# sklearn 내장이라 추가 설치/서명 문제가 없다.
MODEL_TYPES = {
    "random_forest": RandomForestClassifier,
    "gradient_boosting": GradientBoostingClassifier,
    "hist_gradient_boosting": HistGradientBoostingClassifier,
}
MIN_TRAINING_SAMPLES = 50


class InsufficientTrainingDataError(RuntimeError):
    pass


@dataclass
class TrainedEntryFilterModel:
    model: object


def extract_entry_features(
    candles: pd.DataFrame,
    entry_idx: int,
    window_minutes: int = 3,
    min_trade_value: float = 4_000_000_000,
    daily_candles: pd.DataFrame | None = None,
    n_day_high: int = 5,
) -> dict:
    close = candles["close"]
    volume = candles["volume"]

    ref_idx = max(0, entry_idx - window_minutes + 1)
    window_trade_value = (close.iloc[ref_idx:entry_idx + 1] * volume.iloc[ref_idx:entry_idx + 1]).sum()
    trade_value_ratio = window_trade_value / min_trade_value if min_trade_value else 0.0
    return_pct = close.iloc[entry_idx] / close.iloc[ref_idx] - 1 if close.iloc[ref_idx] else 0.0

    momentum_5min = close.iloc[entry_idx] / close.iloc[entry_idx - 5] - 1 if entry_idx - 5 >= 0 else 0.0
    momentum_10min = close.iloc[entry_idx] / close.iloc[entry_idx - 10] - 1 if entry_idx - 10 >= 0 else 0.0

    recent_returns = close.iloc[max(0, entry_idx - 10):entry_idx + 1].pct_change().dropna()
    volatility_10min = float(recent_returns.std()) if len(recent_returns) > 1 else 0.0

    recent_avg_volume = volume.iloc[max(0, entry_idx - 10):entry_idx + 1].mean()
    volume_ratio = volume.iloc[entry_idx] / recent_avg_volume if recent_avg_volume > 0 else 1.0

    rsi_series = compute_rsi(close.iloc[:entry_idx + 1], period=14)
    rsi_14 = rsi_series.iloc[-1] if not rsi_series.empty else 50.0
    if pd.isna(rsi_14):
        rsi_14 = 50.0

    entry_time = candles.index[entry_idx]
    day_open = entry_time.normalize() + pd.Timedelta(hours=9)
    minutes_since_open = (entry_time - day_open).total_seconds() / 60

    n_day_high_distance = 0.0
    if daily_candles is not None and not daily_candles.empty:
        ref_high = daily_candles["high"].shift(1).rolling(n_day_high).max()
        entry_date = entry_time.normalize()
        if entry_date in ref_high.index:
            ref_value = ref_high.loc[entry_date]
            if pd.notna(ref_value) and ref_value > 0:
                n_day_high_distance = (close.iloc[entry_idx] - ref_value) / ref_value

    return {
        "trade_value_ratio": float(trade_value_ratio),
        "return_pct": float(return_pct),
        "momentum_5min": float(momentum_5min),
        "momentum_10min": float(momentum_10min),
        "volatility_10min": volatility_10min,
        "volume_ratio": float(volume_ratio),
        "rsi_14": float(rsi_14),
        "minutes_since_open": float(minutes_since_open),
        "n_day_high_distance": float(n_day_high_distance),
    }


def build_training_examples(
    candles: pd.DataFrame,
    paths: list[TradePath],
    window_minutes: int = 3,
    min_trade_value: float = 4_000_000_000,
    daily_candles: pd.DataFrame | None = None,
    n_day_high: int = 5,
) -> tuple[pd.DataFrame, pd.Series]:
    """각 TradePath의 entry_idx에서 피처를 뽑고, 최종 결과(익절=1/그외=0)로 라벨링한다."""
    rows = []
    labels = []
    for path in paths:
        rows.append(
            extract_entry_features(candles, path.entry_idx, window_minutes, min_trade_value, daily_candles, n_day_high)
        )
        labels.append(1 if path.exit_reason == "take_profit" else 0)

    if not rows:
        return pd.DataFrame(columns=FEATURE_COLUMNS), pd.Series(dtype=int)

    return pd.DataFrame(rows)[FEATURE_COLUMNS], pd.Series(labels)


def train_entry_filter_model(
    features: pd.DataFrame, labels: pd.Series, model_type: str = "random_forest", **model_kwargs
) -> TrainedEntryFilterModel:
    if len(features) < MIN_TRAINING_SAMPLES:
        raise InsufficientTrainingDataError(f"학습 샘플 {len(features)}개 (최소 {MIN_TRAINING_SAMPLES}개 필요)")
    if labels.nunique() < 2:
        raise InsufficientTrainingDataError("라벨이 단일 클래스뿐이라 학습 불가")

    model_cls = MODEL_TYPES[model_type]
    model = model_cls(random_state=42, **model_kwargs)
    model.fit(features[FEATURE_COLUMNS], labels)
    return TrainedEntryFilterModel(model=model)


def predict_quality_proba(trained: TrainedEntryFilterModel, features: pd.DataFrame) -> pd.Series:
    if features.empty:
        return pd.Series(dtype=float)
    proba = trained.model.predict_proba(features[FEATURE_COLUMNS])[:, 1]
    return pd.Series(proba, index=features.index)


def save_model(trained: TrainedEntryFilterModel, path: str) -> None:
    """학습된 모델을 파일로 저장 — 재학습 없이 실거래에서 계속 불러 쓰기 위함."""
    joblib.dump(trained.model, path)


def load_model(path: str) -> TrainedEntryFilterModel:
    return TrainedEntryFilterModel(model=joblib.load(path))


def predict_live_quality(
    trained: TrainedEntryFilterModel,
    candles: pd.DataFrame,
    entry_idx: int,
    window_minutes: int = 3,
    min_trade_value: float = 4_000_000_000,
    daily_candles: pd.DataFrame | None = None,
    n_day_high: int = 5,
) -> float:
    """실시간 진입 후보 시점(entry_idx)의 피처를 그 자리에서 뽑아 성공확률(0~1)을 반환.

    extract_entry_features + predict_quality_proba를 한 번에 묶은 편의 함수 —
    실거래 루프에서 "이 시점 사도 될까?"를 한 번의 호출로 물어볼 수 있게 한다.
    """
    features = extract_entry_features(candles, entry_idx, window_minutes, min_trade_value, daily_candles, n_day_high)
    features_df = pd.DataFrame([features])[FEATURE_COLUMNS]
    return float(predict_quality_proba(trained, features_df).iloc[0])
