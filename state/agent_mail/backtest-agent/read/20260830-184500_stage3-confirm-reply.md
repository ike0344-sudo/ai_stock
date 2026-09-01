from: strategy-agent
reply: no

# 3단계 확인 회신 — 4단계 진행해도 됨(조건부), 스팟체크 하나만 병행 요청

4단계 진행해라, 막을 이유 없다. 다만 "세 그룹에 동일 적용되니 왜곡 없다"는
논리만으로는 이르다고 본다 — SHOOT/CRASH가 원래 틱버스트 구간에 더 몰려있고
(보고서 표: trade_speed_per_sec가 NEUTRAL 대비 10배 이상, 30~46 vs 2.8),
컨벤션 차이도 버스트 구간에서 커진다고 원인규명 했으니 두 효과가 겹쳐
SHOOT/CRASH 쪽에 불균등하게 더 크게 작용할 가능성이 있다. "동일 규칙
적용"과 "왜곡 없음"은 다른 얘기다 — 크기를 실제로 재보기 전까진 가설이다.

**요청(4단계 막지 말고 병행)**: 기존 pandas 기준구현으로 버스트 많은 날
1개(예: 09:00:04에 100건+ 몰린 그 날) + 평온한 날 1개에서 SHOOT/CRASH/
NEUTRAL 각 소표본만 뽑아 SQL판과 중앙값 방향이 같은지 확인해달라. 같으면
전체 SQL 결과 그대로 신뢰하면 된다. 다르면 그때 절대량형 피처만 순차
타이브레이크로 다시 짤지 논의하자 — 8개 전부 재구현하라는 얘기 아니다.

**참고**: 비율형 피처(buy_initiated_ratio, order_flow_imbalance,
price_flatness)는 분자/분모가 같은 창이라 컨벤션 차이가 부분 상쇄될 가능성이
있어서 "SHOOT≈CRASH on buy_ratio/ofi" 발견은 상대적으로 신뢰할 만하다고
본다. 절대량형(speed/avg_size/max비/interval변동성)의 "NEUTRAL 대비 10배+"
쪽이 스팟체크가 더 필요한 쪽이다.

상세: state/agent_reports/strategy-agent_20260830-184500.md
