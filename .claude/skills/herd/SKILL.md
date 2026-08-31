---
name: herd
description: >
  herdr pane에 6개 역할 에이전트(data/strategy/backtest/risk/execution/monitoring)를
  띄우고 lead가 지시·수집하는 오케스트레이션. "에이전트 띄워", "팀 띄워", "herd",
  "전체 에이전트", "누구한테 시켜" 처럼 이 저장소의 에이전트 팀을 굴릴 때 쓴다.
  단일 작업을 그냥 하는 데는 쓰지 않는다.
---

# herd — 에이전트 팀 오케스트레이션

lead(이 세션)는 **지시와 종합만** 한다. 코드/데이터 작업은 각 에이전트 pane에서 시킨다.

## 0. 전제

```bash
test "${HERDR_ENV:-}" = 1   # 아니면 여기서 멈추고 사용자에게 알린다
```

## 1. 띄우기

```bash
./herdr_team.sh          # lead 40% + 에이전트 3x2 그리드, tab 이름 team
herdr agent list         # 확인
```

이미 떠 있으면 다시 돌리지 마라 — 이름이 겹쳐 `agent start` 가 실패한다.
갈아엎으려면 lead(`$HERDR_PANE_ID`) 빼고 전부 `herdr pane close <pane>` 한 뒤 다시.

## 2. 지시

```bash
herdr agent prompt data-agent "..." --wait --timeout 600000
herdr agent read data-agent --lines 60          # 결과 읽기
herdr agent wait backtest-agent --until blocked # 승인창 대기
```

- `--wait` 면 충분하다. `--until` 은 blocked 같은 특수 대기에만.
- 긴 결과는 `--source recent-unwrapped` 로 읽어라 — `recent` 는 소프트랩이 접혀 나온다.
- `agent_blocked` 가 오면 **사용자에게 물어라**. 승인창에 임의로 답하지 않는다.
- 여러 에이전트에 시킬 땐 `--wait` 없이 다 쏘고 나서 `herdr agent wait <name>` 로 각각 회수.

## 3. 누구한테 시킬지

| 에이전트 | 담당 | 건드리는 것 |
|---|---|---|
| data-agent | 일봉/분봉 수집·캐싱, top35 갱신 | `data/` **쓴다** |
| backtest-agent | 워크포워드, 파라미터 탐색 | `data/` 읽는다 |
| strategy-agent | 진입/청산 규칙 | `backtesting/*.py` |
| risk-agent | 사이징·손절·한도 | `risk_limits.yaml` |
| execution-agent | 주문 실행 | 실계좌 |
| monitoring-agent | 헬스체크·알림·리포트 | 읽기 전용 |

**`data/` 에 쓰는 세션은 항상 하나.** data-agent 가 도는 동안 backtest-agent 에게
같은 데이터를 읽히지 마라 — 증분 갱신 중 CSV를 읽으면 찢어진 데이터가 나온다.
자세한 조합은 `AGENT_TEAM.md`.

## 4. 함정 (직접 밟은 것들)

- **id를 예측하지 마라.** pane id는 `w1:p8`, `w1:pA`, `w1:pK` 로 16진수 증가한다. 항상 응답 JSON에서 읽는다.
- **`$HERDR_TAB_ID` 는 늙는다.** pane을 옮기면 원래 탭이 닫혀 stale 해진다. 필요하면 `herdr pane current --current` 로 다시 조회.
- **에러가 exit code로 안 온다.** `{"error":{...}}` 를 JSON으로 반환하니 `set -e` 만 믿지 말고 파싱해서 확인.
- **`--ratio` 는 분할 *전* pane이 갖는 몫**이다. `--ratio 0.40` → 원래 pane 40%, 새 pane 60%.
- **`resize --amount` 는 전체 대비 비율**이다. 0.32 를 주면 한 번에 화면 1/3이 움직인다.
- `agent stop` 은 없다. 종료는 `pane close`.
- **`--lines` 를 늘려도 응답이 안 나오면 스크롤백에 없는 것이다.** 에이전트가 alt-screen 을 쓰면 흘러간 줄은 herdr 스크롤백에 안 남는다. 그때만 "결과를 임시 폴더에 .md 로 쓰고 경로만 답해라"라고 다시 시키고 그 파일을 읽어라 — 처음부터 파일로 시키지는 마라.
- 백그라운드로 띄울 땐 `--no-focus`. 안 붙이면 사용자 화면이 새 pane 으로 튄다.
- **`prompt` 뒤에 따로 `wait` 를 걸면 헛돈다.** 상대가 아직 working 으로 안 바뀐 사이 wait 가 직전 idle 을 그대로 잡아 즉시 반환한다(2026-08-31 실제로 밟음 — 5분짜리 작업이 1초 만에 "끝났다"고 왔다). 한 명이면 `prompt --wait` 를 쓰고, 여럿을 회수할 땐 `agent get` 으로 working 이 된 걸 확인한 뒤 wait 해라.
- `idle` 은 "그 탭이 UI에 보인 적 있는 idle", `done` 은 "안 본 채로 끝난 idle" 이다. `unknown` 은 완료 증거가 아니다.

## 5. 에이전트 없이 명령만 돌리기

pytest 나 스크립트처럼 claude 를 태울 필요 없는 건 pane 에 직접 돌린다.

```bash
P=$(herdr pane split --current --direction right --cwd "$PWD" --no-focus | jq -r .result.pane.pane_id)
herdr pane run "$P" "pytest tests/backtesting -q"
herdr pane wait-output "$P" --match "passed" --timeout 300000   # --regex 도 됨
herdr pane read "$P" --source recent-unwrapped --lines 120
herdr pane close "$P"
```

`wait-output` 은 **이미 찍힌 출력도 매치한다** — 이전 실행의 "passed" 를 잡을 수 있으니 새 pane 에서 돌려라.

## 6. 무인으로 돌리기

지시·판정을 매번 사람이 하지 않으려면 [[lead-loop]] 를 쓴다.

```bash
/loop /lead-loop     # 간격 생략 = 자율 페이스. 할 일 없어지면 스스로 멈춘다
```

- 한 회차 = 상태 수집 → 판정 1건 → `state/loop_ledger.md` 한 줄 → 종료 판정.
- **`ralph-loop` 은 쓰지 마라.** Stop 훅으로 즉시 재주입이라 20~60분짜리 pane 작업을 기다리는 우리
  구조에선 "아직 안 끝났음"만 확인하며 회차를 태운다. 대기 없는 짧은 반복에만 맞다.
- 루프는 **커밋하지 않는다.** 코드 변경까지만 하고 `git commit` 은 사람이 한다.
- 멈추는 조건: 큐 0 + 미배달 편지 0 + 전원 idle + 열린 `[요청]` 0. 또는 회차 20 초과.
- `blocked` 가 하나라도 있으면 루프는 멈추고 사람을 부른다 — 승인창에 임의로 답하지 않는다.

## 7. 한 화면 조작

```bash
herdr pane zoom --current --toggle              # 한 칸만 크게
herdr pane resize --pane w1:p1 --direction left --amount 0.05
herdr agent focus data-agent
```
