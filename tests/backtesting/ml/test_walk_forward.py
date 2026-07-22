from datetime import date

from backtesting.ml.walk_forward import split


def test_splits_maintain_time_order():
    splits = split(start=date(2026, 1, 1), end=date(2026, 3, 1), train_days=30, test_days=10, step_days=10)

    assert len(splits) > 0
    for s in splits:
        assert s.train_start < s.train_end
        assert s.train_end < s.test_start
        assert s.test_start <= s.test_end


def test_splits_do_not_exceed_end_date():
    end = date(2026, 3, 1)
    splits = split(start=date(2026, 1, 1), end=end, train_days=30, test_days=10, step_days=10)

    for s in splits:
        assert s.test_end <= end


def test_splits_move_forward_by_step_days():
    splits = split(start=date(2026, 1, 1), end=date(2026, 4, 1), train_days=20, test_days=5, step_days=10)

    for earlier, later in zip(splits, splits[1:]):
        assert (later.train_start - earlier.train_start).days == 10
