"""일봉 신고가추세매매 후보 3종(new_high_swing/pullback_reentry/vcp_breakout)의
워크포워드 검증 — ML 게이트 없이 기반 전략만 먼저 잰다(전략1의 교훈: 기반이
마이너스면 ML로 못 살린다).

기존 함수만 조합한다(신규 시뮬레이션 로직 없음):
- ml.walk_forward.split (IS/OOS 날짜 분할, step_days>=test_days assert 포함)
- 로컬 일봉 CSV 로딩(scan_all_trades와 같은 방식 — load_universe 함수 docstring 참고)
- simulator.run (신호 -> 체결, 비용 반영)
- portfolio_sim.simulate_slot_portfolio (총수익/MDD 산출용 자본배분 — 슬롯 수는
  이 세 전략에 대해 아직 리스크 에이전트가 정한 운용규칙이 없어 placeholder)

분봉(strategy_1)은 종목별 표본이 중앙값 3개월뿐이라 폴드가 3개로 묶여 "폴드 하나가
견인한 결과"를 통계적으로 못 걸러냈다 — 일봉은 종목당 7년치가 있어 폴드를 15~20개로
늘려 그 판정을 가능하게 한다.

고정 홀드아웃: 전체 기간의 마지막 20%는 이 스크립트가 만드는 워크포워드 폴드
생성 범위에 아예 포함하지 않는다(wf_split 호출 시 end를 홀드아웃 시작 이전으로
자름) — 마지막 20%는 튜닝이 다 끝난 뒤 딱 한 번만 연다.

실행: python -m backtesting.daily_walk_forward
"""
import argparse
import os
import time
from datetime import date, timedelta

import pandas as pd

from .ml.walk_forward import split as wf_split
from .portfolio_sim import simulate_slot_portfolio
from .simulator import DEFAULT_TAX_RATE
from .strategies.new_high_swing import NewHighSwing
from .strategies.pullback_reentry import PullbackReentry
from .strategies.vcp_breakout import VcpBreakout
from .types import Signal
from . import simulator

DATA_DIR = "data"
STRATEGIES = [NewHighSwing(), PullbackReentry(), VcpBreakout()]
PARAMS = {"n_day_high": 60}  # REGIME_MA_PERIOD과 동일 주기(strategy1과 공유 근거) — 20/120 그리드는 이 1차 결과 이후.

# n_day_high=60(트레이딩일) 롤링 채널이 워밍업을 다 채우도록, 테스트 구간 시작 이전에
# 얹어주는 달력일 버퍼. 60거래일 ≈ 84달력일 + 휴장 여유 -> 150일이면 넉넉하다.
LOOKBACK_BUFFER_DAYS = 150
MIN_FOLD_TRADES = 30           # 이 미만이면 "참고용" — 합산 집계에서 제외.
PLACEHOLDER_MAX_CONCURRENT = 20  # 이 3전략엔 아직 운용(동시보유) 규칙이 없음 — 총수익/MDD 계산용 임시값.
HOLDOUT_FRACTION = 0.20

COMMISSION_RATE = 0.00015
SLIPPAGE_RATE = 0.001
INITIAL_CAPITAL = 10_000_000


def load_universe(data_dir: str = DATA_DIR) -> dict[str, pd.DataFrame]:
    """data/stocks/daily 전체를 한 번만 메모리에 올린다 — 폴드마다 다시 읽으면
    같은 파일을 최대 20번(폴드 수) 중복으로 읽게 된다.

    load_history는 [start,end] 구간을 API 폴백까지 고려해 받아오는 함수라, "로컬에
    이미 있는 전체 이력을 그대로" 원하는 이 경우엔 안 맞는다(요청 구간이 실제 커버
    범위를 살짝이라도 벗어나면 캐시를 무효로 보고 API로 폴백하려다 client=None에서
    죽는다) — scan_all_trades/daily_top_n_from_local과 같은 방식으로 로컬 CSV를
    그대로 읽는다(일봉은 리샘플링이 없어 data_loader._load_local_series의 일봉
    분기와 완전히 동일한 두 줄).
    """
    # lead 지시(20260901 일봉캐시 편지): 종목별 CSV 2,413번 여는 대신 합친 parquet
    # 캐시를 쓴다 - 판단 로직/결과는 그대로, 로딩 방식만 바꾼다.
    # date를 groupby 전에 한 번만 파싱/인덱싱해야 한다 - 그룹마다 pd.to_datetime을
    # 부르면 파일 읽기 절약분(0.07초)을 재구성 루프가 다시 까먹는다(실측 1.6초->0.7초).
    from backtesting.daily_cache import load_daily_all

    daily_dir = os.path.join(data_dir, "stocks", "daily")
    panel = load_daily_all(daily_dir)
    panel = panel.assign(date=pd.to_datetime(panel["date"])).set_index("date")
    universe = {code: g.drop(columns="code") for code, g in panel.groupby("code", sort=True) if not g.empty}
    return universe


def compute_holdout_start(universe: dict[str, pd.DataFrame]) -> tuple[date, date, date]:
    """전체 유니버스의 실제 커버 기간(가장 이른 봉~가장 늦은 봉)과, 그 기간의 마지막
    20%가 시작되는 날짜(이후로는 폴드를 만들지 않는다)를 반환."""
    overall_start = min(df.index.min() for df in universe.values()).date()
    overall_end = max(df.index.max() for df in universe.values()).date()
    total_days = (overall_end - overall_start).days
    holdout_start = overall_start + timedelta(days=round(total_days * (1 - HOLDOUT_FRACTION)))
    return overall_start, overall_end, holdout_start


def _simulate_stock(df: pd.DataFrame, strategy, params: dict, entry_start: date, entry_end: date, horizon_end: date) -> list:
    """한 종목: 폴드마다 따로 simulator.run을 부르지 않는다 — 폴드별 독립 호출은
    두 가지 문제가 있었다(실측으로 확인). (1) 느리다: 폴드마다 청산을 horizon_end까지
    열어야 해서(아래 참고) 같은 구간을 최대 15번 겹쳐 다시 걷는다 — 종목당 최대
    O(fold수 x 구간길이)가 O(구간길이) 한 번으로 준다. (2) 더 심각하게, 틀린다: 폴드 N의
    포지션이 폴드 N+1의 test 구간까지 안 닫힌 채 넘어가면, 폴드 N+1은 그걸 모르고
    "새 진입"을 또 받아버린다(각 simulator.run 호출이 자기 폴드만 알고 이전 폴드의
    미청산 포지션을 이어받지 않으므로) — 실제로는 한 번에 포지션 하나뿐인데 인접 폴드
    경계에서 이중 포지션이 생기는 버그였다. 종목당 딱 한 번, 전체 워크포워드 구간
    (entry_start~entry_end, 폴드들의 합집합 — step_days==test_days라 폴드가 빈틈/겹침
    없이 붙어 있음을 wf_split의 assert가 보장)을 이어서 시뮬레이션하고, 거래를
    entry_date로 어느 폴드에 속하는지 나중에 나눠 담는다.

    진입은 entry_start~entry_end(전체 워크포워드 구간)에서만, 청산은 그 뒤로도
    horizon_end(고정 홀드아웃 시작 직전)까지 열어둔다 — 채널 청산 없이 몇 달씩 달리는
    승리 거래가 짧은 구간에서 "미청산"으로 통째로 잘려나가는 왜곡이 처음에 실측으로
    확인됐다(2020-11-16 진입 삼성전자 트레이드, 90일 test 안에서는 안 닫히고 실제
    청산은 2021-05-13 +22.7%). horizon_end 밖 데이터는 여전히 안 연다.
    """
    eval_start = entry_start - timedelta(days=LOOKBACK_BUFFER_DAYS)
    window = df.loc[str(eval_start):str(horizon_end)]
    if len(window) < 30:
        return []

    signals = strategy.evaluate(window, params)
    dates = window.index.date
    buy_ok = (dates >= entry_start) & (dates <= entry_end)
    sell_ok = dates >= entry_start
    masked = signals.copy()
    masked[(signals == Signal.BUY) & ~buy_ok] = Signal.HOLD
    masked[(signals == Signal.SELL) & ~sell_ok] = Signal.HOLD
    if not (masked != Signal.HOLD).any():
        return []

    return simulator.run(
        window, masked, COMMISSION_RATE, SLIPPAGE_RATE, INITIAL_CAPITAL,
        stock_code="", tax_rate=DEFAULT_TAX_RATE,
    )


def _fold_index_for(entry_date: date, splits: list) -> int | None:
    for i, sp in enumerate(splits):
        if sp.test_start <= entry_date <= sp.test_end:
            return i
    return None


def _raw_trade_stats(trades: list) -> dict:
    """슬롯/자본 제약 없이 신호 자체의 품질만 본다 — 승률/손익비/평균수익률은
    포지션 슬롯이 몇 개인지에 영향받지 않아야 "선별력"을 순수하게 볼 수 있다."""
    closed = [t for t in trades if t.pnl is not None]
    n = len(closed)
    if n == 0:
        return {"n_trades": 0, "win_rate_pct": 0.0, "profit_factor": 0.0, "avg_pct_per_trade": 0.0}
    wins = [t for t in closed if t.pnl > 0]
    losses = [t for t in closed if t.pnl <= 0]
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = -sum(t.pnl for t in losses)
    return {
        "n_trades": n,
        "win_rate_pct": len(wins) / n * 100,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
        "avg_pct_per_trade": sum(t.pnl_pct for t in closed) / n * 100,
    }


def _portfolio_return_mdd(trades: list, codes: list[str]) -> dict:
    """총수익/MDD만 여기서 낸다(승률/손익비는 위 _raw_trade_stats가 슬롯 편향 없이
    이미 계산했다) — PLACEHOLDER_MAX_CONCURRENT 슬롯 가정 하의 자본곡선."""
    rows = [
        {"code": code, "entry_time": pd.Timestamp(t.entry_date), "exit_time": pd.Timestamp(t.exit_date), "pct": t.pnl_pct}
        for t, code in zip(trades, codes) if t.pnl is not None
    ]
    df = pd.DataFrame(rows, columns=["code", "entry_time", "exit_time", "pct"])
    result = simulate_slot_portfolio(df, INITIAL_CAPITAL, PLACEHOLDER_MAX_CONCURRENT)
    taken = result.taken_trades
    equity, peak, mdd = result.initial_capital, result.initial_capital, 0.0
    for t in sorted(taken, key=lambda t: t.exit_time):
        equity += t.profit
        peak = max(peak, equity)
        if peak > 0:
            mdd = max(mdd, (peak - equity) / peak)
    return {
        "total_return_pct": (result.final_capital / result.initial_capital - 1) * 100,
        "mdd_pct": mdd * 100,
    }


def simulate_and_bucket_by_fold(
    universe: dict[str, pd.DataFrame],
    strategy,
    splits: list,
    horizon_end: date,
    params: dict = PARAMS,
) -> tuple[list[list], list[list[str]]]:
    """종목당 한 번 시뮬레이션하고(_simulate_stock) 거래를 entry_date로 폴드에
    배정한다 — run_daily_walk_forward와 daily_walk_forward_benchmark.py가 이 결과를
    공유해야 같은 거래로 같은 숫자를 낸다(따로 재계산하면 숫자가 미묘하게 어긋날 수 있음)."""
    if not splits:
        return [], []
    entry_start, entry_end = splits[0].test_start, splits[-1].test_end

    fold_trades: list[list] = [[] for _ in splits]
    fold_codes: list[list] = [[] for _ in splits]
    for code, df in universe.items():
        trades = _simulate_stock(df, strategy, params, entry_start, entry_end, horizon_end)
        for t in trades:
            if t.pnl is None:
                continue  # horizon_end까지도 안 닫힌 포지션 — 어느 폴드 것이든 집계에서 제외.
            idx = _fold_index_for(t.entry_date, splits)
            if idx is not None:
                fold_trades[idx].append(t)
                fold_codes[idx].append(code)
    return fold_trades, fold_codes


def run_daily_walk_forward(
    universe: dict[str, pd.DataFrame],
    strategy,
    splits: list,
    horizon_end: date,
    params: dict = PARAMS,
) -> pd.DataFrame:
    if not splits:
        return pd.DataFrame([])
    fold_trades, fold_codes = simulate_and_bucket_by_fold(universe, strategy, splits, horizon_end, params)

    rows = []
    agg_trades, agg_codes = [], []
    for i, sp in enumerate(splits, 1):
        stats = _raw_trade_stats(fold_trades[i - 1])
        included = stats["n_trades"] >= MIN_FOLD_TRADES
        pm = _portfolio_return_mdd(fold_trades[i - 1], fold_codes[i - 1]) if stats["n_trades"] else {"total_return_pct": 0.0, "mdd_pct": 0.0}
        rows.append({
            "fold": i, "test_start": sp.test_start, "test_end": sp.test_end,
            "included_in_agg": included, **stats, **pm,
        })
        if included:
            agg_trades.extend(fold_trades[i - 1])
            agg_codes.extend(fold_codes[i - 1])

    agg_stats = _raw_trade_stats(agg_trades)
    agg_pm = _portfolio_return_mdd(agg_trades, agg_codes) if agg_trades else {"total_return_pct": 0.0, "mdd_pct": 0.0}
    rows.append({
        "fold": "합산(30건 미만 폴드 제외)", "test_start": None, "test_end": None,
        "included_in_agg": True, **agg_stats, **agg_pm,
    })
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=DATA_DIR)
    parser.add_argument("--train-days", type=int, default=730)
    parser.add_argument("--test-days", type=int, default=90)
    parser.add_argument("--step-days", type=int, default=90)
    args = parser.parse_args()

    t0 = time.perf_counter()
    universe = load_universe(args.data_dir)
    t1 = time.perf_counter()
    overall_start, overall_end, holdout_start = compute_holdout_start(universe)
    print(f"유니버스 {len(universe)}종목, 실제 커버기간 {overall_start} ~ {overall_end} (로딩 {t1-t0:.1f}s)")
    print(f"고정 홀드아웃: {holdout_start} ~ {overall_end} (마지막 {HOLDOUT_FRACTION:.0%}) - 이번 실행에서 폴드 생성 범위 밖")

    splits = wf_split(overall_start, holdout_start, args.train_days, args.test_days, args.step_days)
    horizon_end = holdout_start - timedelta(days=1)  # 청산은 이 날짜까지만 열어둔다 — 홀드아웃 첫날은 절대 안 본다.
    print(f"워크포워드 범위 {overall_start} ~ {holdout_start}, train={args.train_days}일/test={args.test_days}일/"
          f"step={args.step_days}일 -> {len(splits)}개 폴드\n")

    pd.set_option("display.width", 200)
    for strategy in STRATEGIES:
        t0 = time.perf_counter()
        df = run_daily_walk_forward(universe, strategy, splits, horizon_end)
        t1 = time.perf_counter()
        print(f"=== {strategy.name} (n_day_high={PARAMS['n_day_high']}, {t1-t0:.1f}s) ===")
        print(df.to_string(index=False))
        print()


if __name__ == "__main__":
    main()
