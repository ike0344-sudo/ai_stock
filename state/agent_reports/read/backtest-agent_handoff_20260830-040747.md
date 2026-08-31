# backtest-agent 인수인계 — 2026-08-30 04:07

새 세션은 이 파일만 읽고 바로 이어가면 된다. 전략1(분봉 신고가추세) 검증이 메인,
일봉 3전략(new_high_swing/pullback_reentry/vcp_breakout)은 별도 트랙.

## 절대 원칙
- **홀드아웃 미개봉**: 전략1 `2026-06-05~2026-08-28`, 일봉전략도 각자 마지막 20%. 세션 내내 한 번도 안 열었다.
- 판단 로직 바꾸는 최적화 금지, 전후 결과숫자 동일 확인 필수(오늘 이 원칙 어긴 사례를 직접 잡아 되돌린 적 있음 — 아래 버그3 참고).
- 비용: `breakout_reversal.DEFAULT_COMMISSION_RATE(0.015%)+SLIPPAGE_RATE(0.1%)+TAX_RATE(0.23%)`=왕복0.46%p, **scan 단계에서 이미 pct에 반영됨**(추가 반영 불필요, 언급만 할 것).
- 보고는 `state/agent_reports/<agent>_<timestamp>.md` 파일로(SendMessage 안 됨, 확인됨). lead가 읽으면 `read/`로 옮기니 폴더에 남은 파일=안읽힘.

## 확정된 결론 (근거 숫자 포함)
1. **레짐필터(조건7) 유지**. A/B: 손익비 1.02(on)→0.92(off), 막힌546건 자체 PF0.66. ML게이트가 레짐 대체한다는 가설 반증(레짐만 막고 ML은 통과시킨 32건 자체가 PF0.72 손실집합, t검정 p=0.22~0.33 무의미).
2. **25위+상승률1등 조건 기각**. top35 안 끈 버그로 204건→3+/1- 오판할 뻔했다가, top35 제대로 끄고 ML을 조건1~7전체로 학습(사후필터 방식)해 재실행 → 566건, **4폴드 전부 마이너스**(평균R-0.177, PF0.774, p=0.084).
3. **ML threshold=0.3 채택**(0.5는 표본 붕괴).
4. **전략1 기준선**(조건1~7+top35+threshold0.3) 월별: 11개월(2025-07-04~2026-06-04) 총수익+1.70%, 연환산+1.85%(참고용), MDD-16.05%(2026-01), n=877, PF1.008.
5. **결측데이터 무영향 확정**. data-agent 실측: 진짜 수집실패 197건/181종목(교집합), 그중 17건 실제 수정됨(`_dq_fix19.log`). 캐시 12개 파일 전부(아래 목록) 대조 결과 이 17종목-일이 **0건** 걸림 → 캐시 전부 유효, 재스캔 불필요.
6. **leave-one-out(가장 최근, 최고 발견)**: 기준선(8조건) n877 PF1.008 MDD27.3%.
   - top35 제외: ML후 PF0.724(Δ-0.284) MDD265%(파탄), 4폴드 전부(-)
   - no_drawdown 제외: PF0.852(Δ-0.156) MDD71.4%, 4폴드 전부(-) ← **엣지 뚜렷**
   - day_floor/day_ceiling/regime/base 제외: Δ-0.07~-0.10, 폴드 2:2 ← 약한 기여
   - **new_high 제외: PF1.022(Δ+0.014, 개선) MDD20.2%(-7.1%p 개선)** ← 유일하게 빼면 나아짐
   - 상관(phi, base_ok통과 52934건): **new_high-no_drawdown=0.437**(최강, 겹침 확인) / day_floor-day_ceiling=-0.073(가설과 반대로 안 겹침)
   - **다음 작업(바로 아래)이 이걸 검증하는 것**

## 버그 3건 (전부 "구간경계 독립 재시뮬레이션→이중집계/유실", 회귀테스트 있음)
1. `backtesting/daily_walk_forward.py` — 폴드별 독립 simulator.run. 종목당 1회 연속시뮬+entry_date 사후배정으로 수정. 테스트: `tests/backtesting/test_daily_walk_forward.py`.
2. `backtesting/grid_search.py`(`_one_combo`) — IS/OOS 독립 시뮬. 전체캔들 1회+사후분할로 수정. 테스트: `tests/backtesting/test_grid_search.py::test_run_rule_based_position_spanning_is_oos_boundary_is_not_double_entered`.
3. `backtesting/gate_ab_check.py`(`gate_ab_per_fold`) — trades_df 자체 min(entry_time)으로 폴드시작 잡아 A/B 폴드경계 어긋남. `start`/`end` 외부고정 인자 추가. 테스트: `tests/backtesting/test_gate_ab_check.py`.
- 참고(속도 최적화 중 판단): `universe.intraday_top_n_return_rank1_by_minute` 벡터화 시도에서 18건 불일치 발견 → 전부 "진짜 동점"으로 확인(버그 아님) → tie-break를 `rank(method="first")`로 명시적 채택. 테스트: `tests/backtesting/test_universe.py`.

## final_strategy.py 확장
`detect_final_entries(..., disabled_conditions: frozenset[str] = frozenset(), top25_return_rank1_by_minute=None)`.
`disabled_conditions`에 넣을 수 있는 이름: `"base"`(3분거래대금+수익률), `"day_floor"`, `"day_ceiling"`, `"new_high"`, `"no_drawdown"`, `"regime"`, `"top35"`. 전부 개별 토글 가능(오늘 확장).

## 폴드/데이터 구성
- 로컬 분봉 커버: 2025-07-04~2026-08-28. 홀드아웃 `2026-06-05~2026-08-28`.
- 워크포워드: train=150일/test=45일/step=45일 → 4폴드(fold_end=2026-06-04):
  fold1 `2025-12-01~2026-01-14` / fold2 `2026-01-15~2026-02-28` / fold3 `2026-03-01~2026-04-14` / fold4 `2026-04-15~2026-05-29`
- IS샘플부족 해법: ML은 조건1~7 전체(top35끔) 풀로 학습, 관심 서브셋은 사후필터. `gate_ab_check._train_and_predict_per_fold(pool_df, splits)` 재사용 → oos_df를 서브셋 key(`code`,`entry_time`)로 필터 후 threshold 적용.
- RandomForest: n_estimators=300,max_depth=6,min_samples_leaf=20,n_jobs=-1,random_state=42, MIN_TRAINING_SAMPLES=50.

## 캐시 파일 (results/, 결측수정 반영 확인됨, 전부 유효)
- `regime_on_trades.csv` — 조건1~7+top35, 2246건 (**기준선**)
- `regime_notop35_trades.csv` — 조건1~7(top35끔), 10306건
- `top25_on_trades_notop35.csv` — 25위+1등(top35끔, 최종판), 566건
- `top25_on_trades.csv` — 25위+1등(top35켬, 버그판) **폐기, 쓰지 말 것**
- `loo_{base,day_floor,day_ceiling,new_high,no_drawdown,regime,top35}_trades.csv` — 조건별 leave-one-out 스캔
- `_dq_real_gaps_intersection.csv`(197건 실결측), `_dq_fix19.log`(17건 실수정 목록)

## 스크립트
`backtesting/daily_walk_forward.py`(+`_benchmark.py`, `new_high_swing_side_effects.py`) — 일봉3전략.
`backtesting/gate_ab_check.py` — ML on/off 폴드A/B(start/end 고정 지원).
`backtesting/regime_filter_ab.py` — 레짐 A/B(diff_analysis/overlap_analysis/cost_sensitivity).
`backtesting/top25_rank1_ab.py` — 25위+1등 A/B.
임시분석(`/tmp/*.py`)은 세션종료시 사라짐 — 위 정식 스크립트 + `gate_ab_check._train_and_predict_per_fold` 재사용 패턴으로 그때그때 재작성했음, 같은 패턴 반복하면 됨.

## 다음 작업 (지시받음, 즉시 시작)
new_high 조건 제외 구성 검증 — leave-one-out은 "하나만 뺀 효과"였고 이제 새 기준선 후보로 제대로 재기:
1. new_high 뺀 7조건으로 전체 워크포워드(4폴드) 재실행, 폴드별 부호 + PF≥1 폴드 수 확인.
2. 월별수익률(11개월) 산출, 기존 기준선(+1.70%)과 나란히.
3. **new_high + no_drawdown 둘 다 제외**한 구성도 재기 — 무너지면 no_drawdown이 진짜 엣지원 확정, 안 무너지면 둘 다 불필요.
4. 비용은 이미 반영돼 있음을 명시(왕복0.46%p) — PF가 그 이상 나오는지가 관건.
5. 홀드아웃 여전히 미개봉.
결과는 `state/agent_reports/`에 파일로.

## 미해결(지시 없으면 건드리지 말 것)
base_ok(40억/1.5%/3분창) 값 민감도, kospi-theme-engine 스크립트 감사, pullback_reentry 재가설(strategy-agent 대기), `ml_entry_filter.build_training_examples` 죽은코드 삭제 여부, ceiling/base_ok 완화시 증가건수(118/253건은 top35켠 상태 기준이라 낡음, 미갱신).
