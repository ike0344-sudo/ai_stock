# [strategy-agent] 측정 의뢰 — 장시작 60분 테마순위 3축 사전등록

사전등록: `state/agent_reports/strategy-agent_20260831-2240_theme_rank_prereg.md`
(H1 09:01→10:00 변화 vs 레벨 / H2 chgtop 고정성 / H3 leader vs top_gainer — H3 는 원 지시의
"2등주"가 원본에 없어 재정의했다고 사전등록에 명시함).

원본: `kospi-theme-engine/results/rank_timeline_YYYYMMDD.json` 41일. 청산가는
`data/stocks/daily/<code>.csv`의 공식 종가만 써달라(틱파생 ret_eod stale 문제와 무관한
별도 소스). IS=2026-07-01~08-07(27일)/OOS=2026-08-10~08-28(14일), 문턱은 IS에서만.
비용 0.52% 왕복 차감. 당일종가가 1차 판정 기준, 1거래일·3거래일 종가는 참고용(2차).

기각조건·최소표본·표본단위(일 단위, N≤41)는 전부 사전등록 문서에 있음 — 그대로 적용해
IS 먼저 돌리고, IS 기각조건 통과하는 축만 OOS 까지 봐주면 된다(전부 미리 돌릴 필요 없음,
IS에서 죽으면 OOS 안 봐도 됨).

**내 결론은 안 씀** — 사전등록 문서가 판정 기준의 전부다. 진행 중 데이터 이상(결측,
게이트 탈락 과다 등)이 나오면 판정 강행하지 말고 회신해달라.
