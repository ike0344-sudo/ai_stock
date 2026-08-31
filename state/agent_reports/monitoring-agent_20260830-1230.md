from: monitoring-agent · reply: no

## orca-tell.ps1 문구 정정 + agent-poke 실패카운트 분리 — 완료·재검증

**JSON 재확인 결과**: `agent_prompt_stalled` 응답 본문(id/ok/error.code/error.message/_meta)에 "실제로 큐잉됐는지" 구분하는 필드 없음 — 직접 확인함. 그리고 오늘 재현해보니(내 pane에 재전송) stalled 에러가 떠도 텍스트가 실제로 도착하는 경우가 흔하다는 lead 관찰과 일치 — API로는 구분 불가능하다는 뜻이라 문구만 정확히 고쳤다.

- `orca-tell.ps1`: "전송 보류...실패로 들리는 워딩" → **"[STALLED] 전송했으나 상대가 생성 중이라 처리 여부 미확인"** 으로 변경. `terminal_handle_stale`(진짜 죽음) 쪽 문구는 그대로 유지(이건 구분됨 — error.code로 확실히 다름).
- `agent-poke.ps1`: `[STALLED]` 태그를 매칭해서 실패카운트(`$failCount`)에 안 넣도록 분리. 이유: 6개 pane이 거의 항상 바쁜 상황이라 stalled를 실패로 세면 "연속10회 경고"가 정상 상황에서도 계속 울려 진짜 죽은 pane 신호가 묻힌다. stalled는 조용히(DarkGray 로그만) 넘어가고, 죽은 pane만 경고 카운트.
- 쿨다운(300초)은 원래도 성공/실패 무관하게 무조건 적용되는 구조라(`$lastPoked` 갱신이 try/catch 밖에 있음) — 재시도 폭주 위험은 애초에 없었음, 확인만 하고 손 안 댐.

## 검증
격리 스크래치(가짜 stalled-agent/dead-agent + stub orca-tell.ps1)로 agent-poke 전체를 실행: stalled-agent는 "바쁨(재시도는 쿨다운 뒤 자동)"만 찍고 카운트 없음, dead-agent는 "poke 실패(누적 1회)" 경고 정상 발생 — 설계대로 분리됨 확인.

## 재기동
오늘 세 번째로 "코드 고침 ≠ 반영됨" 패턴 재발 — agent-poke가 watchdog 재기동 후에도 orphan으로 계속 살아있어서(하트비트 신선 = 안 죽음) 옛 코드를 계속 씀. 하트비트 파일 직접 삭제 후 재기동해서 새 PID 9384로 교체 확인. monitor-nasdaq-drop(PID 31616): 이번 재기동 3회 내내 끊김 없음.

## 안 한 것
- stalled 케이스에서 실제 도착 여부를 API 밖에서 확인하는 방법(예: -Read로 화면 재확인)은 자동화 안 함 — 매번 자동 재확인하면 호출이 2배 늘고 그 자체도 또 stalled 날 수 있어 과설계로 판단, 사람이 필요시 -Read로 확인하는 걸로 충분하다고 봄.
