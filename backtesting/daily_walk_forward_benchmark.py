"""daily_walk_forward.py 결과를 코스피 대비로 재본다 — 신고가추세 3전략의 폴드별
방향이 시장국면(코스피 상승/하락)과 겹치면 베타, 국면과 무관하게 흩어지면 알파다.

daily_walk_forward.simulate_and_bucket_by_fold가 만든 폴드별 거래를 그대로 재사용한다
(신규 시뮬레이션 로직 없음, 숫자가 이전 리포트와 어긋나지 않도록).

두 가지 비교를 나란히 낸다:
1. 단순 비교: 같은 구간 코스피 buy&hold 수익률 대비 초과수익
2. 노출조정 비교: 전략이 실제로 포지션을 들고 있던 "거래일에만" 코스피를 들고
   있었다면 얻었을 복리수익률(그 날짜들의 실제 코스피 일간수익률을 그대로 곱함 —
   선형 스케일링이 아니다) 대비 초과수익. 노출이 랠리에 몰려 있으면 이 벤치마크도
   같이 커지므로, 단순 비교보다 "노출을 코스피로 대체했어도 이 정도는 벌었다"는
   착시를 막는다.

실행: python -m backtesting.daily_walk_forward_benchmark
"""
import argparse
from datetime import date, timedelta

import pandas as pd

from . import daily_walk_forward as dwf
from .metrics import buy_and_hold_return_pct

KOSPI_INDEX_CODE = "001"  # final_strategy.py와 동일 종목(코스피 지수).


def load_kospi(data_dir: str = dwf.DATA_DIR) -> pd.DataFrame:
    return pd.read_csv(f"{data_dir}/index/daily/{KOSPI_INDEX_CODE}.csv", index_col=0, parse_dates=True)


def _fold_kospi_return(kospi: pd.DataFrame, test_start: date, test_end: date) -> float | None:
    window = kospi.loc[str(test_start):str(test_end)]
    if len(window) < 2:
        return None
    return buy_and_hold_return_pct(window)


def _exposure_days(trades: list, test_start: date, test_end: date) -> set:
    """포지션이 열려 있던 날짜(진입~청산, 폴드 구간으로 클립)의 합집합 — 여러 종목이
    겹쳐 있어도 "시장에 나가 있던 날"은 하루로 센다(시간 비중이지 자본가중 비중이 아님)."""
    days: set = set()
    for t in trades:
        if t.pnl is None:
            continue
        start, end = max(t.entry_date, test_start), min(t.exit_date, test_end)
        d = start
        while d <= end:
            days.add(d)
            d += timedelta(days=1)
    return days


def _exposure_adjusted_kospi_return(kospi: pd.DataFrame, exposure_days: set) -> tuple[float | None, float | None]:
    """(노출조정 코스피 복리수익률, 노출 거래일 수)를 반환. 코스피의 거래일 캘린더를
    기준으로 exposure_days와 교집합만 쓴다(주말 등은 코스피 인덱스에 아예 없어
    자동으로 빠진다)."""
    if not exposure_days:
        return None, 0
    daily_ret = kospi["close"].pct_change()
    mask = daily_ret.index.normalize().isin(pd.to_datetime(sorted(exposure_days)))
    exposed_returns = daily_ret[mask]
    if exposed_returns.empty:
        return None, 0
    compounded = (float((1 + exposed_returns).prod()) - 1) * 100
    return compounded, len(exposed_returns)


def compare_to_kospi(
    universe: dict[str, pd.DataFrame],
    strategy,
    splits: list,
    horizon_end: date,
    kospi: pd.DataFrame,
    params: dict = dwf.PARAMS,
) -> pd.DataFrame:
    fold_trades, _ = dwf.simulate_and_bucket_by_fold(universe, strategy, splits, horizon_end, params)

    rows = []
    for i, sp in enumerate(splits, 1):
        trades = fold_trades[i - 1]
        n_trades = len([t for t in trades if t.pnl is not None])
        reliable = n_trades >= dwf.MIN_FOLD_TRADES

        strat_pm = dwf._portfolio_return_mdd(trades, [""] * len(trades)) if n_trades else {"total_return_pct": 0.0}
        strat_return = strat_pm["total_return_pct"]

        kospi_return = _fold_kospi_return(kospi, sp.test_start, sp.test_end)
        kospi_trading_days = len(kospi.loc[str(sp.test_start):str(sp.test_end)])

        exp_days = _exposure_days(trades, sp.test_start, sp.test_end)
        exp_kospi_return, exposed_trading_days = _exposure_adjusted_kospi_return(kospi, exp_days)
        exposure_pct = (exposed_trading_days / kospi_trading_days * 100) if kospi_trading_days else None

        rows.append({
            "fold": i, "test_start": sp.test_start, "test_end": sp.test_end,
            "n_trades": n_trades, "reliable(>=30건)": reliable,
            "strategy_return_pct": round(strat_return, 2),
            "kospi_return_pct": None if kospi_return is None else round(kospi_return, 2),
            "excess_vs_kospi_pct": None if kospi_return is None else round(strat_return - kospi_return, 2),
            "exposure_pct": None if exposure_pct is None else round(exposure_pct, 1),
            "kospi_exposure_adjusted_pct": None if exp_kospi_return is None else round(exp_kospi_return, 2),
            "excess_vs_exposure_adjusted_pct": None if exp_kospi_return is None else round(strat_return - exp_kospi_return, 2),
        })
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=dwf.DATA_DIR)
    parser.add_argument("--train-days", type=int, default=730)
    parser.add_argument("--test-days", type=int, default=90)
    parser.add_argument("--step-days", type=int, default=90)
    args = parser.parse_args()

    universe = dwf.load_universe(args.data_dir)
    overall_start, overall_end, holdout_start = dwf.compute_holdout_start(universe)
    horizon_end = holdout_start - timedelta(days=1)
    splits = dwf.wf_split(overall_start, holdout_start, args.train_days, args.test_days, args.step_days)
    kospi = load_kospi(args.data_dir)
    print(f"코스피 데이터 커버기간: {kospi.index.min().date()} ~ {kospi.index.max().date()}")
    print(f"폴드 {len(splits)}개, {overall_start} ~ {holdout_start}\n")

    pd.set_option("display.width", 220)
    for strategy in dwf.STRATEGIES:
        df = compare_to_kospi(universe, strategy, splits, horizon_end, kospi)
        print(f"=== {strategy.name} (n_day_high={dwf.PARAMS['n_day_high']}) vs KOSPI ===")
        print(df.to_string(index=False))
        print()


if __name__ == "__main__":
    main()
