import numpy as np
import pandas as pd
import pytest

from backtesting.ml import model as ml_model


def _synthetic_data(n: int = 200):
    rng = np.random.default_rng(42)
    features = pd.DataFrame({"f1": rng.normal(size=n), "f2": rng.normal(size=n)})
    labels = pd.Series((features["f1"] > 0).astype(float), index=features.index)
    return features, labels


def test_train_and_predict_round_trip():
    features, labels = _synthetic_data()

    trained = ml_model.train(features, labels, model_type="random_forest", n_estimators=10)
    proba = ml_model.predict(trained, features)

    assert len(proba) == len(features)
    assert proba.between(0, 1).all()


def test_train_raises_on_insufficient_data():
    features = pd.DataFrame({"f1": [0.1, 0.2], "f2": [0.3, 0.4]})
    labels = pd.Series([1.0, 0.0])

    with pytest.raises(ml_model.InsufficientTrainingDataError):
        ml_model.train(features, labels)


def test_predict_handles_missing_features_without_error():
    features, labels = _synthetic_data()
    trained = ml_model.train(features, labels, model_type="random_forest", n_estimators=10)

    features_with_nan = features.copy()
    features_with_nan.iloc[0, 0] = float("nan")

    proba = ml_model.predict(trained, features_with_nan)

    assert proba.iloc[0] == 0.0
