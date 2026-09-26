// 데이터 허브 API 계약 (`/api/data/*`) — 화면과 서버가 어긋나지 않게 **여기서 모양을 고정**한다.
//
//   사람이 읽는 표: docs/02-design/api/datahub-api.md   (이 파일과 같은 내용, 같이 고친다)
//   구현: datahub/api.py (data-agent) — 이미 있는 함수(status.dataset_status·tick_window·gaps·stale·
//         quality.daily_quality·sophie.overview·ledger.runs·policy.decide·alerts.Alert)의 반환 모양을 최대한 그대로 쓴다.
//   실례 JSON: frontend/src/test/fixtures/hub.ts (화면 테스트가 쓰는 고정 값 — data-agent 도 API 테스트에 같이 쓴다)
//
// 규칙
//   - 성공은 {"data": ...}, 실패는 §6 오류 봉투. 여기 타입은 전부 `data` 안쪽이다.
//   - 시각은 로컬(KST) ISO 문자열, 초 또는 분 단위 ("2026-09-25T10:12:00"). 날짜는 "YYYY-MM-DD".
//   - 값이 없거나 계산 못 하는 것은 **null** (0·빈 문자열로 채우지 않는다) — 화면은 null 을 "—" 로 보여준다.
//   - `?` 가 붙은 키는 그 데이터셋·규칙에만 있는 것(없을 수 있음). 나머지는 항상 있다.
//   - 화면은 이 파일에 없는 키를 읽지 않는다. 키를 더하고 싶으면 여기와 표에 먼저 더한다.

// ───────────────────────────── 공통 ─────────────────────────────

/** 판정 3단계 — 화면 색과 같다: good=초록 warn=주황 bad=빨강 */
export type Verdict = 'good' | 'warn' | 'bad'

/** 지금 시간대(소피증권 config.yaml 기준). market=정규장 sophie_live=소피증권 가동(정규장 밖) night=야간 holiday=주말·휴장일 */
export type Window = 'market' | 'sophie_live' | 'night' | 'holiday'

/** 수집 정책 판정 */
export type Decision = 'allow_now' | 'needs_confirm' | 'schedule_only'

/** 쓰기 주체(장부 cmd 에서 사람 말로 바꾼 것 — datahub.ledger.source_label 과 같다) */
export type Source = '허브' | '야간 갱신' | '8765' | '소피증권' | '수동'

/** 장부 run 상태(datahub.ledger.runs 와 같다) */
export type RunState = '실행 중' | '완료' | '실패' | '중단됨'

export type LockResource = 'daily_minute' | 'minute_al' | 'tick_al'

export interface SophieHours {
  connect_from: string // "08:20"
  open: string // "09:00"
  close: string // "15:30"
  connect_to: string // "20:10"
  source: string // "kospi-theme-engine/config.yaml" 또는 "기본값(설정을 못 읽음)"
}

export interface LockOwner {
  pid: number
  cmdline: string
  since: string // ISO
  alive: boolean
  dead: boolean // 소유자는 죽었는데 파일이 남음(다음 획득자가 회수)
  source: Source
}

export interface LastWrite {
  ts: string
  writer: string | null
  source: Source
  ok: boolean | null
}

// ───────────────────── GET /api/data/overview ─────────────────────

/** 데이터셋 한 장 — datahub.status.dataset_status() 반환 + 아래 규칙별 칸 */
export interface DatasetStatus {
  id: string // 카탈로그 id: daily, minute_krx, index, minute_al, minute_al_archive, tick_al, sophie_reference, sophie_live_logs, reference_static, high120, daily_all_cache
  label: string
  basis: string // 카탈로그 값 그대로: KRX | AL(통합) | derived(파생) | reference(참조) — 화면이 사람 말로 바꾼다
  verdict: Verdict
  reason: string // 판정 이유 한 줄(사람 말)
  retention: string // 카탈로그 값 그대로: keep | forever | forever_unrecoverable | overwrite_20d | regenerable
  last_write: LastWrite | null
  lock: { resource: LockResource; held: boolean } | null
  updated?: string // 파일 수정 시각(분 단위)
  // rule=last_trading_day (daily, minute_krx, index, high120…)
  n_codes?: number
  reference_date?: string | null // 종목별 최신일의 최빈값
  expected_date?: string | null // 마감 기한이 지난 가장 최근 거래일
  stale_count?: number
  stale_inactive_count?: number
  sophie_stale_count?: number // 소피증권 유니버스 중 밀린 종목
  // rule=max_age_days (minute_al)
  last_date_mode?: string
  age_days?: number
  behind_share?: number // 0~1
  // rule=archive_superset (minute_al_archive)
  codes_cache?: number
  codes_archive?: number
  missing_vs_cache?: number
  missing_codes?: string[] // 최대 50
  // rule=tick_window (tick_al)
  window_missing?: number // 조회창 안 빠진 (종목,날짜) 쌍
  min_days_left?: number | null // 가장 급한 빠진 날짜의 남은 거래일
  // rule=dist_sync (sophie_reference)
  data_updated?: string | null
  dist_updated?: string | null
  in_sync?: boolean
  diff_files?: string[]
  // rule=backup_exists (sophie_live_logs)
  backup_date?: string
  found?: string[]
}

export interface ActivityRow {
  source: Source
  writer: string | null
  lock: LockResource | null
  dataset: string | null // 주로 쓰는 데이터셋 id (잠금이 여러 개를 덮으면 첫 번째)
  state: '실행 중' | '잠금 대기'
  done: number | null
  total: number | null
  since: string // 시작 시각
  run: string | null // 장부 run id
  job_id: string | null // 허브가 띄운 것이면 잡 id (외부면 null)
}

export type AlertRuleId =
  | 'daily_stale_before_open'
  | 'tick_window_loss'
  | 'archive_behind'
  | 'dead_lock_owner'
  | 'sophie_stale_day'
  | 'tick_nightly_failed'
  | 'tick_given_up'
  | 'daily_catchup_incomplete'
  | 'unledgered_write'

export interface ActiveAlert {
  id: AlertRuleId
  title: string // 규칙 이름(사람 말)
  target: string // 무엇에 대한 알림인가(datahub.alerts.Alert.target)
  message: string
  first_seen: string // 처음 감지 시각
}

/** 일봉 아침 따라잡기(§2.4.11) 결과 — 안 돈 날이면 null */
export interface DailyCatchup {
  date: string
  received: number
  remaining: number
  sophie_remaining: number
  deadline_passed: boolean
}

export interface OverviewData {
  now: {
    ts: string
    window: Window
    sophie_hours: SophieHours
    /** 대량 수집을 지금 해도 되나 — 시간대 배너 문구용 ("가능 / 확인 필요 / 20:10 예약만") */
    bulk: { decision: Decision; suggest_at: string | null }
  }
  datasets: DatasetStatus[] // 카탈로그 11종, 카탈로그 순서
  activity: ActivityRow[]
  alerts_active: ActiveAlert[]
  daily_catchup: DailyCatchup | null
}

// ───────────────── GET /api/data/datasets/{id} ─────────────────

export interface DatasetDetail extends DatasetStatus {
  notes: string
  path: string // 카탈로그 경로 템플릿
  writers: { id: string; cmd: string; triggers: string[] }[]
  readers: string[]
  freshness: Record<string, unknown>
  lock_owner: LockOwner | null
  recent_ledger: LedgerRun[] // 최근 20건
  schedule_ids: string[]
}

// ───────────────────── GET /api/data/activity ─────────────────────
export type ActivityData = ActivityRow[]

// ───────────────────── GET /api/data/locks ─────────────────────
export interface LockRow {
  resource: LockResource
  covers: string[] // 덮는 데이터셋 id
  held: boolean
  owner: LockOwner | null
}
export type LocksData = LockRow[]

// ─────── GET /api/data/ledger?lock=&source=&since=&limit=100 ───────
// lock: 자원, source: Source 문자열, since: ISO 날짜/시각, limit: 1~500(기본 100). 최신이 앞.

export interface LedgerRun {
  run: string
  ts: string // 시작
  ended: string | null // 끝(끝 기록 없으면 null)
  duration_sec: number | null
  lock: LockResource | null
  writer: string | null
  source: Source
  trigger: 'hub' | 'external' | null
  job_id: string | null
  state: RunState
  done: number | null
  total: number | null
  detail: Record<string, unknown> | null // 시작 기록의 detail (모드·종목 수 등)
  error: string | null
}
export type LedgerData = LedgerRun[]

// ───────── GET /api/data/ledger/unledgered?hours=24 ─────────
// 장부 없는 쓰기(§2.4.8) — 관문을 안 거친 수동 스크립트 찾기. 파일 수정 시각을 훑어서 무겁다 → 별도 경로.
export interface UnledgeredWrite {
  dataset: string
  lock: LockResource
  file: string
  mtime: string
}
export type UnledgeredData = UnledgeredWrite[]

// ───────── GET /api/data/policy?kind=&mode=&codes= ─────────
// kind: collect_daily | collect_ticks | collect_minute_al | archive_minute_al
// mode: 각 kind 의 mode (collect_ticks 는 catch_up | range), codes: 콤마 구분 6자리(개수만 정책에 쓴다)
export type CollectKind = 'collect_daily' | 'collect_ticks' | 'collect_minute_al' | 'archive_minute_al'

export interface PolicyData {
  kind: CollectKind
  mode: string | null
  weight: 'heavy' | 'light' | 'local' // 대량 / 소량 / 로컬(API 호출 없음)
  window: Window
  decision: Decision
  suggest_at: string | null // schedule_only·needs_confirm 일 때 제안 예약 시각
  reason: string
  warnings: string[]
  /** 이 수집의 대상 수(모드별). 못 세면 null */
  n_codes: number | null
  /** 예상 소요(초) — 추정이다. 근거는 estimate_basis. 모르면 null */
  eta_sec: number | null
  estimate_basis: string | null // 예: "09-19 실측 86분"
  /** 통합 분봉만: 소피증권 분봉 기준선이 바뀌나 */
  baseline_effect: 'updated' | 'unchanged' | null
  /** 지금 시작할 수 없는 이유(있으면 버튼 비활성 + 사유). 없으면 null */
  blocked: null | {
    code: 'LOCKED' | 'COLLECT_BUSY' | 'MINUTE_REFRESH_RUNNING'
    message: string
    details: Record<string, unknown> // LOCKED 면 owner(LockOwner)
  }
}

// ─────── GET /api/data/stale?dataset=daily&sophie_only= ───────
export interface StaleRow {
  code: string
  name: string | null
  last: string // 마지막 날짜
  days_behind: number // 기준일 − last (달력일)
  sophie: boolean // 소피증권 유니버스
  inactive: string | null // 거래 중단·상장폐지 추정 사유(있으면 받아도 소용없음)
}
export interface StaleData {
  dataset: string
  reference_date: string | null
  rows: StaleRow[]
}

// ─────── GET /api/data/gaps?dataset=daily&days=120 ───────
export interface GapRow {
  date: string
  codes: number
  share: number // 0~1, 그날 데이터가 있는 종목 비율
}
export interface GapsData {
  dataset: string
  days: number
  threshold: number // 강조 기준(0.9)
  rows: GapRow[] // 오래된 날부터
}

// ─────── GET /api/data/quality?dataset=daily&since=&limit=200 ───────
export type QualityKind = 'ohlc' | 'nonpositive' | 'duplicate_date' | 'jump' | 'zero_volume_run'
export interface QualityIssue {
  code: string
  name: string | null
  date: string
  kind: QualityKind
  detail: string
}
export interface QualityData {
  dataset: string
  since: string | null
  rows_checked: number
  counts: Record<QualityKind, number>
  issues: QualityIssue[] // 최대 limit, counts 는 전체 건수
}

// ───────────────── GET /api/data/tick-window ─────────────────
export type TickDateStatus = 'collected' | 'partial' | 'missing' | 'pending'
export interface TickDate {
  date: string
  status: TickDateStatus // pending = 오늘 체결(장 마감 전이라 아직 못 받음)
  collected_codes: number
  expected_codes: number
  days_left: number // 이 날짜가 조회창에서 밀려나기까지 남은 거래일(0 = 내일 사라짐)
  missing_count: number
  missing_sample: string[] // 빠진 종목 코드 앞 20개
}
export interface TickGivenUp {
  code: string
  name: string | null
  date: string
  attempts: number
  days_left: number | null // 이미 창 밖이면 null
}
export interface TickNight {
  night: string // 그날 밤 날짜
  started: string | null
  finished: string | null
  attempts: number
  collected_pairs: number
  remaining_pairs: number
  deferred: number
}
export interface TickWindowData {
  verdict: Verdict
  reason: string
  window_days: number
  universe: string
  min_days_left: number | null
  dates: TickDate[] // 오래된 날부터
  auto: {
    schedule: 'tick_nightly'
    enabled: boolean
    next_run: string | null
    last_night: TickNight | null
    given_up: TickGivenUp[]
  }
  note: string
}

// ───────────────────── GET /api/data/archive ─────────────────────
export interface SpanBucket {
  label: string // "0–20일" 처럼
  codes: number
}
export interface ArchiveData {
  verdict: Verdict
  reason: string
  codes_cache: number
  codes_archive: number
  missing_vs_cache: number
  missing_codes: string[] // 최대 50
  last_merge_at: string | null // 마지막 병합 시각(state/datahub/archive_state.json)
  first_date: string | null // 보관소 전체에서 가장 이른 날
  last_date: string | null
  span_buckets: SpanBucket[] // 종목별 보관 기간(달력일) 분포
}

// ───────────────── GET /api/data/schedules ─────────────────
export type ScheduleOwner = 'hub' | 'watchdog' | '8765' | 'sophie'
export interface ScheduleRun {
  job_id: string | null
  started: string
  finished: string | null
  result: string // "빠진 150쌍 중 150 수집"
  planned: number | null // 계획한 쌍/종목
  received: number | null
  remaining: number | null
  deferred: number | null
  ok: boolean | null
}
export interface ScheduleRow {
  id: string // daily_report, minute_refresh, top35_live, sophie_restart, sophie_rebuild, tick_nightly, daily_catchup, minute_archive, freshness_check
  label: string
  owner: ScheduleOwner
  when: string // 사람 말 ("매일 20:15 (+재시도)")
  does: string
  enabled: boolean | null // 외부 소유는 null(관측만)
  editable: boolean // 허브 소유만 true
  time: string | null // 변경 가능한 시각 "HH:MM" (허브 소유 중 시각이 있는 것)
  last_started: string | null
  last_finished: string | null
  last_ok: boolean | null
  last_result: string | null
  next_expected: string | null
  missed: boolean
  missed_note: string | null // 예: "18일째 기록 없음"
  runs: ScheduleRun[] // 허브 소유만, 최근 14회. 외부는 빈 배열
}
export type SchedulesData = ScheduleRow[]

/** PATCH /api/data/schedules/{id} — 허브 소유만(외부는 409 NOT_HUB_OWNED). 준 키만 바꾼다. 응답은 바뀐 ScheduleRow */
export interface SchedulePatch {
  enabled?: boolean
  time?: string // "HH:MM"
}

// ───────────────── GET /api/data/alerts ─────────────────
export interface AlertRule {
  id: AlertRuleId
  title: string
  when: string // 조건 설명(카탈로그)
  enabled: boolean
  default_enabled: boolean
  last_sent: string | null
  last_message: string | null
}
export interface AlertsData {
  rules: AlertRule[]
  active: ActiveAlert[]
}
/** PATCH /api/data/alerts/{id} — 응답은 바뀐 AlertRule */
export interface AlertPatch {
  enabled: boolean
}

// ───────────────── GET /api/data/sophie ─────────────────
// datahub.sophie.overview() 반환 그대로.
export interface SophieData {
  engine: { up: boolean; healthz: number | null; pid: number | null; started_at: string | null; stale_day: boolean }
  hours: SophieHours
  minute_refresh: {
    running: boolean
    last_started: string | null
    last_finished: string | null
    last_result: string | null // "완료 · 실패 13종목 · 보유 2041종목"
    next_due: string // "2026-10-03 (토) 09:00 이후"
  }
  baseline: { data_updated: string | null; dist_updated: string | null; in_sync: boolean; applies: string }
  universe_daily: { n_codes: number; stale_count: number; stale_inactive_count: number }
  restart: { last_midnight: string | null; days_since: number | null; last_rebuild: string | null }
  contract: string[] // 연계 계약 10개 한 줄 요약(§2.4.9)
}

// ───────────────── 수집 작업 제출 (POST) ─────────────────
// 공통: when=now 인데 정책이 schedule_only → 422 SOPHIE_MARKET_HOURS, needs_confirm 인데 confirm≠true → 422 SOPHIE_LIVE_CONFIRM.
//       when=scheduled 는 scheduled_at 필수(ISO, 야간 구간). 그 밖의 오류는 §6.
export interface CollectWhen {
  when: 'now' | 'scheduled'
  scheduled_at?: string | null
  confirm?: boolean
}

/** POST /api/data/jobs/collect-daily */
export interface CollectDailyRequest extends CollectWhen {
  mode: 'stale' | 'all' | 'codes'
  codes?: string[] // mode=codes 일 때 1개 이상, 각 ^[0-9A-Z]{6}$
}

/** POST /api/data/jobs/collect-ticks */
export type CollectTicksRequest =
  | ({ mode: 'catch_up' } & CollectWhen)
  | ({
      mode: 'range'
      start: string // 조회창 안 날짜(밖이면 422 OUT_OF_TICK_WINDOW)
      end: string
      universe: 'default' | 'codes'
      codes?: string[]
      concurrency: number // 1~6
    } & CollectWhen)

/** POST /api/data/jobs/collect-minute-al */
export interface CollectMinuteAlRequest extends CollectWhen {
  mode: 'sophie_baseline' | 'all_cached' | 'codes' | 'deep_archive'
  codes?: string[] // codes 1~500, deep_archive 1~300
  days?: number | null // deep_archive 만: 20~250
}

/** POST /api/data/jobs/archive-minute-al — 로컬(API 호출 없음)이라 본문 없음 */
export type ArchiveRequest = Record<string, never>

/** 202 응답 */
export interface JobAccepted {
  job_id: string
  status: 'scheduled' | 'queued'
  scheduled_at: string | null
}
/** collect-ticks catch_up 인데 빠진 게 없으면 200 */
export interface NothingToDo {
  nothing_to_do: true
}
export type CollectResponse = JobAccepted | NothingToDo

/** POST /api/data/tick-window/retry — 응답 {retried: 되돌린 쌍 수} */
export interface TickRetryRequest {
  pairs: { code: string; date: string }[] | 'all'
}
export interface TickRetryResponse {
  retried: number
}

// ───────────────── 허브 오류 코드 (§6 + 이 API) ─────────────────
// 409 LOCKED(details.owner: LockOwner) · 409 COLLECT_BUSY · 409 MINUTE_REFRESH_RUNNING · 409 NOT_HUB_OWNED
// 422 SOPHIE_MARKET_HOURS(details.suggest_at) · 422 SOPHIE_LIVE_CONFIRM(details.suggest_at) · 422 OUT_OF_TICK_WINDOW
// 400 VALIDATION_ERROR(details.fieldErrors) · 404 NOT_FOUND(없는 데이터셋·일정·규칙)
