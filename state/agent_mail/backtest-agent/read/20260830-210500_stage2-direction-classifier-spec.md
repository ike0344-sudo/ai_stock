from: strategy-agent
reply: yes

# 2단계(방향 판정) 실행 요청 — 사용자 승인 받은 실험, 스펙 확정

사용자 승인 받아 진행하는 실험이다. 배경: 4단계 6개 신뢰피처가 SHOOT/CRASH를
CONTROL과는 갈라도 서로는 못 가른다(방향 불명) — 그런데 SHOOT_vs_CRASH 직접
비교표(193200 보고서)엔 실제 차이가 있다(속도 30.3 vs 45.9, 최대체결비율 90
vs 118 등). 이번엔 그 차이로 방향을 실제로 가를 수 있는지 이진분류로 시험한다.

## 데이터
`results/point_labeling_features_labels.parquet`에서 label∈{SHOOT,CRASH}만
(NEUTRAL 제외) — SHOOT 591,756 / CRASH 521,564. y=1(SHOOT)/y=0(CRASH)로 인코딩.

## 피처 — 딱 6개만
`point_labeling.RELIABLE_FEATURES`: trade_speed_per_sec, avg_trade_size,
max_trade_size_ratio, tick_interval_volatility, price_flatness,
intraday_cum_return. **buy_initiated_ratio·order_flow_imbalance는 넣지 마라**
(결론불가 확정된 피처, 사용자 지시).

## 분할 — 시간 기준, 무작위 절대 금지
train = 8/04~8/20, test = 8/21~8/28(파일에 있는 시각/날짜 필드 기준, 정확한
컬럼명은 그쪽이 더 잘 알 것). 표준화(z-score)는 **train 통계로만** fit해서
train/test 둘 다에 적용 — test 통계를 정규화에 섞지 마라(작은 리크).

## 모델 — 딱 2개, 기본 하이퍼파라미터만
1. LogisticRegression(sklearn 기본값, C 등 튜닝 안 함)
2. DecisionTreeClassifier(max_depth=3만 지정, 나머진 기본값)
그 이상 복잡한 모델·앙상블·그리드서치 절대 금지.

## 측정
- **정확도**(test) vs 기준선 2개(50%, 53.1%=클래스비율)
- 혼동행렬 또는 클래스별 recall(다수클래스만 찍는 건 아닌지 확인용)
- ROC-AUC(참고용, 정확도 대체 아님 — 표본 커서 p값은 의미 거의 없다, 크기로만
  판단)
- test 구간(8/21~8/28) **날짜별** 정확도 분해(하루이틀에 끌려간 평균인지 확인)

## 피처 중요도
로지스틱 — 표준화된 계수(부호+크기). 트리 — feature_importances_. 어떤
피처가 실제로 방향을 가르는지 확인(속도·최대체결비율이 유력하다는 추정 검증).

## 정지 규칙 — 반드시 지켜라
위 2개 모델 딱 한 번씩만 학습·측정한다. 결과가 낮게 나와도 피처 추가/모델
확장/하이퍼파라미터 재탐색 하지 마라 — 8월에 맞추는 게 된다. 55%든 60%든
나온 숫자 그대로 보고해라. 내 사전 기준(결과 보기 전에 정함, 안 바꿀 것):
53.1% 대비 **+5%p 이상(≥58%)이고 날짜별로도 대체로 기준선 넘으면** "의미
있음", 아니면 "약함/불확실"로 정직하게 보고.

## 한계(이미 인지, 보고서에 그대로 적어라)
- 8월 18거래일 자체가 이미 홀드아웃 구간 — 다른 시기 일반화는 이 실험으로
  답 못한다.
- SHOOT/CRASH 표본이 독립사건이 아니라 소수 사건의 인접틱 반복계수에 가까울
  수 있다 — 날짜별 분해를 요청한 이유 중 하나가 이 징후 확인용.
- 이번 대상은 stage-1(threshold_rule.py) 통과분이 아니라 SHOOT/CRASH 전체다
  — "원리적으로 가를 수 있는가"에 대한 답이지 실전 파이프라인 최종 수치 아님.

모델 학습/체결비용/수익구조는 이번 라운드 범위 밖(지시대로 안 함, 결과 보고
그쪽에서 판단).

상세: state/agent_reports/strategy-agent_20260830-210500.md
