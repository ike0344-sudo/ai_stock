"""'무장(armed) 이후 반전' ML 분류기 — breakout_reversal의 본전손절 판단을 담당.

무장 시점(peak 순수익률 >= breakeven_arm_pct) 이후의 매 분마다, 이 거래가 결국
익절(take_profit)에 도달할지(1) 아니면 손절/EOD로 끝날지(0)를 예측한다. 예측
확률이 낮으면(반전 가능성 높음) 그 시점에 현재가로 조기 청산해 본전 근처에서
빠져나온다.
"""
from dataclasses import dataclass

import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier

from .breakout_reversal import TradePath, simulate_trade_path

FEATURE_COLUMNS = [
    "current_net_pct", "peak_net_pct", "drawdown_from_peak",
    "minutes_since_entry", "minutes_since_peak",
    "recent_return_1min", "recent_return_3min", "volume_ratio",
]

MODEL_TYPES = {"random_forest": RandomForestClassifier, "gradient_boosting": GradientBoostingClassifier}
MIN_TRAINING_SAMPLES = 50


class InsufficientTrainingDataError(RuntimeError):
    pass


@dataclass
class TrainedReversalModel:
    model: object


def extract_armed_features(candles: pd.DataFrame, path: TradePath, breakeven_arm_pct: float) -> pd.DataFrame:
    """path.path(무장 여부와 무관한 전체 경로)에서 armed 구간만 골라 시점별 피처를 만든다."""
    rows = []
    peak_idx = path.entry_idx
    peak_so_far = 0.0

    for idx, net_pct, peak_net_pct in path.path:
        if net_pct >= peak_so_far:
            peak_so_far = net_pct
            peak_idx = idx
        if peak_net_pct < breakeven_arm_pct:
            continue  # 아직 무장 전

        close = candles["close"]
        recent_return_1min = close.iloc[idx] / close.iloc[idx - 1] - 1 if idx - 1 >= 0 else 0.0
        recent_return_3min = close.iloc[idx] / close.iloc[idx - 3] - 1 if idx - 3 >= 0 else 0.0
        volume = candles["volume"]
        recent_avg_volume = volume.iloc[max(0, idx - 10):idx + 1].mean()
        volume_ratio = volume.iloc[idx] / recent_avg_volume if recent_avg_volume > 0 else 1.0

        rows.append(
            {
                "idx": idx,
                "current_net_pct": net_pct,
                "peak_net_pct": peak_net_pct,
                "drawdown_from_peak": peak_net_pct - net_pct,
                "minutes_since_entry": idx - path.entry_idx,
                "minutes_since_peak": idx - peak_idx,
                "recent_return_1min": recent_return_1min,
                "recent_return_3min": recent_return_3min,
                "volume_ratio": volume_ratio,
            }
        )

    return pd.DataFrame(rows)


def build_training_examples(
    candles: pd.DataFrame, paths: list[TradePath], breakeven_arm_pct: float = 0.01
) -> tuple[pd.DataFrame, pd.Series]:
    """여러 TradePath에서 armed 구간의 (피처, 라벨) 쌍을 모은다.

    라벨: 해당 거래가 최종적으로 take_profit에 도달했으면 1, 아니면(stop_loss/eod) 0.
    같은 거래의 armed 시점들은 모두 같은 라벨을 공유한다 (거래 단위 결과이므로).
    """
    feature_frames = []
    label_lists = []

    for path in paths:
        features = extract_armed_features(candles, path, breakeven_arm_pct)
        if features.empty:
            continue
        label = 1 if path.exit_reason == "take_profit" else 0
        feature_frames.append(features[FEATURE_COLUMNS])
        label_lists.append(pd.Series([label] * len(features)))

    if not feature_frames:
        return pd.DataFrame(columns=FEATURE_COLUMNS), pd.Series(dtype=int)

    return pd.concat(feature_frames, ignore_index=True), pd.concat(label_lists, ignore_index=True)


def train_reversal_model(
    features: pd.DataFrame, labels: pd.Series, model_type: str = "random_forest", **model_kwargs
) -> TrainedReversalModel:
    if len(features) < MIN_TRAINING_SAMPLES:
        raise InsufficientTrainingDataError(f"학습 샘플 {len(features)}개 (최소 {MIN_TRAINING_SAMPLES}개 필요)")
    if labels.nunique() < 2:
        raise InsufficientTrainingDataError("라벨이 단일 클래스뿐이라 학습 불가")

    model_cls = MODEL_TYPES[model_type]
    model = model_cls(random_state=42, **model_kwargs)
    model.fit(features[FEATURE_COLUMNS], labels)
    return TrainedReversalModel(model=model)


def predict_success_probability(trained: TrainedReversalModel, features: pd.DataFrame) -> pd.Series:
    if features.empty:
        return pd.Series(dtype=float)
    proba = trained.model.predict_proba(features[FEATURE_COLUMNS])[:, 1]
    return pd.Series(proba, index=features.index)


def simulate_trade_path_with_ml_exit(
    candles: pd.DataFrame,
    entry_idx: int,
    trained: TrainedReversalModel,
    take_profit_pct: float = 0.03,
    stop_loss_pct: float = 0.02,
    breakeven_arm_pct: float = 0.01,
    reversal_threshold: float = 0.5,
    commission_rate: float = 0.00015,
    slippage_rate: float = 0.001,
) -> TradePath:
    """익절/손절/EOD 하드 경계는 그대로 두되, 무장 이후 매 분 ML이 '반전(실패) 가능성
    높음'으로 판단하면(예측확률 < reversal_threshold) 그 시점 현재가로 조기 청산한다.
    """
    entry_price = candles["close"].iloc[entry_idx] * (1 + slippage_rate)
    entry_time = candles.index[entry_idx]
    entry_day = entry_time.normalize()

    two_way_commission = commission_rate * 2
    n = len(candles)
    peak_pct = 0.0
    peak_idx = entry_idx
    path: list[tuple] = []
    exit_idx, exit_reason = entry_idx, "eod"

    for j in range(entry_idx, n):
        ts = candles.index[j]
        if ts.normalize() != entry_day:
            exit_idx, exit_reason = j - 1, "eod"
            break

        exit_price_if_now = candles["close"].iloc[j] * (1 - slippage_rate)
        net_pct = (exit_price_if_now - entry_price) / entry_price - two_way_commission
        if net_pct >= peak_pct:
            peak_pct = net_pct
            peak_idx = j
        path.append((j, net_pct, peak_pct))

        if net_pct >= take_profit_pct:
            exit_idx, exit_reason = j, "take_profit"
            break
        if net_pct <= -stop_loss_pct:
            exit_idx, exit_reason = j, "stop_loss"
            break

        if peak_pct >= breakeven_arm_pct:
            close = candles["close"]
            recent_return_1min = close.iloc[j] / close.iloc[j - 1] - 1 if j - 1 >= 0 else 0.0
            recent_return_3min = close.iloc[j] / close.iloc[j - 3] - 1 if j - 3 >= 0 else 0.0
            volume = candles["volume"]
            recent_avg_volume = volume.iloc[max(0, j - 10):j + 1].mean()
            volume_ratio = volume.iloc[j] / recent_avg_volume if recent_avg_volume > 0 else 1.0

            feature_row = pd.DataFrame(
                [
                    {
                        "current_net_pct": net_pct, "peak_net_pct": peak_pct,
                        "drawdown_from_peak": peak_pct - net_pct,
                        "minutes_since_entry": j - entry_idx, "minutes_since_peak": j - peak_idx,
                        "recent_return_1min": recent_return_1min, "recent_return_3min": recent_return_3min,
                        "volume_ratio": volume_ratio,
                    }
                ]
            )
            success_proba = predict_success_probability(trained, feature_row).iloc[0]
            if success_proba < reversal_threshold:
                exit_idx, exit_reason = j, "ml_breakeven"
                break
    else:
        exit_idx, exit_reason = n - 1, "eod"

    exit_price = candles["close"].iloc[exit_idx] * (1 - slippage_rate)
    net_pnl_pct = (exit_price - entry_price) / entry_price - two_way_commission

    return TradePath(
        entry_idx=entry_idx, entry_time=entry_time, entry_price=entry_price,
        exit_idx=exit_idx, exit_time=candles.index[exit_idx], exit_price=exit_price,
        exit_reason=exit_reason, net_pnl_pct=net_pnl_pct, peak_pnl_pct=peak_pct, path=path,
    )
