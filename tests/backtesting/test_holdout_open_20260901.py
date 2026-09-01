from backtesting.holdout_open_20260901 import classify_verdict


def test_classify_verdict_confirms_when_positive_return_and_pf_at_least_1():
    assert classify_verdict(total_return_pct=2.0, profit_factor=1.05, n_trades=100) == "확증"


def test_classify_verdict_fails_when_pf_below_worst_observed_fold():
    assert classify_verdict(total_return_pct=1.0, profit_factor=0.75, n_trades=100) == "실패(재현 실패)"


def test_classify_verdict_fails_when_return_not_positive():
    assert classify_verdict(total_return_pct=-0.5, profit_factor=1.10, n_trades=100) == "실패(재현 실패)"


def test_classify_verdict_gray_zone_between_thresholds():
    assert classify_verdict(total_return_pct=0.5, profit_factor=0.90, n_trades=100) == "혼조(그레이존)"


def test_classify_verdict_holds_when_too_few_trades():
    assert classify_verdict(total_return_pct=5.0, profit_factor=2.0, n_trades=10) == "판단보류(표본부족)"
