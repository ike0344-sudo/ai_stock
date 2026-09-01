# 대금 순위(universe.py 199/259) AL 전환 완료

lead 편지(1625)의 스코프 그대로 실행했다 — `universe.py` 199·259행 **두 곳만**,
`data_loader.py`·나머지 호출부는 안 건드렸다.

## 한 일
1. `backtesting/minute_store.py`에 `coverage()`/`assert_date_covered()` 추가
   — 종목별 (시작일,끝일)을 1,265개 파일 head/tail만 읽어 스캔(0.2초, lru_cache로
   프로세스당 1회), 범위 밖 요청이면 어느 종목·어느 날짜가 없어서인지 메시지에
   찍고 에러. 자체검사(`python -m backtesting.minute_store`) 통과.
2. `backtesting/universe.py`에 `_trading_value_minute_dir(data_dir)` 헬퍼 추가,
   199행(`intraday_top_n_return_rank1_by_minute`)·259행
   (`intraday_top_n_return_rank1_by_minute_duckdb`) 두 곳에서 사용.
   **설계 선택 하나 밝힌다(스스로 결정하고 넘기지 않음)**: `data_dir`이 기본값
   `"data"`일 때만 AL 경로로 가고, 그 외(테스트가 넘기는 `tmp_path` 등)는 기존
   KRX 레이아웃(`data_dir/stocks/minute`)을 그대로 쓴다. 이렇게 안 하면 두 함수의
   기존 단위테스트(픽스처로 소량 CSV를 tmp_path에 만들어 검증)가 전부 진짜
   1,265종목 AL 캐시를 읽게 돼 깨진다 — 테스트 파일은 손 안 대는 게 원칙이라
   이 방법을 택했다. 다른 방식(명시적 `minute_dir` 파라미터 추가 등)을 원하면
   말해달라.
3. `daily_dir`(일봉 경로)은 그대로 `data_dir/stocks/daily` — 이번 스코프 밖.

## 테스트
- `tests/backtesting/test_universe.py` 14개 전부 통과.
- 전체 스위트: **1435 passed, 4 failed**(899건이라던 이전 기준보다 스위트 자체가
  커졌다 — 다른 에이전트가 추가한 것으로 보임). 실패 4건 전부 **내 변경과 무관함
  확인**:
  - `kospi-theme-engine/test_instance_lock.py` 2건 — 격리 실행해도 실패, 소켓
    락 테스트라 실제 소피증권 프로세스가 떠 있으면 그럴 수 있음(monitoring-agent
    소관 파일, 나는 안 건드림).
  - `tests/backtesting/test_cli.py::test_run_trading_derives_paths_...` — 격리
    실행하면 통과(전체 스위트에서만 실패 — 테스트 간 상태 누수로 보이는 기존
    플레이키, universe.py/minute_store.py 무관).
  - `tests/test_kiwoom_client.py::test_request_tr_serializes_concurrent_calls...`
    — 마찬가지로 격리 실행하면 통과.
  - (참고: backtest-agent가 같은 스위트를 16:47에 돌렸을 땐 다른 2건이 실패했다고
    보고함 — 매번 다른 테스트가 걸리는 게 "내 변경 탓"이 아니라 "스위트 자체가
    플레이키하다"는 정황을 더 보강한다.)

## 검증 — 바꾸기 전후 대금 상위 25 비교 (2026-08-25, 09:00~10:00 누적)
| 순위 | KRX(before) | AL(after) |
|---|---|---|
| 1 | SK하이닉스 20,741억 | SK하이닉스 30,121억 |
| 2 | 삼성전자 16,631억 | 삼성전자 24,773억 |
| 3 | 삼성전자우 3,099억 | 삼성전기 3,336억 |
| 4 | 삼성전기 2,221억 | 삼성전자우 3,099억 |
| 5 | 두산에너빌리티 1,532억 | 한미약품 2,889억 |
| ... | (전체 25개는 리포트 첨부 로그 참고) | |

- **같은 순위 유지: 2/25**(1위 SK하이닉스, 4위권 근처 삼성전자우만 우연히 겹침) —
  순위 자체는 크게 흔들리지만 **top-25 멤버십은 20/25 유지**.
- **top25에서 빠진 5종목**(KRX에서만 상위): 해치텍, 한화머시너리앤서비스홀딩스,
  주성엔지니어링, 금호건설, HPSP — KRX 기준으로만 과대평가돼 있던 종목들.
- **top25에 새로 들어온 5종목**(AL에서만 상위): 한미사이언스, 한국전력,
  한화에어로스페이스, 고려아연, 한미반도체 — NXT 거래가 커서 KRX 전용으로는
  안 보이던 종목들.
- 값 자체도 전종목 AL > KRX(NXT가 더해지니 방향은 항상 이래야 정상 — 실제로
  전 종목 그 방향으로 확인됨, 역전된 종목 0건).
- **바뀌긴 바뀌었다** — 교체가 안 먹은 게 아니라는 확인.

## 편지
`state/agent_mail/backtest-agent/20260901-1705_AL분봉캐시_생김.md` 발송 —
1.1~1.3%p 오차가 "분봉 대 원틱" 비교였다는 것과, 이제 로컬 AL 분봉으로 §2·§3을
재측정할 수 있다는 것 전달. 재측정은 안 함(그쪽 소관).

## 안 한 것 / 남은 위험
- `data_loader.py`·나머지 8개 파일 호출부는 그대로 KRX — 지시 스코프 밖, 안 건드림.
- `_trading_value_minute_dir`의 `data_dir == "data"` 분기는 문자열 상수 비교라
  다소 암묵적이다 — 나중에 헷갈릴 수 있어 위에 이유를 명시해뒀다.
- 커버리지 체크(`assert_date_covered`)는 `minute_store.py`에 만들어뒀지만
  `universe.py`의 두 함수엔 안 걸었다 — 그 두 함수는 "요청 날짜"라는 개념이
  없고(파일에 있는 날짜를 전부 처리) 있는 데이터만 쓰므로 조용한 빈 값 위험이
  구조적으로 없다고 판단했다. 다른 판단이면 알려달라.
