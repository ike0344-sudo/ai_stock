# 에이전트 팀 dispatch 헬퍼. 조합과 안전장치는 AGENT_TEAM.md 참고.
#
#   .\team.ps1 nightly     데이터 갱신 -> (끝나면) 후보 탐색   ※ data/ 공유라 순차
#   .\team.ps1 review      전략/리스크 코드 검토 2개 병렬
#   .\team.ps1 health      운영 헬스체크 (읽기 전용)
#   .\team.ps1 status      백그라운드 세션 목록
#
# execution-agent 는 여기 없다 — 실계좌 주문은 백그라운드로 돌리지 않는다.

param([Parameter(Position = 0)][string]$Task = "status")

$Repo = $PSScriptRoot
$Data = Join-Path $Repo "data"

function Start-Agent {
    param([string]$Agent, [string]$Prompt, [switch]$NeedsData)
    $args = @("--bg", "--agent", $Agent)
    # worktree 격리 세션에는 data/(gitignore 대상)가 없다 — 원본 경로를 열어준다.
    if ($NeedsData) { $args += @("--add-dir", $Data) }
    $args += $Prompt
    Write-Host "dispatch: $Agent" -ForegroundColor Cyan
    & claude @args
}

switch ($Task) {
    "nightly" {
        # data/ 에 쓰는 세션은 하나만. 갱신이 끝난 걸 확인하고 백테스트를 붙인다.
        $id = Start-Agent -Agent "data-agent" -NeedsData -Prompt @'
python -m backtesting.cli update-top35 로 오늘 일봉/분봉을 증분 갱신해줘.
실패한 종목코드와 사유만 표로 보고하고, 성공 목록은 나열하지 마.
data/ 에 쓰는 다른 작업은 하지 마.
'@
        Write-Host "`n갱신 세션: $id" -ForegroundColor Yellow
        Write-Host "끝나면 아래를 실행하세요 (data/ 를 동시에 읽지 않기 위해 순차):" -ForegroundColor Yellow
        Write-Host "  claude logs $id" -ForegroundColor DarkGray
        Write-Host "  .\team.ps1 evolve" -ForegroundColor DarkGray
    }

    "evolve" {
        Start-Agent -Agent "backtest-agent" -NeedsData -Prompt @'
evolve.py --scan 을 돌려 전략 후보를 탐색해줘.
홀드아웃 게이트를 통과한 후보만 보고하고, 0개면 0개라고 그대로 말해줘.
통과율이 20%를 넘으면 게이트가 느슨하거나 홀드아웃이 오염된 것이니 그것도 짚어줘.
risk_limits.yaml 이나 final_strategy.py 의 값은 절대 바꾸지 마 — 보고만.
'@
    }

    "review" {
        # 서로 다른 파일을 만지고 데이터도 안 읽으므로 병렬 안전.
        Start-Agent -Agent "strategy-agent" -Prompt @'
final_strategy.py 의 진입조건 7개 중 완화 여지가 있는 것을 근거와 함께 제안해줘.
파일은 고치지 말고 제안만. 백테스트도 돌리지 마.
'@
        Start-Agent -Agent "risk-agent" -Prompt @'
risk_limits.yaml 의 stop_loss_pct 를 2.5%에서 바꿀 경우 영향받는 코드 경로를 전부 짚어줘.
portfolio_sim.py 가 고정 슬롯 금액을 쓰는 것과 risk_manager.get_position_size 가
손절폭으로 수량을 나누는 것의 차이도 함께. 값은 바꾸지 말고 보고만.
'@
    }

    "health" {
        Start-Agent -Agent "monitoring-agent" -Prompt @'
8765 트레이딩 대시보드와 monitor-nasdaq-drop 이 살아있는지 확인해줘.
죽어 있으면 되살리는 방법만 알려주고, 프로세스를 직접 죽이거나 띄우지는 마.
state/strategy_1/ 의 킬스위치 상태와 마지막 실행일도 같이 보고해줘.
'@
    }

    "status" {
        & claude agents --json | Out-String | Write-Host
    }

    default {
        Write-Host "사용법: .\team.ps1 [nightly|evolve|review|health|status]"
        Write-Host "자세한 내용은 AGENT_TEAM.md"
    }
}
