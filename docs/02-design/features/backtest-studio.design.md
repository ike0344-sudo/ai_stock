# backtest-studio Design Document

> **Summary**: 공유 데이터를 중앙에서 통제하는 **데이터 허브**(`datahub` — 카탈로그·쓰기 관문·잠금·장부·정책·일정·감시·소피증권 연계·통합 분봉 보관소)와, 그 위에서 도는 **백테스트 스튜디오**(`studio` — 새 엔진·조건 조립기·최적화·워크포워드)를 짓는다. 두 쪽의 긴 작업은 공용 실행기(`jobrunner`)가 분리 프로세스로 돌린다. 화면은 8780 서버 하나(FastAPI + React)다.
>
> **Project**: ai_stock
> **Version**: datahub 0.1 / studio 0.1 (신규)
> **Author**: namdae (+Claude)
> **Date**: 2026-09-25
> **Status**: Draft
> **Planning Doc**: [backtest-studio.plan.md](../../01-plan/features/backtest-studio.plan.md) (v0.4)

### Pipeline References

| Phase | Document | Status |
|-------|----------|--------|
| Phase 1 | Schema Definition | N/A — §2.4.2 카탈로그, §3 이 대신함 |
| Phase 2 | Coding Conventions | N/A — `CLAUDE.md` + §10 |
| Phase 3 | Mockup | N/A — §5 화면 체크리스트 |
| Phase 4 | API Spec | N/A — §4 |

---

## Context Anchor

| Key | Value |
|-----|-------|
| **WHY** | 공유 데이터의 쓰기·일정이 흩어져 있어 충돌·이력 소실 위험이 있고, 검증(백테스트)은 명령줄이라 느리다 |
| **WHO** | 이 PC의 사용자 1명 (localhost 전용) + 데이터를 같이 쓰는 소피증권·8765·연구 스크립트·에이전트 |
| **RISK** | 동시 쓰기로 CSV 깨짐 / 키움 REST 429(계정 단위)로 소피증권 실시간 저하 / 통합 분봉 덮어쓰기·체결 조회창으로 영구 소실 / 새 엔진 숫자가 기존 연구와 어긋남 |
| **SUCCESS** | 공유 데이터 쓰기 6곳이 전부 관문을 지남 / 통합 분봉 갱신 뒤에도 보관소 이력 불감소 / 소피증권 정규장 시간 대량 수집 차단 / 호환 모드 = 기존 CLI |
| **SCOPE** | P1 데이터 허브(핵심 → 화면) → P2 일봉 엔진·백테스트 화면 → P3 최적화·워크포워드 → P4 분봉·틱 |

---

## 1. Overview

### 1.1 Design Goals

| # | 목표 | 확인 방법 |
|---|------|----------|
| G1 | **공유 데이터는 중앙에서 통제** — 무엇이 있고, 누가 쓰고 읽고, 얼마나 신선해야 하고, 무엇을 지우면 안 되는지 한 곳(카탈로그)에 정의하고 관문으로 강제 | 카탈로그 테스트, 장부 |
| G2 | **소피증권과 충돌 없이 연계** — 소피증권 운영 시간·재기동·기준선 갱신과 부딪히지 않고, 허브 수집 결과가 소피증권에도 쓰임 | 정책·wait-quiet 테스트, SC-9·10 |
| G3 | **데이터는 사라지지 않는다** — 통합 분봉 덮어쓰기 전 보관, 체결 조회창 소실 전 경고 | 보관 테스트, 알림 |
| G4 | 일봉·분봉·틱을 **하나의 체결 규칙**으로 계산하는 새 엔진 | 도메인 테스트 |
| G5 | 새 엔진이 **기존 연구와 비교 가능** — 호환 모드 = 기존 CLI | 패리티 §8.6 |
| G6 | 화면이 멈추지 않는다 — 긴 작업은 전부 분리 프로세스, 서버 재시작에도 계속 | L1/L3 |
| G7 | 결과를 믿을 수 있게 — 미래정보 차단, 비용 민감도·워크포워드·홀드아웃·몬테카를로 | §8.7, §3.8 |

### 1.2 Design Principles

**데이터**
- **공유 데이터 쓰기는 관문 안에서만** — `datahub.write()`(잠금 + 장부). 예외 없음. 새 코드는 경로도 카탈로그에서 얻는다.
- **허브가 꺼져도 안전** — 잠금·장부는 파일 기반 라이브러리라 수집 스크립트가 스스로 잡는다. 서버(8780)는 화면·예약·감시만 한다.
- **소피증권 데이터는 소피증권 스크립트로만 쓴다** — 허브는 그 스크립트를 부르고 관측한다. 소피증권 엔진(EXE)은 건드리지 않는다.
- **지우지 않는다** — 허브에는 삭제 기능이 없다. 보관·압축만.
- **소피증권이 먼저** — 소피증권 가동 시간에는 허브가 양보한다(REST 한도는 계정 단위).

**엔진**
- 도메인은 순수 함수(파일·네트워크·현재시각 접근 없음, §9 import 검사로 강제).
- 체결 규칙은 한 곳(`studio/domain/engine/fills.py`).
- 보수적 기본값: 같은 봉 손절·익절 둘 다면 손절 먼저 / 슬리피지 `max(비율, 1호가)` / 상하한가 잠긴 봉은 체결 안 됨.
- 숨기지 않는다: 데이터 한계는 결과 머리에 항상 표시, 정보를 접지 않는다(사용자 원칙).
- 추상화는 구현이 둘 이상이거나 테스트 대역이 필요한 곳에만.

### 1.3 새로 짓지 않는 것 (B안에서도 재사용)

| 대상 | 이유 |
|------|------|
| 수집기 `backfill_universe.py`, `tick_collect_804_828_al.py` | 야간 작업이 같은 스크립트를 쓴다. 두 벌이면 쓰기 규칙이 갈라진다. 429 이어받기·경계일 절단 방지 등 실측 교훈 포함 |
| 소피증권 `scripts/fetch_minute.py`, `run_minute_refresh.ps1`, `scripts/fill_daily.py` | 소피증권 데이터는 소피증권 스크립트로만 쓴다(§2.4.9) |
| 틱 1초 격자 `_precursor_fastpath.to_grid` | 같은 초 체결 순서 버그를 고친 판 |
| 일봉 합본 캐시 `backtesting.daily_cache.load_daily_all` | 2,577개 CSV → 0.07초 |
| 파일 잠금 `backtesting.risk_manager.risk_state_lock` | PID 생존 확인·소유 토큰·Windows 공유위반 재시도가 실측으로 다듬어짐 |
| 텔레그램 `backtesting.notifier.send_telegram` | 기존 알림 경로 |
| 체결 압축 `tick_compact_daemon.py --once` (+ `tick_compress`) | 무손실 확인 후에만 CSV → parquet — 야간 수집 뒤 그대로 호출 |

---

## 2. Architecture Options

### 2.0 Architecture Comparison

| Criteria | Option A: Minimal | Option B: Clean | Option C: Pragmatic |
|----------|:-:|:-:|:-:|
| **Approach** | 서버 파일 하나에 전부 | 허브·실행기·엔진·앱 새로 짓기, 계층 분리, React SPA | 기존 엔진 재사용 + 옵션 추가 |
| **New Files** | 3 | 약 110 (datahub 18 · jobrunner 7 · studio 40 · 프론트 45) | 약 14 |
| **Modified Files** | 1 | 11 (쓰는 곳 6 · 소피증권 재기동 2 · 워치독 · 캐시 · 규칙) | 약 9 |
| **Complexity** | Low | High | Medium |
| **Maintainability** | Medium | High | High |
| **Effort** | Low | High | Medium |
| **Risk** | 화면 멈춤·기능 부족 | 숫자 불일치 → **패리티로 차단** | 공유 엔진 회귀 |

**Selected**: **Option B — Clean** — **Rationale**: 사용자 선택(2026-09-25). 이어서 사용자 지시("데이터 관리는 중앙에서 통제", "소피증권과 충돌 없이 연계")로 데이터 쪽을 스튜디오의 한 페이지가 아니라 **독립 패키지 `datahub`** 로 올렸다 — 소피증권·8765·연구도 같은 관문을 쓰기 때문이다. 숫자 불일치 위험은 호환 모드 + 패리티(§3.6, §8.6)로 막는다.

### 2.1 Component Diagram

```
                 ┌───────────────────────────────────────────────┐
                 │ Browser — React SPA (static/studio/)          │
                 │  데이터 허브 · 백테스트 · 최적화 · 실행 기록     │
                 └───────────────────────┬───────────────────────┘
                                         │ HTTP JSON (127.0.0.1:8780)
┌────────────────────────────────────────▼────────────────────────────────────────┐
│ 8780 서버 (python -m studio) — 워치독이 상시 가동                               │
│  studio.api (FastAPI) ── datahub.api(/api/data) · jobs · runs · meta · presets  │
│  스레드: jobrunner.dispatcher (대기열·예약·한도)  ·  datahub.scheduler (일정·감시) │
└───────┬──────────────────────────────────┬─────────────────────────────┬────────┘
        │ spawn                            │ 읽기                          │ 읽기
┌───────▼────────────┐        ┌────────────▼─────────────┐      ┌────────▼──────────┐
│ jobrunner.worker   │        │ datahub (라이브러리)      │      │ studio.domain     │
│  handler 실행:      │        │  catalog · calendar ·    │      │  엔진·조건·지표·   │
│  datahub.jobs.* /  │───────►│  gate(write) · locks ·   │      │  검증 (순수)       │
│  studio 작업        │        │  ledger · policy ·       │      └───────────────────┘
└───────┬────────────┘        │  status · sophie ·       │
        │ 자식 프로세스          │  minute_al_archive       │
        ▼                     └────────────▲─────────────┘
 기존 수집기·소피증권 스크립트 ────────────────┘ (import: datahub.write)
 backfill · top35 · 지수 · 체결 · fetch_minute · fill_daily
        ▲                                   ▲
 워치독(야간·토요일) · 8765(15:40) · 수동        소피증권 재기동 스크립트 → python -m datahub wait-quiet
```

### 2.2 Data Flow

**(a) 허브에서 수집**
```
[수집] 버튼 → GET /api/data/policy (지금 가능/확인 필요/예약만) → POST /api/data/jobs/collect-*
  → 사전확인: 잠금 소유자(살아 있으면 409 LOCKED) · 허브 수집 실행 중(409 COLLECT_BUSY) · 정책
  → Job 생성(state/jobs/<id>) — 지금이면 queued, 예약이면 scheduled
  → dispatcher 가 시각·한도 확인 후 worker 기동 → 자식: 기존 수집 스크립트 (DATAHUB_TRIGGER=hub, DATAHUB_JOB_ID=<id>)
  → 스크립트가 datahub.write() 로 잠금·장부 → 진행 기록 → 허브 화면이 장부로 진행률 표시
```

**(b) 외부(워치독·8765·수동) 쓰기** — 서버를 거치지 않아도 같은 관문
```
워치독 → daily_report_job.py → backfill_universe.py → datahub.write("daily_minute") → 장부(trigger=external, cmd=...)
허브 화면 "지금 쓰는 작업"에 외부 작업도 진행률과 함께 보인다
```

**(c) 소피증권 재기동**
```
restart_after_midnight.ps1 (00:05) → python -m datahub wait-quiet --until 08:00
  → 일봉·분봉 잠금 보유자 없음 + 야간 갱신·분봉 기준선 갱신 표식이 '실행 중' 아님 → 즉시 통과
  → 아니면 60초마다 확인, 08:00 넘으면 로그 남기고 진행 → 엔진 재기동
```

**(d) 통합 분봉 갱신 → 보관**
```
fetch_minute.py (허브·워치독·수동 누가 부르든) → datahub.write("minute_al")
  → 종목마다: 보관소 ∪ 기존 캐시 ∪ 새로 받은 봉 → 보관소 저장 → 그다음 캐시를 20거래일 창으로 교체
```

**(e) 백테스트**
```
조건 조립기 → POST /api/jobs/backtest (Spec) → 검증 → Job(queued) → worker(compute 한도 2)
  → MarketData(카탈로그 경로) → 조건 평가 → 엔진 → 지표·견고성 → results/studio/<run_id>
```

### 2.3 Dependencies

**새 패키지**

| 패키지 | 쓰는 곳 | 이유 |
|--------|---------|------|
| `fastapi`, `uvicorn` | 서버 | 요청 검증·API 문서 |
| `httpx` | 테스트 | TestClient |
| (기존) `pydantic`, `psutil`, `pyyaml`, `pyarrow` | 카탈로그·명세·잠금 소유자·소피증권 설정·보관소 | 이미 설치 |
| 프론트: `react`, `react-dom`, `react-router-dom`, `antd`, `dayjs`, `echarts`, `@tanstack/react-query` | 화면 | antd 표·폼 / echarts 캔들·히트맵 |
| 프론트 개발: `vite`, `typescript`, `vitest`, `@testing-library/react`, `@playwright/test` | 빌드·테스트 | Node 24.18 / npm 11.16 확인 |

**기존 코드 재사용 경계**

| 기존 코드 | 사용처 | 용도 |
|-----------|--------|------|
| `backtesting.risk_manager.risk_state_lock` | `datahub/locks.py` | 파일 잠금 |
| `backtesting.notifier.send_telegram` | `datahub/alerts.py` | 알림 |
| `backtesting.daily_cache.load_daily_all` | `datahub/status.py`, `studio/infrastructure/market_data.py` | 일봉 전 종목 |
| `_precursor_fastpath.to_grid` | `studio/infrastructure/market_data.py` | 틱 1초 격자 |
| `backtesting.strategies.*` | `studio/infrastructure/legacy_strategies.py` | 기존 전략 |
| `simulator`·`metrics`·`portfolio_sim`·`round_trip_cost_pct`·`detect_breakouts`·`_resample_minute`·`daily_top_n_from_local` | **패리티 테스트에서만** | 숫자 대조 |

---

### 2.4 데이터 허브 (`datahub`) — 중앙 데이터 통제

#### 2.4.1 역할

| 역할 | 내용 | 모듈 |
|------|------|------|
| 카탈로그 | 공유 데이터 전부의 목록·경로·기준·쓰는/읽는 주체·잠금·신선도·보관·일정 | `catalog.yaml`, `catalog.py` |
| 달력 | 거래일 = 지나간 날은 코스피 지수 봉이 있는 날, 앞날은 평일 − 휴장일 목록 | `calendar.py` |
| 쓰기 관문 | `write()` = 잠금 + 장부 + 정책 경고 | `gate.py` |
| 잠금 | 자원 3종, 소유자 조회, 죽은 잠금 표시 | `locks.py` |
| 장부 | 모든 쓰기의 시작·진행·끝 기록(외부 작업 포함) | `ledger.py` |
| 정책 | 소피증권 운영 시간·작업 무게·동시 실행·앱키 | `policy.py` |
| 상태·감시 | 신선도·품질·결측·조회창·보관 누락·장부 밖 쓰기 | `status.py`, `quality.py` |
| 일정 | 허브 소유 일정 실행 + 외부 일정 관측 + 이관 규약 | `scheduler.py` |
| 알림 | 규칙 위반 → 텔레그램(같은 알림 하루 1회) | `alerts.py` |
| 소피증권 연계 | 설정·표식·엔진 상태·기준선 신선도 읽기 | `sophie.py` |
| 보관소 | 통합 분봉 누적 보관 | `minute_al_archive.py` |
| 수집 작업 | 수집 스크립트 명령 조립·실행 | `collectors.py`, `jobs.py` |
| CLI | `python -m datahub status · wait-quiet · ledger · archive-minute-al · check` | `__main__.py` |
| API | `/api/data/*` (FastAPI 는 이 모듈만 import) | `api.py` |

#### 2.4.2 카탈로그 (`datahub/catalog.yaml`, 커밋 대상)

```yaml
version: 1
calendar:
  source: data/index/daily/001.csv     # 지나간 거래일
  holidays: []                         # 앞으로의 KRX 휴장일 — Do 단계에서 KRX 공지로 채우고 매년 갱신
locks:
  daily_minute: {path: state/locks/data_daily_minute, covers: [daily, minute_krx, index]}
  minute_al:    {path: state/locks/data_minute_al,    covers: [minute_al, minute_al_archive]}
  tick_al:      {path: state/locks/data_tick_al,      covers: [tick_al]}
datasets:
  - id: daily
    label: 일봉
    basis: KRX
    path: data/stocks/daily/{code}.csv
    lock: daily_minute
    writers:
      - {id: backfill,  cmd: backfill_universe.py,                        triggers: [hub, "watchdog:daily_report"]}
      - {id: top35,     cmd: "backtesting/updater.py:update_top35",       triggers: ["8765:15:40", "watchdog:daily_report"]}
      - {id: fill_daily, cmd: kospi-theme-engine/scripts/fill_daily.py,   triggers: [manual]}
    readers: [소피증권 엔진(시작 시 전일 종가·신고가), 8765, studio, 연구]
    freshness: {rule: last_trading_day, deadline: "07:30"}
    retention: keep
    notes: 거래대금은 종가×거래량(KRX) 근사
  # … 나머지는 아래 표
schedules:  # §2.4.7
alerts:     # §2.4.8
```

**초기 등록 데이터셋 (11종)**

| id | 이름 | 기준 | 경로 | 잠금 | 쓰는 곳 | 읽는 곳 | 신선도 규칙 | 보관 |
|----|------|------|------|------|--------|--------|------------|------|
| `daily` | 일봉 | KRX | `data/stocks/daily/{code}.csv` | daily_minute | 백필 · top35(8765·야간) · 소피증권 fill_daily | 소피증권 엔진·8765·studio·연구 | 전 거래일, 다음 거래일 07:30까지 | 보관 |
| `minute_krx` | 1분봉(KRX) | KRX | `data/stocks/minute/{code}.csv` | daily_minute | 백필 · top35 | 소피증권 재생·기준선, 연구 | 전 거래일 | 보관 (거래대금 신호에 쓰지 말 것 — AL 규칙) |
| `index` | 지수 일봉·분봉 | KRX | `data/index/{daily,minute}/{001,101}.csv` | daily_minute | daily_report_job | studio·연구 | 전 거래일 | 보관 (값 ×100 스케일) |
| `minute_al` | 통합 1분봉 캐시 | AL | `kospi-theme-engine/data/cache/minute_al/{code}.csv` | minute_al | 소피증권 fetch_minute | 소피증권 prepare, 거래대금 순위, 연구 | 14일 이내 | **20거래일 창으로 덮어씀** |
| `minute_al_archive` | 통합 1분봉 보관소 | AL | `data/stocks/minute_al_archive/{code}.parquet` | minute_al | fetch_minute(자동 병합) · 허브 보관 | studio 분봉 | 캐시 ⊆ 보관소 | **영구** |
| `tick_al` | 통합 체결 | AL | `data/stocks/tick_al/{code}/{date}.parquet` | tick_al | 체결 수집기 | studio 틱, 연구 | 조회창(20거래일) 안 전부 수집 | **영구(재수집 불가)** |
| `sophie_reference` | 소피증권 기준 데이터 | 파생 | `kospi-theme-engine/data/reference` → `dist/data/reference` | (표식 minute_refresh) | 소피증권 prepare + 복사 | 소피증권 엔진(시작 시) | dist = data 동기 | 보관 |
| `sophie_live_logs` | 소피증권 실시간 기록 | 파생 | `kospi-theme-engine/dist/logs/*.jsonl` → `data/backup/kospi-theme-engine/{yyyymmdd}` | — | 소피증권 엔진 · backup_logs(워치독) | 연구 | 거래일 백업 존재 | **영구(재수집 불가)** |
| `reference_static` | 종목명·업종·테마 | 참조 | `data/stock_names.json`, `sectors.csv`, `themes.csv`, `theme_group_map.csv` | — | 수동 | 전부 | — | 보관 |
| `high120` | 120일 신고가 | 파생 | `data/high120.csv` | — | daily_report_job | 8765 | 전 거래일 | 재생성 가능 |
| `daily_all_cache` | 일봉 합본 | 파생 | `data/cache/daily_all.parquet` | — | 읽는 쪽이 재생성 | studio·연구 | 원본보다 새로움 | 재생성 가능 |

- 카탈로그는 pydantic 으로 검증한다: 모든 `lock` 이 `locks` 에 있음, 경로가 저장소 루트 기준으로 풀림, `writers`·`schedules` 형식.
- 새 코드는 `datahub.catalog.path("daily", code="005930")` 로 경로를 얻는다. 기존 코드의 하드코딩 경로는 그대로 두되, 카탈로그가 "무엇이 어디 있는지"의 기준이다.

#### 2.4.3 쓰기 관문 `datahub.write()` (`gate.py`)

```python
from datahub import write

with write("daily_minute", writer="backfill_universe", detail={"mode": "stale", "codes": len(codes)}) as w:
    for i, code in enumerate(codes, 1):
        ...                                   # 기존 쓰기 코드 그대로
        w.progress(i, len(codes))             # 장부에 최대 60초마다 한 줄
    w.result(ok=ok, fail=fail)
```

| 단계 | 동작 |
|------|------|
| 1 잠금 | `risk_state_lock(카탈로그 잠금 경로)` — **블로킹**(야간 작업이 실패하면 안 되므로). 기다리는 동안 60초마다 "잠금 대기: <소유자 명령줄>" 출력 |
| 2 정책 경고 | 수동 실행이 소피증권 정규장 시간이면 경고만 출력(막지 않음 — 야간·복구 작업을 깨지 않기 위함). **막는 건 허브 API 가 한다** |
| 3 장부 start | run id, 잠금, writer, pid, 명령줄, `DATAHUB_TRIGGER`(없으면 external), `DATAHUB_JOB_ID`, detail |
| 4 본문 | 기존 쓰기 코드(원자적 교체 그대로) |
| 5 장부 end | ok/실패·예외 메시지·요약 — 예외여도 기록 후 다시 던짐 |
| 6 잠금 해제 | risk_state_lock 의 토큰 확인 해제 |

적용 지점 6곳: `backfill_universe.main` · `updater.update_top35` · `daily_report_job.update_indexes` · `tick_collect_804_828_al.main` · `fetch_minute.main` · `fill_daily.main` (+ 허브 자체의 `minute_al_archive`).

#### 2.4.4 잠금 자원 (`locks.py`)

| 자원 | 파일 | 덮는 데이터 | 비고 |
|------|------|------------|------|
| `daily_minute` | `state/locks/data_daily_minute.lock` | daily, minute_krx, index | 같은 CSV 폴더를 백필·top35·fill_daily 가 같이 씀 |
| `minute_al` | `state/locks/data_minute_al.lock` | minute_al, minute_al_archive | 캐시 교체와 보관 병합을 한 잠금으로 |
| `tick_al` | `state/locks/data_tick_al.lock` | tick_al | |

- 소유자 조회 `owner(resource)`: 토큰 `pid:thread:uuid` → psutil 생존 + `create_time ≤ 잠금 파일 mtime`(PID 재사용 방지) → 명령줄·시작 시각. 소유자가 죽었는데 파일이 남아 있으면 `dead=True`(다음 획득자가 risk_state_lock 규칙대로 즉시 회수).
- 장부 파일 자체는 별도 작은 잠금(`state/locks/datahub_ledger.lock`)으로 한 줄씩 추가.

#### 2.4.5 쓰기 장부 (`ledger.py`)

`state/datahub/ledger-YYYY-MM.jsonl` (월별, 추가만)
```json
{"ts": "2026-09-25T20:12:03", "event": "start|progress|end", "run": "b3f1…", "lock": "daily_minute",
 "writer": "backfill_universe", "trigger": "hub|external", "job_id": "20260925-201000-a1b2c3",
 "pid": 1234, "cmd": "python backfill_universe.py --codes=…", "detail": {"mode": "codes", "codes": 12},
 "done": 5, "total": 12, "ok": null, "error": null}
```
- `cmd` 로 출처를 사람 말로 바꿔 보여준다: `backtesting.cli dashboard` → 8765 / `daily_report_job` → 야간 갱신 / `run_minute_refresh`·`fetch_minute` → 소피증권 / `jobrunner.worker` → 허브 / 그 외 → 수동.
- 끝 기록 없이 pid 가 죽은 run → "중단됨"으로 표시.

#### 2.4.6 정책 (`policy.py`)

시간대는 **소피증권 `config.yaml` 의 `market.open/close/connect_from/connect_to`** 에서 읽는다(지금 09:00/15:30/08:20/20:10). 소피증권이 시간을 바꾸면 허브도 따라간다. 주말·휴장일은 "야간"과 같다.

| 시간대 | 대량 수집 | 소량 수집(종목 ≤ 20) |
|--------|----------|--------------------|
| 정규장 (open~close) | **불가 — 예약만**(제안 시각 = connect_to) → 422 SOPHIE_MARKET_HOURS | 확인 후 가능 |
| 소피증권 가동 (connect_from~open, close~connect_to) | 확인 후 가능(REST 한도 공유 경고) — 기본 제안은 connect_to 예약 → 확인 없으면 422 SOPHIE_LIVE_CONFIRM | 가능 |
| 야간·주말·휴장일 | 가능 | 가능 |

- **대량**: 체결 수집, 통합 분봉(소피증권 기준선·보유 전체·깊게), 일봉(밀린 종목·전체), 종목 지정 21개 이상.
- **허브 수집은 동시에 1개**(REST 한도는 앱키를 나눠도 계정 단위 — 2026-09-20 실측). 예약된 것끼리는 순서대로.
- **앱키**: 수집은 배치 앱키(`KIWOOM_BATCH_*`) — 체결 수집기는 `--batch-key` 로 부른다. 배치키가 없으면 경고(같은 앱키로 WebSocket 을 열면 소피증권 실시간이 끊기는 규칙 때문에 분리해 둔 키).
- **CPU**: 허브·스튜디오 워커는 BELOW_NORMAL 우선순위. 소피증권 가동 시간에는 그리드 병렬 수를 `cpu//4` 로(야간 `cpu//2`).
- `GET /api/data/policy?kind=&codes=` 가 판정을 미리 돌려준다 → 화면은 버튼을 "지금 실행 / 확인 후 실행 / 20:10 예약" 으로 바꿔 보여준다.
- **예약·일정 작업은 "야간" 구간에서만 시작**하고, 수집기에 `--stop-at`(connect_from − 10분 = 08:10)을 넘겨 소피증권이 붙기 전에 스스로 멈추게 한다. 못 받은 것은 다음 회차가 이어받는다(§2.4.11).

#### 2.4.7 일정 (`scheduler.py`)

| id | 주인 | 언제 | 하는 일 | 기본 |
|----|------|------|--------|------|
| `daily_report` | 워치독 | 평일 16:00 이후 1회 | 야간 갱신(top35·백필·지수·신고가·리포트) | 관측 |
| `minute_refresh` | 워치독 | 토 09:00 이후, 마지막 완료 13일 뒤 | 소피증권 통합 분봉 기준선 갱신(ps1) | 관측 |
| `top35_live` | 8765 | 평일 15:40 | top35 증분 | 관측 |
| `sophie_restart` | 소피증권 | 매일 00:05 (`restart_after_midnight.ps1`, 1회성 실행) | 엔진 재기동 | 관측 — **2026-09-07 이후 기록 없음** |
| `sophie_rebuild` | 소피증권 | 평일 15:35 (`rebuild_after_close.ps1`) | exe 재빌드·재기동 | 관측 |
| `tick_nightly` | **허브** | 매일 20:15 (+같은 밤 재시도) | 조회창 안 **빠진 (종목, 날짜) 전부** 수집 → 압축. 놓친 밤은 다음 밤이 따라잡음(§2.4.11) | **켜짐** (사용자 결정 2026-09-25) |
| `daily_catchup` | **허브** | 거래일 05:30~08:10 | 야간 갱신을 놓쳐 일봉이 밀렸을 때만 밀린 종목(소피증권 유니버스 먼저)을 받음(§2.4.11) | 켜짐 |
| `minute_archive` | **허브** | 매일 21:00 | 캐시 중 보관소보다 새 파일 병합(안전망, API 호출 없음) | 켜짐 |
| `freshness_check` | **허브** | 10분마다 | 상태 계산 + 알림(§2.4.8) | 켜짐 |

- **허브 소유**: 서버 안 스케줄러 스레드가 1분마다 확인 → 잡 생성(`DATAHUB_TRIGGER=hub`). 서버가 꺼져 있다 켜지면 "오늘 아직 안 돈 것"은 바로 실행(시작 날짜 기준 — daily_report 규약과 같게). 켜기·끄기·시각 변경은 화면에서, 값은 `state/datahub/overrides.json`.
- **외부**: 표식(`state/daily_report`, `state/minute_refresh` — BOM 있는 JSON 은 `utf-8-sig`), 로그 끝줄(`kospi-theme-engine/logs/*.log`), 장부로 **관측만** — 마지막 실행·결과·다음 예정·놓침.
- **이관 규약(후속 M단계)**: 일정의 `owner` 를 hub 로 바꾸면 허브가 `state/datahub/owned/<id>` 표식을 만든다. 워치독은 그 표식이 있으면 해당 블록을 건너뛴다(워치독 한 줄씩 추가). 허브 2주 안정 운영 뒤 일정별로 옮긴다. 이번 범위는 규약 설계까지.

#### 2.4.8 상태·감시·알림 (`status.py`, `quality.py`, `alerts.py`)

**신선도 판정** — 좋음 / 주의 / 나쁨 (화면 색과 같은 3단계)

| 규칙 | 판정 |
|------|------|
| `last_trading_day` | 기대일 = 마감 기한(다음 거래일 07:30)이 지난 가장 최근 거래일. 기준일(종목별 최신일의 최빈값) = 기대일이면 좋음, 기한 전 밀림은 주의, 기한 후 밀림·**소피증권 유니버스 종목 밀림**은 나쁨 |
| `max_age_days` (통합 분봉 캐시) | ≤ 14일 좋음 / ≤ 21일 주의 / 그 이상 나쁨. 최빈 최신일보다 5일 넘게 뒤처진 파일 비율도 표시(소피증권 prepare 경고와 같은 기준) |
| `archive_superset` | 캐시 파일 mtime ≤ 보관소 병합 시각이면 좋음, 아니면 나쁨(보관 누락) |
| `tick_window` | 조회창 안 미수집 날짜 없음 좋음 / 있음 주의 / 남은 거래일 ≤ 2 인 미수집 날짜 나쁨 |
| `dist_sync` (소피증권 기준 데이터) | dist 와 data 수정 시각 같으면 좋음, data 가 새로우면 주의(dist 반영 안 됨) |
| `backup_exists` (소피증권 실시간 기록) | 거래일 20:10 이후 그날 백업 폴더 있으면 좋음 |

**품질 검사**(일봉): OHLC 불일치, 0 이하 가격, 중복 날짜, ±30.5% 초과 변동(수정주가 누락 의심), 5일 이상 거래량 0. **결측 거래일**: 최근 120거래일 날짜별 "데이터 있는 종목 비율".

**장부 밖 쓰기 감지**: 10분마다 데이터셋 파일 mtime 을 보고, 그 시각에 해당 잠금의 장부 run 이 없으면 "장부 없는 쓰기"로 표시(관문을 안 거친 수동 스크립트 찾기).

**알림 규칙**(텔레그램, 같은 규칙·대상은 하루 1회, 규칙별 켜기/끄기)

| id | 조건 | 기본 |
|----|------|------|
| `daily_stale_before_open` | 거래일 07:30 에 일봉 기준일 < 기대일, 또는 소피증권 유니버스 밀림 > 0 | 켜짐 |
| `tick_window_loss` | 미수집 체결 날짜가 2거래일 안에 조회창 밖으로 | 켜짐 |
| `archive_behind` | 보관 누락 | 켜짐 |
| `dead_lock_owner` | 죽은 소유자의 잠금 파일 30분 이상 | 켜짐 |
| `sophie_stale_day` | 거래일 08:20 에 소피증권 엔진 시작 시각이 오늘 00:00 이전 | 켜짐 |
| `tick_nightly_failed` | 이틀 밤 연속, 회차를 다 돌았는데도 빠진 (종목, 날짜)가 남음 | 켜짐 |
| `tick_given_up` | 3일 밤 실패로 "수동 확인 필요" 목록에 새로 들어감 | 켜짐 |
| `daily_catchup_incomplete` | 아침 따라잡기가 08:10 까지 못 끝냄(소피증권이 일부 종목 전일 종가가 밀린 채 시작) | 켜짐 |
| `unledgered_write` | 장부 없는 쓰기 감지 | 꺼짐(1주 관찰 후 켤지 결정) |

#### 2.4.9 소피증권 연계 계약

| # | 규칙 | 구현 |
|---|------|------|
| 1 | 소피증권 데이터(통합 분봉 캐시·기준 데이터)는 소피증권 스크립트로만 쓴다 | 허브는 `run_minute_refresh.ps1`·`fetch_minute` 를 부른다 |
| 2 | 소피증권 스크립트의 쓰기도 허브 관문을 쓴다 | `fetch_minute`·`fill_daily` 에 `datahub.write` |
| 3 | 운영 시간은 소피증권 설정이 기준 | `policy.py` 가 `config.yaml` 을 읽음 |
| 4 | 소피증권 엔진은 데이터 쓰기 중에 (재)기동하지 않는다 | 재기동 스크립트 2개가 `python -m datahub wait-quiet` (자정: 08:00까지, 재빌드: 30분) |
| 5 | 기준선 갱신은 다음 재기동부터 적용 — 화면에 엔진 시작 시각과 함께 표시 | `sophie.py` |
| 6 | 수집은 배치 앱키 | 체결 수집기 `--batch-key`, `fill_daily` 는 실시간 키(`KIWOOM_APPKEY`)를 직접 읽으므로 `batch_keys()` 로 바꿈, 나머지는 이미 `batch_keys()` |
| 7 | 허브는 소피증권 엔진을 끄거나 켜지 않는다 | 상태 조회만(`/healthz` 200·401 = 가동, psutil `ai_stock.exe` 시작 시각) |
| 8 | 소피증권 엔진(EXE) 코드는 수정하지 않는다 | 스크립트 4개만 |
| 9 | 소피증권 스크립트 수정은 장중(09:00~15:30) 금지, ps1 은 BOM 유지 | Do 지시에 명시 |
| 10 | `wait-quiet` 는 **stdout 에만** 쓴다 | PS 5.1 `$ErrorActionPreference='Stop'` 에서 stderr 는 NativeCommandError 가 된다(rebuild 스크립트의 PyInstaller 사례) |

`wait-quiet` 판정: 잠금 `daily_minute` 에 살아 있는 소유자 없음 **그리고** 표식 `daily_report`·`minute_refresh` 가 "실행 중"(시작 > 끝, 6시간 이내 — 워치독과 같은 규칙)이 아님. 종료코드 0 = 조용함, 3 = 기한 초과(호출한 스크립트는 로그 남기고 진행).

#### 2.4.10 통합 분봉 보관소 (`minute_al_archive.py`)

- 저장: `data/stocks/minute_al_archive/{code}.parquet` (열 date, open, high, low, close, volume — 캐시와 같음). `data/stocks/` 는 이미 gitignore.
- 병합 규칙: `보관소 ∪ 기존 캐시 ∪ 새로 받은 봉` → 같은 분은 **나중 것 우선**(늦게 받은 봉이 정정·완성본) → 정렬 → tmp + 교체. 행은 절대 줄지 않는다(테스트로 고정).
- 호출 지점: ① `fetch_minute` 이 종목 캐시를 교체하기 **직전**(누가 부르든) ② 허브 `minute_archive` 일정(안전망) ③ `python -m datahub archive-minute-al --all`(최초 1회).
- **기한**: 다음 워치독 분봉 갱신이 2026-10-03(토) 09:00 이후로 예상된다(09-19 완료 + 13일). 그 전에 ①과 ③이 배포돼야 한다.
- 과거 깊게 받기(P4): `fetch_minute --archive-only --days N --codes …` — 받은 봉을 보관소에만 병합하고 **캐시는 건드리지 않는다**(소피증권 기준선 창 유지).
- 스튜디오 분봉 백테스트는 보관소를 읽는다.

**통합 분봉 갱신 모드** (화면 버튼)

| 모드 | 명령 | 대상 | 소요(추정) | 소피증권 기준선 |
|------|------|------|-----------|----------------|
| `sophie_baseline` (권장) | `powershell -NoProfile -ExecutionPolicy Bypass -File kospi-theme-engine\run_minute_refresh.ps1 -Now` | 소피증권 기본 대상(평소 대금 100억 이상 테마 종목, 09-19 기준 288) | 약 1.5시간(09-19 실측 86분) | **갱신**(다음 재기동부터) + 워치독 표식 갱신 → 워치독 일정이 13일 밀림 |
| `all_cached` | `python -X utf8 -u -m scripts.fetch_minute --codes <캐시 전체>` (cwd kospi-theme-engine) | 2,041 | 약 9시간 | 안 바뀜 |
| `codes` | 같은 명령, `--codes` | 1~500 | 종목 × 15페이지 × 1.1초 | 안 바뀜 |
| `deep_archive` (P4) | 같은 명령 + `--days N --archive-only` | 1~300 | N 에 비례 | 안 바뀜(캐시 안 씀) |

- `sophie_baseline` 은 표식이 "실행 중"이면 409 MINUTE_REFRESH_RUNNING(워치독 회차와 겹치지 않게).
- 20:00 전 실행은 "오늘 통합 분봉은 NXT 마감(20:00) 전이라 잘림 — 다음 갱신 때 다시 받아짐" 안내(ps1 주석의 이유).

#### 2.4.11 야간 자동 수집과 따라잡기

원칙: **날짜가 아니라 "빠진 것"을 받는다.** 회차마다 "지금 받아야 하는데 없는 것"을 계산해서 받으므로, 하룻밤을 통째로 놓치거나(PC·서버 꺼짐, 오류) 일부만 받았어도 다음 회차가 자동으로 채운다.

**체결 — `tick_nightly`**

| 단계 | 내용 |
|------|------|
| 1 시작 | 매일 20:15 (주말·휴장일도 — 빠진 게 없으면 API 호출 없이 "받을 것 없음"으로 끝). 야간 갱신(`daily_report`)·분봉 기준선 갱신이 도는 중이면 끝날 때까지 대기(최대 2시간, REST 한도 경합 방지). 서버가 꺼져 있다 켜지면 야간 구간이면 바로, 아니면 다음 야간 구간 시작에 |
| 2 계획 | `status.tick_window()` → 날짜별 기대 종목 − 수집된 종목(parquet 기준) − 포기 목록 = **빠진 (종목, 날짜) 쌍** |
| 3 실행 | `tick_collect_804_828_al.py --start <가장 오래된 빠진 날> --end <가장 최근 빠진 날> --codes @codes.txt --concurrency 4 --batch-key --stop-at 08:10` — 종목 순서는 **조회창에서 먼저 사라질 날짜가 걸린 종목부터** |
| 4 압축 | 같은 잡 안에서 `tick_compact_daemon.py --once --tick-dir data/stocks/tick_al --main-progress <이번 회차 진행 파일>` → 무손실 확인된 파일만 CSV → parquet |
| 5 재확인 | 상태 다시 계산 → 아직 빠진 쌍마다 시도 횟수 +1 (`state/datahub/tick_attempts.json`) |
| 6 같은 밤 재시도 | 빠진 게 남았고(시간 초과로 미룬 것 제외) 야간 구간 안이면 60분 뒤 재시도, 하룻밤 최대 3회 |
| 7 다음 밤 | 남은 것은 다음 날 20:15 회차가 자동으로 받는다(조회창 안이면) |
| 8 포기 | 같은 쌍이 **3일 밤** 실패하면 "수동 확인 필요" 목록으로 옮겨 자동 재시도에서 뺀다 — 386380 처럼 서버 응답 한도에 걸리는 종목이 매일 밤 API 를 낭비하지 않게. 화면 [다시 시도]로 되돌린다 |

- 키움 체결(ka10079)은 최신부터 과거로만 넘어간다 → 오래된 날짜일수록 비싸다. 여러 날이 빠졌으면 **한 번의 실행으로 범위 전체**를 받는다(종목당 한 번만 거슬러 넘김).
- `--stop-at`: 수집기가 새 종목을 시작하기 전에 시각을 보고, 지났으면 그 종목은 "미룸"으로 남기고 정상 종료 → 소피증권이 붙는 08:20 전에 반드시 멈춘다.
- 조회창 20거래일이 지난 날짜는 되살릴 수 없다 — 소실 2거래일 전 알림(`tick_window_loss`)이 마지막 방어선. PC 가 20거래일 넘게 꺼져 있으면 그 사이 날짜는 잃는다(알림도 못 감).
- 압축 못 한 날짜(원본 CSV 유지)는 수집된 것으로 치되, 스튜디오 로더가 읽을 때 `tick_compress.compress` 로 같은 형식으로 바꿔 읽는다.

**일봉 — `daily_catchup`** (야간 갱신을 놓친 날의 아침 보험)

일봉은 원래 매일 밤 워치독 야간 갱신이 "밀린 종목만" 받으므로 **다음 날 16:00 회차가 자동으로 따라잡는다**. 문제는 그 사이 아침 — 소피증권은 08:20 에 전일 종가로 시작한다. 그래서 아침에 한 번 더 막는다.

| 단계 | 내용 |
|------|------|
| 1 시작 | 거래일 05:30~08:10 사이(서버가 그 사이 켜지면 그때). 일봉 신선도가 "나쁨"(기준일 < 전 거래일)이거나 소피증권 유니버스 밀림 > 0 일 때만 — 정상이면 아무것도 안 함 |
| 2 계획 | 허브가 **거래일 달력 기준**으로 밀린 종목을 계산해 넘긴다(백필 스크립트의 자체 기준은 달력일이라 월요일 아침엔 전 종목을 밀림으로 본다) — 소피증권 유니버스 종목 먼저 |
| 3 실행 | `backfill_universe.py --codes @codes.txt --stop-at 08:10` |
| 4 결과 | 08:10 까지 못 받은 종목이 남으면 `daily_catchup_incomplete` 알림(개수·소피증권 영향 종목 수). 나머지는 16:00 야간 갱신이 받는다 |

---

## 3. Data Model (백테스트 스튜디오)

### 3.1 Domain Entities (`studio/domain/models.py`)

```python
class ExitReason(StrEnum):
    SIGNAL = "signal"; STOP = "stop"; TARGET = "target"; TRAILING = "trailing"
    TIME = "time"; EOD = "eod"; END_OF_DATA = "end_of_data"

@dataclass(frozen=True)
class Panel:                       # 넓은 표 묶음 — index=시각(일 또는 봉), columns=종목코드
    open: pd.DataFrame; high: pd.DataFrame; low: pd.DataFrame
    close: pd.DataFrame; volume: pd.DataFrame
    value: pd.DataFrame            # close×volume (거래대금 근사 — §3.7)
    prev_close: pd.DataFrame       # 일자 기준 전일 종가(상하한가 판정)

@dataclass
class Position:
    code: str; qty: int; entry_ts: pd.Timestamp; entry_price: float
    stop: float | None; target: float | None; trail_peak: float | None
    bars_held: int; entry_costs: float

@dataclass(frozen=True)
class Fill:
    ts: pd.Timestamp; code: str; side: Literal["buy", "sell"]; qty: int
    price: float; reference_price: float
    commission: float; tax: float; slippage_cost: float; reason: str

@dataclass(frozen=True)
class Trade:
    code: str; entry_ts: pd.Timestamp; entry_price: float
    exit_ts: pd.Timestamp | None; exit_price: float | None; qty: int
    gross_pnl: float | None; commission: float; tax: float; slippage_cost: float
    net_pnl: float | None; net_pct: float | None; exit_reason: ExitReason | None
    bars_held: int; mfe_pct: float | None; mae_pct: float | None

@dataclass(frozen=True)
class BacktestResult:
    trades: list[Trade]
    equity: pd.DataFrame           # ts, cash, positions_value, equity, n_positions
    fills: list[Fill]
    skipped: dict[str, int]        # slots_full · cash · upper_limit · volume_cap · no_data
    diagnostics: dict
```

### 3.2 백테스트 명세 (Spec)

pydantic v2 (`studio/domain/spec.py`, `conditions/ast.py`). 숫자 칸은 전부 `number | {"param": "이름"}`.

```jsonc
{
  "version": 1,
  "name": "20일 신고가 돌파",
  "mode": "daily_portfolio",              // daily_single | daily_portfolio | intraday | tick
  "period": {"start": "2021-01-04", "end": "2026-09-23"},
  "universe": {"type": "top_value", "n": 100, "lookback_days": 1,
               "markets": ["거래소", "코스닥"], "exclude": ["spac", "preferred", "mega_cap"], "codes": []},
  "strategy": {"source": "builder",
               "entry": {"logic": "all", "items": []},
               "exit":  {"logic": "any", "items": []}},
               // legacy: {"source":"legacy","name":"new_high_swing","params":{"n_day_high":20}}
  "market_filter": null,
  "exits": {"stop_loss_pct": 7, "take_profit_pct": null, "trailing_stop_pct": 10, "max_holding_bars": 20},
  "portfolio": {"initial_capital": 10000000, "max_positions": 5, "sizing": "equal_slot_fixed",
                "fixed_amount": null, "risk_pct": null, "max_weight_pct": 25,
                "rank_by": "value", "random_seed": 42},
  "costs": {"commission_rate": 0.00015, "tax_rate": 0.0023,
            "slippage_mode": "max_rate_tick", "slippage_rate": 0.001, "slippage_ticks": 1},
  "fills": {"same_bar_policy": "stop_first", "volume_cap_pct": 10},
  "intraday": {"bar_minutes": 5, "prefilter": null, "prefilter_top_value": 30, "eod_time": "15:20"},
  "tick": {"entry_source": "catalog",
           "catalog": {"breakout_min": 5, "value_speed": null, "buy_ratio": null, "time_from": "09:05", "time_to": "15:00"},
           "cooldown_sec": 300, "exclude_gap_open_pct": 5, "time_stop_sec": 600, "eod_time": "15:19:59"},
  "compat": {"legacy": false},
  "params": {},
  "validation": null
}
```

**조건식**
```jsonc
Group     = {"logic": "all" | "any", "items": [Condition | Group]}      // 깊이 최대 2
Condition = {"left": Operand, "op": "gt|gte|lt|lte|cross_above|cross_below", "right": Operand}
Operand   = {"kind": "field",  "name": "open|high|low|close|volume|value", "offset": 0, "mul": 1}
          | {"kind": "ind",    "name": "<카탈로그>", "params": {...}, "offset": 0, "mul": 1}
          | {"kind": "market", "index": "kospi|kosdaq", "name": "close|sma|change_pct", "params": {...}}
          | {"kind": "const",  "value": 30}
```
- `cross_above(a,b)` = `a_t > b_t AND a_{t-1} <= b_{t-1}`, `cross_below` 대칭 — 기존 `MovingAverageCrossover` 와 같은 정의.
- 호환 모드 신호 조립: 기본 HOLD, 진입 → BUY, 청산 → SELL(둘 다면 SELL).

### 3.3 저장 형식

```
datahub/catalog.yaml                         # 커밋
state/locks/data_{daily_minute,minute_al,tick_al}.lock, datahub_ledger.lock
state/datahub/ledger-YYYY-MM.jsonl           # 쓰기 장부
state/datahub/overrides.json                 # 일정·알림 켜기/끄기·시각
state/datahub/alerts_sent.json               # 하루 1회 중복 방지
state/datahub/archive_state.json             # 종목별 마지막 보관 병합 시각
state/datahub/tick_attempts.json             # 체결 (종목, 날짜)별 실패한 밤 수 + 포기 목록
state/datahub/owned/<schedule_id>            # (후속) 이관 표식
state/jobs/<job_id>/job.json · progress.json · log.txt · cancel.flag
data/stocks/minute_al_archive/{code}.parquet
results/studio/<run_id>/spec.json · meta.json · summary.json · trades.parquet · equity.parquet · grid.parquet · folds.json
results/studio/holdout_ledger.json
presets/studio/*.json                        # 커밋 (state/ 는 git 복구 불가 교훈)
```

- ID: `YYYYMMDD-HHMMSS-xxxxxx`. API 는 `^\d{8}-\d{6}-[0-9a-f]{6}$` 외 거부.
- `job.json` 은 worker·dispatcher 만, `cancel.flag` 는 API 만 쓴다(쓰는 주체 분리).

```jsonc
// job.json
{"job_id": "...", "kind": "collect_daily", "group": "collect|local|compute",
 "handler": "datahub.jobs:collect_daily",       // worker 가 import — 허용 접두사 datahub.jobs: / studio.application.jobs:
 "status": "scheduled|queued|running|succeeded|failed|cancelled",
 "scheduled_at": null, "created_at": "...", "started_at": null, "finished_at": null,
 "payload": {...}, "run_id": null, "lock": "daily_minute|minute_al|tick_al|null",
 "pid": null, "pid_create_time": null, "exit_code": null, "error": null, "trigger": "user|schedule"}
```

- `meta.json`(실행 재현 정보): engine_version, git_commit·dirty, **data 기준**(카탈로그 데이터셋별 최신일·종목 수 — `datahub.status` 에서), spec_hash, structure_hash, warnings, memo, starred.
- `trades.parquet` 열: code, name, sector, theme_group, entry_ts, entry_price, exit_ts, exit_price, qty, gross_pnl, commission, tax, slippage_cost, net_pnl, net_pct, exit_reason, bars_held, mfe_pct, mae_pct (+틱 정밀화 열).
- `equity.parquet` 열: ts, cash, positions_value, equity, drawdown_pct, n_positions, benchmark_kospi, benchmark_kosdaq.

### 3.4 Entity Relationships

```
Dataset 1 ── 1 Lock(자원) ── N LedgerRun ── N LedgerEvent
Dataset N ── N Schedule(주인: hub/watchdog/8765/sophie)
Job 1 ── 0..1 LedgerRun (수집 잡)  ·  Job 1 ── 0..1 Run (백테스트 잡)
Run 1 ── N Trade / N EquityPoint · Run(optimize) 1 ── N GridRow · Run(walkforward) 1 ── N Fold
Preset ─(복제)→ Spec ─(실행)→ Run · structure_hash 1 ── N HoldoutOpening
```

### 3.5 체결 규칙 (`studio/domain/engine/fills.py`) — 일반 모드

| 순서 | 처리 | 체결가 |
|:---:|------|--------|
| 1 | 전 봉 종가의 **청산 신호** 실행 | 봉 t 시가 − 슬리피지 |
| 2 | 전 봉 종가의 **진입 후보** 실행(1에서 빈 슬롯·현금 재사용), 순위 순 | 봉 t 시가 + 슬리피지 |
| 3 | 보유 종목 **갭**: 시가 ≤ 손절선 → 시가 손절 / 시가 ≥ 익절선 → 시가 익절 | 시가 ∓ 슬리피지 |
| 4 | **봉 안**: 저가 ≤ 손절·트레일링선, 고가 ≥ 익절선. 둘 다면 `same_bar_policy`(기본 손절 먼저). 이번 시가에 산 종목도 판정 | 선 ∓ 슬리피지 |
| 5 | 트레일링 고점 갱신 — 판정 **뒤에** | — |
| 6 | 보유 봉 수 ≥ `max_holding_bars` → 종가 청산 | 종가 − 슬리피지 |
| 7 | (분봉·틱) `eod_time` 봉 → 종가 청산 | 종가 − 슬리피지 |
| 8 | 봉 t 종가 기준 신호 → 다음 봉 대기 | — |
| 9 | 봉 t 종가 평가(MTM) | — |

- 상하한가: 체결 예정 가격이 전일 종가 ±30%(여유 0.5%) 근처면 체결 안 됨 — 매수는 그날 취소(`skipped.upper_limit`), 매도는 다음 봉으로.
- 슬리피지: `rate` / `ticks` / `max_rate_tick`(기본, `round_trip_cost_pct` 와 같은 규칙).
- 비용: 수수료 매수·매도 각각, 세금 매도만.
- 거래량 한도: 수량 ≤ **전 봉(신호 봉) 거래량** × `volume_cap_pct`%. 체결 봉 자신의 거래량은 시가 시점에 모르는 값이라 쓰지 않는다(미래참조 — 2026-09-25 backtest-agent 지적으로 정정). 전 봉 거래량이 결측이거나 0이면(신규 상장·거래정지 직후) 진입을 막는다(`skipped.volume_cap`) — 알 수 없는 유동성으로 들어가지 않는다.
- 사이징: `equal_slot_fixed`(초기자금/최대보유, 복리 없음) · `equal_slot_compound`(전 봉 평가금/최대보유) · `fixed_amount` · `risk_pct`(평가금×위험%÷(진입가−손절선)) — 전부 `max_weight_pct`·가용 현금으로 상한.
- 데이터 끝: 종목 데이터가 먼저 끝나면 마지막 종가로 청산(`end_of_data`) + 경고. 이월할 다음 봉이 없으니 잠김은 무시한다.

**구현에서 확정한 세부 규칙** (module-3, `backtest-agent_20260925-1800_studio_engine.md` — lead 검토 수용)

| 항목 | 규칙 |
|------|------|
| 보유 봉 수 | 진입 봉을 1 로 센다 — `max_holding_bars=20` 이면 진입 봉 포함 20번째 봉 종가 청산 |
| 같은 봉 진입·청산 신호 | 청산 우선, 그 봉 재진입 없음. 보유 중 종목의 진입 신호는 무시 |
| 현금 부족 | 수량을 줄여 진입(수수료까지 감당되는 수량), 1주도 못 사면 `skipped.cash` |
| 손익 정의 | `gross_pnl` = (체결가 차) × 수량(슬리피지 반영 후, 기존과 같은 정의), `net = gross − 수수료 − 세금` |
| MFE/MAE | 청산 봉 고저까지 포함(봉 안 순서 미상이라 약간 과대) — 호환 모드는 None |
| 상하한가 잠김 | 매수·매도 모두 상·하한 양쪽 대칭 판정(기존과 같은 보수적 규칙). 실제로는 상한가 잠김 매도는 쉬운 편 — 알려진 차이 |
| 호가단위 | 손절선·체결가를 호가에 맞춰 반올림하지 않음 — 고가 종목에서 ±1호가 차이(알려진 한계) |
| 표준 지표 정의 | 소르티노 하방편차 목표 0, 회전율 = 편도 합 ÷ 2 ÷ 평균 평가금 — 기존 연구 수치와 이어지는 지표 아님 |
| 진입점 | `run_portfolio(panel, entries, exits, costs, exit_rules, fill_rules, portfolio)`, 호환 `run_compat(candles, signals, …)` · 규칙 dataclass: `ExitRules`·`FillRules`(`engine/fills.py`), `PortfolioRules`(`engine/portfolio.py`), `CostModel`(`costs.py`) |

### 3.6 호환 모드 (`studio/domain/engine/compat.py`) — 기존 `simulator.run` 재현

| # | 규칙 |
|---|------|
| 1 | 체결가 = 다음 봉 시가 × (1 ± slippage_rate) — 비율만 |
| 2 | 수량 = initial_capital // 진입가 — 복리 없음, 현금 제약 없음 |
| 3 | pnl = (청산가−진입가)×수량 − (매수수수료+매도수수료+세금), pnl_pct = pnl/(진입가×수량) |
| 4 | 체결 예정 봉 시가가 상하한가 근처면 보류, 대기 신호 유지 |
| 5 | 매 봉 새 BUY/SELL 이 대기 신호를 덮어씀. 잠기지 않은 봉에서는 적용 여부와 무관하게 소거 |
| 6 | `force_eod_close`: 그날 마지막 봉에 보유 중이면 종가 × (1−slippage) 청산(잠김이면 보류), 그 봉 새 신호 무시 |
| 7 | 끝까지 보유 중인 거래는 미청산으로 남고 지표 집계 제외 |
| 8 | 전일 종가 = candles 안 일자별 마지막 종가의 shift(1), 첫날 NaN → 잠김 판정 안 함 |
| 9 | 손절·익절·트레일링·보유기간·거래량 한도·사이징 옵션 비활성 |

`legacy_slots`: 종목별 호환 모드 거래 → `portfolio_sim.simulate_slot_portfolio` 규칙(진입 시각 순, 빈 슬롯 없으면 건너뜀, 슬롯 고정)으로 배정(패리티 P3). 기존 함수는 `sort_values("entry_time")`(동률 순서 비보장)라 같은 호출을 그대로 써서 맞춘다 — 같은 날 후보가 슬롯보다 많으면 기존 결과도 pandas 정렬에 좌우된다는 뜻이다. 일반 모드는 `rank_by` 안정 정렬로 결정적.

- **슬리피지 칸 정의가 두 모드에서 다르다**: 기존 `Trade.slippage` 는 진입 쪽만 기록한 정보용 칸(청산 슬리피지는 체결가에만 반영)이고, 호환 모드는 그 값을 그대로 재현한다. 일반 모드 `slippage_cost` 는 진입·청산 양쪽 합(기준가 대비). 손익 숫자에는 차이 없음.

### 3.7 지표 카탈로그 (`studio/domain/conditions/catalog.py`)

| 이름 | 파라미터 | 뜻 | 모드 | 시점 |
|------|---------|----|------|------|
| `sma`, `ema` | src, n | 이동평균 | 전부 | t 포함 |
| `rsi` | n | 기존 `compute_rsi` 와 같은 단순평균 RSI(손실 0 → 100) | 전부 | t 포함 |
| `rsi_wilder` | n | 와일더 RSI | 전부 | t 포함 |
| `highest`, `lowest` | src, n, include_current=false | N봉 최고/최저(기본 t 제외) | 전부 | 기본 t 제외 |
| `change_pct` | n | N봉 전 대비 등락률 | 전부 | t 포함 |
| `gap_pct` | — | 시가/전일 종가 − 1 | 일봉·분봉 | 당일 시가 |
| `atr` | n | 평균 진폭 | 전부 | t 포함 |
| `bb_upper`, `bb_lower` | n, k | 볼린저 밴드 | 전부 | t 포함 |
| `vol_ratio` | n | 거래량 / 직전 N봉 평균 | 전부 | 평균 t 제외 |
| `value_rank` | lookback | 그날 거래대금 순위 | 일봉 | t 종가 |
| `day_change_pct` | — | 전일 종가 대비 등락률 | 분봉·틱 | 전일 종가 D−1 |
| `time` | — | 봉 끝 시각 HHMM | 분봉 | — |
| `cum_value` | — | 당일 누적 거래대금 | 분봉 | t 까지 |
| `vwap` | — | 당일 VWAP | 분봉 | t 까지 |
| 틱 카탈로그 | breakout_min · value_speed(w, ratio) · buy_ratio(w, min) · time_from/to | N분 고점 돌파(`[t−w,t)`, t 제외) · 체결대금 속도(인과적 누적 평균 대비) · 틱룰 매수 비중 | 틱 | s 까지, 진입은 s **다음** 체결 |

**지표 계산 규칙** (module-3 판정, 2026-09-25)
- **롤링은 종목 자기 거래일(행이 있는 날)만 이어서 계산한다** — 기존 전략(종목별 시계열)과 같은 의미. 넓은 표에서 행 없는 날은 NaN 인데 그대로 굴리면 그 뒤 n봉이 통째로 사라진다(실측: 활동 구간 안 행 없는 날 134종목·1,981칸). 빈칸 있는 열만 `dropna` 경로로 계산하고, 빈칸 날 자체는 NaN(신호 없음). 거래량 0 인 날(행은 있음)은 정상 행.
- `atr` = TR 단순평균, `bb_*` = 모표준편차(ddof=0), `value_rank` = 최근 lookback일 평균 거래대금 내림차순 순위.
- 기존 `volume >= 평균×1.5` 와 비트 단위로 맞출 때는 `vol_ratio`(나눗셈) 대신 1봉 미룬 `sma(volume,20) × 1.5` 비교로 표현한다(경계값 차이).
- 기간이 시장 필터 지수(`001/101.csv` 2021-07-26~)·일봉 범위 밖이면 `spec.validate_against(spec, ranges)` 가 문제로 돌려준다 — 조용히 진입 0건이 되지 않게.
- **분봉 롤링 지표(sma·highest 등)는 날마다 리셋하지 않는다**(module-6 판정 2026-09-25) — 기존 분봉 전략·차트처럼 전날 봉을 포함한다(풀이 문장에 명시). 하루 단위 값은 `cum_value`·`vwap`·`day_change_pct`·`gap_pct`·`time`. 분봉 `value` 도 종가×거래량 근사(보관소에 거래대금 열 없음) — `vwap` 은 봉 종가 가중이며 결과 경고 "거래대금 근사"에 분봉 포함. 15:30 종가 단일가 봉은 끝 라벨 15:35(5분봉) — `time<=1530` 조건에서 자동 제외되지만 거래량은 누적 지표와 다음 날 창에 들어간다(의도). 체결 없는 분(NaN)은 건너뛰어 창 = 봉 개수(키움 분봉이 체결 있는 분만 주는 것과 같은 의미). 틱 쿨다운은 조건 쪽(P5 가 `detect_breakouts` 와 같으려면 신호 정의 안에 있어야 한다), 창은 `[s−w, s)`.

**시점 규칙**: 일봉 = t 종가까지 → t+1 시가 체결. 분봉 = 봉 t 까지, 일봉 지표는 D−1, 유니버스 순위는 D−1. 틱 = 초 s 까지, 진입은 s 보다 엄격히 뒤. **데이터 출처**: 일봉 `daily`(KRX, 거래대금 근사), 분봉 **기본 `minute_al_archive`(통합·NXT 포함 — 2026-09-01 사용자 규칙 "통합만")**, **선택** `minute_krx`(`data/stocks/minute`, 1,055종목·2025-07~, NXT 체결 제외 — 거래량 통합의 0.62~0.94배) — Spec `intraday.source: al|krx`(기본 al), KRX 로 돈 결과는 "KRX 기준"을 크게 표시하고 통합 결과와 절대값을 섞어 비교하지 않는다. 틱 `tick_al`(통합) — 모두 카탈로그 경로. (경위: 09-25 lead 가 과거 재수집을 지시했다가 사용자 지적으로 취소 → KRX 기본으로 바꿨으나 09-01 규칙과 충돌 → 09-26 사용자 결정 "통합 기본 + KRX 선택". 분봉 커버리지: 최근 3개월 기대 쌍 중 통합 42%·KRX 99.9%)

### 3.8 검증·견고성

| 항목 | 정의 |
|------|------|
| 거래일 달력 | `datahub.calendar` (분할·워크포워드는 거래일 수 기준) |
| IS/OOS | 후보 선택은 IS 로만 |
| 홀드아웃 | 기본 마지막 20% 거래일, 최적화 범위에서 제외. `holdout_check` 잡으로만 열고 `structure_hash`·`family_hash` 둘 다 기록 — **횟수·경고는 `family_hash`(골격: 숫자·종목 지정·비용·기간 리터럴과 청산 규칙 켜고 끄기까지 뺀 해시) 기준**. 리터럴을 고쳐(손절 7→8%) 횟수를 초기화하는 엿보기를 막는다. 막지는 않고 경고만(module-5 판정 2026-09-25) |
| 그리드 | 조합 ≤ 5,000(500 초과 경고), 병렬 = 정책(§2.4.6) |
| 목표 지표 | sharpe / cagr / calmar / profit_factor / expectancy + 최소 거래 수(30) |
| 이웃 안정성 | 한 칸 옆 조합 목표값 중앙값 ÷ 최고값, < 0.5 경고 |
| 워크포워드 | 학습·검증·이동(거래일), 롤링/누적, 검증 구간만 이은 곡선, WFE = 이은 검증 곡선 연환산 수익률 ÷ 폴드별 IS 연환산 수익률 평균(평균 ≤0 이면 없음). 조합마다 최적화 구간을 **한 번** 돌려 곡선을 IS/OOS/폴드로 자른다 — 경계에 걸친 보유는 이어진다(구간마다 새로 시작해 인위적 청산을 만들지 않음, `equal_slot_compound` 는 경로 의존) |
| 비용 민감도 | 비용 × {0, 0.5, 1, 1.5, 2, 3} → 순수익, 손익분기 배수 |
| 몬테카를로 | 거래 순수익률 복원추출 1,000회(시드 42) → 최종 수익·MDD 5/50/95%, MDD>30% 확률(겹친 보유 무시 근사 표시) |
| 집중도 | 기여 상위 1·2·3 종목/날짜 제외 순손익 + 부호 반전 |
| 사전 판정 기준 | 실행 전 입력 → 결과에 통과/기각, 실행 뒤 수정 불가 |

**표준 지표**(일별 평가): 총수익, CAGR, MDD·기간, 변동성, 샤프, 소르티노, 칼마, 승률, 손익비, 평균 이익·손실, 기대값, 최대 연속 손실, 평균 보유, 노출, 회전율, 비용 내역, 놓친 신호, 벤치마크·초과수익·베타. **기존 CLI 기준 지표**(패리티 P2): total_return_pct, cagr_pct, win_rate_pct, max_drawdown_pct(실현), sharpe_ratio(거래 단위), num_trades.

---

## 4. API Specification

성공 `{"data": ...}`, 오류 `{"error": {...}}`(§6). 127.0.0.1:8780 전용.

### 4.1 Endpoint List

**데이터 허브 (`datahub/api.py`, prefix `/api/data`)**

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/data/overview` | 데이터셋 전부 + 신선도 판정 + 마지막 쓰기 + 잠금 + 지금 시간대 + 활성 알림 |
| GET | `/api/data/datasets/{id}` | 상세: 통계·쓰는/읽는 주체·최근 장부 20건·일정 |
| GET | `/api/data/activity` | 지금 쓰고 있는 작업 전부(허브 잡 + 장부 진행 중 run + 외부 표식) |
| GET | `/api/data/ledger?lock=&writer=&since=&limit=100` | 쓰기 장부 |
| GET | `/api/data/locks` | 잠금 3종 소유자 |
| GET | `/api/data/policy?kind=&mode=&codes=` | 지금 이 수집이 가능한지(allow_now / needs_confirm / schedule_only, 제안 시각, 이유) |
| GET | `/api/data/stale?dataset=&sophie_only=` | 밀린 종목(소피증권 유니버스 표시) |
| GET | `/api/data/gaps?dataset=daily&days=120` | 날짜별 데이터 있는 종목 비율 |
| GET | `/api/data/quality?dataset=daily` | 품질 문제 |
| GET | `/api/data/tick-window` | 체결 조회창(20거래일) 날짜별 상태 |
| GET | `/api/data/archive` | 보관소 커버리지(종목 수·기간·캐시 대비 누락) |
| GET | `/api/data/schedules` | 일정 전부(주인·마지막·결과·다음·놓침) |
| PATCH | `/api/data/schedules/{id}` | 허브 소유 일정 켜기/끄기·시각 (외부는 409 NOT_HUB_OWNED) |
| GET/PATCH | `/api/data/alerts` · `/api/data/alerts/{id}` | 알림 규칙·최근 발송 |
| GET | `/api/data/sophie` | 소피증권 연계 상태 |
| POST | `/api/data/jobs/collect-daily` | 일봉 최신화 |
| POST | `/api/data/jobs/collect-ticks` | 체결 수집 — `catch_up`(빠진 것 전부, 허브 계산) / `range`(기간 지정) |
| POST | `/api/data/tick-window/retry` | "수동 확인 필요" 쌍을 자동 재시도로 되돌림 |
| POST | `/api/data/jobs/collect-minute-al` | 통합 분봉 갱신(4모드) |
| POST | `/api/data/jobs/archive-minute-al` | 보관소 병합(로컬, API 호출 없음) |

**작업 공통 (`studio/api/routes/jobs.py`)**

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/jobs?status=&kind=&group=&limit=50` | 작업 목록 |
| GET | `/api/jobs/{job_id}` | 상태 + 진행률(수집은 장부 진행 기록에서) |
| GET | `/api/jobs/{job_id}/log?offset=0` | 로그 이어받기(비밀값 가림) |
| POST | `/api/jobs/{job_id}/cancel` | 취소(예약 포함) |

**백테스트 스튜디오**

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/meta/status` | 상단 상태 바(허브 요약 + 실행 중 작업 수) |
| GET | `/api/meta/indicators` · `/api/meta/strategies` | 지표 카탈로그 · 기존 전략 8종 |
| GET | `/api/stocks?q=&limit=20` · `/api/stocks/{code}/bars?interval=&start&end` | 종목 검색 · 차트 봉 |
| POST | `/api/jobs/backtest` · `/optimize` · `/walkforward` · `/holdout-check` | 백테스트류 |
| GET | `/api/runs` · `/api/runs/{id}` · `/equity` · `/trades` · `/grid` · `/folds` · `/export/trades.csv` | 결과 |
| PATCH/DELETE | `/api/runs/{id}` | 이름·메모·별표 / 삭제(실행 결과만 — 데이터 아님) |
| POST | `/api/runs/compare` | 2~5개 비교 |
| POST | `/api/conditions/validate` · `/api/conditions/preview` | 명세 검증·풀이 · 오늘 조건 맞는 종목 |
| GET/PUT/DELETE | `/api/presets` · `/api/presets/{name}` | 프리셋 |

### 4.2 Detailed Specification

#### `GET /api/data/overview`

```jsonc
{"data": {
  "now": {"ts": "2026-09-25T10:12:00", "window": "market|sophie_live|night|holiday",
          "sophie_hours": {"connect_from": "08:20", "open": "09:00", "close": "15:30", "connect_to": "20:10"}},
  "datasets": [
    {"id": "daily", "label": "일봉", "basis": "KRX", "verdict": "good|warn|bad",
     "n_codes": 2577, "reference_date": "2026-09-23", "expected_date": "2026-09-23", "stale_count": 376,
     "sophie_stale_count": 0, "last_write": {"ts": "...", "writer": "backfill_universe", "source": "야간 갱신", "ok": true},
     "lock": {"resource": "daily_minute", "held": false}, "retention": "keep"},
    {"id": "minute_al", "verdict": "bad", "last_date_mode": "2026-09-04", "age_days": 21, "behind_share": 0.83, ...},
    {"id": "minute_al_archive", "verdict": "bad", "missing_vs_cache": 2041, ...},
    {"id": "tick_al", "verdict": "good", "window_missing": 0, "min_days_left": null, ...}],
  "activity": [{"source": "워치독(야간 갱신)", "writer": "backfill_universe", "done": 820, "total": 2016, "since": "..."}],
  "alerts_active": [{"id": "archive_behind", "message": "통합 분봉 보관소가 비어 있음 — 첫 전체 보관 필요"}]}}
```

#### `GET /api/data/policy?kind=collect_minute_al&mode=sophie_baseline`

```json
{"data": {"weight": "heavy", "window": "market", "decision": "schedule_only",
  "suggest_at": "2026-09-25T20:10:00", "reason": "소피증권 정규장 시간 — 대량 수집은 장 마감 뒤(20:10) 예약만 됩니다",
  "warnings": ["오늘 통합 분봉은 NXT 마감(20:00) 전이면 잘립니다"]}}
```
`decision`: `allow_now` / `needs_confirm` / `schedule_only`.

#### `POST /api/data/jobs/collect-minute-al`

**Request**
```json
{"mode": "sophie_baseline", "codes": [], "days": null, "when": "scheduled", "scheduled_at": "2026-09-25T20:10:00", "confirm": false}
```
- `mode`: `sophie_baseline` | `all_cached` | `codes`(1~500) | `deep_archive`(P4, 1~300, `days` 20~250).
- `when`: `now` | `scheduled`. 정책이 `schedule_only` 인데 `now` → 422 SOPHIE_MARKET_HOURS. `needs_confirm` 인데 `confirm=false` → 422 SOPHIE_LIVE_CONFIRM.

**Response 202** `{"data": {"job_id": "...", "status": "scheduled", "scheduled_at": "..."}}`

**Errors**: 400 VALIDATION_ERROR / 409 LOCKED(`minute_al` 소유자) / 409 MINUTE_REFRESH_RUNNING / 409 COLLECT_BUSY / 422 SOPHIE_MARKET_HOURS · SOPHIE_LIVE_CONFIRM

#### `POST /api/data/jobs/collect-daily`

```json
{"mode": "stale", "codes": [], "when": "now", "scheduled_at": null, "confirm": false}
```
- `stale` → `python backfill_universe.py` / `all` → `--all` / `codes` → `--codes=A,B`(신규 종목은 5년치).
- 코드 형식 `^[0-9A-Z]{6}$`. 오류는 위와 같은 체계(LOCKED 자원 = `daily_minute`).

#### `POST /api/data/jobs/collect-ticks`

```jsonc
{"mode": "catch_up", "when": "now", "confirm": false}                        // 빠진 것 전부 — 야간 회차와 같은 계획(§2.4.11)
{"mode": "range", "start": "2026-09-28", "end": "2026-09-28", "universe": "default", "codes": [],
 "concurrency": 4, "when": "scheduled", "scheduled_at": "2026-09-28T20:15:00"}
```
- `catch_up`: 허브가 빠진 쌍·범위·종목 순서를 계산. 빠진 게 없으면 200 `{"data": {"nothing_to_do": true}}`.
- `range`: 날짜는 조회창 안(밖이면 422 OUT_OF_TICK_WINDOW), `concurrency` 1~6.
- 명령: `python tick_collect_804_828_al.py --start S --end E --concurrency C --batch-key --codes @<잡 폴더>/codes.txt --stop-at <야간 구간 끝>` → 이어서 `tick_compact_daemon.py --once`.

#### `POST /api/data/tick-window/retry`

`{"pairs": [{"code": "386380", "date": "2026-09-01"}]}` 또는 `{"pairs": "all"}` → 포기 목록에서 빼고 시도 횟수 0 으로. 다음 회차(또는 `catch_up`)가 다시 받는다.

#### `GET /api/data/tick-window`

```json
{"data": {"window_days": 20, "universe": "날짜별 거래대금 상위 35 합집합(초대형주 제외)",
  "dates": [{"date": "2026-08-27", "status": "collected|partial|missing", "collected_codes": 150, "expected_codes": 150, "days_left": 1}],
  "auto": {"schedule": "tick_nightly", "enabled": true, "next_run": "2026-09-25T20:15:00",
           "last_night": {"started": "...", "finished": "...", "attempts": 1, "collected_pairs": 150, "remaining_pairs": 0, "deferred": 0},
           "given_up": [{"code": "386380", "date": "2026-09-01", "attempts": 3}]},
  "note": "키움 체결 조회창은 약 20거래일 — 밖으로 밀려난 날짜는 다시 받을 수 없음"}}
```

#### `GET /api/data/sophie`

```jsonc
{"data": {
  "engine": {"up": true, "healthz": 401, "pid": 37688, "started_at": "2026-09-25T00:05:25", "stale_day": false},
  "hours": {"connect_from": "08:20", "open": "09:00", "close": "15:30", "connect_to": "20:10", "source": "kospi-theme-engine/config.yaml"},
  "minute_refresh": {"running": false, "last_started": "2026-09-19T19:46", "last_finished": "2026-09-19T21:13",
                     "last_result": "완료 · 실패 13종목 · 보유 2041종목", "next_due": "2026-10-03 (토) 09:00 이후"},
  "baseline": {"data_updated": "2026-09-23T16:55", "dist_updated": "2026-09-23T16:55", "in_sync": true,
               "applies": "다음 엔진 재기동부터"},
  "universe_daily": {"n_codes": 2158, "stale_count": 0},
  "restart": {"last_midnight": "2026-09-07T00:05:25", "days_since": 18, "last_rebuild": "..."},
  "contract": ["소피증권 데이터는 소피증권 스크립트로만 씀", "..."]}}
```

#### `GET /api/data/schedules`

```json
{"data": [{"id": "daily_report", "owner": "watchdog", "when": "평일 16:00 이후 1회",
  "last_started": "...", "last_finished": "...", "last_ok": true, "next_expected": "...", "missed": false, "editable": false},
  {"id": "tick_nightly", "owner": "hub", "when": "매일 20:15 (+재시도)", "enabled": true, "editable": true,
   "runs": [{"job_id": "...", "started": "...", "result": "빠진 150쌍 중 150 수집", "remaining": 0}]}]}
```

#### `POST /api/jobs/backtest`

Request: Spec(§3.2). Response 202 `{"data": {"job_id": "...", "run_id": "..."}}`. Errors: 400 VALIDATION_ERROR(`details.fieldErrors`) / 422 SPEC_INVALID. 한도 초과는 대기열(`queued`).

#### `GET /api/jobs/{job_id}`

```json
{"data": {"job_id": "...", "kind": "collect_daily", "group": "collect", "status": "running",
  "scheduled_at": null, "created_at": "...", "started_at": "...", "finished_at": null,
  "progress": {"pct": 42.0, "stage": "수집", "message": "[820/2016] 005930", "eta_sec": 3600, "paused": false, "waiting_lock": null},
  "ledger_run": "b3f1…", "run_id": null, "error": null}}
```
- `waiting_lock`: 관문이 잠금을 기다리는 중이면 소유자 정보.

#### `GET /api/jobs/{job_id}/log?offset=N`

`{"data": {"text": "...", "next_offset": 20480, "eof": false}}` — `.env` 값·`Bearer` 토큰 `****`.

#### `POST /api/conditions/preview`

Request `{"spec": Spec, "limit": 50}` → 최신 거래일 기준 진입 조건 만족 종목(코드·이름·종가·등락률·거래대금·피연산자 값).

#### `GET /api/runs/{run_id}`

```jsonc
{"data": {"meta": {...}, "spec": {...},
  "summary": {"metrics": {...}, "legacy_metrics": {...}, "benchmark": {...}, "exit_reasons": {...},
              "costs": {...}, "skipped": {...}, "monthly": [...], "yearly": [...],
              "by_sector": [...], "by_theme_group": [...],
              "robustness": {"cost_sensitivity": [...], "breakeven_cost_mult": 1.4, "monte_carlo": {...}, "concentration": {...}},
              "criteria": [...], "tick_refine": null},
  "warnings": [...]}}
```

---

## 5. UI/UX Design

### 5.1 Screen Layout

```
┌────────────┬────────────────────────────────────────────────────────────────────┐
│ 데이터 허브 │ 상태 바: 지금 = 정규장(소피증권 가동) · 일봉 09-23 좋음 · 작업 2 · 알림 1 · 🌙 │
│ 백테스트    ├────────────────────────────────────────────────────────────────────┤
│ 최적화      │   페이지 본문 — 넓은 화면 기준 2~3단, 정보를 접지 않는다                │
│ 실행 기록   │                                                                    │
└────────────┴────────────────────────────────────────────────────────────────────┘
```

### 5.2 User Flow

```
데이터 허브(개요: 무엇이 밀렸나·곧 사라지나·누가 쓰고 있나)
  → 수집(지금/예약 — 정책이 버튼을 바꿔 줌) → 활동·장부에서 진행 확인
  → 백테스트(조건 조립 → 오늘 맞는 종목 → 실행) → 결과 → 수정·재실행 → 비교
  → 최적화/워크포워드(사전 판정 기준 → 실행) → 홀드아웃 열기(한 번)
```

### 5.3 Component List

| Component | Location | Responsibility |
|-----------|----------|----------------|
| AppShell, StatusBar | `frontend/src/components/layout/` | 메뉴·상태 바(시간대·기준일·작업·알림)·다크 모드 |
| EChart + 차트들 | `components/charts/` | echarts 래퍼, 캔들·곡선·히트맵·막대 |
| DatasetCards, NowWindowBanner, ActivityList, AlertList | `components/hub/overview/` | 허브 개요 |
| CollectDailyPanel, CollectTicksPanel(TickWindowCalendar), CollectMinuteAlPanel, PolicyButton, JobTable, LogViewer | `components/hub/collect/` | 수집 |
| ScheduleTable | `components/hub/schedules/` | 일정 |
| LedgerTable | `components/hub/ledger/` | 장부 |
| StaleTable, QualityTable, GapBars, ArchiveCoverage | `components/hub/quality/` | 품질 |
| SophiePanel | `components/hub/sophie/` | 소피증권 연계 |
| SpecForm … SpecNarration (v0.1 과 같음) | `components/builder/` | 조건 조립 |
| ResultHeader … CriteriaTable | `components/results/` | 결과 |
| ParamRangeEditor … HoldoutPanel | `components/optimize/` | 최적화 |
| HubPage, BacktestPage, ResultPage, OptimizePage, RunsPage, ComparePage | `frontend/src/pages/` | 페이지 |

### 5.4 Page UI Checklist

#### 공통

- [ ] 메뉴 4개: 데이터 허브 / 백테스트 / 최적화 / 실행 기록
- [ ] 상태 바: 지금 시간대(정규장·소피증권 가동·야간·휴장), 일봉 기준일+판정 색, 실행 중 작업 수, 활성 알림 수, 다크 모드
- [ ] HashRouter: `#/hub/{overview,collect,schedules,ledger,quality,sophie}`, `#/backtest`, `#/results/:runId`, `#/optimize`, `#/runs`, `#/compare?ids=`

#### 데이터 허브 — 개요 탭

- [ ] 시간대 배너: 지금 구간 + "대량 수집: 가능 / 확인 필요 / 20:10 예약만" + 소피증권 운영 시간(설정 파일 출처 표기)
- [ ] 데이터셋 카드 11개: 이름, 기준(KRX/통합/파생/참조), 판정 색, 종목 수, 최신일(기준일·기대일), 밀린 수, **소피증권 유니버스 밀린 수**, 마지막 쓰기(누가·언제·결과), 잠금 상태, 보관 규칙(영구·덮어씀 등 배지)
- [ ] 통합 분봉 캐시 카드: "소피증권 기준선용 20거래일 창 — 갱신 때 덮어씀" 문구 + 보관소 카드로 연결
- [ ] 통합 체결 카드: 조회창 빠진 쌍 수, 가장 먼저 사라질 날짜(남은 거래일), 자동 수집 켜짐·다음 실행
- [ ] 일봉 카드: 아침 따라잡기 결과(돌았으면 받은 수·못 받은 수)
- [ ] 지금 쓰는 작업 목록: 출처(허브·야간 갱신·8765·소피증권·수동), 쓰는 데이터, 진행률, 시작 시각
- [ ] 활성 알림 목록: 규칙 이름, 내용, 처음 감지 시각

#### 데이터 허브 — 수집 탭

- [ ] 일봉 최신화 패널: 모드 3개(밀린 종목만 / 전체 겹쳐받기 / 종목 지정 + 검색 다중 선택), 대상 수, 정책 버튼(지금 / 확인 후 / 예약 + 시각), "16시 전에는 어제까지가 최신" 안내
- [ ] 체결 수집 패널: 조회창 달력(수집됨 초록 · 일부 주황 · 미수집 빨강 · 소실 임박(≤3거래일) 굵은 테두리), [빠진 것 지금 받기](catch_up, 정책 버튼), 기간 지정 수집(창 밖 비활성·대상 기본 상위 35 합집합/종목 지정·동시성 1~6 기본 4), 정규장 자동 일시정지 안내
- [ ] 체결 자동 수집 줄: 켜짐/꺼짐, 다음 실행 시각, 지난밤 결과(받은 쌍 · 남은 쌍 · 미룬 쌍 · 시도 횟수)
- [ ] 수동 확인 필요 목록: 종목, 날짜, 시도 횟수, 남은 거래일, [다시 시도](개별·전체)
- [ ] 통합 분봉 패널: 모드 4개(소피증권 기준선 갱신(권장) / 보유 전체 / 종목 지정 / 과거 깊게(보관소만, P4)), 모드별 대상 수·예상 소요·"소피증권 기준선: 갱신됨(다음 재기동부터) / 안 바뀜" 표시, 기준선 갱신 실행 중이면 비활성+사유, 20:00 전 "오늘치 잘림" 안내, 정책 버튼
- [ ] 보관소 패널: [보관 병합 지금 실행](로컬), 마지막 병합 시각, 누락 종목 수
- [ ] 작업 표: 종류, 상태(예약·대기·실행·잠금 대기·완료·실패·취소), 예약 시각, 진행률, 단계, 시작, 경과, 남은 시간, [로그] [취소]
- [ ] 로그 뷰어: 2초 이어받기, 자동 스크롤, 비밀값 가림

#### 데이터 허브 — 일정 탭

- [ ] 일정 표: 이름, 주인(허브 / 워치독 / 8765 / 소피증권), 언제, 마지막 시작·끝·결과, 다음 예정, 놓침 배지(예: 자정 재기동 "18일째 기록 없음")
- [ ] 허브 소유 일정만 켜기/끄기·시각 변경(외부는 잠금 아이콘 + "워치독이 관리")
- [ ] 허브 소유 일정 회차 기록(최근 14회): 시작·끝·계획한 쌍/종목·받은 것·남은 것·미룬 것·결과
- [ ] 알림 규칙 표: 규칙, 켜기/끄기, 마지막 발송

#### 데이터 허브 — 장부 탭

- [ ] 장부 표: 시각, 잠금 자원, 쓴 주체, 출처, 대상 수, 결과(성공·실패·중단됨), 소요 — 필터(자원·출처·기간)
- [ ] 장부 없는 쓰기 목록(감지된 경우): 파일, 수정 시각, 데이터셋

#### 데이터 허브 — 품질 탭

- [ ] 밀린 종목 표: 코드, 이름, 마지막 날짜, 며칠 밀림, **소피증권 유니버스 배지**, 체크 → [선택 종목 받기]
- [ ] 품질 문제 표: 종류 5가지, 종목, 날짜, 값 + 종류별 건수
- [ ] 결측 거래일 막대: 최근 120거래일, 90% 미만 강조
- [ ] 보관소 커버리지: 종목 수, 종목별 기간 분포, 캐시 대비 누락

#### 데이터 허브 — 소피증권 탭

- [ ] 엔진: 가동 여부(헬스체크), 시작 시각, "어제 상태 — 재기동 필요" 경고(거래일에 시작이 오늘 00:00 이전)
- [ ] 운영 시간: connect_from · 정규장 · connect_to (`config.yaml` 출처)
- [ ] 분봉 기준선 갱신: 실행 중 여부, 마지막 시작·끝·결과 줄, 다음 예정(워치독 규칙)
- [ ] 기준 데이터: data·dist 수정 시각, 동기 여부, "다음 재기동부터 적용"
- [ ] 소피증권 유니버스 일봉: 종목 수, 밀린 수(품질 탭 링크)
- [ ] 재기동 기록: 마지막 자정 재기동(며칠 전), 마지막 재빌드
- [ ] 연계 계약 10개 요약(§2.4.9)

#### 백테스트 (BacktestPage)

- [ ] 모드 탭 4개: 일봉 단일 종목 / 일봉 포트폴리오 / 분봉 단타 / 체결(틱)
- [ ] 전략 소스: 조건 조립기 / 기존 전략(8종 + 파라미터 폼) / 프리셋(불러오기·저장·삭제)
- [ ] 종목·유니버스: 단일 = 종목 1개 / 포트폴리오 = 전체·거래대금 상위 N(기본 100)·종목 지정 + 시장(거래소·코스닥) + 제외(스팩 64·우선주 9·초대형주 2)
- [ ] 기간: 시작·종료(데이터 밖 비활성), 데이터 범위(허브 기준일), 홀드아웃 회색
- [ ] 진입·청산 조건 그룹 편집기: AND/OR, 행 추가·삭제·복제, 하위 그룹 1단계
- [ ] 조건 행: 왼쪽(지표·파라미터·며칠 전·배수) / 비교 6종 / 오른쪽(지표·숫자), 숫자 칸 "변수로"
- [ ] 청산 규칙: 손절·익절·트레일링 %, 최대 보유 봉
- [ ] 시장 필터(지수 피연산자)
- [ ] 자금·배분: 초기자금 1,000만, 최대 보유 5, 배분 4종, 종목당 최대 비중, 우선순위(거래대금·등락률·무작위+시드)
- [ ] 비용·체결: 수수료 0.015%, 세금 0.23%, 슬리피지(비율·호가·큰 쪽), 같은 봉 판정, 거래량 한도 10%
- [ ] 호환 모드(단일 종목만): 켜면 손절·익절·사이징·거래량 한도 잠금
- [ ] 분봉 탭: 봉 길이, 전일 거래대금 상위 N(30), 일봉 사전 필터, 장마감 청산 15:20, **통합 분봉 보관소 사용 가능 기간**(허브 보관소 링크)
- [ ] 틱 탭: 진입 방식(분봉+틱 정밀화 / 틱 조건), 틱 조건 4종, 쿨다운, 갭시작(+5%) 제외, 시간 손절, 틱 표본 안내
- [ ] 조건 풀이 문장 패널
- [ ] [오늘 조건 맞는 종목] 표 · [검증] 오류 목록 · [백테스트 실행] 진행 모달(취소) → 결과로 이동

#### 결과 (ResultPage)

- [ ] 헤더: 이름(편집), 모드, 기간, **데이터 기준(허브 기준일)**, 엔진 버전, git 해시, 소요 시간, [재실행] [조건 복제해서 수정] [비교에 추가] [CSV]
- [ ] 경고 배지: 표본 부족, 생존편향, 거래대금 KRX 근사, 분봉 짧은 표본, 틱 표본 수, 데이터가 먼저 끝난 종목 수
- [ ] 지표 카드(접지 않음, §5.5 판정 색) 전부 + 기존 CLI 기준 줄
- [ ] 수익곡선(코스피/코스닥, 로그 축, 확대) · 낙폭 · 월별 히트맵 + 연도 막대 · 수익 분포 · MFE/MAE · 보유기간 vs 수익 · **업종별 · 소피증권 테마 그룹별 성과** · 청산 사유 비율 · 비용 민감도(손익분기 배수)
- [ ] 거래 표(정렬·검색·페이지) → 행 클릭 캔들 서랍(진입·청산·손절·익절선, 앞뒤 30봉)
- [ ] 틱 정밀화 비교(해당 시) · 사전 판정 기준 표(해당 시)

#### 최적화 (OptimizePage)

- [ ] 기준 명세 선택 · 변수 표(최소·최대·간격, 조합 수, 5,000 초과 비활성, 500 초과 경고)
- [ ] 목표 지표, 최소 거래 수, 분할(학습 비율/날짜, 홀드아웃 % 자물쇠), 워크포워드(학습·검증·이동 거래일, 롤링/누적)
- [ ] 사전 판정 기준 편집기(실행 후 잠김)
- [ ] 조합 표 · 2변수 히트맵 · 이웃 안정성 · 검증 구간 성과 카드와 곡선
- [ ] 워크포워드 폴드 표 · 이은 검증 곡선 · WFE · 변수 변화
- [ ] 몬테카를로 분포 · 집중도 표 · 홀드아웃 패널(열기 확인, 이력)

#### 실행 기록 / 비교

- [ ] 표(별표·이름·모드·기간·총수익·CAGR·MDD·샤프·거래 수·메모·생성 시각), 정렬·검색·필터, 인라인 편집
- [ ] 다중 선택 → [비교](2~5) · [삭제](확인 — 실행 결과만)
- [ ] 비교: 곡선 겹치기, 지표 비교 표(최고 강조), 조건 차이 문장

### 5.5 지표 판정 기준 (`frontend/src/lib/verdicts.ts`)

| 지표 | 좋음 | 보통 | 나쁨 |
|------|------|------|------|
| 샤프 | ≥ 1.0 | 0.5 ~ 1.0 | < 0.5 |
| 소르티노 | ≥ 1.5 | 0.75 ~ 1.5 | < 0.75 |
| MDD | ≤ 15% | 15 ~ 30% | > 30% |
| 칼마 | ≥ 1.0 | 0.3 ~ 1.0 | < 0.3 |
| 손익비 | ≥ 1.5 | 1.0 ~ 1.5 | < 1.0 |
| 기대값(거래당, 비용 후) | > 0.3% | 0 ~ 0.3% | ≤ 0 |
| 초과수익(연) | > 0 | — | ≤ 0 |
| 거래 수 | ≥ 100 | 30 ~ 99 | < 30 |
| WFE | ≥ 0.5 | 0.3 ~ 0.5 | < 0.3 |
| 이웃 안정성 | ≥ 0.7 | 0.5 ~ 0.7 | < 0.5 |
| 손익분기 비용 배수 | ≥ 2.0 | 1.0 ~ 2.0 | < 1.0 |

데이터 신선도 판정(좋음·주의·나쁨)은 §2.4.8 이 기준이고 같은 색을 쓴다.

---

## 6. Error Handling

### 6.1 Error Code Definition

| HTTP | code | 원인 | 화면 처리 |
|------|------|------|----------|
| 400 | VALIDATION_ERROR | 요청 형식 — `details.fieldErrors` | 칸 강조 |
| 403 | ORIGIN_FORBIDDEN | 다른 출처의 상태 변경 요청 | 알림 |
| 404 | NOT_FOUND | 없는 잡·실행·프리셋·데이터셋, ID 형식 불일치 | "찾을 수 없음" |
| 409 | LOCKED | 잠금 소유자 살아 있음 — `details` 에 소유자 | 잠금 배너 |
| 409 | COLLECT_BUSY | 허브 수집이 이미 실행 중 | 작업 표로 안내 |
| 409 | MINUTE_REFRESH_RUNNING | 소피증권 분봉 기준선 갱신 실행 중(워치독 포함) | 소피증권 탭 링크 |
| 409 | NOT_HUB_OWNED | 외부 일정 수정 시도 | "워치독이 관리" |
| 409 | JOB_NOT_CANCELLABLE | 끝난 잡 취소 | 알림 |
| 413 | PAYLOAD_TOO_LARGE | 요청 본문 256KB 초과 | 알림 |
| 422 | SOPHIE_MARKET_HOURS | 정규장 대량 수집 → 예약만 | 예약 버튼 강조 |
| 422 | SOPHIE_LIVE_CONFIRM | 소피증권 가동 시간 대량 수집 확인 필요 | 확인 대화상자 |
| 422 | SPEC_INVALID · OUT_OF_TICK_WINDOW · GRID_TOO_LARGE | 이름대로 | 해당 칸 |
| 424 | DATA_MISSING | 필요한 데이터 없음(보관소 비어 있음 등) | 허브 링크 |
| 500 | INTERNAL | 예상 못 한 오류 | "로그 확인" |

- 워커 안 오류: `job.json.error`, traceback 은 `log.txt`.
- 워커가 사라짐: 디스패처가 pid·create_time 로 확인 → failed("프로세스가 중간에 사라짐"), `cancel.flag` 있으면 cancelled. 관문을 쥔 채 죽었으면 장부 run 은 "중단됨", 잠금은 다음 획득자가 회수.

### 6.2 Error Response Format

```json
{"error": {"code": "SOPHIE_MARKET_HOURS", "message": "소피증권 정규장 시간에는 대량 수집을 예약만 할 수 있습니다", "details": {"suggest_at": "2026-09-25T20:10:00"}}}
```

---

## 7. Security Considerations

- [ ] 127.0.0.1 전용 바인딩(코드 고정)
- [ ] 상태 변경 요청은 Origin ≠ Host 면 403(개발 중 Vite 만 `STUDIO_DEV_ORIGIN`)
- [ ] **Host 가 루프백이 아니면 모든 요청 403** — Origin==Host 검사만으로는 DNS 리바인딩(악성 도메인이 127.0.0.1 로 되돌아옴)을 못 막는다. `Sec-Fetch-Site: cross-site` 도 거부. `/docs`·`/openapi.json` 은 끈다(module-2 구현 보완 — lead 실측: 위조 Host 403 · 교차 출처 POST 403 · /docs 404)
- [ ] 로그 가림 범위: `.env` 값 중 6자 이상 전부 + 이름에 KEY·SECRET·TOKEN 이 든 환경변수 + `Bearer` 토큰 — 쓸 때 가리고 읽을 때 한 번 더
- [ ] 워커는 **짧게 사는 launcher 가 띄우고 끝나는 이중 기동**으로 분리한다 — 분리 플래그만으로는 서버 트리 종료(`taskkill /T`) 때 워커도 죽는 것을 실측으로 확인(module-2 보완). G6 "서버 재시작에도 작업 계속"의 조건
- [ ] CORS 없음, 요청 본문 256KB 상한
- [ ] 조건식은 화이트리스트 문법만(`eval`/`exec` 없음), 파라미터 범위 검증
- [ ] 경로 입력 없음: ID 정규식, 프리셋 이름 `^[\w가-힣\- ]{1,40}$`, 종목코드 `^[0-9A-Z]{6}$`, 데이터셋은 카탈로그 id 만
- [ ] 실행 파일 허용 목록: `sys.executable` + {`backfill_universe.py`, `tick_collect_804_828_al.py`, `-m scripts.fetch_minute`(cwd kospi-theme-engine), `-m jobrunner.worker`}, `powershell.exe -NoProfile -ExecutionPolicy Bypass -File kospi-theme-engine\run_minute_refresh.ps1 -Now` — 인자 리스트, 셸 미사용
- [ ] worker 는 `job.json.handler` 를 허용 접두사(`datahub.jobs:`, `studio.application.jobs:`)만 import
- [ ] 수집은 배치 앱키(소피증권 실시간 키 보호), 허브는 키를 읽지도 돌려주지도 않음, 로그는 `.env` 값·`Bearer` 토큰 가림
- [ ] 허브에는 데이터 **삭제 API 가 없다**(보관·병합만). 실행 결과 삭제는 `results/studio` 만
- [ ] 실주문 모듈 import 금지(`kiwoom_client`, `trading_loop`, `order_execution`, `sell_order`) — §9 검사. 수집 스크립트는 별도 프로세스라 허브·스튜디오 import 경로와 무관
- [ ] 워커 BELOW_NORMAL 우선순위(소피증권 실시간 CPU 보호)

---

## 8. Test Plan

### 8.1 Test Scope

| Type | Target | Tool | Phase |
|------|--------|------|-------|
| L0 허브 | 카탈로그·달력·관문·잠금·장부·정책·상태·보관·wait-quiet·일정·알림·소피증권 어댑터 | pytest (`tests/datahub/`) | Do |
| L0 실행기 | 저장·분리 실행·취소·예약·한도·handler 허용 목록 | pytest (`tests/jobrunner/`) | Do |
| L0 엔진 | 체결·비용·조건식·지표·엔진·지표 계산·검증·견고성 | pytest (`tests/studio/domain/`) | Do |
| L0 패리티 | §8.6 | pytest `-m parity` | Do |
| L0 카나리아 | §8.7 | pytest | Do |
| L0 구조 | §9.3 import 규칙 | pytest(AST) | Do |
| L1 API | 상태·응답 모양 | pytest + TestClient, `STUDIO_DATA_ROOT` = 픽스처 | Do |
| L2 UI | 페이지 요소·동작 | Playwright | Do |
| L3 E2E | 여정 | Playwright | Do |

### 8.2 L0 허브 핵심 시나리오

| # | 대상 | 시나리오 | 통과 조건 |
|---|------|---------|----------|
| H1 | 카탈로그 | 실제 `catalog.yaml` 로드 | 모든 lock 존재, 경로 풀림, 11종 |
| H2 | 관문 | 두 프로세스가 같은 자원에 `write()` | 겹치지 않음(구간 비교), 장부 start/end 각 2 |
| H3 | 관문 | 본문 예외 | 장부 end ok=false + 예외 재발생 + 잠금 풀림 |
| H4 | 잠금 | 소유 pid 죽음 | `owner().dead=True`, 다음 획득 즉시 |
| H5 | 정책 | 시계 주입 행렬(정규장·가동·야간·주말·휴장 × 대량·소량) | 표 §2.4.6 그대로 |
| H6 | 달력 | 휴장일 목록 + 지수 날짜 | 추석 연휴 같은 날을 밀림으로 안 봄 |
| H7 | 보관소 | 캐시가 20거래일로 잘린 뒤 병합 | 보관소 행 수 불감소, 같은 분은 나중 값 |
| H8 | 보관소 | `fetch_minute` 가짜 클라이언트로 1종목 | 캐시 교체 + 보관소 합집합 |
| H9 | wait-quiet | 잠금 없음 / 살아 있는 소유자 / 표식 실행 중 / 기한 | 0 즉시 / 대기 / 대기 / 3 반환, **stderr 출력 0바이트** |
| H10 | 상태 | 픽스처 데이터 | 신선도 판정·밀린 수·조회창 상태 기대값 |
| H11 | 장부 밖 쓰기 | 관문 없이 파일 수정 | 감지 목록에 1건 |
| H12 | 소피증권 | BOM 표식·설정·헬스체크(모의) | 시간대·실행 중·엔진 상태 정확 |
| H13 | 일정 | 서버 꺼졌다 켜짐 | 오늘 안 돈 허브 일정 즉시 1회, 꺼진 일정은 안 돔 |
| H14 | 알림 | 같은 규칙 두 번 | 하루 1회만 발송 |
| H15 | 체결 계획 | 빠진 쌍 픽스처 | start=가장 오래된 날, end=가장 최근 날, 종목은 먼저 사라질 날짜가 걸린 것부터, 포기 목록 제외 |
| H16 | 따라잡기 | 가짜 수집기로 하룻밤 통째 건너뜀 | 다음 밤 회차가 그 날짜까지 한 번에 수집 |
| H17 | stop-at | 시각이 지난 뒤 | 새 종목 시작 안 함, 종료코드 0, "미룸" 기록, 다음 회차가 이어받음 |
| H18 | 포기 | 같은 쌍 3일 밤 실패 | 포기 목록 이동·알림 1회, [다시 시도] 후 다시 계획에 포함 |
| H19 | 일봉 아침 | ① 월요일 아침 정상 ② 금요일 밤 야간 갱신 놓침 | ① 아무것도 안 함(달력일 오탐 없음) ② 밀린 종목만·소피증권 유니버스 먼저·`--stop-at 08:10` |
| H20 | 서버 재기동 | 20:15 회차 시각에 서버 꺼짐 | 야간 구간에 켜지면 즉시, 주간에 켜지면 다음 야간 시작에 실행 |
| H21 | 같은 밤 재시도 | 회차가 쌍을 남기고 끝남 | 60분 뒤 재시도, 하룻밤 최대 3회, 미룬 쌍은 재시도 안 함 |

### 8.3 L1: API Test Scenarios

| # | Endpoint | Method | Test Description | Expected Status | Expected Response |
|---|----------|--------|-----------------|:--------------:|-------------------|
| 1 | /api/data/overview | GET | 픽스처 | 200 | datasets 11, 판정 값 |
| 2 | /api/data/policy?kind=collect_minute_al&mode=sophie_baseline | GET | 시계 = 정규장 | 200 | decision=schedule_only, suggest_at=connect_to |
| 3 | /api/data/jobs/collect-minute-al | POST | 정규장 + when=now | 422 | SOPHIE_MARKET_HOURS |
| 4 | /api/data/jobs/collect-minute-al | POST | 표식 실행 중 | 409 | MINUTE_REFRESH_RUNNING |
| 5 | /api/data/jobs/collect-daily | POST | 살아 있는 소유자 | 409 | LOCKED + details.pid |
| 6 | /api/data/jobs/collect-daily | POST | 허브 수집 실행 중 | 409 | COLLECT_BUSY |
| 7 | /api/data/jobs/collect-daily | POST | codes=["12345"] | 400 | fieldErrors.codes |
| 8 | /api/data/jobs/collect-ticks | POST | 조회창 밖 | 422 | OUT_OF_TICK_WINDOW |
| 9 | /api/data/jobs/collect-ticks | POST | when=scheduled | 202 | status=scheduled |
| 10 | /api/data/schedules/daily_report | PATCH | 외부 일정 수정 | 409 | NOT_HUB_OWNED |
| 11 | /api/data/sophie | GET | 픽스처 | 200 | hours 출처, minute_refresh.last_result |
| 12 | /api/data/ledger | GET | 픽스처 장부 | 200 | 출처 사람 말 변환 |
| 13 | /api/jobs/backtest → /api/jobs/{id} → /api/runs/{run_id} | POST/GET | 인라인 러너 | 202→200→200 | succeeded, summary.metrics |
| 14 | /api/jobs/backtest | POST | 없는 지표 | 400 | fieldErrors |
| 15 | /api/conditions/preview | POST | 돌파 심은 종목 | 200 | rows 에 포함 |
| 16 | /api/runs/..%2Fx | GET | ID 형식 위반 | 404 | NOT_FOUND |
| 17 | /api/data/jobs/collect-daily | POST | Origin 위조 | 403 | ORIGIN_FORBIDDEN |
| 18 | /api/jobs/{id}/cancel | POST | 예약 잡 | 200 | cancelled, 실행 안 됨 |
| 19 | /api/jobs/{id}/log?offset=N | GET | 이어받기 | 200 | N 이후만, 시크릿 없음 |
| 20 | /api/jobs/optimize | POST | 조합 6,000 | 422 | GRID_TOO_LARGE |

### 8.4 L2: UI Action Test Scenarios

| # | Page | Action | Expected Result | Data Verification |
|---|------|--------|----------------|-------------------|
| 1 | 허브 개요 | 열기 | 카드 11개·시간대 배너·활동·알림 | overview API |
| 2 | 허브 수집 | 정규장 시계로 통합 분봉 패널 | 버튼이 "20:10 예약"으로 | policy API |
| 3 | 허브 수집 | 잠금 보유 상태 | 해당 버튼 비활성 + 사유 | locks API |
| 4 | 허브 일정 | 외부 일정 행 | 토글 없음 + "워치독이 관리" | schedules API |
| 5 | 허브 소피증권 | 열기 | 엔진·시간·기준선·재기동 기록 | sophie API |
| 6 | 백테스트 | 프리셋 불러오기 | 조건 행 + 풀이 문장 | 프리셋 |
| 7 | 백테스트 | 호환 모드 | 손절·익절·사이징 잠김 | — |
| 8 | 백테스트 | 잘못된 조건 [검증] | 행 강조 + 메시지 | validate API |
| 9 | 결과 | 거래 행 클릭 | 캔들 서랍 | bars API |
| 10 | 최적화 | 변수 범위 | 조합 수 갱신·5,000 초과 비활성 | — |

### 8.5 L3: E2E Scenario Test Scenarios

| # | Scenario | Steps | Success Criteria |
|---|----------|-------|-----------------|
| 1 | 예약 수집 | 정규장 시계 → 통합 분봉 기준선 갱신 → 예약 → 시계 20:10 → 가짜 수집기 실행 | 예약→실행→완료, 장부 기록, 보관소 증가 |
| 2 | 외부 작업 관측 | 가짜 "야간 백필"을 관문으로 실행 | 개요 활동 목록에 진행률 |
| 3 | 첫 백테스트 | 프리셋 → 실행 → 결과 → 거래 클릭 | 지표 전부 값, 차트 |
| 4 | 반복 | 복제 → 손절 변경 → 실행 → 비교 | 곡선 2개 |
| 5 | 최적화 | 변수 2개 → 기준 → 실행 → 홀드아웃 두 번 | 두 번째 경고 |
| 6 | 잠금 | 가짜 수집 중 같은 자원 수집 | 409 → 배너 |
| 7 | 놓친 밤 따라잡기 | 가짜 시계로 20:15 회차를 서버 꺼짐으로 건너뜀 → 다음 날 20:15 | 달력의 빨간 날짜가 초록으로, 회차 기록에 "빠진 N쌍 중 N 수집" |

### 8.6 Seed Data Requirements

| Entity | Minimum Count | Key Fields Required |
|--------|:------------:|---------------------|
| 합성 일봉(`tests/fixtures/make_panel.py`) | 6종목 × 400거래일 | 돌파·갭 손절 관통·상한가 잠김·같은 봉 손절/익절·밀린 종목·OHLC 오류 |
| 합성 지수 001·101 | 400거래일 | 달력(휴장일 1일 포함) |
| 통합 분봉 캐시·보관소 샘플 | 2종목 × 30일 | 캐시가 20일로 잘린 상태 |
| 실제 틱 사본 | 2파일 | 같은 초 다중 체결 |
| 소피증권 픽스처 | config.yaml·BOM 표식·로그 | 운영 시간·실행 중 판정 |
| 가짜 수집기(`tests/fixtures/fake_collector.py`) | — | 관문 사용 + 진짜와 같은 진행 줄, `STUDIO_FAKE_COLLECTORS=1` |

### 8.7 Parity Contract (깨지면 머지 금지)

| ID | 대조 | 기준 | 허용 오차 |
|----|------|------|----------|
| P1 | 호환 모드 vs `simulator.run` | ma_crossover·rsi·new_high_swing × 실제 20종목 + 합성 모서리 | 거래 목록 동일(1e-9) |
| P2 | 기존 CLI 기준 지표 vs `metrics.compute` | P1 | 1e-9 |
| P3 | `legacy_slots` vs `simulate_slot_portfolio` | 같은 후보 | final_capital·채택 집합 동일 |
| P4 | `CostModel.round_trip_pct` vs `round_trip_cost_pct` | 가격 격자 | 1e-12 |
| P5 | 틱 돌파 vs `precursor_master.detect_breakouts` | 실제 20파일 | 동일 |
| P6 | 조립기 SMA5/20 교차 vs `MovingAverageCrossover` | 실제 20종목 | Signal 동일 → SC-4 |
| P7 | 허브 조회창 기대 종목 vs `daily_top_n_from_local(35)` − 초대형주 + 보충 | 최근 20거래일 | 집합 동일 |
| P8 | 분봉 리샘플 vs `_resample_minute` | 샘플 | 동일 |

### 8.8 Lookahead Canaries

| ID | 방법 | 통과 조건 |
|----|------|----------|
| C1 | 일봉 t 이후 ×10 | t 이하 신호·t+1 이하 체결 불변 |
| C2 | 일봉 순위: t 이후 거래량 변조 | t 이하 순위 불변 |
| C3 | 분봉 k 이후 + 당일 일봉 변조 | k 이하 신호 불변, 일봉 피연산자 D−1 |
| C4 | 틱 s 이후 변조 | s 이하 신호 불변, 진입가는 s 뒤 체결 |

### 8.9 Performance Targets (Do 단계 실측)

| 작업 | 목표 |
|------|------|
| `/api/data/overview` | ≤ 2초 (파일 끝만 읽기 + 캐시 60초) |
| `/api/data/tick-window` | ≤ 3초 |
| 보관소 `--all` 최초 병합(2,041종목·1.3GB) | 기록만(1회성) |
| `fetch_minute` 보관 병합 추가 시간 | 종목당 ≤ 0.2초 |
| 일봉 포트폴리오: 전 종목 × 5년, 조건 2개 | ≤ 30초 |
| 그리드 100조합 | ≤ 5분(야간 병렬) |
| 분봉 2단계: 60거래일 × 상위 30 | ≤ 60초 |

---

## 9. Clean Architecture

### 9.1 Layer Structure

| Layer | Responsibility | Location |
|-------|---------------|----------|
| **Presentation** | React 화면, HTTP 라우터 | `frontend/`, `studio/api/`, `datahub/api.py` |
| **Application** | 스튜디오 유스케이스·포트, 허브 수집 작업·일정 | `studio/application/`, `datahub/jobs.py`, `datahub/scheduler.py` |
| **Domain** | 스튜디오 엔진·조건·지표·검증(순수) · 허브 정책·판정 규칙(순수 함수) | `studio/domain/`, `datahub/policy.py` 의 판정 함수 |
| **Infrastructure** | 파일·프로세스·잠금·장부·기존 코드 어댑터 | `studio/infrastructure/`, `datahub/{catalog,calendar,gate,locks,ledger,status,quality,sophie,minute_al_archive,collectors,alerts}.py`, `jobrunner/` |

### 9.2 Dependency Rules

```
frontend ─HTTP→ studio.api ─→ studio.application ─→ studio.domain ◄─ studio.infrastructure
                    │                                                     │
                    └─→ datahub.api ─→ datahub(core) ◄────────────────────┘ (경로·상태·보관소 읽기)
jobrunner ← datahub.jobs · studio.application.jobs (handler 는 이름으로만 연결)
기존 수집기·소피증권 스크립트 ─→ datahub(core) (write · catalog)
```

### 9.3 File Import Rules — `tests/test_architecture.py` 가 AST 로 검사

| From | Can Import | Cannot Import |
|------|-----------|---------------|
| `datahub` (core, `api.py` 제외) | stdlib, pandas, pyarrow, pydantic, yaml, psutil, `backtesting.{risk_manager,notifier,daily_cache}` | `fastapi`, `studio`, `jobrunner`(※ `jobs.py`·`scheduler.py` 만 예외), 실주문 모듈 |
| `datahub/api.py` | datahub, jobrunner, fastapi | `studio` |
| `jobrunner` | stdlib, psutil | `datahub`, `studio`, `backtesting`, `fastapi` (handler 는 문자열로만) |
| `studio.domain` | stdlib(아래 제외), numpy, pandas, pydantic | `os`, `io`, `subprocess`, `socket`, `requests`, `psutil`, `fastapi`, `backtesting`, `datahub`, 다른 studio 계층 |
| `studio.application` | domain, stdlib | `fastapi`, `backtesting`, `studio.infrastructure`, `studio.api` |
| `studio.infrastructure` | domain, application.ports, `datahub`(읽기 API), `backtesting.{daily_cache,strategies}`, `_precursor_fastpath`, psutil | `studio.api`, 실주문 모듈 |
| `studio.api` | application, domain(스키마), `datahub.api`, jobrunner, fastapi | `backtesting`, 실주문 모듈 |
| 전부 | — | `kiwoom_client`, `backtesting.trading_loop`, `order_execution`, `sell_order` |

### 9.4 This Feature's Layer Assignment

| Component | Layer | Location |
|-----------|-------|----------|
| 카탈로그·달력·관문·잠금·장부 | Infrastructure(허브 핵심) | `datahub/` |
| 정책 판정·신선도 규칙 함수 | Domain(허브) | `datahub/policy.py`, `datahub/status.py` 의 순수 함수 |
| 수집 작업·일정 | Application(허브) | `datahub/jobs.py`, `datahub/scheduler.py` |
| 작업 실행기 | Infrastructure | `jobrunner/` |
| Spec·조건식·엔진·지표·검증 | Domain | `studio/domain/` |
| 포트·서비스 | Application | `studio/application/` |
| 시장 데이터(카탈로그 경로)·실행 저장·기존 전략 | Infrastructure | `studio/infrastructure/` |
| FastAPI 앱·라우터 | Presentation | `studio/api/`, `datahub/api.py` |

---

## 10. Coding Convention Reference

### 10.1 Naming Conventions

| Target | Rule | Example |
|--------|------|---------|
| Python 모듈·함수·변수 | snake_case | `wait_quiet()`, `same_bar_policy` |
| Python 클래스 | PascalCase | `CostModel`, `WriteHandle` |
| 상수 | UPPER_SNAKE_CASE | `MAX_GRID_COMBOS = 5000` |
| React 컴포넌트 | PascalCase.tsx | `CollectMinuteAlPanel.tsx` |
| 훅·유틸 | camelCase.ts | `useJobPolling.ts` |
| 데이터셋·잠금·일정 id | snake_case (카탈로그) | `minute_al_archive`, `tick_nightly` |

### 10.2 Import Order

Python: stdlib → 서드파티 → 프로젝트. TS: 외부 → `@/` → 상대 → 타입 → 스타일.

### 10.3 Environment Variables

| 변수 | 용도 | 기본 |
|------|------|------|
| `STUDIO_PORT` | 서버 포트 | 8780 |
| `STUDIO_DATA_ROOT` | 저장소 루트(테스트는 픽스처) | 저장소 루트 |
| `STUDIO_MAX_COMPUTE_JOBS` | 동시 백테스트 | 2 |
| `STUDIO_DEV_ORIGIN` | 개발 중 허용 Origin | 없음 |
| `STUDIO_FAKE_COLLECTORS` | 테스트용 가짜 수집기 | 없음 |
| `DATAHUB_TRIGGER`, `DATAHUB_JOB_ID` | 허브가 띄운 작업 표시(장부) — 허브가 설정 | 없음 = external |

### 10.4 This Feature's Conventions

| Item | Convention Applied |
|------|-------------------|
| 공유 데이터 쓰기 | `datahub.write()` 안에서만 — data-agent 상시 규칙에 추가 |
| 공유 데이터 경로 | 새 코드는 `datahub.catalog.path()` |
| 모듈 docstring | 용도 + `Design: docs/02-design/features/backtest-studio.design.md §x` |
| 주석 | 비직관적 처리만 한글로 이유(시점 규칙·호환 규칙·소피증권 연계 이유) |
| 파일 쓰기 | tmp + `os.replace`, UTF-8 (PowerShell 표식 JSON 은 BOM → 읽을 때 `utf-8-sig`) |
| 콘솔 | 워커·CLI 시작 시 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` |
| PowerShell 수정 | BOM 유지, 장중 금지, 네이티브 호출은 stdout 만 |
| 프론트 상태 | TanStack Query 폴링 + 컴포넌트 state |

---

## 11. Implementation Guide

### 11.1 File Structure

```
datahub/
├── __init__.py            # write, catalog, wait_quiet 공개
├── __main__.py            # CLI: status · wait-quiet · ledger · archive-minute-al · check
├── catalog.yaml  catalog.py  calendar.py
├── gate.py  locks.py  ledger.py
├── policy.py  status.py  quality.py  sophie.py
├── minute_al_archive.py  collectors.py  jobs.py  scheduler.py  alerts.py
└── api.py                 # FastAPI 라우터(/api/data)

jobrunner/
├── __init__.py  store.py  spawn.py  dispatcher.py  worker.py  child.py  mask.py

studio/
├── __init__.py  __main__.py          # python -m studio → uvicorn(127.0.0.1) + dispatcher·scheduler 스레드
├── domain/  models.py market_rules.py costs.py spec.py narration.py metrics.py robustness.py validation.py
│   ├── conditions/  ast.py catalog.py indicators.py evaluator.py
│   └── engine/      fills.py portfolio.py intraday.py compat.py tick.py
├── application/  ports.py backtest_service.py optimize_service.py screener_service.py jobs.py
├── infrastructure/  market_data.py run_store.py legacy_strategies.py presets.py git_info.py
└── api/  app.py deps.py errors.py schemas.py  routes/ jobs.py runs.py meta.py conditions.py presets.py

frontend/  package.json tsconfig.json vite.config.ts(outDir ../static/studio) index.html playwright.config.ts
└── src/  main.tsx App.tsx  api/ types/ lib/  components/{layout,charts,hub,builder,results,optimize}/  pages/
static/studio/          # 빌드 결과(커밋)
presets/studio/         # 기본 프리셋 6종(커밋)
tests/  datahub/ jobrunner/ studio/ fixtures/ test_architecture.py
run_studio.bat
```

### 11.2 Implementation Order

1. [ ] **허브 핵심(기한 있음)**: 카탈로그·달력·잠금·장부·관문, 보관소 + `fetch_minute` 병합 훅, CLI, 쓰는 곳 6곳 관문, 수집기 `--codes @파일`·`--stop-at`, 소피증권 재기동 2곳 `wait-quiet`, **보관소 최초 전체 병합 실행**
2. [ ] 허브 서버·화면: jobrunner, FastAPI 골격, 정책·상태·품질·소피증권·일정(**체결 야간 수집·따라잡기, 일봉 아침 따라잡기**)·알림·수집 작업·API, 워치독 8780, 프론트 골격 + 데이터 허브 페이지
3. [ ] 일봉 엔진 + 패리티(P1~P4·P6·P8)·카나리아(C1·C2)
4. [ ] 백테스트 화면(조립기·결과·기록·비교·프리셋)
5. [ ] 검증(그리드·워크포워드·견고성·홀드아웃)
6. [ ] 분봉·틱(보관소 로더·모드 A·B·P5·C3·C4) + 과거 깊게 받기
7. [ ] L1~L3, 성능 실측

### 11.3 Session Guide

#### Module Map

| Module | Scope Key | Description | 담당(제안) | 선행 | Estimated Turns |
|--------|-----------|-------------|-----------|------|:---------------:|
| 허브 핵심 | `module-1` | 카탈로그·관문·잠금·장부·보관소·CLI·쓰는 곳 6곳(+수집기 `--codes @파일`·`--stop-at`)·재기동 2곳 | data-agent(허브·수집기·소피증권 데이터 스크립트) + monitoring-agent(재기동 스크립트) | — | 40–50 · **기한 2026-10-02** |
| 허브 서버·화면 | `module-2` | jobrunner·서버 골격·정책·상태·일정(야간 수집·따라잡기)·알림·수집 작업·API·워치독·허브 페이지 | monitoring-agent(서버·화면·워치독·알림) + data-agent(상태·수집 작업) | module-1 | 50–60 |
| 일봉 엔진 | `module-3` | 체결·포트폴리오·호환·지표·패리티 | backtest-agent + strategy-agent(조건식·기존 전략·프리셋) | module-1(카탈로그) | 50–60 |
| 백테스트 화면 | `module-4` | 조립기·결과·기록·비교 | monitoring-agent | module-2, 3 | 40–50 |
| 검증 | `module-5` | 그리드·워크포워드·견고성 | backtest-agent + monitoring-agent(화면) | module-3, 4 | 40–50 |
| 분봉·틱 | `module-6` | 보관소 로더·틱 A/B·깊게 받기 | backtest-agent + data-agent | module-3 | 50–60 |

#### Recommended Session Plan

| Session | Phase | Scope | Turns |
|---------|-------|-------|:-----:|
| Session 1 | Plan + Design | 전체 (완료) | — |
| Session 2 | Do | `--scope module-1` (10-02 까지) | 40–50 |
| Session 3 | Do | `--scope module-2,module-3` (다른 에이전트·파일 → 병렬) | 50–60 |
| Session 4 | Do | `--scope module-4` | 40–50 |
| Session 5 | Do | `--scope module-5` | 40–50 |
| Session 6 | Do | `--scope module-6` | 50–60 |
| Session 7 | Check + QA + Report | 전체 | 30–40 |

### 11.4 기존 파일 변경 (정확히 이것만)

| 파일 | 변경 | 주의 |
|------|------|------|
| `backfill_universe.py` | 본 작업을 `datahub.write("daily_minute", writer="backfill_universe")` 로, 진행 기록, `--codes=A,B` 또는 `--codes @파일`, `--stop-at HH:MM`(종목 시작 전 확인, 지나면 남은 수를 기록하고 정상 종료) | 야간 작업 자동 적용 |
| `backtesting/updater.py` | `update_top35` 본문을 관문으로 | 8765 는 재시작해야 적용 |
| `daily_report_job.py` | `update_indexes` 를 관문으로 | |
| `tick_collect_804_828_al.py` | main 을 `datahub.write("tick_al")` 로, 진행 기록, `--codes A,B` 또는 `--codes @파일`, `--stop-at HH:MM`(워커가 새 종목 시작 전 확인 → 지나면 "deferred" 상태로 done 에 안 넣고 정상 종료) | 기존 인자 호환 |
| `backtesting/daily_cache.py` | tmp 이름에 PID | |
| `kospi-theme-engine/scripts/fetch_minute.py` | main 을 `datahub.write("minute_al")` 로, 종목 캐시 교체 **직전** 보관소 병합, `--archive-only` | 장중 수정 금지 |
| `kospi-theme-engine/scripts/fill_daily.py` | main 을 `datahub.write("daily_minute")` 로 + 클라이언트 키를 `batch_keys()` 로(계약 6) | 장중 수정 금지 |
| `kospi-theme-engine/restart_after_midnight.ps1` | 엔진 종료 전 `python -X utf8 -m datahub wait-quiet --until 08:00` (저장소 루트에서) | BOM 유지·관리자 권한 스크립트·장중 금지 |
| `kospi-theme-engine/rebuild_after_close.ps1` | 엔진 교체·재기동 전 `wait-quiet --max-minutes 30`, 그 호출만 `$ErrorActionPreference='Continue'` | 같음 |
| `nasdaq_monitor_watchdog.ps1` | `$targets` 에 `@{ Type = "Heartbeat"; Match = "-m studio(\s|$)"; Args = @("-m", "studio"); LogName = "studio_server"; HeartbeatPath = "state\studio\heartbeat.json" }` — 처음엔 Http 프로브였으나 5초 1회 실패 = 재기동이라 허브 계산(GIL)에 뚫림 → 서버 이벤트 루프 안 asyncio 작업이 15초마다 쓰는 하트비트(120초)로 교체(2026-09-25). 재기동마다 `state/watchdog/restarts.log` 에 사유 | 돌던 워치독은 옛 스크립트를 들고 있음 → 시작폴더 VBS 를 explorer 경유로 재기동(2026-09-23 절차) |
| `state/agent_mail/data-agent/standing.md` | 상시 규칙: "공유 데이터 쓰기는 `datahub.write` 안에서만, 경로는 카탈로그에서" | 덮어쓰지 말고 추가(git 복구 불가) |
| `requirements.txt` | `fastapi`, `uvicorn`, `httpx  # 테스트` | |
| `.gitignore` | `results/studio/`, `node_modules/`, `frontend/playwright-report/`, `frontend/test-results/` | |

### 11.5 운영 메모

- **기한**: 보관소 최초 전체 병합 + `fetch_minute` 병합 훅은 **2026-10-02 까지**(워치독 분봉 갱신 예상 10-03 토 09:00 이후).
- 8765 재시작(장 마감 후, monitoring-agent)해야 top35 가 관문을 쓴다.
- 야간 `daily_report_job` 자체는 관문 적용 외 변경 없음 — 허브 수집과 겹치면 순서대로.
- 소피증권 스크립트 4개 수정 후: 다음 토요일 분봉 갱신 로그·다음 재기동 로그에서 정상 확인.
- 첫 실행: `pip install -r requirements.txt` → `cd frontend && npm ci && npm run build` → `run_studio.bat`(이후 워치독이 유지).

---

## 12. Open Questions & Known Limitations

| # | 내용 | 기본 처리 |
|---|------|----------|
| OQ-1 | ~~통합 분봉 갱신 버튼~~ → **넣음**(사용자 결정 2026-09-25), 소피증권 연계 계약 §2.4.9 | 해결 |
| OQ-2 | ~~체결 야간 자동 수집 켤지~~ → **매일 밤 자동 + 못 받은 것은 다음 밤 따라잡기**(사용자 결정 2026-09-25), 일봉은 아침 따라잡기 추가 — §2.4.11 | 해결 |
| OQ-3 | `unledgered_write`(장부 밖 쓰기) 알림 | 1주 관찰 후 결정 |
| OQ-4 | 워치독 일정 허브 이관(M단계) | 허브 2주 안정 운영 뒤 |
| OQ-5 | 소피증권 자정 재기동 기록이 09-07 이후 없음 | 허브 일정 탭에 "놓침"으로 표시 — 원인 조사는 별도(monitoring-agent) |
| OQ-6 | 실행 결과 보관 기간 | 무제한 |
| OQ-7 | 끝난 작업 폴더(`state/jobs/`) 보관 규칙 — 지금은 계속 쌓임(module-2 1단계 보고) | module-2 2단계에서 결정: 지우지 않고 월별 압축 보관 제안 |

**작업 처리기 계약(module-2 1단계 확정)**: 처리기는 `datahub/jobs.py`·`studio/application/jobs.py` 안의 함수(`패키지.모듈:함수` — 서브모듈은 접두사 검사에서 거부), 시그니처 `def handler(ctx) -> dict | None`. `ctx` = job_id·payload·root·`progress(pct, stage, message, eta_sec=, waiting_lock=, paused=)`·`log(line)`·`is_cancelled()`·`set_run_id()`·`run_child(argv, cwd=, env=, on_line=)`. **§7 실행 파일 허용 목록 검사는 명령을 조립하는 `datahub.jobs` 가 한다**(jobrunner 는 받은 argv 를 그대로 돌린다). 자세한 건 `jobrunner/worker.py` 머리말.
| L-1 | 일봉 거래대금 = 종가×거래량 KRX 근사 | 경고 배지 |
| L-2 | 생존편향 — 상장폐지 종목 없음 | 경고 배지 |
| L-3 | 체결 174종목·36거래일, 조회창 20거래일 | 표본 표시·조회창 달력 |
| L-4 | 통합 분봉은 보관소가 쌓이기 전 이력이 짧다(캐시 중앙값 70일, 최근 3개월 기대 쌍의 42%) | 기본은 통합 그대로(결과에 커버리지 표시). 긴 과거가 필요하면 사용자가 KRX 를 골라 쓰거나("KRX 기준" 표시) 과거 깊게 받기(P4 — 60일 1.4시간·250일 약 20시간, 사용자 결정) |
| L-5 | 휴장일 달력은 사람이 매년 채운다(지난날은 지수로 자동) | 카탈로그 `holidays` |
| L-6 | 호가 없음 → 체결가는 체결 데이터 + 슬리피지 가정 | 비용 민감도 |
| L-7 | 통합(_AL) 체결 응답은 **같은 초 안·근처 순서가 흔들린다**(파일 40%, 행의 0.0054% — 페이지 이음새 아님, 행 수·거래량 합은 정확: 2026-09-25 전수 감사) | 로더는 초 단위 안정 정렬. 같은 초 순서에 갈리는 규칙(틱룰 방향·같은 초 마지막 가격)은 틱 결과 경고에 표시 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-09-25 | 초안 — Option B(새로 짓기), 호환 모드·패리티 계약 | namdae + Claude |
| 0.2 | 2026-09-25 | **중앙 데이터 허브(`datahub`)** 추가(사용자 지시): 카탈로그·쓰기 관문·잠금 3종·장부·정책(소피증권 운영 시간)·일정·감시·알림·소피증권 연계 계약·통합 분봉 보관소·통합 분봉 갱신 4모드. 공용 실행기 `jobrunner` 분리. 스튜디오 분봉 출처를 보관소로 | namdae + Claude |
| 0.3 | 2026-09-25 | **야간 자동 수집과 따라잡기**(사용자 결정): 체결 `tick_nightly` 켜짐 — 빠진 (종목, 날짜) 전부를 받는 방식이라 놓친 밤은 다음 밤이 채움, 같은 밤 재시도 3회, 3일 밤 실패 시 수동 확인 목록, `--stop-at` 으로 소피증권 전 정지, 수집 뒤 압축. 일봉 `daily_catchup`(야간 갱신 놓친 날 아침, 거래일 달력 기준). 알림 3종 추가 | namdae + Claude |
