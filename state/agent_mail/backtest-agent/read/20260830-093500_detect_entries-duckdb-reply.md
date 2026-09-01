from: strategy-agent
reply: no

# 답: detect_entries_batch_duckdb 추가 — 승인

진행해도 된다. 앞서 포팅한 2건(1:1 동치검증, 3.1~3.3배)과 같은 패턴이면 판단 로직
위험 없다고 본다. 조건만 확인해달라:
- 기존 `detect_entries(candles, ...)`는 그대로 유지, 새 함수만 추가(계획대로)
- 동치검증 유닛테스트 필수 포함(계획대로) — day별 롤링 경계(거래일 넘어 안 섞이는지)
  케이스가 특히 중요하다, `detect_entries` 자체가 `candles.groupby(index.normalize())`로
  일자별로 나눠 계산해서 그 리셋 로직이 SQL PARTITION에도 똑같이 들어가야 한다
- detect_final_entries 실연결은 지금 안 함(계획대로)

드래프트를 편지로 보내라고 할 필요는 없다 — 직접 넣고 완료되면 report로 알려달라,
그때 diff/테스트만 확인하겠다. 질문 있으면 다시 편지해도 된다.
