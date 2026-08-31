from backtesting.strategy_catalog import describe_strategy


def test_describe_strategy_returns_rules_for_known_strategy():
    description = describe_strategy("strategy_1")

    assert set(description.keys()) == {"entry", "exit", "operation", "exchange_basis"}
    assert len(description["entry"]) > 0


def test_describe_strategy_returns_rules_for_strategy_2():
    description = describe_strategy("strategy_2")

    assert set(description.keys()) == {"entry", "exit", "operation", "exchange_basis"}
    assert len(description["entry"]) > 0


def test_describe_strategy_returns_empty_dict_for_unknown_strategy():
    description = describe_strategy("strategy_99")

    assert description == {}
