# 자율 전략 개선 사이클 (Auto-Develop)

너는 이 저장소(`ai_stock`)에서 완전히 무인으로, 한 사이클만 실행된다. 사람이 결과를
실시간으로 검토하지 않고 검증을 통과하면 그대로 `origin/main`에 반영된다 — 그래서
이 문서에 적힌 범위와 절차를 벗어나지 않는 것이 특히 중요하다.

## 0. 시작 시 반드시 먼저 할 일

1. 지금이 어떤 git worktree/branch인지 확인: `git branch --show-current`, `git status`.
   **메인 체크아웃(사용자가 평소 작업하는 디렉토리)이 아니라 이 세션 전용 worktree여야
   한다** — worktree가 아니라면 즉시 중단하고 아무것도 하지 마라.
2. **상태 파일은 항상 절대경로 `C:\Users\ike03\Desktop\code\ai_stock\state\auto_develop\`를
   쓴다 (repo-relative `state/auto_develop/`가 아니다).** 매 사이클이 서로 다른 worktree
   디렉토리에서 실행되고 `state/`는 git으로 공유되지 않는 로컬 전용 폴더라, 상대경로로
   쓰면 그 worktree가 지워질 때 같이 사라져 다음 사이클이 이전 기록을 전혀 못 본다
   (2026-07-26 첫 테스트에서 실제로 겪은 문제).
3. 디렉토리가 없으면 만들고, 시작 시각을 `last_run_started.json`에
   `{"started_at": <unix epoch>}` 형식으로 기록한다 (Bash로 `python -c "import json,time;..."` 등 사용).
4. `baseline_metrics.json`이 없으면 이번 사이클에서 변경 없이
   현재 코드 그대로 아래 3번 절차(검증)를 한 번 돌려서 그 결과를 baseline으로 저장하고
   종료한다 (첫 실행은 "베이스라인 확립"만 하고 코드는 건드리지 않는다).
5. 검증에 필요한 도구(`validate_strategy1.py`/`validate_strategy2.py`/`ml/walk_forward.py` 등)가
   이 worktree에 없으면 — 예를 들어 `run_auto_develop.ps1`이 `git push origin main`을
   실행하지 못했거나 실패한 경우 — 추측으로 진행하지 말고 4번 "차단됨(blocked)" 절차로
   바로 넘어간다.

## 1. 절대 건드리면 안 되는 파일 (금지 목록)

아래 파일들은 읽는 것은 괜찮지만 **수정/생성/삭제 절대 금지**:

- `backtesting/risk_manager.py`, `risk_limits.yaml` — 리스크 한도/포지션 사이징
- `backtesting/reconcile.py`, `backtesting/sell_order.py`, `backtesting/telegram_order_bot.py`,
  `backtesting/trading_loop.py`, `buy_once.py`, `kiwoom_client.py` — 실주문/체결/계좌 연동
- `.env`, `.env.example`
- `nasdaq_monitor_watchdog.ps1`, `nasdaq_monitor_watchdog_launcher.vbs`, `run_nasdaq_monitor.bat`,
  `run_dashboard.bat`, `auto_develop_prompt.md`(이 문서 자체), `.claude/agents/*.md`
- `backtesting/dashboard_server.py`, `backtesting/notifier.py`, `backtesting/nasdaq_drop_monitor.py`,
  `backtesting/dashboard_monitor.py`, `backtesting/top35_job.py`, `backtesting/updater.py`,
  `backtesting/data_loader.py`, `backtesting/universe.py`, `backtesting/screener.py`,
  `backtesting/realtime_feed.py` — 데이터/운영 인프라, 이번 사이클의 담당 범위 아님

**건드릴 수 있는 범위**: `backtesting/final_strategy.py`, `backtesting/breakout_reversal.py`,
`backtesting/entry_filters.py`, `backtesting/oversold_strategy.py`, `backtesting/strategy3_scalp.py`,
`backtesting/strategy4_rank_watch.py` 같은 **신호 생성(진입/청산 조건) 코드와 그 파라미터**,
그리고 대응하는 `tests/backtesting/test_*.py`. 즉 `.claude/agents/strategy-agent.md`가 정의한
전략 에이전트의 역할 경계와 동일하다 — 신호만 바꾼다. 체결/비용/자본금 계산 로직은 손대지 않는다.

## 2. 이번 사이클에서 할 일

1. `strategy1_backtest_report.pdf`, `baseline_metrics.json`(0번의 절대경로), 최근 커밋 로그를
   읽어 현재 strategy_1/strategy_2의 알려진 약점을 하나 고른다 (예: 특정 구간 승률 저조,
   손익비 개선 여지, 과최적화 의심 파라미터).
2. **딱 하나**의 작고 구체적인 가설을 세운다 (예: "n_day_high_filter의 n을 20→30으로
   바꾸면 손익비가 개선될 것이다"). 여러 개를 한 번에 바꾸지 않는다 — 실패 시 원인을
   특정할 수 있어야 한다.
3. `.claude/agents/strategy-agent.md`의 규칙을 따라 신호 코드만 수정한다.
4. `.claude/agents/backtest-agent.md`가 설명하는 방식대로 검증한다 — `validate_strategy1.py`
   또는 `validate_strategy2.py`(해당 전략에 맞는 쪽)를 확장/재사용해 워크포워드
   IS/OOS 검증을 돌린다. 새로 만들지 말고 기존 함수(`scan_all_trades`, `run_walk_forward`,
   `compute_portfolio_metrics`)를 재사용한다.

## 3. 통과 기준 (전부 만족해야 반영, 하나라도 실패하면 폐기)

`baseline_metrics.json`(0번의 절대경로)의 워크포워드 OOS 수치와 비교해서:

- OOS 손익비(Profit Factor)가 baseline 대비 **악화되지 않음** (허용 오차: 상대 5% 이내 하락은
  잡음으로 보고 허용, 그 이상 하락이면 실패)
- OOS 승률이 baseline 대비 **상대 5% 이상 하락하지 않음**
- OOS 거래 건수가 baseline 대비 **20% 이상 줄지 않음** (신호 빈도를 죽여서 지표만
  좋아 보이게 만드는 것 방지)
- `python -m pytest tests/ -q` **전체 통과** (기존 테스트 깨짐 없음)
- 세금(매도 증권거래세) 반영 수치로 비교한다 — 세금 미반영 수치로 판단하지 않는다
- 변경한 함수/파라미터에 대응하는 테스트가 없으면 하나 추가한다 (ponytail 관례: 로직
  변경엔 최소 하나의 테스트)

## 4. 결과 처리

세 가지 결과 중 하나로 끝난다 — **어느 쪽이든 아래 "공통 마무리"를 반드시 수행한다.**

**통과한 경우 (adopted):**
1. 변경사항을 커밋한다 (무엇을 왜 바꿨는지, 이전/이후 지표를 커밋 메시지에 명시,
   `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` 포함)
2. `baseline_metrics.json`을 새 지표로 갱신하고 같이 커밋한다
3. `git push origin HEAD:main` — **로컬 main 브랜치나 사용자의 기본 작업 디렉토리는
   절대 건드리지 않는다.** origin(GitHub)의 main만 갱신한다.
4. `log.jsonl`에 한 줄 추가: `{"finished_at": <epoch>, "outcome": "adopted", "hypothesis": "...", "before": {...}, "after": {...}}`

**기준 미달로 실패한 경우 (rejected):**
1. 변경사항을 커밋하지 않는다 (`git checkout -- .`로 되돌리거나 그냥 두고 커밋만 안 함)
2. push 하지 않는다
3. `log.jsonl`에 한 줄 추가: `{"finished_at": <epoch>, "outcome": "rejected", "hypothesis": "...", "reason": "..."}`

**검증 자체를 못 한 경우 (blocked — 예: 도구 없음, 데이터 없음, 애매한 상황):**
1. 아무것도 커밋/push하지 않는다. 추측으로 진행하지 않는다.
2. `log.jsonl`에 한 줄 추가: `{"finished_at": <epoch>, "outcome": "blocked", "reason": "..."}`

**공통 마무리 (세 경우 모두, 반드시 이 순서로):**
1. `last_run_finished.json`(절대경로)에 `{"finished_at": <unix epoch>}`를 기록한다
   (이게 없으면 watchdog이 "아직 실행 중"으로 오판해 다음 사이클을 못 띄운다).
2. **이 worktree를 정리한다**: 메인 체크아웃으로 돌아가지 말고(어차피 다른 세션이라 이동
   불가), 이 세션이 끝나면 worktree가 남아 계속 쌓이므로 마지막 응답에 다음 사실을
   분명히 적어라 — "이 worktree(`<경로>`, 브랜치 `<이름>`)는 이제 정리 대상입니다." 실제
   삭제(`git worktree remove`)는 메인 체크아웃에서 실행해야 하므로 이 세션 자신은 못
   지운다 — 대신 `last_run_finished.json`에 `"worktree_path"`와 `"branch"`를 같이 기록해
   다음 사이클(또는 사용자)이 정리할 수 있게 남긴다.

## 금지사항 (재확인)

- 위 "절대 건드리면 안 되는 파일" 목록 수정 금지
- 한 사이클에 여러 개의 변경 묶어서 시도 금지 (하나씩만)
- 통과 기준 미달인데 "그래도 방향은 맞다"며 반영 금지 — 기준 미달이면 무조건 폐기
- `--force`/`git push --force` 금지, git 히스토리 재작성 금지
- 로컬 main 브랜치나 다른 worktree 체크아웃 건드리기 금지 (origin만 갱신)
- `last_run_finished.json`(절대경로) 기록 없이 종료 금지
