"""손익비 구조로 기대값 양수 만들기 — 사용자 직접지시(2026-09-01), 큐(6)
"최종 모델"을 대체한다. **승률은 낮아도 된다 — 손절/익절 비대칭으로 거래당
기대값(순수익)을 양수로 만들 수 있는가**가 질문이다.

## 재사용 — 새 진입조건을 만들지 않는다
진입은 이미 확정된 것: `t0_forward_return.py`의 price_speed 세 창(w1/w3/w10)
동시 IS 하위10%(OOS 총수익 +0.067%, t=2.88 —
`backtest-agent_20260831-182932_t0_forward_return.md` §5에서 이미 확정,
여기서 새로 안 고른다). 비용은 `round_trip_cost_pct` 그대로(안 낮춤).

## 왜 새로 시뮬레이션이 필요한가
`mfe_mae.py`가 이 조건의 MFE(상방여지)/MAE(하방여지)를 이미 쟀지만 그건
"그 구간에서 찍은 사후 최댓값"이라 실제로 그 가격에 팔 수 있었다는 뜻이
아니다. 손절선·익절선·시간손절 중 **어느 게 먼저 닿는지**를 초 단위
가격 경로로 직접 따라가야 진짜 청산가를 알 수 있다.

## 방법
1. 신호마다 `_precursor_fastpath.to_grid`로 그 (종목,일)의 초단위 가격배열
   (px)을 한 번만 읽어, 진입 초부터 `MAX_HORIZON`(=시간손절 후보 중 최댓값,
   600초)까지의 **상대수익률 경로**를 캐시한다(같은 날 신호가 여러 개면
   파일을 한 번만 읽는다).
2. 60개 그리드 조합(손절4 x 익절5 x 시간손절3) 전부 이 캐시 위에서
   벡터화 평가한다 - 조합마다 파일을 다시 읽거나 경로를 다시 스캔하지
   않는다.
3. **동시타격은 구조적으로 불가능함을 확인**(유닛테스트로 증명) — stop>0·
   target>0인 정상 그리드에서는 같은 초의 가격 하나가 "진입가 대비 -stop%
   이하"이면서 동시에 "+target% 이상"일 수 없다(부호가 반대라 한 값이 둘 다
   못 만족한다). 그래도 방어적으로 `simultaneous_hit` 플래그를 남겨 실행
   결과에서 실제로 0건인지 재확인한다 - 0건이 아니면 그 자체가 버그 신호다.

## 그리드 (넓게 안 깐다)
손절 [0.3/0.5/0.8/1.2%] x 익절 [0.3/0.5/0.8/1.2/1.5%] x 시간손절
[3/5/10분] = 60조합. IS(첫12일)에서 기대값(순수익 평균) 최댓값 조합
하나만 골라 OOS(뒤6일)에 그대로 적용한다 - OOS에서 다시 고르지 않는다.

실행: python -m backtesting.exit_path_grid_search
"""
import os
import time

import numpy as np
import pandas as pd

from _precursor_fastpath import N, SESSION_START, to_grid
from backtesting.shooting_precursor import TEST_DATES, TRAIN_DATES
from backtesting.t0_forward_return import round_trip_cost_pct

STOP_GRID = [0.003, 0.005, 0.008, 0.012]
TARGET_GRID = [0.003, 0.005, 0.008, 0.012, 0.015]
TIME_STOP_GRID = {"3m": 180, "5m": 300, "10m": 600}
MAX_HORIZON = max(TIME_STOP_GRID.values())


def load_entry_thresholds(train: pd.DataFrame) -> dict[str, float]:
    """t0_forward_return 리포트에서 이미 확정한 조건(price_speed 세 창 IS
    하위10%) - 여기서 다시 고르지 않고 그대로 재현한다."""
    return {feat: train[feat].quantile(0.10) for feat in ("w3_price_speed", "w1_price_speed", "w10_price_speed")}


def entry_signals(dataset: pd.DataFrame, dates: list[str], thresholds: dict[str, float]) -> pd.DataFrame:
    mask = pd.Series(True, index=dataset.index)
    for feat, thr in thresholds.items():
        mask &= dataset[feat] <= thr
    sub = dataset[mask & dataset["date"].isin(dates)]
    return sub[["code", "date", "t_sec", "price_t"]].sort_values(["date", "t_sec"]).reset_index(drop=True)


def build_path_cache(signals: pd.DataFrame, tick_dir: str = "data/stocks/tick_al") -> np.ndarray:
    """신호별 진입 초~MAX_HORIZON초까지의 상대수익률 경로(행=신호, 열=경과초,
    길이 MAX_HORIZON+1). 세션을 넘는 구간은 NaN."""
    paths = np.full((len(signals), MAX_HORIZON + 1), np.nan)
    for (code, date), group in signals.groupby(["code", "date"]):
        path = os.path.join(tick_dir, code, f"{date}.parquet")
        g = to_grid(path)
        if g is None:
            continue
        px = g["px"]
        for idx, row in group.iterrows():
            t0 = int(row["t_sec"] - SESSION_START)
            entry_price = px[t0]
            end = min(t0 + MAX_HORIZON, N - 1)
            length = end - t0 + 1
            paths[idx, :length] = px[t0:end + 1] / entry_price - 1
    return paths


def evaluate_combo(paths: np.ndarray, stop: float, target: float, time_stop_sec: int) -> pd.DataFrame:
    """조합 하나의 신호별 결과(gross_ret/exit_type). 동시타격은 손절 우선."""
    window = paths[:, :time_stop_sec + 1]
    n = window.shape[0]
    with np.errstate(invalid="ignore"):
        stop_hit = window <= -stop
        target_hit = window >= target
    stop_idx = np.where(stop_hit.any(axis=1), stop_hit.argmax(axis=1), time_stop_sec + 1)
    target_idx = np.where(target_hit.any(axis=1), target_hit.argmax(axis=1), time_stop_sec + 1)

    exit_is_stop = stop_idx <= target_idx  # 동시타격(==)이면 손절 우선(보수적)
    exit_is_target = (target_idx < stop_idx)
    triggered = (stop_idx <= time_stop_sec) | (target_idx <= time_stop_sec)

    time_ret = window[:, time_stop_sec]
    invalid = np.isnan(time_ret) & ~triggered  # 세션 밖이라 시간손절 값도 없는 신호

    gross = np.where(triggered, np.where(exit_is_stop, -stop, target), time_ret)
    gross = np.where(invalid, np.nan, gross)

    exit_type = np.where(triggered, np.where(exit_is_stop, "stop", "target"), "time")
    exit_type = np.where(invalid, "invalid", exit_type)
    simultaneous = triggered & (stop_idx == target_idx) & stop_hit.any(axis=1) & target_hit.any(axis=1)

    return pd.DataFrame({"gross_ret": gross, "exit_type": exit_type, "simultaneous_hit": simultaneous})


def trade_stats(df: pd.DataFrame, signals: pd.DataFrame) -> dict:
    """net_ret이 이미 계산된 df(gross_ret/exit_type/net_ret + signals의
    date/price_t)로 지시받은 통계 전부를 낸다."""
    valid = df.dropna(subset=["net_ret"])
    n = len(valid)
    if n == 0:
        return {"n_trades": 0}
    wins = valid[valid["net_ret"] > 0]
    losses = valid[valid["net_ret"] <= 0]
    gross_profit = wins["net_ret"].sum()
    gross_loss = -losses["net_ret"].sum()

    # 최대 연속손실 - entry 시간순(신호는 이미 date,t_sec로 정렬돼 들어옴)
    is_loss = (valid["net_ret"] <= 0).to_numpy()
    max_streak = streak = 0
    for loss in is_loss:
        streak = streak + 1 if loss else 0
        max_streak = max(max_streak, streak)

    daily = valid.groupby("date")["net_ret"].sum()
    n_days = valid["date"].nunique()

    return {
        "n_trades": n,
        "signals_per_day": n / max(n_days, 1),
        "win_rate_pct": len(wins) / n * 100,
        "avg_win_pct": wins["net_ret"].mean() * 100 if len(wins) else 0.0,
        "avg_loss_pct": losses["net_ret"].mean() * 100 if len(losses) else 0.0,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
        "expectancy_pct": valid["net_ret"].mean() * 100,
        "expectancy_se_pct": daily.std(ddof=1) / np.sqrt(n_days) * 100 if n_days > 1 else np.nan,
        "max_consecutive_losses": max_streak,
        "stop_hit_rate_pct": (valid["exit_type"] == "stop").mean() * 100,
        "target_hit_rate_pct": (valid["exit_type"] == "target").mean() * 100,
        "time_exit_rate_pct": (valid["exit_type"] == "time").mean() * 100,
        "simultaneous_hit_count": int(df["simultaneous_hit"].sum()),
        "daily_net_sum_pct_mean": daily.mean() * 100,
        "n_days": n_days,
    }


def run_grid(paths: np.ndarray, signals: pd.DataFrame) -> pd.DataFrame:
    rows = []
    cost = round_trip_cost_pct(signals["price_t"].to_numpy())
    for stop in STOP_GRID:
        for target in TARGET_GRID:
            for name, horizon in TIME_STOP_GRID.items():
                result = evaluate_combo(paths, stop, target, horizon)
                result["net_ret"] = result["gross_ret"] - cost
                result["date"] = signals["date"].to_numpy()
                stats = trade_stats(result, signals)
                stats.update({"stop_pct": stop * 100, "target_pct": target * 100, "time_stop": name})
                rows.append(stats)
    return pd.DataFrame(rows)


def main():
    t0 = time.time()
    dataset = pd.read_parquet("results/t0_forward_return_dataset.parquet")
    train_full = dataset[dataset["date"].isin(TRAIN_DATES)]
    thresholds = load_entry_thresholds(train_full)
    print("진입조건 문턱(IS, 기존 확정값 재현):", thresholds, flush=True)

    is_signals = entry_signals(dataset, TRAIN_DATES, thresholds)
    oos_signals = entry_signals(dataset, TEST_DATES, thresholds)
    print(f"IS 신호 {len(is_signals):,}건 / OOS 신호 {len(oos_signals):,}건", flush=True)

    print("IS 경로 캐시 구축...", flush=True)
    is_paths = build_path_cache(is_signals)
    print(f"IS 그리드 탐색({len(STOP_GRID)}x{len(TARGET_GRID)}x{len(TIME_STOP_GRID)}={len(STOP_GRID)*len(TARGET_GRID)*len(TIME_STOP_GRID)}조합)...", flush=True)
    is_grid = run_grid(is_paths, is_signals)
    is_grid.to_csv("results/exit_path_grid_is.csv", index=False)
    print(f"완료 {time.time()-t0:.1f}초", flush=True)

    valid_grid = is_grid[is_grid["n_trades"] >= 30]
    print(f"IS 유효조합(n_trades>=30): {len(valid_grid)}/{len(is_grid)}", flush=True)
    print("=== IS 그리드 전체(기대값 내림차순) ===")
    print(valid_grid.sort_values("expectancy_pct", ascending=False).to_string(index=False))

    best = valid_grid.sort_values("expectancy_pct", ascending=False).iloc[0]
    print(f"\n=== IS 최선 조합: 손절{best['stop_pct']:.1f}% 익절{best['target_pct']:.1f}% "
          f"시간손절{best['time_stop']} (기대값 {best['expectancy_pct']:.4f}%) ===")

    print("OOS 경로 캐시 구축...", flush=True)
    oos_paths = build_path_cache(oos_signals)
    stop = best["stop_pct"] / 100
    target = best["target_pct"] / 100
    horizon = TIME_STOP_GRID[best["time_stop"]]
    oos_result = evaluate_combo(oos_paths, stop, target, horizon)
    oos_cost = round_trip_cost_pct(oos_signals["price_t"].to_numpy())
    oos_result["net_ret"] = oos_result["gross_ret"] - oos_cost
    oos_result["date"] = oos_signals["date"].to_numpy()
    oos_stats = trade_stats(oos_result, oos_signals)
    print("=== OOS 결과(IS에서 고른 조합 그대로 적용) ===")
    for k, v in oos_stats.items():
        print(f"{k}: {v}")

    return is_grid, best, oos_stats


if __name__ == "__main__":
    main()
