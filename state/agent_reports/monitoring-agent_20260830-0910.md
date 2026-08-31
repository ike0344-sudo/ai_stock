from: monitoring-agent · reply: no

## agent-poke.ps1 워치독 등록 — 완료
- `agent-poke.ps1`: 하트비트(`state/agent_poke/heartbeat.json`, 60초 주기) 추가, 우선순위 BelowNormal 설정, orca-tell 실패 시 조용히 삼키되 연속 10회마다 1번만 경고 로그
- `nasdaq_monitor_watchdog.ps1`: $targets에 agent-poke 추가(FilePath="powershell.exe" 신규 지원, 기존 대상은 기본값 python 그대로), stuck-process 정리 대상도 python.exe만 보던 걸 powershell.exe까지 확장(안 그러면 agent-poke가 멈춰도 안 죽이고 새로 못 띄움)
- 자가테스트 통과: monitoring-agent 편지함에 편지 넣음 → 실제 poke 도착(내 pane에 텍스트 수신) 확인 → 처리 후 read/로 이동 → 편지함 비우니 조용해짐(monitoring-agent 목록에서 빠짐) 확인
- monitor-nasdaq-drop: 두 번의 워치독 재기동(구코드 확인용 1회 + stale 하트비트 수정 후 1회) 동안 PID 31616 그대로, 하트비트 끊김 없음(재기동 직전 12.2초 → 직후 10.9초)
- 다른 대상(dashboard 8765=200, sophie_bot, tunnel_job, watch_surge) 전부 PID 불변

## 검증 중 발견한 문제(이번에 고침)
내가 수동으로 `agent-poke.ps1`을 1회성으로 두 번 실행해 테스트했는데, 그때 남은 하트비트 파일이 120초 임계값 안에 들어 있어 워치독이 "이미 살아있다"고 오판 — 실제로는 프로세스가 없는데도 안 띄움. `state/agent_poke/heartbeat.json` 삭제 후 재기동해서 해결. **일반화하면**: 수동 1회성 테스트가 하트비트 파일을 남기면 watchdog을 잠깐 속일 수 있다는 뜻 — 다른 대상 테스트할 때도 같은 함정 주의.

## 안 한 것 / 남은 위험
- agent-poke 자체의 장시간(수 시간) 생존은 아직 미관측 — 방금 뜬 것만 확인, 재부팅 후 pane 없을 때 "조용한 실패"는 실측 안 함(로직상으론 처리됨)
- 편지 중복발송 가능성 확인됨(내 수동 2회 테스트로 strategy-agent가 같은 편지로 2번 깨워짐) — Loop 모드에서는 쿨다운(300초)이 있어 문제 안 되지만 참고
