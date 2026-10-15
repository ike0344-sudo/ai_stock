# 트레이딩뷰 전략 규칙서 (백테스트 넘김용)

작성 2026-09-27 · scalping-researcher · 소스: `research/raw/tv/*.pine`(lead 가 pine-facade 로 받은 공개 소스 20개, 첫 줄에 원문 URL)
원칙: **규칙은 Pine 소스에서 그대로 옮김**(설명문과 다르면 소스 우선, 차이 표시). 성과·인기 숫자는 안 봄. "수익 난다" 판정 없음.

## 0. 공통 메모 (Pine 기본 동작 — 옮길 때 꼭 지킬 것)
- `strategy.entry` 시장가는 **신호 봉 종가에 결정 → 다음 봉 시가 체결**(`process_orders_on_close=false` 기본). 예외는 표에 적음.
- `pyramiding` 을 안 적으면 0 → 한 방향 포지션 1개.
- 소스의 수수료·슬리피지 값은 무시하고 우리 비용 모델(`studio/domain/costs.py`, 문턱 1.06%)을 쓴다.
- 공매도 쪽 규칙은 전부 뺀다(롱만).
- 봉 출처: 일봉(긴 과거 있음) / 분봉 = 통합 `minute_al`(종목별 1~2개월, 기본) 또는 KRX `minute_krx`(1년, **사용자가 고를 때만**, 섞어 비교 금지) / 틱 `tick_al`(약 36거래일).
- **세션 주의**: 통합 분봉은 08:00~20:00(NXT)까지 있다. "전날 마지막 봉·당일 첫 봉"을 쓰는 규칙은 `session="regular"`(09:00~15:30)로 잘라야 한다 — 안 그러면 전날 19:59 NXT 봉이 "전날 마지막 봉"이 된다.

## 1. 20개 선별 결과

| # | 소스 | 이름 | 종류 | 판정 | 이유 |
|---|---|---|---|---|---|
| 1 | ghocsiv7 | Gap Filling Strategy | strategy | **선정 A** | 장중 갭 메우기, 롱 가능, 규칙 단순, repaint 없음 → H-004 변형 |
| 2 | GoeqO1ev | Liquidity Sweep Reversal | strategy | **선정 B** | 스윙 저점 스윕 후 복귀, 롱 가능 → H-013 변형 |
| 3 | EA1AXZui | VWAP Reversal V1 | strategy | **선정 C** | VWAP 돌파 뒤 되돌림 재진입 → H-012 인접 변형 |
| 4 | nVECqIQx | TASC 2026.03 One Percent A Week | strategy | **선정 D** | 주 1회, 1~5일 보유, 한국 레버리지 ETF 로 옮길 수 있음 |
| 5 | Qg1Jra51 | RSI Bullish Divergence Breakout | strategy | **선정 E** | 일봉 롱 전용, 미래참조 없음 명시, 규칙 명확 |
| 6 | PETyqH3b | EMA Pullback Trend Continuation | strategy | **선정 F** | 추세 중 EMA50 눌림, 일봉·분봉 둘 다 가능 |
| 7 | M6uONKNI | BB Power + Squeeze Release | strategy | **선정 G (결함 확인 필요)** | 변동성 수축→확장. 단 손절·목표 변수 가림 결함 추정(아래) |
| 8 | n7sVlEUq | Stock Breakout Momentum | strategy | 겹침 — 제외 | 20봉 최고가 종가 돌파 + 거래량 = **롤링 돌파 전조**와 겹침 |
| 9 | OvE4qQgh | Liquidity Sweep + Delta Absorption | strategy | 겹침 — 제외 | 하위 봉 up/down 거래량 델타 = **체결 쏠림(H-009)** 계열. 스윕 부분은 #2 로 대체 |
| 10 | FDeprmix | TrendLock Supertrend Donchian | strategy | 제외 | **이름과 소스가 다름**: 롱 조건이 `close > lower_channel`(채널 **하단**) — 돌파가 아님. 사실상 "슈퍼트렌드 상승 + 거래량 1.5배" 추격. 4시간봉 `request.security`(lookahead_off, 실시간 repaint 가능) |
| 11 | Za5HKgrL | ICT 10AM First FVG | strategy | 제외 | 뉴욕 10시 기준, "왜 누가 잃나"를 못 씀(ICT 용어 체계). 롱·숏 대칭 |
| 12 | rLkjr2sQ | Bjorgum Double Tap | strategy | 제외 | 쌍바닥 패턴 상태기계가 복잡(행렬·선 객체로 판정) → 옮기다 틀릴 위험 큼, 메커니즘 없음 |
| 13 | V87nRt9v | MACD Pullback Sniper | strategy | 제외 | MACD 교차 + EMA200 + ADX 조합 — 메커니즘 없는 지표 조합 |
| 14 | nHGK4Qtp | PMax Explorer | strategy | 제외 | 이평 vs ATR 추적선 교차, 항상 롱/숏 전환. 다른 20종목 `security` 는 스크리너 표시용(매매 무관) |
| 15 | mVkDf8qh | TrendMaster Pro 2.3 | strategy | 제외 | SMA9/21 교차에 필터 7개 고정 — 과최적화 조합, 미국 세션 시간 하드코딩. 지지·저항은 `lookahead_on` security(그림 전용) |
| 16 | mpjNqADq | SuperTrend Regime Confluence | strategy | 제외 | 슈퍼트렌드 전환 + 점수 65 이상 — 점수 가중치가 임의 |
| 17 | kbYTJ8V2 | Aurora KAMA Trend | strategy | 제외 | KAMA 3봉 상승 + SMA200 — 일반 추세추종, pyramiding=1 |
| 18 | YVnhptce | STP Flip Always-In | strategy | 제외(위험) | 항상 포지션, 뒤집을 때마다 **수량 2배**(마틴게일식), 공매도 필수 |
| 19 | mmrInMTp | Momentum Sequence [Herman] | strategy | 제외 | 음봉 뒤 연속 5양봉 추격 — 메커니즘 없음 |
| 20 | oG5a3MJU | Ichimoku 5 Rules | **indicator** | 제외 | 전략이 아니라 지표(`indicator()`), 목록 제목과 다름 |

선정 7개(A~G). 카드로 만든 것: 메커니즘이 서는 A·B·C 만 기존 카드 변형으로 병합(새 카드 없음). D~G 는 메커니즘을 한 문장으로 못 써서 **규칙서만**.

---

## 2. 선정 전략 규칙 (소스 그대로)

### A. Gap Filling Strategy — `ghocsiv7` (alexgrover, Pine v4) → [[H-004]] 변형 f
원문: https://www.tradingview.com/script/ghocsiv7-Gap-Filling-Strategy/

| 항목 | 소스 규칙 |
|---|---|
| 봉 | 장중 봉(아무 분봉). `ses = change(time("D"))` = 그날 첫 봉 |
| 진입(롱, 기본 invert=false) | 그날 첫 봉이 **아래 갭**: `open < low[1]`(전 봉 저가 아래 시가) **그리고** `max(close, open) < min(close[1], open[1])`(첫 봉 몸통 전체가 전 봉 몸통 아래). 첫 봉 종가에 판정 → 다음 봉 시가 매수 |
| 목표 | 지정가 = `min(close[1], open[1])`(전날 마지막 봉 몸통 아래끝) — 갭 메움 |
| 손절 | **없음** |
| 시간청산 | 기본 "New Session": **다음 날 첫 봉**에서 전량 청산(당일 청산 아님 — 오버나이트 보유 발생) |
| 재진입 | 하루 첫 봉에서만 신호 → 하루 최대 1회 |
| 숏 | 위 갭이면 숏 — 제외 |
| repaint | 없음(확정 봉만) |
| 우리 데이터 | 분봉 가능(통합 1~2개월 / KRX 1년). **정규장만** 잘라야 "전 봉 = 전날 15:30 종가 단일가 봉" |
| 옮길 때 판단 필요 | 손절 없음·오버나이트 보유를 그대로 둘지, 15:19 시간청산 변형을 추가할지 — 사람이 정함(여기선 원형만 기록) |

### B. Liquidity Sweep Reversal — `GoeqO1ev` → [[H-013]] 변형
원문: https://www.tradingview.com/script/GoeqO1ev-Sweep-Reverse-Liquidity-Sweep-Reversal-Strategy/

| 항목 | 소스 규칙 |
|---|---|
| 봉 | 장중(기본 세션 필터 12:00~16:00 거래소 시각 = 런던·뉴욕 겹침) → 한국은 시간대 재지정 필요 |
| 기준 저점 | `pivotlow(low, 7, 7)`(좌우 7봉, **7봉 뒤 확정**). 기존 저점과 0.25×ATR14 안이면 안 담음. 150봉 지나면 폐기 |
| 스윕(롱) | `low < 저점 and close > 저점` + 아래꼬리 ≥ 1.5×몸통(몸통 0이면 꼬리>0) + 거래량 > 1.3×거래량SMA20. 스윕된 저점은 목록에서 삭제 |
| 확인(기본 켬) | 다음 봉 `close > (스윕 꼬리 저가 + 스윕 봉 종가)/2` → 그 봉 종가 판정, 다음 봉 시가 매수 |
| 손절 | 스윕 꼬리 저가 − 1.2×ATR14. 위험 < 0.5×ATR14 이면 **진입 안 함** |
| 목표 | 확인 봉 종가 + 1.5×위험 |
| 본전 이동 | 고가가 (진입가 + 50%×(목표−진입가)) 도달 시 손절 → 진입가 |
| 시간청산 | **없음**(장 마감 청산도 없음) |
| 차이/주의 | 손절·목표·본전 기준 "진입가"가 실제 체결가가 아니라 **확인 봉 종가**(`activeEntry := close`) |
| repaint | 없음(피벗 확정 뒤 사용) |
| 우리 데이터 | 분봉 가능. 틱으로 정밀화하면 H-013 원형과 비교 가능 |

### C. VWAP Reversal V1 — `EA1AXZui` → [[H-012]] 인접 변형
원문: https://www.tradingview.com/script/EA1AXZui-VWAP-Reversal-Strategy-V1/

| 항목 | 소스 규칙 |
|---|---|
| 봉 | 장중. 세션 필터 기본 꺼짐(켜면 13:30~20:00 UTC) |
| VWAP | `ta.vwap`(당일 앵커) |
| 진입(롱) | ① 최근 ≤10봉 안에 `close` 가 VWAP 상향 교차 ② 교차 이후 최저가 ≤ VWAP(되돌림 접촉) ③ 현재 `close > VWAP` 이고 양봉 ④ \|close−VWAP\| > 0.2×ATR14 ⑤ 1시간봉 VWAP 편향: `close > VWAP(60분)` |
| 기본 꺼진 필터 | 아래꼬리 ≥1.3×몸통, 거래량 ≥1.2×SMA20 |
| 횟수 | 하루 최대 2회, 동시 1포지션 |
| 손절/목표 | 평균단가 − 1×ATR14 / 평균단가 + **10×ATR14**(사실상 거의 안 닿음) |
| 시간청산 | **없음 — 장 마감 청산 없음, 오버나이트 가능**(설명은 "장중 프레임워크") ← 설명과 다름 |
| repaint | **주의**: `calc_on_every_tick=true` + `request.security("60", ta.vwap)`(lookahead 지정 없음=off) → 과거 봉 백테스트는 괜찮지만 실시간 신호는 봉 안에서 바뀔 수 있음 |
| 우리 데이터 | 분봉 가능(VWAP·60분 VWAP 모두 분봉에서 계산) |

### D. TASC 2026.03 One Percent A Week — `nVECqIQx` (PineCoders, 원 대상 TQQQ)
원문: https://www.tradingview.com/script/nVECqIQx-TASC-2026-03-One-Percent-A-Week/

| 항목 | 소스 규칙 |
|---|---|
| 봉 | `session.isfirstbar_regular` 사용 — 분봉·일봉 모두 동작 |
| 진입 | **월요일** 정규장 첫 봉에서 주간 시가 `wOpen = open` 기록, **지정가 매수 = wOpen×0.99**. 주문은 취소 코드가 없어 그 주 안(다음 월요일에 새 가격으로 갱신될 때까지) 대기 |
| 목표 | 체결 **다음 날** 정규장 첫 봉에 지정가 매도 = 평균단가×1.01 |
| 본전 규칙 | 저가 < 평균단가×0.995 가 되면 매도 지정가를 **평균단가(본전)**로 바꿈 — 손절 주문이 아니라 "본전 회복 시 매도" 지정가 |
| 손절 | **없음**(본전 지정가 + 금요일 강제청산뿐) |
| 시간청산 | 금요일 정규장 마지막 봉(확정)에서 전량 청산 |
| 크기 | 자본의 10% |
| repaint | 없음 |
| 우리 데이터 | 일봉으로 근사 가능(단 같은 날 본전·목표 순서는 분봉 필요). 한국 대상 후보: 코스피200·코스닥150 레버리지 ETF — **ETF 는 매도 거래세 면제라 비용 구조가 다름 [확인 필요]**. ETF 일봉이 저장소에 있는지 미확인 |
| 메커니즘 | 원 기사는 "레버리지 ETF 의 주중 되돌림" 통계. "누가 잃나"는 못 씀 → 카드 없음 |

### E. RSI Bullish Divergence (Oversold) Breakout — `Qg1Jra51`
원문: https://www.tradingview.com/script/Qg1Jra51-RSI-Bullish-Divergence-Oversold-Breakout/

| 항목 | 소스 규칙 |
|---|---|
| 봉 | 아무 봉(디버그 날짜로 보아 일봉 기준 작성) |
| 설정 | RSI(14). RSI 피벗 저점 = 좌 5봉보다 낮고 우 5봉보다 낮음(우 5봉 뒤 확정). `early=true` 면 우측 1~4봉만으로 임시 피벗도 인정(과거 봉만 사용 → 미래참조 아님) |
| 셋업 | L1 = 직전 확정 피벗(**RSI(L1) < 30**), L2 = 새 피벗, L2−L1 = 5~60봉, RSI(L2) > RSI(L1), 가격 저가(L2) < 저가(L1) |
| 트리거 | H = L1~L2 사이 RSI 최고값. RSI 종가 > H → 다음 봉 시가 매수. 단 `close < 목표`·`close > 손절` 일 때만 |
| 손절 | S = L2 이후 최저가(대기 중 계속 갱신), 버퍼 0% |
| 목표 | T = L1~L2 사이 최고가(기본) |
| 취소 | RSI < RSI(L2) 이거나 L2 뒤 30봉 넘으면 셋업 취소 |
| 시간청산 | **없음** — 보유기간 상한 없음(과제 조건 "1~5일"보다 길어질 수 있음) |
| 크기 | 자본 100%, 수수료 0.03%(무시) |
| repaint | 없음(소스 주석에도 명시, 확인함) |
| 우리 데이터 | 일봉 가능(긴 과거) |

### F. EMA Pullback Trend Continuation — `PETyqH3b`
원문: https://www.tradingview.com/script/PETyqH3b-EMA-Pullback-Trend-Continuation-Strategy-with-Volume-and-Momentu/

| 항목 | 소스 규칙 |
|---|---|
| 봉 | 아무 봉 |
| 진입(롱) | EMA50 > EMA200 **그리고** 직전 봉이 EMA50 에 닿음(`low[1] ≤ EMA50[1]` 또는 `close[1] < EMA50[1]`) **그리고** 현재 `close > EMA50` **그리고** 거래량 > 거래량SMA20 **그리고** RSI14 > 40, 포지션 없음. 확정 봉 → 다음 봉 시가 |
| 손절 | 최근 5봉 최저가 − 0.5×ATR14 (신호 봉 기준) |
| 목표 | 신호 봉 종가 + 2.5×ATR14 |
| 시간청산 | 없음 |
| 크기 | 자본 10% |
| repaint | 없음 |
| 우리 데이터 | 일봉·분봉 둘 다 가능 |

### G. BB Power Oscillator + Squeeze Release — `M6uONKNI` (**소스 결함 추정**)
원문: https://www.tradingview.com/script/M6uONKNI-Power-Surge-BB-Momentum-Squeeze-Release/

| 항목 | 소스 규칙 |
|---|---|
| 봉 | 아무 봉 |
| Bull Power | 14봉에 걸쳐 Σmax(close−upper,0) ÷ Σ\|close−upper\| ×100, upper = EMA14 + 1×표준편차14 |
| 스퀴즈 | BB(SMA20 ± 2σ) 가 KC(EMA20 ± 1.5×EMA20(TR)) 안에 들어감 = 스퀴즈. 스퀴즈 끝난 첫 봉 = 해제 |
| 진입(롱) | Bull Power 가 50 을 상향 교차 **그리고** 해제 후 10봉 이내, 포지션 없음 |
| 손절(의도) | close − 1.4×ATR30, 위험 1% 로 수량 계산 |
| 목표(의도) | 체결가 + 1.5×위험, 0.75×위험 도달 시 본전, 이후 고가 − 1.5×ATR30 추적 |
| 시간청산 | 50봉 보유 시 청산 |
| **결함** | 106행 `var float plannedStop` 을 115행 `if` 안에서 `plannedStop = ...`(`:=` 아님)로 **새로 선언** → 바깥 변수는 계속 na. 그러면 `initStop·target·trailStop` 이 na 가 되어 **손절·목표·본전이 작동 안 하고 50봉 시간청산만 남을 수 있음** [추론 — 실제 컴파일로 확인 필요] |
| repaint | 없음 |
| 우리 데이터 | 일봉·분봉 가능 |
| 권고 | 백테스트 전 lead 가 트레이딩뷰에서 거래 목록을 한 번 열어 청산 사유가 전부 "Max Hold" 인지 확인. 그렇다면 "의도 규칙판"과 "소스 그대로판" 중 무엇을 시험할지 사람이 정함 |

---

## 3. backtest-agent 넘김 요약
| 선정 | 봉 | 데이터 | 비고 |
|---|---|---|---|
| A 갭 메우기 | 분봉(정규장) | 통합 1~2개월 / KRX 1년(사용자 선택) | 손절 없음·다음 날 첫 봉 청산이 원형 |
| B 스윕 반전 | 분봉 | 동일 | 세션 시각 한국으로, 진입가 기준 = 확인 봉 종가 |
| C VWAP 되돌림 | 분봉 | 동일 | 장 마감 청산 없음이 원형, 목표 10ATR |
| D 1%/주 | 일봉(+분봉 순서 확인) | 일봉, ETF 보유 여부 확인 | 레버리지 ETF 대상, 세금 다름 |
| E RSI 다이버전스 | 일봉 | 일봉 | 보유기간 상한 없음 |
| F EMA 눌림 | 일봉·분봉 | 둘 다 | — |
| G 스퀴즈 해제 | 일봉·분봉 | 둘 다 | 소스 결함 먼저 확인 |

비용 메모(판정 아님): 분봉 전략(A·B·C)의 목표는 ATR 배수라 1~5분봉이면 거래당 움직임이 문턱 1.06% 에 못 미칠 수 있다 [추론]. 15분봉·일봉판을 같이 볼 가치.
