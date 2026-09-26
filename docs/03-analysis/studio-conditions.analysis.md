# studio-conditions Gap Analysis — 조건식 확장 (c1~c6)

> **기준 문서**: Plan v0.3 · Design v0.3 · **검토**: lead(테스트 재실행·성능 직접 측정·보고서·레시피 검토) · **날짜**: 2026-09-26
> 담당: backtest-agent(c1 시간 단위·c2 청산) · strategy-agent(c3 지표) · data-agent(c4 거래량·테마·업종·분봉/틱) · execution-agent(c5 사용자 수식) · monitoring-agent(c6 화면)

## Context Anchor

| Key | Value |
|-----|-------|
| **WHY** | 조건이 적어 백테스트로 확인하고 싶은 전략을 못 만든다. 특히 분봉에서 일봉 지표(신고가·이평·RSI)를 못 쓴다 |
| **WHO** | 사용자 — 8780 화면에서 직접 조립 |
| **RISK** | 새 조건의 미래참조 · 느려짐 |
| **SUCCESS** | SC-C1~C5·C7 (C6 수급·공매도는 제외) |
| **SCOPE** | 시간 단위·이평·RSI·청산 → 카탈로그·화면 → 사용자 수식 |

## 1. 결과 요약

| 축 | 일치율 | 근거 |
|----|:-----:|------|
| Structural | 100% | `conditions/{timeframe,position,formula,ind_common,ind_trend,ind_oscillator,ind_candle,ind_volume,ind_group}.py` · `infrastructure/{reference_data,formula_store}.py` · `api/routes/formulas.py` · 레시피 19개 · 화면(분류 나무·시간 단위·청산 칸·수식 편집기) |
| Functional | 99% | FR-01~12·14~16 구현(FR-13 수급·공매도는 사용자 결정으로 제외). 지표 **약 110종**(기존 17 + c3 63 + c4 24 + 틱·분봉 전용). 감점: 풀이 문장이 daily_prev 규칙 변경·c2 청산 새 칸을 아직 반영 전(strategy-agent 진행 중) |
| Contract | 100% | `/api/meta/indicators`(분류·정의·시점·live·예시) · `/api/meta/recipes` · `/api/formulas` CRUD·`/check` · validate 의 formula. 기존 명세·프리셋·결과 그대로 읽힘 |
| Runtime | 100% | lead 재실행 **pytest 1,725 passed / 12 skipped / 실패 0**(studio+jobrunner+datahub) · **vitest 232** · 라이브 E2E m7 **18/18** · 성능(아래) |
| **종합** | **99%** | (12:55 98% → 풀이 문장 반영 뒤 99%) |

## 2. 성공 기준

| SC | 상태 | 근거 |
|----|:---:|------|
| SC-C1 분봉 "현재가 > 전일까지 20일 최고가" | ✅ | 합성 3종목×304봉 손계산 일치 + 실데이터 7종목·385봉 원시 일봉 대조. 레시피 "분봉 N일 신고가 돌파" |
| SC-C2 분봉 5분 20선 위 + 일봉 20선(장중 실시간) 위 | ✅ | c1 실측 |
| SC-C3 카탈로그 60종 이상, 정의·시점·모드·테스트, 화면에 전부 | ✅ | 신규 87종(c3 63·c4 24) 전부 메타 완전 + 공통 카나리아(`test_ind_common` — 설계표 등록·메타·prefix·tamper), 화면 분류 나무 |
| SC-C4 수식 = 조립기, 오류 위치 | ✅ | 대표 21식 신호 동일, 악성 입력 거부, (줄, 칸, 기대한 것) |
| SC-C5 카나리아·패리티 무회귀 | ✅ | C5(mN 마감 봉만)·C6(daily_live 15 지표×빈칸 유무 대조)·C7(포지션 청산) + 기존 P1~P8 |
| SC-C7 "수익 5% 그리고 RSI 70" · 분할 익절 | ✅ | 손계산 20건, 진입 기준 승률(조각 승률 50% 인 진입이 진입 승률 0% 로 바르게 셈) |

**성능**: 일봉 전 종목×5년·새 지표 5개(MACD 히스토그램·스토캐스틱·ADX·이평 정배열·20일 신고가) **6.7초**(목표 ≤30초, lead 직접 측정) · 분봉 62일×상위30·조건 5개(일봉 피연산자 포함) **11.2초**(≤60초) · 테마·순위 지표 0.05~0.26초(합성 5년×1,500종목).

## 3. 검토 중 나온 판단

| # | 내용 | 판정 |
|---|------|------|
| D-1 | **`D.HIGHEST(H,20)` 이 하루 밀림**(D−21..D−2) — lead 설계 예시 오류, backtest·execution 이 발견 | `daily_prev` = "오늘 장 시작 전에 알 수 있는 값"(현재 봉을 빼는 지표는 행 D, 나머지 D−1). 세 식(`D.HIGHEST(H,20)`·`DL.HIGHEST(H,20)`·`D.HIGHEST(H,20,TRUE)`) 같은 값 + 카나리아. 수식 해석기는 문자 그대로 |
| D-2 | 상한가는 호가 반올림이 아니라 **절사**(반올림하면 130% 초과) | 수용, 설계 반영 |
| D-3 | mN 격자 = 09:00 기준 차트 격자(로더 P8 과 첫 봉이 다른 종목 있음) | 수용 + 경고 |
| D-4 | `negate` 는 값 없음이면 참 아님 | 수용(워밍업 오탐 방지) |
| D-5 | 거래량 계열 `daily_live` 는 통합 분봉에서 막음(KRX 일봉과 섞이면 부풀려짐) | 설계대로 |
| D-6 | 분할 익절 기록 = 조각 행(entry_id·slice), 지표는 진입 기준 | 설계대로, 조각 수는 따로 표시 |

## 4. Gap

| # | 심각도 | 내용 | 조치 |
|---|:---:|------|------|
| GC-1 | ~~Minor~~ 해결 | 풀이 문장이 daily_prev 새 규칙·c2 청산 칸·포지션 조건을 말하지 않음 | strategy-agent 반영("하루 묵은 값" 주의문 삭제·분할 익절 등 청산 문장·pos 문장), lead 실행 통과 |
| GC-2 | Minor | 테마·업종은 현재 구성(생존 편향) | 결과 경고로 표시 |
| GC-3 | Minor | 가장 최근 날(분봉이 일봉보다 앞선 날)엔 daily_prev 행이 없어 그 조건 신호가 안 남(NaN) | 조용히 낡은 값 안 씀 — 알고 쓸 것 |
| GC-4 | Minor | OBV 는 패널 첫 봉 0 기준(추세·교차로만 의미) | 카탈로그 정의 문구에 명시됨 |

## 5. 판정

**Match Rate 99% — 수용.** Critical·Important 없음. 13:10 전체 재실행 1,724 passed / 1 failed = 허브 쪽 오래된 가끔 실패 테스트(`test_handler_reports_waiting_lock`, 단독 6회 통과 — data-agent 에 고치게 함, 이번 기능과 무관).

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-09-26 | c1~c6 점검 | lead |
| 0.2 | 2026-09-26 | 풀이 문장 반영 확인 — 99% | lead |
