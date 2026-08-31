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
- [>] (6) 최종 모델 — 위 (1)~(5) 결과가 다 나온 뒤에 착수한다(이번 라운드에서
      (1)~(5) 전부 완료됨 — 의존성은 풀렸으나 지시대로 이번 패스에서 다시 안
      깨움, 다음 큐 실행 때 [~]로 전환해 착수). T0 이전 **60초만** 써서
      T0 이후 5분내 +2% 이상 상승할 확률을 예측한다. T0 이후 데이터는 예측변수에 절대 금지.
      피처는 (1)~(5)에서 **실제로 살아남은 것만** 쓴다 — 안 되는 걸 다시 넣지 마라.
      호가잔량은 데이터가 없으니 제외하고, 제외했다고 리포트에 명시해라.
      마지막에 "어떤 조건에서 기대수익이 가장 크게 증가하는가"를 조건 2~3개 문턱으로 답한다.
- [x] 테마순위 3축 **재측정** — 완료. 41일 전량(IS27/OOS14) vs 잠정34일(IS21/OOS13)
      나란히 비교. 결론(전부 미채택)은 안 바뀜, 세부는 다름 — 그 자체를 발견으로
      명시: H1 기각폭 축소(-3.22%→-1.10%, 196170 극단치 제거 효과로 추정), H2는
      더 나빠짐(-1.67%→-2.62%), **H3는 표본부족(판단보류, n=19)에서 표본충족
      (n=25)돼 명확한 기각으로 판정 카테고리 자체가 바뀜** — 유일하게 실질
      진전(모른다→아니다). strategy-agent에 사전등록 갱신 필요사항 전달 —
      state/agent_reports/backtest-agent_20260831-235357_theme_rank_41d_remeasurement.md
