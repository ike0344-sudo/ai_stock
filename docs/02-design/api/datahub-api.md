# 데이터 허브 API 계약 (`/api/data/*`)

> **단일 출처는 `frontend/src/types/data.ts`** — 이 문서는 같은 내용을 사람이 읽는 표로 쓴 것이다. 둘을 같이 고친다.
> 설계서: `docs/02-design/features/backtest-studio.design.md` §4.1·§4.2·§5.4·§6 / 실례 JSON: `frontend/src/test/fixtures/hub.ts`
> 구현: `datahub/api.py`(data-agent). 화면: `frontend/src/pages/hub/*`(monitoring-agent). 상태: **계약 v1 (2026-09-25)**

## 공통 규칙

| 규칙 | 내용 |
|---|---|
| 봉투 | 성공 `{"data": …}` / 실패 `{"error": {"code","message","details"}}` (§6). 아래 응답은 전부 `data` 안쪽 |
| 시각·날짜 | 로컬(KST) ISO. 시각 `2026-09-25T10:12:00`(초 또는 분), 날짜 `2026-09-25` |
| 없는 값 | **`null`** — 0·빈 문자열로 채우지 않는다. 화면은 null 을 "—" 로 보여준다 |
| `?` 표시 | 그 데이터셋·규칙에만 있는 키(없을 수 있음). 표시 없는 키는 **항상 있다** |
| 판정 | `good`(초록) / `warn`(주황) / `bad`(빨강) |
| 시간대 | `market`(정규장) / `sophie_live`(소피증권 가동, 정규장 밖) / `night` / `holiday` |
| 정책 판정 | `allow_now` / `needs_confirm` / `schedule_only` |
| 쓰기 주체 `source` | `허브` `야간 갱신` `8765` `소피증권` `수동` (`datahub.ledger.source_label` 그대로) |
| run 상태 `state` | `실행 중` `완료` `실패` `중단됨` (`datahub.ledger.runs` 그대로) |
| 화면의 "API 준비 중" | 라우트가 없어서 `404 NOT_FOUND` 가 오면 화면은 그 패널을 **"허브 API 준비 중 — GET /api/data/…"** 로 표시한다(가짜 값 없음). 그래서 **없는 리소스에 404 를 쓰지 말고**, 있는 리스트 API 는 빈 배열을 돌려줘야 한다 |

## 이미 있는 `datahub` 함수와의 대응 (api.py 는 얇게)

| 엔드포인트 | 재료 |
|---|---|
| overview.datasets[] | `status.overview()` = `dataset_status()` 목록 — **반환 dict 그대로** |
| overview.now | `policy.sophie_hours()`, `policy.window()`, `policy.decide("collect_ticks")` |
| overview.alerts_active | `alerts.evaluate(alerts.build_context(), now)` + 처음 감지 시각(`state/datahub/alerts_sent.json`) |
| tick-window | `status.tick_window()` + `collectors.load_attempts()` + 일정 표식 |
| gaps / stale / quality | `status.gaps()` / `status.stale()` / `quality.daily_quality()` (+ 종목명·`days_behind` 를 API 에서 붙임) |
| sophie | `sophie.overview()` **그대로** |
| ledger | `ledger.read()` → `ledger.runs()` (+ `source`·`ended`·`duration_sec`·`detail`·`job_id` 를 API 에서 붙임) |
| policy | `policy.decide()` (+ `n_codes`·`eta_sec`·`baseline_effect`·`blocked` 를 API 에서 붙임) |

## 엔드포인트

### 읽기 (GET)

| 경로 | 쿼리 | 응답 `data` | 비고 |
|---|---|---|---|
| `/api/data/overview` | — | `OverviewData` = `{now, datasets[11], activity[], alerts_active[], daily_catchup}` | 상태 바·개요 탭. 무거우면 캐시(≤10초) 가능 |
| `/api/data/datasets/{id}` | — | `DatasetDetail` = `DatasetStatus` + `{notes, path, writers[], readers[], freshness, lock_owner, recent_ledger[≤20], schedule_ids[]}` | 없는 id → 404 |
| `/api/data/activity` | — | `ActivityRow[]` | 지금 쓰는 작업(허브 잡 + 장부 진행 중 run + 외부 표식). 없으면 `[]` |
| `/api/data/locks` | — | `LockRow[3]` = `{resource, covers[], held, owner}` | |
| `/api/data/ledger` | `lock` `source` `since` `limit`(1~500, 기본 100) | `LedgerRun[]` 최신 먼저 | |
| `/api/data/ledger/unledgered` | `hours`(1~168, 기본 24) | `UnledgeredWrite[]` | 파일 mtime 을 훑어 무겁다 → 별도 경로(신규, §4.1 에 없음) |
| `/api/data/policy` | `kind` `mode` `codes`(콤마) | `PolicyData` | 수집 버튼이 이걸로 "지금/확인 후/예약"이 된다 |
| `/api/data/stale` | `dataset`(기본 daily) `sophie_only` | `{dataset, reference_date, rows: StaleRow[]}` | |
| `/api/data/gaps` | `dataset`(daily) `days`(기본 120) | `{dataset, days, threshold: 0.9, rows: GapRow[]}` | 오래된 날부터 |
| `/api/data/quality` | `dataset`(daily) `since` `limit`(≤200) | `{dataset, since, rows_checked, counts{5종}, issues[]}` | `counts` 는 전체, `issues` 는 limit 까지 |
| `/api/data/tick-window` | — | `TickWindowData` | 체결 조회창 20거래일 + 자동 수집 + 수동 확인 목록 |
| `/api/data/archive` | — | `ArchiveData` | 보관소 커버리지 |
| `/api/data/schedules` | — | `ScheduleRow[9]` | |
| `/api/data/alerts` | — | `{rules: AlertRule[9], active: ActiveAlert[]}` | |
| `/api/data/sophie` | — | `SophieData` | `sophie.overview()` 그대로 |

### 쓰기 (POST·PATCH)

| 경로 | 본문 | 성공 | 주요 오류 |
|---|---|---|---|
| `POST /api/data/jobs/collect-daily` | `{mode: stale\|all\|codes, codes?, when, scheduled_at?, confirm?}` | 202 `{job_id, status, scheduled_at}` | 409 LOCKED·COLLECT_BUSY · 422 SOPHIE_MARKET_HOURS·SOPHIE_LIVE_CONFIRM · 400 fieldErrors.codes |
| `POST /api/data/jobs/collect-ticks` | `{mode: catch_up, …}` 또는 `{mode: range, start, end, universe, codes?, concurrency 1~6, …}` | 202, 빠진 게 없으면 200 `{nothing_to_do: true}` | 위 + 422 OUT_OF_TICK_WINDOW |
| `POST /api/data/jobs/collect-minute-al` | `{mode: sophie_baseline\|all_cached\|codes\|deep_archive, codes?, days?, …}` | 202 | 위 + 409 MINUTE_REFRESH_RUNNING |
| `POST /api/data/jobs/archive-minute-al` | `{}` | 202 | 409 LOCKED |
| `POST /api/data/tick-window/retry` | `{pairs: [{code,date}] \| "all"}` | 200 `{retried: n}` | |
| `PATCH /api/data/schedules/{id}` | `{enabled?, time?}` (준 키만) | 200 `ScheduleRow` | 409 NOT_HUB_OWNED(외부 일정) · 404 · 400 |
| `PATCH /api/data/alerts/{id}` | `{enabled}` | 200 `AlertRule` | 404 |

공통 (`CollectWhen`): `when: now|scheduled`, `scheduled_at`(when=scheduled 필수), `confirm`(needs_confirm 일 때 true).
`when=now` 인데 정책이 `schedule_only` → **422 SOPHIE_MARKET_HOURS**(`details.suggest_at`). `needs_confirm` 인데 `confirm≠true` → **422 SOPHIE_LIVE_CONFIRM**.

### 작업 표·로그는 이미 있는 `/api/jobs` 를 쓴다 (studio 1단계 구현, 허브가 다시 만들 필요 없음)

| 경로 | 용도 |
|---|---|
| `GET /api/jobs?group=collect&limit=50` | 작업 표. **행마다 `progress`(pct·stage·message·eta_sec·paused·waiting_lock)와 `cancel_requested` 포함** |
| `GET /api/jobs/{id}/log?offset=N` | 로그 뷰어(2초 이어받기) |
| `POST /api/jobs/{id}/cancel` | 취소(예약 포함) |

허브 수집 작업의 `kind` 는 `collect_daily`·`collect_ticks`·`collect_minute_al`·`archive_minute_al`·`tick_nightly`·`daily_catchup` 로 통일한다(화면이 종류 이름으로 보여줌).
`progress.waiting_lock` 은 관문이 잠금을 기다리는 중이면 `{resource, owner}` (없으면 null) — 화면이 "잠금 대기" 로 보여준다.

## 필드 상세

### `DatasetStatus` (overview.datasets[])

공통(항상): `id label basis verdict reason retention last_write lock`, `updated?`.
`basis` 는 카탈로그 값 그대로(`KRX`·`AL`·`derived`·`reference`), `retention` 도 그대로(`keep`·`forever`·`forever_unrecoverable`·`overwrite_20d`·`regenerable`) — 화면이 사람 말·배지로 바꾼다(실제 API 로 확인, 2026-09-25).

| 신선도 규칙 | 데이터셋 | 추가 키 |
|---|---|---|
| `last_trading_day` | daily·minute_krx·index·high120 | `n_codes reference_date expected_date stale_count stale_inactive_count sophie_stale_count` |
| `max_age_days` | minute_al | `n_codes last_date_mode age_days behind_share` |
| `archive_superset` | minute_al_archive | `codes_cache codes_archive missing_vs_cache missing_codes` |
| `tick_window` | tick_al | `n_codes window_missing min_days_left` |
| `dist_sync` | sophie_reference | `data_updated dist_updated in_sync diff_files` |
| `backup_exists` | sophie_live_logs | `backup_date found` |
| `newer_than_source` 등 | daily_all_cache·reference_static | 공통만 |

### `ActivityRow`
`{source, writer, lock, dataset, state(실행 중|잠금 대기), done, total, since, run, job_id}` — `job_id` 가 있으면 허브가 띄운 것.

### `LedgerRun`
`{run, ts, ended, duration_sec, lock, writer, source, trigger(hub|external), job_id, state, done, total, detail, error}`

### `PolicyData` (버튼 문구를 정한다)
`{kind, mode, weight(heavy|light|local), window, decision, suggest_at, reason, warnings[], n_codes, eta_sec, estimate_basis, baseline_effect(updated|unchanged|null), blocked}`
- `blocked`: 지금 시작할 수 없는 사유 — `{code: LOCKED|COLLECT_BUSY|MINUTE_REFRESH_RUNNING, message, details}`. 있으면 버튼 비활성 + 사유 표시(POST 를 보내 보기 전에 화면이 안다).
- `eta_sec` 는 **추정**이라 `estimate_basis`(근거 한 줄)를 같이 준다. 모르면 둘 다 null.
- `n_codes`: 모드별 대상 수(`stale` → 밀린 종목 수, `sophie_baseline` → 소피증권 기본 대상, `all_cached` → 캐시 파일 수, `codes` → `codes` 쿼리 개수).

### `TickWindowData`
`dates[]` = `{date, status(collected|partial|missing|pending), collected_codes, expected_codes, days_left, missing_count, missing_sample[≤20]}`.
화면: collected 초록·partial 주황·missing 빨강·pending 회색, **소실 임박 = 빠진 게 있고 `days_left ≤ 3`** 이면 굵은 테두리.
`auto` = `{schedule, enabled, next_run, last_night{night, started, finished, attempts, collected_pairs, remaining_pairs, deferred}|null, given_up[{code,name,date,attempts,days_left}]}`.

### `ScheduleRow`
`{id, label, owner(hub|watchdog|8765|sophie), when, does, enabled|null, editable, time|null, last_started, last_finished, last_ok, last_result, next_expected, missed, missed_note, runs[≤14]}`
- 외부 소유: `enabled=null`, `editable=false`, `runs=[]`. 허브 소유: `runs` 는 최근 14회.
- `missed_note` 예: 자정 재기동 `"18일째 기록 없음"`.
- 일정 id: `daily_report minute_refresh top35_live sophie_restart sophie_rebuild tick_nightly daily_catchup minute_archive freshness_check`.

### 알림 규칙 id (9)
`daily_stale_before_open tick_window_loss archive_behind dead_lock_owner sophie_stale_day tick_nightly_failed tick_given_up daily_catchup_incomplete unledgered_write`
— `title` 은 API 가 사람 말로 준다(화면에 이름 사전이 없다).

## 허브 오류 코드

| HTTP | code | 언제 | `details` |
|---|---|---|---|
| 409 | LOCKED | 잠금 소유자가 살아 있음 | `owner: LockOwner` |
| 409 | COLLECT_BUSY | 허브 수집이 이미 1개 실행 중 | `job_id` |
| 409 | MINUTE_REFRESH_RUNNING | 소피증권 분봉 기준선 갱신 실행 중 | — |
| 409 | NOT_HUB_OWNED | 외부 일정 수정 시도 | — |
| 422 | SOPHIE_MARKET_HOURS | 정규장 대량 수집을 지금(now)으로 요청 | `suggest_at` |
| 422 | SOPHIE_LIVE_CONFIRM | 소피증권 가동 시간 대량 수집, 확인 없음 | `suggest_at` |
| 422 | OUT_OF_TICK_WINDOW | 체결 기간이 조회창 밖 | `window_start` |
| 400 | VALIDATION_ERROR | 요청 형식 | `fieldErrors` |
| 404 | NOT_FOUND | 없는 데이터셋·일정·규칙 | — |

## 바꾸는 절차
1. 모양을 바꾸려면 **먼저 `types/data.ts` 와 이 표를 고치고** 상대에게 편지(`state/agent_mail/`)를 보낸다.
2. 화면 테스트의 실례(`test/fixtures/hub.ts`)가 타입으로 검사되므로, 타입이 바뀌면 화면 쪽 컴파일이 먼저 깨진다 — 어긋남을 빌드가 잡는다.
