> **[정정, 2026-08-31 22:00]** 아래 가중치 표는 `app/config.py`의 `DEFAULTS`(코드 기본값)를
> 옮긴 것인데, 실제 적용값은 `config.yaml`이 override한다(2026-08-22 재구성, 지금도 유효).
> 특히 share_ratio/relative_volume은 지금 **0(완전 제외)**, value_rank는 30, rise_strength는
> 27이다 — 상세 정정표는 `state/agent_reports/strategy-agent_20260831-2200_mail_theme_rank_processed_and_correction.md`
> 참고. 아래 원문은 정정 근거 보존을 위해 그대로 둔다.

# kospi-theme-engine 테마 점수 로직 파악 (읽기 전용, 가중치 미변경)

대상: `kospi-theme-engine/app/engine/{scoring.py,aggregator.py}`, `app/config.py`, `app/reference/store.py`

## 구조
- 테마 점수(0~100) = `sum(weight_i * min(1, metric_i/cap_i))`, `config.yaml`(`score.weights`) 합이 100 아니면 로드시 에러.
- 별도로 대장주(leader) 점수(0~100)를 종목 단위로 매기고, 테마의 1등 리더를 그 테마 대표로 붙인다.
- 모든 배수(속도/누적/점유율)는 **baseline 대비**로 잰다. baseline은 최근 20영업일(`profile.lookback_days`) 같은 시간대(slot="HH:MM") 중앙값 — 절대 거래대금을 안 쓰는 이유는 삼전/하이닉스 같은 대형주가 상시 만점을 깔고 시작하는 걸 막기 위함(코드 주석에 명시).

## 테마 점수 8개 구성요소 (가중치 순)
| 항목 | 가중치 | cap | 의미 |
|---|---|---|---|
| value_rank | 22 | 3 | 대금상위 20위 내 자리가중 합. **상승종목만**(등락률≥`value_rank_min_chg`) 카운트, 상시 대형주는 `value_rank_surge_gate`로 자리 불인정, 등락률 비례 감쇠(`value_rank_chg_full`) |
| rise_strength | 20 | 5.0%p | 거래대금 가중 평균 등락률 (단순평균 아님 — 대금 실린 종목이 오르는가) |
| value_share | 13 | 0.10 | 테마 거래대금 / 시장(구독200) 거래대금 |
| share_ratio | 11 | 3.0x | 시장점유율의 baseline 대비 배수 (테마 크기 상쇄) |
| flow_speed | 12 | 5.0x | 최근 60초(`flow_window_sec`) 유입속도의 baseline 분당 대비 배수 |
| relative_volume | 9 | 6.0x | 누적 거래대금의 baseline 누적 대비 배수 |
| new_high | 6 | (관찰종목 대비 비율, cap 없음) | 신고가(전일까지 N일고가 돌파, N=`profile.nday_high`=20) 종목 비율 |
| rising_ratio | 7 | (비율, cap 없음) | 등락률≥5.0%(`rise_min_pct`) 종목 비율 |

- 하락은 감점이 아니라 0점(마이너스를 안 넣음) — "수급은 몰리는데 아직 안 오른" 테마가 순위에서 안 사라지게.
- cap은 배점 낼 때만 걸고, 화면 표시용 raw 비율은 안 자름(5.00x vs 12x 구분 유지).

## 대장주(leader) 점수 — 테마와 별도 가중치
`tv_share .35 + change_pct .30 + flow_speed .20 + new_high .15` (합 1.0, ×100).
- 대장 선정 기준은 상승률 1위가 아니라 "돈이 가장 몰린 종목"(tv_share 최상위 가중).
- 최소거래대금(`leader.min_trading_value`=50억) 미달 종목은 score×0.3 — 품절주가 대장으로 뽑히는 걸 막는 패널티.

## baseline 데이터 흐름
`Reference`(app/reference/store.py)가 오프라인에서 만든 20일 median을 슬롯별로 들고 있음: `theme_profile`(분당)/`theme_profile_cum`(누적), `stock_profile_cum`, `market_profile_cum`. baseline 없는 슬롯(시간외 등)은 `speed=rel=0`으로 처리(가짜 강세 방지).

## 전략 관점 메모 (판단 아님, 관찰만)
- 신고가추세매매와 맞닿는 지표는 `value_rank`(22, 최대 가중) + `new_high`(6) + `share_ratio`(11) 조합 — "돈이 실제로 몰리는 자리"가 압도적 비중, 신고가 자체 비중은 낮음.
- `rise_strength` cap이 5%p로 타이트해서 +5% 넘는 급등은 더 이상 가산 없음(포화) — 이 테마 스코어를 신호로 끌어쓸 경우 후속 상승 폭 변별력은 낮을 수 있음.
- 이 로직을 전략 신호로 재사용할 여지가 있으면(예: 테마 주도주 진입 필터) 별도 가설로 제안하겠음 — 지금은 파악만, 코드 변경 없음.

가중치·판정 로직 변경 없음. 큐 항목 완료 처리.
