# 에이전트별로 창을 쪼개서 동시에 띄운다. team.ps1(--bg, 백그라운드)과 달리
# 각 pane이 대화형 세션이라 진행을 눈으로 보고 권한 승인도 바로 할 수 있다.
#
#   .\team-panes.ps1                      기본 4분할 (strategy/risk/backtest/monitoring)
#   .\team-panes.ps1 -Agents data,backtest   원하는 에이전트만
#   .\team-panes.ps1 -WhatIf              실행 대신 만들 명령만 출력
#
# execution-agent 는 기본 레이아웃에 없다 — 실계좌 주문은 따로 띄운다.

param(
    [string[]]$Agents = @("strategy-agent", "risk-agent", "backtest-agent", "monitoring-agent"),
    [switch]$WhatIf
)

$Repo = $PSScriptRoot
$Data = Join-Path $Repo "data"

if (-not (Get-Command wt -ErrorAction SilentlyContinue)) {
    Write-Error "Windows Terminal(wt)이 없습니다. 'winget install Microsoft.WindowsTerminal' 후 다시 실행하세요."
    return
}

# data/ 를 읽어야 하는 에이전트만 --add-dir 로 열어준다(worktree/격리 세션 대비).
$needsData = @("data-agent", "backtest-agent")

function Start-Pane {
    param([string]$Agent, [int]$Index)

    $claude = "claude --agent $Agent"
    if ($needsData -contains $Agent) { $claude += " --add-dir `"$Data`"" }

    # 세미콜론으로 pane 을 이어붙이는 방식(wt a `; split-pane b)은 PowerShell 에서
    # 구분자가 wt 까지 전달되지 않아 창이 아예 안 떴다(실측). 대신 -w 0 으로 같은
    # 창을 지목해 한 번에 하나씩 pane 을 추가한다 — 이스케이프가 필요 없다.
    if ($Index -eq 0) {
        $sub = @("new-tab")
    } else {
        # 첫 pane 이후 좌우/상하를 번갈아 쪼개 격자로 만든다
        $sub = @("split-pane", $(if ($Index % 2 -eq 1) { "-V" } else { "-H" }))
    }

    $a = @("-w", "0") + $sub + @("--title", $Agent, "-d", $Repo, "pwsh", "-NoExit", "-Command", $claude)

    if ($WhatIf) { Write-Host "wt $($a -join ' ')" -ForegroundColor Cyan; return }
    & wt @a
    Start-Sleep -Milliseconds 900   # 창/pane 이 자리를 잡기 전에 다음 걸 밀어넣지 않도록
}

if (-not $WhatIf) { Write-Host "여는 중: $($Agents -join ', ')" -ForegroundColor Cyan }
for ($i = 0; $i -lt $Agents.Count; $i++) {
    Start-Pane -Agent $Agents[$i] -Index $i
}
