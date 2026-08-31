#!/usr/bin/env bash
# lead pane(현재) + 에이전트 6개를 한 탭에 3x2 그리드로 띄운다.
# herdr pane 안에서 실행할 것 (HERDR_ENV=1).
set -e
test "${HERDR_ENV:-}" = 1 || { echo "herdr pane 안에서 실행해라"; exit 1; }
AGENTS="data-agent strategy-agent backtest-agent risk-agent execution-agent monitoring-agent"
CWD=$PWD
TAB=$(herdr pane current --current | python -c "import sys,json;print(json.load(sys.stdin)['result']['pane']['tab_id'])")
pid(){ python -c "import sys,json;print(json.load(sys.stdin)['result']['pane']['pane_id'])"; }

# 1) lead 오른쪽에 위쪽 3칸, 각 칸 아래로 1칸씩 → 3x2
declare -A P
# ratio = 분할 전 pane이 갖는 비율. lead 40% + 에이전트 3열 20%씩이 되게 연쇄 분할.
top=$HERDR_PANE_ID
for pair in "data-agent:0.40" "strategy-agent:0.333" "backtest-agent:0.5"; do
  a=${pair%%:*}; r=${pair##*:}
  top=$(herdr pane split --pane "$top" --direction right --ratio "$r" --cwd "$CWD" --no-focus | pid)
  P[$a]=$top
done
for pair in "risk-agent:data-agent" "execution-agent:strategy-agent" "monitoring-agent:backtest-agent"; do
  a=${pair%%:*}; over=${pair##*:}
  P[$a]=$(herdr pane split --pane "${P[$over]}" --direction down --cwd "$CWD" --no-focus | pid)
done

# 2) 각 pane에 claude를 해당 에이전트로 기동
for a in $AGENTS; do
  herdr agent start "$a" --kind claude --pane "${P[$a]}" --timeout 120000 -- --agent "$a" >/dev/null
  herdr pane rename "${P[$a]}" "$a" >/dev/null
done

# 3) 이름표
herdr pane rename "$HERDR_PANE_ID" lead >/dev/null
herdr tab rename "$TAB" team >/dev/null
herdr agent list
