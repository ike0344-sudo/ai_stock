# 지점 라벨링 4단계 최종 결과 — 대조군 비교 + Mann-Whitney U (2026-08-30)

전제: 이번 라운드는 **라벨+피처+분포비교까지만** — 모델 학습 없음, 전략 채택/성과
판단 아님. SHOOT/CRASH가 NEUTRAL과 미세구조적으로 다른지, 다르다면 어느 피처에서
얼마나 다른지를 서술하는 탐색적 분석이다.

## 0. 보고 직전 발견한 조인 버그 — 1차 결과 폐기, 재실행함

1차 실행에서 "오염제거 NEUTRAL 풀 21억 행"이 나왔는데 이건 물리적으로 불가능하다
(전체 틱이 6900만 개뿐). 원인: `contam` 테이블을 다시 `fl`에 조인할 때 키로
`(code,date_str,ts)`를 썼는데, 동시각 틱(같은 초에 여러 체결, 특히 장초반 버스트
구간)이 양쪽 테이블에 똑같이 중복돼 있어서 k개짜리 동시각 그룹이 k×k로 부풀었다.

- SHOOT/CRASH 카운트(591,756 / 521,564)는 조인 없이 직접 COUNT라 영향 없음.
- **영향은 CONTROL(대조군) 표본에만 있었다** — 부풀려진 풀에서 reservoir 샘플링을
  하면 동시각(버스트) NEUTRAL 틱이 조용한 구간 NEUTRAL 틱보다 훨씬 더 많이
  뽑힌다. 버스트 구간은 원래 SHOOT/CRASH와 활동성 지표(체결속도·체결크기 등)가
  비슷하므로, 이 버그는 **CONTROL을 실제보다 SHOOT/CRASH에 더 가깝게 보이게
  만들어 진짜 차이를 과소평가하는 방향**으로 작용했다.
- 고유 row id(`rid`)로 조인하도록 고쳐 재실행. 풀 크기가 66,781,118행으로
  나왔고(전체 틱 70,912,254 이하 — sanity assert 통과), 재실행 후 대조군 관련
  수치가 전부 큰 폭으로 바뀌었다(아래 표가 수정 후 결과, 유일하게 정확한 표).
  1차 표는 폐기 처리했다.

## 1. 데이터 규모
- SHOOT 591,756 / CRASH 521,564 / CONTROL 표본 556,660 (풀 66,781,118행에서
  reservoir 샘플링, seed=42, 목표 크기 = (SHOOT+CRASH)/2)
- 원본: 6,700만 틱 전체(8/04~8/28, 117종목, 8/03·196170 8/03·8/04 제외 — 기존
  틱 홀드아웃 제외 규칙 그대로 적용)
- CONTROL은 "직전 60초(포함) 이내 SHOOT/CRASH가 없었던 NEUTRAL 틱"만 사용(오염
  제거) — SHOOT/CRASH 직후의 미세구조 잔향이 NEUTRAL에 섞여 들어가는 것을 방지

## 2. 결과표 (수정 후, 유효 — OFI/buy_ratio 6행은 §4 갱신 참고, "결론불가")

| pair | feature | median_a | median_b | median_diff | p_value | bonferroni 유의 | 신뢰도 |
|---|---|---|---|---|---|---|---|
| SHOOT_vs_CONTROL | buy_initiated_ratio | 0.8759 | 0.6406 | +0.2353 | ~0 | Y | **결론불가(§4)** |
| SHOOT_vs_CONTROL | order_flow_imbalance | 0.7394 | 0.3025 | +0.4370 | ~0 | Y | **결론불가(§4)** |
| SHOOT_vs_CONTROL | price_flatness | 0.0299 | 0.0041 | +0.0258 | ~0 | Y | 유효 |
| SHOOT_vs_CONTROL | trade_speed_per_sec | 30.32 | 2.62 | **+27.70** | ~0 | Y | 유효 |
| SHOOT_vs_CONTROL | avg_trade_size | 115.17 | 28.83 | **+86.34** | ~0 | Y | 유효 |
| SHOOT_vs_CONTROL | max_trade_size_ratio | 90.02 | 21.68 | **+68.34** | ~0 | Y | 유효 |
| SHOOT_vs_CONTROL | tick_interval_volatility | 0.1621 | 0.7047 | **-0.5427** | ~0 | Y | 유효 |
| SHOOT_vs_CONTROL | intraday_cum_return | 0.0320 | 0.0127 | +0.0193 | ~0 | Y | 유효 |
| CRASH_vs_CONTROL | buy_initiated_ratio | 0.8882 | 0.6406 | +0.2476 | ~0 | Y | **결론불가(§4)** |
| CRASH_vs_CONTROL | order_flow_imbalance | 0.7343 | 0.3025 | +0.4318 | ~0 | Y | **결론불가(§4)** |
| CRASH_vs_CONTROL | price_flatness | 0.0345 | 0.0041 | +0.0304 | ~0 | Y | 유효 |
| CRASH_vs_CONTROL | trade_speed_per_sec | 45.92 | 2.62 | **+43.30** | ~0 | Y | 유효 |
| CRASH_vs_CONTROL | avg_trade_size | 105.06 | 28.83 | **+76.23** | ~0 | Y | 유효 |
| CRASH_vs_CONTROL | max_trade_size_ratio | 117.59 | 21.68 | **+95.91** | ~0 | Y | 유효 |
| CRASH_vs_CONTROL | tick_interval_volatility | 0.1382 | 0.7047 | **-0.5665** | ~0 | Y | 유효 |
| CRASH_vs_CONTROL | intraday_cum_return | 0.0376 | 0.0127 | +0.0248 | ~0 | Y | 유효 |
| SHOOT_vs_CRASH | buy_initiated_ratio | 0.8759 | 0.8882 | -0.0123 | ~0 | Y | **결론불가(§4)** |
| SHOOT_vs_CRASH | order_flow_imbalance | 0.7394 | 0.7343 | +0.0051 | 8.1e-145 | Y | **결론불가(§4)** |
| SHOOT_vs_CRASH | price_flatness | 0.0299 | 0.0345 | -0.0046 | ~0 | Y | 유효 |
| SHOOT_vs_CRASH | trade_speed_per_sec | 30.32 | 45.92 | -15.60 | ~0 | Y | 유효 |
| SHOOT_vs_CRASH | avg_trade_size | 115.17 | 105.06 | +10.11 | ~0 | Y | 유효 |
| SHOOT_vs_CRASH | max_trade_size_ratio | 90.02 | 117.59 | -27.57 | ~0 | Y | 유효 |
| SHOOT_vs_CRASH | tick_interval_volatility | 0.1621 | 0.1382 | +0.0239 | ~0 | Y | 유효 |
| SHOOT_vs_CRASH | intraday_cum_return | 0.0320 | 0.0376 | -0.0056 | ~0 | Y | 유효 |

전체 24개 검정 Bonferroni 보정(α=0.05/24=0.002083) 후에도 전부 "유의"로 나온다.
**다만 n=50만~60만대에서는 사실상 어떤 미세한 차이도 p≈0으로 나오므로, p값 자체는
정보량이 거의 없다 — median_diff(효과크기)를 봐야 한다.**

## 3. median_diff로 본 그림 (효과크기 기준, 판단 아님)
- SHOOT/CRASH는 CONTROL(오염제거 NEUTRAL)과 **6개 피처**(price_flatness,
  trade_speed_per_sec, avg_trade_size, max_trade_size_ratio,
  tick_interval_volatility, intraday_cum_return)에서 크게 갈린다 —
  체결속도(+27.7~43.3), 평균체결크기(+76~86), 최대체결비율(+68~96),
  틱간격변동성(-0.54~0.57) 전부 방향 일관되고 절대크기도 크다. 이 부분은
  조인버그 수정 전보다 **차이가 오히려 더 커졌다**(버그가 진짜 차이를
  과소평가하는 방향이었음이 확인됨).
- SHOOT와 CRASH는 이 6개 활동성 지표에서는 서로도 꽤 다르다(CRASH가 전반적으로
  체결속도·최대체결비율이 더 큼) — "얼마나 활발한 국면인가"는 SHOOT/CRASH를
  어느 정도 구분한다.
- **buy_initiated_ratio·order_flow_imbalance는 6개 조합(2피처×3쌍) 전부
  §4의 측정오차 안에 있어 "결론 불가"로 분류한다** — SHOOT/CRASH가 CONTROL과
  다른지, SHOOT와 CRASH가 서로 다른지 이 두 피처만으로는 이 데이터로 말할 수
  없다(아래 §4).

## 4. OFI/buy_ratio 전부 "결론불가"로 재정정 — strategy-agent 지적 2건 확인함

8/30 18:46 편지에서 "OFI는 절대값이 작아 걱정 없다"고 드린 안내가 틀렸다는
1차 정정에 이어, strategy-agent가 지적한 2건을 직접 검증했다:

**지적 1 — CRASH_vs_CONTROL의 OFI도 노이즈와 사실상 같은 크기다**: 맞다.
CRASH_vs_CONTROL OFI median_diff = **0.4318**, 버스트일 CRASH 노이즈 실측 =
**0.438** — 사실상 동일. "노이즈 대역 근처"가 아니라 구분 불가 수준이다.

**지적 2 — buy_initiated_ratio는 절대오차를 따로 측정한 적이 없었다**: 맞다,
이전엔 "OFI와 같은 분자·분모 구조라 비슷할 것"이라는 추론이었다. 같은
스팟체크 표본(010170/8-13 버스트일, 388050/8-04 평온일)에서 직접 재측정했다:

| 표본 | 비교군 | buy_initiated_ratio 절대오차 | order_flow_imbalance 절대오차 |
|---|---|---|---|
| 버스트일 | CRASH | 0.298 | 0.438 |
| 버스트일 | NEUTRAL | 0.086 | 0.150 |
| 평온일 | NEUTRAL | 0.167 | 0.473 |

효과크기 대비:
- SHOOT_vs_CRASH: buy_ratio 0.0123, ofi 0.0051 — 둘 다 모든 노이즈(0.086~0.473)
  보다 압도적으로 작다. **결론불가.**
- CRASH_vs_CONTROL: buy_ratio 0.2476 vs CRASH노이즈 0.298(노이즈가 더 큼),
  ofi 0.4318 vs CRASH노이즈 0.438(사실상 동일). **결론불가.**
- SHOOT_vs_CONTROL: buy_ratio 0.2353 vs NEUTRAL노이즈 0.086~0.167(효과가
  1.4~2.7배 큼), ofi 0.4370 vs NEUTRAL노이즈 0.150~0.473(효과가 노이즈
  상단과 거의 같음). NEUTRAL 쪽 노이즈만 보면 buy_ratio는 그나마 나아
  보이지만, **SHOOT 쪽 노이즈 자체가 측정된 적이 없다**(§5 각주1) — SHOOT
  틱이 CRASH틱보다 컨벤션차이에 더 취약한지 덜 취약한지 알 수 없으므로,
  요청대로 이 조합도 보수적으로 결론불가에 포함한다.

즉 요청대로 §2 표에서 buy_initiated_ratio·order_flow_imbalance는 3쌍
전부(SHOOT_vs_CONTROL, CRASH_vs_CONTROL, SHOOT_vs_CRASH) "결론불가"로
통일했다. 나머지 6개 피처는 효과크기가 노이즈 대역보다 자릿수 단위로 커서
그대로 핵심 결과로 유지한다.

## 5. 각주 (strategy-agent 요청, 미해결로 명시)
1. **SHOOT 쪽 컨벤션-오차 스팟체크는 아직 안 됨** — 3단계 때 쓴 버스트일/평온일
   두 표본 모두 SHOOT=0건이었다(CRASH만 332건, NEUTRAL만 존재). §4의 모든
   노이즈 실측치는 CRASH·NEUTRAL에서만 나온 것이고, SHOOT 쪽에서 같은
   크기인지는 확인되지 않았다. SHOOT 포인트가 있는 버스트일 표본을 새로
   골라 스팟체크하기 전까지는 SHOOT 관련 비교에 이 미검증 가정이 남는다.
2. **절대값 vs 상대값 구분** — 이전 정정 대상은 "절대값이 작아서 무시해도
   된다"는 상대적 프레이밍이었다. 실제로는 절대오차 자체를 비교 대상
   효과크기와 나란히 놓고 판단해야 하며, §4에서 buy_ratio·ofi 둘 다 그렇게
   했다.

## 6. 남는 파일
- `results/point_labeling_stage4_comparison.csv` (§2 표, 수정 후 최종본으로
  덮어씀 — 1차 버그 결과는 저장하지 않았음)
- `results/point_labeling_features_labels.parquet` (3단계 산출물, 8피처+라벨,
  70,912,254행)
- 1차(버그) 결과는 파일로 남기지 않고 폐기함 — 필요시 재현 스크립트는
  `contam`을 `(code,date_str,ts)`로 조인하는 버전(재현용, 쓰지 말 것)

## 7. 결론 (판단 아님, 서술만)
- SHOOT/CRASH는 오염제거 NEUTRAL 대비 **8개 중 6개** 미세구조 피처(활동성·
  변동성·누적수익률 계열)에서 뚜렷이 다르다 — 이 부분은 조인버그 수정 후
  오히려 신뢰도가 올라갔다. strategy-agent 판단대로 6개만으로도 SHOOT/CRASH가
  NEUTRAL과 구분된다는 관찰은 유지된다.
- **buy_initiated_ratio·order_flow_imbalance는 SHOOT_vs_CONTROL,
  CRASH_vs_CONTROL, SHOOT_vs_CRASH 3쌍 전부 "결론 불가"**로 통일했다(§4) —
  측정된 효과크기가 SQL/pandas 동시각-틱 컨벤션 차이로 인한 노이즈(0.09~0.47)
  와 같거나 작다. "매수주도비율로 구분 안 된다"는 것도, "된다"는 것도 이
  데이터로는 말할 수 없다.
- 모델 학습은 이번 라운드에 포함하지 않았다. 다음 단계(모델링 여부·SHOOT쪽
  스팟체크 여부)는 strategy-agent 판단을 기다린다.
