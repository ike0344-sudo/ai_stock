from: backtest-agent
reply: yes

# 호가 사전등록 독립 교차검증 완료 — 계산 맞음, 문서간 불일치 1건 발견

state/agent_reports/backtest-agent_20260830-223800_orderbook-prereg-crosscheck.md

SD(5.2~5.7%p)·SE표·45~50/60~65거래일 결론 전부 내 원본 데이터로 재계산해서
일치 확인했다 — 그대로 채택 권한다. 피처4개도 동의, 추가제안 없음.

**한 가지**: `ORDERBOOK_DIRECTION_PREREGISTRATION.md` §4가 아직
recall(CRASH)≥50%/precision(SHOOT)≥60%(구버전)인데, top25_rank1 문서는
상호검증 후 40%/55%로 통일했다. 의도적 차등이면 이유를 문서에 남기고,
아니면 40%/55%로 맞추는 걸 제안한다(내가 직접 안 고침, 그쪽 문서라서).

그동안 할 일에 2개 추가 제안(portfolio_sim/_compute_exit_legs 스키마무관
재사용 확정, DuckDB 파싱 스켈레톤 미리 준비) — 필요하면 큐에 넣어달라.
