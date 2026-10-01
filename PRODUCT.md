# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
운영자 1인(개인 트레이더). 장중에는 옆 모니터에 상시 띄워 두고 흘끗 보고, 장 전후에는 앉아서 꼼꼼히 점검하며, 밖에서는 휴대폰으로 상태를 확인한다.

## Product Purpose
키움 REST 기반 자동매매(trading-dashboard, 포트 8765)의 실거래 상태판. 매매 켜짐/꺼짐·당일손익·슬롯·국면, 보유종목·포지션, 진입 신호와 체결/주문 이력, 시장 순위(거래대금·애프터장·RS 상위 2%·52주 신고가)를 한곳에서 보여준다. 성공 = 방금 무슨 신호가 나고 무엇이 체결됐는지를 가장 먼저 알아채는 것.

## Positioning
범용 HTS가 아니라 이 운영자의 전략(신고가추세매매 등)이 실제로 무엇을 하고 있는지 보여주는 전용 관제판. 신호→주문→체결 흐름과 전략 규칙·실행 조건이 같은 화면에 있다.

## Operating Context
- 메인 `/` (index.html + app.js + style.css), 하위 `/afterhours.html`, `/ranking.html`, `/rs.html`, `/newhigh.html` (market.css). 서버는 `backtesting/dashboard_server.py`.
- 다우 페이지(dow_mobile, dow_interactive)는 이번 범위 밖.
- 소피증권(kospi-theme-engine, 8770)과는 별개 제품.

## Capabilities and Constraints
- app.js 가 쓰는 요소 ID·버튼 동작(일괄 매도, 전략 선택, 손익 일/주/월 전환 등)은 그대로 유지.
- 등락 색은 한국식: 빨강=상승, 파랑=하락.
- 정보는 접지 않는다: 요약칩·접기 금지, 공간 부족은 배치로 해결.
- 데스크톱 상시 모니터와 휴대폰 폭 모두 지원.

## Product Principles
1. 신호·체결 흐름이 첫눈에 — 방금 일어난 일이 가장 먼저 보인다.
2. 전부 보이게, 배치로 정리 — 숨기지 않는다.
3. 흘끗 봐도 읽힌다 — 상태와 숫자는 판정(좋다/나쁘다)과 함께.
4. 실거래 조작(매도)은 실수하기 어렵게.

## Brand Commitments
- 시각 방향은 업계 표준(HTS 계열 밀집 격자)을 정석대로 — 2026-09-29 사용자가 콘셉트 추첨 대신 직접 선택. 완성도 기준은 트레이딩뷰·블룸버그 터미널.
