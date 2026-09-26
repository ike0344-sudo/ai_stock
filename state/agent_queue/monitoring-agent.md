# monitoring-agent 큐

(비어 있음)

- [x] (lead 지시 2026-09-25, 데이터 허브 module-1 후속 — 사용자 승인 범위) **8765 대시보드 재시작 — top35 가 새 쓰기 관문을 쓰게**

      data-agent 가 `backtesting/updater.py` 의 `update_top35` 를 `datahub.write("daily_minute")`(잠금 + 장부) 안으로 넣었다
      (설계서 `docs/02-design/features/backtest-studio.design.md` §2.4.3·§11.5). 8765 프로세스(PID 23256, 09-23 19:31 기동)는
      옛 코드를 메모리에 들고 있어서, **재시작해야** 15:40 top35 자동 갱신이 관문을 거친다.
      **오늘(09-25)은 추석 휴장**이라 애프터장 베이스라인(15:33~15:39)·실거래와 겹칠 일이 없다 — 지금이 적기.

      1. 네가 09-23 에 쓴 절차(`state/agent_reports/monitoring-agent_20260923-1940_dashboard_tailscale.md`)대로 재시작하라 —
         8765 는 워치독 Http 대상이다. 대시보드 프로세스만 내리고(`cli dashboard` 인 것만), 기동은 워치독과 같은 인자
         (`--port 8765 --host 100.126.113.127`)로. 워치독이 동시에 하나 더 띄우지 않게 주의(포트 충돌).
      2. 확인: 새 PID · 기동 시각이 `backtesting/updater.py` 수정 시각보다 뒤 · http://100.126.113.127:8765/ 응답 ·
         워치독 한 주기(5분) 뒤에도 PID 불변(재시작 루프 없음) · **나스닥 감시 PID 불변** · 소피증권(8770) 무영향
      3. 15:40 top35 자동 갱신이 오늘 돌면 `python -m datahub ledger` 에 `update_top35 [daily_minute]` 기록이 남는지 확인
         (휴장이라 안 돌거나 금방 끝나도 정상 — 기록 유무만 보고)

      **하지 말 것**: 워치독 스크립트 수정(허브 서버 대상 추가는 module-2 몫), 실주문·KIWOOM_IS_MOCK, 소피증권 엔진 건드리기, git commit.
      보고: STATUS.md 자기 행 + `state/agent_reports/monitoring-agent_<날짜시각>_8765_restart_datahub.md`.

- [x] (lead 지시 2026-09-25, **사용자 승인 "module-2 시작"**) **module-2 서버 쪽 1단계 — 작업 실행기 + 8780 서버 골격 + 화면 골격**
      설계서 `docs/02-design/features/backtest-studio.design.md` §2.1·§2.2(a)(e) · §3.3(job.json·progress·log·cancel.flag) · §4.1(작업 공통 API) ·
      §6 오류 봉투 · §7 보안 · §9.3 계층 규칙 · §10.3 환경변수 · §11.1 파일 구조를 먼저 읽어라.
      **data-agent 가 동시에 `datahub/` 의 정책·상태·수집 명령을 만든다** — `datahub/*` 는 건드리지 마라. 허브 API 라우터·데이터 허브 페이지·
      일정 실행은 이번 항목이 끝난 뒤 lead 가 따로 넣는다.
      1. `jobrunner/` — `store.py`(state/jobs/<id>/, tmp+교체, 쓰는 주체 분리: job.json 은 worker·dispatcher, cancel.flag 는 API) ·
         `spawn.py`(분리 실행: `CREATE_NEW_PROCESS_GROUP|CREATE_BREAKAWAY_FROM_JOB` 실패 시 폴백 — `backtesting/dashboard_server.spawn_detached`
         와 같은 플래그·같은 이유, BELOW_NORMAL 우선순위, psutil 생존·create_time·자식까지 취소) · `dispatcher.py`(서버 스레드: scheduled/queued →
         그룹 한도 collect 1 · local 1 · compute 2 → spawn, 죽은 워커 정리, 취소 반영) · `worker.py`(`python -m jobrunner.worker <id>` →
         job.json `handler` 를 **허용 접두사 `datahub.jobs:`·`studio.application.jobs:` 만** import) · `child.py`(자식 명령 실행 + 출력 줄을 log.txt 로,
         비밀값 가림 + 줄 콜백) · `mask.py`(.env 값·`Bearer` 토큰 가림). jobrunner 는 datahub·studio·backtesting·fastapi 를 import 하지 않는다
      2. 서버: `studio/__main__.py`(uvicorn, **127.0.0.1 고정**, `STUDIO_PORT` 기본 8780, dispatcher 스레드 시작) · `studio/api/app.py`
         (Origin ≠ Host 인 상태 변경 요청 403, CORS 없음, 본문 256KB, §6 오류 봉투, `static/studio/` 정적 제공) · `studio/api/routes/jobs.py`
         (`GET /api/jobs`·`/api/jobs/{id}`·`/log?offset=`·`POST /cancel`, ID 정규식) · `GET /api/meta/status`(지금은 실행 중 작업 수만)
         · `POST /api/jobs/backtest` → `studio.application.jobs:run_backtest_job`(backtest_service 호출 + run_store 저장, 얇은 처리기)
      3. `requirements.txt` 에 `fastapi`, `uvicorn`, `httpx  # 테스트` · `run_studio.bat`
      4. 프론트 골격 `frontend/`(Vite + React + TS + antd + dayjs + echarts + @tanstack/react-query + react-router-dom HashRouter):
         AppShell(메뉴 4개)·StatusBar·EChart 래퍼·`api/client.ts`(§6 봉투 해석)·빈 페이지 4개, `vite.config.ts` outDir `../static/studio`,
         `npm run build` 결과 커밋 대상(`static/studio/`). `.gitignore` 에 `node_modules/`·`frontend/playwright-report/`·`frontend/test-results/`
      5. 테스트: `tests/jobrunner/`(저장·분리 실행·취소·예약 시각·그룹 한도·handler 허용 목록·가림) + `tests/studio/api/`(§8.3 L1 중 12·16·17·18·19·13 —
         Origin 위조 403, 없는 ID 404, 백테스트 잡 → run_id → succeeded(인라인 러너), 취소, 로그 이어받기·가림)
      6. **워치독 등록은 아직 하지 마라** — 서버가 안정된 뒤 따로(돌던 워치독 재기동 절차 필요).
      **하지 말 것**: `datahub/*`·`backtesting/*`·엔진·조건식 수정, 8765 건드리기, 실주문, git commit.
      보고: 시작·50%·끝에 STATUS.md, 자세한 건 `state/agent_reports/monitoring-agent_<날짜시각>_module2_server.md`.
      **"그대로 믿지 말고 검증해라"** — 설계서 API·보안 규칙이 기존 8765 관례와 부딪히면 먼저 보고.

- [x] (lead 지시 2026-09-25, module-2 2단계 — 사용자 승인 범위) **허브 API 계약 확정 + 데이터 허브 화면**
      네 1단계 수용(lead 검증: 92 passed, 예비 포트 스모크 — 위조 Host 403·교차 출처 POST 403·/docs 404). launcher 이중 기동·Host 검사·413 은
      설계서 §7·§6 에 반영했다. data-agent 는 지금 허브 1단계(정책·상태·품질·소피증권·수집 명령·알림)를 만들고 있고, 그다음 `datahub/api.py`
      (FastAPI 라우터 `/api/data/*`)와 수집 작업 처리기를 만든다. **화면과 API 가 어긋나지 않게 계약을 먼저 고정한다.**
      1. **계약**: 설계서 §4.1 의 `/api/data/*` 전부(overview·datasets/{id}·activity·ledger·locks·policy·stale·gaps·quality·tick-window·archive·
         schedules(+PATCH)·alerts(+PATCH)·sophie·jobs/collect-daily·collect-ticks·collect-minute-al·archive-minute-al·tick-window/retry)의
         요청·응답 모양을 `frontend/src/types/data.ts` 로 확정하라. §4.2 에 있는 건 그대로, 모양이 덜 적힌 것(ledger·locks·stale·gaps·quality·
         archive·activity·alerts)은 §2.4.5·§2.4.8·§5.4 체크리스트가 요구하는 칸으로 네가 정해라. 같은 내용을 사람이 읽는 표로
         `docs/02-design/api/datahub-api.md` 에 쓰고, **data-agent 에 편지**(`state/agent_mail/data-agent/`)로 "이 모양 그대로 구현" 을 알려라.
      2. **데이터 허브 화면**(`#/hub/...` 6탭: 개요·수집·일정·장부·품질·소피증권) — 설계서 §5.4 "데이터 허브" 체크리스트 전부. 수집 버튼은
         `/api/data/policy` 판정에 따라 "지금 / 확인 후 / 20:10 예약" 으로 바뀐다. 상태 바에 시간대·일봉 기준일·알림 수(overview 에서).
         **API 가 아직 없으면(404) 가짜 값을 채우지 말고 "허브 API 준비 중" 으로 표시**(네가 1단계에서 지킨 원칙 그대로). 테스트는 고정 JSON 으로.
      3. `npm run build` → `static/studio/` 갱신, 헤드리스 스크린샷으로 탭 6개 렌더 확인(가능한 만큼).
      **하지 말 것**: `datahub/*`(data-agent 몫 — 모양이 안 맞으면 편지로), 워치독 등록(허브 일정이 붙은 뒤 한 번에), 8765·나스닥 감시, git commit.
      보고: STATUS.md 자기 행 + `state/agent_reports/monitoring-agent_<날짜시각>_module2_hub_ui.md`.

- [x] (lead 지시 2026-09-25, module-2 마무리 — 사용자 승인 범위) **워치독에 8780 허브·스튜디오 서버 등록(상시 가동)**
      네 허브 화면 수용(lead 확인: vitest 51 passed, 빌드 결과물·계약 문서·data-agent 편지 존재). data-agent 가 수집 처리기·일정·허브 API 를
      만드는 동안, 서버를 상시 가동 상태로 만들어 둔다 — 그래야 허브 일정(매일 밤 체결 수집 등)이 붙자마자 돈다.
      1. `nasdaq_monitor_watchdog.ps1` 을 **먼저 백업**하고(`state/_tmp/` 등), `$targets` 에 한 줄만 추가:
         `@{ Type = "Http"; Match = "-m studio(\s|$)"; Args = @("-m", "studio"); LogName = "studio_server"; Url = "http://127.0.0.1:8780/api/meta/status" }`
         — 이 파일은 세션 시작 전부터 커밋 안 된 수정이 있다. 그 수정은 건드리지 말고 **이 한 줄만**. 파일 인코딩·BOM 유지(**BOM 있음 EF BB BF — 반드시 유지**, lead 정정 17:25).
         Http 프로브가 Host 루프백 검사를 통과하는지(127.0.0.1:8780) 확인.
      2. 돌던 워치독은 옛 스크립트를 들고 있다 → 네 09-23 절차대로 시작폴더 VBS 를 explorer 경유로 재기동(도구 세션 자식이 되지 않게).
      3. 확인: 워치독 1개만 · 8780 이 워치독이 띄운 프로세스로 살아 있음(손으로 띄운 것 있으면 정리) · 한 주기(5분) 뒤 PID 불변 ·
         **나스닥 감시 PID 10832 불변** · 8765(PID 19840)·소피증권 쪽 봇 무영향 · `http://127.0.0.1:8780/` 화면 응답
      4. 허브 API·일정 연결(`datahub.api.router` 포함, `datahub.scheduler` 시작)은 **data-agent 가 끝났다고 편지할 때** 따로 한다 — 이번엔 등록만.
      문제가 생기면 백업으로 즉시 되돌리고 보고. git commit 금지. 보고: STATUS.md + `state/agent_reports/monitoring-agent_<날짜시각>_watchdog_8780.md`.

- [x] (lead 지시 2026-09-25 21:45, 워치독 8780 보고서 후속) **워치독 재기동 사유 기록 — 18:44 8765 재기동 원인을 못 찾은 이유 없애기**
      먼저 네 결정요청 답: **관문 무기한 대기는 그대로 둔다.** top35 갱신은 데몬 스레드(`top35_job.py:73`·`:213`)라 대기가 8765 HTTP 를 막지 않고,
      허브 일정은 정책상 소피증권 시간(08:20~20:10) 밖에서만 돈다. 20:34 top35 는 18:44 재기동으로 메모리의 "오늘 성공"이 지워져 한 번 더 돈 것(무해).
      남는 문제는 원인 불명의 재기동이다: 워치독은 5초 프로브 **한 번** 실패하면 바로 죽이고 다시 띄우는데, 이유를 안 남기고 stdout 로그까지 덮어쓴다.
      8765 는 Tailscale 주소(`--host 100.126.113.127`)로 프로브하니 망 순간 끊김·부하로 5초 초과도 후보다(추정, 증거 없음).
      1. 재기동 직전 한 줄 append → `state/watchdog/restarts.log`: 시각·LogName·죽이는 PID·프로브 실패 내용(예외 메시지 또는 상태코드, 걸린 시간 / Heartbeat 면 마지막 갱신 시각)
      2. 재기동 전에 기존 `<LogName>.log`·`.err.log` 를 `<LogName>.prev.log`·`.prev.err.log` 로 옮겨 한 세대 보존
      3. **동작은 바꾸지 마라**(재시도 횟수·타임아웃 그대로) — 증거부터 모은다. 바꿀지는 기록이 쌓인 뒤 판단
      백업 → 수정(BOM EF BB BF·CRLF 유지, 파서 오류 0) → 09-23 절차 재기동 → 워치독 1개 · 나스닥 10832 · 8765 · 8780 · 소피 봇 PID 불변 확인.
      장중(09:00~15:30) 금지 — 주말 안에. data-agent 의 허브 API 완료 편지가 오면 **그 연결 작업이 먼저**다. git commit 금지. 보고: STATUS.md 한 줄.

- [x] (lead 지시 2026-09-25 21:50, module-2 마지막 — 사용자 승인 범위) **허브 API·일정을 8780 에 연결 + 워치독 경유 재기동 + 첫 실제 야간 수집 관찰**
      재기동 사유 기록 수용. data-agent 편지 `agent_mail/monitoring-agent/20260925-2150_data-agent_hub-api-ready.md` 와
      보고서 `state/agent_reports/data-agent_20260925-2150_datahub_{api,jobs_scheduler}.md` 를 먼저 읽어라.
      1. `studio/api/app.py`: `datahub.api.router` 를 `/api/{rest:path}` 404 캐치올보다 **앞에** include. `app.state.store`·`app.state.dispatcher` 가 라우터가 기대하는 이름인지 확인
      2. `studio/__main__.py`(또는 lifespan): 기동 때 `datahub.scheduler.start(root, store)`, 종료 때 `.stop()`. 두 번 뜨지 않게(서버 1개 = 스케줄러 1개)
      3. **`/api/meta/status` 는 가볍게 유지** — 워치독 프로브가 5초 한 번 실패로 서버를 죽인다. overview(유휴 4초)·체결 조회창(2초) 같은 무거운 허브 계산을 여기에 넣지 마라.
         허브 요약을 상태 바에 넣고 싶으면 별도 엔드포인트나 캐시 값만. 연결 후 `/api/meta/status` 응답 시간을 overview 를 동시에 부르는 상태에서도 재라
      4. 확인: §8.3 #17 Origin 위조 → `POST /api/data/jobs/collect-daily` 403 · 화면 6탭이 실제 허브 응답으로 뜨는지(“준비 중” 없어야 함, 어긋나면 data-agent 에 편지) · vitest·pytest 무회귀
      5. 재기동은 **워치독 경유**: 35796 만 종료 → 다음 주기(≤5분)에 워치독이 새 코드로 띄움 → `state/watchdog/restarts.log` 에 기록되는지도 확인. 나스닥 10832 · 8765 · 워치독 1개 불변
      6. **첫 실제 야간 체결 수집**: 스케줄러는 서버가 뜨면 오늘 밤 회차를 바로 판단한다(빠진 쌍이 있으면 실제 API 로 수집 시작 — 사용자가 원한 기능이고 오늘은 휴장·소피증권 꺼짐이라 REST 경합 없음).
         작업이 생기면 job.json 상태·진행률·`python -m datahub ledger`·log.txt 를 보고 **시작했는지 / 잠금 대기인지 / 실패했는지**만 보고(끝까지 기다릴 필요 없음). 안 생기면 왜 안 생겼는지(빠진 쌍 0? 선행 대기?)
      git commit 금지. 보고: STATUS.md + `state/agent_reports/monitoring-agent_<날짜시각>_hub_wiring.md`.

- [x] (lead 판정 2026-09-25 22:20 — 네 판단요청 답) **8780 생존 판정을 하트비트로 (1안 승인)**
      연결 작업 수용(lead 확인 예정: 테스트 재실행). 1안으로 간다. 단 **하트비트는 서버 이벤트 루프 안(asyncio 작업, lifespan 에서 시작·종료)에서 써라** —
      별도 스레드로 쓰면 이벤트 루프가 멈춰도 하트비트는 계속 나가서 "먹통인데 살아 있음"이 된다. HTTP 를 실제로 답하는 곳이 살아 있을 때만 갱신돼야 한다.
      1. 15초마다 `state/studio/heartbeat.json` = `{updated_at: 유닉스초, pid}` — tmp+교체. 기동 직후 1회 즉시 쓰기. 워치독 `Test-HeartbeatFresh` 가 읽는 형식 그대로
      2. 워치독 8780 줄만 `Type = "Heartbeat"; HeartbeatPath = "state\studio\heartbeat.json"` 로(Match·Args·LogName 그대로, 문턱은 전역 120초). 8765·나스닥 줄은 손대지 마라
      3. 백업 → 수정(BOM·CRLF·단독 CR 0·파서 오류 0) → 서버 코드 반영은 워치독 경유 재기동 → 워치독 재기동(09-23 절차) → 두 주기 동안 재기동 없음·하트비트 15초 갱신 확인,
         나스닥 10832 · 8765 · 워치독 1개 불변
      4. 테스트 1건: 하트비트가 이벤트 루프 작업으로 돈다(스레드 아님) + 파일 형식
      장중 금지(주말 안). git commit 금지. 보고: STATUS.md 한 줄.

- [x] (lead 지시 2026-09-25 22:55, **module-4 백테스트 화면 — 사용자 승인 "module-2 끝나면 4~6 바로"**, 위 하트비트 항목 다음) **백테스트·결과·실행 기록·비교 — API 라우트 + 화면**
      허브 연결 수용(lead 재실행: datahub 107 · studio+jobrunner 370/12 skipped · vitest 54 통과). 설계서 §4.1 "백테스트 스튜디오" 표·§4.2(`POST /api/jobs/backtest`·`/api/conditions/preview`·`GET /api/runs/{id}`)·
      §5.4 BacktestPage·ResultPage·실행 기록/비교 체크리스트·§5.5 판정 기준·§8.3 #13~16·#18~19·§8.4 #6~9·§8.5 L3 #3·#4 를 먼저 읽어라.
      1. API: `/api/meta/indicators`·`/strategies` · `/api/stocks?q=` · `/api/stocks/{code}/bars` · `/api/runs`(목록)·`/{id}`·`/equity`·`/trades`·`/export/trades.csv` · PATCH/DELETE `/api/runs/{id}`(실행 결과만 삭제 — 데이터 아님) ·
         `POST /api/runs/compare`(2~5) · `POST /api/conditions/validate`·`/preview`(`studio/application/screener_service.py`, 최신 거래일 기준) · GET/PUT/DELETE `/api/presets`. 그리드·폴드 API 는 module-5 때
      2. 화면: BacktestPage(모드 탭 4개 — 분봉·틱 탭은 "module-6 준비 중"으로 비활성, 전략 소스 3종, 조건 그룹 편집기, 청산·자금·비용·호환 모드 잠금, 풀이 문장, 오늘 맞는 종목, 검증 오류, 실행 모달·취소) ·
         ResultPage(헤더·경고 배지·지표 카드 전부 + 기존 CLI 줄·차트 전부·거래 표 → 캔들 서랍 앞뒤 30봉) · RunsPage · ComparePage
      3. module-3 점검 D3-4: **일봉 단일 종목 기본값 = 최대 보유 1 · 비중 100%**(지금 기본은 자본 20%만 씀)
      4. 결과 화면의 견고성(비용 민감도·몬테카를로·집중도)은 backtest-agent 가 module-5 에서 summary.robustness 에 넣는다 — 없으면 "없음" 표시(값 지어내지 않기)
      5. 원칙: **정보는 접지 않는다**(요약 칩·접기 금지, 공간은 배치로) · 숫자엔 좋다/보통/나쁘다 판정 색(§5.5) · 쉬운 말
      6. 확인: 라이브 8780 에서 프리셋 → 실행 → 결과 → 거래 클릭(L3 #3) · 복제 → 손절 변경 → 비교(L3 #4) 헤드리스 Chrome 스크린샷 · pytest·vitest 무회귀
      공유 파일(`run_store.py`·`wiring.py`·`application/jobs.py`)은 backtest-agent 도 module-5 로 고친다 — **고치기 직전에 다시 읽고, 전체 덮어쓰기 금지, Edit 로 필요한 부분만**.
      git commit 금지. 보고: STATUS.md + `state/agent_reports/monitoring-agent_<날짜시각>_module4_backtest_ui.md`.

- [x] (**00:10 execution-agent 로 넘김 — 사용자 "지금 바로 고쳐줘", 너는 module-4 계속**) (lead 지시 2026-09-26 00:05) **8765 를 127.0.0.1 과 테일스케일 주소 둘 다에서 받게**
      lead 확인: 8765 는 살아 있다(PID 41388, 18:44~, restarts.log 에 8765 재기동 0건). **테일스케일 주소(100.126.113.127)에만 바인딩**돼 있어 이 PC 에서 `localhost:8765`·`127.0.0.1:8765` 는
      연결 거부(실측) → 사용자에겐 죽은 것으로 보인다. `run_dashboard.bat` 주석·워치독 `$dashboardHost` 의 의도(휴대폰은 테일스케일로, 집 와이파이엔 안 열기)는 유지한다.
      1. `backtesting/dashboard_server.py`·`cli.py`: `--host` 에 쉼표 목록(`127.0.0.1,100.126.113.127`) — 주소마다 `build_server` 로 서버를 하나씩, 같은 핸들러. **127.0.0.1 은 반드시 성공**,
         테일스케일 바인딩이 실패하면(테일스케일이 아직 안 떴을 때) 경고를 남기고 60초마다 다시 시도(로컬은 계속 서비스). 출처 검사 `_origin_is_trusted` 는 Host 기준이라 그대로 동작하는지 테스트
      2. 워치독: 8765 Args 의 `--host` 를 두 주소로, Http 프로브 Url 은 `http://127.0.0.1:8765/`(프로세스 생존), 222~223행 거래대금 순위 호출도 127.0.0.1 로.
         `monitor-dashboard`(텔레그램 다운 알림)는 테일스케일 주소 그대로 — 휴대폰 접속이 끊긴 걸 알리는 용도. `run_dashboard.bat` 도 같게, 주석 갱신
      3. 백업 → 수정(BOM·CRLF·단독 CR 0·파서 오류 0) → 8765 는 워치독 경유 재기동(주말이라 장중 아님), 워치독 09-23 절차 재기동 → 확인: 두 주소 모두 200 · 매도·킬스위치 같은 POST 는
         위조 Origin 403(두 주소 각각) · 나스닥 10832 · 8780 · 워치독 1개 불변 · `monitor-dashboard` 거짓 다운 알림 없음(한 주기)
      4. 테스트: 두 주소 바인딩(port 0), 한 주소 실패 시 나머지 서비스·재시도. git commit 금지. 보고: STATUS 한 줄.

- [x] (lead 지시 2026-09-25 23:50 — module-4 L3 확인 다음, 작게) **백테스트 입력 화면 배치 — 넓은 화면의 오른쪽 빈 공간 쓰기**
      네 스크린샷(m4_backtest)에서 입력 칸이 왼쪽 약 650px 한 줄로 2,900px 내려가고 오른쪽은 풀이 문장 아래가 통째로 비어 있다. 사용자 원칙 "정보는 접지 말고, 공간은 배치로".
      넓은 화면(≥1400px)에서 조건 편집기는 왼쪽 넓게, 유니버스·기간·청산 규칙·자금·비용·변수 표는 오른쪽 단으로(풀이 문장·검증·실행 버튼은 오른쪽 위 고정). 좁은 화면은 지금처럼 한 줄.
      접기·탭으로 숨기기 금지. 확인: 1500px 스크린샷에서 스크롤 길이 전·후. vitest 무회귀. 보고: STATUS 한 줄.

- [x] (**00:15 풀림 — 선행 둘 다 끝남: module-4 완료 · backtest-agent module-5 서비스 편지(2345·2450 family_hash)**) (lead 지시 2026-09-25 22:55) **module-5 화면 — 최적화 페이지(§5.4 OptimizePage) + 그리드·폴드·홀드아웃 API(§8.3 #20 GRID_TOO_LARGE 422)**
- [x] (**07:55 풀림 — 선행 끝남: module-6 엔진(backtest 0100) · Spec `intraday.source` 칸(strategy, 28 passed) · 서비스 출처 연결(backtest). module-5 화면 다음에**) (lead 지시 2026-09-25 22:55) **module-6 화면 — 분봉·틱 탭 활성화 + 틱 정밀화 비교(결과 화면)** — **lead 정정 00:15(사용자 결정)**: 분봉 출처 선택은 **통합(AL) 기본** / KRX 는 골라 쓸 때만 — 고르면 결과·화면 상단에 "KRX 기준(NXT 제외, 거래량 20~40% 작음)" 크게. 출처별 사용 가능 기간·종목 수 표시(`/api/meta/data-ranges` 확장). 선행에 strategy-agent Spec `intraday.source` 칸 추가

- [x] (lead 지시 2026-09-26 10:00, **studio-conditions c6 — 사용자 승인 "C안, 5명 병렬"**) **조건 고르기 화면·청산 규칙·수식 편집기·레시피**
      설계 §5.4 체크리스트 전부 + §4 API(`/api/meta/indicators` 확장·`/api/meta/recipes`·수식 CRUD 연결). 지표 메타 모양은 backtest-agent 편지(IndicatorDef 새 칸)로 확정 — 그 전엔 분류 나무·검색·시간 단위 선택기 골격을 먼저.
      분봉 모드 피연산자마다 시간 단위 선택, live 미지원·모드 미지원은 비활성+이유, 풀이 문장에 시간 단위. 청산: 분할 익절 표·익절 방식·트레일링 발동·본전·시간 청산·포지션 피연산자(c2 뒤).
      수식 편집기(검사·오류 위치·저장·목록) — execution-agent 의 라우트를 app.py 에 연결. E2E: 레시피 "분봉 N일 신고가 돌파" → 실행 → 결과 / 수식 → 검사 → 저장 → 실행.
      공통: 설계서 `docs/02-design/features/studio-conditions.design.md` 를 먼저 읽어라(§3 전부·§8·§11.3). **미래참조 없음이 최우선** — 새 조건마다 카나리아. 기존 명세·프리셋·실행 결과·패리티(P1~P8) 무회귀.
      파일 규칙: 새 지표는 **자기 분류 모듈**(`ind_*.py`)에 정의 + `catalog.py`·`indicators.py` 에는 등록 한 줄만(고치기 직전 다시 읽고 Edit, 전체 덮어쓰기 금지). `ast.py`·`evaluator.py`·엔진은 backtest-agent 만.
      분봉 기본 출처 통합(AL), 실주문·KIWOOM_IS_MOCK 무접촉, git commit 금지. 그대로 믿지 말고 검증 — 설계가 틀렸으면 틀렸다고 써라.
      보고: STATUS + `state/agent_reports/monitoring-agent_<날짜시각>_conditions_c6.md`.

- [x] (monitoring 등록 2026-09-26 10:00, 선행: backtest-agent c2 — 12:45 c2 확정 편지로 처리 완료 — Exits 새 칸) **c6 청산 고급 칸 실서버 확인** — 화면은 capabilities.exit_fields 로 저절로 켜지게 만들어 두었다(가짜 서버 시험 통과). c2 가 들어오면: ①칸 이름·모양이 화면 가정(설계서 §3.4)과 맞나 ②라이브에서 분할 익절 표 → 실행 → 결과(조각 행·진입 기준 지표) 확인 ③E2E m7 에 청산 항목 추가. 보고: STATUS + `state/agent_reports/monitoring-agent_<날짜시각>_c6_exits.md`.

- [x] (**14:30 풀림 — backtest-agent c8 완료·명세 편지 1520 도착**) (lead 지시 2026-09-26 14:10, studio-conditions c8 화면) **틱 탭에 "추가 조건(분봉·일봉)" 편집기 + 사전 필터**
      설계서 §3.4b. 분봉 탭과 같은 조건 편집기(분류 나무·검색·시간 단위 — 틱에선 1분·3~60분·일봉 전일/장중)·수식 넣기, 사전 필터(일봉 D−1) 편집기, 풀이 문장에 "체결 시각 전에 끝난 분봉 기준" 한 줄.
      결과 화면에 "분봉 없어 필터 불가 N쌍"·틱 표본 경고. 라이브 E2E: 틱 + 5분봉 + 일봉 조합 실행 → 결과. 편지 오면 [ ] 로 바꾸고 시작. git commit 금지. 보고: STATUS + 보고서.

- [x] (lead 지시 2026-09-26 15:45 — data-agent 편지 1600 후속) **작업 실행기 임시 파일 경쟁 수정 검토 + 8780 을 새 코드로 재기동**
      data-agent 가 `jobrunner/store.py atomic_write_text` 의 tmp 이름(pid 만 → 같은 프로세스 두 스레드가 서로 덮어씀 → 작업 failed)을 스레드 id+난수로 고쳤다(네 파일). lead 확인: 세 폴더 한 번에 **1,738 passed / 실패 0**.
      1. 네 코드 소유자로서 수정 검토(다른 쓰기 경로에 같은 패턴이 남았는지). 2. 지금 떠 있는 8780 은 옛 코드 — 서버 안 디스패처·API 스레드도 같은 파일을 쓰니 **워치독 경유로 재기동**(네 절차), 하트비트·`restarts.log`·8780 응답·나스닥 10832 불변 확인.
      **네 세션 안전장치가 재기동을 막으면 우회하지 말고 STATUS 에 "사용자 승인 필요"로 멈춰라**(lead 가 사용자에게 묻는다). 주말이라 장중 아님. git commit 금지. 보고: STATUS 한 줄.

- [x] (**16:35 풀림 — backtest c9 편지 1740 도착**) (lead 지시 2026-09-26 16:45, studio-conditions c9 화면) **거래대금 조건 억 단위 입력 + 틱 `value_window` 편집 + 레시피 2개** — 대금(억) 피연산자 옆 숫자 칸은 "억" 표시, 시간 단위(5분봉 등) 선택과 함께. 틱 탭에 "최근 N분 체결대금 ≥ X억". E2E 1개. 편지 오면 [ ] 로.

- [x] (lead 지시 2026-09-26 17:08) **8780 을 새 코드로 재기동(커밋 63da29c·731dc28 반영)** — 네 절차(워치독 경유). 확인: 하트비트·`restarts.log`·`/api/meta/status` 200·`/api/data/overview` 의 minute_al 판정이 **좋음**·지표 목록에 `value_eok`·레시피 21개·나스닥 10832·워치독 25648 불변.
      실행 중 작업이 있으면 끝날 때까지 기다렸다가. **세션 안전장치가 막으면 우회하지 말고 STATUS 에 "사용자 승인 필요"로 멈춰라.** git commit 금지. 보고: STATUS 한 줄.

- [x] (lead 지시 2026-09-26 17:15 — **사용자 "못 찾겠는데 어딨어? 조건 넣는데 없는데"**) **거래대금(억) 조건을 찾기 쉽게**
      사용자는 조건 행 첫 칸 기본값 "가격·거래량" 에서 거래대금을 찾았는데 거기엔 원 단위 `value` 필드뿐이고, 억 단위는 "지표 → 거래량 → 거래대금(억)" 에 숨어 있다.
      1. "가격·거래량" 목록에 **"거래대금(억)"** 항목을 추가(고르면 `ind:value_eok` 로 바뀌게, 시간 단위 선택 유지) — 원 단위 "거래대금"은 "거래대금(원)" 으로 이름을 분명히
      2. 조건 고르기 **검색이 종류와 상관없이** 필드·지표·수식을 함께 찾게("거래대금" 치면 원·억·합·배수 전부)
      3. 분봉·일봉 탭 진입 조건 위에 **자주 쓰는 조건 바로 넣기** 버튼 몇 개(예: "N분봉 거래대금 X억 이상", "N일 신고가 돌파", "이평 위") — 누르면 조건 행이 채워짐
      4. 라이브 E2E: 검색 "거래대금" → 억 조건 선택 → 5분 → 20 → 실행. vitest 무회귀, 빌드. git commit 금지. 보고: STATUS 한 줄 + 스크린샷 경로.

- [x] (lead 지시 2026-09-26 17:20 — **사용자 "백테스트 중에 시각효과, 차트가 지나가는 모습 만들어줘"**, 위 거래대금 항목 다음) **실행 중 실시간 곡선 + 결과 화면 "재생"**
      1. **실행 창**: backtest-agent 가 보낼 `live_curve`(progress.json) 로 수익곡선이 오른쪽으로 **그려져 나가는** 애니메이션(ECharts), 지금 날짜·평가금·거래 수·보유 종목 수. 곡선이 없으면(오래된 작업 등) 지금 진행 막대만
      2. **결과 화면 [재생]**: 단일 종목 = 캔들이 옆으로 흐르고(창 이동) 매수·매도 표시가 그 시점에 찍힘, 보유 구간 음영 / 포트폴리오 = 수익곡선이 그려지며 그날 산·판 종목 목록이 바뀜 / 분봉 = 날 단위로 넘어가며 그날 분봉.
         속도 1·4·16배, 일시정지, 날짜로 이동(슬라이더). 결과 데이터(equity·trades·bars API)만으로 — 새 계산 없음
      3. 원칙: 정보 가리지 않기(재생은 별도 패널/전환), 다크 모드, 60fps 못 맞추면 봉 묶어 그리기. E2E: 실행 → 실행 창 곡선이 늘어남 → 결과 → 재생·일시정지·이동. git commit 금지. 보고: STATUS + 스크린샷·짧은 영상(GIF) 경로.

- [x] (lead 지시 2026-09-26 17:50 — **최우선, 재생 작업보다 먼저 · 사용자 "거래대금 입력하는 칸은 왜 없어? 원 억 이렇게만 있고"**) **왼쪽에서 금액·수량을 고르면 오른쪽이 "숫자 [  ] 억/원/주" 입력칸으로 자동 전환**
      원인(네 스크린샷 m10_2·m10_4 로 lead 확인): 새 조건 행의 오른쪽 기본값이 `지표 → N봉 최고값(고가,20)` 이라, 왼쪽을 거래대금(억)으로 바꿔도 오른쪽이 그대로 → **금액 입력칸이 안 보인다**. "자주 쓰는 조건" 버튼 경로만 "초과 [20] 억" 이 나온다.
      1. 왼쪽이 **거래대금(억)·거래대금(원)·거래대금 합(억)·거래량·당일 누적 대금** 등 금액·수량 계열로 바뀌면, 오른쪽이 그와 단위가 안 맞는 값(가격 지표·가격 필드)이면 **숫자로 자동 전환** + 단위 표시(억/원/주) + 알맞은 기본값(억 20, 거래량은 비워서 입력 유도) + 칸에 포커스
      2. 반대로 가격 계열로 돌아오면 이전처럼. 사용자가 오른쪽을 직접 고른 뒤엔 덮어쓰지 않기
      3. 단위가 다른 두 값을 비교하면(가격 vs 거래대금) 검증에 경고 문구
      4. **직접 고르는 경로를 사용자처럼 확인**: 새 조건 → 가격·거래량 → 거래대금(억) → 5분봉 → 오른쪽에 "[  ] 억" 입력칸이 바로 보임 → 20 입력 → 실행. 스크린샷 + vitest + 빌드. git commit 금지.
      **추가(17:58, 사용자 "거래대금(원), 거래대금(억) 둘 중 하나만 있어야지 왜 2개가 있는지 모르겠다")**: 목록에는 **"거래대금" 하나만** — 고르면 억 기준(value_eok), 숫자 칸은 "억".
      원 단위 `value` 필드는 목록에서 숨긴다(수식 `VALUE`·지표의 대상값 "거래대금"은 그대로 — 양쪽 다 원이라 사용자가 단위를 칠 일이 없다).
      옛 명세·레시피의 `field:value` vs 숫자 비교는 불러올 때 value_eok + 숫자÷1억으로 바꿔 보여주고 결과 동일(테스트). 거래량은 "주" 단위 표시.
      끝나면 재생 작업 계속. 보고: STATUS 한 줄 + 스크린샷 경로.

- [x] (lead 지시 2026-09-26 18:20 — 재생 작업 **바로 다음 최우선** · 사용자 "1분봉에 1% 상승시 진입조건 어떻게 만들어?") **숫자칸 자동 전환을 거래대금·거래량만이 아니라 "가격이 아닌 단위" 지표 전부로**
      지금은 금액·수량만 오른쪽이 "[ ] 억/주" 로 바뀐다. **N봉 등락률(%)·몸통(%)·RSI·스토캐스틱·이격도·ATR%·연속 봉 수·경과 분·순위·1/0 지표(정배열 등)** 를 고르면 오른쪽이 여전히 "지표 → N봉 최고값" 이라 숫자를 못 넣는다.
      1. 카탈로그 메타에 단위(가격/%/억/주/회/순위/1·0)를 두거나(없으면 backtest-agent 에 편지) 이름으로 분류해, 왼쪽이 **가격 단위가 아니면** 오른쪽을 숫자칸 + 단위 표시 + 알맞은 기본값(등락률 1, RSI 30, 순위 20…)으로. 1/0 지표는 "참이면" 연산자로
      2. 가격 단위(종가·이평·최고가…)면 지금처럼 지표 비교 유지. 직접 고른 오른쪽은 안 덮기
      3. **사용자 경로로 확인**: 새 조건 → 지표 → N봉 등락률(%) → 기간 1 → 이상 → 오른쪽에 "[ 1 ] %" 칸이 바로 보이는 스크린샷(lead 가 직접 본다) + 몸통(%)·RSI 도. vitest·빌드. git commit 금지. 보고: STATUS + 스크린샷 경로.

- [x] (lead 지시 2026-09-26 18:30 — 선행: 재생 완료 + execution-agent 템플릿 편지 · **사용자 "조건식 만드는게 좀 어려운데 좀 더 쉽게 직관적으로"**) **조건 편집을 "문장 빈칸 채우기" 카드로 개편**
      설계서 §5.5. 조건 목록 = 문장 카드(빈칸이 입력칸·단위 붙음·시간 단위 선택), "[+ 조건 추가]" = 분류·검색 템플릿 목록, 머리글 "아래를 모두 만족하면 산다/하나라도", 카드 삭제·복제.
      "직접 조립(고급)"·"수식" 은 탭으로 유지, 문장에 안 맞는 조건은 풀이 문장 카드 + [고급에서 편집]. 위의 "단위 일반화" 항목은 이 개편이 포함하면 닫아도 된다.
      **사용자 경로 스크린샷**(빈 상태 → 조건 추가 → "1분봉이 직전 봉보다 1% 이상" → 1 입력 → 실행)을 lead 가 직접 본다. vitest·빌드·E2E. git commit 금지.
- [x] (lead 지시 2026-09-26 19:12) **분봉 기본 청산도 문장 카드로** — 분봉 모드 기본 청산 "종가 < 10봉 최저값"이 문장에 안 맞아 옛 조립 행으로 나온다(lead 확인: /match 가 intraday 에서 null, 일봉은 low_break 로 맞음).
      `studio/domain/conditions/templates.py` 에 `high_break_bars` 짝인 `low_break_bars`("{tf}가격이 직전 {n}봉 최저가 아래로 내려갔다", only intraday, 손절 hint) 추가 + test_templates 에 build↔match 왕복·기본 청산 매칭 테스트. execution-agent(파일 주인)에게 한 줄 편지.
      8780 재기동 뒤 **사용자 경로 스크린샷**: 분봉 모드 새 백테스트 → 진입·청산 둘 다 카드로 보이는 화면 1장. pytest studio·vitest. git commit 금지. 끝나면 STATUS 자기 행 갱신.
- [x] (lead 지시 2026-09-26 19:22) **기간 칸 "데이터 범위를 못 불러옴" 오표시** — m14 스크린샷에 뜸. `SpecPanels.tsx:77` 이 ranges 가 없으면(= **불러오는 중**도) "못 불러옴" 이라고 쓴다.
      lead 측정: `/api/meta/data-ranges` 캐시 식은 첫 호출 **3.4초**, 캐시 뒤 0.002초(catalog.py `_ranges` TTL 60초) → 1분 넘게 쉬었다 화면 열면 3초 동안 "못 불러옴".
      ① 불러오는 중엔 "불러오는 중…", 진짜 실패일 때만 "못 불러옴"(+다시 시도). ② 3.4초 스캔이 사용자 대기로 안 보이게(서버 기동 때 미리 채우기·TTL 늘리기 등 — 데이터는 하루 한 번 바뀜) 전후 측정.
      vitest·pytest studio. 스크린샷 불필요, 측정 숫자만. git commit 금지. 끝나면 STATUS 자기 행 갱신.
- [x] (lead 지시 2026-09-26 21:10 — **사용자 "백테스트 하고 난 뒤에 종목들 나오는데 어떤건 종목코드로 나오고 어떤건 종목명으로 나오는데 종목코드로 나오는거 종목명으로 다 통일해줘"**) **결과 화면 종목 표기를 종목명으로 통일**
      ① 네 모드(일봉 포트폴리오·일봉 단일·분봉·틱) 실제 실행 결과 + 최적화·워크포워드·비교·재생·실행 중 곡선(last_event)까지 — 종목이 나오는 **모든 곳**(표·차트 축·툴팁·매수/매도 표시·범례·고르기 목록·경고문)을 사용자처럼 열어 보고 **코드만 나오는 곳 목록부터** 만든다.
      ② 전부 종목명으로(코드는 마우스 올리면 툴팁 정도). 이름을 정말 모르는 경우(상장폐지 등)만 코드 — 몇 건인지 보고. 이름 출처는 서버 한 곳(종목 마스터)에서, 화면마다 따로 찾지 말 것. 서버 응답에 name 이 비는 곳(예: live_curve last_event.name, 틱 거래 등)은 서버에서 채운다.
      ③ **사용자 경로 스크린샷**: 각 모드 결과 화면에서 종목이 보이는 부분 고치기 전/후 — lead 가 직접 본다. vitest·pytest studio·빌드·8780 재기동. git commit 금지. 끝나면 STATUS 자기 행 갱신.
- [>] (lead 지시 2026-09-26 21:25 — 선행: 위 종목명 통일 + execution-agent "모든 지표 문장 카드" 완료) **엔벨로프 사용자 경로 확인** — 8780 재기동(새 템플릿 적재) 뒤 [+ 조건 추가] → "엔벨로프" 검색 → 카드 → 숫자 입력 → 검증 통과 스크린샷 + 분류별 목록에 64개가 들어왔는지(일목·CCI 검색도). lead 가 직접 본다. git commit 금지.
