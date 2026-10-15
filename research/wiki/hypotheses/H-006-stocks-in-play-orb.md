---
id: H-006
status: 기각
created: 2026-09-27
source: [Zarattini·Barbon·Aziz 2024 ORB Stocks in Play](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284) · [RVOL at Time 정의(트레이딩뷰)](https://www.tradingview.com/script/fCgl6lLO-Intraday-RVOL-Overlay-Time-of-Day-Relative-Volume/) · [TORB 정의](https://www.tradingview.com/script/78AVOLmR-Timely-Opening-Range-Breakout-Strategy-TORB-Zeiierman/) · [변동성 돌파 정의](https://penglab.net/strategies/volatility-breakout)
---
# 오늘 재료 있는 종목(Stocks in Play)의 고정 오프닝 레인지 돌파

## 메커니즘
재료(공시·뉴스)가 있는 날은 평소보다 같은 시각 거래가 몰리고, 정보가 가격에 반영되는 과정이 장 초반에 시작해 하루 종일 이어진다(논문의 주장). 평소 방식대로 유동성을 공급하거나 역추세로 받는 참여자는 그날이 특별한 날인지 모르고 반대편에 선다. "같은 시각 과거 평균 대비 거래"로 그날을 골라내는 것이 핵심이고, 돌파는 방향 확인일 뿐이다.

## 진입 조건 (정의)
- RVOL5 = 오늘 09:00~09:05 체결대금 ÷ 직전 14거래일 같은 5분 대금 평균(오늘 제외). 선별: RVOL5 ≥ 1(논문은 상위 20종목).
- OR = 09:00:00~09:05:00 고가 H5·시가 O·09:05 가격 C5. C5 > O 이고 09:05 이후 체결가 > H5 인 첫 초 → 다음 체결 진입. 하루 1회.
- 변형 a: OR 길이 15·30분(논문: 5분보다 약함, 참고).
- 변형 b(TORB): 돌파 순간 1분 대금 ≥ 1.5 × 직전 N=10일 같은 분 평균.
- 변형 c: RVOL 을 **기존 breakout_min 신호의 필터**로만 사용(누적 09:00~s 대금 ÷ 과거 같은 시각 누적 평균 ≥ 2).
- 변형 d(변동성 돌파): 기준선을 H5 대신 시가 + 0.5×(전일 고가−전일 저가).
- 부분 이미 있음: breakout_min(움직이는 창), value_speed(오늘 안 누적평균 대비). "고정 창"·"같은 시각 과거 평균"은 없음. 연구 스크립트 `backtesting/qtai_orb_rvol_*.py` 존재.

## 청산 아이디어
손절 = 진입가 − 0.10×ATR14(일봉), 청산 = 15:19(당일). 변형: OR 저가 이탈.

## 필요한 데이터
틱(돌파 초) — 174종목, 1분봉(통합, RVOL 14~20일) — 있음, 일봉 ATR — 있음. 틱 36거래일이라 RVOL 은 분봉으로 계산해야 함.

## 비용 점검
보유가 당일 종가까지라 거래당 움직임이 크다. 참고(논문): 미국 상위 20종목 포트폴리오 샤프 2.81. 재료 종목의 장중 폭은 대개 1% 를 넘는다 [추론] → 1.06% 통과 가능성 있음. 단 논문은 미국 비용(세금 없음) 기준.
참고 반대 증거: 필터 없는 ORB(나스닥 선물 18년)는 비용 뒤 손실(PF 0.87) — 필터가 핵심이라는 뜻.
참고(09-27 병합): 원조 5분 ORB 논문 [Zarattini·Aziz 2023, SSRN 4416622](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4416622) 의 QQQ 독립 재현은 "비용 넣으면 주당 약 2.2센트 슬리피지에서 손익분기"([github 재현](https://github.com/giovannibrusco/zarattini-2023-orb-qqq)) — 지수판은 비용에 매우 민감.
첫 5분 손절폭(시가~OR 저가)이 1.06% 보다 좁은 날은 비용이 손절폭의 절반 넘게 먹으므로 손절폭 하한을 같이 재야 함 [추론].

## 반증 조건
- RVOL 상위 그룹과 하위 그룹의 ORB 거래당 순수익 차이가 없으면 "Stocks in Play" 메커니즘 기각.
- RVOL 상위 그룹의 거래당 평균(비용 전)이 +1.06% 미만이면 비용 미달로 기각.
- 변형 c: RVOL 필터를 붙인 breakout_min 이 안 붙인 것보다 거래당 성과가 낫지 않으면 기각.

## 실험 결과 (2026-09-27, backtest-agent — 판정은 사람·실험 쪽 몫, 여기는 요약만)
- 519종목×303일, OOS 상위 50: 비용 전 −0.12%, 비용 후 −0.63% — 비용 빼기 전에도 손실.
- 상위−하위 RVOL 차 OOS +0.07%p, 95% [−0.07, +0.21] 0 포함 → 반증 ① 걸림(IS·검증의 작은 효과가 OOS 에서 사라짐).
- 갭 구간 어디서도 비용 후 양수 없음 → **기각**. 보고서: [state/agent_reports/backtest-agent_20260927-1120_H006_orb_stocks_in_play.md](../../../state/agent_reports/backtest-agent_20260927-1120_H006_orb_stocks_in_play.md)

## 관련 가설
[[H-007]] [[H-012]]
