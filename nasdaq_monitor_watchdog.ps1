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
    @{ Type = "Http"; Match = "cli dashboard(\s|$)"; Args = @("-m", "backtesting.cli", "dashboard", "--port", "8765"); LogName = "dashboard_server"; Url = "http://127.0.0.1:8765/" },
    # 소피증권 모바일 화면(8770)을 외부에 여는 Cloudflare 터널. 무료 quick tunnel 은
    # 띄울 때마다 주소가 바뀌므로, tunnel_job.py 가 바뀐 주소를 텔레그램으로 보낸다.
    @{ Type = "Heartbeat"; Match = "tunnel_job"; Args = @("tunnel_job.py"); LogName = "tunnel"; HeartbeatPath = "state\tunnel\heartbeat.json" },
    # 텔레그램으로 소피증권에 물어보는 봇. **조회 전용**이라 계좌에 닿는 경로가 없다
    # (주문은 telegram_order_bot.py 몫이고, 조회하려다 손이 미끄러질 자리를 만들지
    # 않으려고 한 봇에 넣지 않는다). 8770 을 읽으므로 소피증권이 꺼져 있으면
    # "앱이 꺼져 있나요?"라고 답할 뿐 봇 자체는 계속 돈다.
    # 롱폴링 한 바퀴가 최대 50초라 하트비트를 폴링 **앞에서** 찍는다 — 뒤에 두면
    # 기동 직후 이 워치독이 표식을 못 보고 죽은 것으로 판단해 다시 띄운다.
    @{ Type = "Heartbeat"; Match = "sophie_bot"; Args = @("kospi-theme-engine\sophie_bot.py"); LogName = "sophie_bot"; HeartbeatPath = "state\sophie_bot\heartbeat.json" },
    # 소피증권 급등 알림 조건을 밖에서 재현·기록하는 감시기. 예전엔 사람이 손으로
    # Start-Process 로 띄웠는데, 그 계보(내 도구 세션의 자식)가 watchdog·sophie_bot처럼
    # 완전히 detach되지 않아 알 수 없는 시점에 조용히 죽었다(2026-08-29). 여기 등록하면
    # watchdog 자신의 계보에서 뜨고, 죽어도 5분 내 자동 복구된다.
    @{ Type = "Heartbeat"; Match = "watch_surge"; Args = @("kospi-theme-engine\watch_surge.py"); LogName = "watch_surge"; HeartbeatPath = "state\watch_surge\heartbeat.json" },
    # 편지함(state/agent_mail/)에 안 읽은 편지가 있는 에이전트 pane 만 깨운다. claude
    # 세션은 반응형이라 편지가 와도 입력이 없으면 안 읽는다 — 파이썬이 아니라 ps1이라
    # FilePath 를 명시한다(기본값은 python).
    @{ Type = "Heartbeat"; Match = "agent-poke"; FilePath = "powershell.exe"
       Args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "agent-poke.ps1", "-Loop")
       LogName = "agent_poke"; HeartbeatPath = "state\agent_poke\heartbeat.json" },
    # 소피증권 실시간 체결 웹소켓이 실제로 데이터를 받는지(포트 응답이 아니라 엔진
    # 틱 카운터·로그 갱신)를 본다. 2026-08-30 실측: 8770 포트는 응답하는데 피드가
    # 6일간 죽어있었고 아무 알림도 없었다 — monitor-nasdaq-drop/dashboard와 달리
    # 프로세스 생존 확인만으로는 이 사고를 못 잡는다(결과 기준 감시가 필요했던 이유).
    @{ Type = "Heartbeat"; Match = "monitor-sophie-feed"; Args = @("-m", "backtesting.cli", "monitor-sophie-feed"); LogName = "sophie_feed_monitor"; HeartbeatPath = "state\sophie_feed_monitor\heartbeat.json" }
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
        if ($dupDash -le 1) {
            $lines += "PASS 중복 프로세스 없음 (dashboard=$dupDash)"
        } else {
            $lines += "FAIL 중복 프로세스 있음 (dashboard=$dupDash)"
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

# ---- 클린20 리포트 일일 갱신 (daily_report_job.py) ----
# auto_develop과 같은 "주기적으로 딱 한 번" 성격이라 같은 패턴을 쓴다. 장 마감 후
# 정정 시세까지 반영되도록 16시 이후에만 돌리고, 하루에 한 번만 돈다.
$dailyReportHour = 16
# 유니버스가 2,000종목으로 늘어 백필이 3.6시간 걸린다(2026-09-15 실측 13,093초). 3시간이면
# 멀쩡히 도는 회차를 멈춘 것으로 보고 하나를 더 띄워, 둘이 data/ 를 동시에 쓴다.
$dailyReportStuckThresholdSeconds = 6 * 3600

function Test-DailyReportDue {
    if ((Get-Date).Hour -lt $dailyReportHour) { return $false }
    if ((Get-Date).DayOfWeek -in @("Saturday", "Sunday")) { return $false }

    $startedPath = Join-Path $repoRoot "state\daily_report\last_run_started.json"
    $finishedPath = Join-Path $repoRoot "state\daily_report\last_run_finished.json"

    # 실행 중이면(시작 > 종료) stuck 임계값 전까지는 새로 안 띄운다 — 중복 실행 방지
    if (Test-Path $startedPath) {
        try {
            $started = [double](Get-Content $startedPath -Raw | ConvertFrom-Json).started_at
            $finishedAt = $null
            if (Test-Path $finishedPath) {
                $finishedAt = [double](Get-Content $finishedPath -Raw | ConvertFrom-Json).finished_at
            }
            if ($null -eq $finishedAt -or $finishedAt -lt $started) {
                $sinceStarted = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $started
                if ($sinceStarted -lt $dailyReportStuckThresholdSeconds) { return $false }
            }
        } catch {
            return $false
        }
    }

    if (-not (Test-Path $finishedPath)) { return $true }
    try {
        # **오늘 시작해서** 끝난 것이 있으면 이미 돈 것 (실패였어도 같은 날 재시도는 안 한다 —
        # API 한도/장애가 원인일 때 5분마다 재시도하면 상황을 더 나쁘게 만든다).
        #
        # 예전엔 **완료 날짜**만 봤다. 백필이 3시간 넘게 걸려서, 밤에 시작한 회차가 자정을
        # 넘겨 끝나면 그 완료가 "오늘 돈 것"으로 읽혀 **다음 날 회차가 통째로 건너뛰어졌다**
        # (2026-09-15 22:05 시작 -> 09-16 01:43 완료 -> 09-16 16:00 회차 없음 -> 09-17 아침
        # 소피증권이 "일봉이 밀린 종목 2,124개"로 떴다). 시작 날짜로 본다.
        $finished = [double](Get-Content $finishedPath -Raw | ConvertFrom-Json).finished_at
        if (-not (Test-Path $startedPath)) {
            return [DateTimeOffset]::FromUnixTimeSeconds([long]$finished).ToLocalTime().Date -lt (Get-Date).Date
        }
        $startedAt = [double](Get-Content $startedPath -Raw | ConvertFrom-Json).started_at
        $startedLocal = [DateTimeOffset]::FromUnixTimeSeconds([long]$startedAt).ToLocalTime().Date
        $ranToday = ($startedLocal -eq (Get-Date).Date) -and ($finished -ge $startedAt)
        return -not $ranToday
    } catch {
        return $false
    }
}

# ---- 통합 분봉 기준선 격주 갱신 (kospi-theme-engine/run_minute_refresh.ps1) ----
# 소피증권의 유입속도(flow_speed 14점)는 과거 분봉으로 만든 기준선을
# 분모로 쓴다. 그 창이 낡으면 분모가 실제보다 작아져 여러 테마가 상한에 붙고
# 서로 구분이 안 된다. 창은 20거래일이라 격주면 절반이 갱신된다.
#
# 4~5시간짜리라 장이 없는 토요일에만 돌린다. daily_report 와 같은 표식 규약을 쓴다.
# 경로를 문자열 하나로 적지 않고 Join-Path 를 두 번 겹친다. 예전에는 폴더와 파일을
# 역슬래시로 이어 한 문자열에 적었는데, 그 역슬래시와 뒤따르는 r 이 어떤 도구를
# 거치며 캐리지리턴으로 해석돼 문자열이 두 줄로 쪼개졌다. PowerShell 큰따옴표는
# 여러 줄을 허용하므로 **문법 오류조차 안 나고** 존재하지 않는 경로가 된다.
# 그러면 아래 Test-Path 가 조용히 false 를 내서 분봉 갱신이 영영 안 돈다
# (2026-08-20 ~ 08-27 실제로 그랬다 — 5거래일치 분봉이 통째로 안 쌓였다).
$minuteRefreshScript = Join-Path (Join-Path $repoRoot 'kospi-theme-engine') 'run_minute_refresh.ps1'
$minuteRefreshHour = 9
$minuteRefreshEveryDays = 13          # 격주. 토요일에만 도므로 13일이면 2주 뒤 토요일에 걸린다
$minuteRefreshStuckThresholdSeconds = 6 * 3600

function Test-MinuteRefreshDue {
    if (-not (Test-Path $minuteRefreshScript)) {
        # 조용히 넘어가면 "안 돌 때가 아니었다"와 "못 찾았다"를 구분할 수 없다.
        New-Item -ItemType Directory -Force -Path (Join-Path $repoRoot "state\minute_refresh") | Out-Null
        "스크립트를 못 찾음: $minuteRefreshScript" |
            Out-File -FilePath (Join-Path $repoRoot "state\minute_refresh\missing.txt") -Encoding utf8
        return $false
    }
    if ((Get-Date).DayOfWeek -ne "Saturday") { return $false }
    if ((Get-Date).Hour -lt $minuteRefreshHour) { return $false }

    $startedPath = Join-Path $repoRoot "state\minute_refresh\last_run_started.json"
    $finishedPath = Join-Path $repoRoot "state\minute_refresh\last_run_finished.json"

    # 실행 중이면(시작 > 종료) stuck 임계값 전까지 새로 안 띄운다 — 중복 실행 방지
    if (Test-Path $startedPath) {
        try {
            $started = [double](Get-Content $startedPath -Raw | ConvertFrom-Json).started_at
            $finishedAt = $null
            if (Test-Path $finishedPath) {
                $finishedAt = [double](Get-Content $finishedPath -Raw | ConvertFrom-Json).finished_at
            }
            if ($null -eq $finishedAt -or $finishedAt -lt $started) {
                $sinceStarted = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $started
                if ($sinceStarted -lt $minuteRefreshStuckThresholdSeconds) { return $false }
            }
        } catch {
            return $false
        }
    }

    if (-not (Test-Path $finishedPath)) { return $true }
    try {
        $finished = [double](Get-Content $finishedPath -Raw | ConvertFrom-Json).finished_at
        $days = ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $finished) / 86400
        return $days -ge $minuteRefreshEveryDays
    } catch {
        return $false
    }
}

$watchdogHeartbeatPath = Join-Path $repoRoot "state\watchdog\heartbeat.json"

while ($true) {
    try {
        # 워치독 자신이 살아있다는 증거. "powershell.exe 프로세스가 떠있다"는 걸로는
        # 이 루프가 멈췄는지(예: 위 함수 중 하나가 무한 대기) 판단할 수 없다.
        New-Item -ItemType Directory -Force -Path (Split-Path $watchdogHeartbeatPath) | Out-Null
        (@{ updated_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() } | ConvertTo-Json) |
            Out-File -FilePath $watchdogHeartbeatPath -Encoding utf8

        # investor.jsonl/surge.jsonl은 재수집 불가한 시계열이라 매 사이클 백업한다.
        # 멱등적(오늘자 파일을 최신 누적본으로 덮어쓰기)이라 5분마다 불러도 무해하다.
        try { & python (Join-Path $repoRoot "kospi-theme-engine\backup_logs.py") 2>&1 | Out-Null } catch {}

        if (Test-MinuteRefreshDue) {
            Start-Process -FilePath "powershell.exe" `
                -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $minuteRefreshScript, "-Now") `
                -WorkingDirectory (Split-Path -Parent $minuteRefreshScript) -WindowStyle Hidden
        }

        if (Test-DailyReportDue) {
            Start-Process -FilePath "python" -ArgumentList @("daily_report_job.py") `
                -WorkingDirectory $repoRoot -WindowStyle Hidden `
                -RedirectStandardOutput (Join-Path $repoRoot "daily_report.log") `
                -RedirectStandardError (Join-Path $repoRoot "daily_report.err.log")
        }

        if (-not (Test-Path $baselineVerifyMarker) -and (Get-Date) -ge $baselineVerifyDueAt) {
            Invoke-BaselineVerifyOnce
        }

        # python.exe 뿐 아니라 powershell.exe 대상(agent-poke.ps1)도 있어 둘 다 훑는다.
        $candidateProcesses = Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='powershell.exe'"
        foreach ($target in $targets) {
            if (Test-TargetAlive $target) { continue }

            # 죽었거나 멈췄으면 같은 커맨드라인의 기존 프로세스가 남아있을 수 있으니
            # 먼저 정리한다 — 안 그러면 멈춘 프로세스와 새로 띄운 프로세스가 동시에 돌면서
            # (대시보드는 포트 충돌, 감시는 텔레그램 알림 중복 발송) 문제가 생긴다.
            $stuck = $candidateProcesses | Where-Object { $_.CommandLine -match $target.Match }
            foreach ($proc in $stuck) {
                try { Stop-Process -Id $proc.ProcessId -Force } catch {}
            }

            $exe = if ($target.FilePath) { $target.FilePath } else { "python" }
            Start-Process -FilePath $exe -ArgumentList $target.Args `
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
