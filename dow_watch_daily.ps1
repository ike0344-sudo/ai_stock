# 다우 추세 등급을 매 거래일 장 마감 후 한 번 판정하고, 등급이 바뀌면 텔레그램을 보낸다.
# Task Scheduler 등록이 이 계정에서 Access Denied로 막히므로(UAC 필터링),
# nasdaq_monitor_watchdog.ps1과 같은 방식 — 시작 폴더에서 띄운 뒤 자기 자신이 무한 루프를 돈다.
# 항상 켜져 있어야 하는 감시 프로세스가 아니라 "하루 한 번" 작업이므로 watchdog에 얹지 않고
# 따로 둔다(그 파일은 나스닥 감시 생존이 걸려 있어 변경 위험을 지지 않는다).
$repoRoot  = "C:\Users\ike03\Desktop\code\ai_stock"
$runAfter  = 15.67          # 15:40 이후 (장 마감 15:30 + 데이터 반영 여유)
$stateFile = Join-Path $repoRoot "state\dow_watch_lastrun.txt"
$logFile   = Join-Path $repoRoot "dow_watch_daily.log"

New-Item -ItemType Directory -Force (Split-Path $stateFile) | Out-Null

function Get-LastRun {
    if (Test-Path $stateFile) { return (Get-Content $stateFile -Raw).Trim() }
    return ""
}

while ($true) {
    $now = Get-Date
    $today = $now.ToString("yyyy-MM-dd")
    $hour = $now.Hour + $now.Minute / 60.0
    $isWeekday = $now.DayOfWeek -ne "Saturday" -and $now.DayOfWeek -ne "Sunday"

    # PC가 15:40에 꺼져 있었다면 다음 부팅 때(같은 날 안이면) 밀린 실행을 한 번 처리한다.
    if ($isWeekday -and $hour -ge $runAfter -and (Get-LastRun) -ne $today) {
        "[$($now.ToString('yyyy-MM-dd HH:mm:ss'))] dow_watch 실행" | Add-Content $logFile
        try {
            Push-Location $repoRoot
            & python dow_watch.py --notify *>&1 | Add-Content $logFile
            Pop-Location
            $today | Set-Content $stateFile
        } catch {
            "[$($now.ToString('HH:mm:ss'))] 실패: $_" | Add-Content $logFile
        }
    }
    Start-Sleep -Seconds 300
}
