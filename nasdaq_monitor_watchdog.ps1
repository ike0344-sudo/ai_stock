# "항상 켜짐"이 요구되는 백그라운드 감시 프로세스들을 계속 살려둔다
# (나스닥 급락 감시, 트레이딩 대시보드 감시, 트레이딩 대시보드 서버 자체).
# 로그온 시 시작 폴더(nasdaq_monitor_watchdog_launcher.vbs)에서 한 번 실행되면,
# 이 프로세스 자체가 무한 루프로 5분마다 각 대상의 생존을 확인하고 죽어있으면 재시작한다.
# Task Scheduler 등록은 이 계정의 비관리자(UAC 필터링) 세션에서 Access Denied로
# 막혀서(스케줄러 API/schtasks 둘 다 동일 오류) 대신 이 방식을 쓴다.
#
# 생존 확인 방식은 대상마다 다르다:
# - Heartbeat 대상: 자기 상태 폴더에 남기는 heartbeat.json의 나이로 판단
#   (backtesting/heartbeat.py와 동일한 파일 — nasdaq_drop_monitor.py/dashboard_monitor.py가
#   이미 매 사이클 갱신하고 있다). 프로세스는 떠 있지만 멈춰있는(hang) 경우까지 잡아내기
#   위함 — 커맨드라인 문자열 매칭만으로는 이런 행 상태를 감지할 수 없다(monitoring-agent
#   감사 지적사항).
# - Http 대상(대시보드 서버): dashboard_server.py는 자기 heartbeat.json을 안 남기므로
#   대신 monitor-dashboard와 같은 방식(정적 라우트 "/"에 GET)으로 응답 여부를 직접 확인한다.
$repoRoot = "C:\Users\ike03\Desktop\code\ai_stock"

$targets = @(
    @{ Type = "Heartbeat"; Match = "monitor-nasdaq-drop"; Args = @("-m", "backtesting.cli", "monitor-nasdaq-drop"); LogName = "nasdaq_monitor"; HeartbeatPath = "state\nasdaq_drop_monitor\heartbeat.json" },
    @{ Type = "Heartbeat"; Match = "monitor-dashboard"; Args = @("-m", "backtesting.cli", "monitor-dashboard"); LogName = "dashboard_monitor"; HeartbeatPath = "state\dashboard_monitor\heartbeat.json" },
    @{ Type = "Http"; Match = "cli dashboard(\s|$)"; Args = @("-m", "backtesting.cli", "dashboard", "--port", "8765"); LogName = "dashboard_server"; Url = "http://127.0.0.1:8765/" }
)

# 두 대상의 폴링 주기(15초/30초)보다 훨씬 여유있게, 그러나 이 watchdog 자신의 점검
# 주기(300초)보다는 짧게 잡아 다음 점검에서 곧바로 죽거나 멈춘 프로세스를 잡아낸다.
$staleThresholdSeconds = 120
$httpTimeoutSeconds = 5

function Test-HeartbeatFresh([string]$HeartbeatPath) {
    $fullPath = Join-Path $repoRoot $HeartbeatPath
    if (-not (Test-Path $fullPath)) { return $false }
    try {
        $data = Get-Content $fullPath -Raw | ConvertFrom-Json
        $ageSeconds = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [double]$data.updated_at
        return $ageSeconds -lt $staleThresholdSeconds
    } catch {
        return $false  # 손상됐거나 읽을 수 없는 하트비트 = 생존 확인 불가로 취급
    }
}

function Test-HttpHealthy([string]$Url) {
    try {
        $res = Invoke-WebRequest -Uri $Url -TimeoutSec $httpTimeoutSeconds -UseBasicParsing
        return $res.StatusCode -lt 500
    } catch {
        return $false
    }
}

function Test-TargetAlive($Target) {
    if ($Target.Type -eq "Http") { return Test-HttpHealthy $Target.Url }
    return Test-HeartbeatFresh $Target.HeartbeatPath
}

# ---- 자율 전략 개선 사이클 (auto_develop_prompt.md 참고) ----
# 이건 "항상 켜짐"이 아니라 "주기적으로 딱 한 번" 실행되는 작업이라 위 heartbeat/http
# 대상들과 성격이 다르다 — 하지만 이 스크립트가 이미 5분마다 깨어나므로 별도의
# 두 번째 스케줄러 프로세스를 새로 띄우는 대신 이 루프에 얹는다.
$autoDevelopCadenceSeconds = 7 * 24 * 3600  # 주 1회
$autoDevelopStuckThresholdSeconds = 6 * 3600  # 시작만 하고 6시간 넘게 안 끝나면 죽었다고 보고 재시도 허용

function Test-AutoDevelopDue {
    $startedPath = Join-Path $repoRoot "state\auto_develop\last_run_started.json"
    $finishedPath = Join-Path $repoRoot "state\auto_develop\last_run_finished.json"

    if (Test-Path $startedPath) {
        try {
            $started = [double](Get-Content $startedPath -Raw | ConvertFrom-Json).started_at
            $finishedAt = $null
            if (Test-Path $finishedPath) {
                $finishedAt = [double](Get-Content $finishedPath -Raw | ConvertFrom-Json).finished_at
            }
            # 마지막 시작이 마지막 종료보다 최신인데(=현재 실행 중이거나 멈춘 상태) 아직
            # stuck 임계값을 안 넘었으면 새로 띄우지 않는다 — 중복 실행 방지.
            if ($null -eq $finishedAt -or $finishedAt -lt $started) {
                $sinceStarted = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $started
                if ($sinceStarted -lt $autoDevelopStuckThresholdSeconds) { return $false }
            }
        } catch {
            return $false  # 상태 파일이 손상됐으면 판단 불가 — 다음 사이클에 재확인
        }
    }

    if (-not (Test-Path $finishedPath)) { return $true }  # 한 번도 실행된 적 없음
    try {
        $finished = [double](Get-Content $finishedPath -Raw | ConvertFrom-Json).finished_at
        $age = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $finished
        return $age -ge $autoDevelopCadenceSeconds
    } catch {
        return $false
    }
}

function Remove-StaleAutoDevelopWorktrees {
    # auto_develop_prompt.md 자신은 자기 worktree를 못 지우므로(메인 체크아웃에서만
    # git worktree remove 가능), 다음 사이클을 새로 띄우기 직전에 여기서 정리한다.
    # 이 시점엔 Test-AutoDevelopDue로 이전 사이클이 이미 끝났다는 게 확인된 상태다.
    try {
        $currentPath = $null
        foreach ($line in (git -C $repoRoot worktree list --porcelain)) {
            if ($line -match "^worktree (.+)$") {
                $currentPath = $Matches[1]
            } elseif ($line -match "^branch refs/heads/((worktree-)?auto-develop-\S+)$" -and $currentPath) {
                $branchName = $Matches[1]
                # 클로드 세션이 죽어도 worktree lock이 안 풀리는 경우가 있어(실제로 겪음)
                # --force를 두 번 줘야 lock까지 무시하고 지운다.
                try { git -C $repoRoot worktree remove --force --force $currentPath 2>$null } catch {}
                try { git -C $repoRoot branch -D $branchName 2>$null } catch {}
                $currentPath = $null
            }
        }
    } catch {
        # 정리 실패해도 watchdog은 계속 돈다 — 다음 폴링에서 재시도됨
    }
}

# ---- 2026-08-07 장중 베이스라인 수정 확인 (일회성 — 확인 끝나면 이 블록 통째로 지워도 됨) ----
# trading_value_ranking.py의 _ensure_baseline이 빈 베이스라인을 확정으로 안 믿게 고친 게
# 내일 장 시작 후 실제로 동작하는지 사람이 그 시간에 안 붙어있어도 확인하려고 추가.
# 마커 파일이 생기면 그 뒤로는 영원히 다시 안 돈다(날짜 재확인 없음 — 진짜 1회성).
$baselineVerifyMarker = Join-Path $repoRoot "state\baseline_verify_2026-08-07_done.json"
$baselineVerifyDueAt = Get-Date "2026-08-07 09:05:00"

function Get-DotEnvValue([string]$Key) {
    $envPath = Join-Path $repoRoot ".env"
    if (-not (Test-Path $envPath)) { return $null }
    foreach ($line in Get-Content $envPath) {
        if ($line -match "^\s*$Key\s*=\s*(.+?)\s*$") { return $Matches[1].Trim('"') }
    }
    return $null
}

function Invoke-BaselineVerifyOnce {
    $lines = @("[baseline_verify] 2026-08-07 장중 베이스라인 수정 확인 결과")
    try {
        $baselinePath = Join-Path $repoRoot "state\regular_session_baseline.json"
        if (Test-Path $baselinePath) {
            $baseline = Get-Content $baselinePath -Raw | ConvertFrom-Json
            $count = ($baseline.baseline.PSObject.Properties | Measure-Object).Count
            if ($baseline.date -eq "2026-08-07" -and $count -gt 0) {
                $lines += "PASS baseline: date=$($baseline.date), 종목수=$count"
            } else {
                $lines += "FAIL baseline: date=$($baseline.date), 종목수=$count (오늘자+비어있지 않아야 정상)"
            }
        } else {
            $lines += "FAIL baseline: 파일 없음"
        }
    } catch {
        $lines += "FAIL baseline: 확인 중 오류 - $_"
    }

    try {
        $regular = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/trading-value-ranking?window=regular" -TimeoutSec 10
        $extended = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/trading-value-ranking?window=extended" -TimeoutSec 10
        $regTop = $regular.rows[0].trading_value
        $extTop = $extended.rows[0].trading_value
        if ($regTop -lt $extTop) {
            $lines += "PASS regular<extended: $regTop < $extTop ($($regular.rows[0].name))"
        } else {
            $lines += "FAIL regular<extended: $regTop >= $extTop (베이스라인이 여전히 안 빠지는 듯)"
        }
    } catch {
        $lines += "FAIL API 호출 오류 - $_"
    }

    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'"
        $dupDash = ($procs | Where-Object { $_.CommandLine -match "cli dashboard(\s|$)" } | Measure-Object).Count
        $dupS4 = ($procs | Where-Object { $_.CommandLine -match "monitor-signals.*strategy_4" } | Measure-Object).Count
        if ($dupDash -le 1 -and $dupS4 -le 1) {
            $lines += "PASS 중복 프로세스 없음 (dashboard=$dupDash, strategy_4=$dupS4)"
        } else {
            $lines += "FAIL 중복 프로세스 있음 (dashboard=$dupDash, strategy_4=$dupS4)"
        }
    } catch {
        $lines += "FAIL 프로세스 확인 오류 - $_"
    }

    $botToken = Get-DotEnvValue "TELEGRAM_BOT_TOKEN"
    $chatId = Get-DotEnvValue "TELEGRAM_CHAT_ID"
    $message = $lines -join "`n"
    if ($botToken -and $chatId) {
        try {
            Invoke-RestMethod -Uri "https://api.telegram.org/bot$botToken/sendMessage" -Method Post `
                -Body (@{ chat_id = $chatId; text = $message } | ConvertTo-Json) -ContentType "application/json" | Out-Null
        } catch {}
    }

    New-Item -ItemType Directory -Force -Path (Split-Path $baselineVerifyMarker) | Out-Null
    $message | Out-File -FilePath $baselineVerifyMarker -Encoding utf8
}

while ($true) {
    try {
        if (-not (Test-Path $baselineVerifyMarker) -and (Get-Date) -ge $baselineVerifyDueAt) {
            Invoke-BaselineVerifyOnce
        }

        $pythonProcesses = Get-CimInstance Win32_Process -Filter "Name='python.exe'"
        foreach ($target in $targets) {
            if (Test-TargetAlive $target) { continue }

            # 죽었거나 멈췄으면 같은 커맨드라인의 기존 프로세스가 남아있을 수 있으니
            # 먼저 정리한다 — 안 그러면 멈춘 프로세스와 새로 띄운 프로세스가 동시에 돌면서
            # (대시보드는 포트 충돌, 감시는 텔레그램 알림 중복 발송) 문제가 생긴다.
            $stuck = $pythonProcesses | Where-Object { $_.CommandLine -match $target.Match }
            foreach ($proc in $stuck) {
                try { Stop-Process -Id $proc.ProcessId -Force } catch {}
            }

            Start-Process -FilePath "python" -ArgumentList $target.Args `
                -WorkingDirectory $repoRoot -WindowStyle Hidden `
                -RedirectStandardOutput (Join-Path $repoRoot "$($target.LogName).log") `
                -RedirectStandardError (Join-Path $repoRoot "$($target.LogName).err.log")
        }

        if (Test-AutoDevelopDue) {
            Remove-StaleAutoDevelopWorktrees
            Start-Process -FilePath "powershell.exe" `
                -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "$repoRoot\run_auto_develop.ps1" `
                -WorkingDirectory $repoRoot -WindowStyle Hidden
        }
    } catch {
        # 이 확인/재시작 사이클 하나가 실패해도 watchdog 자체는 죽으면 안 된다 —
        # 이게 죽으면 "항상 켜짐" 보장이 아무도 모르게 통째로 깨진다.
    }

    Start-Sleep -Seconds 300
}
