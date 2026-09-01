from: strategy-agent
reply: yes

# 가설C(OFI 다이버전스) 구현 완료 — 측정 3건 요청

`backtesting/ofi_divergence_scalp.py` 신규(구현 상세는
state/agent_reports/strategy-agent_20260830-201500.md). 사용자 지시로 백테스트는
그쪽 담당이라 넘긴다. 8월 18거래일 117종목 틱 기준.

## 요청 1 — 보합틱 비율 실측 (우선순위 가장 높음, 가설 생존 여부에 직결)
방향판정을 순수 틱룰(상승틱=매수주도/하락틱=매도주도/보합틱=직전 이월)로
확정했는데, 보합틱 비율이 높으면 이 판정 자체가 신뢰 못 할 노이즈가 된다.
종목별·시간대별(장초반/중반/마감 등) 분포로 봐줄 것 — 특정 구간에 몰리면
그 구간에서의 가설 신뢰도가 특히 낮다는 뜻이 된다.

## 요청 2 — 부수효과 2개 측정
①`compute_ofi_signal` 신호 시점 기준, 신호 이전 더 긴 구간(예 3×W)에서도 뚜렷한
선행 상승이 없었는지(없어야 함 — 있으면 후행지표라 가설 기각).
②신호 후 W~2W초 내 실제 신고가 경신 비율.

## 요청 3 — 구현/청산 확인
`classify_tick_direction`/`compute_ofi_signal` 그대로 쓰고, 청산은
`final_strategy._compute_exit_legs(path, tiers=(0.03,0.05), stop_loss_pct=0.02)`를
tick_holdout_verification.py와 같은 패턴으로(path를 진입시각+W초에서 잘라 넘기면
시간손절 자동 구현, 함수 자체는 안 고쳐도 됨).

## FYI
`build_training_dataset`에 `day_return_ceiling` 인자를 추가했다(오늘 14/14 확인해준
것 이후 변경) — 기존 호출부(인자 안 넘기면)엔 영향 없음, 그냥 참고.

자유파라미터 W/T/F 값은 사전 등록해뒀다(가설 유도 아님, 실측 후에도 안 바꿀 것) —
코드 docstring 참고.
