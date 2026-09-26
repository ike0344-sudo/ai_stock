// 실제 서버 응답(2026-09-26, 라이브 8780)에서 뽑은 분봉·틱 결과 고정 값 — 분봉 2026-08-24~09-23 · 상위 30 · 5분봉 / 틱 2026-09-01~09-23.
// 요약 하위 구조(summary.intraday·tick·tick_refine)는 타입을 붙여 선언해 컴파일이 실제 응답과 맞는지 검사한다. 거래는 앞 12건, 종목별 보관 기간은 8종목만 남겼다.
import type { IntradaySummary, RunDetail, TickRefineSummary, TickSummary, Trade } from '@/types/studio'

const base = (d: unknown) => d as RunDetail

export const alIntraday: IntradaySummary = {
 "expected_pairs": 690,
 "used_pairs": 566,
 "pairs_share": 0.8202898550724638,
 "days_with_bars": 23,
 "days_in_period": 23,
 "codes_requested": 141,
 "codes_with_minutes": 135,
 "codes_without_minutes": [
  "0011A0",
  "0126Z0",
  "0155E0",
  "0161M0",
  "0220W0",
  "386380"
 ],
 "warmup_days": 8,
 "bar_minutes": 5,
 "minute_source": "al",
 "code_periods": {
  "000150": [
   "2026-08-21",
   "2026-09-18"
  ],
  "000270": [
   "2026-08-24",
   "2026-09-18"
  ],
  "000500": [
   "2026-08-07",
   "2026-09-04"
  ],
  "000720": [
   "2026-08-24",
   "2026-09-18"
  ],
  "000810": [
   "2026-08-13",
   "2026-09-18"
  ],
  "000880": [
   "2026-07-27",
   "2026-09-18"
  ],
  "000990": [
   "2026-08-24",
   "2026-09-18"
  ],
  "001210": [
   "2026-08-04",
   "2026-09-18"
  ]
 }
}

export const alDetail: RunDetail = base({ ...{
 "run_id": "20260926-081441-05610f",
 "meta": {
  "mode": "intraday",
  "compat": false,
  "spec_hash": "f8dbe9e09da9a849",
  "structure_hash": "e02fb4c9d4dd79e5",
  "params": {},
  "data": {
   "daily": [
    "2019-04-23",
    "2026-09-23"
   ],
   "kospi": [
    "2021-07-26",
    "2026-09-23"
   ],
   "kosdaq": [
    "2021-07-26",
    "2026-09-23"
   ],
   "minute_al": [
    "2025-08-01",
    "2026-09-23"
   ],
   "minute_krx": [
    "2025-07-01",
    "2026-09-23"
   ],
   "tick_al": [
    "2026-08-04",
    "2026-09-23"
   ]
  },
  "period_used": [
   "2026-08-24",
   "2026-09-23"
  ],
  "warmup_bars": 8,
  "elapsed_sec": 7.542,
  "warnings": [
   "분봉 커버리지: 기대 (날짜,종목) 690쌍 중 566쌍만 분봉이 있어 나머지는 거래 기회가 없었다(82%) — 종목별 보관 기간이 다르다",
   "분봉 짧은 표본: 분봉이 있는 거래일 23일(<60) — 결과의 통계적 의미가 약하다",
   "분봉 거래대금(value)은 종가×거래량 근사값이다 — 분 단위에선 실제 거래대금과 크게 다를 수 있다. 사전 필터의 일봉 거래대금도 KRX 근사",
   "분봉 출처: 통합(AL) 보관소(정규장 09:00~15:30, NXT 체결 포함). 15:30 종가 단일가 봉은 EOD 이후라 거래하지 않는다",
   "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
   "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)"
  ],
  "minute_source": "al",
  "bar_minutes": 5,
  "eod_time": "15:20",
  "prefilter_top_value": 30,
  "run_id": "20260926-081441-05610f",
  "engine_version": "0.1.0",
  "git": {
   "commit": "2392556",
   "dirty": true
  },
  "created_at": "2026-09-26T08:14:50"
 },
 "spec": {
  "version": 1,
  "name": "분봉 스모크",
  "mode": "intraday",
  "period": {
   "start": "2026-08-24",
   "end": "2026-09-23"
  },
  "universe": {
   "type": "top_value",
   "n": 100,
   "lookback_days": 1,
   "markets": [
    "거래소",
    "코스닥"
   ],
   "exclude": [
    "spac",
    "preferred",
    "mega_cap"
   ],
   "codes": []
  },
  "strategy": {
   "source": "builder",
   "entry": {
    "logic": "all",
    "items": [
     {
      "left": {
       "kind": "field",
       "name": "close",
       "offset": 0,
       "mul": 1.0
      },
      "op": "gt",
      "right": {
       "kind": "ind",
       "name": "highest",
       "params": {
        "src": "high",
        "n": 20
       },
       "offset": 0,
       "mul": 1.0
      }
     }
    ]
   },
   "exit": {
    "logic": "any",
    "items": []
   }
  },
  "market_filter": null,
  "exits": {
   "stop_loss_pct": 1.5,
   "take_profit_pct": 3.0,
   "trailing_stop_pct": null,
   "max_holding_bars": null
  },
  "portfolio": {
   "initial_capital": 10000000.0,
   "max_positions": 3.0,
   "sizing": "equal_slot_fixed",
   "fixed_amount": null,
   "risk_pct": null,
   "max_weight_pct": 34.0,
   "rank_by": "value",
   "random_seed": 42
  },
  "costs": {
   "commission_rate": 0.00015,
   "tax_rate": 0.0023,
   "slippage_mode": "max_rate_tick",
   "slippage_rate": 0.001,
   "slippage_ticks": 1
  },
  "fills": {
   "same_bar_policy": "stop_first",
   "volume_cap_pct": 10.0
  },
  "intraday": {
   "bar_minutes": 5,
   "source": "al",
   "prefilter": null,
   "prefilter_top_value": 30,
   "eod_time": "15:20"
  },
  "tick": null,
  "compat": {
   "legacy": false
  },
  "params": {},
  "validation": null
 },
 "warnings": [
  "분봉 커버리지: 기대 (날짜,종목) 690쌍 중 566쌍만 분봉이 있어 나머지는 거래 기회가 없었다(82%) — 종목별 보관 기간이 다르다",
  "분봉 짧은 표본: 분봉이 있는 거래일 23일(<60) — 결과의 통계적 의미가 약하다",
  "분봉 거래대금(value)은 종가×거래량 근사값이다 — 분 단위에선 실제 거래대금과 크게 다를 수 있다. 사전 필터의 일봉 거래대금도 KRX 근사",
  "분봉 출처: 통합(AL) 보관소(정규장 09:00~15:30, NXT 체결 포함). 15:30 종가 단일가 봉은 EOD 이후라 거래하지 않는다",
  "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
  "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)"
 ],
 "analysis": {
  "monthly": [
   {
    "period": "2026-08",
    "return_pct": -7.958869618700126
   },
   {
    "period": "2026-09",
    "return_pct": -28.78087950006859
   }
  ],
  "yearly": [
   {
    "period": "2026",
    "return_pct": -34.44911644424307
   }
  ],
  "exit_reasons": [
   {
    "reason": "stop",
    "n": 134,
    "share_pct": 60.36036036036037,
    "avg_net_pct": -1.8834605414432222
   },
   {
    "reason": "target",
    "n": 48,
    "share_pct": 21.62162162162162,
    "avg_net_pct": 2.603014941333016
   },
   {
    "reason": "eod",
    "n": 40,
    "share_pct": 18.01801801801802,
    "avg_net_pct": -0.00876601818007897
   }
  ],
  "by_sector": [
   {
    "key": "일반서비스",
    "n": 9,
    "win_rate_pct": 44.44444444444444,
    "net_pnl": 166499.60138514324,
    "avg_net_pct": 0.6294500183134458
   },
   {
    "key": "비금속",
    "n": 2,
    "win_rate_pct": 50.0,
    "net_pnl": 19532.87634000057,
    "avg_net_pct": 0.3733439390086359
   },
   {
    "key": "보험",
    "n": 2,
    "win_rate_pct": 50.0,
    "net_pnl": 16218.183250000002,
    "avg_net_pct": 0.31929060502073825
   },
   {
    "key": "금속",
    "n": 2,
    "win_rate_pct": 50.0,
    "net_pnl": -37809.40235500003,
    "avg_net_pct": -0.5942108398131347
   },
   {
    "key": "운송/창고",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -58665.610575,
    "avg_net_pct": -1.917740857605178
   },
   {
    "key": "(미분류)",
    "n": 2,
    "win_rate_pct": 0.0,
    "net_pnl": -117003.32075977308,
    "avg_net_pct": -1.8545836750000024
   },
   {
    "key": "화학",
    "n": 19,
    "win_rate_pct": 31.57894736842105,
    "net_pnl": -193247.91741511069,
    "avg_net_pct": -0.36077392527487523
   },
   {
    "key": "IT 서비스",
    "n": 16,
    "win_rate_pct": 37.5,
    "net_pnl": -201647.04674447334,
    "avg_net_pct": -0.48540639379019024
   },
   {
    "key": "제약",
    "n": 14,
    "win_rate_pct": 28.57142857142857,
    "net_pnl": -243337.22594920488,
    "avg_net_pct": -0.6006296110591773
   },
   {
    "key": "유통",
    "n": 11,
    "win_rate_pct": 18.181818181818183,
    "net_pnl": -246197.8218240245,
    "avg_net_pct": -0.8571882202265563
   },
   {
    "key": "운송장비/부품",
    "n": 9,
    "win_rate_pct": 0.0,
    "net_pnl": -347122.40632914566,
    "avg_net_pct": -1.5935431464600815
   },
   {
    "key": "건설",
    "n": 14,
    "win_rate_pct": 21.428571428571427,
    "net_pnl": -372305.376746984,
    "avg_net_pct": -0.8715500826946865
   },
   {
    "key": "기계/장비",
    "n": 29,
    "win_rate_pct": 31.03448275862069,
    "net_pnl": -390420.88159875455,
    "avg_net_pct": -0.5490042758534146
   },
   {
    "key": "금융",
    "n": 34,
    "win_rate_pct": 29.411764705882355,
    "net_pnl": -663608.9167010289,
    "avg_net_pct": -0.7230470517655249
   },
   {
    "key": "전기/전자",
    "n": 58,
    "win_rate_pct": 32.758620689655174,
    "net_pnl": -775796.3784009557,
    "avg_net_pct": -0.49167621324877586
   }
  ],
  "by_theme_group": [
   {
    "key": "전력",
    "n": 3,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": -11390.474753279297,
    "avg_net_pct": -0.42836174908952734
   },
   {
    "key": "데이터센터",
    "n": 13,
    "win_rate_pct": 30.76923076923077,
    "net_pnl": -44556.76412111817,
    "avg_net_pct": -0.15302176619907745
   },
   {
    "key": "원전",
    "n": 19,
    "win_rate_pct": 42.10526315789473,
    "net_pnl": -44643.18323315164,
    "avg_net_pct": -0.05117683677882231
   },
   {
    "key": "신재생",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -56742.40275,
    "avg_net_pct": -1.9519230392156866
   },
   {
    "key": "우주",
    "n": 5,
    "win_rate_pct": 40.0,
    "net_pnl": -58464.576004146205,
    "avg_net_pct": -0.3371513886629819
   },
   {
    "key": "양자",
    "n": 9,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": -78835.34900697289,
    "avg_net_pct": -0.3890992323547395
   },
   {
    "key": "조선",
    "n": 3,
    "win_rate_pct": 0.0,
    "net_pnl": -133234.495,
    "avg_net_pct": -1.8608337232238252
   },
   {
    "key": "화장품",
    "n": 5,
    "win_rate_pct": 20.0,
    "net_pnl": -146167.18690250663,
    "avg_net_pct": -0.9856437245007298
   },
   {
    "key": "2차전지",
    "n": 12,
    "win_rate_pct": 41.66666666666667,
    "net_pnl": -148733.49699999997,
    "avg_net_pct": -0.4474002675851594
   },
   {
    "key": "반도체",
    "n": 26,
    "win_rate_pct": 38.46153846153847,
    "net_pnl": -165574.11296298305,
    "avg_net_pct": -0.30245684003011647
   },
   {
    "key": "5G",
    "n": 6,
    "win_rate_pct": 16.666666666666664,
    "net_pnl": -183003.60020000025,
    "avg_net_pct": -1.1415228393865717
   },
   {
    "key": "바이오",
    "n": 12,
    "win_rate_pct": 25.0,
    "net_pnl": -215864.5668894693,
    "avg_net_pct": -0.644389078775589
   },
   {
    "key": "로봇",
    "n": 14,
    "win_rate_pct": 21.428571428571427,
    "net_pnl": -268342.6798749997,
    "avg_net_pct": -0.7675989353332473
   },
   {
    "key": "(미분류)",
    "n": 32,
    "win_rate_pct": 31.25,
    "net_pnl": -414883.3565303311,
    "avg_net_pct": -0.4736243127569515
   },
   {
    "key": "방산",
    "n": 23,
    "win_rate_pct": 21.73913043478261,
    "net_pnl": -551341.6423014571,
    "avg_net_pct": -0.8088996812022181
   },
   {
    "key": "지주사",
    "n": 39,
    "win_rate_pct": 25.64102564102564,
    "net_pnl": -923133.7568938961,
    "avg_net_pct": -0.8607967261560829
   }
  ],
  "histogram": {
   "edges": [
    -1.9972791062801931,
    -1.7659200334661826,
    -1.5345609606521724,
    -1.303201887838162,
    -1.0718428150241515,
    -0.840483742210141,
    -0.6091246693961307,
    -0.3777655965821203,
    -0.1464065237681098,
    0.08495254904590044,
    0.31631162185991113,
    0.5476706946739214,
    0.7790297674879316,
    1.0103888403019423,
    1.2417479131159526,
    1.4731069859299633,
    1.7044660587439735,
    1.9358251315579837,
    2.1671842043719938,
    2.398543277186005,
    2.629902350000015
   ],
   "counts": [
    134,
    1,
    1,
    2,
    3,
    5,
    3,
    4,
    3,
    6,
    2,
    4,
    0,
    0,
    4,
    1,
    0,
    0,
    0,
    49
   ]
  }
 },
 "narration": "종가가 20봉 최고가를 넘면 다음 봉 시가에 산다.\n※ 분봉 N봉 지표(이동평균·최고가 등)는 전날 봉을 포함해 계산하므로 장 시작 직후 신호는 전날 흐름의 영향을 받는다.\n청산 규칙: 손절 -1.5%, 익절 +3%.\n15:20 에 남은 물량을 정리한다.",
 "has_grid": false,
 "has_folds": false
}, summary: { ...{
 "metrics": {
  "total_return_pct": -34.44911644424307,
  "cagr_pct": -99.02199991068052,
  "max_drawdown_pct": 34.44911644424307,
  "mdd_duration_bars": 23,
  "volatility_pct": 38.9251175315794,
  "sharpe": -11.585610158984984,
  "sortino": -9.508147811678507,
  "calmar": -2.874442369834089,
  "num_trades": 222,
  "win_rate_pct": 29.72972972972973,
  "profit_factor": 0.5330496403277367,
  "avg_win_pct": 2.1115276581583515,
  "avg_loss_pct": -1.7125029585580858,
  "expectancy_pct": -0.575628991426172,
  "max_consec_losses": 15,
  "avg_holding_bars": 14.058558558558559,
  "exposure_pct": 0.0,
  "turnover": 75.07896914577903,
  "commission_total": 183591.87413213402,
  "tax_total": 1405403.3978513856,
  "slippage_total": 1565004.1398407668,
  "skipped": {
   "slots_full": 879,
   "cash": 0,
   "upper_limit": 0,
   "volume_cap": 0,
   "no_data": 324
  },
  "benchmark_return_pct": 5.73334766819571,
  "excess_return_pct": -40.18246411243878,
  "beta": 0.265966939786004
 },
 "legacy_metrics": null,
 "skipped": {
  "slots_full": 879,
  "cash": 0,
  "upper_limit": 0,
  "volume_cap": 0,
  "no_data": 324
 },
 "n_trades": 222,
 "n_closed": 222,
 "n_codes": 135,
 "n_bars": 23,
 "universe_excluded": {
  "spac": 64,
  "preferred": 7,
  "mega_cap": 2,
  "market_unknown": 0,
  "market_other": 0
 },
 "warnings": [
  "분봉 커버리지: 기대 (날짜,종목) 690쌍 중 566쌍만 분봉이 있어 나머지는 거래 기회가 없었다(82%) — 종목별 보관 기간이 다르다",
  "분봉 짧은 표본: 분봉이 있는 거래일 23일(<60) — 결과의 통계적 의미가 약하다",
  "분봉 거래대금(value)은 종가×거래량 근사값이다 — 분 단위에선 실제 거래대금과 크게 다를 수 있다. 사전 필터의 일봉 거래대금도 KRX 근사",
  "분봉 출처: 통합(AL) 보관소(정규장 09:00~15:30, NXT 체결 포함). 15:30 종가 단일가 봉은 EOD 이후라 거래하지 않는다",
  "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
  "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)"
 ],
 "robustness": {
  "n_trades": 222,
  "cost_sensitivity": [
   {
    "mult": 0.0,
    "net_pnl": -290912.23260002513,
    "net_return_pct": -2.9091223260002512
   },
   {
    "mult": 0.5,
    "net_pnl": -1867911.9385121684,
    "net_return_pct": -18.679119385121684
   },
   {
    "mult": 1.0,
    "net_pnl": -3444911.644424312,
    "net_return_pct": -34.44911644424312
   },
   {
    "mult": 1.5,
    "net_pnl": -5021911.350336455,
    "net_return_pct": -50.21911350336454
   },
   {
    "mult": 2.0,
    "net_pnl": -6598911.056248598,
    "net_return_pct": -65.98911056248598
   },
   {
    "mult": 3.0,
    "net_pnl": -9752910.468072886,
    "net_return_pct": -97.52910468072886
   }
  ],
  "breakeven_cost_mult": 0.0,
  "cost_sensitivity_meta": {
   "gross_before_costs": -290912.23260002513,
   "total_costs": 3153999.4118242864,
   "approximation": "같은 거래·같은 수량을 가정한 사후 계산(비용이 바뀌면 달라질 사이징·건너뜀은 미반영)"
  },
  "monte_carlo": {
   "n_sims": 1000,
   "seed": 42,
   "n_trades": 222,
   "weight": 0.27608147385585585,
   "final_return_pct": {
    "p5": -38.18878737085195,
    "p50": -30.176942668257706,
    "p95": -20.07733634716015
   },
   "max_drawdown_pct": {
    "p5": 21.679313129518004,
    "p50": 30.961942052692983,
    "p95": 38.89981219247948
   },
   "prob_mdd_gt_30": 0.569,
   "approximation": "겹친 보유 무시 — 거래를 한 줄로 세워 복리"
  },
  "concentration": {
   "total_net_pnl": -3444911.644424311,
   "by_code": [
    {
     "k": 1,
     "removed": [
      "052690"
     ],
     "removed_pnl": 189595.99638514323,
     "net_pnl_excluding": -3634507.640809454,
     "sign_flipped": false
    },
    {
     "k": 2,
     "removed": [
      "052690",
      "222800"
     ],
     "removed_pnl": 353394.78565861203,
     "net_pnl_excluding": -3798306.430082923,
     "sign_flipped": false
    },
    {
     "k": 3,
     "removed": [
      "052690",
      "222800",
      "010120"
     ],
     "removed_pnl": 431729.68482361274,
     "net_pnl_excluding": -3876641.3292479236,
     "sign_flipped": false
    }
   ],
   "by_date": [
    {
     "k": 1,
     "removed": [
      "2026-09-03"
     ],
     "removed_pnl": 69324.11305820923,
     "net_pnl_excluding": -3514235.7574825203,
     "sign_flipped": false
    },
    {
     "k": 2,
     "removed": [
      "2026-09-03",
      "2026-08-31"
     ],
     "removed_pnl": 83028.12358188606,
     "net_pnl_excluding": -3527939.768006197,
     "sign_flipped": false
    },
    {
     "k": 3,
     "removed": [
      "2026-09-03",
      "2026-08-31",
      "2026-09-18"
     ],
     "removed_pnl": 48737.225435063345,
     "net_pnl_excluding": -3493648.869859374,
     "sign_flipped": false
    }
   ]
  }
 },
 "criteria": []
}, intraday: alIntraday } })

export const alTrades: Trade[] = [
 {
  "code": "001210",
  "name": "금호전기",
  "sector": "전기/전자",
  "entry_ts": "2026-08-24T09:10:00",
  "entry_price": 9460.0,
  "exit_ts": "2026-08-24T09:10:00",
  "exit_price": 9308.1,
  "qty": 352,
  "gross_pnl": -53468.79999999987,
  "commission": 990.9556799999999,
  "tax": 7535.83776,
  "slippage_cost": 7040.0,
  "net_pnl": -61995.59343999987,
  "net_pct": -0.018617742600422794,
  "exit_reason": "stop",
  "bars_held": 1,
  "mfe_pct": 2.9598308668076,
  "mae_pct": -3.488372093023251
 },
 {
  "code": "041190",
  "name": "우리기술투자",
  "sector": "금융",
  "entry_ts": "2026-08-24T09:10:00",
  "entry_price": 6299.999999999999,
  "exit_ts": "2026-08-24T09:15:00",
  "exit_price": 6195.499999999999,
  "qty": 529,
  "gross_pnl": -55280.5,
  "commission": 991.5179249999998,
  "tax": 7538.064849999999,
  "slippage_cost": 10579.99999999952,
  "net_pnl": -63810.082775,
  "net_pct": -0.0191466626984127,
  "exit_reason": "stop",
  "bars_held": 2,
  "mfe_pct": 2.539682539682553,
  "mae_pct": -3.1746031746031633
 },
 {
  "code": "006400",
  "name": "삼성SDI",
  "sector": "전기/전자",
  "entry_ts": "2026-08-24T09:10:00",
  "entry_price": 496500.0,
  "exit_ts": "2026-08-24T09:15:00",
  "exit_price": 510395.0,
  "qty": 6,
  "gross_pnl": 83370.0,
  "commission": 906.2054999999999,
  "tax": 7043.451,
  "slippage_cost": 9000.0,
  "net_pnl": 75420.3435,
  "net_pct": 0.025317335850956697,
  "exit_reason": "target",
  "bars_held": 2,
  "mfe_pct": 4.128902316213501,
  "mae_pct": -0.503524672708966
 },
 {
  "code": "001210",
  "name": "금호전기",
  "sector": "전기/전자",
  "entry_ts": "2026-08-25T09:10:00",
  "entry_price": 8950.0,
  "exit_ts": "2026-08-25T09:10:00",
  "exit_price": 8805.75,
  "qty": 372,
  "gross_pnl": -53661.0,
  "commission": 990.7708499999999,
  "tax": 7534.1997,
  "slippage_cost": 7440.0,
  "net_pnl": -62185.97055,
  "net_pct": -0.018677831005586593,
  "exit_reason": "stop",
  "bars_held": 1,
  "mfe_pct": 0.22346368715084886,
  "mae_pct": -2.7932960893854775
 },
 {
  "code": "124500",
  "name": "아이티센글로벌",
  "sector": "IT 서비스",
  "entry_ts": "2026-08-25T09:10:00",
  "entry_price": 40150.0,
  "exit_ts": "2026-08-25T09:10:00",
  "exit_price": 39497.75,
  "qty": 81,
  "gross_pnl": -52832.25,
  "commission": 967.7201624999999,
  "tax": 7358.4308249999995,
  "slippage_cost": 8100.0,
  "net_pnl": -61158.400987500005,
  "net_pct": -0.01880552895392279,
  "exit_reason": "stop",
  "bars_held": 1,
  "mfe_pct": 1.1207970112079746,
  "mae_pct": -2.8642590286425906
 },
 {
  "code": "124500",
  "name": "아이티센글로벌",
  "sector": "IT 서비스",
  "entry_ts": "2026-08-25T09:15:00",
  "entry_price": 40250.0,
  "exit_ts": "2026-08-25T09:15:00",
  "exit_price": 41407.5,
  "qty": 82,
  "gross_pnl": 94915.0,
  "commission": 1004.3872499999999,
  "tax": 7809.4545,
  "slippage_cost": 8200.0,
  "net_pnl": 86101.15825000001,
  "net_pct": 0.026087307453416152,
  "exit_reason": "target",
  "bars_held": 1,
  "mfe_pct": 4.223602484472044,
  "mae_pct": -0.7453416149068359
 },
 {
  "code": "005380",
  "name": "현대차",
  "sector": "운송장비/부품",
  "entry_ts": "2026-08-25T09:10:00",
  "entry_price": 416000.00000000006,
  "exit_ts": "2026-08-25T09:20:00",
  "exit_price": 409260.00000000006,
  "qty": 8,
  "gross_pnl": -53920.0,
  "commission": 990.3120000000001,
  "tax": 7530.384000000001,
  "slippage_cost": 8000.000000000466,
  "net_pnl": -62440.695999999996,
  "net_pct": -0.01876222836538461,
  "exit_reason": "stop",
  "bars_held": 3,
  "mfe_pct": 0.24038461538460343,
  "mae_pct": -2.4038461538461675
 },
 {
  "code": "124500",
  "name": "아이티센글로벌",
  "sector": "IT 서비스",
  "entry_ts": "2026-08-25T09:20:00",
  "entry_price": 41600.00000000001,
  "exit_ts": "2026-08-25T09:25:00",
  "exit_price": 40926.00000000001,
  "qty": 80,
  "gross_pnl": -53920.0,
  "commission": 990.3120000000001,
  "tax": 7530.384000000001,
  "slippage_cost": 8000.000000000582,
  "net_pnl": -62440.695999999996,
  "net_pct": -0.01876222836538461,
  "exit_reason": "stop",
  "bars_held": 2,
  "mfe_pct": 0.9615384615384359,
  "mae_pct": -4.687500000000022
 },
 {
  "code": "278470",
  "name": "에이피알",
  "sector": "화학",
  "entry_ts": "2026-08-25T09:35:00",
  "entry_price": 420500.0,
  "exit_ts": "2026-08-25T09:55:00",
  "exit_price": 432615.0,
  "qty": 7,
  "gross_pnl": 84805.0,
  "commission": 895.7707499999999,
  "tax": 6965.1015,
  "slippage_cost": 7000.0,
  "net_pnl": 76944.12775,
  "net_pct": 0.02614035255648038,
  "exit_reason": "target",
  "bars_held": 5,
  "mfe_pct": 3.091557669441136,
  "mae_pct": -0.9512485136741966
 },
 {
  "code": "028260",
  "name": "삼성물산",
  "sector": "유통",
  "entry_ts": "2026-08-25T09:35:00",
  "entry_price": 366500.0,
  "exit_ts": "2026-08-25T10:05:00",
  "exit_price": 360502.5,
  "qty": 9,
  "gross_pnl": -53977.5,
  "commission": 981.4533749999999,
  "tax": 7462.40175,
  "slippage_cost": 9000.0,
  "net_pnl": -62421.355124999995,
  "net_pct": -0.018924164051841743,
  "exit_reason": "stop",
  "bars_held": 7,
  "mfe_pct": 0.13642564802183177,
  "mae_pct": -1.7735334242837686
 },
 {
  "code": "006400",
  "name": "삼성SDI",
  "sector": "전기/전자",
  "entry_ts": "2026-08-25T10:05:00",
  "entry_price": 522000.0,
  "exit_ts": "2026-08-25T10:15:00",
  "exit_price": 513170.0,
  "qty": 6,
  "gross_pnl": -52980.0,
  "commission": 931.6529999999999,
  "tax": 7081.746,
  "slippage_cost": 12000.0,
  "net_pnl": -60993.399,
  "net_pct": -0.0194742653256705,
  "exit_reason": "stop",
  "bars_held": 3,
  "mfe_pct": 0.3831417624521105,
  "mae_pct": -1.532567049808431
 },
 {
  "code": "012450",
  "name": "한화에어로스페이스",
  "sector": "운송장비/부품",
  "entry_ts": "2026-08-25T09:30:00",
  "entry_price": 1120118.9999999998,
  "exit_ts": "2026-08-25T10:25:00",
  "exit_price": 1102213.8977849998,
  "qty": 2,
  "gross_pnl": -35810.204429999925,
  "commission": 666.6998693354999,
  "tax": 5070.183929810999,
  "slippage_cost": 4444.634429999627,
  "net_pnl": -41547.08822914642,
  "net_pct": -0.018545836749999968,
  "exit_reason": "stop",
  "bars_held": 12,
  "mfe_pct": 1.685624473828251,
  "mae_pct": -1.5283197588827457
 }
]

export const krxIntraday: IntradaySummary = {
 "expected_pairs": 690,
 "used_pairs": 690,
 "pairs_share": 1.0,
 "days_with_bars": 23,
 "days_in_period": 23,
 "codes_requested": 141,
 "codes_with_minutes": 141,
 "codes_without_minutes": [],
 "warmup_days": 8,
 "bar_minutes": 5,
 "minute_source": "krx",
 "code_periods": {
  "000150": [
   "2025-07-01",
   "2026-09-23"
  ],
  "000270": [
   "2025-07-01",
   "2026-09-23"
  ],
  "000500": [
   "2025-07-01",
   "2026-09-23"
  ],
  "000720": [
   "2025-07-01",
   "2026-09-23"
  ],
  "000810": [
   "2025-07-01",
   "2026-09-23"
  ],
  "000880": [
   "2025-07-01",
   "2026-09-23"
  ],
  "000990": [
   "2025-07-01",
   "2026-09-23"
  ],
  "0011A0": [
   "2026-03-09",
   "2026-09-23"
  ]
 }
}

export const krxDetail: RunDetail = base({ ...{
 "run_id": "20260926-081452-448b22",
 "meta": {
  "mode": "intraday",
  "compat": false,
  "spec_hash": "a9f216cd025f46cf",
  "structure_hash": "dfe09170c7796b4e",
  "params": {},
  "data": {
   "daily": [
    "2019-04-23",
    "2026-09-23"
   ],
   "kospi": [
    "2021-07-26",
    "2026-09-23"
   ],
   "kosdaq": [
    "2021-07-26",
    "2026-09-23"
   ],
   "minute_al": [
    "2025-08-01",
    "2026-09-23"
   ],
   "minute_krx": [
    "2025-07-01",
    "2026-09-23"
   ],
   "tick_al": [
    "2026-08-04",
    "2026-09-23"
   ]
  },
  "period_used": [
   "2026-08-24",
   "2026-09-23"
  ],
  "warmup_bars": 8,
  "elapsed_sec": 10.809,
  "warnings": [
   "분봉 짧은 표본: 분봉이 있는 거래일 23일(<60) — 결과의 통계적 의미가 약하다",
   "분봉 거래대금(value)은 종가×거래량 근사값이다 — 분 단위에선 실제 거래대금과 크게 다를 수 있다. 사전 필터의 일봉 거래대금도 KRX 근사",
   "분봉 출처: **KRX 전용**(통합 아님) — NXT 체결이 빠져 거래량·거래대금이 통합보다 20~40% 작다(삼성전자 0.76 등, data-agent 실측). 가격은 거의 같다. 거래량·거래대금 조건의 임계값을 통합(AL) 결과와 섞어 해석하지 말 것. 15:30 종가 단일가 봉은 EOD 이후라 거래하지 않는다",
   "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
   "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)"
  ],
  "minute_source": "krx",
  "bar_minutes": 5,
  "eod_time": "15:20",
  "prefilter_top_value": 30,
  "run_id": "20260926-081452-448b22",
  "engine_version": "0.1.0",
  "git": {
   "commit": "2392556",
   "dirty": true
  },
  "created_at": "2026-09-26T08:15:05"
 },
 "spec": {
  "version": 1,
  "name": "분봉 KRX 스모크",
  "mode": "intraday",
  "period": {
   "start": "2026-08-24",
   "end": "2026-09-23"
  },
  "universe": {
   "type": "top_value",
   "n": 100,
   "lookback_days": 1,
   "markets": [
    "거래소",
    "코스닥"
   ],
   "exclude": [
    "spac",
    "preferred",
    "mega_cap"
   ],
   "codes": []
  },
  "strategy": {
   "source": "builder",
   "entry": {
    "logic": "all",
    "items": [
     {
      "left": {
       "kind": "field",
       "name": "close",
       "offset": 0,
       "mul": 1.0
      },
      "op": "gt",
      "right": {
       "kind": "ind",
       "name": "highest",
       "params": {
        "src": "high",
        "n": 20
       },
       "offset": 0,
       "mul": 1.0
      }
     }
    ]
   },
   "exit": {
    "logic": "any",
    "items": []
   }
  },
  "market_filter": null,
  "exits": {
   "stop_loss_pct": 1.5,
   "take_profit_pct": 3.0,
   "trailing_stop_pct": null,
   "max_holding_bars": null
  },
  "portfolio": {
   "initial_capital": 10000000.0,
   "max_positions": 3.0,
   "sizing": "equal_slot_fixed",
   "fixed_amount": null,
   "risk_pct": null,
   "max_weight_pct": 34.0,
   "rank_by": "value",
   "random_seed": 42
  },
  "costs": {
   "commission_rate": 0.00015,
   "tax_rate": 0.0023,
   "slippage_mode": "max_rate_tick",
   "slippage_rate": 0.001,
   "slippage_ticks": 1
  },
  "fills": {
   "same_bar_policy": "stop_first",
   "volume_cap_pct": 10.0
  },
  "intraday": {
   "bar_minutes": 5,
   "source": "krx",
   "prefilter": null,
   "prefilter_top_value": 30,
   "eod_time": "15:20"
  },
  "tick": null,
  "compat": {
   "legacy": false
  },
  "params": {},
  "validation": null
 },
 "warnings": [
  "분봉 짧은 표본: 분봉이 있는 거래일 23일(<60) — 결과의 통계적 의미가 약하다",
  "분봉 거래대금(value)은 종가×거래량 근사값이다 — 분 단위에선 실제 거래대금과 크게 다를 수 있다. 사전 필터의 일봉 거래대금도 KRX 근사",
  "분봉 출처: **KRX 전용**(통합 아님) — NXT 체결이 빠져 거래량·거래대금이 통합보다 20~40% 작다(삼성전자 0.76 등, data-agent 실측). 가격은 거의 같다. 거래량·거래대금 조건의 임계값을 통합(AL) 결과와 섞어 해석하지 말 것. 15:30 종가 단일가 봉은 EOD 이후라 거래하지 않는다",
  "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
  "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)"
 ],
 "analysis": {
  "monthly": [
   {
    "period": "2026-08",
    "return_pct": -10.645063147883638
   },
   {
    "period": "2026-09",
    "return_pct": -27.4777239829467
   }
  ],
  "yearly": [
   {
    "period": "2026",
    "return_pct": -35.197766061244494
   }
  ],
  "exit_reasons": [
   {
    "reason": "stop",
    "n": 130,
    "share_pct": 62.5,
    "avg_net_pct": -1.883422944033668
   },
   {
    "reason": "target",
    "n": 41,
    "share_pct": 19.71153846153846,
    "avg_net_pct": 2.59403859334927
   },
   {
    "reason": "eod",
    "n": 37,
    "share_pct": 17.78846153846154,
    "avg_net_pct": 0.06837235877114488
   }
  ],
  "by_sector": [
   {
    "key": "비금속",
    "n": 2,
    "win_rate_pct": 50.0,
    "net_pnl": 19874.927630000566,
    "avg_net_pct": 0.3733439390086357
   },
   {
    "key": "보험",
    "n": 2,
    "win_rate_pct": 50.0,
    "net_pnl": 15460.682499999413,
    "avg_net_pct": 0.29338277578984384
   },
   {
    "key": "일반서비스",
    "n": 6,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": -26245.132328660875,
    "avg_net_pct": -0.15213305344236344
   },
   {
    "key": "운송/창고",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -58073.02864999999,
    "avg_net_pct": -1.917740857605178
   },
   {
    "key": "통신",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -60369.51573385216,
    "avg_net_pct": -1.854583674999995
   },
   {
    "key": "유통",
    "n": 7,
    "win_rate_pct": 28.57142857142857,
    "net_pnl": -63106.033119765474,
    "avg_net_pct": -0.4192176304663375
   },
   {
    "key": "금속",
    "n": 3,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": -82278.16885450654,
    "avg_net_pct": -1.1420707948966748
   },
   {
    "key": "화학",
    "n": 17,
    "win_rate_pct": 35.294117647058826,
    "net_pnl": -122124.99379553078,
    "avg_net_pct": -0.2523581332805269
   },
   {
    "key": "(미분류)",
    "n": 7,
    "win_rate_pct": 28.57142857142857,
    "net_pnl": -139686.92080436856,
    "avg_net_pct": -0.5924632290096614
   },
   {
    "key": "IT 서비스",
    "n": 11,
    "win_rate_pct": 27.27272727272727,
    "net_pnl": -141805.25564857933,
    "avg_net_pct": -0.4390986537230386
   },
   {
    "key": "운송장비/부품",
    "n": 7,
    "win_rate_pct": 0.0,
    "net_pnl": -208944.56624619628,
    "avg_net_pct": -1.2151171255929227
   },
   {
    "key": "기계/장비",
    "n": 28,
    "win_rate_pct": 32.142857142857146,
    "net_pnl": -276856.642093764,
    "avg_net_pct": -0.4151545698422472
   },
   {
    "key": "건설",
    "n": 14,
    "win_rate_pct": 28.57142857142857,
    "net_pnl": -313230.2724034895,
    "avg_net_pct": -0.7587365270504404
   },
   {
    "key": "금융",
    "n": 24,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": -337294.7301738404,
    "avg_net_pct": -0.5822846439327704
   },
   {
    "key": "제약",
    "n": 18,
    "win_rate_pct": 22.22222222222222,
    "net_pnl": -419772.4737223476,
    "avg_net_pct": -0.8804569782175259
   },
   {
    "key": "전기/전자",
    "n": 60,
    "win_rate_pct": 26.666666666666668,
    "net_pnl": -1305324.4826795473,
    "avg_net_pct": -0.8734047594229352
   }
  ],
  "by_theme_group": [
   {
    "key": "2차전지",
    "n": 10,
    "win_rate_pct": 50.0,
    "net_pnl": 34110.96475000042,
    "avg_net_pct": 0.10724632704363553
   },
   {
    "key": "양자",
    "n": 7,
    "win_rate_pct": 42.857142857142854,
    "net_pnl": 10503.03035142069,
    "avg_net_pct": 0.029610608401048642
   },
   {
    "key": "로봇",
    "n": 6,
    "win_rate_pct": 16.666666666666664,
    "net_pnl": -78338.59987499965,
    "avg_net_pct": -0.49096186696907984
   },
   {
    "key": "우주",
    "n": 4,
    "win_rate_pct": 25.0,
    "net_pnl": -108216.83927119662,
    "avg_net_pct": -1.0761077695349774
   },
   {
    "key": "조선",
    "n": 3,
    "win_rate_pct": 0.0,
    "net_pnl": -113889.455625,
    "avg_net_pct": -1.5095170549157508
   },
   {
    "key": "전력",
    "n": 4,
    "win_rate_pct": 25.0,
    "net_pnl": -146010.3013298106,
    "avg_net_pct": -1.34127683670977
   },
   {
    "key": "신재생",
    "n": 3,
    "win_rate_pct": 0.0,
    "net_pnl": -160808.52950950677,
    "avg_net_pct": -1.915841050230217
   },
   {
    "key": "화장품",
    "n": 3,
    "win_rate_pct": 0.0,
    "net_pnl": -163897.91756434506,
    "avg_net_pct": -1.8908012457624332
   },
   {
    "key": "데이터센터",
    "n": 14,
    "win_rate_pct": 21.428571428571427,
    "net_pnl": -184227.46026170888,
    "avg_net_pct": -0.41620536574546313
   },
   {
    "key": "원전",
    "n": 18,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": -189663.24472132334,
    "avg_net_pct": -0.3654577235520394
   },
   {
    "key": "5G",
    "n": 7,
    "win_rate_pct": 14.285714285714285,
    "net_pnl": -228649.06478875026,
    "avg_net_pct": -1.2615073443614062
   },
   {
    "key": "(미분류)",
    "n": 31,
    "win_rate_pct": 35.483870967741936,
    "net_pnl": -269657.0803371376,
    "avg_net_pct": -0.31659760397105896
   },
   {
    "key": "바이오",
    "n": 13,
    "win_rate_pct": 23.076923076923077,
    "net_pnl": -300645.90822054655,
    "avg_net_pct": -0.8507533275319596
   },
   {
    "key": "방산",
    "n": 19,
    "win_rate_pct": 21.052631578947366,
    "net_pnl": -473519.8981553194,
    "avg_net_pct": -0.8754725071905967
   },
   {
    "key": "지주사",
    "n": 33,
    "win_rate_pct": 30.303030303030305,
    "net_pnl": -538683.6867543736,
    "avg_net_pct": -0.7067596950668945
   },
   {
    "key": "반도체",
    "n": 33,
    "win_rate_pct": 30.303030303030305,
    "net_pnl": -608182.6148118515,
    "avg_net_pct": -0.8063194200757342
   }
  ],
  "histogram": {
   "edges": [
    -1.9972791062801933,
    -1.7659200334661829,
    -1.5345609606521724,
    -1.3032018878381622,
    -1.0718428150241517,
    -0.8404837422101412,
    -0.609124669396131,
    -0.3777655965821205,
    -0.14640652376811003,
    0.08495254904590022,
    0.3163116218599109,
    0.5476706946739212,
    0.7790297674879314,
    1.010388840301942,
    1.2417479131159523,
    1.473106985929963,
    1.7044660587439733,
    1.9358251315579835,
    2.1671842043719938,
    2.398543277186005,
    2.629902350000015
   ],
   "counts": [
    130,
    0,
    0,
    1,
    2,
    5,
    3,
    3,
    5,
    6,
    3,
    2,
    3,
    1,
    2,
    1,
    0,
    0,
    0,
    41
   ]
  }
 },
 "narration": "종가가 20봉 최고가를 넘면 다음 봉 시가에 산다.\n※ 분봉 N봉 지표(이동평균·최고가 등)는 전날 봉을 포함해 계산하므로 장 시작 직후 신호는 전날 흐름의 영향을 받는다.\n※ KRX 분봉 기준 — NXT 체결이 빠져 거래량·거래대금이 통합보다 20~40% 작다(같은 임계값이 더 엄격해진다).\n청산 규칙: 손절 -1.5%, 익절 +3%.\n15:20 에 남은 물량을 정리한다.",
 "has_grid": false,
 "has_folds": false
}, summary: { ...{
 "metrics": {
  "total_return_pct": -35.197766061244494,
  "cagr_pct": -99.13765411735565,
  "max_drawdown_pct": 35.197766061244494,
  "mdd_duration_bars": 23,
  "volatility_pct": 42.284703905067005,
  "sharpe": -10.926180400183707,
  "sortino": -9.170673149254526,
  "calmar": -2.8165893808389733,
  "num_trades": 208,
  "win_rate_pct": 28.365384615384613,
  "profit_factor": 0.48547537443558525,
  "avg_win_pct": 2.007865708545461,
  "avg_loss_pct": -1.707541610246353,
  "expectancy_pct": -0.6536520342429057,
  "max_consec_losses": 14,
  "avg_holding_bars": 13.971153846153847,
  "exposure_pct": 0.0,
  "turnover": 68.76380255493483,
  "commission_total": 168163.89320421152,
  "tax_total": 1286882.0743312445,
  "slippage_total": 1467352.1265889653,
  "skipped": {
   "slots_full": 875,
   "cash": 0,
   "upper_limit": 0,
   "volume_cap": 0,
   "no_data": 731
  },
  "benchmark_return_pct": 5.73334766819571,
  "excess_return_pct": -40.931113729440206,
  "beta": 0.25539856407131556
 },
 "legacy_metrics": null,
 "skipped": {
  "slots_full": 875,
  "cash": 0,
  "upper_limit": 0,
  "volume_cap": 0,
  "no_data": 731
 },
 "n_trades": 208,
 "n_closed": 208,
 "n_codes": 141,
 "n_bars": 23,
 "universe_excluded": {
  "spac": 64,
  "preferred": 7,
  "mega_cap": 2,
  "market_unknown": 0,
  "market_other": 0
 },
 "warnings": [
  "분봉 짧은 표본: 분봉이 있는 거래일 23일(<60) — 결과의 통계적 의미가 약하다",
  "분봉 거래대금(value)은 종가×거래량 근사값이다 — 분 단위에선 실제 거래대금과 크게 다를 수 있다. 사전 필터의 일봉 거래대금도 KRX 근사",
  "분봉 출처: **KRX 전용**(통합 아님) — NXT 체결이 빠져 거래량·거래대금이 통합보다 20~40% 작다(삼성전자 0.76 등, data-agent 실측). 가격은 거의 같다. 거래량·거래대금 조건의 임계값을 통합(AL) 결과와 섞어 해석하지 말 것. 15:30 종가 단일가 봉은 EOD 이후라 거래하지 않는다",
  "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
  "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)"
 ],
 "robustness": {
  "n_trades": 208,
  "cost_sensitivity": [
   {
    "mult": 0.0,
    "net_pnl": -597378.5120000263,
    "net_return_pct": -5.9737851200002625
   },
   {
    "mult": 0.5,
    "net_pnl": -2058577.5590622374,
    "net_return_pct": -20.585775590622372
   },
   {
    "mult": 1.0,
    "net_pnl": -3519776.6061244486,
    "net_return_pct": -35.19776606124449
   },
   {
    "mult": 1.5,
    "net_pnl": -4980975.65318666,
    "net_return_pct": -49.8097565318666
   },
   {
    "mult": 2.0,
    "net_pnl": -6442174.700248871,
    "net_return_pct": -64.4217470024887
   },
   {
    "mult": 3.0,
    "net_pnl": -9364572.794373294,
    "net_return_pct": -93.64572794373295
   }
  ],
  "breakeven_cost_mult": 0.0,
  "cost_sensitivity_meta": {
   "gross_before_costs": -597378.5120000263,
   "total_costs": 2922398.0941244224,
   "approximation": "같은 거래·같은 수량을 가정한 사후 계산(비용이 바뀌면 달라질 사이징·건너뜀은 미반영)"
  },
  "monte_carlo": {
   "n_sims": 1000,
   "seed": 42,
   "n_trades": 208,
   "weight": 0.2699897480769231,
   "final_return_pct": {
    "p5": -37.98623985995919,
    "p50": -30.471274365438255,
    "p95": -22.33025674837092
   },
   "max_drawdown_pct": {
    "p5": 23.33481698916464,
    "p50": 31.13309873299896,
    "p95": 38.573689873724355
   },
   "prob_mdd_gt_30": 0.608,
   "approximation": "겹친 보유 무시 — 거래를 한 줄로 세워 복리"
  },
  "concentration": {
   "total_net_pnl": -3519776.6061244486,
   "by_code": [
    {
     "k": 1,
     "removed": [
      "222800"
     ],
     "removed_pnl": 78217.79828182331,
     "net_pnl_excluding": -3597994.404406272,
     "sign_flipped": false
    },
    {
     "k": 2,
     "removed": [
      "222800",
      "024060"
     ],
     "removed_pnl": 141500.18843705783,
     "net_pnl_excluding": -3661276.7945615062,
     "sign_flipped": false
    },
    {
     "k": 3,
     "removed": [
      "222800",
      "024060",
      "096770"
     ],
     "removed_pnl": 200414.97157920126,
     "net_pnl_excluding": -3720191.5777036496,
     "sign_flipped": false
    }
   ],
   "by_date": [
    {
     "k": 1,
     "removed": [
      "2026-09-03"
     ],
     "removed_pnl": 68913.88079754772,
     "net_pnl_excluding": -3588690.4869219963,
     "sign_flipped": false
    },
    {
     "k": 2,
     "removed": [
      "2026-09-03",
      "2026-08-31"
     ],
     "removed_pnl": 133435.26372225976,
     "net_pnl_excluding": -3653211.869846708,
     "sign_flipped": false
    },
    {
     "k": 3,
     "removed": [
      "2026-09-03",
      "2026-08-31",
      "2026-09-18"
     ],
     "removed_pnl": 176938.73908646885,
     "net_pnl_excluding": -3696715.3452109173,
     "sign_flipped": false
    }
   ]
  }
 },
 "criteria": []
}, intraday: krxIntraday } })

export const krxTrades: Trade[] = [
 {
  "code": "035420",
  "name": "NAVER",
  "sector": "IT 서비스",
  "entry_ts": "2026-08-24T09:10:00",
  "entry_price": 231000.0,
  "exit_ts": "2026-08-24T09:10:00",
  "exit_price": 227035.0,
  "qty": 14,
  "gross_pnl": -55510.0,
  "commission": 961.8734999999999,
  "tax": 7310.527,
  "slippage_cost": 14000.0,
  "net_pnl": -63782.4005,
  "net_pct": -0.019722449134199134,
  "exit_reason": "stop",
  "bars_held": 1,
  "mfe_pct": 0.43290043290042934,
  "mae_pct": -1.5151515151515138
 },
 {
  "code": "041190",
  "name": "우리기술투자",
  "sector": "금융",
  "entry_ts": "2026-08-24T09:10:00",
  "entry_price": 6299.999999999999,
  "exit_ts": "2026-08-24T09:15:00",
  "exit_price": 6195.499999999999,
  "qty": 529,
  "gross_pnl": -55280.5,
  "commission": 991.5179249999998,
  "tax": 7538.064849999999,
  "slippage_cost": 10579.99999999952,
  "net_pnl": -63810.082775,
  "net_pct": -0.0191466626984127,
  "exit_reason": "stop",
  "bars_held": 2,
  "mfe_pct": 2.539682539682553,
  "mae_pct": -3.1746031746031633
 },
 {
  "code": "011070",
  "name": "LG이노텍",
  "sector": "전기/전자",
  "entry_ts": "2026-08-24T09:20:00",
  "entry_price": 567000.0,
  "exit_ts": "2026-08-24T09:20:00",
  "exit_price": 557495.0,
  "qty": 5,
  "gross_pnl": -47525.0,
  "commission": 843.3712499999999,
  "tax": 6411.1925,
  "slippage_cost": 10000.0,
  "net_pnl": -54779.563749999994,
  "net_pct": -0.019322597442680774,
  "exit_reason": "stop",
  "bars_held": 1,
  "mfe_pct": 0.0,
  "mae_pct": -1.5873015873015928
 },
 {
  "code": "017670",
  "name": "SK텔레콤",
  "sector": "통신",
  "entry_ts": "2026-08-24T09:10:00",
  "entry_price": 105004.9,
  "exit_ts": "2026-08-24T09:40:00",
  "exit_price": 103326.3966735,
  "qty": 31,
  "gross_pnl": -52033.60312149984,
  "commission": 968.7405295317749,
  "tax": 7367.17208282055,
  "slippage_cost": 6458.224621499699,
  "net_pnl": -60369.51573385216,
  "net_pct": -0.01854583674999995,
  "exit_reason": "stop",
  "bars_held": 7,
  "mfe_pct": 1.4238383161166768,
  "mae_pct": -1.5284048649158222
 },
 {
  "code": "475150",
  "name": "SK이터닉스",
  "sector": "건설",
  "entry_ts": "2026-08-24T09:45:00",
  "entry_price": 53900.0,
  "exit_ts": "2026-08-24T11:05:00",
  "exit_price": 52991.5,
  "qty": 61,
  "gross_pnl": -55418.5,
  "commission": 978.0572249999999,
  "tax": 7434.70745,
  "slippage_cost": 12200.0,
  "net_pnl": -63831.264675,
  "net_pct": -0.01941399211502783,
  "exit_reason": "stop",
  "bars_held": 17,
  "mfe_pct": 0.927643784786647,
  "mae_pct": -1.6697588126159513
 },
 {
  "code": "347850",
  "name": "디앤디파마텍",
  "sector": "일반서비스",
  "entry_ts": "2026-08-24T11:30:00",
  "entry_price": 55700.0,
  "exit_ts": "2026-08-24T11:45:00",
  "exit_price": 57271.0,
  "qty": 59,
  "gross_pnl": 92689.0,
  "commission": 999.7933499999999,
  "tax": 7771.6747,
  "slippage_cost": 11800.0,
  "net_pnl": 83917.53195,
  "net_pct": 0.02553556642728905,
  "exit_reason": "target",
  "bars_held": 4,
  "mfe_pct": 3.2315978456014305,
  "mae_pct": -0.8976660682226245
 },
 {
  "code": "347850",
  "name": "디앤디파마텍",
  "sector": "일반서비스",
  "entry_ts": "2026-08-24T11:50:00",
  "entry_price": 57200.00000000001,
  "exit_ts": "2026-08-24T12:05:00",
  "exit_price": 56242.00000000001,
  "qty": 58,
  "gross_pnl": -55564.0,
  "commission": 986.9454000000001,
  "tax": 7502.6828000000005,
  "slippage_cost": 11600.000000000422,
  "net_pnl": -64053.6282,
  "net_pct": -0.01930721853146853,
  "exit_reason": "stop",
  "bars_held": 4,
  "mfe_pct": 0.34965034965033226,
  "mae_pct": -1.7482517482517612
 },
 {
  "code": "001210",
  "name": "금호전기",
  "sector": "전기/전자",
  "entry_ts": "2026-08-24T12:10:00",
  "entry_price": 9110.0,
  "exit_ts": "2026-08-24T12:15:00",
  "exit_price": 8963.35,
  "qty": 364,
  "gross_pnl": -53380.59999999987,
  "commission": 986.8049099999998,
  "tax": 7504.11662,
  "slippage_cost": 7280.0,
  "net_pnl": -61871.52152999987,
  "net_pct": -0.018658255488474162,
  "exit_reason": "stop",
  "bars_held": 2,
  "mfe_pct": 0.658616904500553,
  "mae_pct": -2.8540065861690445
 },
 {
  "code": "006400",
  "name": "삼성SDI",
  "sector": "전기/전자",
  "entry_ts": "2026-08-24T09:15:00",
  "entry_price": 507000.0,
  "exit_ts": "2026-08-24T15:20:00",
  "exit_price": 513000.0,
  "qty": 6,
  "gross_pnl": 36000.0,
  "commission": 917.9999999999999,
  "tax": 7079.4,
  "slippage_cost": 12000.0,
  "net_pnl": 28002.6,
  "net_pct": 0.009205325443786981,
  "exit_reason": "eod",
  "bars_held": 75,
  "mfe_pct": 2.9585798816567976,
  "mae_pct": -0.39447731755424265
 },
 {
  "code": "329180",
  "name": "HD현대중공업",
  "sector": "운송장비/부품",
  "entry_ts": "2026-08-24T09:25:00",
  "entry_price": 457500.0,
  "exit_ts": "2026-08-24T15:20:00",
  "exit_price": 455000.0,
  "qty": 7,
  "gross_pnl": -17500.0,
  "commission": 958.1249999999999,
  "tax": 7325.5,
  "slippage_cost": 7000.0,
  "net_pnl": -25783.625,
  "net_pct": -0.008051092896174863,
  "exit_reason": "eod",
  "bars_held": 73,
  "mfe_pct": 1.4207650273224015,
  "mae_pct": -1.0928961748633892
 },
 {
  "code": "079550",
  "name": "LIG디펜스앤에어로스페이스",
  "sector": "금속",
  "entry_ts": "2026-08-24T12:30:00",
  "entry_price": 712000.0,
  "exit_ts": "2026-08-24T15:20:00",
  "exit_price": 716000.0,
  "qty": 4,
  "gross_pnl": 16000.0,
  "commission": 856.8,
  "tax": 6587.2,
  "slippage_cost": 8000.0,
  "net_pnl": 8556.0,
  "net_pct": 0.0030042134831460674,
  "exit_reason": "eod",
  "bars_held": 36,
  "mfe_pct": 0.7022471910112404,
  "mae_pct": -1.1235955056179803
 },
 {
  "code": "128940",
  "name": "한미약품",
  "sector": "제약",
  "entry_ts": "2026-08-26T09:10:00",
  "entry_price": 535000.0,
  "exit_ts": "2026-08-26T09:10:00",
  "exit_price": 525975.0,
  "qty": 6,
  "gross_pnl": -54150.0,
  "commission": 954.8774999999998,
  "tax": 7258.455,
  "slippage_cost": 12000.0,
  "net_pnl": -62363.332500000004,
  "net_pct": -0.019427829439252337,
  "exit_reason": "stop",
  "bars_held": 1,
  "mfe_pct": 0.0,
  "mae_pct": -3.9252336448598157
 }
]

export const tickTick: TickSummary = {
 "expected_pairs": 589,
 "used_pairs": 589,
 "days": 17,
 "codes": 173,
 "signals": 13788,
 "gap_open_days_skipped": 14,
 "signals_without_entry_tick": 0,
 "eod_time": "15:19:59"
}

export const tickDetail: RunDetail = base({ ...{
 "run_id": "20260926-081506-586d47",
 "meta": {
  "mode": "tick",
  "compat": false,
  "spec_hash": "21c0430e744beede",
  "structure_hash": "9e9fde47848c2b4b",
  "params": {},
  "data": {
   "daily": [
    "2019-04-23",
    "2026-09-23"
   ],
   "kospi": [
    "2021-07-26",
    "2026-09-23"
   ],
   "kosdaq": [
    "2021-07-26",
    "2026-09-23"
   ],
   "minute_al": [
    "2025-08-01",
    "2026-09-23"
   ],
   "minute_krx": [
    "2025-07-01",
    "2026-09-23"
   ],
   "tick_al": [
    "2026-08-04",
    "2026-09-23"
   ]
  },
  "period_used": [
   "2026-09-01",
   "2026-09-23"
  ],
  "warmup_bars": 0,
  "elapsed_sec": 68.525,
  "warnings": [
   "틱 표본: 체결 데이터가 있는 거래일 17일 · 종목 173개 — 수집 조회창이 짧아 통계적 의미가 약하다",
   "체결 파일 상당수(실측 40%)에 시각이 어긋난 줄이 있다 — 초 단위 순서는 맞고 같은 초 안 체결 순서만 불확실하다(로더가 to_grid 식 안정 정렬)",
   "틱 모드 근사: 거래량 한도 미적용, 청산가가 상하한가에 잠겨도 그 가격으로 청산(다음 날 이월 없음), bars_held 는 초 단위, 우선순위는 진입 시각 순(rank_by 무시)",
   "상하한가에 잠긴 가격으로 청산된 거래 1건 — 실제론 청산 불가였을 수 있다",
   "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
   "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)"
  ],
  "entry_source": "catalog",
  "run_id": "20260926-081506-586d47",
  "engine_version": "0.1.0",
  "git": {
   "commit": "2392556",
   "dirty": true
  },
  "created_at": "2026-09-26T08:16:17"
 },
 "spec": {
  "version": 1,
  "name": "5분 고점 돌파 틱 진입 (시연용·미검증)",
  "mode": "tick",
  "period": {
   "start": "2026-09-01",
   "end": "2026-09-23"
  },
  "universe": {
   "type": "top_value",
   "n": 35,
   "lookback_days": 1,
   "markets": [
    "거래소",
    "코스닥"
   ],
   "exclude": [
    "spac",
    "preferred",
    "mega_cap"
   ],
   "codes": []
  },
  "strategy": null,
  "market_filter": null,
  "exits": {
   "stop_loss_pct": null,
   "take_profit_pct": null,
   "trailing_stop_pct": null,
   "max_holding_bars": null
  },
  "portfolio": {
   "initial_capital": 10000000.0,
   "max_positions": 3.0,
   "sizing": "equal_slot_fixed",
   "fixed_amount": null,
   "risk_pct": null,
   "max_weight_pct": 34.0,
   "rank_by": "value",
   "random_seed": 42
  },
  "costs": {
   "commission_rate": 0.00015,
   "tax_rate": 0.0023,
   "slippage_mode": "max_rate_tick",
   "slippage_rate": 0.001,
   "slippage_ticks": 1
  },
  "fills": {
   "same_bar_policy": "stop_first",
   "volume_cap_pct": 10.0
  },
  "intraday": null,
  "tick": {
   "entry_source": "catalog",
   "catalog": {
    "breakout_min": 5,
    "value_speed": null,
    "buy_ratio": null,
    "time_from": "09:05",
    "time_to": "15:00"
   },
   "cooldown_sec": 300,
   "exclude_gap_open_pct": 5.0,
   "time_stop_sec": 600,
   "eod_time": "15:19:59"
  },
  "compat": {
   "legacy": false
  },
  "params": {},
  "validation": null
 },
 "warnings": [
  "틱 표본: 체결 데이터가 있는 거래일 17일 · 종목 173개 — 수집 조회창이 짧아 통계적 의미가 약하다",
  "체결 파일 상당수(실측 40%)에 시각이 어긋난 줄이 있다 — 초 단위 순서는 맞고 같은 초 안 체결 순서만 불확실하다(로더가 to_grid 식 안정 정렬)",
  "틱 모드 근사: 거래량 한도 미적용, 청산가가 상하한가에 잠겨도 그 가격으로 청산(다음 날 이월 없음), bars_held 는 초 단위, 우선순위는 진입 시각 순(rank_by 무시)",
  "상하한가에 잠긴 가격으로 청산된 거래 1건 — 실제론 청산 불가였을 수 있다",
  "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
  "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)"
 ],
 "analysis": {
  "monthly": [
   {
    "period": "2026-09",
    "return_pct": -95.24989403426896
   }
  ],
  "yearly": [
   {
    "period": "2026",
    "return_pct": -95.24989403426896
   }
  ],
  "exit_reasons": [
   {
    "reason": "time",
    "n": 1697,
    "share_pct": 100.0,
    "avg_net_pct": -0.566437810354713
   }
  ],
  "by_sector": [
   {
    "key": "음식료/담배",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -6918.390049999767,
    "avg_net_pct": -0.536605479148163
   },
   {
    "key": "전기/가스",
    "n": 3,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": -16619.955,
    "avg_net_pct": -0.552273456629919
   },
   {
    "key": "운송/창고",
    "n": 9,
    "win_rate_pct": 0.0,
    "net_pnl": -63801.18125000072,
    "avg_net_pct": -0.7492551777158617
   },
   {
    "key": "의료/정밀기기",
    "n": 9,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": -94823.43627999934,
    "avg_net_pct": -0.33793382770991676
   },
   {
    "key": "통신",
    "n": 10,
    "win_rate_pct": 0.0,
    "net_pnl": -103416.65749999977,
    "avg_net_pct": -0.4758592331149924
   },
   {
    "key": "금속",
    "n": 21,
    "win_rate_pct": 4.761904761904762,
    "net_pnl": -132061.59875149926,
    "avg_net_pct": -0.7008263564636354
   },
   {
    "key": "비금속",
    "n": 16,
    "win_rate_pct": 18.75,
    "net_pnl": -183551.27050000007,
    "avg_net_pct": -0.830471619017205
   },
   {
    "key": "건설",
    "n": 83,
    "win_rate_pct": 15.66265060240964,
    "net_pnl": -207145.64883423847,
    "avg_net_pct": -0.3743745851329563
   },
   {
    "key": "(미분류)",
    "n": 60,
    "win_rate_pct": 21.666666666666668,
    "net_pnl": -215411.62282649727,
    "avg_net_pct": -0.6485086589816084
   },
   {
    "key": "보험",
    "n": 26,
    "win_rate_pct": 3.8461538461538463,
    "net_pnl": -284771.85099999956,
    "avg_net_pct": -0.6825655286919322
   },
   {
    "key": "일반서비스",
    "n": 65,
    "win_rate_pct": 7.6923076923076925,
    "net_pnl": -322554.32962249906,
    "avg_net_pct": -0.5675100814284211
   },
   {
    "key": "IT 서비스",
    "n": 89,
    "win_rate_pct": 15.730337078651685,
    "net_pnl": -389272.94756099855,
    "avg_net_pct": -0.5625907728052847
   },
   {
    "key": "유통",
    "n": 73,
    "win_rate_pct": 8.21917808219178,
    "net_pnl": -567743.6698144985,
    "avg_net_pct": -0.6006911878193961
   },
   {
    "key": "화학",
    "n": 125,
    "win_rate_pct": 12.8,
    "net_pnl": -765903.2518429898,
    "avg_net_pct": -0.6113324003922275
   },
   {
    "key": "제약",
    "n": 95,
    "win_rate_pct": 17.894736842105264,
    "net_pnl": -885764.1766119977,
    "avg_net_pct": -0.6782262393269817
   },
   {
    "key": "운송장비/부품",
    "n": 113,
    "win_rate_pct": 5.3097345132743365,
    "net_pnl": -903169.1172624896,
    "avg_net_pct": -0.5714301711730181
   },
   {
    "key": "기계/장비",
    "n": 212,
    "win_rate_pct": 16.037735849056602,
    "net_pnl": -952556.2355779957,
    "avg_net_pct": -0.5714724477893722
   },
   {
    "key": "금융",
    "n": 181,
    "win_rate_pct": 4.972375690607735,
    "net_pnl": -1187453.496338485,
    "avg_net_pct": -0.5765722630568192
   },
   {
    "key": "전기/전자",
    "n": 506,
    "win_rate_pct": 17.391304347826086,
    "net_pnl": -2242050.5668027243,
    "avg_net_pct": -0.5277321151114367
   }
  ],
  "by_theme_group": [
   {
    "key": "양자",
    "n": 47,
    "win_rate_pct": 31.914893617021278,
    "net_pnl": -75157.26960799849,
    "avg_net_pct": -0.32838731252910924
   },
   {
    "key": "신재생",
    "n": 17,
    "win_rate_pct": 5.88235294117647,
    "net_pnl": -111644.5394249999,
    "avg_net_pct": -0.676775265393465
   },
   {
    "key": "5G",
    "n": 49,
    "win_rate_pct": 20.408163265306122,
    "net_pnl": -166746.50164999993,
    "avg_net_pct": -0.6267473612824954
   },
   {
    "key": "조선",
    "n": 39,
    "win_rate_pct": 7.6923076923076925,
    "net_pnl": -189813.163750001,
    "avg_net_pct": -0.6133463134420808
   },
   {
    "key": "전력",
    "n": 64,
    "win_rate_pct": 12.5,
    "net_pnl": -239728.32449349773,
    "avg_net_pct": -0.6903934986262252
   },
   {
    "key": "화장품",
    "n": 33,
    "win_rate_pct": 6.0606060606060606,
    "net_pnl": -303831.94706149964,
    "avg_net_pct": -0.7519900960145449
   },
   {
    "key": "우주",
    "n": 43,
    "win_rate_pct": 9.30232558139535,
    "net_pnl": -335258.935772494,
    "avg_net_pct": -0.640652489579682
   },
   {
    "key": "2차전지",
    "n": 53,
    "win_rate_pct": 13.20754716981132,
    "net_pnl": -431618.76525999483,
    "avg_net_pct": -0.47787008159013167
   },
   {
    "key": "원전",
    "n": 115,
    "win_rate_pct": 13.91304347826087,
    "net_pnl": -443465.84225299506,
    "avg_net_pct": -0.45503282251364546
   },
   {
    "key": "방산",
    "n": 130,
    "win_rate_pct": 15.384615384615385,
    "net_pnl": -487773.1802034939,
    "avg_net_pct": -0.44351422350355185
   },
   {
    "key": "로봇",
    "n": 105,
    "win_rate_pct": 11.428571428571429,
    "net_pnl": -689828.6014899956,
    "avg_net_pct": -0.5765382750176745
   },
   {
    "key": "데이터센터",
    "n": 113,
    "win_rate_pct": 9.734513274336283,
    "net_pnl": -789873.2035924909,
    "avg_net_pct": -0.4904240333861794
   },
   {
    "key": "반도체",
    "n": 290,
    "win_rate_pct": 18.96551724137931,
    "net_pnl": -1066679.9654079871,
    "avg_net_pct": -0.5242652005849622
   },
   {
    "key": "바이오",
    "n": 114,
    "win_rate_pct": 12.280701754385964,
    "net_pnl": -1090401.2511459985,
    "avg_net_pct": -0.6976545841776712
   },
   {
    "key": "지주사",
    "n": 222,
    "win_rate_pct": 4.954954954954955,
    "net_pnl": -1491462.9980884818,
    "avg_net_pct": -0.589770658775519
   },
   {
    "key": "(미분류)",
    "n": 263,
    "win_rate_pct": 15.5893536121673,
    "net_pnl": -1611704.9142249841,
    "avg_net_pct": -0.6439534231158254
   }
  ],
  "histogram": {
   "edges": [
    -7.320971385542169,
    -6.513065111862545,
    -5.70515883818292,
    -4.8972525645032965,
    -4.089346290823672,
    -3.281440017144048,
    -2.473533743464424,
    -1.6656274697847993,
    -0.8577211961051754,
    -0.04981492242555152,
    0.7580913512540732,
    1.565997624933697,
    2.373903898613321,
    3.181810172292945,
    3.9897164459725705,
    4.797622719652194,
    5.605528993331818,
    6.413435267011442,
    7.221341540691066,
    8.029247814370692,
    8.837154088050314
   ],
   "counts": [
    2,
    1,
    1,
    4,
    14,
    15,
    64,
    364,
    981,
    182,
    32,
    17,
    7,
    5,
    2,
    2,
    1,
    1,
    1,
    1
   ]
  }
 },
 "narration": "09:05~15:00 사이 5분 고점 돌파 이면 다음 체결에 산다.",
 "has_grid": false,
 "has_folds": false
}, summary: { ...{
 "metrics": {
  "total_return_pct": -95.24989403426896,
  "cagr_pct": -100.0,
  "max_drawdown_pct": 95.24989403426896,
  "mdd_duration_bars": 17,
  "volatility_pct": 51.60719314347176,
  "sharpe": -79.833093438374,
  "sortino": -15.58712783847214,
  "calmar": -1.0498699343856703,
  "num_trades": 1697,
  "win_rate_pct": 13.553329404832057,
  "profit_factor": 0.17330861344470885,
  "avg_win_pct": 0.8627386565062107,
  "avg_loss_pct": -0.7905077404010746,
  "expectancy_pct": -0.566437810354713,
  "max_consec_losses": 38,
  "avg_holding_bars": 601.1909251620507,
  "exposure_pct": 0.0,
  "turnover": 602.1811861529559,
  "commission_total": 493451.6863589999,
  "tax_total": 3777086.977068,
  "slippage_total": 4296888.739999913,
  "skipped": {
   "slots_full": 11787,
   "cash": 304,
   "upper_limit": 0,
   "volume_cap": 0,
   "no_data": 0
  },
  "benchmark_return_pct": 3.585827554931398,
  "excess_return_pct": -98.83572158920036,
  "beta": 0.5283863685306585
 },
 "legacy_metrics": null,
 "skipped": {
  "slots_full": 11787,
  "cash": 304,
  "upper_limit": 0,
  "volume_cap": 0,
  "no_data": 0
 },
 "n_trades": 1697,
 "n_closed": 1697,
 "n_codes": 173,
 "n_bars": 17,
 "universe_excluded": {
  "spac": 64,
  "preferred": 7,
  "mega_cap": 2,
  "market_unknown": 0,
  "market_other": 0
 },
 "warnings": [
  "틱 표본: 체결 데이터가 있는 거래일 17일 · 종목 173개 — 수집 조회창이 짧아 통계적 의미가 약하다",
  "체결 파일 상당수(실측 40%)에 시각이 어긋난 줄이 있다 — 초 단위 순서는 맞고 같은 초 안 체결 순서만 불확실하다(로더가 to_grid 식 안정 정렬)",
  "틱 모드 근사: 거래량 한도 미적용, 청산가가 상하한가에 잠겨도 그 가격으로 청산(다음 날 이월 없음), bars_held 는 초 단위, 우선순위는 진입 시각 순(rank_by 무시)",
  "상하한가에 잠긴 가격으로 청산된 거래 1건 — 실제론 청산 불가였을 수 있다",
  "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
  "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)"
 ],
 "robustness": {
  "n_trades": 1697,
  "cost_sensitivity": [
   {
    "mult": 0.0,
    "net_pnl": -957562.0,
    "net_return_pct": -9.57562
   },
   {
    "mult": 0.5,
    "net_pnl": -5241275.701713457,
    "net_return_pct": -52.41275701713457
   },
   {
    "mult": 1.0,
    "net_pnl": -9524989.403426914,
    "net_return_pct": -95.24989403426913
   },
   {
    "mult": 1.5,
    "net_pnl": -13808703.10514037,
    "net_return_pct": -138.0870310514037
   },
   {
    "mult": 2.0,
    "net_pnl": -18092416.806853827,
    "net_return_pct": -180.92416806853825
   },
   {
    "mult": 3.0,
    "net_pnl": -26659844.21028074,
    "net_return_pct": -266.5984421028074
   }
  ],
  "breakeven_cost_mult": 0.0,
  "cost_sensitivity_meta": {
   "gross_before_costs": -957562.0,
   "total_costs": 8567427.403426914,
   "approximation": "같은 거래·같은 수량을 가정한 사후 계산(비용이 바뀌면 달라질 사이징·건너뜀은 미반영)"
  },
  "monte_carlo": {
   "n_sims": 1000,
   "seed": 42,
   "n_trades": 1697,
   "weight": 0.09708109486741308,
   "final_return_pct": {
    "p5": -63.0615053785779,
    "p50": -60.69200916577527,
    "p95": -58.20791301986099
   },
   "max_drawdown_pct": {
    "p5": 58.23849761801686,
    "p50": 60.715237081594566,
    "p95": 63.0615053785779
   },
   "prob_mdd_gt_30": 1.0,
   "approximation": "겹친 보유 무시 — 거래를 한 줄로 세워 복리"
  },
  "concentration": {
   "total_net_pnl": -9524989.403426914,
   "by_code": [
    {
     "k": 1,
     "removed": [
      "032820"
     ],
     "removed_pnl": 24557.632971000803,
     "net_pnl_excluding": -9549547.036397913,
     "sign_flipped": false
    },
    {
     "k": 2,
     "removed": [
      "032820",
      "032940"
     ],
     "removed_pnl": 44278.02397100079,
     "net_pnl_excluding": -9569267.427397914,
     "sign_flipped": false
    },
    {
     "k": 3,
     "removed": [
      "032820",
      "032940",
      "131290"
     ],
     "removed_pnl": 58304.473971000785,
     "net_pnl_excluding": -9583293.877397913,
     "sign_flipped": false
    }
   ],
   "by_date": [
    {
     "k": 1,
     "removed": [
      "2026-09-23"
     ],
     "removed_pnl": -70006.17176299899,
     "net_pnl_excluding": -9454983.231663914,
     "sign_flipped": false
    },
    {
     "k": 2,
     "removed": [
      "2026-09-23",
      "2026-09-22"
     ],
     "removed_pnl": -182386.53446549817,
     "net_pnl_excluding": -9342602.868961416,
     "sign_flipped": false
    },
    {
     "k": 3,
     "removed": [
      "2026-09-23",
      "2026-09-22",
      "2026-09-21"
     ],
     "removed_pnl": -313327.5892204968,
     "net_pnl_excluding": -9211661.814206418,
     "sign_flipped": false
    }
   ]
  }
 },
 "criteria": []
}, tick: tickTick } })

export const tickTrades: Trade[] = [
 {
  "code": "086790",
  "name": "하나금융지주",
  "sector": "금융",
  "entry_ts": "2026-09-01T09:05:01",
  "entry_price": 137437.3,
  "exit_ts": "2026-09-01T09:15:06",
  "exit_price": 137062.8,
  "qty": 24,
  "gross_pnl": -8988.0,
  "commission": 988.2003599999998,
  "tax": 7565.8665599999995,
  "slippage_cost": 6588.0,
  "net_pnl": -17542.066919999997,
  "net_pct": -0.005318202955092976,
  "exit_reason": "time",
  "bars_held": 605,
  "mfe_pct": 0.3366626090588243,
  "mae_pct": -0.5364628088590173
 },
 {
  "code": "105560",
  "name": "KB금융",
  "sector": "금융",
  "entry_ts": "2026-09-01T09:05:01",
  "entry_price": 172572.4,
  "exit_ts": "2026-09-01T09:15:01",
  "exit_price": 171328.5,
  "qty": 19,
  "gross_pnl": -23634.09999999989,
  "commission": 980.1175649999999,
  "tax": 7487.05545,
  "slippage_cost": 6534.099999999889,
  "net_pnl": -32101.27301499989,
  "net_pct": -0.009790329652945629,
  "exit_reason": "time",
  "bars_held": 600,
  "mfe_pct": 0.07393998113256472,
  "mae_pct": -0.9111538113858231
 },
 {
  "code": "055550",
  "name": "신한지주",
  "sector": "금융",
  "entry_ts": "2026-09-01T09:05:03",
  "entry_price": 111411.29999999999,
  "exit_ts": "2026-09-01T09:15:03",
  "exit_price": 110289.6,
  "qty": 29,
  "gross_pnl": -32529.299999999494,
  "commission": 964.398915,
  "tax": 7356.316320000001,
  "slippage_cost": 6429.299999999494,
  "net_pnl": -40850.01523499949,
  "net_pct": -0.01264343217429455,
  "exit_reason": "time",
  "bars_held": 600,
  "mfe_pct": -0.09990009990008542,
  "mae_pct": -1.1769901257771775
 },
 {
  "code": "373220",
  "name": "LG에너지솔루션",
  "sector": "전기/전자",
  "entry_ts": "2026-09-01T09:15:02",
  "entry_price": 374499.99999999994,
  "exit_ts": "2026-09-01T09:25:02",
  "exit_price": 380750.0,
  "qty": 8,
  "gross_pnl": 50000.000000000466,
  "commission": 906.2999999999998,
  "tax": 7005.8,
  "slippage_cost": 7999.999999999534,
  "net_pnl": 42087.90000000046,
  "net_pct": 0.014048030707610303,
  "exit_reason": "time",
  "bars_held": 600,
  "mfe_pct": 2.1361815754339375,
  "mae_pct": -0.26702269692922
 },
 {
  "code": "066570",
  "name": "LG전자",
  "sector": "전기/전자",
  "entry_ts": "2026-09-01T09:15:38",
  "entry_price": 208000.00000000003,
  "exit_ts": "2026-09-01T09:25:38",
  "exit_price": 206500.0,
  "qty": 16,
  "gross_pnl": -24000.000000000466,
  "commission": 994.8,
  "tax": 7599.2,
  "slippage_cost": 16000.000000000466,
  "net_pnl": -32594.000000000466,
  "net_pct": -0.00979387019230783,
  "exit_reason": "time",
  "bars_held": 600,
  "mfe_pct": -1.1102230246251565e-14,
  "mae_pct": -0.9615384615384803
 },
 {
  "code": "035420",
  "name": "NAVER",
  "sector": "IT 서비스",
  "entry_ts": "2026-09-01T09:15:44",
  "entry_price": 217000.00000000003,
  "exit_ts": "2026-09-01T09:25:44",
  "exit_price": 216500.0,
  "qty": 15,
  "gross_pnl": -7500.000000000437,
  "commission": 975.375,
  "tax": 7469.25,
  "slippage_cost": 15000.000000000437,
  "net_pnl": -15944.625000000437,
  "net_pct": -0.0048985023041475985,
  "exit_reason": "time",
  "bars_held": 600,
  "mfe_pct": 0.6912442396313168,
  "mae_pct": -0.4608294930875667
 },
 {
  "code": "080220",
  "name": "제주반도체",
  "sector": "전기/전자",
  "entry_ts": "2026-09-01T09:25:26",
  "entry_price": 80800.0,
  "exit_ts": "2026-09-01T09:35:26",
  "exit_price": 80100.0,
  "qty": 41,
  "gross_pnl": -28700.0,
  "commission": 989.5349999999999,
  "tax": 7553.43,
  "slippage_cost": 8200.0,
  "net_pnl": -37242.965,
  "net_pct": -0.01124214108910891,
  "exit_reason": "time",
  "bars_held": 600,
  "mfe_pct": 0.866336633663356,
  "mae_pct": -0.990099009900991
 },
 {
  "code": "011070",
  "name": "LG이노텍",
  "sector": "전기/전자",
  "entry_ts": "2026-09-01T09:25:40",
  "entry_price": 603000.0,
  "exit_ts": "2026-09-01T09:35:40",
  "exit_price": 600000.0,
  "qty": 5,
  "gross_pnl": -15000.0,
  "commission": 902.2499999999999,
  "tax": 6900.0,
  "slippage_cost": 10000.0,
  "net_pnl": -22802.25,
  "net_pct": -0.007562935323383085,
  "exit_reason": "time",
  "bars_held": 600,
  "mfe_pct": 0.24875621890547706,
  "mae_pct": -0.497512437810943
 },
 {
  "code": "000150",
  "name": "두산",
  "sector": "전기/전자",
  "entry_ts": "2026-09-01T09:25:56",
  "entry_price": 1212210.9999999998,
  "exit_ts": "2026-09-01T09:35:59",
  "exit_price": 1208790.0,
  "qty": 2,
  "gross_pnl": -6841.999999999534,
  "commission": 726.3002999999999,
  "tax": 5560.434,
  "slippage_cost": 4841.999999999534,
  "net_pnl": -13128.734299999534,
  "net_pct": -0.005415201767678868,
  "exit_reason": "time",
  "bars_held": 603,
  "mfe_pct": 0.6425449034862973,
  "mae_pct": -0.34738176769554263
 },
 {
  "code": "055550",
  "name": "신한지주",
  "sector": "금융",
  "entry_ts": "2026-09-01T09:35:34",
  "entry_price": 112011.9,
  "exit_ts": "2026-09-01T09:45:34",
  "exit_price": 110689.2,
  "qty": 29,
  "gross_pnl": -38358.299999999916,
  "commission": 968.7497849999999,
  "tax": 7382.969639999999,
  "slippage_cost": 6458.299999999916,
  "net_pnl": -46710.01942499992,
  "net_pct": -0.014379635779769804,
  "exit_reason": "time",
  "bars_held": 600,
  "mfe_pct": -0.09990009990009652,
  "mae_pct": -1.1265767297938822
 },
 {
  "code": "000270",
  "name": "기아",
  "sector": "운송장비/부품",
  "entry_ts": "2026-09-01T09:35:44",
  "entry_price": 132232.09999999998,
  "exit_ts": "2026-09-01T09:45:44",
  "exit_price": 131768.1,
  "qty": 25,
  "gross_pnl": -11599.999999999272,
  "commission": 990.0007499999999,
  "tax": 7576.66575,
  "slippage_cost": 6599.999999999272,
  "net_pnl": -20166.66649999927,
  "net_pct": -0.0061003845511034835,
  "exit_reason": "time",
  "bars_held": 600,
  "mfe_pct": -0.09990009990008542,
  "mae_pct": -0.40239850989280956
 },
 {
  "code": "066970",
  "name": "엘앤에프",
  "sector": "전기/전자",
  "entry_ts": "2026-09-01T09:36:02",
  "entry_price": 145945.8,
  "exit_ts": "2026-09-01T09:46:02",
  "exit_price": 145354.5,
  "qty": 22,
  "gross_pnl": -13008.599999999744,
  "commission": 961.2909899999999,
  "tax": 7354.9376999999995,
  "slippage_cost": 6408.599999999744,
  "net_pnl": -21324.828689999744,
  "net_pct": -0.006641577866577788,
  "exit_reason": "time",
  "bars_held": 600,
  "mfe_pct": 0.927878705656493,
  "mae_pct": -1.333234666567995
 }
]

export const refineIntraday: IntradaySummary = {
 "expected_pairs": 510,
 "used_pairs": 390,
 "pairs_share": 0.7647058823529411,
 "days_with_bars": 17,
 "days_in_period": 17,
 "codes_requested": 123,
 "codes_with_minutes": 119,
 "codes_without_minutes": [
  "0011A0",
  "0126Z0",
  "0161M0",
  "386380"
 ],
 "warmup_days": 8,
 "bar_minutes": 5,
 "minute_source": "al",
 "code_periods": {
  "000150": [
   "2026-08-21",
   "2026-09-18"
  ],
  "000270": [
   "2026-08-24",
   "2026-09-18"
  ],
  "000500": [
   "2026-08-07",
   "2026-09-04"
  ],
  "000720": [
   "2026-08-24",
   "2026-09-18"
  ],
  "000810": [
   "2026-08-13",
   "2026-09-18"
  ],
  "000990": [
   "2026-08-24",
   "2026-09-18"
  ],
  "001210": [
   "2026-08-04",
   "2026-09-18"
  ],
  "001440": [
   "2026-08-04",
   "2026-09-18"
  ]
 }
}

export const refineRefine: TickRefineSummary = {
 "n_trades": 160,
 "n_refined": 160,
 "n_without_ticks": 0,
 "n_no_matching_tick": 0,
 "entry_diff_pct": {
  "mean": 0.0,
  "median": 0.0,
  "p5": 0.0,
  "p95": 0.0,
  "n": 160
 },
 "exit_diff_pct": {
  "mean": -0.028430677647290903,
  "median": -0.01774867420305526,
  "p5": -0.14163712974039233,
  "p95": 0.07993646115651448,
  "n": 160
 },
 "net_pnl_bar": -3318657.021166619,
 "net_pnl_tick": -3439533.6533074765,
 "definition": "diff = 틱 기준가 ÷ 봉 기준가 − 1 (슬리피지 전). 진입·시그널 청산=봉이 끝난 시각 이후 첫 체결, 선 청산=봉 안에서 선을 처음 넘은 체결, 종가 청산=봉의 마지막 체결. net_pnl_tick 은 같은 비용 모델로 다시 계산(정밀화된 거래만)."
}

export const refineDetail: RunDetail = base({ ...{
 "run_id": "20260926-081619-7a32aa",
 "meta": {
  "mode": "tick",
  "compat": false,
  "spec_hash": "7dedae1991760991",
  "structure_hash": "b0ba1158a295b1df",
  "params": {},
  "data": {
   "daily": [
    "2019-04-23",
    "2026-09-23"
   ],
   "kospi": [
    "2021-07-26",
    "2026-09-23"
   ],
   "kosdaq": [
    "2021-07-26",
    "2026-09-23"
   ],
   "minute_al": [
    "2025-08-01",
    "2026-09-23"
   ],
   "minute_krx": [
    "2025-07-01",
    "2026-09-23"
   ],
   "tick_al": [
    "2026-08-04",
    "2026-09-23"
   ]
  },
  "period_used": [
   "2026-09-01",
   "2026-09-23"
  ],
  "warmup_bars": 8,
  "elapsed_sec": 20.37,
  "warnings": [
   "분봉 커버리지: 기대 (날짜,종목) 510쌍 중 390쌍만 분봉이 있어 나머지는 거래 기회가 없었다(76%) — 종목별 보관 기간이 다르다",
   "분봉 짧은 표본: 분봉이 있는 거래일 17일(<60) — 결과의 통계적 의미가 약하다",
   "분봉 거래대금(value)은 종가×거래량 근사값이다 — 분 단위에선 실제 거래대금과 크게 다를 수 있다. 사전 필터의 일봉 거래대금도 KRX 근사",
   "분봉 출처: 통합(AL) 보관소(정규장 09:00~15:30, NXT 체결 포함). 15:30 종가 단일가 봉은 EOD 이후라 거래하지 않는다",
   "체결 파일 상당수(실측 40%)에 시각이 어긋난 줄이 있어 같은 초 안 체결 순서는 원본 그대로라 불확실하다(초 단위 순서는 맞음)",
   "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
   "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)"
  ],
  "minute_source": "al",
  "bar_minutes": 5,
  "eod_time": "15:20",
  "prefilter_top_value": 30,
  "run_id": "20260926-081619-7a32aa",
  "engine_version": "0.1.0",
  "git": {
   "commit": "2392556",
   "dirty": true
  },
  "created_at": "2026-09-26T08:16:42"
 },
 "spec": {
  "version": 1,
  "name": "틱 정밀화 스모크",
  "mode": "tick",
  "period": {
   "start": "2026-09-01",
   "end": "2026-09-23"
  },
  "universe": {
   "type": "top_value",
   "n": 100,
   "lookback_days": 1,
   "markets": [
    "거래소",
    "코스닥"
   ],
   "exclude": [
    "spac",
    "preferred",
    "mega_cap"
   ],
   "codes": []
  },
  "strategy": {
   "source": "builder",
   "entry": {
    "logic": "all",
    "items": [
     {
      "left": {
       "kind": "field",
       "name": "close",
       "offset": 0,
       "mul": 1.0
      },
      "op": "gt",
      "right": {
       "kind": "ind",
       "name": "highest",
       "params": {
        "src": "high",
        "n": 20
       },
       "offset": 0,
       "mul": 1.0
      }
     }
    ]
   },
   "exit": {
    "logic": "any",
    "items": []
   }
  },
  "market_filter": null,
  "exits": {
   "stop_loss_pct": 1.5,
   "take_profit_pct": 3.0,
   "trailing_stop_pct": null,
   "max_holding_bars": null
  },
  "portfolio": {
   "initial_capital": 10000000.0,
   "max_positions": 3.0,
   "sizing": "equal_slot_fixed",
   "fixed_amount": null,
   "risk_pct": null,
   "max_weight_pct": 34.0,
   "rank_by": "value",
   "random_seed": 42
  },
  "costs": {
   "commission_rate": 0.00015,
   "tax_rate": 0.0023,
   "slippage_mode": "max_rate_tick",
   "slippage_rate": 0.001,
   "slippage_ticks": 1
  },
  "fills": {
   "same_bar_policy": "stop_first",
   "volume_cap_pct": 10.0
  },
  "intraday": {
   "bar_minutes": 5,
   "source": "al",
   "prefilter": null,
   "prefilter_top_value": 30,
   "eod_time": "15:20"
  },
  "tick": {
   "entry_source": "minute_refine",
   "catalog": {
    "breakout_min": 5,
    "value_speed": null,
    "buy_ratio": null,
    "time_from": "09:05",
    "time_to": "15:00"
   },
   "cooldown_sec": 300,
   "exclude_gap_open_pct": 5.0,
   "time_stop_sec": 600,
   "eod_time": "15:19:59"
  },
  "compat": {
   "legacy": false
  },
  "params": {},
  "validation": null
 },
 "warnings": [
  "분봉 커버리지: 기대 (날짜,종목) 510쌍 중 390쌍만 분봉이 있어 나머지는 거래 기회가 없었다(76%) — 종목별 보관 기간이 다르다",
  "분봉 짧은 표본: 분봉이 있는 거래일 17일(<60) — 결과의 통계적 의미가 약하다",
  "분봉 거래대금(value)은 종가×거래량 근사값이다 — 분 단위에선 실제 거래대금과 크게 다를 수 있다. 사전 필터의 일봉 거래대금도 KRX 근사",
  "분봉 출처: 통합(AL) 보관소(정규장 09:00~15:30, NXT 체결 포함). 15:30 종가 단일가 봉은 EOD 이후라 거래하지 않는다",
  "체결 파일 상당수(실측 40%)에 시각이 어긋난 줄이 있어 같은 초 안 체결 순서는 원본 그대로라 불확실하다(초 단위 순서는 맞음)",
  "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
  "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)"
 ],
 "analysis": {
  "monthly": [
   {
    "period": "2026-09",
    "return_pct": -33.18657021166619
   }
  ],
  "yearly": [
   {
    "period": "2026",
    "return_pct": -33.18657021166619
   }
  ],
  "exit_reasons": [
   {
    "reason": "stop",
    "n": 103,
    "share_pct": 64.375,
    "avg_net_pct": -1.8839916249407185
   },
   {
    "reason": "target",
    "n": 30,
    "share_pct": 18.75,
    "avg_net_pct": 2.606307964518
   },
   {
    "reason": "eod",
    "n": 27,
    "share_pct": 16.875,
    "avg_net_pct": -0.24878282797896228
   }
  ],
  "by_sector": [
   {
    "key": "금속",
    "n": 2,
    "win_rate_pct": 50.0,
    "net_pnl": -32911.923070000135,
    "avg_net_pct": -0.5942108398131346
   },
   {
    "key": "비금속",
    "n": 3,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": -40984.807514999586,
    "avg_net_pct": -0.3837781883881839
   },
   {
    "key": "운송/창고",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -59850.774424999996,
    "avg_net_pct": -1.917740857605178
   },
   {
    "key": "일반서비스",
    "n": 9,
    "win_rate_pct": 22.22222222222222,
    "net_pnl": -69973.86237734315,
    "avg_net_pct": -0.20343814503616292
   },
   {
    "key": "IT 서비스",
    "n": 10,
    "win_rate_pct": 30.0,
    "net_pnl": -114077.57109101667,
    "avg_net_pct": -0.5046292232823579
   },
   {
    "key": "화학",
    "n": 10,
    "win_rate_pct": 30.0,
    "net_pnl": -149443.16780529745,
    "avg_net_pct": -0.5310707580268563
   },
   {
    "key": "유통",
    "n": 10,
    "win_rate_pct": 20.0,
    "net_pnl": -175737.97868823403,
    "avg_net_pct": -0.7521293183545904
   },
   {
    "key": "제약",
    "n": 14,
    "win_rate_pct": 28.57142857142857,
    "net_pnl": -244877.4640448718,
    "avg_net_pct": -0.5957535527760955
   },
   {
    "key": "건설",
    "n": 5,
    "win_rate_pct": 0.0,
    "net_pnl": -292683.49548187834,
    "avg_net_pct": -1.9113151509562796
   },
   {
    "key": "금융",
    "n": 27,
    "win_rate_pct": 37.03703703703704,
    "net_pnl": -310889.4530155255,
    "avg_net_pct": -0.4723709539278759
   },
   {
    "key": "운송장비/부품",
    "n": 8,
    "win_rate_pct": 0.0,
    "net_pnl": -358585.94797499955,
    "avg_net_pct": -1.7905795048745101
   },
   {
    "key": "기계/장비",
    "n": 24,
    "win_rate_pct": 25.0,
    "net_pnl": -480388.25654391875,
    "avg_net_pct": -0.7558594039862626
   },
   {
    "key": "전기/전자",
    "n": 37,
    "win_rate_pct": 18.91891891891892,
    "net_pnl": -988252.3191335329,
    "avg_net_pct": -0.9593486054070457
   }
  ],
  "by_theme_group": [
   {
    "key": "우주",
    "n": 4,
    "win_rate_pct": 50.0,
    "net_pnl": -10992.961074999886,
    "avg_net_pct": 0.042206682921271936
   },
   {
    "key": "화장품",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -45648.14598638545,
    "avg_net_pct": -1.8545836750000002
   },
   {
    "key": "신재생",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -57737.883499999996,
    "avg_net_pct": -1.951923039215686
   },
   {
    "key": "원전",
    "n": 12,
    "win_rate_pct": 41.66666666666667,
    "net_pnl": -58774.36226226157,
    "avg_net_pct": -0.11589484073483607
   },
   {
    "key": "데이터센터",
    "n": 8,
    "win_rate_pct": 25.0,
    "net_pnl": -61852.66180692622,
    "avg_net_pct": -0.2996487648045517
   },
   {
    "key": "양자",
    "n": 9,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": -78992.68359101619,
    "avg_net_pct": -0.3890992323547397
   },
   {
    "key": "전력",
    "n": 2,
    "win_rate_pct": 0.0,
    "net_pnl": -89725.37391827999,
    "avg_net_pct": -1.8545836749999978
   },
   {
    "key": "2차전지",
    "n": 5,
    "win_rate_pct": 20.0,
    "net_pnl": -156074.45525,
    "avg_net_pct": -1.009428319819279
   },
   {
    "key": "5G",
    "n": 6,
    "win_rate_pct": 16.666666666666664,
    "net_pnl": -185852.59656000027,
    "avg_net_pct": -1.1415228393865717
   },
   {
    "key": "조선",
    "n": 4,
    "win_rate_pct": 0.0,
    "net_pnl": -191128.08687499998,
    "avg_net_pct": -1.8628859209489423
   },
   {
    "key": "(미분류)",
    "n": 17,
    "win_rate_pct": 29.411764705882355,
    "net_pnl": -196369.59221400865,
    "avg_net_pct": -0.5262069930912553
   },
   {
    "key": "바이오",
    "n": 13,
    "win_rate_pct": 23.076923076923077,
    "net_pnl": -248826.0249606539,
    "avg_net_pct": -0.6885417083266273
   },
   {
    "key": "로봇",
    "n": 12,
    "win_rate_pct": 16.666666666666664,
    "net_pnl": -272848.81625,
    "avg_net_pct": -0.9015619432885172
   },
   {
    "key": "지주사",
    "n": 32,
    "win_rate_pct": 31.25,
    "net_pnl": -518587.773980417,
    "avg_net_pct": -0.6251334440077648
   },
   {
    "key": "반도체",
    "n": 18,
    "win_rate_pct": 16.666666666666664,
    "net_pnl": -544515.3996673679,
    "avg_net_pct": -1.1180777735061458
   },
   {
    "key": "방산",
    "n": 16,
    "win_rate_pct": 12.5,
    "net_pnl": -600730.2032693006,
    "avg_net_pct": -1.2343480810611176
   }
  ],
  "histogram": {
   "edges": [
    -1.9972791062801933,
    -1.7659200334661829,
    -1.5345609606521724,
    -1.3032018878381622,
    -1.0718428150241517,
    -0.8404837422101412,
    -0.609124669396131,
    -0.3777655965821205,
    -0.14640652376811003,
    0.08495254904590022,
    0.3163116218599109,
    0.5476706946739212,
    0.7790297674879314,
    1.010388840301942,
    1.2417479131159523,
    1.473106985929963,
    1.7044660587439733,
    1.9358251315579835,
    2.1671842043719938,
    2.398543277186005,
    2.6299023500000156
   ],
   "counts": [
    103,
    1,
    1,
    2,
    4,
    3,
    3,
    4,
    0,
    2,
    1,
    3,
    0,
    0,
    3,
    0,
    0,
    0,
    0,
    30
   ]
  }
 },
 "narration": "종가가 20봉 최고가를 넘면 다음 봉 시가에 산다.\n※ 분봉 N봉 지표(이동평균·최고가 등)는 전날 봉을 포함해 계산하므로 장 시작 직후 신호는 전날 흐름의 영향을 받는다.\n청산 규칙: 손절 -1.5%, 익절 +3%.",
 "has_grid": false,
 "has_folds": false
}, summary: { ...{
 "metrics": {
  "total_return_pct": -33.18657021166619,
  "cagr_pct": -99.74656716081873,
  "max_drawdown_pct": 33.18657021166619,
  "mdd_duration_bars": 17,
  "volatility_pct": 45.89442447039256,
  "sharpe": -12.647169357007327,
  "sortino": -10.094058491696423,
  "calmar": -3.0056304862065706,
  "num_trades": 160,
  "win_rate_pct": 24.375,
  "profit_factor": 0.41262200776854496,
  "avg_win_pct": 2.1890320286056344,
  "avg_loss_pct": -1.718605652102526,
  "expectancy_pct": -0.7661189674299124,
  "max_consec_losses": 15,
  "avg_holding_bars": 14.4,
  "exposure_pct": 0.0,
  "turnover": 54.60409797963895,
  "commission_total": 129377.914247585,
  "tax_total": 989367.4441526367,
  "slippage_total": 1120691.1341663762,
  "skipped": {
   "slots_full": 585,
   "cash": 0,
   "upper_limit": 0,
   "volume_cap": 0,
   "no_data": 208
  },
  "benchmark_return_pct": 3.585827554931398,
  "excess_return_pct": -36.772397766597585,
  "beta": 0.10001350472760355
 },
 "legacy_metrics": null,
 "skipped": {
  "slots_full": 585,
  "cash": 0,
  "upper_limit": 0,
  "volume_cap": 0,
  "no_data": 208
 },
 "n_trades": 160,
 "n_closed": 160,
 "n_codes": 119,
 "n_bars": 17,
 "universe_excluded": {
  "spac": 64,
  "preferred": 7,
  "mega_cap": 2,
  "market_unknown": 0,
  "market_other": 0
 },
 "warnings": [
  "분봉 커버리지: 기대 (날짜,종목) 510쌍 중 390쌍만 분봉이 있어 나머지는 거래 기회가 없었다(76%) — 종목별 보관 기간이 다르다",
  "분봉 짧은 표본: 분봉이 있는 거래일 17일(<60) — 결과의 통계적 의미가 약하다",
  "분봉 거래대금(value)은 종가×거래량 근사값이다 — 분 단위에선 실제 거래대금과 크게 다를 수 있다. 사전 필터의 일봉 거래대금도 KRX 근사",
  "분봉 출처: 통합(AL) 보관소(정규장 09:00~15:30, NXT 체결 포함). 15:30 종가 단일가 봉은 EOD 이후라 거래하지 않는다",
  "체결 파일 상당수(실측 40%)에 시각이 어긋난 줄이 있어 같은 초 안 체결 순서는 원본 그대로라 불확실하다(초 단위 순서는 맞음)",
  "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
  "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)"
 ],
 "robustness": {
  "n_trades": 160,
  "cost_sensitivity": [
   {
    "mult": 0.0,
    "net_pnl": -1079220.5286000199,
    "net_return_pct": -10.792205286000199
   },
   {
    "mult": 0.5,
    "net_pnl": -2198938.7748833187,
    "net_return_pct": -21.989387748833185
   },
   {
    "mult": 1.0,
    "net_pnl": -3318657.0211666175,
    "net_return_pct": -33.18657021166618
   },
   {
    "mult": 1.5,
    "net_pnl": -4438375.267449916,
    "net_return_pct": -44.38375267449916
   },
   {
    "mult": 2.0,
    "net_pnl": -5558093.513733216,
    "net_return_pct": -55.580935137332155
   },
   {
    "mult": 3.0,
    "net_pnl": -7797530.006299812,
    "net_return_pct": -77.97530006299812
   }
  ],
  "breakeven_cost_mult": 0.0,
  "cost_sensitivity_meta": {
   "gross_before_costs": -1079220.5286000199,
   "total_costs": 2239436.4925665976,
   "approximation": "같은 거래·같은 수량을 가정한 사후 계산(비용이 바뀌면 달라질 사이징·건너뜀은 미반영)"
  },
  "monte_carlo": {
   "n_sims": 1000,
   "seed": 42,
   "n_trades": 160,
   "weight": 0.27022479374374997,
   "final_return_pct": {
    "p5": -34.9413963206249,
    "p50": -28.30680628579153,
    "p95": -20.82317381458873
   },
   "max_drawdown_pct": {
    "p5": 21.988261672816847,
    "p50": 28.999046220565,
    "p95": 35.24993110557816
   },
   "prob_mdd_gt_30": 0.402,
   "approximation": "겹친 보유 무시 — 거래를 한 줄로 세워 복리"
  },
  "concentration": {
   "total_net_pnl": -3318657.021166618,
   "by_code": [
    {
     "k": 1,
     "removed": [
      "272210"
     ],
     "removed_pnl": 59474.37595,
     "net_pnl_excluding": -3378131.3971166178,
     "sign_flipped": false
    },
    {
     "k": 2,
     "removed": [
      "272210",
      "298040"
     ],
     "removed_pnl": 101966.37395000047,
     "net_pnl_excluding": -3420623.3951166184,
     "sign_flipped": false
    },
    {
     "k": 3,
     "removed": [
      "272210",
      "298040",
      "203650"
     ],
     "removed_pnl": 140115.7498627506,
     "net_pnl_excluding": -3458772.7710293685,
     "sign_flipped": false
    }
   ],
   "by_date": [
    {
     "k": 1,
     "removed": [
      "2026-09-03"
     ],
     "removed_pnl": 90872.94396039912,
     "net_pnl_excluding": -3409529.965127017,
     "sign_flipped": false
    },
    {
     "k": 2,
     "removed": [
      "2026-09-03",
      "2026-09-18"
     ],
     "removed_pnl": 57349.217476145335,
     "net_pnl_excluding": -3376006.2386427633,
     "sign_flipped": false
    },
    {
     "k": 3,
     "removed": [
      "2026-09-03",
      "2026-09-18",
      "2026-09-23"
     ],
     "removed_pnl": 16103.808976145338,
     "net_pnl_excluding": -3334760.8301427634,
     "sign_flipped": false
    }
   ]
  }
 },
 "criteria": []
}, intraday: refineIntraday, tick_refine: refineRefine } })

export const refineTrades: Trade[] = [
 {
  "code": "001210",
  "name": "금호전기",
  "sector": "전기/전자",
  "entry_ts": "2026-09-01T09:10:00",
  "entry_price": 13713.699999999999,
  "exit_ts": "2026-09-01T09:10:00",
  "exit_price": 14110.985889,
  "qty": 243,
  "gross_pnl": 96540.47102700017,
  "commission": 1014.2098006540499,
  "tax": 7886.6300133621,
  "slippage_cost": 6761.501972999584,
  "net_pnl": 87639.63121298402,
  "net_pct": 0.026299023500000053,
  "exit_reason": "target",
  "bars_held": 1,
  "mfe_pct": 4.639885661783483,
  "mae_pct": -0.6832583474919107,
  "entry_ref_bar": 13700.0,
  "entry_ref_tick": 13700.0,
  "entry_diff_pct": 0.0,
  "exit_ref_bar": 14125.110999999999,
  "exit_ref_tick": 14130.0,
  "exit_diff_pct": 0.034612117384424934,
  "net_pnl_tick": 88823.56243050047,
  "net_pct_tick": 0.026654299240905226,
  "tick_refined": true
 },
 {
  "code": "028300",
  "name": "HLB",
  "sector": "제약",
  "entry_ts": "2026-09-01T09:10:00",
  "entry_price": 37425.0,
  "exit_ts": "2026-09-01T09:10:00",
  "exit_price": 36813.625,
  "qty": 89,
  "gross_pnl": -54412.375,
  "commission": 991.0856437499999,
  "tax": 7535.7490375,
  "slippage_cost": 8900.0,
  "net_pnl": -62939.209681249995,
  "net_pct": -0.018895982130928524,
  "exit_reason": "stop",
  "bars_held": 1,
  "mfe_pct": 0.2004008016031955,
  "mae_pct": -2.0708082832331276,
  "entry_ref_bar": 37375.0,
  "entry_ref_tick": 37375.0,
  "entry_diff_pct": 0.0,
  "exit_ref_bar": 36863.625,
  "exit_ref_tick": 36850.0,
  "exit_diff_pct": -0.03696055393358488,
  "net_pnl_tick": -64148.86375,
  "net_pct_tick": -0.019259151636606544,
  "tick_refined": true
 },
 {
  "code": "096770",
  "name": "SK이노베이션",
  "sector": "화학",
  "entry_ts": "2026-09-01T09:10:00",
  "entry_price": 133533.4,
  "exit_ts": "2026-09-01T09:15:00",
  "exit_price": 137401.862598,
  "qty": 24,
  "gross_pnl": 92843.10235200031,
  "commission": 975.3669453527999,
  "tax": 7584.582815409601,
  "slippage_cost": 6502.545647999737,
  "net_pnl": 84283.15259123791,
  "net_pct": 0.0262990235000001,
  "exit_reason": "target",
  "bars_held": 2,
  "mfe_pct": 3.045380406699749,
  "mae_pct": -0.6241135176667356,
  "entry_ref_bar": 133400.0,
  "entry_ref_tick": 133400.0,
  "entry_diff_pct": 0.0,
  "exit_ref_bar": 137539.402,
  "exit_ref_tick": 137600.0,
  "exit_diff_pct": 0.0440586472812976,
  "net_pnl_tick": 85732.49064,
  "net_pct_tick": 0.026751263054786298,
  "tick_refined": true
 },
 {
  "code": "001210",
  "name": "금호전기",
  "sector": "전기/전자",
  "entry_ts": "2026-09-01T09:15:00",
  "entry_price": 14164.149999999998,
  "exit_ts": "2026-09-01T09:15:00",
  "exit_price": 13937.736062249998,
  "qty": 235,
  "gross_pnl": -53207.27537124991,
  "commission": 990.5914836943123,
  "tax": 7533.3463416461245,
  "slippage_cost": 6603.896621249278,
  "net_pnl": -61731.213196590346,
  "net_pct": -0.018545836749999975,
  "exit_reason": "stop",
  "bars_held": 1,
  "mfe_pct": 0.9591115598182931,
  "mae_pct": -2.0061210873931534,
  "entry_ref_bar": 14150.0,
  "entry_ref_tick": 14150.0,
  "entry_diff_pct": 0.0,
  "exit_ref_bar": 13951.687749999997,
  "exit_ref_tick": 13950.0,
  "exit_diff_pct": -0.012097102732233633,
  "net_pnl_tick": -62126.46707499966,
  "net_pct_tick": -0.018664582414052278,
  "tick_refined": true
 },
 {
  "code": "096770",
  "name": "SK이노베이션",
  "sector": "화학",
  "entry_ts": "2026-09-01T09:20:00",
  "entry_price": 137737.59999999998,
  "exit_ts": "2026-09-01T09:25:00",
  "exit_price": 135535.86446399995,
  "qty": 24,
  "gross_pnl": -52841.65286400053,
  "commission": 983.7844720703996,
  "tax": 7481.579718412797,
  "slippage_cost": 6558.5168639996555,
  "net_pnl": -61307.017054483724,
  "net_pct": -0.018545836750000162,
  "exit_reason": "stop",
  "bars_held": 2,
  "mfe_pct": 0.5535162511906888,
  "mae_pct": -2.277954603535981,
  "entry_ref_bar": 137600.0,
  "entry_ref_tick": 137600.0,
  "entry_diff_pct": 0.0,
  "exit_ref_bar": 135671.53599999996,
  "exit_ref_tick": 135600.0,
  "exit_diff_pct": -0.05272734584501615,
  "net_pnl_tick": -63017.96207999958,
  "net_pct_tick": -0.01906341057198603,
  "tick_refined": true
 },
 {
  "code": "047050",
  "name": "포스코인터내셔널",
  "sector": "유통",
  "entry_ts": "2026-09-01T09:25:00",
  "entry_price": 56300.0,
  "exit_ts": "2026-09-01T10:00:00",
  "exit_price": 55355.5,
  "qty": 59,
  "gross_pnl": -55725.5,
  "commission": 988.151175,
  "tax": 7511.74135,
  "slippage_cost": 11800.0,
  "net_pnl": -64225.392525,
  "net_pct": -0.019335097246891652,
  "exit_reason": "stop",
  "bars_held": 8,
  "mfe_pct": 0.7104795737122638,
  "mae_pct": -1.5985790408525768,
  "entry_ref_bar": 56200.0,
  "entry_ref_tick": 56200.0,
  "entry_diff_pct": 0.0,
  "exit_ref_bar": 55455.5,
  "exit_ref_tick": 55400.0,
  "exit_diff_pct": -0.10008024452038411,
  "net_pnl_tick": -67491.87,
  "net_pct_tick": -0.020318472468916517,
  "tick_refined": true
 },
 {
  "code": "006400",
  "name": "삼성SDI",
  "sector": "전기/전자",
  "entry_ts": "2026-09-01T09:25:00",
  "entry_price": 586000.0,
  "exit_ts": "2026-09-01T11:30:00",
  "exit_price": 576210.0,
  "qty": 5,
  "gross_pnl": -48950.0,
  "commission": 871.6574999999999,
  "tax": 6626.415,
  "slippage_cost": 10000.0,
  "net_pnl": -56448.0725,
  "net_pct": -0.019265553754266213,
  "exit_reason": "stop",
  "bars_held": 26,
  "mfe_pct": 2.3890784982935065,
  "mae_pct": -2.0477815699658675,
  "entry_ref_bar": 585000.0,
  "entry_ref_tick": 585000.0,
  "entry_diff_pct": 0.0,
  "exit_ref_bar": 577210.0,
  "exit_ref_tick": 577000.0,
  "exit_diff_pct": -0.03638190606538583,
  "net_pnl_tick": -57495.5,
  "net_pct_tick": -0.019623037542662116,
  "tick_refined": true
 },
 {
  "code": "373220",
  "name": "LG에너지솔루션",
  "sector": "전기/전자",
  "entry_ts": "2026-09-01T09:30:00",
  "entry_price": 382000.0,
  "exit_ts": "2026-09-01T11:30:00",
  "exit_price": 375770.0,
  "qty": 8,
  "gross_pnl": -49840.0,
  "commission": 909.324,
  "tax": 6914.168,
  "slippage_cost": 8000.0,
  "net_pnl": -57663.492,
  "net_pct": -0.018868943717277487,
  "exit_reason": "stop",
  "bars_held": 25,
  "mfe_pct": 1.308900523560208,
  "mae_pct": -1.832460732984298,
  "entry_ref_bar": 381500.0,
  "entry_ref_tick": 381500.0,
  "entry_diff_pct": 0.0,
  "exit_ref_bar": 376270.0,
  "exit_ref_tick": 376000.0,
  "exit_diff_pct": -0.07175698301751243,
  "net_pnl_tick": -59818.2,
  "net_pct_tick": -0.01957401832460733,
  "tick_refined": true
 },
 {
  "code": "402340",
  "name": "SK스퀘어",
  "sector": "금융",
  "entry_ts": "2026-09-01T10:05:00",
  "entry_price": 1047546.4999999999,
  "exit_ts": "2026-09-01T11:35:00",
  "exit_price": 1030801.4691974999,
  "qty": 3,
  "gross_pnl": -50235.092407499906,
  "commission": 935.2565861388748,
  "tax": 7112.530137462749,
  "slippage_cost": 6234.9999074995285,
  "net_pnl": -58282.87913110152,
  "net_pct": -0.01854583674999997,
  "exit_reason": "stop",
  "bars_held": 19,
  "mfe_pct": 0.9024420395657984,
  "mae_pct": -1.6750091762036234,
  "entry_ref_bar": 1046500.0,
  "entry_ref_tick": 1046500.0,
  "entry_diff_pct": 0.0,
  "exit_ref_bar": 1031833.3024999999,
  "exit_ref_tick": 1031000.0,
  "exit_diff_pct": -0.08075941123250052,
  "net_pnl_tick": -60774.168074999645,
  "net_pct_tick": -0.01933857449287443,
  "tick_refined": true
 },
 {
  "code": "055550",
  "name": "신한지주",
  "sector": "금융",
  "entry_ts": "2026-09-01T12:25:00",
  "entry_price": 111211.09999999999,
  "exit_ts": "2026-09-01T15:20:00",
  "exit_price": 111188.7,
  "qty": 29,
  "gross_pnl": -649.5999999998312,
  "commission": 967.4391299999999,
  "tax": 7416.286289999999,
  "slippage_cost": 6449.599999999831,
  "net_pnl": -9033.32541999983,
  "net_pct": -0.0028009252673518573,
  "exit_reason": "eod",
  "bars_held": 37,
  "mfe_pct": 0.7093716364643621,
  "mae_pct": -0.4595764271731806,
  "entry_ref_bar": 111100.0,
  "entry_ref_tick": 111100.0,
  "entry_diff_pct": 0.0,
  "exit_ref_bar": 111300.0,
  "exit_ref_tick": 111300.0,
  "exit_diff_pct": 0.0,
  "net_pnl_tick": -9033.32541999983,
  "net_pct_tick": -0.0028009252673518573,
  "tick_refined": true
 },
 {
  "code": "034730",
  "name": "SK",
  "sector": "금융",
  "entry_ts": "2026-09-01T12:40:00",
  "entry_price": 579000.0,
  "exit_ts": "2026-09-01T15:20:00",
  "exit_price": 582000.0,
  "qty": 5,
  "gross_pnl": 15000.0,
  "commission": 870.7499999999999,
  "tax": 6693.0,
  "slippage_cost": 10000.0,
  "net_pnl": 7436.25,
  "net_pct": 0.002568652849740933,
  "exit_reason": "eod",
  "bars_held": 34,
  "mfe_pct": 1.3816925734024155,
  "mae_pct": -1.0362694300518172,
  "entry_ref_bar": 578000.0,
  "entry_ref_tick": 578000.0,
  "entry_diff_pct": 0.0,
  "exit_ref_bar": 583000.0,
  "exit_ref_tick": 583000.0,
  "exit_diff_pct": 0.0,
  "net_pnl_tick": 7436.25,
  "net_pct_tick": 0.002568652849740933,
  "tick_refined": true
 },
 {
  "code": "402340",
  "name": "SK스퀘어",
  "sector": "금융",
  "entry_ts": "2026-09-01T12:40:00",
  "entry_price": 1046044.9999999999,
  "exit_ts": "2026-09-01T15:20:00",
  "exit_price": 1062936.0,
  "qty": 3,
  "gross_pnl": 50673.00000000035,
  "commission": 949.0414499999999,
  "tax": 7334.2584,
  "slippage_cost": 6326.999999999651,
  "net_pnl": 42389.70015000035,
  "net_pct": 0.013507927527018551,
  "exit_reason": "eod",
  "bars_held": 34,
  "mfe_pct": 2.4812508066096806,
  "mae_pct": -0.6734891902355877,
  "entry_ref_bar": 1045000.0,
  "entry_ref_tick": 1045000.0,
  "entry_diff_pct": 0.0,
  "exit_ref_bar": 1064000.0,
  "exit_ref_tick": 1064000.0,
  "exit_diff_pct": 0.0,
  "net_pnl_tick": 42389.70015000035,
  "net_pct_tick": 0.013507927527018551,
  "tick_refined": true
 }
]
