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
- [~] (2) MFE/MAE — 각 T0 이후 1/3/5/10분의 최대수익(MFE)·최대손실(MAE)을 계산한다.
      평균수익이 아니라 **기대값(MFE/MAE 비대칭 포함)이 가장 높은 T0 조건**을 찾는다.
      승률은 부차 지표다 — 승률 높고 기대값 낮은 구간을 골라내지 마라.
- [ ] (3) 선후관계 — "수익이 발생하기 시작하는 시점"과 "거래량(대금)이 폭발하는 시점"
      중 무엇이 먼저 오는지 초 단위로 잰다. 둘의 시차 분포(중앙값·사분위)를 낸다.
      대금폭발이 가격보다 뒤면 이 데이터로 전조 예측은 원리적으로 어렵다 — 그러면 그렇게 써라.
      같은 항목에서 "가격상승+체결속도증가가 동시에 나타나는 가속구간"을 자동 탐지해
      그 구간의 전방수익도 같이 낸다.
- [ ] (4) 매수세의 질 — 매수-매도 체결금액 격차가 급확대되는 순간, 대량 매수체결이
      연속 발생하는 구간을 찾고 각각의 전방수익을 낸다. 특히 **대량매수 후 오른 경우와
      안 오른 경우의 체결패턴 차이**를 대조표로 낸다(이게 이 항목의 핵심이다).
      "대량"의 기준은 그 시점까지의 확장분포로 정의한다 — 하루 전체 분포를 쓰면 미래정보다.
- [ ] (5) 체결↔가격 괴리 — 체결금액은 급증하는데 가격이 안 움직이는 구간 이후의
      가격 움직임을 본다. 체결금액 증가율 대비 가격상승률이 느린 구간/빠른 구간을
      나눠 전방수익을 비교한다. (매물벽 소화 가설의 검증이다)
- [ ] (6) 최종 모델 — 위 (1)~(5) 결과가 다 나온 뒤에 착수한다. T0 이전 **60초만** 써서
      T0 이후 5분내 +2% 이상 상승할 확률을 예측한다. T0 이후 데이터는 예측변수에 절대 금지.
      피처는 (1)~(5)에서 **실제로 살아남은 것만** 쓴다 — 안 되는 걸 다시 넣지 마라.
      호가잔량은 데이터가 없으니 제외하고, 제외했다고 리포트에 명시해라.
      마지막에 "어떤 조건에서 기대수익이 가장 크게 증가하는가"를 조건 2~3개 문턱으로 답한다.
