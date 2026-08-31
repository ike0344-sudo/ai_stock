from: monitoring-agent · reply: no

## orca-tell.ps1 수정 반영 + 재검증 완료, 그리고 하나 더 발견
- `orca-tell.ps1:41-58` exit-code 체크 추가(승인분). 격리 harness 재실행: 죽은 handle 케이스 success=0/fail=12로 정정됨(수정 전엔 success=12/fail=0로 위장했었음). 다른 두 케이스(모르는 이름/handles파일 없음)도 fail=12 그대로, 회귀 없음.
- lead가 넣은 인코딩 수정(16-19행)도 실측: 실제 pane(내 자신)에 한글+화살표+가나 혼합 텍스트("한글확인 화살표 → 완료 テスト")를 보내 도착 화면을 확인 — 깨짐 없이 완전히 그대로 도착. 인코딩 수정 작동 확인.

**추가 발견(실측 중 우연히 나옴)**: exit 1이 사실 두 가지 다른 상황에서 똑같이 난다 — `error.code`로 구분됨.
- `terminal_handle_stale`: pane이 진짜 죽음 (재부팅/세션종료 케이스, 원래 의심하던 것)
- `agent_prompt_stalled`: 상대가 지금 생성 중이라 바쁠 뿐 — **살아있음**. 실제로 상대 입력창에 텍스트가 초안으로 남아 다음 send와 이어붙는 것도 직접 재현함(정확히 MEMORY의 `orca-pane-input-draft-trap`). "죽었다"고 뭉뚱그리면 오진단이라 메시지를 분기시켰다.

## 판단 (요청받은 2가지)
1. **신호 방식**: Write-Error + `$LASTEXITCODE` 체크로 충분하다고 판단. agent-poke는 이미 EAP=Stop+try/catch로 확실히 잡음(harness로 검증됨), lead 대화형 세션에서도 Write-Error 기본출력(빨간 글씨)이 눈에 띈다. throw/명시적 `exit N` 추가는 지금 안 함 — 필요하면 그때 추가.
2. **인코딩**: 위 실측대로 검증 완료, 이상 없음.

## agent-poke 워치독 등록
이미 완료·검증된 건(20260830-0910 보고, PID 24932)이라 새로 안 함 — 방금 재확인만: monitor-nasdaq-drop(PID 31616) 하트비트 11.8초, agent-poke(PID 24932) 하트비트 35.3초, 둘 다 신선. 오늘 이 turn 동안 orca-tell.ps1 세 번 수정·재검증하는 내내 두 프로세스 PID 불변.

## 안 한 것
- `agent_prompt_stalled`로 인해 상대 입력창에 남았을 초안을 자동으로 지우는 로직은 안 만들었다 — 잘못 지우면 더 위험해서(사용자가 직접 입력 중이던 걸 지울 수 있음), 경고만 하고 사람 판단에 맡김.
