"""전략 ID -> 정적 진입/청산/운용 규칙 설명 매핑. run-trading 실행 여부와 무관하게
대시보드가 "이 전략이 뭘 하는 전략인지" 보여줄 때 쓴다(대시보드 실행 조건 패널은
run-trading이 실제로 시작돼야 채워지는 것과 달리, 이건 코드에 정의된 규칙이라 항상
조회 가능하다). final_strategy.py의 실제 상수값에서 문구를 만들어 설명이 코드와
어긋나지 않게 한다 — 값이 바뀌면 여기 문구도 자동으로 같이 바뀐다.

새 전략(전략2 등)이 추가되면 그 전략의 규칙 모듈에 describe_* 함수를 만들고
STRATEGY_DESCRIPTIONS에 등록만 하면 대시보드가 자동으로 노출한다.
"""
from .final_strategy import describe_strategy_1

STRATEGY_DESCRIPTIONS = {
    "strategy_1": describe_strategy_1,
}


def describe_strategy(strategy: str) -> dict:
    """정의된 전략이면 규칙 설명 dict, 아직 규칙이 등록되지 않은 전략(전략2 대기 중 등)이면
    빈 dict — dashboard_data.py의 load_* 함수들과 동일하게 "없으면 빈 값" 규칙을 따른다."""
    factory = STRATEGY_DESCRIPTIONS.get(strategy)
    return factory() if factory else {}
