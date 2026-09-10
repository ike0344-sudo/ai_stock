"""전략 evaluate()가 미래 봉을 쓰지 않는지 검증하는 공용 헬퍼.

tests/backtesting/ml/test_features.py의 test_features_do_not_use_future_data와 같은
돌연변이 방식 — 미래 시점 값을 크게 바꿔놓고, 그보다 훨씬 과거 시점의 신호가 그대로인지
직접 증명한다(날짜창 경계만 보는 정적 검증보다 강함).

배경: state/agent_reports/strategy-agent_20260910-153500_tradingagents_salvage.md §2
"""
import pandas as pd


def assert_signals_do_not_use_future_data(
    strategy, params: dict, candles: pd.DataFrame, check_until: int, mutate_at: int = -1,
) -> None:
    """candles[mutate_at] 행을 크게 흔들어도 candles[:check_until] 신호가 안 변해야 한다."""
    mutated = candles.copy()
    idx = mutated.index[mutate_at]
    for col in mutated.columns:
        original_value = mutated.loc[idx, col]
        # volume은 0으로 죽이고(거래량 조건 트리거 여부가 뒤집힐 수 있는 값), 그 외
        # 가격류 컬럼은 5배로 부풀려 "미래가 바뀌면 눈에 띄게 다른 값"으로 만든다.
        mutated.loc[idx, col] = 0 if col == "volume" else original_value * 5

    original_signals = strategy.evaluate(candles, params)
    mutated_signals = strategy.evaluate(mutated, params)

    pd.testing.assert_series_equal(
        original_signals.iloc[:check_until], mutated_signals.iloc[:check_until], check_names=False,
    )
