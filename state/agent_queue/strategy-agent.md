# strategy-agent 큐

- [>] new_high_leg_exit A/B 결과 오면 청산가설 A 검증 결과 해석
- [>] 청산가설 B(추격매수 소진, 거래량 다이버전스) 구현 여부 판단 — A 결과 보고
- [x] pullback_reentry 처리 확정 (재가설 / 조건 수정 / 폐기) — 이미 완료:
      가설 기각으로 폐기, `pullback_reentry.py` 자체 docstring에 [폐기됨]
      명시 + `strategies/__init__.py` __all__에서 제외(파일은 안 지움).
      순서 무시하고 먼저 체크함(이 큐 존재를 오늘 처음 인지, 이미 끝난
      항목이라 확인 즉시 표시) — 상세는 아래 §1~2 미해결분과 별개임.
- [x] kospi-theme-engine app/engine/ 테마 점수 로직 파악 — 가중치는 바꾸지 말 것
      완료(읽기전용, 가중치 미변경) — state/agent_reports/strategy-agent_20260831-171500_kospi-theme-score-review.md
- [x] 가설 3개 제안 (상시임무 신설분) — lead 지시로 주제를 "장시작60분 테마순위"로 지정,
      highs축 제외 3축(H1 변화vs레벨/H2 chgtop고정성/H3 leader-vs-top_gainer, H3는 원본에
      2등주 데이터 없어 재정의)으로 사전등록 완료 —
      state/agent_reports/strategy-agent_20260831-2240_theme_rank_prereg.md.
      backtest-agent 측정 의뢰(2245) → 오염 발견으로 보류(2312) → lead 판단(옵션2,
      오염7일 제외) 반영해 재개(2355) → **측정결과(잠정) 수령·검증 완료: H1 기각,
      H2 기각, H3 판단보류 — 3개 다 미채택**
      (state/agent_reports/strategy-agent_20260901-0010_theme_rank_result_verified_all_rejected.md).
      standing.md 규율대로 새 가설 스스로 안 만듦 — STATUS.md에 "방향 재설정 필요"로
      lead 판단 요청 올림. **41일 균일본 최종 재측정 결과 수령·검증·사전등록 갱신
      완료: H1/H2 기각 유지(크기만 변화), H3는 표본충족(19→25)돼 판단보류→기각으로
      확정 — 3축 다 최종 기각.** 사전등록 문서(2240)에 최종 확정 배너 추가.
- [x] [lead 방향재설정, 2026-09-01] 일봉 3축 사전등록 — H1 눌림후반등/H2 CLV(순매도우세
      데이터제약 재정의)/H3 갭vs장중전용, IS 2019~2024/OOS 2025~2026-08, 리밸런스5거래일
      비중첩 — state/agent_reports/strategy-agent_20260901-0040_daily_bar_prereg.md.
      backtest-agent 측정 의뢰 발송 완료(0045). **결과: H1/H2/H3 전부 기각**(핵심발견:
      H1 총수익 전부 갭에서 나옴, 장중전용은 t=-3.94로 유의하게 마이너스 — 틱 라운드와
      교차검증) — 독립검증(산출물 행수·표본수 대조) 완료, 결론 수용.
- [x] [lead, 2026-09-01 01:00] **3라운드 보류 — 사용자 판단 대기.** 두 라운드(틱/일봉)
      연속 전부 기각, "갭이 전부다"가 두 번 독립 확인됨. 새 가설 스스로 안 만듦, 지시대로
      유휴 전환. 사용자가 방향 정하면 재개.

- [x] (lead 지시, **사용자 승인 2026-09-25 "다른 에이전트로 같이 시작해"**) **백테스트 스튜디오 module-3 (조건식 쪽) — 명세·조건 조립기·지표·기존 전략 연결·프리셋**

      **먼저 편지함 정리**: `state/agent_mail/strategy-agent/` 의 2026-08-31~09-01 편지 7통은 주제 순위 측정 조율 건으로
      이후 9/10~9/24 연구로 대체됐다(lead 판단: 오래된 것). 훑어보고 지금도 할 일이 있으면 보고만 하고, 전부 `read/` 로 옮겨라.

      설계서: `docs/02-design/features/backtest-studio.design.md` — **§3.2 명세·조건식 문법, §3.7 지표 카탈로그·시점 규칙,
      §5.4 백테스트 화면 체크리스트(조립기가 표현해야 할 것), §8.7 P6, §8.8 C2, §9.3 import 규칙**을 먼저 읽어라.
      Plan: `docs/01-plan/features/backtest-studio.plan.md` (v0.4). B안(새로 짓기) — 사용자 선택.

      **왜**: 백테스트 GUI 의 "조건 조립기"(지표 × 비교 × AND/OR, 숫자 칸은 최적화 변수 가능)를 받치는 명세와 평가기를 짓는다.
      조립기로 만든 "SMA5 상향돌파 SMA20" 이 기존 `MovingAverageCrossover` 와 **신호가 한 칸도 안 틀려야** 기존 연구와 비교된다.

      **분담 (파일이 안 겹치게 나눴다)**
      - **너(strategy-agent)**: `studio/domain/spec.py`(§3.2 Spec 전체 pydantic) · `studio/domain/conditions/`{`ast.py`,`catalog.py`,
        `indicators.py`,`evaluator.py`} · `studio/domain/narration.py`(명세 → 한국어 문장) · `studio/infrastructure/legacy_strategies.py` ·
        `presets/studio/*.json` · 네 몫 테스트
      - **backtest-agent**: `studio/__init__.py` · `studio/domain/__init__.py` · `models.py` · 엔진 · 비용 · 지표 계산 —
        **이 파일들은 만들지도 고치지도 마라.** `Panel` 은 backtest-agent 가 만든다: 평가기는 속성
        `open/high/low/close/volume/value/prev_close`(넓은 표: index=날짜, columns=종목코드)만 쓰는 덕 타이핑으로 짜고,
        테스트에선 `types.SimpleNamespace` 대역을 써라. 평가기 출력 = 진입·청산 bool 표(같은 모양).

      **할 일**
      1. `conditions/ast.py` — Operand(field/ind/market/const) · Condition(op 6종) · Group(all/any, 깊이 ≤ 2),
         숫자 칸은 `number | {"param": 이름}`, 파라미터 범위 검증(예: n 1~500), 없는 지표 이름은 경로 포함 오류
      2. `conditions/catalog.py` — §3.7 표(이름·파라미터·한국어 설명·쓸 수 있는 모드·시점 규칙). 분봉 전용
         (`day_change_pct`·`time`·`cum_value`·`vwap`)과 틱 카탈로그는 **목록에만** 올리고 계산은 module-6 몫으로 표시
      3. `conditions/indicators.py` — 넓은 표 벡터 연산: sma·ema·**rsi(기존 `backtesting.indicators.compute_rsi` 와 같은
         단순평균 방식, 손실 0 → 100)**·rsi_wilder·highest/lowest(기본 **봉 t 제외**)·change_pct·gap_pct·atr·bb_upper/lower·
         vol_ratio(평균 t 제외)·value_rank(그날 거래대금 순위)
      4. `conditions/evaluator.py` — Group → bool 표, `cross_above(a,b)= a_t>b_t AND a_{t-1}<=b_{t-1}`(NaN 비교 False),
         offset·mul, param 치환, market 피연산자(지수 `data/index/daily/001.csv`·`101.csv`, 값 ×100 스케일 주의)
         + 호환 모드용 Signal 조립(기본 HOLD, 진입 → BUY, 청산 → SELL, 둘 다면 SELL — 기존 전략 대입 순서와 같게)
      5. `spec.py` — §3.2 Spec 전체(mode·period·universe·strategy(builder|legacy)·market_filter·exits·portfolio·costs·fills·
         intraday·tick·compat·params·validation), 모드별 의미 검사(예: compat 은 daily_single 만)
      6. `narration.py` — 명세 → 문장("종가가 20일 최고가를 넘고 거래량이 20일 평균의 1.5배 이상이면 다음 날 시가에 산다")
      7. `legacy_strategies.py` — 기존 전략 8종(ma_crossover · rsi · envelope(exit_mode: ma_touch/opposite_band) ·
         new_high_swing · pullback_reentry · vcp_breakout · new_high_leg_exit · new_high_volume_divergence_exit) 레지스트리 +
         파라미터 명세(이름·형·기본값·범위 — 기본값은 cli.py 격자/클래스 상수에서 확인) + evaluate 어댑터. ml_strategy 제외
      8. `presets/studio/*.json` 6종(new_high_20 · golden_cross_5_20 · rsi_rebound · pullback_ma20 · gap_up_value_top(분봉) ·
         tick_breakout_5m(틱)) — 전부 Spec 검증 통과
      9. 테스트: ast 오류 경로 · 지표 정확도(rsi 는 compute_rsi 와 동일) · cross 정의 · **P6**(조립기 SMA5/20 교차 → Signal 이
         `MovingAverageCrossover.evaluate` 와 실제 20종목에서 동일, `@pytest.mark.parity`) · **C2**(t 이후 거래량 변조 → t 이하
         value_rank 불변) · 평가기 카나리아(t 이후 변조 → t 이하 신호 불변) · import 규칙(§9.3)

      **읽기 전용 참고**: `backtesting/strategies/*`, `backtesting/indicators.py`, `backtesting/cli.py`(파라미터 격자),
      `data/stock_names.json`·`data/sectors.csv`. **기존 `backtesting/*.py` 는 수정하지 마라.** data-agent 가 `datahub/`·수집기를,
      backtest-agent 가 엔진을 동시에 고치는 중이다 — 그 파일들은 건드리지 마라.

      **"그대로 믿지 말고 검증해라. 설계의 지표 정의가 기존 전략과 다르거나 틀렸으면 틀렸다고 해라."**
      git commit 금지. 보고: 시작·50%·끝에 STATUS.md 자기 행, 자세한 건 `state/agent_reports/strategy-agent_<날짜시각>_studio_conditions.md`.

      **[2026-09-25 진행]** 8개 할 일 코드·프리셋·테스트 작성 완료. 1차 154 passed(lead 실행). lead 답신(1415) 반영(빈칸 경로·validate_against·infrastructure/__init__) 작성 완료 — **수정분 pytest 대기**, 결과 받기 전엔 `[x]` 안 함.
      상세: `state/agent_reports/strategy-agent_20260925-1200_studio_conditions.md`

- [x] (lead 지시 2026-09-25 22:50, **module-6 조건식 — 사용자 승인 "module-2 끝나면 4~6 바로"**) **분봉 지표 + 틱 조건 카탈로그 + P5 패리티**
      설계서 §3.7(지표 표의 분봉·틱 줄, "지표 계산 규칙", "시점 규칙"), §3.2 `tick.catalog` 칸, §8.7 P5, §8.8 C3·C4 를 먼저 읽어라.
      1. 분봉 지표(`studio/domain/conditions/` 카탈로그·계산): `day_change_pct`(전일 종가 D−1 대비) · `time`(봉 끝 시각 HHMM) · `cum_value`(당일 누적 거래대금, t 까지) · `vwap`(당일, t 까지) · `gap_pct`(분봉에서도).
         당일 누적 지표는 **날이 바뀌면 0부터**. 분봉 모드에서 일봉 피연산자는 **D−1 값**(당일 일봉은 장중에 모르는 값)
      2. 틱 조건(새 파일 가능, 예 `conditions/tick.py`): `breakout_min`(구간 `[s−w, s)` 고점 돌파, s 자신 제외) · `value_speed(w, ratio)`(인과적 누적 평균 대비) · `buy_ratio(w, min)`(틱룰 매수 비중) ·
         `time_from/to`. 신호는 초 s 까지의 체결만 보고, **진입은 s 보다 엄격히 뒤 체결**(엔진이 하지만 조건 쪽 반환값에 s 를 분명히)
      3. **P5**: 틱 돌파 결과 = `backtesting/precursor_master.detect_breakouts(px, window_min, cooldown)` — 실제 체결 파일 20개로 동일. 쿨다운을 조건 쪽에서 할지 엔진 쪽에서 할지 정하고 근거를 적어라
      4. 카나리아: C3(분봉 k 이후 + 당일 일봉 변조 → k 이하 신호 불변) · C4(틱 s 이후 변조 → s 이하 신호 불변)
      5. 입력 모양은 data-agent 가 로더를 만들고 편지로 알린다(열 이름·정렬). 그 전엔 합성 프레임으로 짜고, 편지가 오면 맞춰라. 엔진(backtest-agent)이 부를 함수 서명을 끝날 때 **backtest-agent 에 편지**로.
      **너는 Bash 가 없다 — 테스트는 lead 가 돌려 결과를 편지로 준다.** 테스트 파일을 다 쓰면 STATUS.md 에 "테스트 준비됨: <경로>" 로 알려라.
      계층 규칙(§9.3: domain 은 os·io·backtesting·datahub import 금지 — P5 테스트만 tests/ 에서 precursor_master 를 import). 그대로 믿지 말고 검증해라 — 설계서 정의가 기존 함수와 다르면 다르다고 써라.
      git commit 금지. 보고: STATUS.md + `state/agent_reports/strategy-agent_<날짜시각>_module6_conditions.md`.

      **[2026-09-25 진행]** 1~4 코드·테스트 작성 완료(pytest 실행 0회 — lead 실행 대기), 5 backtest-agent 편지 발송(`agent_mail/backtest-agent/20260925-2359_module6_조건식_함수서명.md`). data-agent 로더 편지는 미수신 — 오면 입력 모양 맞춤. lead 실행 결과 받기 전엔 `[x]` 안 함.
      상세: `state/agent_reports/strategy-agent_20260926-0000_module6_conditions.md`

- [x] (lead 지시 2026-09-26 00:15 — **사용자 결정 "통합 기본 + KRX 선택"**) **Spec 에 분봉 출처 칸 + validate_against 출처별 키**
      네 추천 (a) 채택. `intraday.source: "al" | "krx"`, **기본 `"al"`**(9월 1일 규칙 "통합만"이 기본). KRX 는 사용자가 화면에서 고를 때만.
      1. `studio/domain/spec.py`: 필드 추가(기본 al), `validate_against` 가 출처별 데이터셋 키(`minute_al` / `minute_krx`)와 메시지("통합 분봉" / "KRX 분봉")를 쓰게
      2. 풀이 문장: `krx` 면 "KRX 분봉 기준 — NXT 체결이 빠져 거래량·거래대금이 통합보다 20~40% 작다" 한 줄
      3. 프리셋은 `al` 그대로(바꾸지 마라). 테스트: 기본값 al · krx 선택 시 키·메시지 · 옛 명세(칸 없음) 로드 = al
      끝나면 STATUS 에 "테스트 준비됨: <경로>" — lead 가 돌리고, 결과가 통과면 backtest-agent 가 서비스에 연결한다. git commit 금지.

- [x] (lead 지시 2026-09-26 10:00, **studio-conditions c3 — 사용자 승인 "C안, 5명 병렬"**) **지표 카탈로그 — 가격·이평·신고가 / 보조지표 / 캔들**
      설계 §3.3 의 `ind_trend.py`·`ind_oscillator.py`·`ind_candle.py` 표 전부(기존 ✔ 는 그대로 두고 새 것만). 지표마다: 정의 식·파라미터 범위·시점·지원 모드·live 여부(IndicatorDef 새 칸 — backtest-agent 편지 기다리되, 계산 함수는 먼저 써도 된다).
      일목 선행스팬은 "t 에서 보이는 구름 = t−26 에 계산된 값"(미래참조 금지), 상한가는 호가 반올림. 테스트: 지표마다 손계산 기대값 + live 지원 지표는 "가상 봉 재계산 = 점화식 값" 대조.
      너는 Bash 가 없다 — 테스트 파일을 다 쓰면 STATUS 에 "테스트 준비됨: <경로>" (lead 가 돌린다). 분류 하나 끝날 때마다 알려도 된다(한꺼번에 몰지 말 것).
      공통: 설계서 `docs/02-design/features/studio-conditions.design.md` 를 먼저 읽어라(§3 전부·§8·§11.3). **미래참조 없음이 최우선** — 새 조건마다 카나리아. 기존 명세·프리셋·실행 결과·패리티(P1~P8) 무회귀.
      파일 규칙: 새 지표는 **자기 분류 모듈**(`ind_*.py`)에 정의 + `catalog.py`·`indicators.py` 에는 등록 한 줄만(고치기 직전 다시 읽고 Edit, 전체 덮어쓰기 금지). `ast.py`·`evaluator.py`·엔진은 backtest-agent 만.
      분봉 기본 출처 통합(AL), 실주문·KIWOOM_IS_MOCK 무접촉, git commit 금지. 그대로 믿지 말고 검증 — 설계가 틀렸으면 틀렸다고 써라.
      보고: STATUS + `state/agent_reports/strategy-agent_<날짜시각>_conditions_c3.md`.
      **[2026-09-26 완료]** 63종 구현·테스트 작성(실행은 lead 대기). 상세: `state/agent_reports/strategy-agent_20260926-1130_conditions_c3.md`

- [x] c3 후속 ① `daily_live` 켜기 — backtest-agent c1 편지(1010)로 `timeframe.LiveBars` 서명 확정 → 구현 완료(2026-09-26, 실행은 lead 대기): 각 `ind_*.py` 에 `LIVE` 점화식 함수 46종(가격·이평·신고가 16 / 보조지표 15 / 캔들 15) 등록·`live=True`, 테스트 `tests/studio/conditions/test_ind_live.py`(재계산 대조 + 미래참조 카나리아). 상세: `state/agent_reports/strategy-agent_20260926-1130_conditions_c3.md` "후속" 절.
- [>] c3 후속 ② `rel_strength`(상대강도, 지수 연결) — **선행: backtest-agent c1 의 market/지수 연결.** 편지가 오면 `[ ]` 로 되돌려 시작.
