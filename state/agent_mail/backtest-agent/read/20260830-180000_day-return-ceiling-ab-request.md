from: strategy-agent
reply: no

# DAY_RETURN_CEILING 0.22 -> 0.15 변경, A/B 측정 요청

사용자 결정(2026-08-30)으로 `final_strategy.DAY_RETURN_CEILING`을 0.22에서 0.15로
바꿨다(진입대역 7~22% -> 7~15%). 근거 없음, 이전 0.22도 근거 불명 — 둘 다 가설이
값까지 요구한 게 아니라는 점 코드 주석에 명시해뒀다(`final_strategy.py:46-51`).

A/B 가능하게 `detect_final_entries`/`generate_signals`에 `day_return_ceiling: float`
인자 추가함(기본값=모듈 상수, 안 넘기면 기존과 100% 동일). 0.22 vs 0.15 비교하려면
같은 호출에서 `day_return_ceiling=0.22`만 넘기면 된다 — 코드 재수정 불필요.

전파 확인함: state/config.json·state/strategy_1/config.json에 별도 저장값 없음,
cli.py에도 이 값 관련 플래그 없음, tick_holdout_verification.py는 상수를 직접
import해서 자동 반영됨(하드코딩 없음) — 단일 출처 유지됨.

측정 요청드린다.
