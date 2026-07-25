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

while ($true) {
    try {
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
    } catch {
        # 이 확인/재시작 사이클 하나가 실패해도 watchdog 자체는 죽으면 안 된다 —
        # 이게 죽으면 "항상 켜짐" 보장이 아무도 모르게 통째로 깨진다.
    }

    Start-Sleep -Seconds 300
}
