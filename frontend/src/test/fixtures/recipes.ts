// 실제 서버 응답(GET /api/meta/indicators, 2026-09-26 — studio-conditions c1 확정 칸 포함)에서 대표 지표만 남긴 카탈로그 + 레시피(GET /api/meta/recipes).
import type { IndicatorCatalog, Recipe } from '@/types/studio'

export const realCatalog: IndicatorCatalog = {
 "indicators": [
  {
   "name": "sma",
   "label": "이동평균",
   "desc": "대상 값의 N봉 단순 이동평균",
   "params": [
    {
     "name": "src",
     "kind": "enum",
     "default": "close",
     "lo": null,
     "hi": null,
     "choices": [
      "open",
      "high",
      "low",
      "close",
      "volume",
      "value"
     ],
     "label": "대상 값"
    },
    {
     "name": "n",
     "kind": "int",
     "default": 20,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday",
    "tick"
   ],
   "timing": "t 포함",
   "compute": true,
   "category": "trend",
   "definition": "SMA_n = (X_t + … + X_{t−n+1}) ÷ n",
   "example": "종가가 20일 이동평균 위",
   "live": true,
   "volume_based": false,
   "category_ko": "가격·이평·신고가"
  },
  {
   "name": "ema",
   "label": "지수이동평균",
   "desc": "대상 값의 N봉 지수 이동평균(span=N)",
   "params": [
    {
     "name": "src",
     "kind": "enum",
     "default": "close",
     "lo": null,
     "hi": null,
     "choices": [
      "open",
      "high",
      "low",
      "close",
      "volume",
      "value"
     ],
     "label": "대상 값"
    },
    {
     "name": "n",
     "kind": "int",
     "default": 20,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday",
    "tick"
   ],
   "timing": "t 포함",
   "compute": true,
   "category": "trend",
   "definition": "EMA_t = α·X_t + (1−α)·EMA_{t−1}, α = 2÷(n+1) (시작 n봉은 값 없음)",
   "example": "종가가 12일 지수이평 위",
   "live": true,
   "volume_based": false,
   "category_ko": "가격·이평·신고가"
  },
  {
   "name": "rsi",
   "label": "RSI",
   "desc": "단순평균 RSI — 기존 compute_rsi 와 같음(손실 0 이면 100)",
   "params": [
    {
     "name": "n",
     "kind": "int",
     "default": 14,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday",
    "tick"
   ],
   "timing": "t 포함",
   "compute": true,
   "category": "oscillator",
   "definition": "RSI = 100 − 100÷(1+평균상승÷평균하락), 평균은 n봉 단순평균(하락 0 이면 100)",
   "example": "RSI(14) ≥ 70",
   "live": true,
   "volume_based": false,
   "category_ko": "보조지표"
  },
  {
   "name": "highest",
   "label": "N봉 최고값",
   "desc": "직전 N봉 최고값(기본: 오늘 제외 → 돌파 판정용)",
   "params": [
    {
     "name": "src",
     "kind": "enum",
     "default": "high",
     "lo": null,
     "hi": null,
     "choices": [
      "open",
      "high",
      "low",
      "close",
      "volume",
      "value"
     ],
     "label": "대상 값"
    },
    {
     "name": "n",
     "kind": "int",
     "default": 20,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    },
    {
     "name": "include_current",
     "kind": "bool",
     "default": false,
     "lo": null,
     "hi": null,
     "choices": null,
     "label": "오늘 포함"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday",
    "tick"
   ],
   "timing": "기본 t 제외",
   "compute": true,
   "category": "trend",
   "definition": "직전 n봉 X 의 최댓값(기본 오늘 제외 — 돌파 기준선)",
   "example": "종가 > 20일 신고가(어제까지)",
   "live": true,
   "volume_based": false,
   "category_ko": "가격·이평·신고가"
  },
  {
   "name": "lowest",
   "label": "N봉 최저값",
   "desc": "직전 N봉 최저값(기본: 오늘 제외 → 이탈 판정용)",
   "params": [
    {
     "name": "src",
     "kind": "enum",
     "default": "low",
     "lo": null,
     "hi": null,
     "choices": [
      "open",
      "high",
      "low",
      "close",
      "volume",
      "value"
     ],
     "label": "대상 값"
    },
    {
     "name": "n",
     "kind": "int",
     "default": 20,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    },
    {
     "name": "include_current",
     "kind": "bool",
     "default": false,
     "lo": null,
     "hi": null,
     "choices": null,
     "label": "오늘 포함"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday",
    "tick"
   ],
   "timing": "기본 t 제외",
   "compute": true,
   "category": "trend",
   "definition": "직전 n봉 X 의 최솟값(기본 오늘 제외 — 이탈 기준선)",
   "example": "종가 < 10일 최저가(어제까지)",
   "live": true,
   "volume_based": false,
   "category_ko": "가격·이평·신고가"
  },
  {
   "name": "change_pct",
   "label": "N봉 등락률(%)",
   "desc": "종가의 N봉 전 대비 등락률(퍼센트)",
   "params": [
    {
     "name": "n",
     "kind": "int",
     "default": 1,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday",
    "tick"
   ],
   "timing": "t 포함",
   "compute": true,
   "category": "trend",
   "definition": "(C_t ÷ C_{t−n} − 1) × 100",
   "example": "5일 등락률 ≥ 10%",
   "live": true,
   "volume_based": false,
   "category_ko": "가격·이평·신고가"
  },
  {
   "name": "gap_pct",
   "label": "갭(%)",
   "desc": "당일 시가 ÷ 전일 종가 − 1 (퍼센트)",
   "params": [],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday"
   ],
   "timing": "당일 시가",
   "compute": true,
   "category": "trend",
   "definition": "(당일 시가 ÷ 전일 종가 − 1) × 100",
   "example": "갭 상승 3% 이상",
   "live": true,
   "volume_based": false,
   "category_ko": "가격·이평·신고가"
  },
  {
   "name": "atr",
   "label": "ATR",
   "desc": "진폭(TR)의 N봉 단순평균",
   "params": [
    {
     "name": "n",
     "kind": "int",
     "default": 14,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday",
    "tick"
   ],
   "timing": "t 포함",
   "compute": true,
   "category": "oscillator",
   "definition": "TR = max(H−L, |H−전일C|, |L−전일C|), ATR = TR 의 n봉 단순평균",
   "example": "ATR(14) ÷ 종가 ≥ 3%",
   "live": false,
   "volume_based": false,
   "category_ko": "보조지표"
  },
  {
   "name": "bb_upper",
   "label": "볼린저 상단",
   "desc": "종가 SMA + k × 표준편차(모표준편차)",
   "params": [
    {
     "name": "n",
     "kind": "int",
     "default": 20,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    },
    {
     "name": "k",
     "kind": "float",
     "default": 2.0,
     "lo": 0.1,
     "hi": 10.0,
     "choices": null,
     "label": "표준편차 배수"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday",
    "tick"
   ],
   "timing": "t 포함",
   "compute": true,
   "category": "oscillator",
   "definition": "종가 SMA_n + k × 표준편차(모표준편차)",
   "example": "종가 > 볼린저 상단(20, 2)",
   "live": true,
   "volume_based": false,
   "category_ko": "보조지표"
  },
  {
   "name": "bb_lower",
   "label": "볼린저 하단",
   "desc": "종가 SMA − k × 표준편차(모표준편차)",
   "params": [
    {
     "name": "n",
     "kind": "int",
     "default": 20,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    },
    {
     "name": "k",
     "kind": "float",
     "default": 2.0,
     "lo": 0.1,
     "hi": 10.0,
     "choices": null,
     "label": "표준편차 배수"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday",
    "tick"
   ],
   "timing": "t 포함",
   "compute": true,
   "category": "oscillator",
   "definition": "종가 SMA_n − k × 표준편차(모표준편차)",
   "example": "종가 < 볼린저 하단(20, 2)",
   "live": true,
   "volume_based": false,
   "category_ko": "보조지표"
  },
  {
   "name": "vol_ratio",
   "label": "거래량 배수",
   "desc": "거래량 ÷ 직전 N봉 평균(평균은 오늘 제외). 경계값·평균 0 처리가 `거래량 ≥ 평균 × 배수` 와 미세하게 다를 수 있음",
   "params": [
    {
     "name": "n",
     "kind": "int",
     "default": 20,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday",
    "tick"
   ],
   "timing": "평균 t 제외",
   "compute": true,
   "category": "volume",
   "definition": "V_t ÷ (직전 n봉 V 평균, 오늘 제외)",
   "example": "거래량이 20일 평균의 3배 이상",
   "live": false,
   "volume_based": true,
   "category_ko": "거래량·순위"
  },
  {
   "name": "value_rank",
   "label": "거래대금 순위",
   "desc": "최근 lookback일 평균 거래대금의 종목 간 순위(1=최대)",
   "params": [
    {
     "name": "lookback",
     "kind": "int",
     "default": 1,
     "lo": 1,
     "hi": 60,
     "choices": null,
     "label": "평균 일수"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio"
   ],
   "timing": "t 종가",
   "compute": true,
   "category": "volume",
   "definition": "최근 lookback일 평균 거래대금의 종목 간 순위(1=최대)",
   "example": "거래대금 순위 ≤ 30",
   "live": false,
   "volume_based": true,
   "category_ko": "거래량·순위"
  },
  {
   "name": "day_change_pct",
   "label": "당일 등락률(%)",
   "desc": "봉 종가의 전일 종가(D−1) 대비 등락률(퍼센트)",
   "params": [],
   "modes": [
    "intraday",
    "tick"
   ],
   "timing": "전일 종가 D−1",
   "compute": true,
   "category": "intraday",
   "definition": "(C_t ÷ 전일 종가(D−1) − 1) × 100",
   "example": "당일 등락률 ≥ 5%",
   "live": false,
   "volume_based": false,
   "category_ko": "분봉 전용"
  },
  {
   "name": "time",
   "label": "시각",
   "desc": "봉 끝 시각 HHMM (예: 09:05 → 905)",
   "params": [],
   "modes": [
    "intraday"
   ],
   "timing": "—",
   "compute": true,
   "category": "intraday",
   "definition": "봉 끝 시각 HHMM (09:05 → 905)",
   "example": "09:05 이후 10:30 이전",
   "live": false,
   "volume_based": false,
   "category_ko": "분봉 전용"
  },
  {
   "name": "cum_value",
   "label": "당일 누적 거래대금",
   "desc": "당일 누적 거래대금(날이 바뀌면 0부터)",
   "params": [],
   "modes": [
    "intraday"
   ],
   "timing": "t 까지",
   "compute": true,
   "category": "intraday",
   "definition": "당일 누적 거래대금(날이 바뀌면 0부터)",
   "example": "당일 누적 거래대금 ≥ 100억",
   "live": false,
   "volume_based": true,
   "category_ko": "분봉 전용"
  },
  {
   "name": "vwap",
   "label": "VWAP",
   "desc": "당일 누적 거래대금 ÷ 당일 누적 거래량(날이 바뀌면 다시 시작)",
   "params": [],
   "modes": [
    "intraday"
   ],
   "timing": "t 까지",
   "compute": true,
   "category": "intraday",
   "definition": "당일 누적 거래대금 ÷ 당일 누적 거래량(날이 바뀌면 다시 시작)",
   "example": "종가 > VWAP",
   "live": false,
   "volume_based": true,
   "category_ko": "분봉 전용"
  },
  {
   "name": "wma",
   "label": "가중이평",
   "desc": "WMA_n = Σ(i·X_{t−n+i}) ÷ Σi (i=1..n, 최근 봉이 가장 큰 가중)",
   "params": [
    {
     "name": "src",
     "kind": "enum",
     "default": "close",
     "lo": null,
     "hi": null,
     "choices": [
      "open",
      "high",
      "low",
      "close",
      "volume",
      "value"
     ],
     "label": "대상 값"
    },
    {
     "name": "n",
     "kind": "int",
     "default": 20,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday"
   ],
   "timing": "t 포함",
   "compute": true,
   "category": "trend",
   "definition": "WMA_n = Σ(i·X_{t−n+i}) ÷ Σi (i=1..n, 최근 봉이 가장 큰 가중)",
   "example": "종가가 20일 가중이평 위",
   "live": false,
   "volume_based": false,
   "category_ko": "가격·이평·신고가"
  },
  {
   "name": "ma_aligned",
   "label": "정배열(1/0)",
   "desc": "SMA_n1 > SMA_n2 > SMA_n3 [> SMA_n4] 이면 1 (n4=0 이면 3개만)",
   "params": [
    {
     "name": "n1",
     "kind": "int",
     "default": 5,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    },
    {
     "name": "n2",
     "kind": "int",
     "default": 20,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    },
    {
     "name": "n3",
     "kind": "int",
     "default": 60,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    },
    {
     "name": "n4",
     "kind": "int",
     "default": 0,
     "lo": 0,
     "hi": 500,
     "choices": null,
     "label": "네 번째 이평(0=안 씀)"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday"
   ],
   "timing": "t 포함",
   "compute": true,
   "category": "trend",
   "definition": "SMA_n1 > SMA_n2 > SMA_n3 [> SMA_n4] 이면 1 (n4=0 이면 3개만)",
   "example": "5·20·60일선 정배열",
   "live": false,
   "volume_based": false,
   "category_ko": "가격·이평·신고가"
  },
  {
   "name": "new_high",
   "label": "N봉 신고가 돌파(1/0)",
   "desc": "X_t > max(H_{t−n}..H_{t−1}) 이면 1 (직전 n봉 고가, 오늘 제외)",
   "params": [
    {
     "name": "n",
     "kind": "int",
     "default": 20,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    },
    {
     "name": "src",
     "kind": "enum",
     "default": "high",
     "lo": null,
     "hi": null,
     "choices": [
      "high",
      "close"
     ],
     "label": "비교 값"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday"
   ],
   "timing": "기준선 t 제외",
   "compute": true,
   "category": "trend",
   "definition": "X_t > max(H_{t−n}..H_{t−1}) 이면 1 (직전 n봉 고가, 오늘 제외)",
   "example": "20일 신고가 돌파",
   "live": false,
   "volume_based": false,
   "category_ko": "가격·이평·신고가"
  },
  {
   "name": "macd",
   "label": "MACD 선",
   "desc": "EMA_fast(C) − EMA_slow(C)",
   "params": [
    {
     "name": "fast",
     "kind": "int",
     "default": 12,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    },
    {
     "name": "slow",
     "kind": "int",
     "default": 26,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    },
    {
     "name": "sig",
     "kind": "int",
     "default": 9,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday"
   ],
   "timing": "t 포함",
   "compute": true,
   "category": "oscillator",
   "definition": "EMA_fast(C) − EMA_slow(C)",
   "example": "MACD > 0",
   "live": false,
   "volume_based": false,
   "category_ko": "보조지표"
  },
  {
   "name": "macd_signal",
   "label": "MACD 신호선",
   "desc": "EMA_sig(MACD)",
   "params": [
    {
     "name": "fast",
     "kind": "int",
     "default": 12,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    },
    {
     "name": "slow",
     "kind": "int",
     "default": 26,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    },
    {
     "name": "sig",
     "kind": "int",
     "default": 9,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday"
   ],
   "timing": "t 포함",
   "compute": true,
   "category": "oscillator",
   "definition": "EMA_sig(MACD)",
   "example": "MACD 가 신호선 상향 돌파",
   "live": false,
   "volume_based": false,
   "category_ko": "보조지표"
  },
  {
   "name": "stoch_k",
   "label": "스토캐스틱 %K(느린)",
   "desc": "빠른 %K=(C−LL_n)÷(HH_n−LL_n)×100 → 느린 %K=SMA_k(빠른 %K)",
   "params": [
    {
     "name": "n",
     "kind": "int",
     "default": 14,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    },
    {
     "name": "k",
     "kind": "int",
     "default": 3,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    },
    {
     "name": "d",
     "kind": "int",
     "default": 3,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday"
   ],
   "timing": "t 포함",
   "compute": true,
   "category": "oscillator",
   "definition": "빠른 %K=(C−LL_n)÷(HH_n−LL_n)×100 → 느린 %K=SMA_k(빠른 %K)",
   "example": "%K ≤ 20 에서 %D 상향 돌파",
   "live": false,
   "volume_based": false,
   "category_ko": "보조지표"
  },
  {
   "name": "stoch_d",
   "label": "스토캐스틱 %D",
   "desc": "SMA_d(느린 %K)",
   "params": [
    {
     "name": "n",
     "kind": "int",
     "default": 14,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    },
    {
     "name": "k",
     "kind": "int",
     "default": 3,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    },
    {
     "name": "d",
     "kind": "int",
     "default": 3,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday"
   ],
   "timing": "t 포함",
   "compute": true,
   "category": "oscillator",
   "definition": "SMA_d(느린 %K)",
   "example": "%K 가 %D 상향 돌파",
   "live": false,
   "volume_based": false,
   "category_ko": "보조지표"
  },
  {
   "name": "bb_width",
   "label": "볼린저 폭(%)",
   "desc": "(상단 − 하단) ÷ 중심 × 100",
   "params": [
    {
     "name": "n",
     "kind": "int",
     "default": 20,
     "lo": 1,
     "hi": 500,
     "choices": null,
     "label": "기간(봉)"
    },
    {
     "name": "k",
     "kind": "float",
     "default": 2.0,
     "lo": 0.1,
     "hi": 10.0,
     "choices": null,
     "label": "표준편차 배수"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio",
    "intraday"
   ],
   "timing": "t 포함",
   "compute": true,
   "category": "oscillator",
   "definition": "(상단 − 하단) ÷ 중심 × 100",
   "example": "밴드 폭 5% 이하(수축)",
   "live": false,
   "volume_based": false,
   "category_ko": "보조지표"
  },
  {
   "name": "rank_in_theme",
   "label": "테마 안 순위",
   "desc": "테마 그룹 안에서 이 종목의 그날 순위(1=최고, 여러 그룹이면 가장 좋은 순위) (구성은 현재 기준)",
   "params": [
    {
     "name": "by",
     "kind": "enum",
     "default": "value",
     "lo": null,
     "hi": null,
     "choices": [
      "value",
      "change"
     ],
     "label": "기준(대금/등락률)"
    },
    {
     "name": "min_members",
     "kind": "int",
     "default": 3,
     "lo": 1,
     "hi": 50,
     "choices": null,
     "label": "최소 종목 수"
    }
   ],
   "modes": [
    "daily_single",
    "daily_portfolio"
   ],
   "timing": "t 종가 · 구성은 현재",
   "compute": true,
   "category": "group",
   "definition": "rank_desc_{그룹 안}(대금 또는 등락률)",
   "example": "내 테마 안에서 대금 1위(대장)",
   "live": false,
   "volume_based": true,
   "category_ko": "테마·업종·시장"
  },
  {
   "name": "open_change_pct",
   "label": "당일 시가 대비(%)",
   "desc": "봉 종가 ÷ 당일 시가 − 1 (퍼센트). 당일 시가 = 그 날 첫 봉 시가",
   "params": [],
   "modes": [
    "intraday"
   ],
   "timing": "t 까지",
   "compute": true,
   "category": "intraday",
   "definition": "(C_t ÷ 당일 첫 봉 시가 − 1) × 100",
   "example": "시가 대비 3% 이상 상승 중",
   "live": false,
   "volume_based": false,
   "category_ko": "분봉 전용"
  },
  {
   "name": "day_high_break",
   "label": "당일 고점 돌파(1/0)",
   "desc": "t 봉이 당일 앞 봉들의 최고가를 넘으면 1(첫 봉은 값 없음)",
   "params": [
    {
     "name": "src",
     "kind": "enum",
     "default": "close",
     "lo": null,
     "hi": null,
     "choices": [
      "close",
      "high"
     ],
     "label": "비교 값(종가/고가)"
    }
   ],
   "modes": [
    "intraday"
   ],
   "timing": "앞 봉 t 제외",
   "compute": true,
   "category": "intraday",
   "definition": "X_t > max(당일 앞 봉 고가), X = 종가 또는 고가",
   "example": "종가가 당일 고점을 갱신",
   "live": false,
   "volume_based": false,
   "category_ko": "분봉 전용"
  }
 ],
 "fields": [
  "open",
  "high",
  "low",
  "close",
  "volume",
  "value"
 ],
 "modes": [
  "daily_single",
  "daily_portfolio",
  "intraday",
  "tick"
 ],
 "ops": [
  "gt",
  "gte",
  "lt",
  "lte",
  "cross_above",
  "cross_below",
  "cross_above_within",
  "cross_below_within",
  "is_true",
  "is_false"
 ],
 "market": {
  "indexes": [
   "kospi",
   "kosdaq"
  ],
  "names": [
   "close",
   "sma",
   "change_pct"
  ]
 },
 "tick_catalog": {
  "breakout_min": "N분 고점 돌파([t−w,t), t 제외)",
  "value_speed": "체결대금 속도(인과적 누적 평균 대비 ratio 배)",
  "buy_ratio": "틱룰 매수 비중(w분, 최소 비율)",
  "trade_strength": "체결강도(w초 틱룰 매수량÷매도량×100 이상)",
  "block_trades": "대량 체결(w초 안 한 번에 min_value 이상 체결 건수)",
  "daily_breakout": "현재가 > D−1까지 n일 최고가(틱 단위 N일 신고가 돌파)",
  "time_window": "시간대(time_from ~ time_to)"
 },
 "n_range": [
  1,
  500
 ],
 "categories": [
  {
   "key": "trend",
   "label": "가격·이평·신고가"
  },
  {
   "key": "oscillator",
   "label": "보조지표"
  },
  {
   "key": "candle",
   "label": "캔들"
  },
  {
   "key": "volume",
   "label": "거래량·순위"
  },
  {
   "key": "group",
   "label": "테마·업종·시장"
  },
  {
   "key": "intraday",
   "label": "분봉 전용"
  },
  {
   "key": "tick",
   "label": "틱 전용"
  },
  {
   "key": "position",
   "label": "포지션(청산만)"
  }
 ],
 "capabilities": {
  "timeframes": [
   "bar",
   "m1",
   "m3",
   "m5",
   "m10",
   "m15",
   "m30",
   "m60",
   "daily_prev",
   "daily_live"
  ],
  "condition_fields": [
   "hold"
  ],
  "group_fields": [
   "negate"
  ],
  "operand_kinds": [
   "field",
   "ind",
   "market",
   "const",
   "expr",
   "pos"
  ],
  "pos_names": [
   "return_pct",
   "bars_held",
   "minutes_held",
   "max_return_pct",
   "drawdown_pct",
   "entry_price"
  ],
  "formulas": false,
  "exit_fields": []
 }
}

export const realRecipes: Recipe[] = [
 {
  "id": "new_high_20",
  "category": "신고가",
  "title": "20일 신고가 돌파",
  "description": "종가가 지난 20일 최고가를 넘으면 산다. 10일 최저가 밑으로 내려가면 판다 — 신고가 추세매매의 가장 기본 꼴.",
  "modes": [
   "daily_portfolio",
   "daily_single"
  ],
  "needs": [],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "field",
      "name": "close"
     },
     "op": "gt",
     "right": {
      "kind": "ind",
      "name": "highest",
      "params": {
       "src": "high",
       "n": 20
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
      "name": "close"
     },
     "op": "lt",
     "right": {
      "kind": "ind",
      "name": "lowest",
      "params": {
       "src": "low",
       "n": 10
      }
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 },
 {
  "id": "high52_near",
  "category": "신고가",
  "title": "52주 신고가 근접",
  "description": "종가가 250거래일 최고가의 95% 이상이면 신고가 코앞으로 보고 산다. 20일선을 깨면 판다.",
  "modes": [
   "daily_portfolio",
   "daily_single"
  ],
  "needs": [],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "field",
      "name": "close"
     },
     "op": "gte",
     "right": {
      "kind": "ind",
      "name": "highest",
      "params": {
       "src": "high",
       "n": 250
      },
      "mul": 0.95
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
      "name": "close"
     },
     "op": "lt",
     "right": {
      "kind": "ind",
      "name": "sma",
      "params": {
       "src": "close",
       "n": 20
      }
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 },
 {
  "id": "new_high_volume",
  "category": "신고가",
  "title": "신고가 돌파 + 거래량 동반",
  "description": "20일 신고가를 돌파하면서 거래량이 20일 평균의 2배 이상이면 산다. 10일 최저가 밑으로 내려가면 판다.",
  "modes": [
   "daily_portfolio",
   "daily_single"
  ],
  "needs": [
   "indicator:new_high",
   "op:is_true"
  ],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "ind",
      "name": "new_high",
      "params": {
       "n": 20
      }
     },
     "op": "is_true"
    },
    {
     "left": {
      "kind": "ind",
      "name": "vol_ratio",
      "params": {
       "n": 20
      }
     },
     "op": "gte",
     "right": {
      "kind": "const",
      "value": 2
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
      "name": "close"
     },
     "op": "lt",
     "right": {
      "kind": "ind",
      "name": "lowest",
      "params": {
       "src": "low",
       "n": 10
      }
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 },
 {
  "id": "pullback_ma20",
  "category": "이동평균",
  "title": "상승 추세 눌림목 반등",
  "description": "60일선 위(상승 추세)에서 눌렸던 종가가 20일선을 다시 넘으면 산다. 20일선 아래로 밀리면 판다.",
  "modes": [
   "daily_portfolio",
   "daily_single"
  ],
  "needs": [],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "field",
      "name": "close"
     },
     "op": "gt",
     "right": {
      "kind": "ind",
      "name": "sma",
      "params": {
       "src": "close",
       "n": 60
      }
     }
    },
    {
     "left": {
      "kind": "field",
      "name": "close"
     },
     "op": "cross_above",
     "right": {
      "kind": "ind",
      "name": "sma",
      "params": {
       "src": "close",
       "n": 20
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
      "name": "close"
     },
     "op": "cross_below",
     "right": {
      "kind": "ind",
      "name": "sma",
      "params": {
       "src": "close",
       "n": 20
      }
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 },
 {
  "id": "golden_cross",
  "category": "이동평균",
  "title": "이평 골든크로스",
  "description": "5일선이 20일선을 아래에서 위로 뚫으면 산다. 다시 아래로 뚫으면 판다.",
  "modes": [
   "daily_portfolio",
   "daily_single"
  ],
  "needs": [],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "ind",
      "name": "sma",
      "params": {
       "src": "close",
       "n": 5
      }
     },
     "op": "cross_above",
     "right": {
      "kind": "ind",
      "name": "sma",
      "params": {
       "src": "close",
       "n": 20
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
      "kind": "ind",
      "name": "sma",
      "params": {
       "src": "close",
       "n": 5
      }
     },
     "op": "cross_below",
     "right": {
      "kind": "ind",
      "name": "sma",
      "params": {
       "src": "close",
       "n": 20
      }
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 },
 {
  "id": "ma_aligned_first",
  "category": "이동평균",
  "title": "이평 정배열 첫 돌파",
  "description": "5·20·60일 이동평균이 정배열이 되는 첫날(어제까지는 정배열이 아니었던 날) 산다. 20일선을 깨면 판다.",
  "modes": [
   "daily_portfolio",
   "daily_single"
  ],
  "needs": [
   "indicator:ma_aligned",
   "op:is_true"
  ],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "ind",
      "name": "ma_aligned",
      "params": {
       "n1": 5,
       "n2": 20,
       "n3": 60
      }
     },
     "op": "is_true"
    },
    {
     "left": {
      "kind": "ind",
      "name": "ma_aligned",
      "params": {
       "n1": 5,
       "n2": 20,
       "n3": 60
      },
      "offset": 1
     },
     "op": "is_false"
    }
   ]
  },
  "exit": {
   "logic": "any",
   "items": [
    {
     "left": {
      "kind": "field",
      "name": "close"
     },
     "op": "lt",
     "right": {
      "kind": "ind",
      "name": "sma",
      "params": {
       "src": "close",
       "n": 20
      }
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 },
 {
  "id": "cross_within",
  "category": "이동평균",
  "title": "최근 3봉 안 골든크로스 + 정배열 유지",
  "description": "5일선이 20일선을 최근 3봉 안에 위로 뚫었고 종가가 60일선 위이면 산다. 5일선이 20일선 아래로 내려가면 판다.",
  "modes": [
   "daily_portfolio",
   "daily_single"
  ],
  "needs": [
   "op:cross_above_within"
  ],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "ind",
      "name": "sma",
      "params": {
       "src": "close",
       "n": 5
      }
     },
     "op": "cross_above_within",
     "right": {
      "kind": "ind",
      "name": "sma",
      "params": {
       "src": "close",
       "n": 20
      }
     },
     "within": 3
    },
    {
     "left": {
      "kind": "field",
      "name": "close"
     },
     "op": "gt",
     "right": {
      "kind": "ind",
      "name": "sma",
      "params": {
       "src": "close",
       "n": 60
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
      "kind": "ind",
      "name": "sma",
      "params": {
       "src": "close",
       "n": 5
      }
     },
     "op": "lt",
     "right": {
      "kind": "ind",
      "name": "sma",
      "params": {
       "src": "close",
       "n": 20
      }
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 },
 {
  "id": "volume_surge",
  "category": "거래량·거래대금",
  "title": "거래량 급증 양봉",
  "description": "거래량이 20일 평균의 3배 이상이면서 3% 넘게 오른 날 산다. 5일선 아래로 내려가면 판다.",
  "modes": [
   "daily_portfolio",
   "daily_single"
  ],
  "needs": [],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "ind",
      "name": "vol_ratio",
      "params": {
       "n": 20
      }
     },
     "op": "gte",
     "right": {
      "kind": "const",
      "value": 3
     }
    },
    {
     "left": {
      "kind": "ind",
      "name": "change_pct",
      "params": {
       "n": 1
      }
     },
     "op": "gt",
     "right": {
      "kind": "const",
      "value": 3
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
      "name": "close"
     },
     "op": "lt",
     "right": {
      "kind": "ind",
      "name": "sma",
      "params": {
       "src": "close",
       "n": 5
      }
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 },
 {
  "id": "gap_hold",
  "category": "갭",
  "title": "갭 상승 유지",
  "description": "전일 종가보다 3% 이상 높게 시작해 그 봉을 양봉으로 끝내면 산다(갭이 메워지지 않은 것). 5일선 아래로 밀리면 판다.",
  "modes": [
   "daily_portfolio",
   "daily_single",
   "intraday"
  ],
  "needs": [],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "ind",
      "name": "gap_pct"
     },
     "op": "gte",
     "right": {
      "kind": "const",
      "value": 3
     }
    },
    {
     "left": {
      "kind": "field",
      "name": "close"
     },
     "op": "gt",
     "right": {
      "kind": "field",
      "name": "open"
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
      "name": "close"
     },
     "op": "lt",
     "right": {
      "kind": "ind",
      "name": "sma",
      "params": {
       "src": "close",
       "n": 5
      }
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 },
 {
  "id": "macd_cross",
  "category": "보조지표",
  "title": "MACD 골든크로스",
  "description": "MACD 선이 신호선을 아래에서 위로 뚫으면 산다. 다시 아래로 뚫으면 판다.",
  "modes": [
   "daily_portfolio",
   "daily_single",
   "intraday"
  ],
  "needs": [
   "indicator:macd"
  ],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "ind",
      "name": "macd",
      "params": {
       "fast": 12,
       "slow": 26,
       "sig": 9
      }
     },
     "op": "cross_above",
     "right": {
      "kind": "ind",
      "name": "macd_signal",
      "params": {
       "fast": 12,
       "slow": 26,
       "sig": 9
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
      "kind": "ind",
      "name": "macd",
      "params": {
       "fast": 12,
       "slow": 26,
       "sig": 9
      }
     },
     "op": "cross_below",
     "right": {
      "kind": "ind",
      "name": "macd_signal",
      "params": {
       "fast": 12,
       "slow": 26,
       "sig": 9
      }
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 },
 {
  "id": "rsi_rebound",
  "category": "보조지표",
  "title": "RSI 과매도 반등",
  "description": "RSI(14)가 30을 아래에서 위로 뚫으면 산다. 70을 넘으면 판다.",
  "modes": [
   "daily_portfolio",
   "daily_single"
  ],
  "needs": [],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "ind",
      "name": "rsi",
      "params": {
       "n": 14
      }
     },
     "op": "cross_above",
     "right": {
      "kind": "const",
      "value": 30
     }
    }
   ]
  },
  "exit": {
   "logic": "any",
   "items": [
    {
     "left": {
      "kind": "ind",
      "name": "rsi",
      "params": {
       "n": 14
      }
     },
     "op": "gt",
     "right": {
      "kind": "const",
      "value": 70
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 },
 {
  "id": "bb_squeeze_break",
  "category": "보조지표",
  "title": "볼린저 수축 뒤 상단 돌파",
  "description": "밴드 폭이 좁아진 뒤(폭 10% 이하) 종가가 상단을 넘으면 산다. 중심선 아래로 내려가면 판다.",
  "modes": [
   "daily_portfolio",
   "daily_single"
  ],
  "needs": [
   "indicator:bb_width"
  ],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "ind",
      "name": "bb_width",
      "params": {
       "n": 20,
       "k": 2.0
      }
     },
     "op": "lte",
     "right": {
      "kind": "const",
      "value": 10
     }
    },
    {
     "left": {
      "kind": "field",
      "name": "close"
     },
     "op": "gt",
     "right": {
      "kind": "ind",
      "name": "bb_upper",
      "params": {
       "n": 20,
       "k": 2.0
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
      "name": "close"
     },
     "op": "lt",
     "right": {
      "kind": "ind",
      "name": "sma",
      "params": {
       "src": "close",
       "n": 20
      }
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 },
 {
  "id": "bb_rebound",
  "category": "보조지표",
  "title": "볼린저 하단 복귀",
  "description": "종가가 볼린저 하단 밖에 있다가 안으로 돌아오면 산다. 상단을 넘으면 판다.",
  "modes": [
   "daily_portfolio",
   "daily_single"
  ],
  "needs": [],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "field",
      "name": "close"
     },
     "op": "cross_above",
     "right": {
      "kind": "ind",
      "name": "bb_lower",
      "params": {
       "n": 20,
       "k": 2.0
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
      "name": "close"
     },
     "op": "gt",
     "right": {
      "kind": "ind",
      "name": "bb_upper",
      "params": {
       "n": 20,
       "k": 2.0
      }
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 },
 {
  "id": "stoch_rebound",
  "category": "보조지표",
  "title": "스토캐스틱 과매도 반등",
  "description": "스토캐스틱 %K 가 30 아래에서 %D 를 위로 뚫으면 산다. 80을 넘으면 판다.",
  "modes": [
   "daily_portfolio",
   "daily_single",
   "intraday"
  ],
  "needs": [
   "indicator:stoch_k"
  ],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "ind",
      "name": "stoch_k"
     },
     "op": "cross_above",
     "right": {
      "kind": "ind",
      "name": "stoch_d"
     }
    },
    {
     "left": {
      "kind": "ind",
      "name": "stoch_k"
     },
     "op": "lt",
     "right": {
      "kind": "const",
      "value": 30
     }
    }
   ]
  },
  "exit": {
   "logic": "any",
   "items": [
    {
     "left": {
      "kind": "ind",
      "name": "stoch_k"
     },
     "op": "gt",
     "right": {
      "kind": "const",
      "value": 80
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 },
 {
  "id": "intraday_high_break",
  "category": "분봉",
  "title": "분봉 N봉 신고가 돌파 (VWAP 위)",
  "description": "종가가 지난 20봉 최고가를 넘고 그날 VWAP 위에 있으면 산다. VWAP 아래로 내려가면 판다.",
  "modes": [
   "intraday"
  ],
  "needs": [],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "field",
      "name": "close"
     },
     "op": "gt",
     "right": {
      "kind": "ind",
      "name": "highest",
      "params": {
       "src": "high",
       "n": 20
      }
     }
    },
    {
     "left": {
      "kind": "field",
      "name": "close"
     },
     "op": "gt",
     "right": {
      "kind": "ind",
      "name": "vwap"
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
      "name": "close"
     },
     "op": "lt",
     "right": {
      "kind": "ind",
      "name": "vwap"
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 },
 {
  "id": "intraday_daily_high_break",
  "category": "분봉",
  "title": "분봉 N일 신고가 돌파",
  "description": "분봉 종가가 전일까지 20거래일 일봉 최고가(어제 포함)를 넘으면 산다 — 분봉 실행에서 일봉 신고가를 쓴다. VWAP 아래로 내려가면 판다. ※ 시간 단위 '일봉(전일 확정)'의 최고가는 '어제 포함' 옵션을 켜야 정확히 전일까지 20일이다.",
  "modes": [
   "intraday"
  ],
  "needs": [
   "timeframes"
  ],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "field",
      "name": "close"
     },
     "op": "gt",
     "right": {
      "kind": "ind",
      "name": "highest",
      "params": {
       "src": "high",
       "n": 20,
       "include_current": true
      },
      "tf": "daily_prev"
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
      "name": "close"
     },
     "op": "lt",
     "right": {
      "kind": "ind",
      "name": "vwap"
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 },
 {
  "id": "intraday_rsi_dip",
  "category": "분봉",
  "title": "분봉 눌림 뒤 RSI 반등",
  "description": "당일 3% 이상 오른 종목이 눌렸다가 RSI(14)가 40을 다시 넘으면 산다. 70을 넘으면 판다.",
  "modes": [
   "intraday"
  ],
  "needs": [],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "ind",
      "name": "day_change_pct"
     },
     "op": "gte",
     "right": {
      "kind": "const",
      "value": 3
     }
    },
    {
     "left": {
      "kind": "ind",
      "name": "rsi",
      "params": {
       "n": 14
      }
     },
     "op": "cross_above",
     "right": {
      "kind": "const",
      "value": 40
     }
    }
   ]
  },
  "exit": {
   "logic": "any",
   "items": [
    {
     "left": {
      "kind": "ind",
      "name": "rsi",
      "params": {
       "n": 14
      }
     },
     "op": "gt",
     "right": {
      "kind": "const",
      "value": 70
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 },
 {
  "id": "intraday_open_strength",
  "category": "분봉",
  "title": "분봉 시가 대비 강세 + 당일 고가 돌파",
  "description": "시가보다 2% 넘게 올라 있고 당일 앞 봉들의 고가를 넘으면 산다. VWAP 아래로 내려가면 판다.",
  "modes": [
   "intraday"
  ],
  "needs": [
   "indicator:open_change_pct",
   "indicator:day_high_break",
   "op:is_true"
  ],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "ind",
      "name": "open_change_pct"
     },
     "op": "gte",
     "right": {
      "kind": "const",
      "value": 2
     }
    },
    {
     "left": {
      "kind": "ind",
      "name": "day_high_break",
      "params": {
       "src": "high"
      }
     },
     "op": "is_true"
    }
   ]
  },
  "exit": {
   "logic": "any",
   "items": [
    {
     "left": {
      "kind": "field",
      "name": "close"
     },
     "op": "lt",
     "right": {
      "kind": "ind",
      "name": "vwap"
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 },
 {
  "id": "theme_leader",
  "category": "테마",
  "title": "테마 대장 (테마 안 상승률 1위)",
  "description": "소피증권 테마 그룹 안에서 그날 상승률 1위이고 3% 이상 오르면 산다. 5일선 아래로 내려가면 판다. ※ 테마 구성은 현재 기준(과거에 그대로 적용).",
  "modes": [
   "daily_portfolio",
   "daily_single"
  ],
  "needs": [
   "indicator:rank_in_theme"
  ],
  "entry": {
   "logic": "all",
   "items": [
    {
     "left": {
      "kind": "ind",
      "name": "rank_in_theme",
      "params": {
       "by": "change"
      }
     },
     "op": "lte",
     "right": {
      "kind": "const",
      "value": 1
     }
    },
    {
     "left": {
      "kind": "ind",
      "name": "change_pct",
      "params": {
       "n": 1
      }
     },
     "op": "gt",
     "right": {
      "kind": "const",
      "value": 3
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
      "name": "close"
     },
     "op": "lt",
     "right": {
      "kind": "ind",
      "name": "sma",
      "params": {
       "src": "close",
       "n": 5
      }
     }
    }
   ]
  },
  "available": true,
  "unavailable_reason": null
 }
]
