"""52주 신고가+골든크로스 — "초과분" 단위 오류 정정: 거래당 평균수익률(net_pct)이
아니라 **슬롯 기반 포트폴리오 수익률**로 유니버스 대조군과 같은 단위로 비교한다.

lead 4차지시(2026-09-02) 인정: 3차 라운드까지 "초과분 = 거래당 평균net - 12개월
buy&hold"는 단위가 다른 두 값을 뺀 것(거래당 평균 vs 기간전체 수익률)이었고,
그 강한 음의 상관(r≈-0.99)도 상당부분 이 계산 오류의 기계적 결과였다(작은 분산
값에서 큰 분산 값을 빼면 -그 값에 수렴). **§2(3차 보고서)가 증상은 맞게 짚었지만
원인은 여기 있었다.**

## 재사용 (새 로직 최소화)
- 신호/진입/청산: `newhigh52w_golden_cross.load_panel/add_features/simulate_trades`
  그대로(하나도 안 바꿈).
- 창 목록: `newhigh52w_rolling_windows.rolling_windows()` 그대로(22개, 3개월씩).
- 유니버스/코스피 대조군: `newhigh52w_yearly_windows.universe_buy_and_hold`/
  `kospi_index_return` 그대로.
- 상관표: `newhigh52w_rolling_windows.correlation_table` 그대로(컬럼명만 맞추면
  그대로 먹음 - 새 상관계산 함수 안 만듦).
- **포트폴리오 집계: `portfolio_sim.simulate_slot_portfolio` 그대로**(동시보유
  슬롯 시뮬레이션은 이미 있다 - `backtest-agent.md` 4항에 명시된 재사용 대상,
  새로 안 짬). 진입 로직은 하나도 안 바꿨다 - 바뀐 건 "거래들을 어떻게 집계해서
  하나의 수익률로 만드는가"뿐이다.

## 규칙 (lead 확정, 재량으로 안 바꿈)
- 자본 고정, 최대 5슬롯(기본값), 슬롯당 자본의 1/5. 슬롯 꽉 차면 그 신호는 스킵
  (스킵 건수 별도 집계). 청산된 슬롯은 재사용(자본 재투입) - 단, **복리 재투자는
  안 함**(`portfolio_sim`이 이미 그렇게 설계됨 - 슬롯 크기가 개별 거래 손익에
  안 흔들리게 고정, 모듈 docstring 참고). lead 표현("회수된 금액을 다음 진입에
  다시 쓴다")과 완전히 같은 계산은 아니라는 걸 명시(복리면 슬롯크기가 매번
  바뀜) - 기존 재사용 유틸의 설계를 그대로 따름, 새로 안 짬.
- 동률(같은 날 여러 신호): 종목코드 오름차순(lead 지시, 임의규칙). entry_time에
  마이크로초 단위 순번을 얹어(`to_candidates`) `simulate_slot_portfolio` 내부
  정렬이 흐트러뜨리지 못하게 결정론적으로 고정 - exit_time과는 항상 최소
  하루 이상 차이나서 슬롯가용성 비교를 왜곡 안 함.

실행: python -m backtesting.newhigh52w_portfolio_sim
"""
import os

import numpy as np
import pandas as pd

import backtesting.newhigh52w_golden_cross as m
import backtesting.newhigh52w_yearly_windows as yw
import backtesting.portfolio_sim as ps
from backtesting.metrics import _max_drawdown_pct as _shared_max_drawdown_pct
from backtesting.metrics import _sharpe_ratio as _shared_sharpe_ratio
from backtesting.newhigh52w_rolling_windows import correlation_table, rolling_windows
from backtesting.types import Trade

DEFAULT_CAPITAL = 10_000_000
DEFAULT_MAX_SLOTS = 5
SLOT_SENSITIVITY = [3, 10]  # 5(기본) 외 참고용(지시 "여력 되면만")


def to_candidates(trades: pd.DataFrame) -> pd.DataFrame:
    """simulate_trades 산출물(entry_date/exit_date/net_pct 문자열) ->
    simulate_slot_portfolio가 먹는 entry_time/exit_time/pct/code.
    같은 날 여러 신호는 코드 오름차순으로 정렬한 뒤 entry_time에 마이크로초
    순번을 매겨 동률을 없앤다(§ 동률 규칙, 결정론 보장)."""
    if trades.empty:
        return pd.DataFrame(columns=["code", "entry_time", "exit_time", "pct"])
    df = trades.sort_values(["entry_date", "code"], kind="mergesort").reset_index(drop=True)
    offset = df.groupby("entry_date").cumcount()
    df["entry_time"] = pd.to_datetime(df["entry_date"]) + pd.to_timedelta(offset, unit="us")
    df["exit_time"] = pd.to_datetime(df["exit_date"])
    return df[["code", "entry_time", "exit_time", "net_pct"]].rename(columns={"net_pct": "pct"})


def _to_metric_trades(taken_trades: list) -> list[Trade]:
    """SlotTrade(portfolio_sim) -> types.Trade 로 변환하는 얇은 어댑터. 두 타입의
    필드가 달라서만 존재 - 계산 로직은 없다(RL 규율(1), lead 5.5차지시 재사용 목록)."""
    return [
        Trade(stock_code=str(t.code), entry_date=t.entry_time.date(), entry_price=0.0, quantity=1,
              commission=0.0, slippage=0.0, exit_date=t.exit_time.date(), exit_price=0.0,
              pnl=t.profit, pnl_pct=t.pct)
        for t in sorted(taken_trades, key=lambda x: x.exit_time)
    ]


def compute_mdd(result: ps.PortfolioResult) -> float:
    """체결(청산) 이벤트 단위 스텝함수 자본곡선의 최대낙폭. **미실현 평가손실은
    반영 안 함**(보유 중인 포지션의 장중 하락은 안 보임) - 특히 (c)청산없음처럼
    보유기간이 긴 변형에서 실제보다 낙관적일 위험 큼, 보고서에 명시.

    `metrics._max_drawdown_pct`(공용 위험지표)에 위임한다 - 3차 라운드에서 직접
    짠 동일 로직(peak-tracking)을 lead 지시(RL 규율(1), 중복 제거)로 대체했다.
    반환값·거동은 그대로(회귀테스트로 확인)."""
    return _shared_max_drawdown_pct(_to_metric_trades(result.taken_trades), result.initial_capital) / 100.0


def compute_sharpe(result: ps.PortfolioResult) -> float:
    """`metrics._sharpe_ratio` 재사용(RL 규율(1) - 위험지표를 net수익과 항상 같이 냄)."""
    return _shared_sharpe_ratio(_to_metric_trades(result.taken_trades))


def simulate_window_portfolio(trades: pd.DataFrame, capital: float = DEFAULT_CAPITAL,
                               max_slots: int = DEFAULT_MAX_SLOTS) -> dict:
    candidates = to_candidates(trades)
    result = ps.simulate_slot_portfolio(candidates, initial_capital=capital, max_concurrent_positions=max_slots)
    return {
        "portfolio_ret": result.final_capital / result.initial_capital - 1,
        "taken": len(result.taken_trades), "skipped": result.skipped_count,
        "mdd": compute_mdd(result), "sharpe": compute_sharpe(result),
    }


def run_window_portfolio(start: str, end: str, shares: pd.Series, max_slots: int = DEFAULT_MAX_SLOTS) -> list[dict]:
    m.PERIOD_START, m.PERIOD_END = start, end
    panel_raw = m.load_panel()
    panel = m.add_features(panel_raw)
    univ_ret, univ_n = yw.universe_buy_and_hold(panel_raw, shares, start)
    kospi_ret = yw.kospi_index_return(start, end)

    rows = []
    for def_name in m.GOLDEN_CROSS_DEFS:
        for variant_name, (stop_pct, target_pct) in yw.EXIT_VARIANTS.items():
            trades = m.simulate_trades(panel, shares, def_name, stop_pct=stop_pct, target_pct=target_pct)
            sim = simulate_window_portfolio(trades, max_slots=max_slots)
            excess = (sim["portfolio_ret"] - univ_ret) if not np.isnan(univ_ret) else float("nan")
            rows.append({
                "start": start, "end": end, "def": def_name, "variant": variant_name,
                "max_slots": max_slots, "n_signals": len(trades),
                "taken": sim["taken"], "skipped": sim["skipped"],
                "portfolio_ret": sim["portfolio_ret"], "mdd": sim["mdd"],
                "ctrl_universe_ret": univ_ret, "ctrl_universe_n": univ_n,
                "excess_vs_universe": excess, "kospi_ret": kospi_ret,
            })
    return rows


def main():
    shares = m.load_shares()
    windows = rolling_windows()
    print(f"창 {len(windows)}개, 슬롯={DEFAULT_MAX_SLOTS}(기본)", flush=True)

    rows = []
    for start, end in windows:
        print(f"[{start}~{end}] 실행...", flush=True)
        rows += run_window_portfolio(start, end, shares, max_slots=DEFAULT_MAX_SLOTS)
    df = pd.DataFrame(rows)
    os.makedirs("results", exist_ok=True)
    df.to_csv("results/newhigh52w_portfolio_sim.csv", index=False)

    corr = correlation_table(df)  # 재사용 - 컬럼명만 맞으면 그대로 먹음
    corr.to_csv("results/newhigh52w_portfolio_correlation.csv", index=False)

    print("\n=== 상관표 (포트폴리오 초과분 기준, 재계산) ===", flush=True)
    for _, r in corr.iterrows():
        print(f"[{r['def']}/{r['variant']}] n창={r['n_windows']} corr={r['corr']:.3f} 부호={r['sign']}", flush=True)

    print("\n=== 슬롯 민감도(3/10) - 상관계수만 참고 ===", flush=True)
    sens_rows = []
    for slots in SLOT_SENSITIVITY:
        s_rows = []
        for start, end in windows:
            s_rows += run_window_portfolio(start, end, shares, max_slots=slots)
        s_df = pd.DataFrame(s_rows)
        s_corr = correlation_table(s_df)
        s_corr["max_slots"] = slots
        sens_rows.append(s_corr)
        for _, r in s_corr.iterrows():
            print(f"[slots={slots}] [{r['def']}/{r['variant']}] corr={r['corr']:.3f}", flush=True)
    sens_df = pd.concat(sens_rows, ignore_index=True) if sens_rows else pd.DataFrame()
    if not sens_df.empty:
        sens_df.to_csv("results/newhigh52w_slot_sensitivity.csv", index=False)

    print("\n=== 창별 요약 ===", flush=True)
    total_skipped = int(df["skipped"].sum())
    for _, r in df.iterrows():
        thin = " [표본얇음]" if r["n_signals"] <= 5 else (" [0건]" if r["n_signals"] == 0 else "")
        print(f"{r['start']}~{r['end']} [{r['def']}/{r['variant']}] 신호={r['n_signals']}{thin} "
              f"채택={r['taken']} 스킵={r['skipped']} 포트폴리오수익={r['portfolio_ret']*100:.3f}% "
              f"MDD={r['mdd']*100:.3f}% 유니버스={r['ctrl_universe_ret']*100:.3f}% "
              f"초과={r['excess_vs_universe']*100:.3f}%p", flush=True)
    print(f"\n총 스킵(슬롯부족으로 놓친 신호) = {total_skipped}건", flush=True)

    return df, corr


if __name__ == "__main__":
    main()
