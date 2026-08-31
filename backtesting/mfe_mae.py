"""MFE/MAE — 큐(2)번. 평균수익이 아니라 **기대값(MFE/MAE 비대칭 포함)이 가장
높은 T0 조건**을 찾는다. 승률은 부차 지표(승률 높고 기대값 낮은 구간을 고르지
않는다).

## 재사용
`t0_forward_return.py`의 T0_GRID(1분 그리드, 세션 전체)·6피처x3창(저장된
`results/t0_forward_return_dataset.parquet`, 재계산 안 함)·비용모델
(`round_trip_cost_pct`)·`decile_table`(라벨 컬럼을 인자로 받게 이미
파라미터화돼 있어 그대로 재사용)·`_day_clustered_mean_se`. `_precursor_
fastpath.to_grid`(tie-break 수정본)로 MFE/MAE 라벨만 새로 뽑는다(역순
rolling max/min - `shooting_precursor.label_shoot`/`precursor_10_60s.py`에서
쓴 것과 같은 기법, min 쪽만 새로 추가).

## MFE/MAE 정의
horizon h(1/3/5/10분)에 대해:
- `mfe_h = max(px[T0..T0+h-1]) / price_T0 - 1` (그 구간에서 찍은 최고 미실현
  수익)
- `mae_h = min(px[T0..T0+h-1]) / price_T0 - 1` (그 구간에서 찍은 최저
  미실현 손실 - 음수)
- 미래창이 세션을 넘으면(T0+h-1 > 세션 끝) 그 라벨만 NaN(행은 살린다,
  기존 리포트들과 동일 원칙).

## "기대값" 정의 — 해석 판단, 명시
지시문이 구체적인 산식을 안 줘서 다음으로 정한다: **EV_h = mfe_h + mae_h**
(둘 다 부호 있는 값 - MAE는 음수라 덧셈이 곧 "전형적 상방폭에서 전형적
하방폭을 뺀 것"이 된다). 이게 "MFE/MAE 비대칭을 포함한 기대값"의 가장
단순하고 투명한 형태라 이걸 채택했다 - 특정 손절/익절 트레이딩 룰을
가정하지 않는다(그건 이 항목 범위 밖, 승률처럼 "부차"로 취급).

## 평가
- Spearman IC(18피처 x 4호라이즌 EV, 안 되는 것도 전부 표) - IS/OOS.
- IS 상위 지표로 10분위(EV 평균 + 일자클러스터SE) - `decile_table` 그대로.
- **기존에 찾은 조건(price_speed 세 창 동시 하위10%, `t0_forward_return`/
  `holding_horizon`에서 이미 검증)의 MFE/MAE/EV 프로파일**도 이어서
  보고한다 - 새 지표가 그것보다 나은지 비교 기준이 된다.
- 비용은 `round_trip_cost_pct` 그대로, 총수익/순수익 나란히(순수익은 MFE
  기준 "최선의 청산이 가능했다면"과 단순 EV 기준 둘 다 보여준다 - 실현
  가능성 차이를 리포트에서 구분).

## 산출
실행: python -m backtesting.mfe_mae
"""
import glob
import os
import time

import numpy as np
import pandas as pd

from _precursor_fastpath import N, SESSION_START, to_grid
from backtesting.shooting_precursor import TEST_DATES, TRAIN_DATES
from backtesting.t0_forward_return import (
    FEATURE_COLUMNS,
    T0_GRID,
    _day_clustered_mean_se,
    decile_table,
    round_trip_cost_pct,
)

MFE_MAE_HORIZONS = {"1m": 60, "3m": 180, "5m": 300, "10m": 600}  # 초


def compute_mfe_mae_labels(path: str, code: str, date_str: str) -> pd.DataFrame | None:
    g = to_grid(path)
    if g is None:
        return None
    px = g["px"]
    cols = {"code": code, "date": date_str, "t_sec": T0_GRID + SESSION_START}
    for name, h in MFE_MAE_HORIZONS.items():
        fut_max = pd.Series(px[::-1]).rolling(h, min_periods=1).max().to_numpy()[::-1]
        fut_min = pd.Series(px[::-1]).rolling(h, min_periods=1).min().to_numpy()[::-1]
        in_range = T0_GRID + h - 1 <= N - 1
        mfe = np.full(len(T0_GRID), np.nan)
        mae = np.full(len(T0_GRID), np.nan)
        mfe[in_range] = fut_max[T0_GRID[in_range]] / px[T0_GRID[in_range]] - 1
        mae[in_range] = fut_min[T0_GRID[in_range]] / px[T0_GRID[in_range]] - 1
        cols[f"mfe_{name}"] = mfe
        cols[f"mae_{name}"] = mae
        cols[f"ev_{name}"] = mfe + mae
    return pd.DataFrame(cols)


def scan_mfe_mae(tick_dir: str = "data/stocks/tick_al") -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(tick_dir, "*", "*.parquet")))
    frames = []
    for path in files:
        code = os.path.basename(os.path.dirname(path))
        date_str = os.path.splitext(os.path.basename(path))[0]
        frame = compute_mfe_mae_labels(path, code, date_str)
        if frame is not None and not frame.empty:
            frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build_dataset() -> pd.DataFrame:
    base = pd.read_parquet("results/t0_forward_return_dataset.parquet")
    base = base[["code", "date", "t_sec", "price_t"] + FEATURE_COLUMNS].copy()
    labels = scan_mfe_mae()
    return base.merge(labels, on=["code", "date", "t_sec"], how="left")


EV_COLUMNS = [f"ev_{k}" for k in MFE_MAE_HORIZONS]


def spearman_ic_table(df: pd.DataFrame) -> pd.DataFrame:
    cols = FEATURE_COLUMNS + EV_COLUMNS
    corr = df[cols].corr(method="spearman")
    rows = []
    for feat in FEATURE_COLUMNS:
        for label in EV_COLUMNS:
            n = df[[feat, label]].dropna().shape[0]
            rows.append({"feature": feat, "label": label, "ic": corr.loc[feat, label], "n": n})
    return pd.DataFrame(rows)


def condition_mfe_mae_report(train: pd.DataFrame, test: pd.DataFrame, thresholds: dict[str, float]) -> pd.DataFrame:
    rows = []
    for group_name, df in (("IS", train), ("OOS", test)):
        mask = pd.Series(True, index=df.index)
        for feat, thr in thresholds.items():
            mask &= df[feat] <= thr
        sub_all = df[mask]
        n_days_total = df["date"].nunique()
        for name in MFE_MAE_HORIZONS:
            sub = sub_all.dropna(subset=[f"ev_{name}"]).copy()
            if sub.empty:
                rows.append({"group": group_name, "horizon": name, "n": 0})
                continue
            cost = round_trip_cost_pct(sub["price_t"].to_numpy())
            sub["net_mfe"] = sub[f"mfe_{name}"] - cost
            sub["net_ev"] = sub[f"ev_{name}"] - cost
            mfe_mean, mfe_se, n, n_days = _day_clustered_mean_se(sub, f"mfe_{name}")
            mae_mean, mae_se, _, _ = _day_clustered_mean_se(sub, f"mae_{name}")
            ev_mean, ev_se, _, _ = _day_clustered_mean_se(sub, f"ev_{name}")
            net_mfe_mean, net_mfe_se, _, _ = _day_clustered_mean_se(sub, "net_mfe")
            net_ev_mean, net_ev_se, _, _ = _day_clustered_mean_se(sub, "net_ev")
            rows.append({
                "group": group_name, "horizon": name, "n": n, "n_days": n_days,
                "signals_per_day": n / n_days_total,
                "mfe_mean_pct": mfe_mean * 100, "mae_mean_pct": mae_mean * 100,
                "ev_mean_pct": ev_mean * 100, "ev_se_pct": ev_se * 100,
                "t_ev": ev_mean / ev_se if ev_se else np.nan,
                "net_mfe_mean_pct": net_mfe_mean * 100,
                "net_ev_mean_pct": net_ev_mean * 100,
                "win_rate_pct(부차)": (sub[f"mfe_{name}"] + sub[f"mae_{name}"] > 0).mean() * 100,
            })
    return pd.DataFrame(rows)


def main():
    t0 = time.time()
    print("MFE/MAE 라벨 스캔 + 기존 피처 병합...", flush=True)
    dataset = build_dataset()
    dt = time.time() - t0
    os.makedirs("results", exist_ok=True)
    dataset.to_parquet("results/mfe_mae_dataset.parquet", index=False)
    print(f"완료 {dt:.1f}초 | 표본 {len(dataset):,}행", flush=True)

    train = dataset[dataset["date"].isin(TRAIN_DATES)].reset_index(drop=True)
    test = dataset[dataset["date"].isin(TEST_DATES)].reset_index(drop=True)

    ic = spearman_ic_table(train)
    ic_oos = spearman_ic_table(test)
    ic.to_csv("results/mfe_mae_ic_train.csv", index=False)
    ic_oos.to_csv("results/mfe_mae_ic_test.csv", index=False)
    print("=== IS Spearman IC (feature x EV horizon) ===")
    print(ic.pivot(index="feature", columns="label", values="ic").to_string())
    print("=== OOS Spearman IC ===")
    print(ic_oos.pivot(index="feature", columns="label", values="ic").to_string())

    top5 = (ic[ic["label"] == "ev_5m"].assign(abs_ic=lambda d: d["ic"].abs())
            .sort_values("abs_ic", ascending=False).head(5)["feature"].tolist())
    for feat in top5:
        print(f"=== {feat} 10분위(ev_5m) IS ===")
        print(decile_table(train, feat, label="ev_5m").to_string(index=False))
        print(f"=== {feat} 10분위(ev_5m) OOS ===")
        print(decile_table(test, feat, label="ev_5m").to_string(index=False))

    q = {feat: train[feat].quantile(0.10) for feat in ("w3_price_speed", "w1_price_speed", "w10_price_speed")}
    print("=== 기존 조건(price_speed 세창 하위10%) MFE/MAE/EV ===")
    print(condition_mfe_mae_report(train, test, q).to_string(index=False))

    return dataset, ic, ic_oos


if __name__ == "__main__":
    main()
