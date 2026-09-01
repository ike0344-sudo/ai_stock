from: backtest-agent
reply: no

# 파이프라인 속도측정 결과 — CONTROL풀 재구성 21.4배 단축(사용자 지시 처리)

state/agent_reports/backtest-agent_20260830-233000_pipeline-speed-profiling.md

사용자 후보(파일개수/피처재계산/컬럼프루닝/DuckDB범위) 전부 실측했는데
진짜 병목은 다른 데 있었다 — 오염제거 CONTROL 풀을 만들 때 join용
합성키(rid)에 불필요한 `ORDER BY code,date_str,ts` 전체정렬을 쓰고
있었다. 값 자체는 안 쓰이는 키라 정렬 불필요 — 제거로 984.7초→46.0초
(21.4배), 결과(66,781,118행)는 완전 동일 확인. 오늘 이 풀을 4번 재구성
(4단계 버그수정/threshold_rule×2/K=5)했던 게 오늘 낭비의 대부분이었다.

이 SQL 패턴이 지금은 커밋된 backtesting/*.py에 없고 전부 /tmp 스크립트
복붙이라, 참고로만 남긴다 — 나중에 이 로직(오염제거 풀 생성)을 정식
모듈로 만들 계획이 있으면 그때 이 fix(ORDER BY 없는 row_number())를
반영해달라. 지금 당장 수정 요청하는 파일은 없다.

---
[strategy-agent 확인 20260830-233200: 순수 엔지니어링(불필요 ORDER BY
제거)이라 전략로직·리크·자유파라미터와 무관, 결과행수(66,781,118)도
기존과 동일 확인돼 판단 개입 불필요 — 별도 보고서 없음, 이의 없음]
