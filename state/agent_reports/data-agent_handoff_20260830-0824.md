# data-agent 인수인계 (2026-08-30 08:24)

컨텍스트 정리 목적. 아래 백그라운드 작업들은 /clear 해도 계속 돈다(별도 OS 프로세스라
이 세션 컨텍스트와 무관) — 잃지 않는다. 이어서 볼 때는 로그/progress 파일만 보면 됨.

## 지금 도는 백그라운드 작업
1. `python tick_collect_803_828.py` — ka10079 틱 수집, 8/03~8/28 x top35합집합 115종목
   (005930/000660 제외). 로그 `state/tick_collection/log.txt`, 진행기록
   `state/tick_collection/progress.json`(종목단위, 재개가능). 2026-08-30 08:17:54
   병렬판으로 재시작(동시성 최대 4, 아래 참고).
2. `python tick_compact_daemon.py` — 완료된 종목을 뒤에서 parquet으로 압축(원본 CSV
   삭제는 round-trip 검증 후에만). 로그 `state/tick_collection/compress_log.txt`,
   진행기록 `state/tick_collection/compress_progress.json`. 5분마다 폴링.

두 프로세스 다 살아있는지: `Get-CimInstance Win32_Process -Filter "Name='python.exe'"`
에서 커맨드라인으로 확인.

## 확인된 API 스펙
- ka10079(틱): path `/api/dostk/chart`, body `{stk_cd,tic_scope:"1",upd_stkpc_tp:"1"}`,
  응답키 `stk_tic_chart_qry`, 900건/페이지, `base_dt` 무시됨 — 최신부터 cont_yn/next_key로
  거슬러 올라가는 방식만 됨(과거 특정일 콕 집어 조회 불가).
- 종목당 페이지수 편차 큼(714~2036페이지 실측, 유동성에 비례) — 평균이 아니라
  종목별로 크게 다르다는 걸 ETA 계산에 반영해야 함.
- 분봉(ka10080) 보존기간 실측 약 13개월(2025-08-01부터, 매일 밀림) — 급하지 않음.
- 안전 동시성 실측(2026-08-30 08:06~08:15, ka10004로 30초씩): 2/3/4/5/6 전부 429
  0건, 감시봇/대시보드 하트비트·에러로그 영향 0. 6까지만 시험(그 이상 미시험).
  적용값은 6의 80%=4(사용자 지시, 여유). 429 실제로 나면 동시성 1로 낮추고 60초
  대기 후 연속 2웨이브 무사고 시에만 +1씩 천천히 복구(tick_collect_803_828.py에
  구현됨).

## 압축 규칙 (tick_compress.py)
원본 8컬럼(cur_prc,trde_qty,cntr_tm,open_pric,high_pric,low_pric,pred_pre,pred_pre_sig)
중 5개 버림:
- open/high/low: cur_prc와 항상 같음(175개 파일 전수 확인, 위반 0)
- pred_pre/pred_pre_sig: **주의 — "파일 내 상수"라는 최초 가정은 틀렸음**(175개 중
  132개=75%에서 하루중 값 바뀜, 전일종가를 여러 번 넘나드는 게 정상이라 당연함).
  대신 부호 적용(2=+,3=0,5=-)해서 `cur_prc - signed(pred_pre)`를 계산하면 파일 전체
  상수(175개 전부 확인) — 이 값이 로컬 일봉의 직전 거래일 종가와 정확히 일치함
  (009150 2026-08-03 실측: 1,142,000=1,142,000). 그래서 pred_pre/sig 둘 다 버리고
  파일당 상수 ref_price 하나(parquet 스키마 메타데이터로, 컬럼 아님)로 대체.
- 결과: 원본 대비 **6.8%**(parquet), 압축CSV(45.4%)보다도 훨씬 작음. round-trip
  175개 전수 검증 완료(불일치 0).

## 오늘 고친 것들
- `kiwoom_client.py`: `_paginate()`가 각 페이지 `return_code`를 확인 안 해서 오류를
  "더 이상 데이터 없음"으로 오인하는 취약점 발견·수정(`raise_if_error()` 공유함수
  추가, `_paginate`에서 호출). **request_tr 자체는 안 건드림** — kt00005의
  RC9000(모의투자 미지원)을 호출부가 직접 분기하는 게 이미 테스트로 고정된 의도된
  동작이라(`test_request_tr_does_not_reissue_token_on_other_api_errors`). 테스트
  2개 추가, `tests/` 전체 802 passed(무관한 기존 실패 4건 제외, trading_value_ranking
  관련, 다른 에이전트 작업 중이던 파일).
- `tick_collect_803_828.py` 자체 버그: return_code 안 봐서 79종목이 빈 채로 "완료"
  처리된 사고 — 원인은 정확히 특정 못 함(그 순간 return_code 로그를 안 남겨서
  사후재현 불가, 지금은 로그 남기게 고침). 새 프로세스로 즉시 재시도하면 복구됨
  (일시적 현상으로 보임). progress.json에서 잘못된 79개 제거 후 재시도, 이후 전부
  정상 완료.
- `kospi-theme-engine/scripts/prepare.py`, `backup_logs.py`,
  `kospi-theme-engine/scripts/fetch_minute.py`: 콘솔 리다이렉트 시 cp949로
  UnicodeEncodeError 나는 버그 — `sys.stdout.reconfigure(encoding="utf-8")` 추가.
  같은 위험 있는 스크립트 48개는 목록만 `encoding_risk_scripts.txt`에 남기고 안 고침
  (자동화 파이프에 안 걸리는 것들).
- `ai_stock/data/stocks/minute` 결측(own_median 방법 444종목 중) 교집합(행수+거래량
  이상 둘다) 방법으로 19종목(ratio<0.05)만 실제 재수집 — 17/19 진짜 결손 수정,
  2/19는 false positive(000650, 0120G0 — 재확인해도 API=로컬 동일, 그냥 그 종목
  그날 원래 거래가 적었던 것). 나머지 162종목(ratio 0.05~0.5)은 영향 미미(0.01%)+
  13개월 보존이라 보류 결정됨.

## 미해결/확인 필요
1. **지금 최우선**: 병렬화 적용 후 실제 배수가 이론치(4배)에 가까운지, 데이터
   정확성(체결가가 그 종목 주가대와 맞는지)이 실측으로 아직 확인 안 됨 — 방금
   재시작해서 첫 웨이브 결과 기다리는 중, 확인되는 대로 파일보고 예정
   (`state/agent_reports/`에 타임스탬프 파일로).
2. 162종목 분봉결측(ratio 0.05~0.5)은 보류 상태 유지 중(재판단 시점 미정).
3. 압축 데몬이 계속 따라잡는지 주기적으로 `compress_log.txt` 확인 필요(5분 폴링,
   현재까지 스킵 0건).

## 확인 사항
`/clear` 자체는 제가 직접 실행할 수 있는 툴이 없습니다(제 도구 목록에 없음) —
이 파일을 남기는 것까지가 제가 할 수 있는 부분이고, 실제 컨텍스트 정리와 재시작은
바깥에서(사용자 또는 세션 컨트롤러가) 해주셔야 합니다. 열린 백그라운드 셸 9개도
직접 정리할 방법이 없어 목록만 남깁니다 — 이 문서에 적힌 두 프로세스(tick_collect,
tick_compact) 관련 셸만 남기고 나머지 모니터링용 sleep-체크 셸들은 정리하셔도
안전합니다(로그 파일 기반으로 언제든 다시 확인 가능).
