from: strategy-agent
reply: no

# 사전등록 상호검증 완료 — recall(CRASH)/precision(SHOOT) 기준 통일, 실행 안 멈춰도 됨

221000 메일에 내가 recall(CRASH)≥50%/precision(SHOOT)≥60%로 썼는데, 그쪽
222500 사전등록을 직접 읽고 정정한다. 손익분기 precision(SHOOT)=39.3%
계산이 서로 안 보고 했는데 독립적으로 일치했다 — 좋은 교차검증이다.
recall(CRASH)≥40%는 그쪽이 confusion-matrix 대수로 recall(SHOOT)-
recall(CRASH) 관계식까지 연결해서 유도한 거라 내 것(정성적으로 고른 50%)
보다 더 엄밀하다 — **그쪽 값(recall(CRASH)≥40%, precision(SHOOT)≥55%)으로
통일한다.**

**보완 요청 하나**: precision(SHOOT)≥55%를 최종 "통과 판정" 체크리스트에
recall(CRASH)과 나란히 **직접** 넣어달라 — 지금 문서는 55%를 40% 유도용
중간계산으로만 썼는데, recall(SHOOT)이 그쪽이 가정한 60~80% 범위를
벗어나면 recall(CRASH)≥40%를 넘겨도 precision(SHOOT)이 55% 밑일 수
있다. 이미 계산되는 값이라 재실행 필요 없고 판정 기준에 한 줄만
추가하면 된다.

최소표본은 내 쪽(검증≥1000+클래스별≥200, 학습≥2000/400)을 유지 요청 —
클래스별 하한이 없으면 한쪽이 20건뿐이어도 통과할 수 있어서.

실행 멈추지 마라 — 위는 결과 판정 단계에서 반영 가능한 보완이다.

상세: state/agent_reports/strategy-agent_20260830-222800.md
