# 에이전트 팀 운영 (Claude Code 세션 오케스트레이션)

`.claude/agents/` 에 정의된 6개 에이전트를 여러 세션에 나눠 돌리는 방법.
정의 파일은 그대로 두고, **어떤 조합이 안전한지**만 여기에 적는다.

```
data-agent        일봉/분봉 수집·캐싱, top35 갱신          → data/ 를 쓴다
backtest-agent    워크포워드 검증, 파라미터 탐색            → data/ 를 읽는다
strategy-agent    진입/청산 규칙 구현                       → backtesting/*.py
risk-agent        사이징·손절·한도                          → risk_limits.yaml
execution-agent   주문 실행                                 → 실계좌
monitoring-agent  헬스체크·알림·일일 리포트                 → 읽기 전용
```

---

## 먼저 알아야 할 함정 두 개

**1. worktree에는 `data/` 가 없다.**
`.gitignore` 에 `*.csv` 가 있어서 `data/`(2.9GB, 분봉 1045종목)는 git이 추적하지
않는다. `git worktree add` 로 만든 격리 사본에는 **빈 `data/`** 만 생긴다.
백테스트를 worktree에서 돌리려면 원본 데이터 경로를 명시적으로 넘겨야 한다:

```bash
claude --bg --agent backtest-agent \
  --add-dir C:/Users/ike03/Desktop/code/ai_stock/data \
  "--data-dir C:/Users/ike03/Desktop/code/ai_stock/data 로 워크포워드 검증 돌려줘"
```

`state/`, `models/`, `.cache/` 도 같은 이유로 worktree에 없다.

**2. `data/` 는 공유 자원이라 동시에 쓰면 깨진다.**
`update-top35` 가 CSV를 증분 갱신하는 중에 백테스트가 같은 파일을 읽으면
찢어진 데이터를 읽는다. **`data/` 에 쓰는 에이전트는 항상 하나만.**

---

## 조합 A — 데이터 갱신 → 백테스트 (순차, 자동화 가능)

`data/` 를 공유하므로 병렬 금지. 앞이 끝나야 뒤가 시작한다.

```powershell
# 1) 데이터 갱신 (data/ 를 쓰는 유일한 세션)
$id = claude --bg --agent data-agent `
  "python -m backtesting.cli update-top35 를 돌려서 오늘 일봉/분봉을 증분 갱신하고,
   실패한 종목코드와 사유만 표로 보고해줘. 성공 목록은 나열하지 마."

claude logs $id      # 진행 확인
# 끝난 뒤에
claude --bg --agent backtest-agent `
  "evolve.py --scan 을 돌려 후보를 탐색하고, 홀드아웃 게이트를 통과한 것만 보고해줘.
   0개면 0개라고 해. 통과율이 20%를 넘으면 게이트가 느슨한 거니 그것도 알려줘."
```

## 조합 B — 코드 작업 병렬 (worktree 격리, 데이터 불필요)

서로 다른 파일을 만지고 데이터도 안 읽으므로 **진짜 병렬로 돌려도 안전**하다.
세션 안에서 시키는 쪽이 편하다 — 각자 자기 worktree를 받는다:

> strategy-agent 는 진입조건 완화안을, risk-agent 는 손절폭 후보를 각각 worktree에서
> 검토해줘. 코드만 고치고 백테스트는 돌리지 마.

터미널에서 직접 띄우려면:

```powershell
claude --bg --agent strategy-agent "final_strategy.py 진입조건 중 완화 여지가 있는 걸 찾아 제안만 해줘. 파일은 고치지 마."
claude --bg --agent risk-agent    "risk_limits.yaml 의 stop_loss_pct 를 바꿀 때 영향받는 코드 경로를 전부 짚어줘."
```

## 조합 C — 장중 운영 (읽기 전용만 자동화)

```powershell
claude --bg --agent monitoring-agent `
  "8765 대시보드와 monitor-nasdaq-drop 이 살아있는지 확인하고, 죽어 있으면 어떻게
   되살리는지만 알려줘. 프로세스를 직접 죽이거나 띄우지는 마."
```

---

## 하지 말 것

- **`execution-agent` 를 `--bg` 로 띄우지 않는다.** 실계좌 주문이 나가는 경로다.
  주문은 사람이 보는 앞에서만.
- **전략1을 자동 스케줄에 걸지 않는다.** 수동 실행만 (cron/시작프로그램 금지).
- **`data/` 에 쓰는 세션을 둘 이상 띄우지 않는다.** 조합 A를 병렬로 바꾸지 말 것.
- `--dangerously-skip-permissions` 는 `data/` 나 `state/` 를 만지는 세션에 쓰지 않는다.

## 세션 관리

```powershell
claude agents            # 대화형 뷰 (TTY 필요) — 목록 + 새로 dispatch
claude agents --json     # 스크립트용
claude attach <id>       # 이 터미널로 가져오기
claude logs <id>         # 출력만
claude stop <id>         # 중지 (대화 보존, attach 로 재개)
claude rm <id>           # 삭제 (worktree 도 안전하면 같이)
```

세션끼리 메시지도 보낼 수 있다. 세션 이름은 `claude agents` 목록이나 세션 안에서
확인한다 (예: `ai-stock-5f`, `kospi-theme-engine-d0`).

## lead

lead 는 **orca pane 이 아니라 orca 밖의 일반 claude 세션**이다. `orca-team.ps1` 에
`lead` 를 넘겨 pane 을 하나 더 띄울 수도 있지만, 그러면 화면만 한 칸 잡아먹는다 —
`orca-tell.ps1` 은 `.orca-team-handles.json` 의 에이전트↔handle 매핑만 보고 쏘기
때문에 지시하는 쪽이 어디에 있든 상관없다. 지정할 설정값도 없다.

```powershell
.\orca-tell.ps1 risk-agent "..."          # 지시
.\orca-tell.ps1 risk-agent -Read          # 화면 읽기
.\orca-tell.ps1 risk-agent -Read -Cursor 42   # 그 뒤 새 출력만
```

`.orca-team-handles.json` 은 `orca-team.ps1` 이 pane 을 만들 때만 덮어쓴다. pane 을
수동으로 닫으면 기록이 남아 `orca-tell.ps1` 이 죽은 handle 로 쏜다 — 정리는
`.\orca-team.ps1 -Close` 로.

## 담당 분담 — 두 저장소

소피증권(`kospi-theme-engine/`, 8770)은 데이터 조각이 아니라 독립된 시스템이다:
테마 점수 엔진(`app/engine/`), 수집·실시간 구독(`app/ingest/`), 8770 서버, 텔레그램 봇,
배포본, 그리고 **루트에 따로 도는 신호 탐색 스크립트들**(`chgtop_*`, `entry*`,
`rising_*`, `score_analyze.py`).

에이전트를 새로 만들지 않고 기존 6명을 두 저장소에 걸친다. 겹치는 자원은 담당을
하나로 고정한다 — 둘이 같이 만지면 깨진다.

| 담당 | `ai_stock/` | `kospi-theme-engine/` (소피증권) |
|---|---|---|
| strategy-agent | 전략 규칙 설계·구현 | `app/engine/` 테마 점수·가중치 |
| backtest-agent | 검증 절차와 가드, 성능 병목 | 루트 신호 탐색 스크립트 검증 |
| data-agent | `data/` 보관·유실 방지 | `app/ingest/`, 분봉 캐시, 백업 |
| monitoring-agent | 로그·프로세스·디스크 감시 | 8770 서버·봇·워치독·로그·배포본 |
| risk-agent | `risk_manager.py`, `trading_loop.py`, `risk_limits.yaml`, `cli.py` 한도 | 해당 없음 |
| execution-agent | `kiwoom_client.py`, 주문 실행 모듈 | 해당 없음 (주문을 안 낸다) |

**strategy/backtest 를 두 저장소에 걸치는 이유**: 지금 양쪽에서 전략 탐색이 따로 돌고
있다 — `kospi-theme-engine/pullback_entry.py` 와
`ai_stock/backtesting/strategies/pullback_reentry.py` 는 이름부터 겹친다. 담당을 나누면
같은 전략을 두 번 판다.

**테마 점수 가중치는 확정 기준이 있다.** 초과수익이 아니라 현재 수급 기준이고,
우선순위는 대금 20위 개수 > 상승률 > 시장 파이 (2026-08-22 확정). strategy-agent 가
`app/engine/scoring.py` 를 맡더라도 **이 기준을 임의로 바꾸지 않는다** — 바꾸려면 사용자
승인이 먼저다.

**소피증권 데이터는 지우지 않는다.** 로그가 커져도 압축·보관이지 삭제가 아니다.
복구 불가 시계열(장중 스냅샷, 실시간 순위 이력)이 섞여 있어서, 지운 뒤에는 되돌릴
방법이 없다.
## 상시 규칙 — 병목은 항상 최적화

느린 게 보이면 지시를 기다리지 말고 그 자리에서 고친다. 단 순서는 **측정 먼저**다:
어디가 느린지 숫자로 잡고 나서 고치고, 고친 뒤 같은 방식으로 다시 재서 배수를 보고한다.
추측으로 병렬화하지 않는다 — `data/` 를 쓰는 경로는 동시 실행이 오히려 깨뜨린다.
**판단 로직은 그대로 두고 속도만 바꾼다**(기존 커밋 `simulator.run 3.4배`, `5분봉 병렬 배수`
와 같은 방식). 결과 숫자가 달라지면 최적화가 아니라 버그다.
