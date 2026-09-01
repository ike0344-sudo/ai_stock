"""큐(5) 체결↔가격 괴리 — 체결금액은 급증하는데 가격이 안 움직이는 구간
("매물벽 소화" 후보) 이후의 가격 움직임을 본다. 체결금액 증가율 대비
가격상승률이 느린 구간/빠른 구간을 나눠 전방수익을 비교한다.

## 재사용 — 새 틱 스캔 없음(이 항목의 핵심 절약)
`t0_forward_return.py`가 이미 저장해 둔 `results/t0_forward_return_dataset.
parquet`에 1분 그리드 T0마다 `w{1,3,10}_price_speed`(가격상승속도=드리프트/
초)와 `w{1,3,10}_value_surge`(체결금액 증가율=창 거래대금/그 시점까지의
확장평균)가 이미 있다 - **틱을 다시 스캔하지 않고 이 둘의 비율만 새로
계산**한다(`decile_table`/`_day_clustered_mean_se`/`round_trip_cost_pct`도
`t0_forward_return.py`에서 그대로 가져온다).

## "괴리" 정의
`divergence_w = w{key}_price_speed / w{key}_value_surge` — 분자(가격상승
속도)를 분모(체결금액 증가율)로 나눈 것이라, **낮을수록(심지어 음수)
"체결은 급증하는데 가격은 안 움직이거나 밀린다"**(매물벽이 흡수하고 있는
중일 가능성), **높을수록 "적은 체결 증가로도 가격이 잘 움직인다"**(저항이
얇음, 이미 갈 데까지 간 상태일 수 있음).

## 그룹 분리
IS 하위 10%(느린=흡수 후보) vs IS 상위 10%(빠른=이미 반응) — 문턱은 IS에서만
정하고 OOS엔 그대로 적용. "매물벽 소화" 가설이 맞다면 **느린 그룹의 전방수익이
빠른 그룹보다 커야 한다**(흡수가 끝난 뒤 더 크게 움직인다는 뜻).

## 평가
`decile_table`로 전체 십분위(단조성 확인) + 상/하위 10% 그룹 비교(전방수익
1/3/5/10분, 비용 반영 총/순수익, 일자클러스터 SE). IS(첫12일)/OOS(뒤6일).

실행: python -m backtesting.execution_price_divergence
"""
import os

import numpy as np
import pandas as pd

from backtesting.shooting_precursor import TEST_DATES, TRAIN_DATES
from backtesting.t0_forward_return import (
    FEATURE_WINDOWS,
    _day_clustered_mean_se,
    decile_table,
    round_trip_cost_pct,
)

LABEL_COLUMNS = ["ret_1m", "ret_3m", "ret_5m", "ret_10m"]
DIVERGENCE_COLUMNS = [f"{key}_divergence" for key in FEATURE_WINDOWS]


def build_dataset() -> pd.DataFrame:
    df = pd.read_parquet("results/t0_forward_return_dataset.parquet")
    np.seterr(divide="ignore", invalid="ignore")
    for key in FEATURE_WINDOWS:
        div = df[f"{key}_price_speed"] / df[f"{key}_value_surge"]
        div[df[f"{key}_value_surge"] == 0] = np.nan
        df[f"{key}_divergence"] = div
    return df


def group_comparison_report(train: pd.DataFrame, test: pd.DataFrame, feature: str) -> pd.DataFrame:
    """IS 하위10%(느린=흡수 후보) vs 상위10%(빠른=이미 반응) 문턱을 IS에서
    구해 그대로 OOS에 적용 - 전방수익 4개 horizon 전부."""
    lo, hi = train[feature].quantile([0.10, 0.90])
    rows = []
    for group_name, df in (("IS", train), ("OOS", test)):
        n_days_total = df["date"].nunique()
        for side_name, mask in (("느린(하위10%)", df[feature] <= lo), ("빠른(상위10%)", df[feature] >= hi)):
            for label in LABEL_COLUMNS:
                sub = df[mask].dropna(subset=[label]).copy()
                if sub.empty:
                    rows.append({"group": group_name, "side": side_name, "label": label, "n": 0})
                    continue
                sub["net_ret"] = sub[label] - round_trip_cost_pct(sub["price_t"].to_numpy())
                gross_mean, gross_se, n, n_days = _day_clustered_mean_se(sub, label)
                net_mean, net_se, _, _ = _day_clustered_mean_se(sub, "net_ret")
                rows.append({
                    "group": group_name, "side": side_name, "label": label, "n": n,
                    "signals_per_day": n / n_days_total,
                    "gross_mean_pct": gross_mean * 100, "gross_se_pct": gross_se * 100,
                    "t_gross": gross_mean / gross_se if gross_se else np.nan,
                    "net_mean_pct": net_mean * 100, "win_rate_pct": (sub[label] > 0).mean() * 100,
                })
    return pd.DataFrame(rows)


def main():
    print("괴리 지표 계산 (재스캔 없음, 저장된 T0 피처 재사용)...", flush=True)
    dataset = build_dataset()
    os.makedirs("results", exist_ok=True)
    dataset.to_parquet("results/execution_price_divergence_dataset.parquet", index=False)
    print(f"표본 {len(dataset):,}행", flush=True)

    train = dataset[dataset["date"].isin(TRAIN_DATES)].reset_index(drop=True)
    test = dataset[dataset["date"].isin(TEST_DATES)].reset_index(drop=True)

    for key in FEATURE_WINDOWS:
        feat = f"{key}_divergence"
        print(f"=== {feat} 10분위(ret_5m) IS ===")
        print(decile_table(train, feat).to_string(index=False))
        print(f"=== {feat} 10분위(ret_5m) OOS ===")
        print(decile_table(test, feat).to_string(index=False))

    report = group_comparison_report(train, test, "w3_divergence")
    report.to_csv("results/execution_price_divergence_group_report.csv", index=False)
    print("=== 느린(흡수후보) vs 빠른(이미반응) 그룹 비교 (w3_divergence) ===")
    print(report.to_string(index=False))

    return dataset, report


if __name__ == "__main__":
    main()
