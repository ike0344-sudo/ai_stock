from: monitoring-agent · reply: yes(orca-tell.ps1 수정 승인 여부)

## 앞선 결론 정정 — "재부팅 후 pane 없을 때 조용한 실패"는 검증 안 됐다, 실측하니 더 나쁜 문제 발견

격리된 스크래치 디렉터리(레포 밖, `orca-tell.ps1`+가짜 handles.json 복사본)로 3가지 케이스를 12회씩 재현:

| 케이스 | orca-tell 결과 | agent-poke 카운트 | 경고 로그 |
|---|---|---|---|
| handles.json에 없는 agent 이름 | `Write-Error` | fail 12/12 | 1·11번째에만 (설계대로) |
| handles.json 파일 자체 없음(진짜 재부팅 직후) | `Write-Error` | fail 12/12 | 1·11번째에만 (설계대로) |
| **handle은 있지만 죽은 pane(세션 닫힘 — 사용자가 말한 실제 시나리오)** | **"보냄 → agent" 출력, orca.exe 내부는 exit code 1로 실패했지만 orca-tell.ps1이 $LASTEXITCODE를 안 봐서 성공으로 위장** | **success 12/12, fail 0/12** | **없음 — 영원히** |

## 원인
`orca-tell.ps1:36` `& $Orca terminal send ...`가 실패해도 PowerShell native-command 비정상 종료는 자동으로 예외를 안 던진다. `$LASTEXITCODE` 체크가 없어서 다음 줄 `Write-Host "보냄 → $Agent"`가 무조건 실행된다. 내가 agent-poke.ps1에 넣은 "연속 10회 실패 시 경고" 로직은 `Write-Error` 경로만 잡아서, 이 케이스(가장 흔할 실제 재부팅 시나리오 — handles.json 파일 자체는 재부팅 후에도 남아있고 안의 handle들만 죽어있음)는 전혀 못 잡는다.

## 의미
지난 보고(20260830-0910)에서 "재부팅 후 조용한 실패는 로직상 처리했지만 실측 안 함"이라 썼는데, 실측해보니 **처리가 안 돼 있었다.** 재부팅하면 agent-poke는 매 사이클 "성공"만 찍으면서 아무도 못 깨우는 상태가 될 수 있다 — 사용자가 가장 우려한 "조용히 죽는" 패턴이 그대로 재현됨.

## 제안 (승인 요청)
`orca-tell.ps1:36` 뒤에 `if ($LASTEXITCODE -ne 0) { Write-Error "orca 전송 실패(exit $LASTEXITCODE): $Agent" }` 한 줄 추가. orca-tell.ps1은 6개 agent 전체가 공유하는 도구라 임의로 안 고치고 승인부터 구한다. 승인되면 바로 반영 + 같은 harness로 재검증(success 0/12, fail 12/12로 바뀌는지)까지 하고 결과 다시 올리겠다.
