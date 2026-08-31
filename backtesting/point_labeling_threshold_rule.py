"""지점 라벨링 4단계에서 검증된 6개 피처로 만든 가장 단순한 임계값 규칙 —
모델 학습 없이 "활동 급증(activity burst)"만 탐지한다.

## 이 파일의 위치와 한계 (먼저 읽을 것)
- Strategy 프로토콜(일봉, generate_signals)을 따르지 않는다 — 틱 단위로 동작하고
  ofi_divergence_scalp.py처럼 별도 구조를 쓴다. final_strategy.py는 여전히
  import 안 함(지시 그대로, 섞지 않는다).
- point_labeling.py의 RELIABLE_FEATURES만 참조한다(중복 정의 방지).

## 방향(상승/하락) 구분 불가 — 숨기지 않고 먼저 밝힌다
검증된 6개는 전부 "이 순간이 얼마나 활발한가" 류라서 SHOOT/CRASH 둘 다 CONTROL
대비 같은 방향으로 갈린다(4단계 결과 그대로) — 즉 이 규칙은 "곧 큰 움직임이
온다"는 탐지일 뿐 "오른다/내린다"를 모른다. 방향을 알 유일한 후보였던
buy_initiated_ratio/order_flow_imbalance는 지금 신뢰불가 상태(point_labeling.py
UNRELIABLE_FEATURES)라 못 쓴다. 그래서 출력은 Strategy의 signal(진입/청산)이
아니라 burst_detected 불리언이다 — "일단 롱으로 가정" 같은 근거 없는 방향
가정을 신호에 섞지 않는다. 방향 결합(예: 신고가 근접 등 기존 필터와 병행)은
다음 단계로 명시적으로 남겨둔다.

## [2026-08-30 22:30 실측 결과 + 결정] "6개 전부(AND)"는 수학적으로 공집합이었다
backtest-agent 실측(`backtest-agent_20260830-220000_threshold-rule-verification.md`):
CONTROL(1000만)·SHOOT(591,756)·CRASH(521,564) **전부 0건 발동**. 버그 아님 —
SHOOT 591,756건 중 6개 조건을 동시에 만족한 최댓값이 **5/6**(6/6은 아무도
없음)이었다고 직접 검산 확인됨. 개별 통과율은 6.5%(intraday_cum_return)~
65.2%(price_flatness)로 각 피처는 정상 작동하는데(CONTROL 기준 1.64%보다
훨씬 높게 SHOOT를 잡아냄), 상관이 완전하지 않은 6개 꼬리조건을 AND로 겹치면
교집합이 산술적으로 빈다 — "발동이 너무 희소하면 그 자체로 유효한 결과"라고
미리 밝혀둔 대로 처리한다: **K=6(전부)는 기각, K=5(6개 중 5개 이상)로
완화해 재평가한다.** 이건 결과 보고 기준을 맞추는 리크가 아니다 — "너무
희소하면 안다는 것 자체가 답"이라고 사전에 명시해뒀고, 그 판단을 실측
후에 내리는 것도 그 사전등록에 이미 포함돼 있었다(K를 얼마로 낮출지는
결과가 나오기 전엔 정할 수 없는 값이라 미정으로 남겨뒀던 것뿐).
**정지 규칙**: K=5도 CONTROL과 구분 안 되면(선택적이지 않으면) 거기서
멈추고 "AND형 결합 자체가 이 6개 피처로는 안 된다"로 결론 낸다 — K=4,
K=3으로 계속 낮추면서 뭔가 나올 때까지 뒤지지 않는다.

## [2026-08-30 23:03 K=5 재측정 — 채택] 정지규칙 안 걸림, 살아있다
backtest-agent 실측(`backtest-agent_20260830-230200_threshold-rule-k5-result.md`):
CONTROL 450/10,000,000(0.0045%) vs SHOOT 19,939/591,756(3.37%) vs CRASH
25,239/521,564(4.84%) — CONTROL 대비 SHOOT 749배, CRASH 1076배(직접
재검산 일치). 세 그룹이 전혀 안 비슷하다 — 정지규칙 미발동, **K=5 채택**.
**추가 계산(내가 도출, 실제 배치 규모로 환산)**: CONTROL 10,000,000은
표본이고 실제 오염제거 CONTROL 전체는 66,781,118 — 발동률을 그대로
전체에 적용하면 예상 CONTROL 오탐 ≈66,781,118×0.000045≈3,005건. 전체
발동(3,005+19,939+25,239=48,183건) 중 진짜 SHOOT/CRASH(45,178건) 비율
= **precision ≈93.8%** — 규칙이 뜨면 10번 중 9번 이상은 진짜 사건이라는
뜻. 다만 재현율은 낮다(SHOOT의 3.37%/CRASH의 4.84%만 잡음) — "거의 다
잡되 가끔 틀림"이 아니라 "드물게 뜨되 뜨면 거의 확실함" 쪽 신호다.
**CRASH가 SHOOT보다 1.44배 더 자주 뜨는 것은 방향정보로 쓰지 않는다** —
이미 알려진 사실(CRASH가 SHOOT보다 활동성 피처 자체가 원래 더 크다,
4단계 결과)의 재확인일 뿐, 오늘 방향판정(2단계)이 "약함/불확실"로 종결된
걸 우회하는 뒷문으로 쓰면 안 된다.
**실사용 시 `min_count=5`를 명시적으로 넘길 것** — 기본값(6)은 "전부
실패"라는 이력 보존용이지 권장값이 아니다.

## 자유 파라미터는 사실상 2개
1) **min_count(=K)** — 실측으로 6 기각, **5 채택**(위 항목 참고). 기본값은
   여전히 `len(RELIABLE_FEATURES)`=6(이력 보존용, 실사용은 5를 명시).
2) **문턱값 도출 방식**: 각 피처의 문턱값 = CONTROL(오염제거 NEUTRAL) 분포에서
   "라벨 이벤트(SHOOT+CRASH)가 전체에서 차지하는 비율(BASE_RATE)만큼 극단적인"
   분위수. SHOOT/CRASH 자신의 피처 값으로 맞추지 않는다(그러면 정답을 보고
   규칙을 짜는 것). "피처가 사건만큼 희귀해야 한다"는 것 자체가 하나의 가설이지
   증명된 사실은 아니다 — 그렇게 명시한다. BASE_RATE는 라벨링 단계에서 이미
   정해진 실측 카운트에서만 계산하고, 내가 임의로 고른 숫자가 아니다.

## 문턱값 실제 숫자는 여기 없다
나는 CONTROL 그룹의 중앙값만 받았지 원본 분포를 못 받았다(실행 도구 없음).
derive_thresholds()는 CONTROL 표본 원본(피처 컬럼이 있는 DataFrame)을 받아
분위수를 실제로 계산한다 — 숫자를 지어내지 않는다. backtest-agent가 보유한
`results/point_labeling_features_labels.parquet`에서 label==0(오염제거
CONTROL 표본)을 골라 넘기면 된다.
"""
import pandas as pd

from .point_labeling import RELIABLE_FEATURES

# 2026-08-30 4단계 실측 카운트(backtest-agent_20260830-193200_stage4-final.md) —
# 내가 고른 숫자 아니고 이미 확정된 라벨 카운트를 그대로 씀.
SHOOT_COUNT = 591_756
CRASH_COUNT = 521_564
CONTROL_POOL_SIZE = 66_781_118
BASE_RATE = (SHOOT_COUNT + CRASH_COUNT) / (SHOOT_COUNT + CRASH_COUNT + CONTROL_POOL_SIZE)  # ~1.64%


def derive_thresholds(control_baseline: pd.DataFrame, base_rate: float = BASE_RATE) -> dict[str, float]:
    """control_baseline: CONTROL 표본의 피처 원본 DataFrame(컬럼=RELIABLE_FEATURES
    이름들). 피처마다 "사건 비율만큼 극단적인" 분위수를 계산한다 — high 방향은
    상위(1-base_rate)분위, low 방향은 하위(base_rate)분위."""
    thresholds = {}
    for feature, direction in RELIABLE_FEATURES:
        quantile = (1 - base_rate) if direction == "high" else base_rate
        thresholds[feature] = control_baseline[feature].quantile(quantile)
    return thresholds


def detect_activity_burst(
    features: pd.DataFrame, thresholds: dict[str, float], min_count: int = len(RELIABLE_FEATURES)
) -> pd.Series:
    """features: compute_microstructure_features() 출력과 같은 컬럼명의
    DataFrame. min_count: 동시에 만족해야 하는 조건 개수(기본값=6, 즉 전부 —
    실측 결과 6은 공집합이었다, 모듈 docstring 2026-08-30 항목 참고). 반환:
    min_count개 이상 만족하는 시점만 True(방향은 모른다 — 매수/매도 신호가
    아니라 탐지 플래그)."""
    passed_count = pd.Series(0, index=features.index)
    for feature, direction in RELIABLE_FEATURES:
        threshold = thresholds[feature]
        if direction == "high":
            passed_count += (features[feature] >= threshold).astype(int)
        else:
            passed_count += (features[feature] <= threshold).astype(int)
    return passed_count >= min_count


def demo() -> None:
    """자체점검: ①BASE_RATE 계산이 실측 카운트 손합산과 일치 ②합성 CONTROL
    표본에서 분위수 도출이 손계산과 맞는지 ③AND 결합 — 6개 중 1개만 깨져도
    전체 False인지 경계 케이스로 확인."""
    assert abs(BASE_RATE - 1_113_320 / 67_894_438) < 1e-12  # 591756+521564, +66781118 손검산

    # 합성 CONTROL: 6개 컬럼 전부 0..99 균등분포(분위수 손계산이 쉽도록)
    control = pd.DataFrame({name: range(100) for name, _ in RELIABLE_FEATURES})
    thresholds = derive_thresholds(control, base_rate=0.05)  # 실측 1.64% 대신 검산 쉬운 5% 사용(자체점검 전용)
    # linear보간: quantile(0.95)=94.05, quantile(0.05)=4.95 (n=100, position=q*99)
    high_feature = RELIABLE_FEATURES[0][0]
    assert 94.0 <= thresholds[high_feature] <= 94.1
    low_feature = next(name for name, direction in RELIABLE_FEATURES if direction == "low")
    assert 4.9 <= thresholds[low_feature] <= 5.0

    # 경계 케이스: row0=6개 전부 통과(6/6), row1=low_feature 하나만 깨뜨림(5/6)
    passing_row = {
        name: thresholds[name] + (1 if direction == "high" else -1)
        for name, direction in RELIABLE_FEATURES
    }
    features = pd.DataFrame([passing_row, passing_row])
    features.loc[1, low_feature] = thresholds[low_feature] + 100  # low인데 훨씬 큼 -> 조건 위반
    # 기본값(min_count=6, 전부): row0(6/6)만 True, row1(5/6)은 False
    # — 2026-08-30 실측(6/6이 SHOOT/CRASH/CONTROL 전부 0건)과 같은 동작을 검증
    result_k6 = detect_activity_burst(features, thresholds)
    assert result_k6.iloc[0] == True and result_k6.iloc[1] == False
    # min_count=5로 완화하면: row0(6/6)·row1(5/6) 둘 다 True — K 완화 결정 반영
    result_k5 = detect_activity_burst(features, thresholds, min_count=5)
    assert result_k5.iloc[0] == True and result_k5.iloc[1] == True

    print("demo ok: BASE_RATE 손검산 일치 / 분위수 도출 정확 / min_count=6(전부)과 "
          "5(완화) 둘 다 경계 케이스대로 동작 확인")


if __name__ == "__main__":
    demo()
