// 허브 API 실례 — 화면 테스트의 고정 값이자, 계약(types/data.ts)의 "이 모양 그대로" 예시.
// 값은 설계서 §4.2 의 예와 2026-09-25 실제 상태(일봉 09-23, 통합 분봉 09-04, 보관소 비어 있음)를 따랐다.
// 타입으로 검사되므로 계약이 바뀌면 여기가 먼저 컴파일 오류를 낸다.
import type {
  AlertsData,
  ArchiveData,
  DatasetStatus,
  GapsData,
  LedgerData,
  LocksData,
  OverviewData,
  PolicyData,
  QualityData,
  SchedulesData,
  SophieData,
  StaleData,
  TickWindowData,
} from '@/types/data'

const ds = (o: Partial<DatasetStatus> & Pick<DatasetStatus, 'id' | 'label' | 'basis'>): DatasetStatus => ({
  verdict: 'good',
  reason: '최신',
  retention: 'keep',
  last_write: null,
  lock: null,
  ...o,
})

export const overview: OverviewData = {
  now: {
    ts: '2026-09-25T10:12:00',
    window: 'market',
    sophie_hours: { connect_from: '08:20', open: '09:00', close: '15:30', connect_to: '20:10', source: 'kospi-theme-engine/config.yaml' },
    bulk: { decision: 'schedule_only', suggest_at: '2026-09-25T20:10:00' },
  },
  datasets: [
    ds({
      id: 'daily', label: '일봉', basis: 'KRX', verdict: 'bad', reason: '소피증권 유니버스 3종목이 기준일보다 오래됨',
      n_codes: 2577, reference_date: '2026-09-24', expected_date: '2026-09-24', stale_count: 376, stale_inactive_count: 373,
      sophie_stale_count: 3,
      last_write: { ts: '2026-09-24T16:41:10', writer: 'backfill_universe', source: '야간 갱신', ok: true },
      lock: { resource: 'daily_minute', held: false },
    }),
    ds({ id: 'minute_krx', label: '1분봉(KRX)', basis: 'KRX', n_codes: 2500, reference_date: '2026-09-24', expected_date: '2026-09-24', stale_count: 0, sophie_stale_count: 0, lock: { resource: 'daily_minute', held: false } }),
    ds({ id: 'index', label: '지수 일봉·분봉', basis: 'KRX', n_codes: 4, reference_date: '2026-09-24', expected_date: '2026-09-24', stale_count: 0, sophie_stale_count: 0, lock: { resource: 'daily_minute', held: false } }),
    ds({
      id: 'minute_al', label: '통합 1분봉 캐시', basis: 'AL', verdict: 'bad', reason: '최빈 최신일 2026-09-04 (21일 전)',
      retention: 'overwrite_20d', n_codes: 2041, last_date_mode: '2026-09-04', age_days: 21, behind_share: 0.83,
      lock: { resource: 'minute_al', held: false },
    }),
    ds({
      id: 'minute_al_archive', label: '통합 1분봉 보관소', basis: 'AL', verdict: 'bad', reason: '보관 누락 2041종목', retention: 'forever',
      codes_cache: 2041, codes_archive: 0, missing_vs_cache: 2041, missing_codes: ['005930', '000660'],
      lock: { resource: 'minute_al', held: false },
    }),
    ds({
      id: 'tick_al', label: '통합 체결', basis: 'AL', verdict: 'warn', reason: '미수집 160쌍, 가장 급한 날짜 남은 1거래일', retention: 'forever_unrecoverable',
      n_codes: 174, window_missing: 160, min_days_left: 1, lock: { resource: 'tick_al', held: false },
    }),
    ds({ id: 'sophie_reference', label: '소피증권 기준 데이터', basis: 'derived', data_updated: '2026-09-23T16:55', dist_updated: '2026-09-23T16:55', in_sync: true, diff_files: [] }),
    ds({ id: 'sophie_live_logs', label: '소피증권 실시간 기록', basis: 'derived', retention: 'forever_unrecoverable', backup_date: '2026-09-24', found: ['kospi-theme-engine/backups/surge_20260924.jsonl.gz'] }),
    ds({ id: 'reference_static', label: '종목명·업종·테마', basis: 'reference' }),
    ds({ id: 'high120', label: '120일 신고가', basis: 'derived', retention: 'regenerable', n_codes: 1, reference_date: '2026-09-24', expected_date: '2026-09-24', stale_count: 0, sophie_stale_count: 0 }),
    ds({ id: 'daily_all_cache', label: '일봉 합본', basis: 'derived', retention: 'regenerable' }),
  ],
  activity: [
    { source: '야간 갱신', writer: 'backfill_universe', lock: 'daily_minute', dataset: 'daily', state: '실행 중', done: 820, total: 2016, since: '2026-09-25T16:00:41', run: 'b3f1a0', job_id: null },
    { source: '허브', writer: 'tick_collect_804_828_al', lock: 'tick_al', dataset: 'tick_al', state: '잠금 대기', done: null, total: null, since: '2026-09-25T20:15:02', run: null, job_id: '20260925-201502-a1b2c3' },
  ],
  alerts_active: [
    { id: 'archive_behind', title: '보관 누락', target: 'minute_al_archive', message: '통합 분봉 보관소에 빠진 캐시 2041종목 — 보관 누락', first_seen: '2026-09-25T09:10:00' },
  ],
  daily_catchup: { date: '2026-09-25', received: 40, remaining: 2, sophie_remaining: 0, deadline_passed: true },
}

export const overviewNight: OverviewData = {
  ...overview,
  now: { ...overview.now, ts: '2026-09-25T21:00:00', window: 'night', bulk: { decision: 'allow_now', suggest_at: null } },
  alerts_active: [],
  activity: [],
  daily_catchup: null,
}

export const locks: LocksData = [
  { resource: 'daily_minute', covers: ['daily', 'minute_krx', 'index'], held: true,
    owner: { pid: 4242, cmdline: 'python backfill_universe.py', since: '2026-09-25T16:00:41', alive: true, dead: false, source: '야간 갱신' } },
  { resource: 'minute_al', covers: ['minute_al', 'minute_al_archive'], held: false, owner: null },
  { resource: 'tick_al', covers: ['tick_al'], held: false, owner: null },
]

const policyBase: PolicyData = {
  kind: 'collect_minute_al', mode: 'sophie_baseline', weight: 'heavy', window: 'market', decision: 'schedule_only',
  suggest_at: '2026-09-25T20:10:00', reason: '소피증권 정규장 시간 — 대량 수집은 장 마감 뒤(20:10) 예약만 됩니다',
  warnings: ['오늘 통합 분봉은 NXT 마감(20:00) 전이면 잘립니다 — 다음 갱신 때 다시 받아집니다', 'REST 한도는 앱키를 나눠도 계정 단위로 공유됩니다'],
  n_codes: 288, eta_sec: 5160, estimate_basis: '09-19 실측 86분', baseline_effect: 'updated', blocked: null,
}
export const policy = {
  scheduleOnly: policyBase,
  needsConfirm: { ...policyBase, window: 'sophie_live', decision: 'needs_confirm', reason: '소피증권 가동 시간(REST 한도 공유) — 확인 후 실행하거나 20:10 예약하세요' } satisfies PolicyData,
  allowNow: { ...policyBase, window: 'night', decision: 'allow_now', suggest_at: null, reason: '소피증권이 가동 중이 아닌 시간(야간·주말·휴장일)', warnings: [] } satisfies PolicyData,
  blockedRefresh: {
    ...policyBase, window: 'night', decision: 'allow_now', suggest_at: null, reason: '소피증권이 가동 중이 아닌 시간(야간·주말·휴장일)',
    blocked: { code: 'MINUTE_REFRESH_RUNNING', message: '소피증권 분봉 기준선 갱신이 실행 중입니다', details: {} },
  } satisfies PolicyData,
  local: { ...policyBase, kind: 'archive_minute_al', mode: null, weight: 'local', window: 'market', decision: 'allow_now', suggest_at: null,
    reason: 'API 를 안 쓰는 로컬 작업', warnings: [], n_codes: null, eta_sec: null, estimate_basis: null, baseline_effect: null } satisfies PolicyData,
}

export const stale: StaleData = {
  dataset: 'daily', reference_date: '2026-09-24',
  rows: [
    { code: '005930', name: '삼성전자', last: '2026-09-22', days_behind: 2, sophie: true, inactive: null },
    { code: '123456', name: '가나다', last: '2026-08-01', days_behind: 54, sophie: false, inactive: '거래정지' },
  ],
}

export const gaps: GapsData = {
  dataset: 'daily', days: 5, threshold: 0.9,
  rows: [
    { date: '2026-09-18', codes: 2570, share: 0.997 },
    { date: '2026-09-21', codes: 2571, share: 0.998 },
    { date: '2026-09-22', codes: 2100, share: 0.815 },
    { date: '2026-09-23', codes: 2575, share: 0.999 },
    { date: '2026-09-24', codes: 2577, share: 1 },
  ],
}

export const quality: QualityData = {
  dataset: 'daily', since: null, rows_checked: 3_100_000,
  counts: { ohlc: 0, nonpositive: 1, duplicate_date: 0, jump: 2, zero_volume_run: 1 },
  issues: [
    { code: '005930', name: '삼성전자', date: '2018-05-04', kind: 'jump', detail: '전일 대비 -98.0%' },
    { code: '000660', name: 'SK하이닉스', date: '2026-01-05', kind: 'nonpositive', detail: '0 이하 가격' },
  ],
}

export const tickWindow: TickWindowData = {
  verdict: 'bad', reason: '미수집 160쌍, 가장 급한 날짜 남은 1거래일', window_days: 5, min_days_left: 1,
  universe: '날짜별 거래대금 상위 35 합집합(초대형주 제외)',
  dates: [
    { date: '2026-09-18', status: 'collected', collected_codes: 150, expected_codes: 150, days_left: 0, missing_count: 0, missing_sample: [] },
    { date: '2026-09-21', status: 'partial', collected_codes: 140, expected_codes: 150, days_left: 1, missing_count: 10, missing_sample: ['386380'] },
    { date: '2026-09-22', status: 'missing', collected_codes: 0, expected_codes: 150, days_left: 2, missing_count: 150, missing_sample: ['005930'] },
    { date: '2026-09-23', status: 'collected', collected_codes: 150, expected_codes: 150, days_left: 3, missing_count: 0, missing_sample: [] },
    { date: '2026-09-24', status: 'pending', collected_codes: 0, expected_codes: 150, days_left: 4, missing_count: 150, missing_sample: [] },
  ],
  auto: {
    schedule: 'tick_nightly', enabled: true, next_run: '2026-09-25T20:15:00',
    last_night: { night: '2026-09-24', started: '2026-09-24T20:15:01', finished: '2026-09-24T23:40:12', attempts: 1, collected_pairs: 150, remaining_pairs: 12, deferred: 2 },
    given_up: [{ code: '386380', name: '테스트종목', date: '2026-09-21', attempts: 3, days_left: 1 }],
  },
  note: '키움 체결 조회창은 약 20거래일 — 밖으로 밀려난 날짜는 다시 받을 수 없음',
}

export const archive: ArchiveData = {
  verdict: 'bad', reason: '보관 누락 2041종목', codes_cache: 2041, codes_archive: 0, missing_vs_cache: 2041, missing_codes: ['005930'],
  last_merge_at: null, first_date: null, last_date: null,
  span_buckets: [{ label: '0–20일', codes: 0 }, { label: '21–40일', codes: 0 }],
}

export const schedules: SchedulesData = [
  { id: 'daily_report', label: '야간 갱신', owner: 'watchdog', when: '평일 16:00 이후 1회', does: 'top35·백필·지수·신고가·리포트', enabled: null, editable: false, time: null,
    last_started: '2026-09-24T16:00:41', last_finished: '2026-09-24T16:41:10', last_ok: true, last_result: '완료', next_expected: '2026-09-25T16:00:00',
    missed: false, missed_note: null, runs: [] },
  { id: 'sophie_restart', label: '소피증권 자정 재기동', owner: 'sophie', when: '매일 00:05', does: '엔진 재기동', enabled: null, editable: false, time: null,
    last_started: '2026-09-07T00:05:25', last_finished: null, last_ok: null, last_result: null, next_expected: '2026-09-26T00:05:00',
    missed: true, missed_note: '18일째 기록 없음', runs: [] },
  { id: 'tick_nightly', label: '체결 야간 수집', owner: 'hub', when: '매일 20:15 (+재시도)', does: '빠진 (종목,날짜) 전부 수집 → 압축', enabled: true, editable: true, time: '20:15',
    last_started: '2026-09-24T20:15:01', last_finished: '2026-09-24T23:40:12', last_ok: true, last_result: '빠진 150쌍 중 138 수집', next_expected: '2026-09-25T20:15:00',
    missed: false, missed_note: null,
    runs: [{ job_id: '20260924-201501-aaaaaa', started: '2026-09-24T20:15:01', finished: '2026-09-24T23:40:12', result: '빠진 150쌍 중 138 수집', planned: 150, received: 138, remaining: 12, deferred: 2, ok: true }] },
]

export const alerts: AlertsData = {
  rules: [
    { id: 'archive_behind', title: '보관 누락', when: '캐시 파일이 보관소보다 새것', enabled: true, default_enabled: true, last_sent: '2026-09-25T09:10:00', last_message: '통합 분봉 보관소에 빠진 캐시 2041종목' },
    { id: 'unledgered_write', title: '장부 없는 쓰기', when: '관문을 안 거친 쓰기', enabled: false, default_enabled: false, last_sent: null, last_message: null },
  ],
  active: overview.alerts_active,
}

export const sophie: SophieData = {
  engine: { up: true, healthz: 401, pid: 37688, started_at: '2026-09-25T00:05:25', stale_day: false },
  hours: overview.now.sophie_hours,
  minute_refresh: { running: false, last_started: '2026-09-19T19:46', last_finished: '2026-09-19T21:13', last_result: '완료 · 실패 13종목 · 보유 2041종목', next_due: '2026-10-03 (토) 09:00 이후' },
  baseline: { data_updated: '2026-09-23T16:55', dist_updated: '2026-09-23T16:55', in_sync: true, applies: '다음 엔진 재기동부터' },
  universe_daily: { n_codes: 2158, stale_count: 3, stale_inactive_count: 0 },
  restart: { last_midnight: '2026-09-07T00:05:25', days_since: 18, last_rebuild: '2026-09-24T15:40:00' },
  contract: ['소피증권 데이터는 소피증권 스크립트로만 쓴다', '소피증권 엔진(EXE)은 수정하지 않는다'],
}

export const ledger: LedgerData = [
  { run: 'b3f1a0', ts: '2026-09-25T16:00:41', ended: null, duration_sec: null, lock: 'daily_minute', writer: 'backfill_universe', source: '야간 갱신', trigger: 'external',
    job_id: null, state: '실행 중', done: 820, total: 2016, detail: { mode: 'stale', codes: 2016 }, error: null },
  { run: 'c4d2b1', ts: '2026-09-24T16:00:41', ended: '2026-09-24T16:41:10', duration_sec: 2429, lock: 'daily_minute', writer: 'backfill_universe', source: '야간 갱신', trigger: 'external',
    job_id: null, state: '완료', done: 376, total: 376, detail: null, error: null },
  { run: 'd5e3c2', ts: '2026-09-23T19:00:00', ended: '2026-09-23T19:00:09', duration_sec: 9, lock: 'minute_al', writer: 'fetch_minute', source: '소피증권', trigger: 'external',
    job_id: null, state: '중단됨', done: 3, total: 288, detail: null, error: null },
]
