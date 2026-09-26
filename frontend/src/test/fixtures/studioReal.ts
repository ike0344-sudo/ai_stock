// 실제 서버 응답(2026-09-25, 프리셋 new_high_20 · 2025-01~08 · 상위 100종목)에서 뽑은 고정 값 — 타입(types/studio.ts)이 실제 응답과 맞는지 컴파일이 검사한다.
// 거래는 앞 12건, 곡선은 60점만 남겼다(나머지 필드는 그대로).
import type { EquityPoint, RunDetail, Trade } from '@/types/studio'

export const realDetail: RunDetail = {
 "run_id": "20260925-225818-9b9af3",
 "meta": {
  "mode": "daily_portfolio",
  "compat": false,
  "spec_hash": "9ab5feefa91a166c",
  "structure_hash": "93393cdae7977505",
  "params": {
   "n": 20.0,
   "vol_mult": 1.5,
   "exit_n": 7.0
  },
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
   ]
  },
  "period_used": [
   "2025-01-02",
   "2025-08-29"
  ],
  "warmup_bars": 600,
  "elapsed_sec": 5.609,
  "warnings": [
   "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
   "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)",
   "데이터 끝에서 강제 청산된 종목 5건(end_of_data)"
  ],
  "run_id": "20260925-225818-9b9af3",
  "engine_version": "0.1.0",
  "git": {
   "commit": "2392556",
   "dirty": true
  },
  "created_at": "2026-09-25T22:58:26"
 },
 "spec": {
  "version": 1,
  "name": "20일 신고가 돌파 (시연용·미검증)",
  "mode": "daily_portfolio",
  "period": {
   "start": "2025-01-02",
   "end": "2025-08-29"
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
        "n": {
         "param": "n"
        }
       },
       "offset": 0,
       "mul": 1.0
      }
     },
     {
      "left": {
       "kind": "field",
       "name": "volume",
       "offset": 0,
       "mul": 1.0
      },
      "op": "gte",
      "right": {
       "kind": "ind",
       "name": "sma",
       "params": {
        "src": "volume",
        "n": 20
       },
       "offset": 1,
       "mul": {
        "param": "vol_mult"
       }
      }
     }
    ]
   },
   "exit": {
    "logic": "any",
    "items": [
     {
      "left": {
       "kind": "field",
       "name": "close",
       "offset": 0,
       "mul": 1.0
      },
      "op": "lt",
      "right": {
       "kind": "ind",
       "name": "lowest",
       "params": {
        "src": "low",
        "n": {
         "param": "exit_n"
        }
       },
       "offset": 0,
       "mul": 1.0
      }
     }
    ]
   }
  },
  "market_filter": null,
  "exits": {
   "stop_loss_pct": 7.0,
   "take_profit_pct": null,
   "trailing_stop_pct": 10.0,
   "max_holding_bars": null
  },
  "portfolio": {
   "initial_capital": 10000000.0,
   "max_positions": 5.0,
   "sizing": "equal_slot_fixed",
   "fixed_amount": null,
   "risk_pct": null,
   "max_weight_pct": 25.0,
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
  "tick": null,
  "compat": {
   "legacy": false
  },
  "params": {
   "n": {
    "default": 20.0,
    "min": 10.0,
    "max": 120.0,
    "step": 10.0
   },
   "vol_mult": {
    "default": 1.5,
    "min": 1.0,
    "max": 3.0,
    "step": 0.5
   },
   "exit_n": {
    "default": 7.0,
    "min": 3.0,
    "max": 40.0,
    "step": 1.0
   }
  },
  "validation": null
 },
 "summary": {
  "metrics": {
   "total_return_pct": 9.698002959717167,
   "cagr_pct": 15.589860016038237,
   "max_drawdown_pct": 29.30765512918888,
   "mdd_duration_bars": 61,
   "volatility_pct": 38.433479225459486,
   "sharpe": 0.566109799711667,
   "sortino": 0.9110047820222599,
   "calmar": 0.5319381556565254,
   "num_trades": 157,
   "win_rate_pct": 29.936305732484076,
   "profit_factor": 1.0781211789110032,
   "avg_win_pct": 16.70702834534757,
   "avg_loss_pct": -5.918304972712931,
   "expectancy_pct": 0.8548839823752435,
   "max_consec_losses": 18,
   "avg_holding_bars": 5.101910828025478,
   "exposure_pct": 98.75776397515527,
   "turnover": 27.013400614792925,
   "commission_total": 89314.69902268802,
   "tax_total": 686753.7749260168,
   "slippage_total": 843970.2146595696,
   "skipped": {
    "slots_full": 2122,
    "cash": 6,
    "upper_limit": 0,
    "volume_cap": 0,
    "no_data": 2
   },
   "benchmark_return_pct": 32.80907400768673,
   "excess_return_pct": -23.111071047969567,
   "beta": 0.6204678778259036
  },
  "legacy_metrics": null,
  "skipped": {
   "slots_full": 2122,
   "cash": 6,
   "upper_limit": 0,
   "volume_cap": 0,
   "no_data": 2
  },
  "n_trades": 157,
  "n_closed": 157,
  "n_codes": 2423,
  "n_bars": 161,
  "universe_excluded": {
   "spac": 33,
   "preferred": 7,
   "mega_cap": 2,
   "market_unknown": 0,
   "market_other": 0
  },
  "warnings": [
   "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
   "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)",
   "데이터 끝에서 강제 청산된 종목 5건(end_of_data)"
  ],
  "robustness": {
   "n_trades": 157,
   "cost_sensitivity": [
    {
     "mult": 0.0,
     "net_pnl": 2589838.9845799915,
     "net_return_pct": 25.89838984579991
    },
    {
     "mult": 0.5,
     "net_pnl": 1779819.6402758542,
     "net_return_pct": 17.798196402758542
    },
    {
     "mult": 1.0,
     "net_pnl": 969800.2959717168,
     "net_return_pct": 9.698002959717167
    },
    {
     "mult": 1.5,
     "net_pnl": 159780.95166757936,
     "net_return_pct": 1.5978095166757935
    },
    {
     "mult": 2.0,
     "net_pnl": -650238.392636558,
     "net_return_pct": -6.502383926365581
    },
    {
     "mult": 3.0,
     "net_pnl": -2270277.081244833,
     "net_return_pct": -22.70277081244833
    }
   ],
   "breakeven_cost_mult": 1.5986278616622682,
   "cost_sensitivity_meta": {
    "gross_before_costs": 2589838.9845799915,
    "total_costs": 1620038.6886082748,
    "approximation": "같은 거래·같은 수량을 가정한 사후 계산(비용이 바뀌면 달라질 사이징·건너뜀은 미반영)"
   },
   "monte_carlo": {
    "n_sims": 1000,
    "seed": 42,
    "n_trades": 157,
    "weight": 0.18907180192611464,
    "final_return_pct": {
     "p5": -32.569148146734825,
     "p50": 18.58261351888989,
     "p95": 131.07119883269968
    },
    "max_drawdown_pct": {
     "p5": 14.102747334820833,
     "p50": 24.160029312253716,
     "p95": 43.21988482790657
    },
    "prob_mdd_gt_30": 0.29,
    "approximation": "겹친 보유 무시 — 거래를 한 줄로 세워 복리"
   },
   "concentration": {
    "total_net_pnl": 969800.2959717163,
    "by_code": [
     {
      "k": 1,
      "removed": [
       "034020"
      ],
      "removed_pnl": 2111149.1361999996,
      "net_pnl_excluding": -1141348.8402282833,
      "sign_flipped": true
     },
     {
      "k": 2,
      "removed": [
       "034020",
       "389140"
      ],
      "removed_pnl": 3265777.9054432,
      "net_pnl_excluding": -2295977.6094714836,
      "sign_flipped": true
     },
     {
      "k": 3,
      "removed": [
       "034020",
       "389140",
       "389470"
      ],
      "removed_pnl": 4235169.8944432,
      "net_pnl_excluding": -3265369.5984714837,
      "sign_flipped": true
     }
    ],
    "by_date": [
     {
      "k": 1,
      "removed": [
       "2025-06-25"
      ],
      "removed_pnl": 1986976.961,
      "net_pnl_excluding": -1017176.6650282836,
      "sign_flipped": true
     },
     {
      "k": 2,
      "removed": [
       "2025-06-25",
       "2025-05-09"
      ],
      "removed_pnl": 2956368.9499999997,
      "net_pnl_excluding": -1986568.6540282834,
      "sign_flipped": true
     },
     {
      "k": 3,
      "removed": [
       "2025-06-25",
       "2025-05-09",
       "2025-04-23"
      ],
      "removed_pnl": 3838268.0104006557,
      "net_pnl_excluding": -2868467.7144289394,
      "sign_flipped": true
     }
    ]
   }
  },
  "criteria": []
 },
 "warnings": [
  "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
  "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)",
  "데이터 끝에서 강제 청산된 종목 5건(end_of_data)"
 ],
 "analysis": {
  "monthly": [
   {
    "period": "2025-01",
    "return_pct": -1.1393241733687387
   },
   {
    "period": "2025-02",
    "return_pct": 5.275982886335595
   },
   {
    "period": "2025-03",
    "return_pct": -18.199450964701146
   },
   {
    "period": "2025-04",
    "return_pct": 14.60100276164451
   },
   {
    "period": "2025-05",
    "return_pct": 13.062955348750283
   },
   {
    "period": "2025-06",
    "return_pct": 15.423759486971477
   },
   {
    "period": "2025-07",
    "return_pct": -1.6886652335758812
   },
   {
    "period": "2025-08",
    "return_pct": -12.364097466871382
   }
  ],
  "yearly": [
   {
    "period": "2025",
    "return_pct": 9.698002959717167
   }
  ],
  "exit_reasons": [
   {
    "reason": "trailing",
    "n": 84,
    "share_pct": 53.503184713375795,
    "avg_net_pct": 7.368551372767558
   },
   {
    "reason": "stop",
    "n": 65,
    "share_pct": 41.40127388535032,
    "avg_net_pct": -7.442773656749243
   },
   {
    "reason": "end_of_data",
    "n": 5,
    "share_pct": 3.1847133757961785,
    "avg_net_pct": 0.2608272730100035
   },
   {
    "reason": "signal",
    "n": 3,
    "share_pct": 1.910828025477707,
    "avg_net_pct": -0.7551262519702504
   }
  ],
  "by_sector": [
   {
    "key": "기계/장비",
    "n": 18,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": 2031247.5847227853,
    "avg_net_pct": 5.86586381118496
   },
   {
    "key": "오락/문화",
    "n": 3,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": 934951.5638382002,
    "avg_net_pct": 29.50744697981598
   },
   {
    "key": "제약",
    "n": 8,
    "win_rate_pct": 37.5,
    "net_pnl": 889909.9600510356,
    "avg_net_pct": 5.3646464677108305
   },
   {
    "key": "섬유/의류",
    "n": 4,
    "win_rate_pct": 25.0,
    "net_pnl": 564519.4329477379,
    "avg_net_pct": 5.4675867340173525
   },
   {
    "key": "운송장비/부품",
    "n": 22,
    "win_rate_pct": 36.36363636363637,
    "net_pnl": 336366.3625502449,
    "avg_net_pct": 0.8526067334864598
   },
   {
    "key": "금융",
    "n": 11,
    "win_rate_pct": 45.45454545454545,
    "net_pnl": 149567.2813875027,
    "avg_net_pct": 5.142085931712326
   },
   {
    "key": "보험",
    "n": 1,
    "win_rate_pct": 100.0,
    "net_pnl": 34238.88433000032,
    "avg_net_pct": 1.7451367168545908
   },
   {
    "key": "화학",
    "n": 11,
    "win_rate_pct": 27.27272727272727,
    "net_pnl": 24866.046172660517,
    "avg_net_pct": 0.6112822993157647
   },
   {
    "key": "전기/가스",
    "n": 1,
    "win_rate_pct": 100.0,
    "net_pnl": 12900.019499999999,
    "avg_net_pct": 0.6518124147339699
   },
   {
    "key": "일반서비스",
    "n": 12,
    "win_rate_pct": 16.666666666666664,
    "net_pnl": 7511.402539500661,
    "avg_net_pct": -0.1803861575901068
   },
   {
    "key": "비금속",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -19367.403,
    "avg_net_pct": -0.9716884661117716
   },
   {
    "key": "운송/창고",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -45872.01872824985,
    "avg_net_pct": -2.3066836734693803
   },
   {
    "key": "유통",
    "n": 2,
    "win_rate_pct": 50.0,
    "net_pnl": -52321.92124499993,
    "avg_net_pct": -1.316384518611417
   },
   {
    "key": "의료/정밀기기",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -77671.16384900476,
    "avg_net_pct": -7.335622150000005
   },
   {
    "key": "통신",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -146984.1360875,
    "avg_net_pct": -7.351871857923498
   },
   {
    "key": "건설",
    "n": 6,
    "win_rate_pct": 50.0,
    "net_pnl": -165370.65232500053,
    "avg_net_pct": -1.4314531060363553
   },
   {
    "key": "IT 서비스",
    "n": 15,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": -321176.4299967844,
    "avg_net_pct": -1.1025515829952997
   },
   {
    "key": "음식료/담배",
    "n": 4,
    "win_rate_pct": 0.0,
    "net_pnl": -411050.18299955,
    "avg_net_pct": -5.155171526042455
   },
   {
    "key": "금속",
    "n": 15,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": -729462.1391078972,
    "avg_net_pct": -2.4457549483195304
   },
   {
    "key": "전기/전자",
    "n": 20,
    "win_rate_pct": 10.0,
    "net_pnl": -2047002.1947289652,
    "avg_net_pct": -5.196134950465026
   }
  ],
  "by_theme_group": [
   {
    "key": "원전",
    "n": 6,
    "win_rate_pct": 66.66666666666666,
    "net_pnl": 2150523.9591999995,
    "avg_net_pct": 18.30476204148959
   },
   {
    "key": "바이오",
    "n": 7,
    "win_rate_pct": 42.857142857142854,
    "net_pnl": 1455767.642891191,
    "avg_net_pct": 10.812846897654703
   },
   {
    "key": "조선",
    "n": 15,
    "win_rate_pct": 60.0,
    "net_pnl": 935662.9003085799,
    "avg_net_pct": 3.734623782239018
   },
   {
    "key": "우주",
    "n": 9,
    "win_rate_pct": 44.44444444444444,
    "net_pnl": 714536.2366426319,
    "avg_net_pct": 4.038293156296868
   },
   {
    "key": "2차전지",
    "n": 5,
    "win_rate_pct": 60.0,
    "net_pnl": 382119.8326,
    "avg_net_pct": 3.9475736606691623
   },
   {
    "key": "로봇",
    "n": 9,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": 160937.71371224985,
    "avg_net_pct": 1.02041958090206
   },
   {
    "key": "신재생",
    "n": 3,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": 143809.17984999972,
    "avg_net_pct": 4.257050050696798
   },
   {
    "key": "양자",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -139189.7271400001,
    "avg_net_pct": -7.360485613207551
   },
   {
    "key": "데이터센터",
    "n": 4,
    "win_rate_pct": 25.0,
    "net_pnl": -159926.43244599953,
    "avg_net_pct": -2.15697498913818
   },
   {
    "key": "화장품",
    "n": 3,
    "win_rate_pct": 0.0,
    "net_pnl": -286979.8058928048,
    "avg_net_pct": -4.835811413867441
   },
   {
    "key": "전력",
    "n": 3,
    "win_rate_pct": 0.0,
    "net_pnl": -289660.0405499998,
    "avg_net_pct": -5.002929680326523
   },
   {
    "key": "지주사",
    "n": 6,
    "win_rate_pct": 16.666666666666664,
    "net_pnl": -358829.4425225494,
    "avg_net_pct": -3.1585444446437343
   },
   {
    "key": "반도체",
    "n": 12,
    "win_rate_pct": 16.666666666666664,
    "net_pnl": -797053.8932566331,
    "avg_net_pct": -3.3266297534700886
   },
   {
    "key": "방산",
    "n": 7,
    "win_rate_pct": 0.0,
    "net_pnl": -973546.6399065446,
    "avg_net_pct": -7.030408799594516
   },
   {
    "key": "(미분류)",
    "n": 67,
    "win_rate_pct": 23.88059701492537,
    "net_pnl": -1968371.1875184048,
    "avg_net_pct": -0.474182253200176
   }
  ],
  "histogram": {
   "edges": [
    -9.438845486111111,
    -3.951564322916667,
    1.535716840277777,
    7.022998003472219,
    12.510279166666665,
    17.99756032986111,
    23.484841493055548,
    28.972122656249994,
    34.45940381944444,
    39.946684982638885,
    45.43396614583333,
    50.92124730902777,
    56.40852847222221,
    61.89580963541666,
    67.38309079861111,
    72.87037196180556,
    78.357653125,
    83.84493428819444,
    89.33221545138889,
    94.81949661458333,
    100.30677777777777
   ],
   "counts": [
    87,
    31,
    11,
    10,
    5,
    1,
    3,
    2,
    3,
    1,
    1,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    2
   ]
  }
 },
 "narration": "종가가 [n]일 최고가를 넘고 거래량이 1일 전 거래량 20일 이동평균의 [vol_mult]배 이상이면 다음 날 시가에 산다.\n종가가 [exit_n]일 최저가 미만이면 다음 날 시가에 판다.\n청산 규칙: 손절 -7%, 고점 대비 -10% 트레일링.",
 "has_grid": false,
 "has_folds": false
}

export const realTrades: Trade[] = [
 {
  "code": "277810",
  "name": "레인보우로보틱스",
  "sector": "기계/장비",
  "entry_ts": "2025-01-03T00:00:00",
  "entry_price": 225499.99999999997,
  "exit_ts": "2025-01-03T00:00:00",
  "exit_price": 209214.99999999997,
  "qty": 8,
  "gross_pnl": -130280.0,
  "commission": 521.6579999999999,
  "tax": 3849.5559999999996,
  "slippage_cost": 7999.999999999767,
  "net_pnl": -134651.214,
  "net_pct": -0.0746403625277162,
  "exit_reason": "stop",
  "bars_held": 1,
  "mfe_pct": 5.764966740576516,
  "mae_pct": -9.312638580931253
 },
 {
  "code": "437730",
  "name": "삼현",
  "sector": "운송장비/부품",
  "entry_ts": "2025-01-03T00:00:00",
  "entry_price": 9950.0,
  "exit_ts": "2025-01-06T00:00:00",
  "exit_price": 9243.5,
  "qty": 200,
  "gross_pnl": -141300.0,
  "commission": 575.805,
  "tax": 4252.01,
  "slippage_cost": 4000.0,
  "net_pnl": -146127.815,
  "net_pct": -0.07343106281407036,
  "exit_reason": "stop",
  "bars_held": 2,
  "mfe_pct": 0.6030150753768782,
  "mae_pct": -7.336683417085432
 },
 {
  "code": "158430",
  "name": "아톤",
  "sector": "IT 서비스",
  "entry_ts": "2025-01-07T00:00:00",
  "entry_price": 8480.0,
  "exit_ts": "2025-01-07T00:00:00",
  "exit_price": 7876.4,
  "qty": 223,
  "gross_pnl": -134602.80000000008,
  "commission": 547.12158,
  "tax": 4039.80556,
  "slippage_cost": 4460.0,
  "net_pnl": -139189.7271400001,
  "net_pct": -0.07360485613207551,
  "exit_reason": "stop",
  "bars_held": 1,
  "mfe_pct": 0.8254716981132004,
  "mae_pct": -8.726415094339623
 },
 {
  "code": "466100",
  "name": "클로봇",
  "sector": "IT 서비스",
  "entry_ts": "2025-01-03T00:00:00",
  "entry_price": 10240.23,
  "exit_ts": "2025-01-08T00:00:00",
  "exit_price": 10408.581,
  "qty": 195,
  "gross_pnl": 32828.44500000011,
  "commission": 603.9777217499999,
  "tax": 4668.2485785,
  "slippage_cost": 4026.5549999998893,
  "net_pnl": 27556.21869975011,
  "net_pct": 0.013799879695085029,
  "exit_reason": "trailing",
  "bars_held": 4,
  "mfe_pct": 13.776741342723753,
  "mae_pct": -5.002133741136672
 },
 {
  "code": "079550",
  "name": "LIG디펜스앤에어로스페이스",
  "sector": "금속",
  "entry_ts": "2025-01-03T00:00:00",
  "entry_price": 249500.0,
  "exit_ts": "2025-01-08T00:00:00",
  "exit_price": 241150.0,
  "qty": 8,
  "gross_pnl": -66800.0,
  "commission": 588.78,
  "tax": 4437.16,
  "slippage_cost": 8000.0,
  "net_pnl": -71825.94,
  "net_pct": -0.03598493987975952,
  "exit_reason": "trailing",
  "bars_held": 4,
  "mfe_pct": 7.615230460921851,
  "mae_pct": -6.613226452905807
 },
 {
  "code": "475400",
  "name": "씨메스로보틱스",
  "sector": "기계/장비",
  "entry_ts": "2025-01-03T00:00:00",
  "entry_price": 25400.0,
  "exit_ts": "2025-01-08T00:00:00",
  "exit_price": 24200.0,
  "qty": 78,
  "gross_pnl": -93600.0,
  "commission": 580.3199999999999,
  "tax": 4341.48,
  "slippage_cost": 7800.0,
  "net_pnl": -98521.8,
  "net_pct": -0.04972834645669291,
  "exit_reason": "trailing",
  "bars_held": 4,
  "mfe_pct": 6.889763779527569,
  "mae_pct": -9.645669291338589
 },
 {
  "code": "277810",
  "name": "레인보우로보틱스",
  "sector": "기계/장비",
  "entry_ts": "2025-01-06T00:00:00",
  "entry_price": 231500.00000000003,
  "exit_ts": "2025-01-08T00:00:00",
  "exit_price": 229900.0,
  "qty": 8,
  "gross_pnl": -12800.000000000233,
  "commission": 553.6800000000001,
  "tax": 4230.16,
  "slippage_cost": 8000.000000000233,
  "net_pnl": -17583.840000000233,
  "net_pct": -0.009494514038877015,
  "exit_reason": "trailing",
  "bars_held": 3,
  "mfe_pct": 10.583153347732166,
  "mae_pct": -1.7278617710583255
 },
 {
  "code": "042700",
  "name": "한미반도체",
  "sector": "기계/장비",
  "entry_ts": "2025-01-09T00:00:00",
  "entry_price": 115615.49999999999,
  "exit_ts": "2025-01-13T00:00:00",
  "exit_price": 107414.89258499998,
  "qty": 17,
  "gross_pnl": -139410.3260550001,
  "commission": 568.7275010917499,
  "tax": 4199.922300073499,
  "slippage_cost": 3791.3810549997434,
  "net_pnl": -144178.97585616534,
  "net_pct": -0.07335622150000005,
  "exit_reason": "stop",
  "bars_held": 3,
  "mfe_pct": 3.186856433609697,
  "mae_pct": -8.057310654713245
 },
 {
  "code": "082740",
  "name": "한화엔진",
  "sector": "기계/장비",
  "entry_ts": "2025-01-09T00:00:00",
  "entry_price": 21600.0,
  "exit_ts": "2025-01-16T00:00:00",
  "exit_price": 23575.0,
  "qty": 90,
  "gross_pnl": 177750.0,
  "commission": 609.8625,
  "tax": 4880.025,
  "slippage_cost": 9000.0,
  "net_pnl": 172260.11250000002,
  "net_pct": 0.0886111689814815,
  "exit_reason": "trailing",
  "bars_held": 6,
  "mfe_pct": 21.527777777777768,
  "mae_pct": -2.083333333333337
 },
 {
  "code": "006340",
  "name": "대원전선",
  "sector": "전기/전자",
  "entry_ts": "2025-01-14T00:00:00",
  "entry_price": 3889.9999999999995,
  "exit_ts": "2025-01-20T00:00:00",
  "exit_price": 3680.5,
  "qty": 468,
  "gross_pnl": -98045.99999999978,
  "commission": 531.4490999999998,
  "tax": 3961.6902,
  "slippage_cost": 4679.999999999787,
  "net_pnl": -102539.13929999978,
  "net_pct": -0.05632409383033408,
  "exit_reason": "trailing",
  "bars_held": 5,
  "mfe_pct": 5.26992287917738,
  "mae_pct": -5.526992287917731
 },
 {
  "code": "000100",
  "name": "유한양행",
  "sector": "제약",
  "entry_ts": "2025-01-09T00:00:00",
  "entry_price": 134234.09999999998,
  "exit_ts": "2025-01-23T00:00:00",
  "exit_price": 129270.6,
  "qty": 14,
  "gross_pnl": -69488.99999999959,
  "commission": 553.3598699999999,
  "tax": 4162.51332,
  "slippage_cost": 3688.9999999995925,
  "net_pnl": -74204.87318999959,
  "net_pct": -0.039485854078806885,
  "exit_reason": "signal",
  "bars_held": 10,
  "mfe_pct": 3.773929277284993,
  "mae_pct": -3.675742601917087
 },
 {
  "code": "042660",
  "name": "한화오션",
  "sector": "운송장비/부품",
  "entry_ts": "2025-01-08T00:00:00",
  "entry_price": 43300.0,
  "exit_ts": "2025-01-23T00:00:00",
  "exit_price": 51380.0,
  "qty": 40,
  "gross_pnl": 323200.0,
  "commission": 568.0799999999999,
  "tax": 4726.96,
  "slippage_cost": 6000.0,
  "net_pnl": 317904.95999999996,
  "net_pct": 0.1835478983833718,
  "exit_reason": "trailing",
  "bars_held": 12,
  "mfe_pct": 32.10161662817552,
  "mae_pct": -3.002309468822173
 }
]

export const realEquity: EquityPoint[] = [
 {
  "ts": "2025-01-02T00:00:00",
  "cash": 10000000.0,
  "positions_value": 0.0,
  "equity": 10000000.0,
  "n_positions": 0,
  "drawdown_pct": 0.0,
  "benchmark_kospi": 10000000.0,
  "benchmark_kosdaq": 10000000.0
 },
 {
  "ts": "2025-01-09T00:00:00",
  "cash": 763.5165981510654,
  "positions_value": 9717432.0,
  "equity": 9718195.51659815,
  "n_positions": 5,
  "drawdown_pct": -2.818044834018496,
  "benchmark_kospi": 10512559.713873629,
  "benchmark_kosdaq": 10537261.698440207
 },
 {
  "ts": "2025-01-16T00:00:00",
  "cash": 2118101.4947669855,
  "positions_value": 7895016.0,
  "equity": 10013117.494766986,
  "n_positions": 4,
  "drawdown_pct": -1.7914516647647094,
  "benchmark_kospi": 10535861.672238572,
  "benchmark_kosdaq": 10547747.695265282
 },
 {
  "ts": "2025-01-23T00:00:00",
  "cash": 4191772.469601126,
  "positions_value": 5713650.0,
  "equity": 9905422.469601126,
  "n_positions": 3,
  "drawdown_pct": -2.847723309434136,
  "benchmark_kospi": 10485839.579147458,
  "benchmark_kosdaq": 10544398.00183505
 },
 {
  "ts": "2025-02-05T00:00:00",
  "cash": 27889.054716625717,
  "positions_value": 10654440.0,
  "equity": 10682329.054716626,
  "n_positions": 5,
  "drawdown_pct": 0.0,
  "benchmark_kospi": 10459911.460895227,
  "benchmark_kosdaq": 10645908.27665555
 },
 {
  "ts": "2025-02-12T00:00:00",
  "cash": 4844182.1542896265,
  "positions_value": 5792776.0,
  "equity": 10636958.154289626,
  "n_positions": 3,
  "drawdown_pct": -4.771990712451224,
  "benchmark_kospi": 10622983.484372264,
  "benchmark_kosdaq": 10852715.43626116
 },
 {
  "ts": "2025-02-19T00:00:00",
  "cash": 2503473.6921210755,
  "positions_value": 8849802.0,
  "equity": 11353275.692121075,
  "n_positions": 4,
  "drawdown_pct": -1.4111835400377415,
  "benchmark_kospi": 11136251.844564682,
  "benchmark_kosdaq": 11334634.373680148
 },
 {
  "ts": "2025-02-26T00:00:00",
  "cash": 231757.75718375458,
  "positions_value": 10627342.0,
  "equity": 10859099.757183755,
  "n_positions": 5,
  "drawdown_pct": -5.702475486931668,
  "benchmark_kospi": 11009404.15350113,
  "benchmark_kosdaq": 11234726.126152368
 },
 {
  "ts": "2025-03-06T00:00:00",
  "cash": 2363260.5826357044,
  "positions_value": 8273600.0,
  "equity": 10636860.582635704,
  "n_positions": 4,
  "drawdown_pct": -7.632341173619473,
  "benchmark_kospi": 10738742.94480062,
  "benchmark_kosdaq": 10703289.981503867
 },
 {
  "ts": "2025-03-13T00:00:00",
  "cash": 1836123.6550888626,
  "positions_value": 8797000.0,
  "equity": 10633123.655088862,
  "n_positions": 4,
  "drawdown_pct": -7.6647916552276545,
  "benchmark_kospi": 10728238.305251485,
  "benchmark_kosdaq": 10526775.701615134
 },
 {
  "ts": "2025-03-20T00:00:00",
  "cash": 2196994.866702863,
  "positions_value": 8065454.0,
  "equity": 10262448.866702862,
  "n_positions": 4,
  "drawdown_pct": -10.883632602064154,
  "benchmark_kospi": 10992771.807548333,
  "benchmark_kosdaq": 10561000.830141416
 },
 {
  "ts": "2025-03-27T00:00:00",
  "cash": 1706606.0758529152,
  "positions_value": 7603228.0,
  "equity": 9309834.075852916,
  "n_positions": 4,
  "drawdown_pct": -19.15588523813174,
  "benchmark_kospi": 10867925.000208424,
  "benchmark_kosdaq": 10303802.630237537
 },
 {
  "ts": "2025-04-03T00:00:00",
  "cash": 3897965.671321278,
  "positions_value": 4460552.0,
  "equity": 8358517.671321278,
  "n_positions": 2,
  "drawdown_pct": -27.416863033888827,
  "benchmark_kospi": 10365828.240806356,
  "benchmark_kosdaq": 9954269.402735097
 },
 {
  "ts": "2025-04-10T00:00:00",
  "cash": 5693.417604244256,
  "positions_value": 8857162.0,
  "equity": 8862855.417604243,
  "n_positions": 5,
  "drawdown_pct": -23.03732862897445,
  "benchmark_kospi": 10192251.577780187,
  "benchmark_kosdaq": 9929510.79912034
 },
 {
  "ts": "2025-04-17T00:00:00",
  "cash": 2146923.3236934445,
  "positions_value": 8212656.0,
  "equity": 10359579.323693445,
  "n_positions": 4,
  "drawdown_pct": -10.04017763306676,
  "benchmark_kospi": 10297923.249435168,
  "benchmark_kosdaq": 10365844.77811922
 },
 {
  "ts": "2025-04-24T00:00:00",
  "cash": 1614119.9985059004,
  "positions_value": 8664400.0,
  "equity": 10278519.9985059,
  "n_positions": 4,
  "drawdown_pct": -10.744075182108858,
  "benchmark_kospi": 10514352.172209393,
  "benchmark_kosdaq": 10574545.242707133
 },
 {
  "ts": "2025-05-02T00:00:00",
  "cash": 569227.7664684004,
  "positions_value": 9918461.0,
  "equity": 10487688.7664684,
  "n_positions": 5,
  "drawdown_pct": -8.927709418338814,
  "benchmark_kospi": 10670504.472808823,
  "benchmark_kosdaq": 10513085.650204623
 },
 {
  "ts": "2025-05-13T00:00:00",
  "cash": 3339685.542256033,
  "positions_value": 7412924.0,
  "equity": 10752609.542256033,
  "n_positions": 4,
  "drawdown_pct": -6.627208096180026,
  "benchmark_kospi": 10873219.005060568,
  "benchmark_kosdaq": 10659015.772686891
 },
 {
  "ts": "2025-05-20T00:00:00",
  "cash": 3326937.2084060335,
  "positions_value": 8034576.0,
  "equity": 11361513.208406033,
  "n_positions": 4,
  "drawdown_pct": -1.3396511468212857,
  "benchmark_kospi": 10845623.483705303,
  "benchmark_kosdaq": 10421187.53914044
 },
 {
  "ts": "2025-05-27T00:00:00",
  "cash": 2882517.2898735325,
  "positions_value": 8484284.0,
  "equity": 11366801.289873533,
  "n_positions": 4,
  "drawdown_pct": -1.3941848239443333,
  "benchmark_kospi": 10993272.028479245,
  "benchmark_kosdaq": 10589546.043720782
 },
 {
  "ts": "2025-06-04T00:00:00",
  "cash": 715809.1672785336,
  "positions_value": 10749000.0,
  "equity": 11464809.167278534,
  "n_positions": 5,
  "drawdown_pct": -0.5439767136112494,
  "benchmark_kospi": 11550268.035048814,
  "benchmark_kosdaq": 10925971.775191879
 },
 {
  "ts": "2025-06-12T00:00:00",
  "cash": 715809.1672785336,
  "positions_value": 11835900.0,
  "equity": 12551709.167278534,
  "n_positions": 5,
  "drawdown_pct": 0.0,
  "benchmark_kospi": 12172167.707404105,
  "benchmark_kosdaq": 11497458.602158368
 },
 {
  "ts": "2025-06-19T00:00:00",
  "cash": 715809.1672785336,
  "positions_value": 12528100.0,
  "equity": 13243909.167278534,
  "n_positions": 5,
  "drawdown_pct": 0.0,
  "benchmark_kospi": 12412732.290094793,
  "benchmark_kosdaq": 11396385.243872244
 },
 {
  "ts": "2025-06-26T00:00:00",
  "cash": 8817720.344608534,
  "positions_value": 4280500.0,
  "equity": 13098220.344608534,
  "n_positions": 2,
  "drawdown_pct": -5.1277362755278055,
  "benchmark_kospi": 12837169.749972906,
  "benchmark_kosdaq": 11475612.775439465
 },
 {
  "ts": "2025-07-03T00:00:00",
  "cash": 2185289.9961989056,
  "positions_value": 10047332.0,
  "equity": 12232621.996198906,
  "n_positions": 5,
  "drawdown_pct": -11.397387619695976,
  "benchmark_kospi": 12990195.66975414,
  "benchmark_kosdaq": 11553966.473937929
 },
 {
  "ts": "2025-07-10T00:00:00",
  "cash": 2104283.3366989056,
  "positions_value": 10237719.0,
  "equity": 12342002.336698905,
  "n_positions": 5,
  "drawdown_pct": -10.605130333044066,
  "benchmark_kospi": 13269318.949202564,
  "benchmark_kosdaq": 11617610.64911233
 },
 {
  "ts": "2025-07-17T00:00:00",
  "cash": 2035863.8200864075,
  "positions_value": 10125189.0,
  "equity": 12161052.820086408,
  "n_positions": 5,
  "drawdown_pct": -11.915773291340514,
  "benchmark_kospi": 13307085.629486358,
  "benchmark_kosdaq": 11917189.75285088
 },
 {
  "ts": "2025-07-24T00:00:00",
  "cash": 2035863.8200864075,
  "positions_value": 10569544.0,
  "equity": 12605407.820086408,
  "n_positions": 5,
  "drawdown_pct": -8.69724713754586,
  "benchmark_kospi": 13299415.575212386,
  "benchmark_kosdaq": 11795144.400914613
 },
 {
  "ts": "2025-07-31T00:00:00",
  "cash": 4012948.838058408,
  "positions_value": 8504524.0,
  "equity": 12517472.838058408,
  "n_positions": 4,
  "drawdown_pct": -9.334172657660588,
  "benchmark_kospi": 13528641.81680242,
  "benchmark_kosdaq": 11727422.338086013
 },
 {
  "ts": "2025-08-07T00:00:00",
  "cash": 4079150.993389257,
  "positions_value": 8089040.0,
  "equity": 12168190.993389256,
  "n_positions": 4,
  "drawdown_pct": -11.864070491854662,
  "benchmark_kospi": 13454609.11902757,
  "benchmark_kosdaq": 11735723.752239197
 },
 {
  "ts": "2025-08-14T00:00:00",
  "cash": 5755152.940272021,
  "positions_value": 6014600.0,
  "equity": 11769752.940272022,
  "n_positions": 3,
  "drawdown_pct": -14.750013700831365,
  "benchmark_kospi": 13446188.733357234,
  "benchmark_kosdaq": 11873352.460568283
 },
 {
  "ts": "2025-08-22T00:00:00",
  "cash": 3295813.451166717,
  "positions_value": 7805335.0,
  "equity": 11101148.451166717,
  "n_positions": 4,
  "drawdown_pct": -19.592810641858115,
  "benchmark_kospi": 13208875.586717468,
  "benchmark_kosdaq": 11396385.243872244
 },
 {
  "ts": "2025-08-29T00:00:00",
  "cash": 10969800.295971716,
  "positions_value": 0.0,
  "equity": 10969800.295971716,
  "n_positions": 0,
  "drawdown_pct": -20.544183919412752,
  "benchmark_kospi": 13280907.400768673,
  "benchmark_kosdaq": 11606105.18037371
 }
]
