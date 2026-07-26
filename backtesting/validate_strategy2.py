"""전략 2번(oversold_strategy.py, SK하이닉스 과대낙폭 3단 분할매수)의 백테스트 검증.

기존 함수만 조합한다(신규 시뮬레이션 로직은 에피소드 루프 하나뿐):
- data_loader._resample_minute / oversold_trading_loop._filter_regular_session
  (1분봉 -> 정규장 15분봉, 실전 코드와 동일한 리샘플)
- oversold_strategy.compute_ma / compute_tier_prices / next_entry_tier /
  should_exit_by_touch / should_exit_by_hard_stop / should_exit_by_time
  (oversold_trading_loop.process_oversold_entry_once/process_oversold_exit_once와
  같은 우선순위: 매 봉마다 청산 조건 먼저 확인 → 그 다음 신규/추가 분할매수 확인)
- breakout_reversal.DEFAULT_COMMISSION_RATE/DEFAULT_SLIPPAGE_RATE (비용 모델 재사용)

전략1과 달리 ML 필터/동시보유 슬롯이 없다 — 항상 SK하이닉스 단일 종목, 에피소드
하나씩 순차 진행이라 portfolio_sim이 아니라 완결된 에피소드 목록만으로 집계한다.

실행: python -m backtesting.validate_strategy2
"""
import argparse
import os

import pandas as pd

from .breakout_reversal import DEFAULT_COMMISSION_RATE, DEFAULT_SLIPPAGE_RATE, DEFAULT_TAX_RATE
from .data_loader import _resample_minute
from .oversold_strategy import (
    BAR_INTERVAL_MINUTES,
    HARD_STOP_PCT,
    MA_WINDOW,
    STOCK_CODE,
    TIER_BAND_PCTS,
    TIME_EXIT_TRADING_DAYS,
    compute_ma,
    compute_tier_prices,
    next_entry_tier,
    should_exit_by_hard_stop,
    should_exit_by_time,
    should_exit_by_touch,
)
from .oversold_trading_loop import _filter_regular_session


def load_15min_candles(data_dir: str = "data", code: str = STOCK_CODE) -> pd.DataFrame:
    """실전(compute_current_ma)과 동일한 방식으로 로컬 1분봉을 정규장만 걸러 15분봉으로
    리샘플한다."""
    minute_df = pd.read_csv(os.path.join(data_dir, "stocks", "minute", f"{code}.csv"), index_col=0, parse_dates=True)
    return _resample_minute(_filter_regular_session(minute_df), BAR_INTERVAL_MINUTES)


def simulate_all_episodes(
    candles_15m: pd.DataFrame,
    tier_band_pcts: tuple[float, ...] = TIER_BAND_PCTS,
    hard_stop_pct: float = HARD_STOP_PCT,
    time_exit_trading_days: int = TIME_EXIT_TRADING_DAYS,
    ma_window: int = MA_WINDOW,
    commission_rate: float = DEFAULT_COMMISSION_RATE,
    slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
    tax_rate: float = DEFAULT_TAX_RATE,
) -> list[dict]:
    """oversold_trading_loop과 같은 순서(청산 확인 → 진입/추가매수 확인)로 15분봉을
    순회하며 완결된 에피소드(3단 이내 분할매수 ~ 전량청산)를 모두 기록한다.

    봉 단위 근사: 밴드/60선 "터치"는 실전은 실시간 현재가로 판정하지만 여기선
    OHLC만 있어 저가(매수 밴드)/고가(60선 익절)가 그 수준에 닿았는지로 근사하고,
    체결가는 해당 수준 자체(+슬리피지)로 가정한다 — 유동성 높은 대형주 전제(전략
    설명 docstring과 동일한 가정).

    같은 봉(폴링)에서 막 청산된 포지션을 즉시 재진입하지 않는다 — 하드스톱
    발동가는 항상 다음 미체결 밴드가보다 낮아 이 가드가 없으면 손절 직후 같은
    가격에 곧바로 재매수하는 휩쏘가 벌어진다(oversold_trading_loop.py도 동일하게
    수정됨, 회귀 테스트: test_validate_strategy2.py).
    """
    ma = compute_ma(candles_15m, window=ma_window)

    episodes: list[dict] = []
    filled_prices: list[float] = []
    entry_date = None
    entry_time = None

    for idx in candles_15m.index:
        ma_value = ma.at[idx]
        if pd.isna(ma_value):
            continue
        bar = candles_15m.loc[idx]
        today = idx.date()
        just_closed = False

        if filled_prices:
            avg_entry_price = sum(filled_prices) / len(filled_prices)
            exit_price, reason = None, None
            if should_exit_by_hard_stop(bar["low"], avg_entry_price):
                # 하드스톱(손실 방어)을 60선 터치(익절)보다 먼저 확인한다 — 한 봉 안에서
                # 저가가 하드스톱을, 고가가 60선을 동시에 찍는 근사치 한계 상황에서
                # 손실 방어가 익절 판정보다 우선해야 한다(리스크 원칙과 동일한 우선순위).
                stop_level = avg_entry_price * (1 - hard_stop_pct)
                exit_price, reason = stop_level * (1 - slippage_rate), "hard_stop"
            elif should_exit_by_touch(bar["high"], ma_value):
                exit_price, reason = ma_value * (1 - slippage_rate), "touch_ma"
            elif entry_date and should_exit_by_time(entry_date, today, time_exit_trading_days):
                exit_price, reason = bar["close"] * (1 - slippage_rate), "time_exit"

            if reason is not None:
                net_pct = (exit_price - avg_entry_price) / avg_entry_price - commission_rate * 2 - tax_rate
                episodes.append(
                    {
                        "entry_time": entry_time, "entry_date": entry_date, "exit_time": idx,
                        "n_tiers": len(filled_prices), "avg_entry_price": avg_entry_price,
                        "exit_price": exit_price, "exit_reason": reason, "net_pct": net_pct,
                    }
                )
                filled_prices, entry_date, entry_time = [], None, None
                just_closed = True

        # 하드스톱 발동가(평단*(1-hard_stop_pct))는 항상 다음 미체결 밴드가보다 낮아,
        # 방금 청산과 같은 봉에서 진입을 확인하면 그 자리에서 곧바로 재매수(휩쏘)돼버린다
        # (oversold_trading_loop.run_oversold_trading_loop과 동일한 이유로 동일하게 수정).
        # 이번 봉에서 막 청산됐으면 진입 확인을 건너뛰고 다음 봉(새 가격)부터 다시 본다.
        filled_tier_count = len(filled_prices)
        tier = None if just_closed else next_entry_tier(filled_tier_count, bar["low"], ma_value)
        if tier is not None:
            fill_price = compute_tier_prices(ma_value)[tier - 1] * (1 + slippage_rate)
            filled_prices.append(fill_price)
            if filled_tier_count == 0:
                entry_date, entry_time = today, idx

    # 데이터 끝에서도 포지션이 열려있으면 마지막 종가로 강제청산(백테스트 구간 경계
    # 아티팩트일 뿐 — 실제 청산 신호가 아니라 리포트에서 "eod_of_data"로 구분 표기)
    if filled_prices:
        avg_entry_price = sum(filled_prices) / len(filled_prices)
        last_idx = candles_15m.index[-1]
        exit_price = candles_15m["close"].iloc[-1] * (1 - slippage_rate)
        net_pct = (exit_price - avg_entry_price) / avg_entry_price - commission_rate * 2 - tax_rate
        episodes.append(
            {
                "entry_time": entry_time, "entry_date": entry_date, "exit_time": last_idx,
                "n_tiers": len(filled_prices), "avg_entry_price": avg_entry_price,
                "exit_price": exit_price, "exit_reason": "eod_of_data", "net_pct": net_pct,
            }
        )

    return episodes


def compute_episode_metrics(episodes: list[dict], risk_unit_pct: float = HARD_STOP_PCT) -> dict:
    """에피소드 목록에서 승률/손익비/평균R/누적수익률(단순합산, PDF와 동일 방식)/
    MDD(단순합산 equity 기준)를 집계."""
    n = len(episodes)
    if n == 0:
        return {"n_trades": 0, "win_rate_pct": 0.0, "profit_factor": 0.0, "avg_r_multiple": 0.0,
                "total_return_pct_simple_sum": 0.0, "mdd_pct": 0.0, "avg_holding_days": 0.0}

    pcts = [e["net_pct"] for e in episodes]
    wins = [p for p in pcts if p > 0]
    losses = [p for p in pcts if p <= 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)

    equity = 1.0
    peak = equity
    mdd = 0.0
    for p in pcts:
        equity += p  # 단순합산(비복리) — PDF 성과 표기 방식과 비교하기 위함
        peak = max(peak, equity)
        if peak > 0:
            mdd = max(mdd, (peak - equity) / peak)

    holding_days = [
        (e["exit_time"].normalize() - e["entry_time"].normalize()).days + 1 for e in episodes if e["entry_time"]
    ]

    return {
        "n_trades": n,
        "win_rate_pct": len(wins) / n * 100,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
        "avg_r_multiple": (sum(pcts) / n) / risk_unit_pct,
        "total_return_pct_simple_sum": sum(pcts) * 100,
        "mdd_pct": mdd * 100,
        "avg_holding_days": sum(holding_days) / len(holding_days) if holding_days else 0.0,
    }


def _fmt_pf(pf: float) -> str:
    return "inf" if pf == float("inf") else f"{pf:.2f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--code", default=STOCK_CODE)
    args = parser.parse_args()

    candles = load_15min_candles(args.data_dir, args.code)
    print(f"15분봉 {len(candles)}개, 기간 {candles.index.min()} ~ {candles.index.max()}")

    episodes = simulate_all_episodes(candles)
    metrics = compute_episode_metrics(episodes)

    print("\n=== strategy_2 성과 요약 (전략 배정자금 100% 기준, 단순합산) ===")
    print(
        f"거래수 {metrics['n_trades']} 승률 {metrics['win_rate_pct']:.1f}% "
        f"손익비 {_fmt_pf(metrics['profit_factor'])} 평균R {metrics['avg_r_multiple']:.2f} "
        f"누적수익 {metrics['total_return_pct_simple_sum']:.1f}% MDD {metrics['mdd_pct']:.1f}% "
        f"평균보유 {metrics['avg_holding_days']:.1f}일"
    )
    print("\n=== 에피소드별 상세 ===")
    for e in episodes:
        print(
            f"  {e['entry_date']} {e['n_tiers']}단 진입, 청산 {e['exit_time']} [{e['exit_reason']}] "
            f"순손익 {e['net_pct']*100:+.2f}%"
        )


if __name__ == "__main__":
    main()
