# studio-conditions Design Document

> **Summary**: 조건식 확장 — 다중 시간 단위(분봉↔일봉)·조건 70여 종·사용자 수식·포지션 청산 조건. 기존 스튜디오 계층(domain/application/infrastructure/api) 그대로
>
> **Project**: ai_stock (백테스트 스튜디오 8780) · **Author**: lead · **Date**: 2026-09-26 · **Status**: Draft v0.1
> **Planning Doc**: [studio-conditions.plan.md](../../01-plan/features/studio-conditions.plan.md) · 상위 설계: [backtest-studio.design.md](backtest-studio.design.md) §3.2·§3.5·§3.7

## Context Anchor

| Key | Value |
|-----|-------|
| **WHY** | 조건이 적어 백테스트로 확인하고 싶은 전략을 못 만든다. 특히 분봉에서 일봉 지표(신고가·이평·RSI)를 못 쓴다 |
| **WHO** | 사용자(신고가 추세·주도주·거래대금 상위·테마 매매) — 8780 화면에서 직접 조립 |
| **RISK** | 새 조건이 미래 데이터를 보는 것 · 조건 수 증가로 느려짐 · 수급·공매도 과거 자료 없음 |
| **SUCCESS** | SC-C1~C7 (계획서 §4.1) |
| **SCOPE** | P1 다중 시간 단위·이평·RSI·청산 조건 → P2 카탈로그·조건 고르기 화면 → P3 사용자 수식 (수급·공매도 제외) |

---

## 1. Overview

### 1.1 Design Goals
1. 조건 하나하나에 **시간 단위**를 붙인다 — 분봉 실행에서 분봉·다른 분봉·일봉(전일 확정/장중 실시간) 값을 섞어 쓴다.
2. **카탈로그가 유일한 출처** — 조건 정의·파라미터·시점·지원 모드·실시간 지원 여부가 카탈로그 한 곳에 있고, 평가기·검증·풀이 문장·화면 설명이 전부 거기서 나온다.
3. **사용자 수식은 같은 AST 로** 컴파일한다 — 평가기·카나리아·패리티를 그대로 재사용.
4. 청산 조건에서 **포지션 값**(매수가 대비 수익률 등)을 쓴다.

### 1.2 Design Principles
- **미래참조 없음이 최우선**: 모든 새 조건·시간 단위는 카나리아를 통과해야 머지한다.
- 기존 명세·프리셋·실행 결과는 그대로 읽히고 같은 결과(`tf` 없으면 `bar`, 새 칸 전부 기본값이 옛 동작).
- 지표는 널리 쓰는 정의(키움 HTS 와 같은 식)로, 기존 함수가 있으면 비트 단위로 맞춘다.
- 계산 중복 없음 — 지표 memo 키에 시간 단위를 넣는다.

---

## 2. Architecture Options

### 2.0 Architecture Comparison

| Criteria | A: 최소 변경 | B: 전면 재구성 | **C: 실용 균형** |
|----------|:-:|:-:|:-:|
| 방식 | 기존 `indicators.py`·`catalog.py` 에 지표를 계속 덧붙임, `tf` 는 평가기 안 분기 | 조건 패키지를 레지스트리+분류 모듈+시간 단위 해석기+수식 컴파일러로 다시 짬, 기존 지표도 옮김 | **새 것만 새 모듈**(`timeframe.py`·`formula.py`·`position.py`·분류별 `ind_*.py`)로, 기존 파일은 등록·연결 몇 줄만 |
| 기존 코드 위험 | 낮음 | **높음**(통과 중인 600여 테스트·패리티 흔듦) | 낮음 |
| 파일 크기 | 한 파일이 수천 줄 | 깔끔 | 분류별로 나뉨 |
| 에이전트 병렬 | 한 파일 동시 편집 충돌 | 재구성 끝날 때까지 병렬 불가 | **분류 모듈별로 병렬 가능** |
| 권장 | | | **✔** |

**Selected**: C (사용자 확인 대기) — 이유: 병렬로 여러 에이전트가 파일 충돌 없이 나눠 만들 수 있고, 검증된 기존 지표·패리티를 건드리지 않는다.

### 2.1 Component Diagram

```
Spec(조건 AST) ──┬─ Operand(tf) ──► timeframe.resolve(tf) ──► 시간 단위별 패널(bar / mN / daily_prev / daily_live)
                 │                                             │
                 │                          catalog(분류·정의·지원) ─► ind_*.compute() ─► memo[(tf,name,params)]
                 ├─ formula(text) ──► formula.compile() ──► 같은 AST
                 └─ exit Group + pos 피연산자 ──► engine 이 보유 종목별로 평가(position.py)
```

### 2.2 Data Flow
명세 → 검증(카탈로그·시간 단위·모드·실시간 지원) → 시간 단위별 패널 준비(필요한 것만) → 지표 계산(memo) → 조건 평가(bool 표) → 엔진(진입 신호 / 청산: 신호 + 포지션 조건 + 청산 규칙) → 결과.

### 2.3 Dependencies
추가 라이브러리 없음(numpy·pandas 만). 수식 해석기는 직접 작성(재귀 하강, eval 금지).

---

## 3. Data Model

### 3.1 AST 확장 (`studio/domain/conditions/ast.py`)

```jsonc
Operand = {"kind":"field", "name":"close", "offset":0, "mul":1, "tf":"bar"}          // tf 추가(기본 "bar")
        | {"kind":"ind", "name":"sma", "params":{"src":"close","n":20}, "offset":0, "mul":1, "tf":"daily_live"}
        | {"kind":"market", ...}                                                        // 기존 + ind 이름 확대(§3.3 시장)
        | {"kind":"const", "value":30}
        | {"kind":"expr", "op":"+|-|*|/", "left":Operand, "right":Operand}             // 신규: 산술(수식용, 깊이 ≤ 8)
        | {"kind":"pos", "name":"return_pct|bars_held|minutes_held|max_return_pct|drawdown_pct|entry_price"}  // 신규: 청산 조건 전용
Condition = {"left", "op", "right", "hold": 1}                                          // hold 추가: 연속 k봉 만족(기본 1)
op ∈ gt gte lt lte cross_above cross_below + cross_above_within(k) cross_below_within(k) + is_true is_false(1/0 지표용)
Group = {"logic":"all|any", "items":[...], "negate": false}                             // negate 추가(수식 NOT)
tf ∈ "bar" | "m1" "m3" "m5" "m10" "m15" "m30" "m60" | "daily_prev" | "daily_live"
```

- 일봉 모드: `tf` 는 `bar` 만(다른 값은 검증 오류). 분봉 모드: `mN` 은 실행 봉 길이의 **배수이면서 더 긴 것**만.
- `pos` 는 **청산 조건 그룹에서만** 허용(진입에 쓰면 검증 오류 — 보유 전엔 값이 없다).
- 기존 명세(칸 없음) = `tf:"bar"`, `hold:1`, `negate:false` — 옛 결과와 동일.

### 3.2 시간 단위 규칙 (`studio/domain/conditions/timeframe.py`) — 미래참조 차단의 핵심

| tf | 값의 뜻 (실행 봉 끝 시각 t, 날짜 D) | 정렬 규칙 | 카나리아 |
|----|------|------|------|
| `bar` | 실행 봉 그대로 | — | 기존 C1·C3 |
| `mN` | N분봉으로 다시 묶은 뒤(P8 리샘플 규칙) 그 위에서 지표 계산 | **끝 시각 ≤ t 인 마지막 N분봉 값**(마감된 봉만). 롤링은 날을 넘어 이어짐(§3.7 결정과 같음) | **C5**: t 이후 분봉 변조 → t 이하 값 불변, 그리고 t 에 걸친 미마감 N분봉 값이 안 쓰임 |
| `daily_prev` | **오늘(D) 장 시작 전에 알 수 있는 값** — 지표의 행 D 값이 봉 D 자료에 의존하지 않으면(현재 봉을 빼는 highest/lowest 등, 카탈로그 `excludes_current`) **행 D**, 의존하면 **행 D−1** | 그래서 `D.HIGHEST(H,20)` = D−20..D−1(전일까지 20일), `D.SMA(C,20)` = D−20..D−1 종가 평균 (v0.3 정정 — 처음 규칙 "항상 D−1 행"은 highest 에서 하루 밀림) | C3 확장 + 표시 지표마다 "봉 D 변조 → 그날 값 불변" |
| `daily_live` | 키움 조건검색처럼 **오늘 일봉을 장중 값으로** 만든 뒤 계산: O=당일 첫 시가, H/L=t까지 최고/최저, C=t 봉 종가, V/대금=t까지 누적 | 과거 일봉(D−1까지) + 오늘 가상 봉(t 까지)으로 계산 | **C6**: 같은 날 t 이후 분봉 변조 → t 이하 값 불변, 그리고 값 = "가상 봉을 붙인 일봉으로 다시 계산한 값"(손계산 대조) |

- `daily_live` 는 **실시간 지원 표시가 있는 지표만**(카탈로그 `live=True`) — 점화식이 O(1)인 것: sma·ema·wma·highest·lowest·change_pct·gap_pct·rsi·rsi_wilder·bb·stoch·이격도·기울기·52주 위치·박스 폭·연속 봉·캔들 계열. 나머지는 `daily_prev` 만(검증 오류 문구로 안내).
- **거래량·거래대금 계열 `daily_live`**: 과거 일봉은 KRX 인데 장중 분봉 기본 출처는 통합(AL)이라 섞으면 부풀려진다 → `intraday.source=al` 이면 **검증 오류**("거래량 계열 일봉 실시간은 KRX 분봉에서만 — 통합 분봉과 KRX 일봉을 섞으면 20~40% 부풀려진다"), `krx` 면 허용.
- 일봉 데이터는 이미 엔진이 사전 필터용으로 읽는 일봉 패널을 재사용(추가 로드 없음). 워밍업: 필요한 가장 긴 창 + 여유.

### 3.3 조건 카탈로그 (`catalog.py` 등록 + 분류별 `ind_*.py` 계산) — 70여 종

표기: 모드 D=일봉, M=분봉, T=틱 / live = `daily_live` 지원 / ✔=기존.

**가격·이평·신고가 (`ind_trend.py`)**

| 이름 | 표시명 | 파라미터 | 정의 | 모드 | live |
|---|---|---|---|---|:-:|
| sma ✔ · ema ✔ | 이동평균 · 지수이평 | src, n | | D M | ✔ |
| wma | 가중이평 | src, n | Σ(w_i·x_i)/Σw_i, w=1..n | D M | ✔ |
| vwma | 거래량가중이평 | n | Σ(C·V)/ΣV | D M | krx |
| ma_disparity | 이격도 | src, n, ma(sma/ema) | x / MA × 100 | D M | ✔ |
| ma_slope | 이평 기울기(%) | n, k | (MA_t / MA_{t−k} − 1)×100 | D M | ✔ |
| ma_aligned | 정배열(1/0) | n1<n2<n3[<n4] | MA_n1 > MA_n2 > … | D M | ✔ |
| ma_reversed | 역배열(1/0) | 같음 | MA_n1 < MA_n2 < … | D M | ✔ |
| highest ✔ · lowest ✔ | N봉 최고/최저 | src, n, include_current | | D M | ✔ |
| new_high | N봉 신고가 돌파(1/0) | n, src(high/close) | x_t > highest(high, n) (t 제외) | D M | ✔ |
| new_low | N봉 신저가 이탈(1/0) | n | low_t < lowest(low, n) (t 제외) | D M | ✔ |
| high52_pct | 52주 고가 대비(%) | — | (C / highest(H,250) − 1)×100 | D M | ✔ |
| low52_pct | 52주 저가 대비(%) | — | (C / lowest(L,250) − 1)×100 | D M | ✔ |
| bars_since_high | 신고가 뒤 경과 봉 | n | 최근 n봉 최고가가 난 뒤 지난 봉 수 | D M | ✔ |
| box_pct | 박스 폭(%) | n | (highest(H,n) − lowest(L,n)) / lowest(L,n) × 100 | D M | ✔ |
| up_streak · down_streak | 연속 상승/하락 봉 | — | 종가가 직전보다 오른(내린) 연속 봉 수 | D M | ✔ |
| change_pct ✔ · gap_pct ✔ | | | | | ✔ |
| limit_up_pct | 상한가까지 남은(%) | — | (전일 종가×1.3 을 **호가 단위로 절사** − C) / C × 100 (반올림하면 130% 초과 — c3 정정) | D M | ✔ |
| limit_up_hit | 상한가 도달(1/0) | — | H ≥ 상한가 | D M | ✔ |
| prev_high_break | 전일 고가 돌파(1/0) | — | 일봉: C_t > H_{t−1} / 분봉: C_t > D−1 고가 | D M | — |
| rel_strength | 상대강도(%p) | n, index | 종목 n봉 등락률 − 지수 n봉 등락률 | D (M는 daily_prev) | — |

**보조지표 (`ind_oscillator.py`)**

| 이름 | 표시명 | 파라미터 | 정의 | live |
|---|---|---|---|:-:|
| rsi ✔ · rsi_wilder ✔ | RSI | n | | ✔ |
| rsi_signal | RSI 신호선 | n, m | sma(RSI_n, m) | ✔ |
| macd · macd_signal · macd_hist | MACD 선·신호·히스토그램 | fast, slow, sig | EMA_f − EMA_s / EMA(MACD, sig) / 차 | ✔ |
| stoch_k · stoch_d | 스토캐스틱 %K(느린)·%D | n, k, d | 빠른 %K=(C−LL)/(HH−LL)×100, 느린 %K=sma(빠른,k), %D=sma(느린,d) | ✔ |
| cci | CCI | n | (TP − sma(TP,n)) / (0.015 × 평균편차) | — |
| adx · plus_di · minus_di | ADX·+DI·−DI | n | 와일더 평활 | — |
| obv · obv_signal | OBV·신호 | m | 누적(부호×V), sma(OBV,m) | — |
| mfi | MFI | n | 자금흐름지수 | — |
| williams_r | 윌리엄스 %R | n | (HH − C)/(HH − LL) × −100 | ✔ |
| momentum · roc | 모멘텀·ROC | n | C − C_{t−n} / (C/C_{t−n}−1)×100 | ✔ |
| ichimoku_conv · ichimoku_base · ichimoku_span_a · ichimoku_span_b · ichimoku_cloud_top · ichimoku_cloud_bottom | 일목 전환·기준·선행1·선행2·구름 위/아래 | 9,26,52 | 선행스팬은 **t 에서 보이는 구름 = t−26 에 계산된 값**(앞으로 민 것) — 미래참조 없음 | — |
| envelope_upper · envelope_lower | 엔벨로프 | n, pct | sma × (1 ± pct) | ✔ |
| bb_upper ✔ · bb_lower ✔ · bb_pctb · bb_width | 볼린저 %b·폭 | n, k | (C−하단)/(상단−하단) / (상단−하단)/중심×100 | ✔ |
| psar | 파라볼릭 SAR | step, max | 와일더 | — |
| keltner_upper · keltner_lower | 켈트너 | n, mult | ema ± mult×ATR | — |
| psy | 투자심리선 | n | n봉 중 상승 봉 비율×100 | ✔ |
| vr | VR | n | 상승일 V 합 / 하락일 V 합 ×100(보합 반씩) | — |
| atr ✔ · atr_pct · volatility | ATR·ATR(%)·변동성 | n | ATR/C×100 · 수익률 표준편차(%) | ✔(atr_pct) |

**캔들 (`ind_candle.py`)** — 전부 D M, live ✔

| 이름 | 정의 |
|---|---|
| body_pct | (C−O)/O×100 |
| upper_wick_ratio · lower_wick_ratio | 윗꼬리/(H−L), 아랫꼬리/(H−L) |
| range_pct | (H−L)/전일 종가×100 |
| long_bull · long_bear (min_body_pct) | 장대양봉/음봉(1/0) |
| doji (max_body_ratio) · hammer · inverted_hammer | 1/0 |
| bull_engulfing · bear_engulfing | 장악형(1/0) |
| inside_bar · outside_bar | 1/0 |
| gap_held · gap_filled (min_gap_pct) | 갭 상승 뒤 저가 > 전일 종가 / 갭 메움 |

**거래량·거래대금·순위 (`ind_volume.py`)**

| 이름 | 표시명 | 정의 | 모드 | live |
|---|---|---|---|:-:|
| vol_ratio ✔ | 거래량 N봉 평균 대비 | | D M | krx |
| vol_change_pct | 직전 봉 대비 거래량(%) | V_t/V_{t−1}×100 | D M | krx |
| value_ratio | 거래대금 N봉 평균 대비 | | D M | krx |
| value_rank ✔ · volume_rank | 대금·거래량 순위 | 그날 순위(D−1 기준 선택) | D | — |
| top_value_count | 최근 n일 대금 상위 m 진입 횟수 | n, m | D (M는 daily_prev) | — |
| cum_value_rank | 당일 누적 대금 순위(분봉 t 시점, 유니버스 안) | — | M | — |

**분봉 전용 (`intraday.py` 확장)** — M 만

| 이름 | 정의 |
|---|---|
| day_change_pct ✔ · time ✔ · cum_value ✔ · vwap ✔ | 기존 |
| open_change_pct | C_t / 당일 시가 − 1 (%) |
| day_high_break · day_low_break | t 봉이 당일 앞 봉들의 최고가/최저가를 넘음(1/0) |
| minutes_since_open | 09:00 부터 경과 분 |
| first_n_value | 장 시작 후 n분 누적 대금(n분 전엔 NaN) |
| vwap_disparity | (C/VWAP − 1)×100 |

**틱 전용 (`tick.py` 확장)** — T

| 이름 | 정의 |
|---|---|
| breakout_min ✔ · value_speed ✔ · buy_ratio ✔ | 기존 |
| trade_strength (w) | 체결강도 = w초 매수 체결량 / 매도 체결량 × 100 (틱룰) |
| block_trades (w, min_value) | w초 안 한 번에 min_value 이상 체결 건수 |
| daily_breakout (n) | 현재가 > D−1 까지 n일 최고가(틱 단위 N일 신고가 돌파) |

**테마·업종·시장 (`ind_group.py` + 참조 데이터)** — D (M는 daily_prev) · 결과에 "구성은 현재 기준" 경고

| 이름 | 정의 |
|---|---|
| theme_change · theme_value · theme_rank | 종목이 속한 소피증권 테마 그룹의 평균 등락률·대금 합·그룹 순위(그날) |
| rank_in_theme | 그룹 안 종목 등락(대금) 순위 |
| sector_change · sector_rank | 업종 평균 등락률·업종 순위 |
| market 피연산자 확대 | `kind:"market"` 에 ind 이름(sma·ema·rsi·ma_disparity·change_pct·highest·lowest) 허용 |

**포지션 (`position.py`, 청산 조건 전용)**

| 이름 | 정의(봉 t 종가 기준 — 청산은 다음 봉 시가, §3.5 규칙과 같은 시점) |
|---|---|
| pos.return_pct | (C_t / 매수가 − 1) × 100 |
| pos.bars_held · pos.minutes_held | 진입 봉을 1로 센 보유 봉 수 · 분 |
| pos.max_return_pct | 보유 중 최고 수익률(고가 기준) |
| pos.drawdown_pct | 보유 중 최고가 대비 현재 하락률 |
| pos.entry_price | 매수가 |

**시간·이벤트** — weekday(요일), days_since_listing(데이터 첫날 기준 경과 거래일 — 신규 상장 근사, 경고).

**수급·공매도 조건은 제외**(사용자 결정 09-26).

### 3.4 청산 규칙 확장 (`engine/fills.py` `ExitRules`)

| 칸 | 뜻 | 기본 |
|---|---|---|
| `take_profit_levels: [{pct, fraction}]` | 분할 익절 — 예 `[{5, 0.5}, {10, 1.0}]` = +5% 에 절반, +10% 에 나머지(봉 안 목표가 체결, 기존 익절과 같은 규칙) | 없음 |
| `take_profit_mode: intrabar/close` | 익절을 봉 안 즉시(기존) / 종가 확인 뒤 다음 봉 시가 | intrabar |
| `trail_activate_pct` | 최고 수익률이 X% 를 넘은 뒤부터 트레일링 작동 | 없음(즉시) |
| `breakeven_after_pct` | 최고 수익률 X% 도달 뒤 손절선을 매수가로 | 없음 |
| `max_holding_minutes` | 분봉 시간 청산 | 없음 |

- 분할 청산의 기록: 거래 한 건을 **조각 행**(같은 `entry_id`, `slice` 1·2…)으로 남긴다. 지표는 **진입 기준**(승률·기대값은 entry_id 로 묶어 합산) — 조각을 따로 세면 승률이 부풀려진다.
- 청산 조건 그룹(`strategy.exit`)에 `pos` 피연산자가 있으면 엔진이 보유 종목마다 봉 t 에서 평가(나머지 피연산자는 미리 계산한 표에서 읽음) → 참이면 다음 봉 시가 청산(`exit_reason = signal`).

### 3.5 사용자 수식 (`studio/domain/conditions/formula.py`)

```
식       := 논리합
논리합   := 논리곱 ( OR 논리곱 )*
논리곱   := 부정 ( AND 부정 )*
부정     := NOT 부정 | 비교
비교     := 합 ( (> | >= | < | <= | = | !=) 합 )?  |  CROSSUP(합, 합) | CROSSDOWN(합, 합)
합       := 곱 ( (+ | -) 곱 )*
곱       := 단항 ( (* | /) 단항 )*
단항     := - 단항 | 뒤붙이
뒤붙이   := 기본 ( '(' 정수 ')' )?            # 오프셋: C(1) = 1봉 전, 음수 금지
기본     := 숫자 | [단위 '.'] 필드 | [단위 '.'] 함수 '(' 인자 ')' | POS.이름 | '(' 식 ')'
필드     := O | H | L | C | V | VALUE
단위     := D (daily_prev) | DL (daily_live) | M1 | M3 | M5 | M10 | M15 | M30 | M60
함수     := 카탈로그 이름(대문자) + 별칭 MA=SMA, HIGHEST, LOWEST, CROSSUP, CROSSDOWN, HOLD(조건, k)
```

- 예: `C > D.HIGHEST(H,20)` (분봉에서 전일까지 20일 신고가 돌파) · `M5.C > M5.MA(C,20) AND DL.C > DL.MA(C,20)` · `POS.RETURN_PCT >= 5 AND RSI(14) >= 70`
- 컴파일 결과 = §3.1 AST(비교 → Condition, AND/OR → Group, NOT → negate, 산술 → expr). 원문도 명세에 같이 저장(재현).
- 상한: 길이 2,000자·깊이 20·함수 호출 50. 오류는 `(줄, 칸, 기대한 것)` 으로.
- 저장: `presets/studio/formulas/<이름>.json` `{name, text, description, created_at}` — API CRUD. 수식은 이름으로 조건 행에서 불러 쓴다(불러올 때 컴파일된 AST 를 명세에 박아 넣는다 — 수식 파일이 나중에 바뀌어도 옛 결과는 그대로).

---

## 4. API Specification

| Method | Path | 변경 |
|--------|------|------|
| GET | `/api/meta/indicators` | 분류(category)·표시명·정의 식·시점·모드·`live` 지원·예시 추가 |
| POST | `/api/conditions/validate` | `formula` 입력 허용 → 컴파일된 AST + 오류(줄·칸) |
| GET/PUT/DELETE | `/api/formulas` · `/api/formulas/{name}` | 사용자 수식 저장소 |
| GET | `/api/meta/recipes` | 조건검색 레시피 프리셋 목록(분류별) |

오류: 400 `VALIDATION_ERROR`(fieldErrors — 시간 단위·모드·live 미지원 사유), 422 `FORMULA_INVALID`(details: line, col, expected).

---

## 5. UI/UX Design

### 5.4 Page UI Checklist

#### 조건 고르기 (조건 행 왼쪽·오른쪽 피연산자)
- [ ] 분류 나무(가격·이평·신고가 / 보조지표 / 캔들 / 거래량·순위 / 테마·업종·시장 / 분봉 전용 / 틱 전용 / 포지션(청산만) / 내 수식) + 검색
- [ ] 조건마다 설명·정의 식·시점 규칙·예시, 지원 안 되는 모드면 비활성 + 이유
- [ ] 분봉 모드에서 피연산자마다 **시간 단위 선택**(이 봉 / 5분 / 15분 … / 일봉 전일 / 일봉 장중), live 미지원 지표는 "일봉 장중" 비활성 + 이유
- [ ] 연산자: 기존 6종 + N봉 이내 크로스 + 참이면/거짓이면 + "연속 k봉"
- [ ] 풀이 문장에 시간 단위가 보인다("일봉 20일선(전일 확정)", "5분봉 20선")

#### 청산 규칙
- [ ] 분할 익절 표(수익률·비중, 행 추가), 익절 방식(봉 안 즉시/종가 확인), 트레일링 발동 수익, 본전 손절, 시간 청산(분)
- [ ] 청산 조건 편집기에 포지션 피연산자(매수가 대비 수익률 등)

#### 사용자 수식
- [ ] 수식 입력칸(고정폭), [검사](오류 위치 표시), [저장](이름·설명), 내 수식 목록(불러오기·수정·삭제), 예시 모음

#### 레시피
- [ ] 조건검색 레시피 10종 이상(분봉 N일 신고가 돌파·눌림목·이평 정배열 첫 돌파·거래대금 급증·갭 상승 유지·52주 신고가 근접·RSI 과매도 반등·볼린저 수축 돌파·테마 대장 등) → 불러오면 조건 행으로 풀림

---

## 6. Error Handling
| Code | 뜻 |
|---|---|
| `VALIDATION_ERROR` | 시간 단위가 모드와 안 맞음 / live 미지원 지표 / 거래량 계열 daily_live + 통합 출처 / pos 를 진입에 씀 / 파라미터 범위 |
| `FORMULA_INVALID` | 수식 문법 오류(줄·칸·기대한 것), 모르는 함수, 상한 초과 |

---

## 7. Security Considerations
- 수식은 **eval·exec·import 없이** 토큰 → 문법 나무 → AST. 이름은 카탈로그 허용 목록만.
- 길이·깊이·호출 수 상한(계산 폭주 방지). 저장 파일 이름은 `^[가-힣A-Za-z0-9_\- ]{1,40}$`.

---

## 8. Test Plan

| 종류 | 내용 |
|---|---|
| 지표 단위 | 지표마다 손계산 가능한 짧은 표 또는 알려진 값(MACD·스토캐스틱·ADX·일목·SAR 은 정의 식으로 직접 계산한 기대값) |
| **C5** | `mN`: t 이후 분봉 변조 → t 이하 값 불변, 미마감 N분봉 값 사용 안 함 |
| **C6** | `daily_live`: 같은 날 t 이후 분봉 변조 → t 이하 불변, 값 = 가상 봉 붙인 일봉 재계산값 |
| **C7** | 포지션 조건: t 이후 변조 → t 이하 청산 결정 불변 |
| 수식 패리티 | 수식 = 같은 조건을 조립기로 만든 명세 → 신호 동일(대표 20식) · 악성 입력(깊이·길이·이상한 토큰) 거부 |
| 청산 | 분할 익절 수량·가격·순손익 손계산, 진입 기준 승률, 본전 손절·트레일링 발동 |
| 호환 | 기존 패리티 P1~P8·프리셋 6종·저장된 실행 결과 재실행 동일 |
| 성능 | 일봉 전 종목×5년 조건 5개 ≤ 30초 · 분봉 60일×30 조건 5개(일봉 피연산자 포함) ≤ 60초 |
| E2E | 라이브 8780: 레시피 "분봉 N일 신고가 돌파" → 실행 → 결과 / 수식 입력 → 검사 → 저장 → 실행 |

---

## 9. Clean Architecture

| 파일 | 계층 | 비고 |
|---|---|---|
| `conditions/{timeframe,formula,position,ind_trend,ind_oscillator,ind_candle,ind_volume,ind_group}.py` | Domain | IO 금지(§9.3 기존 규칙) — 테마·업종 구성은 infrastructure 가 dict 로 주입 |
| `infrastructure/reference_data.py` | Infrastructure | 테마·업종 구성 읽기(카탈로그 경로) |
| `infrastructure/formula_store.py` | Infrastructure | 수식 저장소 |
| `api/routes/{catalog,formulas}.py` | Presentation | |

---

## 11. Implementation Guide

### 11.3 Session Guide — Module Map

| Module | Scope Key | 내용 | 담당 | 선행 |
|---|---|---|---|---|
| 시간 단위·연산자 | `c1` | AST `tf`·`hold`·`negate`·새 연산자, `timeframe.py`(mN·daily_prev·daily_live), 평가기·memo 연결, C5·C6, 레시피 "분봉 N일 신고가 돌파"(SC-C1·C2) | backtest-agent | — |
| 청산 확장 | `c2` | `pos` 피연산자·보유 종목별 청산 평가·분할 익절·트레일링 발동·본전·시간 청산·조각 기록·진입 기준 지표, C7(SC-C7) | backtest-agent | c1 |
| 지표 카탈로그 | `c3` | `ind_trend`·`ind_oscillator`·`ind_candle` + 카탈로그 등록(분류·정의·live) + 지표 단위 테스트 | strategy-agent (테스트 lead 대행) | — |
| 거래량·테마·업종·틱 | `c4` | `ind_volume`·`ind_group`·`reference_data`·분봉 전용 확장·틱 확장 + 테스트 | data-agent | — |
| 사용자 수식 | `c5` | `formula.py`(해석기 → AST)·`formula_store`·API·수식 패리티·악성 입력 | execution-agent | c1(AST 칸) |
| 화면 | `c6` | 조건 고르기(분류 나무·검색·시간 단위)·청산 규칙·수식 편집기·레시피, `/api/meta/indicators` 확장, E2E | monitoring-agent | c1·c3 계약(지표 메타 모양) |
| ~~수급·공매도 견적~~ | `c7` | **취소**(사용자 결정 09-26 "없어도 될 거 같아") | — | — |

병렬: c1·c3·c4·c5(해석기 부분) 동시 시작 → c2·c5(c1 뒤) → c6(c1·c3 계약 뒤, 화면 골격은 먼저 가능).

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-09-26 | 초안 — 시간 단위 규칙·카탈로그 70여 종·수식 문법·청산 확장·모듈 배분 | lead |
| 0.3 | 2026-09-26 | daily_prev 정의 정정(장 시작 전에 알 수 있는 값 — highest 하루 밀림 해소), mN 09:00 격자, negate 값 없음=참 아님 | lead |
| 0.2 | 2026-09-26 | c3 판단 반영: 상한가 절사·52주/박스 현재 봉 포함·엔벨로프 pct=퍼센트·OBV 기준점·분봉 전일 고가=패널 전날 봉·일목 shift | lead |
