# studio-conditions Planning Document

> **Summary**: 백테스트 스튜디오 조건식을 "키움 조건검색" 수준으로 넓힌다 — 분봉·일봉을 섞어 쓰는 다중 시간 단위, 분류별 조건 수십 종, 목록에 없는 조건을 직접 쓰는 사용자 수식
>
> **Project**: ai_stock (백테스트 스튜디오 8780)
> **Version**: studio engine 0.1.0 → 0.2
> **Author**: lead (사용자 요구 2026-09-26)
> **Date**: 2026-09-26
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 조건이 지표 17개·틱 조건 3개뿐이고, 분봉 모드에서 종목의 **일봉 지표를 못 쓴다** — "장중에 N일 신고가를 뚫으면 진입", "분봉 20선 위 + 일봉 20선 위" 같은 기본 전략조차 못 만든다. 백테스트하기에 조건이 부족하다(사용자) |
| **Solution** | ① 피연산자에 **시간 단위**(이 봉 / 다른 분봉 / 일봉 전일 확정 / 일봉 장중 실시간)를 붙인다 ② 분류별 조건 카탈로그를 **60종 이상**으로 늘린다(가격·이평·신고가, 보조지표·캔들, 거래량·순위, 테마·업종·시장, 분봉·틱 전용) ③ **사용자 수식**(안전한 해석기 → 같은 조건식 AST) ④ 수급·공매도는 과거 자료를 먼저 모으는 단계로 분리 |
| **Function/UX Effect** | 조건 고르기 창이 분류 나무 + 검색 + 설명 + 예시로 바뀌고, 조건마다 "분봉/일봉" 을 고른다. 식을 직접 써서 저장·재사용한다. 자주 쓰는 조합은 프리셋(조건검색 레시피)으로 |
| **Core Value** | 아이디어를 코드 수정 없이 바로 백테스트 — 그러면서도 **미래 데이터를 절대 못 보게**(모든 새 조건에 시점 규칙·카나리아) |

---

## Context Anchor

| Key | Value |
|-----|-------|
| **WHY** | 조건이 적어 백테스트로 확인하고 싶은 전략을 못 만든다. 특히 분봉에서 일봉 지표(신고가·이평·RSI)를 못 쓴다 |
| **WHO** | 사용자(신고가 추세·주도주·거래대금 상위·테마 매매) — 8780 스튜디오 화면에서 직접 조립 |
| **RISK** | 새 조건이 미래 데이터를 보는 것(특히 일봉 장중 실시간·다른 분봉 단위) · 조건 수가 늘며 계산이 느려짐 · 수급·공매도 과거 자료 없음 |
| **SUCCESS** | 분봉에서 "현재가 > 전일까지 20일 최고가" 진입이 돈다 · 카탈로그 60종 이상 전부 정의·시점·테스트 · 사용자 수식 = 같은 조건을 조립기로 만든 결과와 동일 · 새 조건 전부 카나리아 통과 |
| **SCOPE** | P1 다중 시간 단위 + 이평·RSI·청산 조건 → P2 카탈로그 확대 + 조건 고르기 화면 → P3 사용자 수식 (수급·공매도는 제외) |

---

## 1. Overview

### 1.1 Purpose

백테스트 스튜디오의 조건식을 **많이, 정확하게, 미래 데이터 없이** 쓸 수 있게 한다.
사용자 요구 원문: "가능한 많은 조건식을 추가할 수 있게 만들어야 돼", "이동평균선은 기본으로 들어가야 하고 **분단위 이동평균 기준 · 일봉 단위 이동평균선 기준**도 필요하고 RSI 이런 것도", "일봉 기준에서 며칠 신고가 뚫을 때 진입".

### 1.2 Background

- 지금 조건식(module-3·6): 필드 6개, 지표 17개(sma·ema·rsi·rsi_wilder·highest·lowest·change_pct·gap_pct·atr·bb_upper/lower·vol_ratio·value_rank·day_change_pct·time·cum_value·vwap), 지수 피연산자(종가·이평·등락률), 틱 조건 3종.
- 분봉 모드에서 일봉은 **사전 필터 그룹(D−1)**과 **지수(D−1)**로만 쓸 수 있고, 개별 조건 안에서 "분봉 값 vs 일봉 지표" 비교가 안 된다.
- 로컬 자료: 일봉(KRX, 2,577종목)·분봉(통합 보관소 기본 / KRX 선택)·체결(통합)·지수 일봉(코스피·코스닥 + 거래대금)·테마 6,636행·테마 그룹 602종목·업종 4,296행(모두 **현재 구성**).
  **없음**: 외국인·기관 수급 이력, 공매도 이력(2종목 캐시뿐), 시가총액·상장주식수 이력, 재무.

### 1.3 Related Documents

- 백테스트 스튜디오 계획·설계·점검: `docs/01-plan/features/backtest-studio.plan.md`, `docs/02-design/features/backtest-studio.design.md` §3.2·§3.7, `docs/03-analysis/backtest-studio.analysis.md`
- 데이터 기준 규칙: 통합(AL) 원칙, KRX 는 고른 실행만(메모리 `al-integrated-data-rule`)

---

## 2. Scope

### 2.1 In Scope

- [ ] **P1 다중 시간 단위(최우선)** — 피연산자마다 `tf`: `bar`(실행 봉) · `m1/m3/m5/m10/m15/m30/m60`(다른 분봉, 마감된 봉만) · `daily_prev`(일봉 전일 확정, D−1) · `daily_live`(일봉 장중 실시간 — 과거 일봉 + **현재 봉 종가를 오늘 종가로**, 키움 조건검색과 같은 방식). 일봉 모드는 `bar` 만
- [ ] **P1 이평·RSI 보강** — 이평 종류(단순·지수·가중·거래량 가중), 이평 배열(정배열/역배열 N개), 이격도, 이평 기울기, 골든/데드크로스 N봉 이내, RSI·RSI 신호선
- [ ] **P1 청산 조건** — 포지션 조건(매수가 대비 수익률·보유 기간·최고 수익·최고점 대비 하락)을 청산 조건식에서 쓰기, 청산 규칙 확장(분할 익절·트레일링 발동 수익·본전 손절·시간 청산). 지금 있는 익절(+X% 봉 안 체결)은 그대로
- [ ] **P2 카탈로그 확대(60종 이상)** — 분류: 가격·이평·신고가 / 보조지표 / 캔들 / 거래량·거래대금·순위 / 테마·업종·시장 / 분봉 전용 / 틱 전용 / 시간·이벤트 (목록은 §3.1 FR-03~FR-10)
- [ ] **P2 조건 고르기 화면** — 분류 나무 + 검색 + 조건 설명·시점·예시, 조건 행에서 시간 단위 선택, 조건검색 레시피 프리셋(신고가 돌파·눌림목·거래대금 급증 등)
- [ ] **P3 사용자 수식** — `C > HIGHEST(H,20)(1) AND V > MA(V,20)*2` 같은 식을 안전한 해석기(eval 금지)로 AST 로 바꿔 쓴다. 이름 붙여 저장·재사용, 오류 위치 표시, 시간 단위 접두어(`D.MA(C,20)`, `M5.RSI(14)`)

### 2.2 Out of Scope

- 재무(PER·PBR·실적)·뉴스·공시 조건 — 자료 없음
- **수급(외국인·기관·개인)·공매도 조건 — 사용자 결정 09-26 "없어도 될 거 같아"**
- 호가 조건 — 호가 수집은 새 서버 이후(사용자 결정 09-26)
- 분봉·틱 최적화·워크포워드 — 이번엔 조건식 확장만(별도 판단)
- 실시간 조건검색 알림(장중 실행) — 백테스트 전용

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 피연산자 `tf`(bar·m1~m60·daily_prev·daily_live) — 분봉 모드에서 일봉 지표를 D−1 확정 또는 장중 실시간으로 계산 | High | Pending |
| FR-02 | 분봉 모드에서 "현재가 > 전일까지 N일 최고가"(N일 신고가 돌파) 진입 — FR-01 의 대표 사례, 프리셋 제공 | High | Pending |
| FR-03 | 이평 기본 세트: SMA·EMA·WMA·VWMA, 이평 배열(정/역배열), 이격도, 기울기, 크로스 N봉 이내 — 분봉·일봉 둘 다 | High | Pending |
| FR-04 | 보조지표: MACD(선·신호·히스토그램)·스토캐스틱(빠른/느린)·CCI·ADX/DMI·OBV·MFI·윌리엄스%R·모멘텀·ROC·일목균형표(전환·기준·구름)·엔벨로프·볼린저 %b/폭·파라볼릭 SAR·켈트너·투자심리선·VR | High | Pending |
| FR-05 | 캔들: 몸통 %·윗/아랫꼬리 비율·장대양봉/음봉·도지·망치/역망치·장악형·연속 양봉/음봉 N·갭 유지/메움·상한가/하한가 도달·근접 | Medium | Pending |
| FR-06 | 거래량·거래대금·순위: 거래량 N배(전일·N일 평균 대비)·거래대금 N배·거래대금 순위(당일·N일 평균)·최근 N일 대금 상위 M 진입 횟수·회전율(자료 있으면) | High | Pending |
| FR-07 | 신고가·위치: N일/52주 신고가·신저가, 고가 대비 하락률, 저가 대비 상승률, 신고가 갱신 후 경과 봉, 박스권(N일 고저 폭) | High | Pending |
| FR-08 | 테마·업종·시장: 테마 그룹 평균 등락·대금 합·순위, 업종 등락 순위, 종목의 테마 내 순위, 지수 조건 확대(이평·RSI·이격도), 상대강도(종목 vs 지수 N일) | Medium | Pending |
| FR-09 | 분봉 전용: 당일 시가 대비·당일 고가/저가 돌파, 전일 고가 돌파(D−1), 장 시작 후 경과 분, 초반 N분 대금, VWAP 이격, 당일 누적 대금 순위 | High | Pending |
| FR-10 | 틱 전용 확대: 체결강도(매수/매도 체결량 비)·대량 체결 건수·N초 거래대금 급증·틱 속도 | Medium | Pending |
| FR-11 | 사용자 수식: 문법(산술·비교·AND/OR/NOT·함수·오프셋·시간 단위 접두어), 안전한 해석기, 오류 위치, 저장·재사용, 조립기로 만든 같은 조건과 결과 동일 | High | Pending |
| FR-12 | 조건 고르기 화면: 분류 나무·검색·설명·시점·예시, 시간 단위 선택, 레시피 프리셋 10종 이상 | High | Pending |
| FR-13 | ~~수급·공매도 조건~~ — **제외(사용자 결정 09-26)** | — | Dropped |
| FR-14 | 모든 새 조건: 정의(식)·시점 규칙·지원 모드를 카탈로그에 적고, 풀이 문장·화면 설명에 그대로 나온다 | High | Pending |
| FR-15 | **포지션 조건**(청산 조건에서 쓰는 값): 매수가 대비 수익률(%)·보유 봉/분·보유 중 최고 수익률·최고점 대비 하락률·매수가 — 예 "수익률 ≥ 5% **그리고** RSI ≥ 70 이면 매도"(사용자 요구 09-26 "매수가 대비 몇% 수익일 때 매도") | High | Pending |
| FR-16 | **청산 규칙 확장**: 분할 익절(예 +5% 에 절반, +10% 에 나머지)·수익 X% 이후에만 트레일링 발동·수익 X% 도달 뒤 손절선을 매수가로(본전)·시간 청산(N봉/N분)·익절을 봉 안 즉시 vs 종가 확인 중 선택 | High | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 정확성(미래참조 없음) | 새 조건 전부 카나리아 통과 — 봉 t 이후 변조 시 t 이하 신호 불변. `daily_live` 는 현재 봉 종가까지만, 다른 분봉 단위는 **마감된 봉만** | pytest 카나리아(C1·C3 확장) |
| 정확성(정의) | 보조지표는 널리 쓰는 정의(키움 HTS 와 같은 식)로, 기존 함수가 있으면 비트 단위 대조 | 손계산·기존 함수 패리티 |
| 성능 | 일봉 포트폴리오 전 종목×5년 조건 5개 ≤ 30초(기존 목표 유지), 분봉 2단계 60일×30 ≤ 60초 유지, 조건 20개 이상에서도 지표 memo 로 중복 계산 없음 | 실측 |
| 안전(수식) | 사용자 수식은 eval·exec·import 없이 문법 나무로만 해석, 길이·깊이 상한 | 악성 입력 테스트 |
| 호환 | 기존 명세·프리셋·실행 결과가 그대로 읽히고 같은 결과(`tf` 없으면 `bar`) | 패리티 P1~P8 재실행 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] SC-C1: 분봉 모드에서 "현재가 > 전일까지 20일 최고가(일봉 D−1)" 진입 프리셋이 돌고, 신호 시각이 손계산과 같다
- [ ] SC-C2: 분봉 모드에서 "분봉 5분 20선 위 **그리고** 일봉 20선(장중 실시간) 위" 조건이 돈다
- [ ] SC-C3: 카탈로그 60종 이상 — 전부 정의·시점·지원 모드·테스트, 화면 분류 나무에 전부 보인다
- [ ] SC-C4: 사용자 수식으로 만든 조건 = 같은 조건을 조립기로 만든 결과(신호 동일), 잘못된 식은 위치를 짚는 오류
- [ ] SC-C5: 새 조건 전부 미래참조 카나리아 통과, 기존 패리티(P1~P8)·테스트 무회귀
- ~~SC-C6: 수급·공매도~~ — 제외(사용자 결정 09-26)
- [ ] SC-C7: "수익률 ≥ 5% 그리고 RSI ≥ 70 이면 매도"·"+5% 절반 / +10% 나머지" 청산이 돌고 거래별 청산 사유·수량이 손계산과 같다

### 4.2 Quality Criteria

- [ ] 조건마다 단위 테스트(손계산 또는 알려진 값) + 카나리아
- [ ] pytest·vitest 무회귀, 빌드 성공
- [ ] 라이브 8780 E2E: 새 조건 고르기 → 실행 → 결과

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 다른 시간 단위 값이 미래를 봄(예: 5분봉을 1분 실행에 붙일 때 아직 안 끝난 봉) | High | Medium | 마감된 봉만 붙이는 규칙 + 전용 카나리아. `daily_live` 는 현재 봉 종가까지만 |
| 지표 정의가 HTS 와 달라 사용자가 헷갈림 | Medium | Medium | 정의 식을 화면에 그대로, 키움 정의와 다르면 명시 |
| 조건 수 증가로 계산이 느려짐 | Medium | Medium | 지표 memo(이미 있음)·시간 단위별 캐시, 성능 목표 재측정 |
| 수급·공매도 과거 자료 수집이 REST 를 오래 씀(계정 단위 한도) | Medium | High | P4 로 분리 — 견적 → 사용자 결정 → 주말·야간 허브 수집 |
| 테마·업종이 **현재 구성**이라 과거엔 없던 종목이 섞임(생존 편향) | Medium | High | 결과 경고 배지("테마 구성 현재 기준") |
| strategy-agent 에 Bash 가 없어 조건 테스트를 lead 가 대행 → 병목 | Medium | High | 조건 구현을 분류별로 strategy-agent·backtest-agent 에 나눔(파일 분리), 테스트는 각자 |
| 사용자 수식이 악용(과도한 계산·깊은 중첩) | Low | Low | 길이·깊이·함수 수 상한, eval 없음 |

---

## 6. Impact Analysis

### 6.1 Changed Resources

| Resource | Type | Change Description |
|----------|------|--------------------|
| `studio/domain/conditions/ast.py` (Operand) | Schema | `tf` 칸 추가(기본 `bar`), 수식 노드 |
| `studio/domain/conditions/catalog.py`·`indicators.py`·`evaluator.py` | Domain | 지표 대량 추가, 시간 단위별 계산·정렬 |
| `studio/domain/spec.py` | Schema | 사용자 수식 저장 참조, 검증 |
| `/api/meta/indicators` | API | 분류·시간 단위·예시 추가 |
| 화면 조건 편집기 | UI | 분류 나무·검색·시간 단위·수식 입력 |
| `presets/studio/*.json` | Config | 레시피 프리셋 추가(기존 6종 불변) |

### 6.2 Current Consumers

| Resource | Operation | Code Path | Impact |
|----------|-----------|-----------|--------|
| Operand | READ | 평가기·풀이 문장·validate_against·화면 SpecForm | `tf` 없으면 `bar` — 무영향 확인 필요 |
| INDICATORS 카탈로그 | READ | `/api/meta/indicators`·화면·평가기 | 칸 추가 — 화면 타입 갱신 |
| 저장된 실행 결과 spec.json | READ | 결과 화면·재실행·비교 | 옛 명세 그대로 읽힘(테스트) |
| 프리셋 6종 | READ | 백테스트 화면 | 불변 |

### 6.3 Verification

- [ ] 기존 명세·프리셋·실행 결과 로드·재실행 결과 동일
- [ ] 패리티 P1~P8 재실행
- [ ] 계층 규칙(domain 은 IO 금지) 유지

---

## 7. Architecture Considerations

### 7.1 Project Level Selection

| Level | Characteristics | Recommended For | Selected |
|-------|-----------------|-----------------|:--------:|
| **Starter** | Simple structure | Static sites | ☐ |
| **Dynamic** | Feature-based modules | Web apps with backend | ☐ |
| **Enterprise** | Strict layer separation | Complex architectures | ☑ (기존 스튜디오 구조 그대로 — domain/application/infrastructure/api) |

### 7.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| 시간 단위 표현 | 피연산자 칸 / 별도 지표 이름(`daily_sma`) | 피연산자 칸 `tf` | 지표마다 복제하지 않고 모든 지표에 한 번에 적용 |
| 사용자 수식 | Python eval / 자체 해석기 / 라이브러리 | 자체 해석기(재귀 하강) → 같은 AST | 안전(eval 금지)·기존 평가기·카나리아 재사용 |
| 다른 분봉 단위 | 리샘플 후 마감 봉 정렬 | 리샘플(P8 규칙) + 마감 시각 기준 ffill | 미래참조 차단 |
| 테스트 | pytest·vitest·E2E | 기존 그대로 | |

### 7.3 Clean Architecture Approach

```
Selected Level: Enterprise (기존 studio 계층)
studio/domain/conditions/  catalog·indicators(분류별 모듈로 나눔)·timeframe(신규)·formula(신규)·evaluator
studio/application/        명세 검증·수식 저장 서비스
studio/infrastructure/     수식·레시피 저장(presets 옆)
studio/api/routes/         meta/indicators 확장·formulas CRUD
frontend/src/components/builder/  분류 나무·검색·시간 단위·수식 편집기
```

---

## 8. Convention Prerequisites

### 8.1 Existing Project Conventions

- [x] `CLAUDE.md` 코딩 컨벤션(타입 힌트, 모듈 docstring, 비직관적 처리만 한글 주석)
- [x] 스튜디오 계층 규칙(`tests/studio/domain/test_import_rules.py`)
- [x] TypeScript 설정(`frontend/tsconfig.json`)

### 8.2 Conventions to Define/Verify

| Category | Current State | To Define | Priority |
|----------|---------------|-----------|:--------:|
| 지표 이름 | 영문 소문자(`sma`) | 분류 접두어 없이 유지, 한글 표시명·분류 칸 | High |
| 수식 함수 이름 | 없음 | 키움 수식 관리자와 비슷하게(MA·HIGHEST·CROSSUP 등) | High |
| 시간 단위 기호 | 없음 | `bar`·`m5`·`daily_prev`·`daily_live`, 수식 접두어 `M5.`·`D.`·`DL.` | High |

### 8.3 Environment Variables Needed

| Variable | Purpose | Scope | To Be Created |
|----------|---------|-------|:-------------:|
| (없음) | | | ☐ |

---

## 9. Next Steps

1. [ ] 설계 문서(`studio-conditions.design.md`) — 시간 단위 정렬 규칙·카탈로그 전체 표(식·시점·모드)·수식 문법·화면
2. [ ] 사용자 승인
3. [ ] 구현: P1(다중 시간 단위 + 이평·RSI) → P2(카탈로그·화면) → P3(수식) · P4(수급·공매도 견적 → 결정)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-09-26 | 초안 — 사용자 요구(조건 대폭 확대·분봉/일봉 이평·RSI·N일 신고가 돌파·사용자 수식) | lead |
| 0.3 | 2026-09-26 | 수급·공매도 제외(사용자) | lead |
| 0.2 | 2026-09-26 | 청산 확장 추가(사용자 "매수가 대비 몇% 수익일 때 매도") — FR-15 포지션 조건·FR-16 분할 익절 등, SC-C7 | lead |
