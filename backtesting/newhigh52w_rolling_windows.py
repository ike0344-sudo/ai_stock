"""52주 신고가+골든크로스 — "하락·횡보장용" 후보 가설을 12개월 창을 3개월씩
밀어가며(겹치는 창) 재검증. lead 지시(2026-09-02 3차, 2차 결과 §3/§5 정정
인정 후): 근거가 창 2개(n=1~11)뿐이면 후보가 아니다 - 창 경계를 바꿔도
방향이 유지되는지 먼저 가른다.

`newhigh52w_yearly_windows.run_window_full`(진입/청산/대조군 전부 그대로)을
그대로 재사용한다 - 새 백테스트 로직 없음, 창 목록만 촘촘하게 바꿈. 재사용
CSV 트릭은 이번엔 안 씀(전부 새 창이라 재사용 대상이 없음 - 마지막 창이
우연히 2차 라운드의 "재사용 구간"과 겹쳐도 처음부터 다시 돌린다 - 로직은
같으니 값은 같아야 하고, 그 자체가 교차검증이 된다).

실행: python -m backtesting.newhigh52w_rolling_windows
"""
import os

import numpy as np
import pandas as pd

import backtesting.newhigh52w_golden_cross as m
import backtesting.newhigh52w_yearly_windows as yw

STEP_MONTHS = 3
FIRST_START = "2020-05-01"
LAST_START = "2025-09-01"  # 이 날짜 이하까지 생성 시도 - 단 3개월 격자(2020-05 앵커)가
# 정확히 2025-09-01에 안 걸려(66개월 나눠떨어짐 문제) 실제 마지막 창은 2025-08-01~2026-07-31로
# 끝난다(2026-08 한 달이 격자 밖) - 임의로 안 채움, 보고서에 명시(§실행결과 참고)


def rolling_windows(first_start: str = FIRST_START, last_start: str = LAST_START,
                     step_months: int = STEP_MONTHS) -> list[tuple[str, str]]:
    cur = pd.Timestamp(first_start)
    last = pd.Timestamp(last_start)
    out = []
    while cur <= last:
        end = cur + pd.DateOffset(years=1) - pd.DateOffset(days=1)
        out.append((cur.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
        cur = cur + pd.DateOffset(months=step_months)
    return out


def collect(windows: list[tuple[str, str]], shares: pd.Series) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """모든 창을 돌려 (요약행 DataFrame, 청산변형별 풀링된 원거래 DataFrame)을 낸다."""
    all_rows = []
    for start, end in windows:
        print(f"[{start}~{end}] 실행...", flush=True)
        all_rows += yw.run_window_full(start, end, shares)

    trades_by_variant: dict[str, list[pd.DataFrame]] = {v: [] for v in yw.EXIT_VARIANTS}
    for r in all_rows:
        trades_by_variant[r["variant"]].append(r["_trades"])

    df = pd.DataFrame(all_rows).drop(columns=["_trades"])
    pooled = {v: (pd.concat(lst, ignore_index=True) if lst else pd.DataFrame(columns=["net_pct"]))
              for v, lst in trades_by_variant.items()}
    return df, pooled


def correlation_table(df: pd.DataFrame) -> pd.DataFrame:
    """지시 §3: x=그 창의 유니버스 수익률, y=초과분(전략net-유니버스). 조합(정의x청산)별
    상관계수·부호. 창이 겹쳐 독립표본이 아니므로 유의성 검정은 안 한다(지시 §4) - r과
    부호만, p-value 없음."""
    rows = []
    for (def_name, variant), g in df.groupby(["def", "variant"]):
        g = g.dropna(subset=["ctrl_universe_ret", "excess_vs_universe"])
        n = len(g)
        r = float(g["ctrl_universe_ret"].corr(g["excess_vs_universe"])) if n >= 2 else float("nan")
        rows.append({"def": def_name, "variant": variant, "n_windows": n, "corr": r,
                     "sign": ("음(-)" if r < 0 else "양(+)") if not np.isnan(r) else "N/A"})
    return pd.DataFrame(rows)


def loss_stats_table(pooled: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """지시 B: 청산 3종별 최악 단일거래 손실 + 손실거래 최대치. 창이 겹쳐 같은 실제
    거래가 여러 창에 중복 등장할 수 있음(풀링 특성) - 보고서에 명시."""
    rows = []
    for variant, trades in pooled.items():
        if trades.empty or "net_pct" not in trades.columns:
            rows.append({"variant": variant, "n_pooled_trades": 0, "worst_single_trade_pct": float("nan"),
                         "n_losers": 0, "mean_loss_pct": float("nan"), "n_losses_beyond_stop8pct": 0})
            continue
        net = trades["net_pct"].dropna()
        losers = net[net < 0]
        rows.append({
            "variant": variant, "n_pooled_trades": len(net),
            "worst_single_trade_pct": float(net.min()) if len(net) else float("nan"),
            "n_losers": len(losers),
            "mean_loss_pct": float(losers.mean()) if len(losers) else float("nan"),
            "n_losses_beyond_stop8pct": int((losers < -0.08).sum()),
        })
    return pd.DataFrame(rows)


def main():
    shares = m.load_shares()
    windows = rolling_windows()
    print(f"창 {len(windows)}개(3개월씩 밀어가며, {windows[0][0]}~{windows[-1][1]})", flush=True)

    df, pooled = collect(windows, shares)
    os.makedirs("results", exist_ok=True)
    df.to_csv("results/newhigh52w_rolling_windows.csv", index=False)

    corr = correlation_table(df)
    corr.to_csv("results/newhigh52w_rolling_correlation.csv", index=False)
    loss = loss_stats_table(pooled)
    loss.to_csv("results/newhigh52w_rolling_loss_stats.csv", index=False)

    print("\n=== 상관표 (x=유니버스수익률, y=초과분, 창 겹침 - 유의성검정 안 함) ===", flush=True)
    for _, r in corr.iterrows():
        print(f"[{r['def']}/{r['variant']}] n창={r['n_windows']} corr={r['corr']:.3f} 부호={r['sign']}", flush=True)

    print("\n=== 청산3종별 손실 통계 (전체 창 풀링, 중복거래 포함 가능) ===", flush=True)
    for _, r in loss.iterrows():
        print(f"[{r['variant']}] 풀링거래수={r['n_pooled_trades']} "
              f"최악단일거래={r['worst_single_trade_pct']*100:.3f}% "
              f"손실거래수={r['n_losers']} 손실평균={r['mean_loss_pct']*100:.3f}% "
              f"-8%초과손실건수={r['n_losses_beyond_stop8pct']}", flush=True)

    print("\n=== 창별 요약 (표본0건도 남김) ===", flush=True)
    for _, r in df.iterrows():
        thin = " [표본얇음]" if r["n"] <= 5 else (" [0건]" if r["n"] == 0 else "")
        print(f"{r['start']}~{r['end']} [{r['def']}/{r['variant']}] n={r['n']}{thin} "
              f"net={r['net_mean']*100:.3f}% 유니버스={r['ctrl_universe_ret']*100:.3f}% "
              f"초과={r['excess_vs_universe']*100:.3f}%p", flush=True)

    return df, corr, loss


if __name__ == "__main__":
    main()
