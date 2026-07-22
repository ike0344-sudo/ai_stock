"""워크포워드 학습/검증 구간 분할기.

Design: docs/02-design/features/strategy-backtesting.design.md §4.1
학습 구간이 항상 검증 구간보다 시간상 앞서도록 강제한다 (lookahead 방지).
"""
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class WalkForwardSplit:
    train_start: date
    train_end: date
    test_start: date
    test_end: date


def split(
    start: date,
    end: date,
    train_days: int,
    test_days: int,
    step_days: int,
) -> list[WalkForwardSplit]:
    """[start, end] 범위를 train_days/test_days 크기로 step_days만큼 이동하며 분할.

    분할이 end를 넘어서면 중단한다. 달력일 기준 근사치이며 실제 거래일과는 다를 수 있다.
    """
    splits: list[WalkForwardSplit] = []
    train_start = start

    while True:
        train_end = train_start + timedelta(days=train_days - 1)
        test_start = train_end + timedelta(days=1)
        test_end = test_start + timedelta(days=test_days - 1)

        if test_end > end:
            break

        splits.append(WalkForwardSplit(train_start, train_end, test_start, test_end))
        train_start = train_start + timedelta(days=step_days)

    return splits
