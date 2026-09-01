# 안 읽은 편지 또는 안 뽑은 큐 항목이 있는 에이전트만 깨운다.
#
# herdr pane 은 별도 claude 세션이라 SendMessage 가 없다. 파일로 편지를 주고받되,
# claude 세션은 반응형이라 입력이 없으면 편지가 와도 안 읽는다 — 그래서 깨워야 한다.
#
#   .\agent-poke.ps1            한 번 훑고 끝
#   .\agent-poke.ps1 -Loop      60초마다 반복 (Ctrl+C 로 중단)
#   .\agent-poke.ps1 -WhatIf    깨우지 않고 누구를 깨울지만 출력
param([switch]$Loop, [switch]$WhatIf, [int]$IntervalSeconds = 60)

$Repo = $PSScriptRoot
$Mail = Join-Path $Repo "state\agent_mail"
$Queue = Join-Path $Repo "state\agent_queue"
# orca 가 아니라 herdr 로 보낸다. 2026-08-31 실측: .orca-team-handles.json 의 핸들
# (term_<uuid>)은 지금 도는 herdr pane(term_65a3039a...)과 형식부터 다른 죽은 핸들이라
# orca-tell 이 빈 응답 + exit 0 으로 조용히 아무것도 안 하고 있었다 — poke 는 그걸
# "깨움 성공"으로 세고 있었다. herdr 는 에이전트를 이름으로 지목하니 핸들 파일도 필요 없다.
$Herdr = if ($env:HERDR_BIN_PATH) { $env:HERDR_BIN_PATH } else { "herdr" }
$HeartbeatPath = Join-Path $Repo "state\agent_poke\heartbeat.json"

# 한글을 exe 로 넘길 때 콘솔 인코딩을 탄다 — Windows PowerShell 은 $OutputEncoding 이
# US-ASCII, pwsh 는 콘솔이 cp949 라 한글이 깨진다(2026-08-30 실측: 지시 유실의 원인).
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false) } catch {}

# 체결 수집·백테스트·감시봇이 같이 도는 머신이라 이 프로세스는 우선순위를 낮춰둔다.
try { (Get-Process -Id $PID).PriorityClass = "BelowNormal" } catch {}

# 같은 에이전트를 연달아 깨우면 방금 준 일을 끊는다 — 한 번 깨우면 이만큼 쉰다.
$CooldownSeconds = 300
$lastPoked = @{}

# 큐는 편지보다 급하지 않다. 같은 주기로 찔러대면 "아직 대기 중"만 반복 보고하게 된다.
# 2026-09-01 사용자 지시로 30분 -> 10분. 짧게 줄이는 대신 아래에서 working 인 에이전트는
# 아예 건너뛴다 — 안 그러면 40분짜리 작업 도중에 지시가 네 번 쌓인다.
$QueueCooldownSeconds = 600
$lastQueuePoked = @{}

# pane 이 없을 때(재부팅 직후) / 세션이 닫혔을 때 herdr 가 매번
# 실패한다. 조용히 삼키되 완전히 무시하진 않는다 — 연속 10회마다 한 번만 남긴다.
$failCount = @{}

function Write-PokeHeartbeat {
    New-Item -ItemType Directory -Force -Path (Split-Path $HeartbeatPath) | Out-Null
    (@{ updated_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() } | ConvertTo-Json) |
        Out-File -FilePath $HeartbeatPath -Encoding utf8
}

function Invoke-Sweep {
    # 지금 일하고 있는(또는 승인창에 걸린) 에이전트는 건너뛴다. herdr agent prompt 는
    # 상대가 바빠도 입력창에 텍스트를 넣어버려서, 반복 호출하면 초안이 이어붙어 엉킨다.
    $busy = @{}
    try {
        $list = & $Herdr agent list 2>$null | ConvertFrom-Json
        foreach ($a in $list.result.agents) {
            if ($a.name -and ($a.agent_status -eq "working" -or $a.agent_status -eq "blocked")) {
                $busy[$a.name] = $a.agent_status
            }
        }
    } catch { }   # 조회 실패면 예전처럼 그냥 진행한다 — 안 깨우는 것보다 낫다

    foreach ($dir in Get-ChildItem $Mail -Directory -ErrorAction SilentlyContinue) {
        $agent = $dir.Name
        if ($busy.ContainsKey($agent)) {
            Write-Host "  $agent : $($busy[$agent]) — 건너뜀" -ForegroundColor DarkGray
            continue
        }
        # read/ 는 처리 완료분. 최상위에 남은 .md 만 안 읽은 편지다.
        # standing.md 는 상주하는 상시 임무 파일이라 편지가 아니다 — 세면 영원히 깨운다.
        # read/ 에 같은 이름 사본이 있으면 처리된 편지다 — 최상위 원본이 남아 있어도 안 센다.
        # 2026-08-31 실측: strategy-agent pane 은 Bash 가 없어(에이전트 정의상 Read/Write/Edit/
        # Grep/Glob 뿐) mv/rm 자체가 불가능하다. "옮겨라"는 규칙이 그 pane 에서는 원천적으로
        # 실행 불가라, 처리를 다 해놓고도 영원히 깨워지고 있었다. lead 가 "너에겐 Bash 가 있다"고
        # 두 번 잘못 판단했고, 에이전트가 재확인해 바로잡았다.
        $readDir = Join-Path $dir.FullName "read"
        $doneNames = @{}
        if (Test-Path $readDir) {
            foreach ($f in Get-ChildItem $readDir -Filter *.md -File -ErrorAction SilentlyContinue) {
                $doneNames[$f.Name] = $true
            }
        }
        $pending = @(Get-ChildItem $dir.FullName -Filter *.md -File -ErrorAction SilentlyContinue |
                     Where-Object { $_.Name -ne "standing.md" -and -not $doneNames.ContainsKey($_.Name) })

        # 편지가 없어도 큐에 안 뽑은 항목이 있으면 깨운다 - 안 그러면 이미 결정된 일을
        # 놔둔 채 유휴로 앉아 있고, lead 가 매번 손으로 찔러야 한다.
        # `- [>]` 는 선행 결과 대기라 뽑을 수 없는 항목이니 세지 않는다.
        $queueFile = Join-Path $Queue "$agent.md"
        $queueOpen = 0
        if (Test-Path $queueFile) {
            $queueOpen = @(Select-String -Path $queueFile -Pattern '^- \[ \] ' -ErrorAction SilentlyContinue).Count
        }

        if ($pending.Count -eq 0 -and $queueOpen -eq 0) { continue }

        if ($pending.Count -gt 0) {
            $last = $lastPoked[$agent]
            if ($last -and ((Get-Date) - $last).TotalSeconds -lt $CooldownSeconds) {
                Write-Host "  $agent : 편지 $($pending.Count)건 (쿨다운 중, 건너뜀)" -ForegroundColor DarkGray
                continue
            }
            $names = ($pending | Select-Object -First 3 | ForEach-Object { $_.Name }) -join ", "
            Write-Host "  $agent : 편지 $($pending.Count)건 → 깨움 ($names)" -ForegroundColor Green
            $text = "state/agent_mail/$agent/ 에 안 읽은 편지가 $($pending.Count)건 있다. 읽고 처리해라. " +
                    "처리한 편지는 그 폴더의 read/ 로 옮겨라 - 남아 있는 것이 안 읽은 것이다. " +
                    "판단이 필요하거나 앞선 결론을 뒤집는 내용이면 스스로 결정하지 말고 state/agent_reports/ 에 " +
                    "파일로 써서 lead 에게 올려라. 보낸 사람의 결론을 검증 없이 그대로 받아 쓰지 마라. " +
                    "지금 하던 일이 있으면 그것부터 끝내고 확인해도 된다."
        } else {
            $last = $lastQueuePoked[$agent]
            if ($last -and ((Get-Date) - $last).TotalSeconds -lt $QueueCooldownSeconds) {
                Write-Host "  $agent : 큐 $queueOpen 건 (쿨다운 중, 건너뜀)" -ForegroundColor DarkGray
                continue
            }
            Write-Host "  $agent : 큐 $queueOpen 건 → 깨움" -ForegroundColor Green
            $text = "state/agent_queue/$agent.md 에 안 뽑은 항목이 $queueOpen 건 있다. " +
                    "위에서부터 첫 `- [ ] `를 `- [~] `로 바꾸고 시작해라. 끝나면 `- [x] `로 바꾸고 " +
                    "state/STATUS.md 자기 행을 갱신해라. 순서를 바꾸지 마라. " +
                    "항목이 모호하거나 위험하면 하지 말고 state/agent_reports/ 에 파일로 써서 lead 에 물어라. " +
                    "선행 결과를 기다려야 해서 지금 못 하는 항목이면 `- [>] `로 바꿔라 - 그러면 다시 안 깨운다. " +
                    "지금 하던 일이 있으면 그것부터 끝내고 확인해도 된다."
        }

        if ($WhatIf) { continue }

        # herdr 는 서버 에러를 stderr 에 JSON 으로 주고 exit 1 을 낸다 — 종료코드를
        # 직접 봐야 한다. 죽은 pane 이면 여기서 진짜로 실패하니 조용한 무동작은 없다.
        $raw = & $Herdr agent prompt $agent $text 2>&1
        if ($LASTEXITCODE -eq 0) {
            $failCount[$agent] = 0
        } elseif ("$raw" -match 'agent_blocked') {
            # 승인창에서 멈춰 있다 — 죽은 게 아니다. 임의로 답하지 않고 넘어간다.
            Write-Host "  $agent : 승인창 대기중(blocked) - 사람이 봐야 한다" -ForegroundColor Yellow
        } elseif ("$raw" -match 'agent_prompt_stalled') {
            # 상대가 그냥 바쁠 뿐(살아있음). 재시도는 쿨다운 뒤 자동이라 카운트 안 올린다.
            Write-Host "  $agent : 바쁨(재시도는 쿨다운 뒤 자동)" -ForegroundColor DarkGray
        } else {
            $failCount[$agent] = [int]$failCount[$agent] + 1
            if ($failCount[$agent] % 10 -eq 1) {
                Write-Warning "poke 실패(누적 $($failCount[$agent])회) -> $agent : $raw"
            }
        }
        if ($pending.Count -gt 0) { $lastPoked[$agent] = Get-Date } else { $lastQueuePoked[$agent] = Get-Date }
    }
}

do {
    # 스윕이 오래 걸리거나 실패해도 워치독이 "죽었다"고 오판하지 않도록 먼저 찍는다.
    Write-PokeHeartbeat
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 편지함 확인" -ForegroundColor Cyan
    try { Invoke-Sweep } catch { Write-Warning "sweep 오류: $_" }
    if ($Loop) { Start-Sleep -Seconds $IntervalSeconds }
} while ($Loop)
