# backtest-studio Gap Analysis — module-1 (데이터 허브 핵심)

> **범위**: Design v0.3 Session Guide `module-1` (Do 담당 data-agent, 2026-09-25 10:22~14:02)
> **기준 문서**: Plan v0.4 · Design v0.3 (§2.4, §8.2 H1~H9, §11.4, §11.5)
> **검토**: lead (테스트 재실행·diff·실동작 기록 확인) · **날짜**: 2026-09-25
> module-3(엔진·조건식)은 strategy-agent 몫이 진행 중이라 이 문서에 포함하지 않는다.

## Context Anchor

| Key | Value |
|-----|-------|
| **WHY** | 공유 데이터의 쓰기·일정이 흩어져 있어 충돌·이력 소실 위험 |
| **WHO** | 사용자 + 데이터를 같이 쓰는 소피증권·8765·연구·에이전트 |
| **RISK** | 동시 쓰기 / REST 한도 / 통합 분봉 덮어쓰기 / 소피증권이 반쪽 데이터로 켜짐 |
| **SUCCESS** | 쓰기 6곳 관문 통과 · 보관소 불감소 · 재기동 대기 |
| **SCOPE** | module-1 = 카탈로그·관문·잠금·장부·보관소·CLI·쓰는 곳 6곳·재기동 2곳 |

## 1. 결과 요약

| 축 | 일치율 | 근거 |
|----|:-----:|------|
| Structural (파일) | 100% | datahub 9개 · tests/datahub 3개 · 수정 11곳(쓰는 곳 6 · daily_cache · ps1 2 · standing · requirements) 전부 존재 |
| Functional (동작) | 93% | 12개 항목 중 9개 완전, 부분 3개(H5 정책 테스트는 module-2 로 이월 · 휴장일 2일만 · ps1 실제 실행 전) |
| Contract (인터페이스) | 100% | `write(lock, writer, detail)` · CLI 4종 · `--codes`(목록/@파일)·`--stop-at`·`--archive-only` · wait-quiet 종료코드 0/3·stdout 전용 |
| Runtime (테스트) | 100% | `pytest tests/datahub` **28 passed**(lead 재실행 14초), 기존 1,178건 무회귀(data-agent 보고), 보관 규칙 돌연변이 시 H7·H8 실패 확인 |
| **종합** | **98%** | Structural×0.15 + Functional×0.25 + Contract×0.25 + Runtime×0.35 |

## 2. 전략 정렬 (WHY 를 풀었나)

- **데이터 소실 방지 — 달성.** 통합 분봉 보관소 최초 전체 병합: 2,041종목 · 실패 0 · 76초 · 28,646,504행 · 408MB, 캐시 ⊆ 보관소 2041/2041. 기한(10-02) 전에 끝남. 이후 `fetch_minute` 은 캐시 교체 **직전** 병합하고, 병합이 실패하면 **캐시를 교체하지 않는다**(설계보다 안전).
- **중앙 통제 — 달성(쓰기 쪽).** 쓰는 곳 6곳이 전부 `datahub.write()` 안. 오늘 실제 실행 5건이 장부에 기록됨(`python -m datahub ledger`).
- **소피증권 연계 — 부분.** 재기동 2곳에 wait-quiet 추가(BOM 유지·PS 파서 통과), 실제 재기동 실행은 아직.

## 3. 성공 기준 (Plan §4)

| SC | 상태 | 근거 |
|----|:---:|------|
| SC-8 보관소 불감소 | ✅ | H7(행 감소 시 예외·미저장) + 실측 005930 13,500 → 15,576행, 캐시 md5 불변(`--archive-only`) |
| SC-10 쓰기 중 재기동 대기 | ⚠️ | 스크립트·H9(살아 있는 소유자·실행 중 표식이면 대기, 기한 초과 3) 통과. **실제 재기동 로그로 확인 필요** |
| SC-11 쓰는 곳 6곳 장부 | ⚠️ 진행 중 | 오늘 backfill·fetch_minute·archive 기록. 1주 운영 후 6곳 전부 확인 |
| SC-1 일봉 최신화 → 장부 | ✅(CLI) | `backfill_universe.py --codes=005930` 장부 기록. 화면 버튼은 module-2 |

## 4. 설계 결정 준수 (Decision Record)

| 결정 | 준수 | 비고 |
|------|:---:|------|
| 허브 = 파일 기반 라이브러리(서버 없이 동작) | ✅ | 관문·잠금·장부가 스크립트 안에서 동작 |
| 잠금 = `risk_state_lock` 재사용 | ✅ | + 같은 스레드 재진입 즉시 차단(설계에 없던 교착 방지) |
| 보관 병합은 `fetch_minute` 안, 교체 직전 | ✅ | + 병합 실패 시 캐시 미교체 |
| 소피증권은 스크립트 4개만 | ✅ | fetch_minute·fill_daily·ps1 2개. kospi-theme-engine 의 다른 변경 3개(ai_stock.spec·theme_*)는 09-21·09-23 수정분으로 이번 작업과 무관 |
| 수집은 배치 앱키 | ✅ | fill_daily 를 `batch_keys()` 로 변경 |

## 5. Gap 목록

| # | 심각도 | 내용 | 조치 |
|---|:---:|------|------|
| G1 | Important | 휴장일이 09-24·09-25 둘뿐 — KRX 공지가 로그인 리다이렉트(302)라 자동 조회 실패. 10월 초 연휴·12-25·12-31 등이 빠지면 module-2 의 신선도·조회창 계산과 정규장 경고가 그 날을 거래일로 본다 | 사람이 KRX 휴장일 확인 후 `datahub/catalog.yaml` 채움 |
| G2 | Important(운영) | 8765 대시보드가 재시작돼야 top35 관문이 적용(떠 있는 프로세스는 옛 코드) | monitoring-agent — 오늘 휴장이라 지금 재시작 가능 |
| G3 | Minor | 재기동 스크립트 2개는 파서 검증만, 실제 실행 전 | 다음 실제 재기동·재빌드 로그 확인 |
| G4 | Minor | H5(정책 행렬) 테스트 없음 — `policy.py` 가 module-2 | module-2 에서 |
| G5 | Minor(수용) | 체결 수집기 `--shard` 병렬이 이제 한 잠금으로 차례 실행 | 야간 자동 수집은 단일 프로세스라 영향 없음. 대량 소급 때 속도가 필요하면 조각별 잠금 검토 |
| G6 | Minor | `datahub status` 의 sophie_reference 날짜가 오래된 파일 기준(08-16)으로 보임 | module-2 상태 계산에서 기준 파일 정정 |

## 6. 판정

**Match Rate 98% (≥ 90%) — module-1 수용.** 코드 수정이 필요한 Critical 없음. G1·G2 는 사람/운영 조치, G3 은 다음 실운영 확인, G4·G6 은 module-2 에 포함.

---

# module-3 (백테스트 엔진 — 엔진·조건식·연결) — 2026-09-25 16:30

> 담당: backtest-agent(엔진·연결) · strategy-agent(명세·조건식·기존 전략·프리셋). lead 가 테스트 재실행·실측·보고서 검토.

## 1. 결과 요약

| 축 | 일치율 | 근거 |
|----|:-----:|------|
| Structural | 100% | domain(models·market_rules·costs·spec·narration·metrics) · conditions(ast·catalog·indicators·evaluator) · engine(fills·portfolio·compat) · application(ports·backtest_service) · infrastructure(market_data·run_store·legacy_strategies·legacy_adapter·git_info) · presets 6종. intraday/tick 엔진(module-6)·검증(module-5)은 범위 밖 |
| Functional | 96% | §3.5 체결·§3.6 호환·§3.7 지표·§3.8 지표 계산·§3.3 저장 전부 구현. 감점: git_info 한글 경로 디코딩(아래 G3-2) · 카탈로그 index 경로 임시 우회(G3-3) |
| Contract | 100% | 엔진 진입점 `run_portfolio`/`run_compat`, `run_backtest(spec, market_data)`, Spec 스키마, `results/studio/<run_id>/` 파일 구성 |
| Runtime | 100% | lead 재실행 `pytest tests/studio` **266 passed / 12 skipped**(건너뜀 = 잠김 시드, 의도된 규칙 차이), 28초. 성능 lead 실측: 전 종목 2,577×1,238일 조건식 평가 2.1초·엔진 0.4초 |
| **종합** | **99%** | |

## 2. 성공 기준

| SC | 상태 | 근거 |
|----|:---:|------|
| **SC-4** 조립기 골든크로스 호환 모드 = 기존 CLI | ✅ | 실제 3종목(000020·000050·000070, 2023-01~2026-08) 거래 82건·지표 6개 1e-9 일치, legacy 경로도 동일 |
| SC-5 비용 분리 표시 | ✅(데이터) | 거래별 수수료·세금·슬리피지 칸, 표준 지표에 비용 내역 — 화면 표시는 module-4 |
| 패리티 P1·P2·P3·P4·P6 | ✅ | P1 실제 20종목×3전략 983건, P6 빈칸 종목 실데이터 포함 |
| 카나리아 C1·C2 + 서비스 경유 | ✅ | 미래 봉 변조 시 앞쪽 신호·체결 불변 |

## 3. 검토 중 나온 판단

| # | 내용 | 판정 |
|---|------|------|
| D3-1 | 일봉 캐시는 거래정지일을 직전 종가·거래량 0 으로 채움(58,434행) → 엔진이 "거래량 0 또는 시가 NaN" 봉은 체결 불가로 처리 | **수용** — 설계서 §3.5 에 추가 |
| D3-2 | **기존 `simulator.run` 결함 발견**: 상하한가 잠김으로 이월된 SELL 이 다음 봉의 새 BUY 신호에 덮여 사라짐(보유 중인데 청산이 없어짐). 호환 모드는 그대로 재현, 일반 모드는 청산 유지 | 기록 — 과거 연구 영향은 드묾(잠김+다음 봉 BUY 동시). 영향 규모 측정은 별도 판단 |
| D3-3 | 호환 모드는 워밍업 없이 기간 캔들로만 신호 계산(기존 CLI 와 같게) — 일반 모드는 600봉 워밍업 | 수용(호환의 정의) |
| D3-4 | `daily_single` 일반 모드 기본값이 자본의 20%만 씀(최대 보유 5) | 화면(module-4) 기본값을 "최대 보유 1·비중 100%" 로 |
| D3-5 | 우선주 판별 = 이름 끝 우/우B **그리고** 코드 끝자리 ≠ 0 (보통주 '성우' 오판 방지) | 수용 |
| D3-6 | 일봉 328종목이 08-31 에서 멈춤, 시장 정보 없는 종목 419개 | 데이터 확인 필요(data-agent) — 수집 중단인지 상장폐지인지 |

## 4. Gap 목록

| # | 심각도 | 내용 | 조치 |
|---|:---:|------|------|
| G3-1 | — | (없음 — Critical 없음) | |
| G3-2 | Important | `git_info.py` 가 git 출력을 cp949 로 읽어 한글 경로가 있으면 실패 → meta.json `dirty` 가 늘 None | `subprocess.run(..., encoding="utf-8", errors="replace")` — backtest-agent |
| G3-3 | Important | `datahub.catalog.path("index")` KeyError(`{daily,minute}/{001,101}` 집합 표기) — market_data 가 임시 우회 중 | data-agent 에 편지 전달됨 → 고친 뒤 우회 제거 |
| G3-4 | Minor | D3-4 기본값 | module-4 화면 |
| G3-5 | Minor | D3-6 데이터 정체 | data-agent 확인 |

## 5. 판정

**Match Rate 99% — module-3 수용.** Critical 없음. Important 2건(G3-2, G3-3)은 작은 수정.

# module-2 (허브 서버·화면 — 실행기·API·일정·알림·화면·워치독) — 2026-09-25 22:55

> 담당: monitoring-agent(jobrunner·서버·화면·워치독) · data-agent(정책·상태·품질·소피증권·알림·수집 처리기·일정·허브 API). lead 가 테스트 재실행·프로세스 확인·보고서 검토.

## 1. 결과 요약

| 축 | 일치율 | 근거 |
|----|:-----:|------|
| Structural | 100% | §11.1 의 module-2 몫 전부: datahub(policy·status·quality·sophie·collectors·jobs·scheduler·alerts·api) · jobrunner 7파일 · studio 서버(`__main__`·api app/errors/guard/deps·routes jobs/meta) · 허브 화면 6탭 · `static/studio` · 워치독 8780 줄 · `run_studio.bat` |
| Functional | 95% | §5.4 허브 체크리스트·일정 4종(tick_nightly·daily_catchup·minute_archive·freshness)·정책·알림·수집 처리기 4종·허용 목록 구현. 감점: **진짜 수집기로 한 번도 안 돎**(G2-2) · overview 4초(목표 2초, G2-3) · 작업 폴더 보관 규칙 없음(G2-5) |
| Contract | 98% | `/api/data/*` = 계약 v1(키 집합 테스트 고정), 값 규칙 5가지는 보고서에 명시. §6 오류 봉투 + 413 추가. `/api/meta/status` 는 허브 요약 없이 작업 수만(상태 바는 overview 에서 — 프로브를 가볍게 하려는 의도적 차이) |
| Runtime | 97% | lead 재실행 **datahub 107 · studio+jobrunner 370(12 skipped) · vitest 54 통과**. 라이브: GET 17개 200 · 위조 Origin 403 · 실데이터 6탭 렌더("준비 중" 0) · 워치독 경유 재기동 `restarts.log` 기록 · minute_archive 실제 워커 성공(2,041종목). 감점: 수집 경로는 가짜 수집기로만(H13·H15~H21) |
| **종합** | **97%** | (22:55 96% → 실수집 검증 뒤 97%) |

## 2. 성공 기준

| SC | 상태 | 근거 |
|----|:---:|------|
| SC-1 버튼 → 일봉 최신화 + 장부 | ✅ | 라이브 8780 API 로 3종목 19초, 장부 `backfill_universe [daily_minute] hub 3/3`(22:19) — lead 장부 확인 |
| SC-2 체결 기간 수집 → 파일·달력 | ✅ | 001380×09-23 11초, 파일 생성·압축(`tick_compact_daemon` 첫 실전 성공)·조회창 반영, 장부 `tick_collect_804_828_al [tick_al] hub 1/1`(22:21) |
| SC-3 외부 작업 진행률·잠금 사유 | ✅(테스트) | L1 #5·#6(LOCKED·COLLECT_BUSY), 활동 목록. 라이브는 야간 백필이 도는 날 확인 |
| SC-9 정규장 대량 수집 거부 + 20:10 예약 | ✅ | L1 #2·#3, 예약 시각 야간 구간 검증(400) |
| SC-12 놓친 밤 → 다음 밤 자동 | ✅(가짜) | H16·H17·H20. 오늘 첫 회차는 빠진 쌍 0 이라 작업 없음(정상) — **첫 실전은 09-28(월) 20:15** |
| SC-13 아침 일봉 따라잡기 | ✅(가짜) | H19. 첫 실전은 거래일 아침 05:30~08:10 |

## 3. 검토 중 나온 판단

| # | 내용 | 판정 |
|---|------|------|
| D2-1 | 워커를 launcher 이중 기동으로(서버 트리 종료에도 생존 — 실측) | 수용, 설계서 §7 반영 |
| D2-2 | Host 루프백·Sec-Fetch-Site 검사, /docs 끔, 413 | 수용 |
| D2-3 | 관문이 잠금을 무기한 기다림 → 8765 top35 가 백필 뒤 108분 대기 | **그대로** — top35 는 데몬 스레드(`top35_job.py:73,213`)라 HTTP 를 안 막고, 허브 일정은 소피증권 시간 밖 |
| D2-4 | 8765 가 18:44 워치독에 재기동됨, 원인 불명(5초 프로브 1회 실패 = 즉시 재기동, 사유·로그 안 남음) | 재기동 사유 기록 + 이전 로그 한 세대 보존 추가(동작 불변). 원인은 다음 재기동 때 `state/watchdog/restarts.log` |
| D2-5 | 8780 프로브 여유 2.4초 — 허브 pandas 계산이 GIL 을 쥐어 `/api/meta/status` 도 늦어짐(스트레스 60회 중 1회 5초 초과) | **8780 만 하트비트 판정(120초)으로** — 단 하트비트는 이벤트 루프 안에서 써야 먹통을 잡는다(monitoring-agent 진행 중) |
| D2-6 | 배치 앱키 경고가 거짓(서버 환경변수에 없어서) | `.env` 의 키 이름·비어 있지 않음만 확인하게 수정(값은 안 읽음) — data-agent |

## 4. Gap 목록

| # | 심각도 | 내용 | 조치 |
|---|:---:|------|------|
| G2-1 | Important | 8780 프로브 여유 얇음(D2-5) | 하트비트 전환 — monitoring-agent 진행 중 |
| G2-2 | ~~Important~~ 해결 | 수집 경로가 진짜 수집기로 한 번도 안 돎 | 22:19·22:21 실수집 성공(위 SC-1·2). 잠금 대기·429·대량·20:15 회차는 09-28(월) 밤이 첫 실전 |
| G2-3 | Important → 반영 대기 | overview 유휴 4초(목표 ≤2초), 캐시 10초(설계 60초) | 캐시 60초로 고침(제출·일정 수정 때 비움, datahub 112 passed) — **8780 재기동 때 적용**. 첫 호출 4~7초는 남음(기록) |
| G2-4 | Minor | 원인 불명 테스트 실패 1회(이후 7회 통과) | 진단 메시지 부착됨 — 재현 시 원인 확인 |
| G2-5 | Minor | `state/jobs/` 보관 규칙 없음(OQ-7) | 하루 몇 건이라 급하지 않음 — module-4 뒤 월별 압축(삭제 안 함) |
| G2-6 | ~~Minor~~ 해결 | P7 테스트 없었음 | 실데이터 테스트 추가: 조회창 기대 종목 == 수집기 `build_universe()` |

## 5. 판정

**Match Rate 97% — module-2 수용.** Critical 없음. Important 남은 것: 하트비트 전환(진행 중)·캐시 60초 적용(재기동 대기). 사용자 지시("module-2 끝나면 4~6 바로")에 따라 module-4·5·6 동시 투입.

# module-4 (백테스트 화면 — 조립기·결과·실행 기록·비교) — 2026-09-26 07:55

> 담당: monitoring-agent. lead 가 테스트 재실행·보고서·화면 사진 검토.

## 1. 결과 요약

| 축 | 일치율 | 근거 |
|----|:-----:|------|
| Structural | 100% | API `routes/{catalog,runs,conditions,presets}.py` + `application/screener_service.py`·`run_queries.py` · 화면 BacktestPage·ResultPage·RunsPage·ComparePage |
| Functional | 95% | §5.4 백테스트·결과·기록·비교 체크리스트 구현(지표 카드 24개 판정 색, 차트 13종, 거래 → 캔들 서랍, 견고성 표시, D3-4 단일 종목 기본값). 감점: 오늘 맞는 종목 미리보기 약 13초(캐시 없음), `/bars` 분봉은 module-6 |
| Contract | 98% | §4.1 스튜디오 API 전부 + `/api/meta/data-ranges` 추가(기간 입력 제한용). 프리셋 GET 이 빠진 칸을 기본값으로 채움(손으로 쓴 프리셋이 화면을 죽인 실사고 대응) |
| Runtime | 100% | 라이브 8780 L3 #3·#4 헤드리스 Chrome **15/15** · vitest **156** · lead 재실행 studio+jobrunner **612 passed / 12 skipped / 실패 0** |
| **종합** | **98%** | |

## 2. 검토 중 나온 판단

| # | 내용 | 판정 |
|---|------|------|
| D4-1 | 입력 화면이 넓은 화면에서 왼쪽 한 줄 → 2단 배치, 사용자 요청으로 변수 표를 왼쪽 편집기 아래로(1500px 스크롤 2,900 → 1,704px) | 수용 |
| D4-2 | 결과 경고가 분봉 출처와 맞지 않던 것(krx 인데 "통합" 표기) | backtest-agent 가 출처별 문구로 수정 |

## 3. Gap

| # | 심각도 | 내용 | 조치 |
|---|:---:|------|------|
| G4-1 | Minor | 미리보기 약 13초(종목 늘면 더) | 필요해지면 캐시 |
| G4-2 | Minor | 프리셋 동시 저장은 마지막 쓴 쪽이 이김(파일 기반) | 한 사람 사용이라 수용 |
| G4-3 | Minor | L2 #7(호환 모드 잠금)·#8(검증 오류 강조)은 vitest 단위 확인, 브라우저 동작 시험은 L3 두 여정만 | 최종 QA 때 |

## 4. 판정

**Match Rate 98% — module-4 수용.** Critical·Important 없음.

# module-5 (검증 — 그리드·워크포워드·홀드아웃·견고성 + 최적화 화면) — 2026-09-26 08:20

> 담당: backtest-agent(도메인·서비스·처리기) · monitoring-agent(API·최적화 화면). lead 가 테스트 재실행·보고서 검토.

## 1. 결과 요약

| 축 | 일치율 | 근거 |
|----|:-----:|------|
| Structural | 100% | `domain/{validation,robustness}.py` · `application/{optimize_service,validation_requests}.py` · `infrastructure/holdout_ledger.py` · 처리기 3종 · `routes/validation.py` · OptimizePage + 결과 화면 종류별 패널 |
| Functional | 97% | §3.8 전부(IS 로만 선택·홀드아웃 20%·family_hash 열람 횟수·그리드 ≤5,000/500 경고·목표 5종+최소 거래·이웃 안정성·워크포워드+WFE·비용 민감도·몬테카를로·집중도·사전 판정 기준). 홀드아웃 열기 확인창(이력 못 읽으면 못 엶). 감점: 5,000행 응답 크기 미측정 · 화면에 "낮을수록 좋은 지표" 목록 복사 |
| Contract | 98% | §4.1 `/api/jobs/optimize·walkforward·holdout-check`·`/api/runs/{id}/grid·folds` + 조합 수·열람 이력 조회 추가. §8.3 #20 GRID_TOO_LARGE 422 |
| Runtime | 100% | 라이브 E2E **19/19**(최적화 → 결과 → 홀드아웃 → 워크포워드) · lead 재실행 vitest **177** · studio+jobrunner **612 passed / 실패 0** · 그리드 100조합 직렬 243초(목표 ≤300초) · 직렬==4워커 표 동일 · IS 카나리아 |
| **종합** | **98%** | |

## 2. 성공 기준

| SC | 상태 | 근거 |
|----|:---:|------|
| SC-6 워크포워드 학습/검증 성과 분리 | ✅ | 폴드 표·이은 검증 곡선·WFE, E2E |

## 3. 검토 중 나온 판단

| # | 내용 | 판정 |
|---|------|------|
| D5-1 | 홀드아웃 열람 횟수 키 = family_hash(리터럴·청산 켜고 끄기 무시) | lead 판정, 설계서 §3.8 반영 |
| D5-2 | 조합당 한 번 실행 후 곡선 자르기, WFE 정의 | 수용, 설계서 반영 |
| D5-3 | 그리드 워커 수에 메모리 상한(가용 − 예비 6GB) — 메모리가 모자라면 직렬 + 경고 | 수용(나스닥 감시 등 상주 프로세스 보호). 라이브 E2E 60조합이 직렬로 62초 |
| D5-4 | 실데이터에서 잡은 결함: numpy bool 저장 실패(1줄) · 워크포워드 거래에 MFE/MAE 없어 화면 사망 · 타입 누락 | 전부 수정·회귀 테스트 |

## 4. Gap

| # | 심각도 | 내용 | 조치 |
|---|:---:|------|------|
| G5-1 | ~~Minor~~ 해결 | 홀드아웃 장부 항목 `run_id` 가 null | backtest-agent 가 처리기에서 전달하게 고침(09-26), 워크포워드 거래표 MFE/MAE 열도 추가 |
| G5-2 | Minor | 조합 5,000개 응답 크기·속도 미측정 | 최종 QA 성능 측정 때 |
| G5-3 | Minor | 메모리 여유가 적으면 그리드가 직렬로 내려가 느려짐(목표 시간은 충족) | 기록 |

## 4. 판정

**Match Rate 98% — module-5 수용.** Critical·Important 없음.

# module-6 (분봉·틱 — 로더·조건식·엔진·화면) — 2026-09-26 08:55

> 담당: data-agent(로더) · strategy-agent(분봉 지표·틱 조건·Spec 출처 칸) · backtest-agent(분봉·틱 엔진·서비스) · monitoring-agent(분봉·틱 탭·결과). lead 가 테스트 재실행·보고서 검토.

## 1. 결과 요약

| 축 | 일치율 | 근거 |
|----|:-----:|------|
| Structural | 100% | `infrastructure/intraday_data.py` · `conditions/{intraday,prefilter,tick}.py` · `engine/{intraday,tick}.py` · `application/intraday_service.py` · 분봉·틱 탭·결과 패널·`/api/meta/intraday-sources`·분봉 `/bars` |
| Functional | 96% | BT-13 분봉 단타(2단계·EOD 15:20·날 경계 체결 없음) · BT-14 모드 A 매매별 봉↔틱 차이(SC-7) · BT-15 모드 B · 분봉 출처 통합 기본/KRX 선택(사용자 결정) · 과거 깊게 받기 실경로 1종목 확인. 감점: 분봉·틱 최적화·워크포워드 미지원(일봉 전용, 명확히 거절) · 분봉 "오늘 맞는 종목" 없음 · 통합 분봉 커버리지가 기간에 따라 39~82% |
| Contract | 98% | Spec `intraday`·`tick` 칸 1:1 + `intraday.source`. 추가 API 2개 |
| Runtime | 100% | 라이브 E2E **24/24**(분봉 통합·KRX·틱 정밀화·틱 조건) · lead 재실행 vitest **199** · studio+jobrunner **622 passed / 실패 0** · P5(실제 20파일)·P8·C3·C4·지수 D−1 카나리아 · 성능: 분봉 62일×30 **17.6초**(목표 ≤60초), 틱 모드 B 36일 127→**18초** |
| **종합** | **97%** | |

## 2. 성공 기준

| SC | 상태 | 근거 |
|----|:---:|------|
| SC-7 틱 모드 A 매매별 체결가 차이 | ✅ | 결과 거래 표·요약(`summary.tick_refine`), 실측 청산 차이 평균 −0.028% |

## 3. 검토 중 나온 판단

| # | 내용 | 판정 |
|---|------|------|
| D6-1 | 분봉 롤링 지표는 날마다 리셋하지 않음 | lead 판정, 설계서 §3.7 |
| D6-2 | 분봉 출처: lead 가 KRX 기본을 지시했다가 09-01 "통합만" 규칙과 충돌 → **사용자 결정 "통합 기본 + KRX 선택"** | 반영(Spec `intraday.source`, KRX 결과 큰 경고) |
| D6-3 | 과거 250일 재수집 지시 → 사용자 지적("이미 받았다")으로 취소 | 반영, 메모리 기록 |
| D6-4 | 체결 파일 40% 에 같은 초 순서 흔들림 — 원천 성질, 합계 정확 | 설계서 L-7, 틱 결과 경고 |
| D6-5 | 모드 A 는 사후 정밀화(슬롯·현금 2차 효과 없음), 모드 B 근사 4가지 | 결과 경고로 표시 — 수용 |

## 4. Gap

| # | 심각도 | 내용 | 조치 |
|---|:---:|------|------|
| G6-1 | Minor | 분봉·틱 최적화·워크포워드 미지원 | 필요해지면 별도 |
| G6-2 | Minor | `/api/meta/intraday-sources` 5.4초(요청마다 스캔) | 느려지면 몇 분 캐시 |
| G6-3 | Minor | 통합 분봉 보관 기간이 짧아(종목별 1~2개월) 결과가 얇음 | 표본 카드·경고로 표시. 늘리려면 과거 깊게 받기(사용자 결정) |

## 5. 판정

**Match Rate 97% — module-6 수용.** 이로써 module-1~6 전부 점검 통과(98·97·99·98·98·97).

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-09-25 | module-1 점검 | lead |
| 0.2 | 2026-09-25 | module-3 점검 추가 | lead |
| 0.3 | 2026-09-25 | module-2 점검 추가 | lead |
| 0.4 | 2026-09-26 | module-4 점검 추가 | lead |
| 0.5 | 2026-09-26 | module-5 점검 추가 | lead |
| 0.6 | 2026-09-26 | module-6 점검 추가 — 전 모듈 점검 완료 | lead |
