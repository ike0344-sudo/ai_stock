# 자율 전략 개선 사이클 1회 실행 — nasdaq_monitor_watchdog.ps1이 주기가 되면 이 스크립트를
# 백그라운드로 띄운다. 격리를 위해 매번 새 git worktree(새 브랜치)에서 실행하고,
# 결과는 auto_develop_prompt.md의 규칙에 따라 검증 통과 시에만 origin/main에 push된다
# (로컬 main 체크아웃/작업 디렉토리는 절대 건드리지 않음).
$repoRoot = "C:\Users\ike03\Desktop\code\ai_stock"
$branchName = "auto-develop-" + (Get-Date -Format "yyyyMMdd-HHmmss")
$worktreePath = Join-Path $repoRoot ".worktrees\$branchName"
$logPath = Join-Path $repoRoot "auto_develop.log"

Set-Location $repoRoot

# worktree는 origin/main 기준으로 만들어지므로, 로컬 main이 origin보다 앞서있으면
# 그 worktree엔 최신 검증 도구(validate_strategy*.py 등)가 없어 사이클이 매번 막힌다.
# 그래서 worktree를 만들기 전에 로컬 main을 origin에 먼저 반영해 둘 항상 최신 상태로 맞춘다
# (2026-07-26, 첫 테스트 실행에서 실제로 겪은 문제 — 사용자 승인된 정책).
git push origin main *>> $logPath

git worktree add $worktreePath -b $branchName *>> $logPath

# data/(로컬 캔들 캐시)와 .env(키움 API 자격증명)는 .gitignore 대상이라 새 worktree엔
# 절대 안 생긴다 — validate_strategy1/2가 실행 불가능해 두 번째 실전 사이클이 그대로
# 막혔었다(2026-07-26). junction/hardlink로 메인 체크아웃의 실제 파일을 그대로 연결해
# 디스크 복사 없이 접근 가능하게 한다.
if (Test-Path (Join-Path $repoRoot "data")) {
    cmd /c mklink /J "$worktreePath\data" "$repoRoot\data" *>> $logPath
}
if (Test-Path (Join-Path $repoRoot ".env")) {
    New-Item -ItemType HardLink -Path "$worktreePath\.env" -Target (Join-Path $repoRoot ".env") *>> $logPath
}

Push-Location $worktreePath
Get-Content (Join-Path $repoRoot "auto_develop_prompt.md") -Raw |
    & claude -p --permission-mode bypassPermissions --max-budget-usd 5 --output-format json *>> $logPath
Pop-Location
