"""RandomForest/GradientBoosting 학습·예측 래퍼.

Design: docs/02-design/features/strategy-backtesting.design.md §4.1, §6.1
"""
from dataclasses import dataclass

import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier

MODEL_TYPES = {
    "random_forest": RandomForestClassifier,
    "gradient_boosting": GradientBoostingClassifier,
}

MIN_TRAINING_SAMPLES = 50


class InsufficientTrainingDataError(RuntimeError):
    pass


@dataclass
class TrainedModel:
    model: object
    feature_columns: list[str]


def train(
    features: pd.DataFrame,
    labels: pd.Series,
    model_type: str = "random_forest",
    **model_kwargs,
) -> TrainedModel:
    combined = features.join(labels.rename("label")).dropna()
    if len(combined) < MIN_TRAINING_SAMPLES:
        raise InsufficientTrainingDataError(
            f"학습 샘플 {len(combined)}개 (최소 {MIN_TRAINING_SAMPLES}개 필요)"
        )
    if combined["label"].nunique() < 2:
        raise InsufficientTrainingDataError("라벨이 단일 클래스뿐이라 학습 불가 (매수/비매수 사례가 모두 필요)")

    model_cls = MODEL_TYPES[model_type]
    model = model_cls(random_state=42, **model_kwargs)
    model.fit(combined[features.columns], combined["label"])

    return TrainedModel(model=model, feature_columns=list(features.columns))


def predict(trained: TrainedModel, features: pd.DataFrame) -> pd.Series:
    """양성(라벨=1) 확률을 반환. 특징에 NaN이 있는 행은 확률 0으로 처리한다(매수 보류)."""
    valid = features[trained.feature_columns].dropna()
    proba = pd.Series(0.0, index=features.index)
    if not valid.empty:
        predicted = trained.model.predict_proba(valid)[:, 1]
        proba.loc[valid.index] = predicted
    return proba
