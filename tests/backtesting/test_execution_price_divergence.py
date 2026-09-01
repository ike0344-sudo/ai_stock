import numpy as np
import pandas as pd
import pytest

from backtesting.execution_price_divergence import group_comparison_report


def test_group_comparison_report_uses_is_thresholds_on_oos_unchanged():
    train = pd.DataFrame({
        "date": ["d1"] * 10, "w3_divergence": list(range(10)),
        "ret_1m": [0.01] * 10, "ret_3m": [0.01] * 10, "ret_5m": [0.01] * 10, "ret_10m": [0.01] * 10,
        "price_t": [10_000.0] * 10,
    })
    test = pd.DataFrame({
        "date": ["d2"] * 10, "w3_divergence": list(range(10)),
        "ret_1m": [0.02] * 10, "ret_3m": [0.02] * 10, "ret_5m": [0.02] * 10, "ret_10m": [0.02] * 10,
        "price_t": [10_000.0] * 10,
    })
    # IS 하위10%(<=0.9번째분위, 값 0)와 상위10%(>=8.1번째분위, 값 9) 문턱 -> OOS도 같은 값(0,9)로 걸러야 함

    report = group_comparison_report(train, test, "w3_divergence")

    oos_slow = report[(report["group"] == "OOS") & (report["side"] == "느린(하위10%)") & (report["label"] == "ret_1m")]
    assert oos_slow.iloc[0]["n"] == 1  # OOS에서 w3_divergence<=0 인 행은 값0인 1개뿐
    assert oos_slow.iloc[0]["gross_mean_pct"] == pytest.approx(2.0)
