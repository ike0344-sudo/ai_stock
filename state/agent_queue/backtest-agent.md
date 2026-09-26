# backtest-agent 큐

- [x] new_high 제거(7조건) 전체 워크포워드 — 폴드별 부호 일관성, 월별 수익률, 비용 반영
      (큐 생기기 전에 이미 완료 — state/agent_reports/backtest-agent_20260830-081152.md)
- [x] new_high + no_drawdown 둘 다 뺀 경우도 측정 (상관 0.437 의 정체 판정)
      (위 보고서 3항 — 둘 다 빼면 4폴드 전부 PF<1로 붕괴, no_drawdown이 진짜 원천)
- [x] DuckDB 통합 — universe.py rank1, 기존 pandas 구현과 결과 동일성 테스트 유지
      (큐 생기기 전에 이미 완료 — state/agent_reports/backtest-agent_20260830-083548.md)
- [x] scan_all_trades(233초)가 SQL 로 갈 수 있는지 판단하고 가능하면 이관
      (완료 — lead 지시로 순서(pandas 기준선 확정→SQL 실연결→재실행 대조) 지정받아
      진행. detect_final_entries에 precomputed_* 옵션 인자 추가, scan_all_trades에
      use_duckdb_conditions 스위치 추가(기본 False, 하위호환). new_high 제외 스캔을
      새 경로로 재실행해 기존 pandas 캐시와 13개 컬럼 전부 대조 → 불일치 0, 폴드
      테이블도 소수점까지 일치 확인. state/agent_reports/backtest-agent_20260830-105616.md.
      부수 발견: 배치 3개가 각자 CSV 전체스캔이라 실제 속도이득 미미(223s vs 233s) —
      정확성 문제없음, 속도는 추가작업 필요(안 건드림))
- [x] kospi-theme-engine 루트 탐색 스크립트 감사 (미래참조/IS-OOS겹침/폴드경계/OOS선택)
      (완료 — state/agent_reports/backtest-agent_20260830-092448.md. walkforward_*.py
      3개+evolve.py+공용 시뮬레이터 감사, 구조적으로 건전(경미한 것 1건 제외).
      나머지 스크립트는 스코프 밖으로 명시)

- [x] 소피증권(kospi-theme-engine) 성능 측정 — 완료. 14개 스크립트 전부 `time` 실측.
      최느림 chgtop_hold.py(296.86s) 포함 5개(chgtop_hold/rising_threshold/
      flow_distribution/rising_test/entry20)가 엔진 미사용 단순집계라 DuckDB 후보.
      **rank_timeline.py는 이름과 달리 후보 아님** — 실제로 열어보니 라이브
      Aggregator/score_themes(상태유지 엔진)를 분단위로 재생하고 있었다(chgtop_swap/
      clean20_theme_edge도 마찬가지). state/agent_reports/backtest-agent_20260830-120305.md
- [x] 소피증권 실시간 엔진 SQL대상 아님 판단 확인 — 완료, **lead 판단 맞음**. 실제
      운영 폴러(app.main.start_index_poller)와 같은 순서로 라이브 API 2회 독립측정:
      API대기 5.54s vs 로컬계산 0.0001s → API 대기 비중 100.0%(2회 재현). 건드리지
      않음. 위 보고서에 같이 포함.
- [x] (큐 밖, 사용자 직접 지시) 홀드아웃 순수 틱 백테스트(8/04~8/28, 117종목) —
      완료. 진입 SQL/청산 파이썬 분리, 142건 산출, 분봉 3갈래 비교, 틱 데이터가
      KRX전용(NXT누락)이라는 발견을 해석에 반영. 성과판정 안 함(메커니즘 검증만).
      state/agent_reports/backtest-agent_20260830-170655.md
- [x] (큐 밖, lead 직접 지시) 전략1 폐기 확정, 관련 A/B(상한15%, 25위+1등 재측정)
      중단. 리스크제약(5슬롯+동일종목병합) 틱 인프라는 새 전략에도 필요해 완료·
      검증 — state/agent_reports/backtest-agent_20260830-180415.md
- [x] (큐 밖, strategy-agent 요청) 새 전략(지점 라벨링) 실측 1~4단계 — 1단계(N/M
      분포)→2단계(라벨: SHOOT 591,756/CRASH 521,564)→3단계(피처8개 SQL이식,
      6700만틱)→4단계(대조군+Mann-Whitney U) 전부 완료. 4단계 1차 결과에서 조인
      버그(대조군 21억행 뻥튀기) 직접 발견·수정 후 재실행, OFI 절대오차 관련
      이전 안내("걱정없다") 정정 포함해 최종 보고 —
      state/agent_reports/backtest-agent_20260830-193200_stage4-final.md
      (5단계=모델학습은 이번 라운드 범위 밖, strategy-agent 다음 지시 대기)
- [x] (큐 밖, strategy-agent 요청) 가설C(OFI 다이버전스) 측정 3건 — 완료.
      W=60초 신호정의 SQL/pandas 발산 캐비엇(원틱일치84%, 후보수-37%) 달고
      측정1(보합틱74.1%)·2①(선행상승 없음)·2②(돌파율41.2%)·3(진입청산,
      99.84% 시간손절·median pct=편도고정비용과 일치) 완료. 핵심관찰(청산-돌파
      구간 타이밍 불일치) 포함 보고 —
      state/agent_reports/backtest-agent_20260830-203500_ofi-hypothesis-measurement.md
- [x] (큐 밖, strategy-agent 요청) point_labeling_threshold_rule.py 실측 검증
      2건 — 완료. label==0 그대로 쓰라는 지시 검증없이 안 받고 오염제거
      풀 재구성(rid조인, 66,781,118행 일치 확인) 후 문턱값 도출, 6개 AND
      규칙이 CONTROL·SHOOT·CRASH 전부 0건 발동 확인(버그 아님, SHOOT 내
      최대 동시만족 5/6 직접검산) —
      state/agent_reports/backtest-agent_20260830-220000_threshold-rule-verification.md
- [x] (큐 밖, 사용자 직접지시) 지점라벨링 2단계 방향판정 시험 — 완료(위 참고),
      "약함/불확실"로 종결, strategy-agent 동의
- [x] (큐 밖, 사용자 직접지시, 2026-08-30) 체결만으로 방향판정 실패 확정 → 호가
      기반 재도전 계획 — 완료. strategy-agent가 먼저 docs/ORDERBOOK_DIRECTION_
      PREREGISTRATION.md 제출해서 처음부터 새로 안 만들고 독립 교차검증으로
      전환: SD·SE표·최소일수(45~50/60~65거래일) 재계산해 일치 확인, 문서간
      recall/precision 불일치(구버전 50%/60% vs 통일된 40%/55%) 발견해 정정
      요청, 재사용 인프라 확정+추가제안 2건 —
      state/agent_reports/backtest-agent_20260830-223800_orderbook-prereg-crosscheck.md
- [x] (큐 밖, 사용자 직접지시, 2026-08-30) 25위+등락률1등 부분집합 방향판정
      재시험 — 완료. 사전등록 먼저 작성(초안), strategy-agent가 더 상세한
      독립 사전등록(docs/TOP25_RANK1_DIRECTION_PREREGISTRATION.md) 제출해
      그쪽 기준으로 통일해 실행. 1차 pandas merge 팬아웃버그(22.9배 중복,
      (code,date_str,ts) 비고유키) 발견·폐기, SQL단일패스로 재작성. 게이트
      통과(30개 종목·날짜, 일화적 아님)했으나 정확도는 전체표본보다 오히려
      나쁨(로지스틱45.62%<자체기준선58.94%, 트리50.92%, 둘다 통과선63.94%
      미달) —
      state/agent_reports/backtest-agent_20260830-223200_rank1subset-result.md
- [x] (큐 밖, strategy-agent 요청) threshold_rule.py K=5 완화 재측정 — 완료.
      CONTROL 0.0045%/SHOOT 3.37%(749배)/CRASH 4.84%(1076배) — 정지규칙
      안 걸림, K=5는 살아있음(방향은 여전히 모름) —
      state/agent_reports/backtest-agent_20260830-230200_threshold-rule-k5-result.md
- [x] (큐 밖, strategy-agent 승인) 호가 DuckDB 파싱 스켈레톤 — 가정 스키마
      (code/date_str/ts/rank/bid1~10_price/qty/ask1~10_price/qty)로 미리
      작성, 실제 FID/스키마 확정되면 컬럼명만 교체. 8월 데이터 무관
      (완료 — backtesting/orderbook_parser.py. RAW_FIELD_MAP에 원본 JSON 키를
      전부 넣어 확인된 것만 채움: code=stock_code, ts=received_at,
      bid1_price=buy_fpr_bid, ask1_price=sel_fpr_bid(전부 trading_loop.
      _parse_quote_price로 실측 확인된 것 재사용, ABS 처리도 동일 이유로
      적용). 2~10단·rank는 미확인이라 None → SELECT에서 NULL로 채워 스키마
      모양은 고정, 나중에 FID 확인되면 맵 값만 채우면 됨. DuckDB
      read_json_objects로 원본 JSONL을 파싱(실캡처 데이터 없음 — 순수
      스켈레톤). 테스트 1건(tests/backtesting/test_orderbook_parser.py)
      통과 확인 — 확정필드 매핑값·ABS부호처리·미확인필드 NULL 전부 검증)
- [x] (큐 밖, 사용자 직접지시, 2026-08-30) 체결 백테스트 파이프라인 속도측정
      +최적화 — 완료. 사용자 가설 4개 실측했으나 병목 아님(원틱스캔 이미
      2.1초, 피처재계산 이미 캐시중), 실제 병목은 CONTROL풀 재구성의
      불필요한 rid ORDER BY 전체정렬 — 제거로 984.7초→46.0초(21.4배),
      결과(66,781,118행) 완전동일 검증. 파이썬 청산루프(42.4%)는 다음
      후보로 기록만 —
      state/agent_reports/backtest-agent_20260830-233000_pipeline-speed-profiling.md
- [x] (큐 밖, 사용자 직접지시, 2026-08-31) 25위+등락률1등 상한(ceiling)측정
      — 완료. 1차 진입후보 SQL 중복제거 누락 버그로 3.5시간 정체(한
      종목/일 33,989건까지 부풀어 청산루프 사실상 O(n²)) → 상승엣지
      디듀프+청산경로 벡터화(재현검증)+진행표시+사전 소요시간추정 반영,
      62.5초로 해결. 결과: 52건, +9.56%/18일(방향100%맞춰도 손절32.7%>
      익절28.8%) —
      state/agent_reports/backtest-agent_20260831-051500_CEILING_top25rank1_result.md
      (사후분석: backtest-agent_20260831-050000_ceiling-stall-postmortem.md)
- [x] (큐 밖, 사용자 직접지시, 2026-08-31) 탈환(2등→1등) 실험 — 완료.
      사전등록(backtest-agent_20260831-001500) 그대로 실행, 위 상한측정
      최적화 파이프라인 재사용(72.6초). 233건 중 97.9% NEUTRAL,
      SHOOT:CRASH=3:2(가설과 방향일치, n=5라 무의미). 두 실험팔(상한n=3,
      실현가능n=1) 다 사전등록 최소표본 미달로 판정보류/불가 —
      state/agent_reports/backtest-agent_20260831-052500_TAKEOVER_result.md

## 체결데이터 상승전조 연구 (2026-08-31 사용자 지시 5단계, lead 가 6건으로 묶음)

아래 6건에 **공통 적용**되는 조건 — 항목마다 반복 안 하니 매번 읽어라:
- 데이터/정규장필터/1초격자는 `_precursor_fastpath.to_grid`(tie-break 수정본) 재사용. 117종목 18일 전부, 표본 줄이지 마라.
- 미래정보 금지. 확장평균·문턱 전부 그 시점까지만.
- 매수/매도 판정은 tick rule. `pred_pre_sig` 는 전일종가 대비 부호라 못 쓴다(실증됨).
- **호가잔량은 없다.** 데이터 컬럼은 time/cur_prc/trde_qty/pred_pre_sig 넷뿐이다. 호가가 필요한 항목은 하지 말고 "데이터 없음"으로 남겨라.
- IS(첫12일)/OOS(뒤6일) 분리, 문턱은 IS 에서만 고르고 OOS 엔 그대로 적용.
- **비용**: 왕복 수수료+거래세+슬리피지(1틱 이상) 명시 상수. 총수익·순수익 나란히.
- **겹침 보정**: T0 가 촘촘해 인접표본이 상관된다. 유의성은 일자 단위로 묶어 일별 평균의 분산으로 본다.
- 안 되는 것도 표에 남겨라. OOS 에서 무너지면 무너졌다고 써라. 비용 빼고 남는 게 없으면 없다고 써라.
- 리포트 1건당 `state/agent_reports/backtest-agent_<날짜시각>_<주제>.md`, STATUS.md 엔 경로만.

- [x] (1) 상승 직전 10~60초 — 완료. onset(클러스터 첫t)/제외(한복판+사후60초)/
      negative 3분할로 격리(shooting_precursor_onset.cluster_bounds 재사용,
      유닛테스트로 격리 자체를 검증). 결과: 체결속도(초당틱수, 10~60초 전부)가
      최강·최안정 전조(AUC 0.65~0.66, IS-OOS 차이 0.001~0.002), 체결금액증가율
      (1~10초)도 유효(0.58~0.61), **매수-매도 대금격차는 방향반전**(순매도 우세가
      반등 예고, T0회귀의 평균회귀 패턴과 일치), 체결강도변화율은 무쓸모(표에 남김).
      온셋사건 실현수익(사후확정)은 순수익+0.12~0.13%로 비용을 살짝 넘지만 "예측
      성과 아님"을 명시(실시간 판별은 큐(6) 몫). 부수발견: value_surge 0/0 아닌
      x/0 inf 버그 실측 발견·수정(회귀테스트 추가) —
      state/agent_reports/backtest-agent_20260831-205128_precursor_10_60s.md
- [x] (2) MFE/MAE — 완료. EV=MFE+MAE로 정의(해석판단 명시). price_speed(1/3/10분)가
      여기서도 최강(IC -0.044~-0.097, 십분위 IS-OOS 완전 단조·재현), buy_ratio는
      OOS서 또 무너짐(T0회귀와 동일 패턴 재확인), value_surge류는 여전히 무쓸모.
      기존조건(price_speed 세창 하위10%)의 EV가 IS·OOS 전부 양수+보유시간에 비례
      증가(비대칭 진짜) — 단 MFE기준 순수익만 3분부터 플러스(비현실적 상한),
      EV기준 순수익은 전 구간 마이너스, 새 조건 못 찾음(정직히 명시) —
      state/agent_reports/backtest-agent_20260831-210012_mfe_mae.md
- [x] (3) 선후관계 — 완료. 가격상승온셋(큐1과 동일정의)/대금폭발온셋(10초창,
      확장평균대비3배)을 초단위로 최근접매칭(±180초). **결과: 가격이 대금폭발보다
      먼저인 경우 59.6% vs 대금폭발이 먼저 39.0%(중앙값 -8초)** — 지시대로 명시:
      대금폭발 관측 기반 전조예측은 다수사례에서 이미 늦다. 미매칭 41.3%도 보고
      (대금폭발 없이 일어나는 상승도 흔함). 동시가속구간(|lag|≤10초, n=4442 IS/
      2383 OOS) 순수익은 전 구간·IS/OOS 전부 마이너스(-0.10~-0.18%, 승률
      67~91%는 부차지표로 취급). t값(12~53)이 명백히 과신수준임을 직접 발견해
      경고로 명시(일별 사건수 과다로 일자클러스터SE도 못 거른 사례) —
      state/agent_reports/backtest-agent_20260831-215233_precursor_lead_lag.md
- [x] (4) 매수세의 질 — 완료. "대량"=`shooting_precursor.large_trade_flag`(기존
      LARGE_TRADE_MULT=3.0 재사용, 인과적), "연속발생"=5초내 병합. 결과: 대량매수
      구간 자체는 예측력 거의 없음(1분뒤 총수익 IS+0.006%/OOS+0.004%, 순수익 전
      구간 -0.50%대 확정, 승률도 36~44%로 낮음). **핵심 대조표**: 오른/안오른
      구간의 체결패턴 차이는 IS·OOS 방향 완전 일치(교차검증)하나 직접계산한
      효과크기(Cohen's d 0.06~0.16)가 전부 미미~작음 등급 — n이 커서 "유의"해
      보여도 실전 선별력은 약하다고 정직히 명시. buy_share는 오히려 오른쪽이
      낮음(매도 흡수하며 오른 쪽이 근소하게 나음, 큐(5)와 연결) —
      state/agent_reports/backtest-agent_20260831-215851_large_buy_bursts.md
- [x] (5) 체결↔가격 괴리 — 완료. 새 틱스캔 없이 t0_forward_return이 저장해둔
      price_speed/value_surge 재사용, divergence=price_speed/value_surge만 계산
      (2초만에 끝남). 결과: 매물벽 소화 가설 방향과 일치 — "느린"(체결급증+가격
      안움직임) 그룹이 "빠른"(이미반응) 그룹보다 IS·OOS 전 구간 부호 일관되게
      높음(1분 t=6.41/-3.61 IS, 4.46/-4.14 OOS로 특히 강함). divergence는
      price_speed와 상관 0.18뿐이라 재탕 아님을 확인. 단 순수익은 16칸 전부
      마이너스(-0.48~-0.57%, 크기가 비용 10% 남짓) —
      state/agent_reports/backtest-agent_20260831-220203_execution_price_divergence.md
- [x] (6) 최종 모델 — 완료. 사전등록 먼저 작성(docs/PRECURSOR_FINAL_MODEL_
      PREREGISTRATION.md) 후 측정. lead 지시문의 "체결속도/price_speed AUC
      0.65~0.66"이 서로 다른 두 연구·두 지표를 섞은 표현임을 실행 전에 정정
      (AUC 0.65~0.66은 tick_speed(초 단위 창)만의 수치, price_speed는 분 단위
      창이라 w1=60초만 60초 예산에 들어옴 — w3/w10은 처음부터 후보에서 뺌).
      결과: RF모델(IS AUC 0.93/OOS 0.76)·해석규칙(1~3개 결합) **전부 OOS 순수익
      마이너스(-0.53~-0.64%)**, 모델 상위신호가 **무작위/상시진입 대조군보다도
      나쁨**(-0.534% vs -0.514%) — 기각조건(a)(c) 둘 다 걸림, "그런 조건 없음"으로
      결론. 부수발견: 온셋격리 재평가(같은 모델, 평가표본만 재필터)로 OOS AUC
      0.758→0.639, tick_speed 강함의 절반 가까이가 "이미 랠리 중"이라는 자명한
      정보였음을 직접 확인. (1)~(5)와 같은 결론("안 되는 게 정상") 재확인, 다만
      어느 지표가 왜 약해졌는지(price_speed는 60초 예산 제약, buy_sell_gap/
      divergence는 horizon이 길어져서)까지 짚음. 테스트 4건, 회귀 31 passed —
      state/agent_reports/backtest-agent_20260910-180133_precursor_final_model.md
- [x] 테마순위 3축 **재측정** — 완료. 41일 전량(IS27/OOS14) vs 잠정34일(IS21/OOS13)
      나란히 비교. 결론(전부 미채택)은 안 바뀜, 세부는 다름 — 그 자체를 발견으로
      명시: H1 기각폭 축소(-3.22%→-1.10%, 196170 극단치 제거 효과로 추정), H2는
      더 나빠짐(-1.67%→-2.62%), **H3는 표본부족(판단보류, n=19)에서 표본충족
      (n=25)돼 명확한 기각으로 판정 카테고리 자체가 바뀜** — 유일하게 실질
      진전(모른다→아니다). strategy-agent에 사전등록 갱신 필요사항 전달 —
      state/agent_reports/backtest-agent_20260831-235357_theme_rank_41d_remeasurement.md
- [x] **손익비 구조로 기대값 양수 만들기** — 완료. **기대값 양수 조합 없음**(60개
      그리드 전부 IS -0.430%~-0.507%). 진입조건 재사용(price_speed 세창 하위10%,
      새로 안 고름), 틱 초단위 경로로 손절/익절/시간손절 선착순 시뮬레이션. 동시타격은
      부호상 구조적으로 불가능함을 유닛테스트로 증명(실행결과도 0건 확인) — 이 체크에
      한해 봉내부경로 문제 없음. IS최선(손절1.2%/익절1.5%/시간손절10분, -0.430%)을
      OOS 그대로 적용해도 -0.440%, 손익비 0.339=0.339로 IS-OOS 거의 완전 재현(과최적화
      아님, 구조적으로 안정된 마이너스). 익절0.3%대는 왕복비용보다 작아 승률 0.0%
      구조적 원인 규명. 문턱 재탐색 없이 정직히 "없다"로 결론 — (사용자 직접지시 2026-09-01)
      큐(6) 최종모델을 이 형태로 대체함 —
      state/agent_reports/backtest-agent_20260901-134441_exit_path_grid_search.md
      목표: **승률은 낮아도 된다. 손절/익절 비대칭으로 거래당 기대값(순수익)을 양수로 만들 수 있는가.**

      **진입은 이미 확정된 것을 쓴다** — `price_speed` 3창(1/3/10분) 동시 하위10%.
      OOS 총수익 +0.067%, t=2.88 로 오늘 나온 것 중 가장 견고하다
      (`backtest-agent_20260831-182932_t0_forward_return.md` 5번). **새 진입조건을 만들지 마라.**

      **재료도 이미 있다** — `mfe_mae.md` 에서 이 조건의 MFE(상방여지)는 크고 MAE(하방여지)는
      작아 EV 가 IS·OOS 둘 다 양수(+0.03~0.17%)이고 보유가 길수록 커진다는 걸 이미 쟀다.
      그 리포트가 "손절/익절 룰을 가정하지 않는 진단이라 실제로 얼마나 잡아낼 수 있는지는
      큐(6) 몫"이라고 넘겼다. 그 답을 내는 것이 이 항목이다.

      ## 할 일
      1. 틱 경로로 **실제 청산을 시뮬레이션**해라 — MFE/MAE 는 사후 최대치라 그대로는 못 먹는다.
         진입 후 초 단위로 따라가며 손절선/익절선/시간손절 중 **먼저 닿는 것**으로 청산한다.
      2. 문턱은 **IS 에서만** 고른다. 그리드를 넓게 깔지 마라 — 손절·익절 각 4~5개, 시간손절 3개
         정도로 좁혀라. 넓게 깔면 그건 최적화가 아니라 과최적화다.
      3. 고른 조합 **하나**를 OOS 에 그대로 적용한다. OOS 에서 다시 고르지 마라.

      ## 반드시 같이 보고할 것
      - **거래당 기대값(순수익)** 이 핵심 지표다. 승률은 부차다 — 승률 낮고 기대값 양수면 성공이다.
      - 승률 / 평균이익 / 평균손실 / **손익비** / 최대연속손실.
      - **손절 히트율** — 손절이 자주 걸리면 비용만 내고 나온다. 이게 높으면 그 조합은 못 쓴다.
      - **거래 빈도**(일평균 건수). 승률이 낮을수록 거래당 비용 0.52% 부담이 커지니
        빈도가 높으면 총비용이 기대값을 먹는다. 일 단위 합산 순수익도 같이 내라.
      - 일자클러스터 SE 로 유의성. IS 12일/OOS 6일이라 t 값을 문자 그대로 믿지 마라.

      ## 정직성
      기대값이 양수인 조합이 **없으면 없다고 써라.** 문턱을 계속 바꿔가며 양수를 찾아내지 마라 —
      그건 발견이 아니라 조작이다. 시도한 조합은 전부 표에 남겨라(되는 것만 보여주지 마라).
      비용 0.52% 는 그대로다. 슬리피지를 낮춰 통과시키지 마라.
- [x] **대금 25위(실제 20위) 안 등락률 1등 — 슈팅 관성** (사용자 직접지시 2026-09-01) — 완료.
      데이터: `rank_timeline_full_*.json`(41일, data-agent AL 재생성 확인분)만 사용,
      직접 재실행 안 해 MINUTE_STORE는 안 켬(이미 만들어진 산출물 소비 — 소스 확인해
      all_codes() 전체유니버스 기반임을 검증). **명명 정정**: `rank_timeline.py` 직접
      확인 결과 chgtop은 `value_rank_top=20`(25 아님) 기준 — 리포트 전체 20위로 통일,
      기존 25위 실험과 비교 안 함. §1(1등 유지시간, AL 그대로·근사문제 없음) 신뢰
      가능: 중앙값 3분, 꼬리 최대 388~389분, IS/OOS 재현. §2(순방향수익률)·§3(교체
      쌍대비교)는 **판정보류** — KRX전용 분봉으로 근사한 게 실제 AL 원틱과 얼마나
      다른지 118종목 겹치는 144건 직접대조: 절대오차평균 1.1~1.3%p로 측정하려는
      신호크기(-0.5~-0.8%)와 같은 자릿수라 결론 못 믿음(근사 검증 안 하고 그냥 썼으면
      틀린 결론을 냈을 뻔). 항목4(AL vs KRX 순위차이)는 시장전체 랭킹엔진 재현이
      필요해 인프라부족으로 판정보류, 후속 필요사항(AL 1분봉 전종목 캐시) 명시만 하고
      직접요청은 안 함. 비용은 상수 아닌 `round_trip_cost_pct` 실측(0.50~0.51%) —
      state/agent_reports/backtest-agent_20260901-153000_chgtop_leader_persistence.md
      **[정정 2026-09-01 17:45, lead 지시로 §2·§3 AL 재측정 중 자체발견]** 위 판정보류
      원인은 "KRX/AL 차이"가 아니라 `MinuteCloseLookup`이 1분봉 `close`를 읽은 버그
      (행 타임스탬프=구간시작인데 close=구간끝, ~1분씩 밀림)였다. `open`으로 고치니
      오차 1.1~1.3%p→0.15~0.23%p(corr 0.95~0.997)로 해소. 고친 뒤 재측정: §2(단독
      진입)는 여전히 뚜렷한 신호 없음(중립), **§3(교체 쌍대비교)는 IS 전구간(t=3.4~7.2)·
      OOS 1분(t=3.06)에서 유의한 양의 신호(신규1등-빼앗김종목 +0.9~1.2%p)로 새로 나옴**
      — 재현 1회뿐이라 "검증됨" 아님, 후속확인 필요. 항목4는 여전히 인프라부족 판정보류.
      §1은 이번 건과 무관한 별개 파이프라인이라 안 바뀜(실사로 데이터오염 아님 확인,
      금호건설=진성 급등주) —
      state/agent_reports/backtest-agent_20260901-174500_chgtop_al_remeasure.md
      **[추가정정 2026-09-01 18:20, lead 지시로 §3 실전조건 검증]** 위 §3 신규신호를
      사전등록(비용후수익/빈도/OOS감쇠/실행지연1분/날짜편중, 5개 기각조건 먼저 확정)
      후 실행 → **최종 기각.** 결정타는 실행지연: 순간비교였을 땐 IS 1분 t=7.20이었는데
      **지연 1분만 넣어도 t=-0.58로 신호가 사라지고 부호까지 뒤집힘**(순간적 가격차였지
      예측력 아니었음). 비용후 단독진입도 이미 무의미(t=0.07~0.48), 빈도·날짜편중은
      문제없었음(원인이 지연 자체임을 재확인). 버그전파감사: `MinuteCloseLookup` 패턴은
      다른 사용처 없음(grep 확인), 영향 리포트 153000 1건뿐 —
      state/agent_reports/backtest-agent_20260901-180000_swap_signal_prereg.md
      **반드시 통합(AL) 기준.** 체결은 `data/stocks/tick_al/`, 소피증권 쪽은 `MINUTE_STORE=al`.
      리포트에 통합 기준임을 명시하고 어떻게 보장했는지 적어라.

      ## 기존 측정과 뭐가 다른가 (중복 금지)
      `backtest-agent_20260831-051500_CEILING_top25rank1_result.md` 는 **KRX 기준**으로
      "방향을 100% 맞히면 얼마 버나"(상한)를 쟀다 — 18일 +9.56%, 거래 52건, 8/18 하루가 38%.
      **그건 다시 재지 마라.** 이번은 다른 질문이다: **한번 튀면 계속 가는가(관성).**

      ## 볼 것
      1. **1등 자리 유지 시간** — 등락률 1등에 오른 종목이 그 자리를 몇 분 지키는가.
         분포(중앙값·사분위)와, 오래 지킨 날과 자주 바뀐 날의 차이.
      2. **튄 뒤에 더 가는가** — 1등에 오른 시점부터 이후 1/3/5/10분 수익률.
         꺼지는 쪽인지 이어지는 쪽인지.
      3. **1등이 바뀌는 순간이 신호인가** — 자리를 빼앗는 새 종목의 이후 수익률 vs
         빼앗긴 종목의 이후 수익률. (기존 TAKEOVER 실험은 표본 미달로 판정보류였다 —
         통합 기준·확장 데이터로 표본이 늘었는지부터 확인하고, 여전히 미달이면 보류로 끝내라.)
      4. **통합과 KRX 의 순위 차이 자체가 신호인가** — 통합 기준 25위 안인데 KRX 기준으로는
         밖인 종목(또는 그 반대). 이런 종목이 더 가는가. **이건 통합 전환으로 새로 생긴 질문이다.**

      ## 데이터
      소피증권 기록은 하루 종일치(09:01~15:30, 390분)가 이미 만들어져 있다
      (`kospi-theme-engine/results/rank_timeline_full_*.json`, 41일, AL 기준 재생성분).
      **아직 아무 분석에도 안 쓰였다.** 60분본만 쓰지 말고 이걸 써라 —
      개장 60분과 그 이후를 비교할 수 있는 유일한 재료다.

      ## 규율
      왕복비용은 통합 기준으로 다시 확인해 명시(기존 전략은 0.46%, 오늘 틱 연구는 0.52% 였다 —
      어느 쪽을 왜 쓰는지 밝혀라). IS/OOS 분리, 문턱은 IS 에서만.
      표본이 적으면 판정보류로 끝내라 — 18~41일은 성과 판정에 부족하다는 걸 이미 여러 번 확인했다.
      안 되는 것도 표에 남겨라.
- [x] **사자마자 오르는 구간** (사용자 직접지시 2026-09-01) — 완료. 즉시성(안
      빠지고 바로 오름) 자체는 22~28%로 드물지 않으나, 조건축(price_speed하위10%/
      tick_speed상위10%/divergence느린10%/시간대/is_chgtop_leader) 중 어느 것도
      즉시성을 베이스라인 대비 크게(최고 +3%p) 못 올리고, **모든 축·모든 호라이즌
      (30/60/180초)에서 순수익이 마이너스(-0.47~-0.53%, 비용 0.50~0.52%와 거의 같은
      크기)** — "즉시성은 있으나 돈은 안 된다"로 정직히 결론. 마감30분은 즉시성이
      뚜렷이 낮음(16.6→17.3% IS→OOS)을 발견. MAE분포로 손절폭 참고치는 냈으나 정의상
      부분순환임을 명시. 새 스캔은 ret_30s 하나뿐(mfe_mae/t0_forward_return/
      execution_price_divergence/chgtop_leader_persistence 산출물 전부 재사용) —
      state/agent_reports/backtest-agent_20260901-160500_immediacy_zone.md
      `data/stocks/tick_al/` 2026-08-04~08-28, 18거래일 x 118종목. 이게 가진 전부다
      (다른 달 없음). 일봉으로 넘어가지 마라 — 초 단위 즉시성이 이 항목의 핵심이라
      일봉으로는 아예 못 잰다.
      지금까지는 "평균적으로 오르나"만 봤다. 이건 다른 질문이다: **진입 직후 빠지지 않고
      바로 오르는 구간이 따로 있는가.** 평균 수익이 낮아도 즉시성이 높은 구간이 있을 수 있다.

      ## 정의 (숫자로 못박아라)
      진입 시점 t 에서:
      - **안 빠졌다** = [t, t+60초] 동안 최저가가 진입가 대비 **-0.1% 아래로 안 내려감**
      - **바로 올랐다** = t+30초 / t+60초 / t+180초 시점 수익률이 **양수**
      - **즉시성** = 위 둘을 동시에 만족한 비율

      `mfe_mae.py` 가 이미 진입 후 최대상승·최대하락을 재고 있다 — **그걸 재사용해라.**
      새로 다 짜지 마라. 최대하락(MAE)이 0 근처인 구간을 찾는 게 이 항목의 핵심이다.

      ## 무엇으로 가르는가 (이미 나온 지표만 쓴다, 새로 만들지 마라)
      - `price_speed`(1/3/10분) — 지금까지 가장 일관됐던 것
      - 체결속도(초당 틱수) — 10~60초 창에서 AUC 0.65~0.66 로 가장 안정적이었음
      - 체결금액 증가율, 체결↔가격 괴리(`execution_price_divergence` 의 "느린" 구간)
      - **시간대** — 개장 30분 / 중반 / 마감. `holding_horizon` 7번에서 개장이 유리해 보였으나
        사후관찰이라 미검증으로 남겼다. 여기서 사전등록해 같이 검증해라.
      - 대금 25위 안 등락률 1등 여부(앞 큐 항목 결과가 나왔으면 그것도 축으로)

      ## 반드시 같이 보고
      - 즉시성이 높은 구간의 **순수익(비용 후)**. 즉시성이 높아도 **왕복 0.52% 를 못 넘으면
        못 쓴다** — 그때는 "즉시성은 있으나 돈은 안 된다"고 정확히 그렇게 써라.
      - 그 구간의 **빈도**(일평균 몇 건). 드물면 자본이 논다.
      - 즉시성이 높은 구간의 손절폭을 얼마나 좁힐 수 있나 — MAE 분포로 답해라.
        (안 빠진다면 손절을 -0.3% 처럼 좁게 걸 수 있고, 그러면 틀렸을 때 손실이 작아진다)
      - IS/OOS 분리, 문턱은 IS 에서만. 안 되는 축도 표에 남겨라.

      ## 주의
      **"사자마자 오른다"가 곧 "돈이 된다"가 아니다.** 0.1% 올랐다 내려가면 비용도 못 건진다.
      즉시성과 수익성을 **따로** 보고하고, 둘이 같이 가는 구간이 있는지를 마지막에 답해라.
- [x] **미끄러짐(슬리피지) 실측** — 완료. 호가 없이 연속체결 점프(0아닌 것,
      2,880만건)로 보수적 프록시 측정. **실측 중앙값 0.109%·75%지점 0.160%가
      가정치(0.1%)보다 오히려 크다** — 가정이 낙관적이지 않았다는 뜻, "낙관적으로
      잡지 마라" 지시대로 그대로 보고. 종목·시간대 편차는 뚜렷: 대금상위 종목이
      대금하위보다 14~21% 저렴, 개장30분이 중반·마감보다 9~20% 비쌈(대금상위만
      골라도 비용 내려간다는 답). 체결크기 영향은 약한 상관(+11%, 근사·인과아님
      명시). 오늘 기각된 것(exit_path_grid_search 최선조합, immediacy_zone
      최고축) 실제 진입가 분포로 재계산 → **되살아나는 것 없음**(비용이 오히려
      +0.008~0.071%p 올라 더 나빠짐, 임의가격 하나로 처음 재다 틱플로어가 두
      실측치를 덮어버리는 실수 직접 발견·수정) —
      state/agent_reports/backtest-agent_20260901-190000_slippage_measurement.md
      **통합(AL) 8월 체결데이터** `data/stocks/tick_al/` 2026-08-04~08-28, 118종목.

      ## 왜 이게 지금 가장 값이 큰가
      왕복비용 구성: 거래세 0.23%(못 줄임) + 수수료 0.03%(이미 낮음) + **미끄러짐 왕복 0.20~0.26%**.
      미끄러짐만 줄일 수 있고, 그 값은 `max(0.1%, 1틱)` 이라는 **추정치**다 — 한 번도 실측한 적이 없다.
      실제가 이보다 작으면 오늘 기각된 것들 중 일부가 되살아난다.
      **신호를 하나 더 찾는 것보다 이미 찾은 신호들의 문턱을 낮추는 쪽이 값이 크다.**

      ## 무엇을 재나
      체결 데이터로 잴 수 있는 것만 정직하게 잰다(호가 데이터는 없다 — 없는 걸 추정하지 마라).
      1. **호가 단위 대비 실제 체결 간격** — 연속 체결의 가격 점프 분포. 1틱이 실제로 얼마인가를
         KRX 호가단위표(`krx_tick_size`, `breakout_reversal.py` 에 이미 있다)와 대조.
      2. **종목별·시간대별 차이** — 대형주와 소형주, 개장/중반/마감. 어디가 싸고 어디가 비싼가.
         **거래대금 상위 종목만 골라도 비용이 내려가는가**가 이 항목의 핵심 실무 질문이다.
      3. **주문 크기 영향** — 한 번에 얼마를 사면 몇 틱을 먹고 들어가는가.
         체결량 분포로 근사하되 **근사라는 걸 명시**해라(호가 잔량이 없으니 정확히는 못 낸다).

      ## 반드시
      - **낙관적으로 잡지 마라.** 유리한 쪽으로 가정하면 오늘 기각한 것들이 거짓으로 되살아난다.
        모르면 보수적으로 잡고 "모른다"고 써라.
      - 결과를 **현재 가정(0.1% 또는 1틱)과 나란히** 비교표로. 실제가 더 크면 더 크다고 써라 —
        그러면 오늘 결과들이 오히려 낙관적이었다는 뜻이고, 그것도 중요한 발견이다.
      - 실측치로 왕복비용을 다시 계산해 **오늘 기각된 것 중 되살아나는 게 있는지** 마지막에 답해라.
        되살아나는 게 없으면 없다고 써라.
      - 호가 데이터가 있어야만 답할 수 있는 부분은 **그렇다고 명시**하고 추정하지 마라.

- [x] (사용자 직접지시, 2026-09-02) 52주 신고가 + 골든크로스 진입, -8%/+24% 청산, 시총 3조 이상, 최근 1년
      완료. 사전등록 먼저 작성(docs/NEWHIGH52W_GOLDEN_CROSS_PREREGISTRATION.md,
      지시에 없던 구현 디테일은 [구현결정]으로 분리 명시) 후 측정. 5/20·20/60
      둘 다 실행 — 거래당 평균은 플러스(net +1.77%/+5.56%, 손익비3:1 구조 확인)
      지만 **같은 종목군 단순보유(+98.7%/+58.4%)에 압도적으로 못 미침**
      (-96.9%p/-52.8%p). +24% 상한이 강세장 상승을 일찍 잘라버리는 구조적
      원인. 종목·날짜 편중 없음(월별 고르게 분산), 시총필터 사후참조 민감도
      확인(1건 차이뿐, 결론 무관), 만료(기간끝 강제청산) 0건. **단일 창
      시뮬레이션이라 이 결론이 다른 체제(하락장 등)에서도 성립하는지는
      모름 — 검증됐다고 안 함.** 테스트 6건 통과 —
      state/agent_reports/backtest-agent_20260902-165849_newhigh52w_golden_cross.md
      **먼저 사전등록을 쓰고(docs/), 그다음 측정한다. 결과 보고 규칙을 바꾸지 마라.**

      ## 규칙 (내가 확정했다 — 재량으로 바꾸지 말고, 틀렸다고 보이면 보고해라)
      - 유니버스: `data/cache/daily_all.parquet` (2019-04-23~2026-08-31, 2413종목)
      - 시총: `kospi-theme-engine/data/reference/universe.csv` 의 `shares` x 진입일 종가 >= 3조.
        **주식수는 현재 스냅샷 한 장뿐이라 과거 증자/감자가 반영 안 된다 — 근사임을 보고서에 명시해라.**
        shares 없는 종목(약 1400개)은 제외되고, 그게 결과를 어느 쪽으로 기울이는지도 한 줄 써라.
      - 52주 신고가: 당일 종가가 **직전 252거래일 고가(당일 제외)** 를 초과. 당일 값 섞지 마라.
      - 골든크로스: **5/20 과 20/60 두 정의를 다 재고 둘 다 표에 남겨라.** 하나만 고르지 마라.
        신호일 = 단기선이 장기선을 상향 돌파한 날.
      - 진입: 두 조건이 같은 날 성립하면 **익일 시가**. 종가 진입은 미래참조다.
      - 청산: 진입가 대비 -8% 손절 / +24% 익절, 일봉 고가·저가로 판정.
        **같은 날 둘 다 닿으면 손절 우선**(일봉으론 순서를 모른다 — 보수적으로).
      - 기간: 2025-09-01 ~ 2026-08-31. 기간 끝까지 안 닿은 포지션은 **마지막 종가로 청산**하고
        미청산 몇 건이었는지 따로 보고해라.
      - 비용: 왕복 0.52%(실측 슬리피지 반영) 차감 후로 판정.

      ## 같이 낼 것
      - 총 수익률, 거래 건수, 승률, 손절/익절/기간만료 각각 몇 건
      - 대조군: 같은 기간 같은 종목군 단순 보유 수익률. **대조군을 못 이기면 못 이긴다고 써라.**
      - 종목·날짜 편중(특정 며칠에 몰렸는지)
      - 되는 것만 고르지 마라. 5/20 과 20/60 중 한쪽이 나빠도 둘 다 표에 남겨라.

- [x] (strategy-agent 요청, TradingAgents 기법 훔쳐오기 2건 — 급하지 않음, 순서 재량)
      전체 배경: state/agent_reports/strategy-agent_20260910-153500_tradingagents_salvage.md

      **(A) look-ahead 방어 테스트를 전략 레이어로 확장**
      `tests/backtesting/ml/test_features.py:20-33`(`test_features_do_not_use_future_data`)는
      미래 시점 값을 임의로 바꿔놓고 그보다 과거 시점 출력이 안 변하는지 직접 증명하는
      돌연변이 테스트다 — 이게 `backtesting/ml/features.py`에만 있고, 실제 매매신호를
      내는 `backtesting/strategies/*.py`(new_high_swing/pullback_reentry/vcp_breakout/
      new_high_leg_exit/new_high_volume_divergence_exit/ma_crossover/rsi_strategy/envelope,
      전부 8개)엔 없다. 코드는 `shift(1)`로 맞게 짜여 있음(직접 확인함) — 지금 버그가
      있다는 게 아니라, 나중에 리팩터 중 shift 하나가 빠져도 잡아줄 회귀가 없다는 뜻.
      공유 헬퍼 하나(미래 봉 변조 → 과거 시점 신호 `assert_series_equal`) 만들어 8개
      전략 `evaluate()`에 재사용. 추정 ~60~80줄, 반나절.

      **(B) 플레이스홀더/파싱실패 방어 통일**
      `investor0782/krx.py:29-33`의 `_num()`은 파싱 실패(`ValueError`)를 그냥 `0`으로
      뭉갠다 — "데이터 없음"과 "진짜 순매수 0"이 구분 안 됨. `investor0782/
      investor_flow.py:155-160`의 `_num()`은 그 방어조차 없어(try/except 자체가 없음)
      예상 밖 문자가 오면 그냥 예외를 던진다. 대조로 `backtesting/realtime_feed.py:69`는
      이미 파싱 안 되면 `None`으로 명시적으로 구분해서 흘려보낸다(`int(values["13"])
      if values.get("13","").lstrip("-").isdigit() else None`) — 이 스타일로 두 함수
      맞춰라. 추정 ~15줄, 단 호출부가 지금 `int` 리턴을 가정하고 있으면(Optional 처리
      안 함) 호출부도 같이 봐야 함 — 손대기 전에 호출부부터 확인해라.
      (참고: `investor0782/`는 `backtesting/`이 아니라 실시간 GUI/데이터수집 쪽이다 —
      착수 전에 이 큐가 맞는 담당인지, 혹은 data-agent 쪽 큐로 옮길지 lead에게 먼저
      확인해도 된다. 사용자가 backtest-agent 큐에 넣으라고 명시적으로 지시해서 일단
      여기 올린다.)

      두 건 다 지금 급한 버그 수정이 아니라 "나중에 조용히 깨질 걸 미리 막는" 성격의
      작업이다 — 착수 순서는 backtest-agent 재량, 다른 지시가 밀려 있으면 그게 먼저다.

      **[진행 2026-09-10] (A) 완료.** `tests/backtesting/_lookahead.py`에 공유 돌연변이
      헬퍼 추가, 8개 전략 전부(`pullback_reentry` 포함, 폐기됐지만 코드/테스트 살아있어
      같이 처리) `evaluate()`에 회귀 테스트 8건 추가. 26 passed 확인. 전략 코드 자체는
      안 고침(원래 맞게 짜여 있었음). **(B)는 착수 안 함** — 호출부가 실시간 GUI/트레이딩
      루프(backtest-agent가 안 건드리던 영역)라 "위험하면 하지 말고 물어라" 원칙에 해당,
      담당(backtest-agent 계속 vs data-agent로 이관) lead 확인 요청 —
      state/agent_reports/backtest-agent_20260910-190000_lookahead_test_and_scope_question.md

      **[lead 판정 2026-09-10 17:15] (B)는 data-agent로 이관 확정.** backtest-agent
      큐에서 제거(직접 안 함). 이 항목 전체 완료 처리.

- [x] (data-agent 발견, TradingAgents salvage 후속) `grid_search.py` 조용한 실패
      전체 배경: state/agent_reports/data-agent_20260910-1712_silent_failure_fix.md

      `backtesting/grid_search.py:135-141`(`run_rule_based`)과 `215-221`
      (`run_ml_walk_forward`)에 같은 패턴이 있다:
      ```python
      try:
          candles = load_history(client, stock_code, start, end, interval=interval,
                                  use_local_data=use_local_data, data_dir=data_dir)
      except Exception:
          continue
      ```
      `load_history`가 실패한 종목(API 오류·네트워크 등)이 "이 구간에 데이터가
      원래 없어서 제외"와 똑같이 조용히 스킵된다 — 그리드서치 결과가 실제보다
      적은 종목으로 계산됐다는 걸 알 방법이 없다(data-agent가 `universe.py`
      `build_liquid_universe`/`build_topn_union_universe`에서 고친 것과 동일
      계열 문제, 2026-09-10 처리분).

      data-agent가 이미 고른 패턴(참고만, 그대로 베끼라는 뜻 아님 — 이 함수의
      호출부/반환 계약은 backtest-agent가 더 잘 안다): 실패 종목코드를 모아
      로그로 남기고, 반환값(`list[GridSearchResult]`)에 실패 정보를 얹을 방법이
      마땅치 않으면 최소한 함수 끝에 `logger.warning`으로 "N종목 중 M종목이
      조회 실패로 그리드서치에서 빠짐" 요약 한 줄. `top35_job.py`의 "실패를
      상태로 남기고 알린다" 원칙과 같은 방향.

      data-agent 담당(전략/백테스트 구현 금지) 밖이라 여기 넣기만 하고 직접
      고치지 않았다. 급하지 않음 — 순서는 backtest-agent 재량.

      **[완료 2026-09-10] 줄번호/진단 직접 대조로 정확함 확인.** `universe.py`
      패턴(개별 `logger.warning` + 실패코드 수집 + 함수 끝 요약 로그) 그대로 적용,
      `run_rule_based`/`run_ml_walk_forward` 둘 다. 반환 타입은 안 바꿈(로그만).
      신규 테스트 2건(caplog로 실패종목/건수 로그 확인), 8 passed. 전체회귀
      1022 passed/18 failed — 16개는 data-agent가 오늘 git stash로 이미 무관 확인한
      기존 실패(`_build_client(batch=...)` 시그니처 불일치)와 동일, 나머지 2개
      (test_risk_manager 동시쓰기, test_sophie_feed_monitor 폴링루프)는 내가 건드린
      모듈을 import조차 안 해 구조적으로 무관 —
      state/agent_reports/backtest-agent_20260910-174132_lookahead_guard.md

- [x] (완료 2026-09-25 — state/agent_reports/backtest-agent_20260925-1800_studio_engine.md) (lead 지시, **사용자 승인 2026-09-25 "다른 에이전트로 같이 시작해"**) **백테스트 스튜디오 module-3 (엔진 쪽) — 새 일봉 엔진 + 호환 모드 + 패리티**

      설계서: `docs/02-design/features/backtest-studio.design.md` — **§3 전체(특히 §3.1 엔티티 · §3.5 체결 규칙 ·
      §3.6 호환 모드 · §3.8 지표), §8.7 패리티, §8.8 카나리아, §9.3 import 규칙**을 먼저 읽어라.
      Plan: `docs/01-plan/features/backtest-studio.plan.md` (v0.4). B안(새로 짓기) — 사용자 선택.

      **왜**: 백테스트 GUI 용 새 엔진(손절·익절·트레일링·보유기간·사이징·현금·일별 평가)을 짓는다.
      가장 큰 위험은 **새 엔진 숫자가 네가 19번 돌린 기존 연구와 어긋나는 것** — 그래서 호환 모드가
      기존 `simulator.run` + `metrics.compute` 와 거래·지표까지 똑같이 나와야 한다(깨지면 머지 금지).

      **분담 (파일이 안 겹치게 나눴다)**
      - **너(backtest-agent)**: `studio/__init__.py`(ENGINE_VERSION="0.1.0") · `studio/domain/__init__.py` ·
        `studio/domain/models.py`(§3.1 — **제일 먼저 만들어라**, strategy-agent 가 `Panel` 속성 이름에 맞춰 짠다) ·
        `market_rules.py` · `costs.py` · `engine/fills.py` · `engine/portfolio.py` · `engine/compat.py` · `metrics.py` ·
        `tests/studio/domain/`·`tests/studio/parity/` 중 네 몫
      - **strategy-agent**: `studio/domain/spec.py` · `studio/domain/conditions/*` · `narration.py` ·
        `studio/infrastructure/legacy_strategies.py` · `presets/studio/*` — **이 파일들은 만들지도 고치지도 마라.**
        엔진은 Spec 을 몰라도 된다: 엔진 입력은 네가 정의하는 규칙 dataclass(체결·비용·청산·배분) +
        진입/청산 bool 표(index=날짜, columns=종목코드) 또는 호환 모드의 Signal 시계열이다.
        Spec → 엔진 규칙 연결(`backtest_service`)은 둘 다 끝난 뒤 lead 가 따로 넣는다.

      **할 일**
      1. `models.py`(§3.1 그대로: ExitReason · Panel · Position · Fill · Trade · BacktestResult) → STATUS 에 "models 완료" 한 줄
      2. `market_rules.py`(상하한가 ±30%·여유 0.5% · KRX 호가단위 · 정규장 시각), `costs.py`(CostModel: rate/ticks/max_rate_tick,
         `round_trip_pct`) — **P4**: `t0_forward_return.round_trip_cost_pct` 와 가격 1,000~1,000,000 격자 1e-12 일치
      3. `engine/fills.py` + `engine/portfolio.py` — §3.5 표의 봉 안 순서 1~9 그대로(갭 · 봉 안 손절/익절 · 같은 봉 정책 ·
         트레일링은 판정 **뒤** 갱신 · 보유기간 종가 청산 · 상하한가 매수 취소/매도 이월 · 거래량 한도 · 사이징 4종 · 우선순위 ·
         현금·슬롯 · 일별 MTM · `skipped` 사유별 · 데이터 끝 청산)
      4. `engine/compat.py` — §3.6 규칙 1~9 **줄 단위로** 재현 + `legacy_slots`
         - **P1**: 호환 모드 vs `backtesting.simulator.run` — ma_crossover(5/20)·rsi(14/30/70)·new_high_swing(20) ×
           실제 20종목 고정 구간 + 합성 모서리(상하한가 잠김 이월 · force_eod_close · 끝까지 미청산) → 거래 목록 동일(1e-9)
         - **P2**: 기존 CLI 기준 지표 6개 vs `metrics.compute` (1e-9)
         - **P3**: `legacy_slots` vs `portfolio_sim.simulate_slot_portfolio` — final_capital·채택/건너뜀 집합 동일
         - 신호는 기존 전략 클래스의 `evaluate()` 결과를 그대로 넣어라(조립기는 strategy-agent 몫, P6 은 그쪽)
         - 실데이터 테스트는 `@pytest.mark.parity`, 데이터 없으면 skip
      5. `metrics.py` — §3.8 표준 지표(일별 평가 기준) + 기존 CLI 기준 지표(P2 정의 그대로)
      6. **카나리아 C1**(일봉 t 이후 ×10 → t 이하 신호·t+1 이하 체결 불변) — 엔진이 미래 봉을 안 보는지
      7. `studio.domain` import 규칙 검사(§9.3: os/io/subprocess/psutil/fastapi/backtesting 등 금지) — 테스트 파일로
      8. 성능 실측: 전 종목 × 5년 일봉 포트폴리오(단순 신호로) — 목표 ≤ 30초(§8.9), 실측값 보고

      **읽기 전용 참고**: `backtesting/{simulator,metrics,portfolio_sim,types}.py`, `t0_forward_return.py`, `strategies/*`,
      `backtesting/daily_cache.load_daily_all`(실데이터 로드). **기존 `backtesting/*.py` 는 수정하지 마라.**
      data-agent 가 지금 `datahub/`·수집기들을 고치는 중이다 — 그 파일들은 건드리지 마라.

      **"그대로 믿지 말고 검증해라. 내 설계(§3.5·§3.6)가 기존 코드와 다르거나 틀렸으면 틀렸다고 해라."**
      패리티가 안 맞으면 엔진을 억지로 맞추기 전에 **어느 쪽 규칙이 옳은지부터 보고**해라.
      git commit 금지(사람이 한다). 보고: 시작·models 완료·50%·끝에 STATUS.md 자기 행,
      자세한 건 `state/agent_reports/backtest-agent_<날짜시각>_studio_engine.md`.

- [x] (완료 2026-09-25, 보고서 갱신) (lead 판정 2026-09-25, 네 결정요청 답) **거래량 한도를 전 봉(신호 봉) 거래량 기준으로 바꿔라 — 옵션 말고 유일 규칙으로**

      네 지적이 맞다: 시가 체결 시점엔 체결 봉 전체 거래량을 모른다(설계서 §3.5 가 틀렸다, 이미 고쳤다 —
      "수량 ≤ 전 봉(신호 봉) 거래량 × volume_cap_pct%"). 미래참조를 기본값으로 둘 이유가 없어 옵션도 만들지 않는다.
      1. `engine/fills.py`(또는 portfolio 쪽 해당 자리) 거래량 한도를 전 봉 거래량으로. 첫 봉(전 봉 없음)은 한도 판정 불가 →
         그 봉 진입은 `skipped.volume_cap` 가 아니라 **체결 허용**(알 수 없는 값으로 막지 않는다 — 기존 전일종가 NaN 규칙과 같은 원칙)
         인지, 막을지는 네 판단으로 정하고 보고서에 적어라.
      2. 카나리아 추가: 체결 봉 거래량만 바꿔도(×0.01, ×100) 체결·수량 불변.
      3. 네 보고서 §"설계서와 다른 곳" 4번에 "lead 판정: 전 봉 기준으로 변경" 한 줄 추가.
      `pytest tests/studio` 통과 확인. 보고: STATUS.md 자기 행 한 줄 + 보고서 갱신. git commit 금지.
      나머지 "네가 정한 것" 목록은 lead 가 검토해 설계서 §3.5 "구현에서 확정한 세부 규칙" 표로 수용했다 — 더 할 것 없음.

- [x] (완료 2026-09-25 — state/agent_reports/backtest-agent_20260925-2000_studio_service.md) (lead 지시 2026-09-25, module-3 마무리 — 사용자 승인 범위) **조립기 → 엔진 연결: `backtest_service` + `market_data`(일봉) + `run_store`**

      엔진(네 몫)·조건식(strategy-agent 몫) 둘 다 끝났다(`pytest tests/studio` 195 passed, 전 종목×5년 평가+엔진 5.7초).
      이제 Spec 하나로 끝까지 도는 길을 잇는다. 설계서 §2.2(e) 흐름, §3.2 Spec, §3.3 저장 형식, §3.7 지표 계산 규칙,
      §9.3 계층 규칙(application 은 infrastructure 를 모른다 — 포트로만)을 먼저 읽어라.

      **만들 것**
      1. `studio/application/ports.py` — `MarketData` Protocol(일봉 패널 로드(기간+워밍업 봉), 지수 프레임, 종목 정보
         (이름·업종·시장), 데이터 범위(`validate_against` 용)), `RunStore` Protocol(저장·조회)
      2. `studio/infrastructure/market_data.py` — 일봉은 `backtesting.daily_cache.load_daily_all`, 지수는
         `data/index/daily/001·101.csv`, 이름 `data/stock_names.json`, 업종 `data/sectors.csv`, 시장은
         `kospi-theme-engine/(dist/)data/reference/universe.csv` 의 market 열. **경로는 `datahub.catalog.path()` 로**
         (data-agent 가 만든 카탈로그가 있다 — 없는 데이터셋 id 면 보고)
      3. `studio/application/backtest_service.py` — `run_backtest(spec, market_data, progress=None)`:
         - `bind_params` → `validate_against`(오류면 예외, 경고는 결과에 붙임)
         - 유니버스 마스크(전체 / 거래대금 상위 N = `value_rank` t 기준 / 종목 지정 / 시장 / 제외: 스팩(이름 "스팩")·
           우선주(이름 끝 우·우B 등)·초대형주(`data_exclude.MEGA_CAP_EXCLUDE`))
         - 조건식은 **워밍업 봉까지 포함해 평가**하고 **진입은 기간 안에서만**(기간 시작 전 봉으로 체결하지 않게)
         - builder → `evaluate` / legacy → `legacy_strategies` 어댑터(BUY→진입, SELL→청산 표)
         - 모드: `daily_single`·`daily_portfolio` (+ `compat.legacy` 면 `run_compat` + 기존 CLI 기준 지표). intraday·tick 은 module-6 —
           명확한 예외로 거절
         - Spec → `CostModel`·`ExitRules`·`FillRules`·`PortfolioRules` 변환 한 곳
         - 결과 = 엔진 결과 + 표준 지표 + (호환이면) 기존 CLI 지표 + 경고 목록(표본 부족 <30건, 생존편향, 거래대금 KRX 근사
           — value/value_rank 를 썼을 때, 데이터가 기간보다 먼저 끝난 종목 수)
      4. `studio/infrastructure/run_store.py` — `results/studio/<run_id>/` 에 spec.json · meta.json(엔진 버전, git 커밋·dirty,
         데이터 범위, spec_hash, structure_hash(파라미터 값 뺀 구조), 경고, 소요 시간) · summary.json · trades.parquet · equity.parquet.
         run_id 형식 `YYYYMMDD-HHMMSS-xxxxxx`. tmp + 교체. `results/studio/` 는 .gitignore 에 추가.
      5. 테스트
         - **SC-4(플랜 성공기준)**: 프리셋 `golden_cross_5_20` 을 `daily_single` + 호환 모드로 `run_backtest` 에 넣은 결과가
           같은 종목·기간의 `simulator.run(MovingAverageCrossover 5/20)` + `metrics.compute` 와 거래·지표 1e-9 일치 — 실제 3종목, `@pytest.mark.parity`
         - 포트폴리오 스모크(합성 패널) · 워밍업(기간 시작 전 체결 0건) · 유니버스 제외 규칙 · run_store 왕복(저장 → 읽기 동일)
         - 서비스 경유 카나리아(기간 끝쪽 변조 → 앞쪽 거래 불변)
      6. 계층 규칙 검사에 application→infrastructure import 금지 추가(없으면)

      **하지 말 것**: `backtesting/*.py`·`datahub/*`·조건식 파일 수정(필요하면 편지로 요청), 서버·화면(module-2/4), git commit.
      보고: 시작·끝에 STATUS.md 자기 행, 자세한 건 `state/agent_reports/backtest-agent_<날짜시각>_studio_service.md`.
      **"그대로 믿지 말고 검증해라"** — Spec 필드가 엔진 규칙에 1:1 로 안 맞는 게 있으면 억지로 끼우지 말고 보고해라.

- [x] (완료 2026-09-25) (lead 지시 2026-09-25, module-3 점검 G3-2 — 사용자 "지금 모두 수정") **`git_info.py` 인코딩 수정**
      `subprocess.run(..., text=True)` 가 git 출력을 cp949 로 읽어, 수정 파일 목록에 한글 경로가 있으면 디코딩 실패 →
      meta.json `dirty` 가 늘 None 이 된다(lead 가 `pytest tests/studio` 경고로 확인). `encoding="utf-8", errors="replace"` 로 고치고,
      한글 경로가 있는 저장소에서도 commit·dirty 가 채워지는 테스트 추가(임시 git 저장소 + 한글 파일명).
      `datahub.catalog.path("index")` 우회는 **data-agent 가 카탈로그를 고친 뒤** 제거한다 — 지금 고쳐졌는지 확인해서
      고쳐졌으면 우회 제거, 아니면 그대로 두고 보고. 보고: STATUS.md 한 줄. git commit 금지.

- [x] (완료 2026-09-25 — state/agent_reports/backtest-agent_20260925-2345_module5_validation.md) (lead 지시 2026-09-25 22:45, **module-5 검증 — 사용자 승인 "module-2 끝나면 4~6 바로"**) **그리드·워크포워드·홀드아웃·견고성 — 도메인·서비스·작업 처리기**
      설계서 §3.8(전부)·§3.3(grid.parquet·folds.json·holdout_ledger.json)·§3.2(`params`·`validation`·숫자 칸 `{"param":..}`)·§2.4.6 CPU 줄·§8.3 #20·§8.9(그리드 100조합 ≤5분), 계획서 BT-10~12·SC-6 을 먼저 읽어라.
      1. `studio/domain/validation.py` — 거래일 달력(`datahub.calendar` 는 infrastructure 경유로 주입) 기준 분할: IS/OOS · 홀드아웃(기본 마지막 20% 거래일, 최적화 범위에서 제외) ·
         워크포워드 폴드(학습·검증·이동 거래일, 롤링/누적) · 검증 구간만 이은 곡선 · WFE · 사전 판정 기준(실행 전 입력 → 통과/기각, 실행 뒤 수정 불가)
      2. `studio/domain/robustness.py` — 비용 ×{0,0.5,1,1.5,2,3} 순수익·손익분기 배수 · 몬테카를로(거래 순수익률 복원추출 1,000회, 시드 42 → 최종수익·MDD 5/50/95%, MDD>30% 확률, "겹친 보유 무시 근사" 표시) ·
         집중도(기여 상위 1·2·3 종목/날짜 제외 순손익 + 부호 반전). **일반 백테스트 결과 summary.robustness 에도 넣는다**(결과 화면이 쓴다 — §4.2 `GET /api/runs/{id}`)
      3. 그리드: 조합 ≤5,000(초과 → `GRID_TOO_LARGE`, 500 초과 경고) · 목표 지표 sharpe/cagr/calmar/profit_factor/expectancy + 최소 거래 30 · 이웃 안정성(한 칸 옆 중앙값÷최고, <0.5 경고) ·
         **후보 선택은 IS 로만**(OOS·홀드아웃을 보고 고르면 검증이 아니다) · 병렬 수 = 소피증권 가동 시간 `cpu//4`, 야간 `cpu//2`(정책 함수 주입, BELOW_NORMAL)
      4. 홀드아웃: `holdout_check` 작업으로만 연다, `results/studio/holdout_ledger.json` 에 `structure_hash` 별 열람 기록, 두 번째부터 경고(막지는 않음). 네가 정의한 structure_hash 가 여기서 맞는지 판단해 보고
      5. `studio/application/optimize_service.py` + 처리기 `studio.application.jobs:run_optimize_job`·`run_walkforward_job`·`run_holdout_check_job`(허용 접두사 그대로), 진행률·협조 취소, 저장은 run_store(grid.parquet·folds.json)
      6. 테스트: 분할 경계(휴장일 포함 달력) · IS 만으로 선택(OOS 를 바꿔도 선택 불변 — 카나리아) · 홀드아웃 두 번째 경고 · 몬테카를로 시드 재현 · 비용 0 배수에서 비용 전 수익과 일치 · GRID_TOO_LARGE · 실측(실데이터 그리드 100조합 시간)
      API 라우트·최적화 화면은 monitoring-agent 몫(module-4 뒤) — 서비스 함수 서명과 오류 코드를 끝날 때 **monitoring-agent 에 편지**로.
      공유 파일(`run_store.py`·`wiring.py`·`application/jobs.py`)은 monitoring-agent 도 고친다 — **고치기 직전에 다시 읽고, 전체 덮어쓰기(Write) 금지, Edit 로 필요한 부분만**.
      그대로 믿지 말고 검증해라 — 설계서가 틀렸으면 틀렸다고 써라. 실데이터 예시 결과가 나쁘면 나쁘다고 써라(성과 주장 아님). git commit 금지.
      보고: STATUS.md + `state/agent_reports/backtest-agent_<날짜시각>_module5_validation.md`.

- [x] (완료 2026-09-26 — 직렬 217.8→98.3초·4워커 85.0→53.1초, 표 동일, 보고서 덧붙임) (lead 지시 2026-09-25 23:15, module-5 후속 — 병목 원칙 "측정→고치기→재측정") **지표 memo 연결 + 그리드 재측정**
      strategy-agent 가 네 제안(2340)대로 `compute`·`evaluate_group`·`evaluate` 에 `memo` 인자를 넣었다(lead 실행 test_memo·evaluator·P6 62 passed). `RunContext` 에서 `context.cache["indicator_memo"]` 를 넘겨라(한 Panel 전용).
      재측정: 그리드 100조합 직렬·4워커 — 전·후 시간, **그리드 표 전·후 완전 동일**(assert_frame_equal). 이득이 없으면 없다고 써라. 보고: STATUS 한 줄 + module-5 보고서 덧붙임.

- [x] (완료 2026-09-26 — state/agent_reports/backtest-agent_20260926-0130_grid_memory_cap.md) (lead 지시 2026-09-25 23:10 — **안전, module-6 엔진보다 먼저**) **그리드 병렬 수에 메모리 상한**
      23:05 네 `perf_grid.py 4`(워커 4개 × 0.65~0.93GB) 도는 동안 이 PC 의 **커밋 여유가 2.4GB 까지 떨어졌다**(물리 32GB 중 여유 4.4GB, Claude 세션 8개·소피증권·8765·나스닥 감시 상주).
      Claude Code 가 메모리 부족으로 lead 의 백그라운드 작업 3개를 강제 종료했다. 야간 정책은 `cpu//2` = **8워커**라 그대로 두면 커밋이 바닥나 **나스닥 감시·8765 가 할당 실패로 죽을 수 있다**.
      1. `studio/infrastructure/wiring.py:31` 의 워커 수 = `min(정책 cpu 워커, (psutil 가용 메모리 − 예비 6GB) ÷ 워커당 메모리)`, 최소 1. 워커당 메모리는 **실측값**(패널 크기 기반 추정 + 여유)
      2. 가용 메모리가 예비보다 작으면 직렬로 돌고 결과 경고에 "메모리 부족으로 직렬" 한 줄
      3. 테스트: 가짜 메모리 값으로 워커 수 계산 · 실측: 워커 1개가 실제로 차지하는 메모리(피크)
      측정용 스크립트도 이 상한을 따르게 하거나, 수동 측정 때는 예비를 확인하고 돌려라. git commit 금지. 보고: STATUS 한 줄.

- [x] (완료 2026-09-26 — state/agent_reports/backtest-agent_20260926-0100_module6_engine.md) (lead 지시 2026-09-25 22:45, module-6 엔진 — 선행 끝남 23:15: module-5 수용 · data-agent 로더 편지 2250·2320) **분봉 단타 엔진 + 틱 모드 A·B**
      `studio/domain/engine/intraday.py`: 2단계(일봉 D−1 거래대금 상위 N 사전 필터 → 분봉 신호), 봉 t 까지·일봉 피연산자 D−1, `eod_time` 15:20 종가 청산(§3.5 7번).
      `studio/domain/engine/tick.py`: **모드 A** = 분봉 신호의 체결을 체결 데이터로 정밀화(매매별 분봉 체결가 vs 틱 체결가 차이 = SC-7), **모드 B** = 틱 조건 진입(쿨다운·갭시작 +5% 제외·시간 손절·15:19:59 청산, 진입은 신호 초 s **다음** 체결).
      backtest_service 의 `ModeNotSupportedError` 해제. 카나리아 C3(분봉 k 이후+당일 일봉 변조 → k 이하 신호 불변)·C4(틱 s 이후 변조 → s 이하 불변, 진입가는 s 뒤). 성능 §8.9(60거래일×상위 30 ≤60초).
      조건식(분봉 지표·틱 조건)은 strategy-agent, 로더는 data-agent — 둘의 편지를 받고 시작. 보고: `state/agent_reports/backtest-agent_<날짜시각>_module6_engine.md`.
      lead 추가(23:15): ① **분봉 보관 기간이 종목마다 다르다**(005930 은 08-24~) → `strict=False`·`minute_coverage` 로 받되 조용히 줄이지 말고 "쓴 (날짜,종목) 쌍 / 기대 쌍"과
      "분봉 짧은 표본" 경고를 결과에 ② 분봉 `value`=종가×거래량 근사 → "거래대금 근사" 경고에 분봉 포함 ③ 체결 파일 40% 에 시각 어긋남(로더가 `to_grid` 식 안정 정렬) → 틱 결과 경고에 한 줄
      ④ 15:30 종가 단일가 봉은 끝 라벨 15:35 — `eod_time` 15:20 청산과 겹치지 않는지 테스트

- [x] (완료 2026-09-26 — module-6 보고서 덧붙임) (**00:35 풀림 — strategy-agent Spec 칸 lead 실행 28 passed, 전체 studio+jobrunner 612 passed**) (lead 지시 2026-09-26 00:15 — **사용자 결정 "통합 기본 + KRX 선택"**) **분봉 출처를 Spec 에서 받기 — 기본 통합(AL), KRX 는 선택**
      (아래 23:50 원문의 "기본 krx" 는 **폐기**. 네 배관 `LocalMarketData(minute_source=)` 는 그대로 쓰고, 서비스가 `spec.intraday.source` 를 넘긴다. 기본 al, krx 경고는 네가 만든 문구 유지.)
      (원 지시 2026-09-25 23:50) **분봉 엔진 데이터 출처 선택**
      사용자 지적: 과거 분봉은 `data/stocks/minute`(KRX, 2025-07~)에 이미 있다 — 통합 보관소(1~2개월)만 쓰면 분봉 결과가 얇다. 다시 받지 않는다.
      Spec `intraday.source: "krx" | "al"`(기본 `krx`) → 서비스·엔진이 그 출처로 읽고, meta 에 출처·종목별 사용 기간 기록, `krx` 면 경고 "NXT 체결 제외 — 2025-03 이후 거래량·거래대금 낮게 잡힘".
      틱 모드 A(정밀화)는 체결이 통합이라 출처가 섞인다는 것도 경고에. 기존 테스트·카나리아 유지. 보고: STATUS 한 줄 + module-6 보고서 덧붙임.

- [x] (완료 2026-09-26 — 36일 127.0→18.1초(7.0×), 거래 목록 동일, 엔진 보고서 덧붙임) (lead 지시 2026-09-26 08:25 — module-6 엔진 수용 후속, 병목 원칙 "측정→고치기→재측정") **틱 모드 B 체결 읽기 병목 줄이기**
      엔진 보고서(0100) 수용: 세션 규칙·C3·C4·지수 D−1 카나리아·모드 A 사후 정밀화(2차 효과 미반영 경고)·모드 B 근사 경고 — 전부 결과에 표시되는 조건으로 수용.
      남은 병목: 모드 B 8거래일×173종목 40.8초, 대부분 "종목-일 parquet 읽기·격자화"(36일이면 약 3분 추정).
      1. 먼저 **프로파일로 나눠 재라**(읽기 / 격자화 / 신호 / 시뮬레이션 비율)
      2. 새 저장소 없이 되는 것부터: 필요한 열만 읽기, 격자화 벡터화, 한 번 읽은 종목-일 재사용 — **판단 로직·결과는 그대로**(전·후 거래 목록 동일 테스트)
      3. 디스크 캐시(파생 데이터)가 꼭 필요하다고 보이면 **만들지 말고 보고** — `data/` 아래 새 데이터는 허브 카탈로그·쓰기 관문 대상이라 lead·data-agent 가 정한다
      4. 재측정: 8일·36일 전·후 시간. 이득이 작으면 작다고 써라. git commit 금지. 보고: STATUS 한 줄 + 엔진 보고서 덧붙임.

- [x] (완료 2026-09-26 — state/agent_reports/backtest-agent_20260926-1105_conditions_c1.md) (lead 지시 2026-09-26 10:00, **studio-conditions c1 — 사용자 승인 "C안, 5명 병렬"**) **시간 단위·새 연산자 — 분봉에서 일봉 지표 쓰기, N일 신고가 돌파**
      1. AST: 피연산자 `tf`(bar·m1~m60·daily_prev·daily_live, 기본 bar), `expr`(산술)·`pos`(청산 전용) 종류, Condition `hold`, Group `negate`, 연산자 cross_*_within(k)·is_true/is_false (설계 §3.1)
      2. `conditions/timeframe.py`: mN(마감된 봉만)·daily_prev(D−1)·daily_live(가상 오늘 봉, live 지표만, 거래량 계열은 krx 출처에서만) — §3.2. memo 키에 tf
      3. **IndicatorDef 에 칸 추가**(category·definition·timing·example·live) — **제일 먼저 해서 strategy·data·monitoring 에 편지**(그들이 이 모양으로 정의·표시한다)
      4. 검증: 모드별 tf 허용·live 미지원·pos 진입 금지 오류 문구. 카나리아 C5·C6. 레시피 프리셋 "분봉 N일 신고가 돌파"(`C > D.HIGHEST(H,20)` 에 해당) + SC-C1·C2 실측
      끝나면 execution-agent(수식)·monitoring-agent(화면)에 AST 모양 편지. 이어서 큐의 c2(청산 확장).
      공통: 설계서 `docs/02-design/features/studio-conditions.design.md` 를 먼저 읽어라(§3 전부·§8·§11.3). **미래참조 없음이 최우선** — 새 조건마다 카나리아. 기존 명세·프리셋·실행 결과·패리티(P1~P8) 무회귀.
      파일 규칙: 새 지표는 **자기 분류 모듈**(`ind_*.py`)에 정의 + `catalog.py`·`indicators.py` 에는 등록 한 줄만(고치기 직전 다시 읽고 Edit, 전체 덮어쓰기 금지). `ast.py`·`evaluator.py`·엔진은 backtest-agent 만.
      분봉 기본 출처 통합(AL), 실주문·KIWOOM_IS_MOCK 무접촉, git commit 금지. 그대로 믿지 말고 검증 — 설계가 틀렸으면 틀렸다고 써라.
      보고: STATUS + `state/agent_reports/backtest-agent_<날짜시각>_conditions_c1.md`.

- [x] (lead 지시 2026-09-26 10:00, studio-conditions c2 — 선행 c1) **청산 확장 — 포지션 조건·분할 익절·트레일링 발동·본전·시간 청산**
      설계 §3.3 포지션 표·§3.4. 보유 종목별 봉 t 평가(나머지 피연산자는 미리 계산한 표), 분할 조각 기록(entry_id·slice)·**진입 기준 승률**, C7, SC-C7 손계산. c1 끝나면 [ ] 로 바꾸고 시작.

- [x] (lead 지시 2026-09-26 10:05 — **c2 보다 먼저, 작게**) **c1 보정: `daily_prev` = "오늘 장 시작 전에 알 수 있는 값"** — 편지 `20260926-1005_lead_c1_판정.md` 1번 그대로. 끝나면 execution-agent 에 편지, c2 계속.

- [x] (lead 지시 2026-09-26 14:10, **studio-conditions c8 — 사용자 "틱에서 일봉까지 같이 조합" → "넣어줘"**) **틱 조건 진입(모드 B)에 분봉·일봉 조건 묶음을 AND 로**
      설계서 §3.4b(v0.4) 를 먼저 읽어라. 지금 `run_tick` 은 틱 카탈로그만 받는다(일봉은 daily_breakout·대금 순위뿐).
      1. Spec `tick.filter: Group|None`(일반 조건·연산자·수식 그대로, tf: bar=1분봉·m3~m60·daily_prev·daily_live) · `tick.prefilter: Group|None`(D−1, intraday.prefilter 와 같은 규칙) + 검증 문구
      2. `run_tick`: 틱 종목·날의 분봉(출처 규칙 같게) → 1분봉 패널에서 필터 평가(기존 평가기·시간 단위 층 재사용) → 체결 시각 s 에 **끝 시각 ≤ s 인 마지막 1분봉 값**(마감 봉만)으로 붙임 → 틱 신호 AND 필터 AND 사전 필터
      3. 분봉 없는 (종목, 날)은 필터 없음 = 진입 없음 + 결과 경고 수. 모드 A(minute_refine)는 이미 분봉·일봉 조건을 쓰니 무변경
      4. 카나리아 **C8**(s 이후 분봉·틱 변조 → s 이하 신호·진입 불변, 미마감 분봉 값 안 씀) + **SC-C8** 손계산("체결강도 ≥ 150 그리고 5분봉 20선 위 그리고 일봉 정배열(전일)") + 실데이터 실측(시간)
      끝나면 monitoring-agent(틱 탭 조건 편집기)·strategy-agent(풀이 문장)에 명세 모양 편지.
      미래참조 없음 최우선 · 분봉 기본 출처 통합 · git commit 금지. 보고: STATUS + `state/agent_reports/backtest-agent_<날짜시각>_conditions_c8.md`.

- [x] (lead 지시 2026-09-26 16:45, **studio-conditions c9 — 사용자 "몇분봉에 몇억 이상 터질 때 진입조건 추가해줘"**) **거래대금(억) 조건 — 분봉·일봉 `value_eok`·`value_sum_eok(n)` + 틱 `value_window(w_min, min_eok)`**
      설계서 §3.4c(v0.5). `ind_volume.py`(data-agent 파일 — 고치기 직전 다시 읽고 Edit)·`tick.py`·TickCatalog 칸·카탈로그 메타(정의·억 단위·예시).
      분봉 대금은 종가×거래량 근사(경고), 틱은 가격×수량 정확값. 틱 창은 `(s−w, s]`, 진입은 s 뒤(기존 규칙). 레시피 2개(분봉 5분봉 ≥20억+양봉+VWAP 위 / 틱 최근 1분 ≥10억).
      테스트: 손계산(5분봉 묶음 대금·합·틱 창 경계) + 카나리아. 끝나면 monitoring(화면 억 단위)·strategy(풀이 문장) 에 편지. git commit 금지. 보고: STATUS + 짧은 보고서.
