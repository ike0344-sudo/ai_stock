# execution-agent 큐

- [x] 실거래 게이트 날짜 검증 마무리 (진행 중이면 그것부터)
- [x] ka10075 필드명 실계좌 미검증 위험 — 모의투자로 최소 1회 실주문을 넣어
      필드가 실제로 어떻게 오는지 확인할 수 있는지 판단해라. 가능하면 절차를
      제안만 하고 실행은 사용자 승인 후. 불가능하면 왜인지 밝혀라.
      → state/agent_reports/execution-agent_20260830-092507.md (판단: 가능, 절차 제안, 실행 안 함)
- [x] 주문 실패 시나리오 정리 — 부분체결, 타임아웃 취소 실패, 재시작 중 미체결,
      API 응답 지연. 각각 지금 코드가 어떻게 행동하고 무엇이 안 막혀 있는지.
      → state/agent_reports/execution-agent_20260830-092555.md (핵심 위험 2건: 취소실패 무한재시도 무알림, 재시작복원 실패 시 조용히 고아됨)
- [x] 실거래 첫 주문 리허설 절차 문서화 — 모의에서 무엇을 확인하고 넘어가야 하는지
      순서대로. state/agent_reports/ 에 남겨라.
      → state/agent_reports/execution-agent_20260830-092641.md, risk-agent와 6·7단계 겹쳐 편지 조율 요청함(state/agent_mail/risk-agent/20260830-092708_live-rehearsal-overlap.md)
