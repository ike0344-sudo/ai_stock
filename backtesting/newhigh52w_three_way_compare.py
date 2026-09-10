"""52주 신고가+골든크로스 — 포트폴리오 수익률 vs 현금(0%) vs 유니버스, 세 값을 나란히.
lead 5차지시(2026-09-02): "이 전략을 쓰는 게 현금·지수 어느 쪽보다도 나은 상황이
존재하는가?" 새 시뮬레이션 없음 - `results/newhigh52w_portfolio_sim.csv`(4차 라운드
산출물)를 그대로 읽어 판정만 추가한다.

전략이 1등 = 포트폴리오수익률 > 0(현금) **그리고** 포트폴리오수익률 > 유니버스.
현금 0% 비교는 이미 공정하다 - `portfolio_ret`가 `final_capital/initial_capital-1`
(전체자본 기준, 미사용 슬롯의 자본도 분모에 포함)이라 노는 돈이 이미 반영돼 있다
(portfolio_sim.py 재확인, 새로 뺄 것 없음).

실행: python -m backtesting.newhigh52w_three_way_compare
"""
import os

import pandas as pd

SOURCE_CSV = "results/newhigh52w_portfolio_sim.csv"


def add_winner_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["cash_ret"] = 0.0

    def _winner(row):
        vals = {"portfolio": row["portfolio_ret"], "cash": 0.0, "universe": row["ctrl_universe_ret"]}
        return max(vals, key=vals.get)

    df["winner"] = df.apply(_winner, axis=1)
    df["strategy_beats_both"] = (df["portfolio_ret"] > 0) & (df["portfolio_ret"] > df["ctrl_universe_ret"])
    return df


def win_summary(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["def", "variant"])["strategy_beats_both"]
    out = g.agg(n_windows="count", n_wins="sum").reset_index()
    out["win_rate"] = out["n_wins"] / out["n_windows"]
    return out


def main():
    df = add_winner_columns(pd.read_csv(SOURCE_CSV))
    os.makedirs("results", exist_ok=True)
    df.to_csv("results/newhigh52w_three_way_compare.csv", index=False)

    summary = win_summary(df)
    summary.to_csv("results/newhigh52w_three_way_win_summary.csv", index=False)

    print("=== 조합별 3자비교 1등 판정 ===", flush=True)
    for _, r in summary.iterrows():
        print(f"[{r['def']}/{r['variant']}] {int(r['n_wins'])}/{int(r['n_windows'])}창 "
              f"({r['win_rate']*100:.1f}%) 전략이 현금·유니버스 둘 다 이김", flush=True)

    print("\n=== 전략이 이긴 창 전부 (사후선택 아님 - 전수) ===", flush=True)
    wins = df[df["strategy_beats_both"]].sort_values(["def", "variant", "start"])
    for _, r in wins.iterrows():
        print(f"{r['start']}~{r['end']} [{r['def']}/{r['variant']}] 신호={r['n_signals']} "
              f"채택={r['taken']} 스킵={r['skipped']} 포트폴리오={r['portfolio_ret']*100:.3f}% "
              f"유니버스={r['ctrl_universe_ret']*100:.3f}%", flush=True)

    return df, summary


if __name__ == "__main__":
    main()
