import pandas as pd

from backtesting.theme_rank_remeasure_41d import _h1_summary, _h3_summary


def test_h1_summary_rejects_at_condition1_when_mean_negative():
    is_df = pd.DataFrame({
        "change_net": [-0.01, -0.02, -0.03, -0.01, -0.02] * 5,  # 25건, 평균<0
        "level_net": [0.0] * 25,
    })
    oos_df = pd.DataFrame({"change_net": [0.01] * 10, "level_net": [0.0] * 10})

    row = _h1_summary(is_df, oos_df, "테스트")

    assert row["verdict"] == "기각(조건1)"
    assert row["n_is"] == 25


def test_h1_summary_holds_when_sample_too_small():
    is_df = pd.DataFrame({"change_net": [0.01] * 5, "level_net": [0.0] * 5})
    oos_df = pd.DataFrame({"change_net": [], "level_net": []})

    row = _h1_summary(is_df, oos_df, "테스트")

    assert row["verdict"] == "판단보류(표본부족)"


def test_h3_summary_rejects_when_diff_below_cost_threshold():
    # 평균은 양수·유의하지만 절대크기가 비용(0.52%)보다 작음 -> 기각조건2
    is_df = pd.DataFrame({"diff": [0.001, 0.0011, 0.0009, 0.001, 0.0012] * 5})
    oos_df = pd.DataFrame({"diff": [0.001] * 10})

    row = _h3_summary(is_df, oos_df, "테스트")

    assert row["verdict"] == "기각(조건1/2)"
