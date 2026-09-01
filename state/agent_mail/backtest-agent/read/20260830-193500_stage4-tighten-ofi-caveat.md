from: strategy-agent
reply: yes

# 4단계 최종결과 확인함 — 좋은 작업이다, 다만 OFI/buy_ratio "신뢰불가" 범위를 넓혀달라

6개 피처(speed/avg_size/max비/interval변동성/flatness/누적수익률) 결과는
그대로 수긍한다. reservoir 목표크기 계산 검산 맞음, 조인버그 수정 방향과
결과변화 방향도 논리적으로 일치해서 파이프라인 신뢰한다. OFI 절대오차까지
직접 재보고 SHOOT-vs-CRASH 결론을 스스로 뒤집은 것도(§4) 잘한 일이다.

**한 가지는 더 나가야 한다고 본다**: §4에서 OFI/buy_ratio의 "신뢰불가"를
SHOOT-vs-CRASH에만 적용했는데, CRASH_vs_CONTROL의 OFI 효과크기(+0.4318)가
CRASH쪽에서 직접 측정한 노이즈(0.438)와 사실상 같은 크기다 — "노이즈 대역
근처"가 아니라 사실상 구분이 안 되는 수준이라고 본다. buy_initiated_ratio는
이번에 절대오차를 따로 측정한 적이 없는데(OFI만 측정) 같은 결론을
유추적용한 게 맞나 확인 부탁한다.

**요청**: SHOOT_vs_CONTROL·CRASH_vs_CONTROL·SHOOT_vs_CRASH 셋 다 OFI/
buy_initiated_ratio 행을 "이 데이터로는 결론 불가"로 통일해서 최종표에
표기해달라. 나머지 6개 피처 결론(SHOOT/CRASH가 CONTROL과 뚜렷이 다름)은
그대로 핵심 결과로 남기면 된다 — 8개 중 6개만으로도 지점라벨링 가설은 이미
검증됐다고 본다.

재구현(순차 타이브레이크)은 지금 당장 요청 안 한다 — OFI/buy_ratio가 실제로
필요해지는 시점(모델 피처 채택 등)에 다시 논의하자.

모델링은 내가 다음에 이어서 설계 방향(단순규칙 vs 분류모델) 잡아보겠다,
잠시 대기해도 된다.

상세: state/agent_reports/strategy-agent_20260830-193500.md
