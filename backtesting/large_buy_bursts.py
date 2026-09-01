"""큐(4) 매수세의 질 — 대량 매수체결이 연속 발생하는 구간을 찾아 전방수익을
내고, **대량매수 후 오른 경우와 안 오른 경우의 체결패턴 차이**를 대조표로
낸다(지시 — 이게 이 항목의 핵심).

## 재사용
`_precursor_fastpath.to_grid`(tie-break 수정본)/`window_sum`,
`shooting_precursor._tick_rule_direction`/`large_trade_flag`(**"대량" 정의를
새로 안 만들고 그대로 가져옴** - `LARGE_TRADE_MULT=3.0`, 그 순간까지의
확장평균 체결크기 대비 배수, 인과적이라 미래정보 없음 - 지시 "그 시점까지의
확장분포로 정의, 하루 전체 분포를 쓰면 미래정보"를 그대로 만족),
`shooting_precursor_onset.cluster_bounds`(사슬병합),
`t0_forward_return.round_trip_cost_pct`, `shooting_precursor.TRAIN_DATES`/
`TEST_DATES`, `t0_forward_return._day_clustered_mean_se`.

## "연속 발생 구간" 정의
대량 매수체결(tick rule 매수주도 + `large_trade_flag`) 틱들을 초 단위로
접어(그 초에 대량매수가 하나라도 있으면 1) `cluster_bounds(gap=BURST_GAP=5)`
로 병합한다 - 5초 이내로 잇따라 나오면 "연속 발생"으로 본다(임의값, 문서화).
각 구간의 **첫 초**를 T0로 삼는다(이미 진행된 구간이 아니라 시작점 - 큐(1)/
(3)과 같은 원칙).

## 체결패턴 피처 (구간별로 하나씩)
- `n_ticks`: 구간 안 대량매수 틱 수
- `duration_sec`: 구간 길이(초)
- `total_buy_value`: 구간 안 대량매수 거래대금 합
- `avg_size_mult`: 각 틱의 (수량/그 시점까지의 확장평균) 평균 - "보통보다
  몇 배 컸는지"
- `price_drift_pct`: 구간 시작→끝 가격변화율
- `concurrent_sell_value`: 같은 구간 동안의 매도주도 거래대금(합)
- `buy_share`: total_buy_value / (total_buy_value+concurrent_sell_value)
  - 매수가 그 구간 체결의 얼마를 차지했는지("매수세의 질")

## 평가
구간 T0의 전방수익(1/3/5/10분, 비용 `round_trip_cost_pct` 반영)을 낸 뒤,
**ret_5m>0(올랐다) vs 그 외(안 올랐다)로 나눠 위 6개 패턴 피처의 평균을
대조표로** 낸다(핵심 산출물). IS(첫12일)/OOS(뒤6일) 분리, 일자클러스터 SE.

실행: python -m backtesting.large_buy_bursts
"""
import glob
import os
import time

import numpy as np
import pandas as pd

from _precursor_fastpath import N, SESSION_START, to_grid, window_sum
from backtesting.shooting_precursor import TEST_DATES, TRAIN_DATES, _tick_rule_direction, large_trade_flag
from backtesting.shooting_precursor_onset import cluster_bounds
from backtesting.t0_forward_return import _day_clustered_mean_se, round_trip_cost_pct

BURST_GAP = 5  # 초 - 대량매수 틱을 "연속 발생"으로 묶는 최대 간격
FORWARD_HORIZONS = {"1m": 60, "3m": 180, "5m": 300, "10m": 600}
PATTERN_COLUMNS = ["n_ticks", "duration_sec", "total_buy_value", "avg_size_mult",
                    "price_drift_pct", "concurrent_sell_value", "buy_share"]


def compute_stock_day(path: str, code: str, date_str: str) -> pd.DataFrame | None:
    g = to_grid(path)
    if g is None:
        return None
    px = g["px"]
    tick_sec, tick_prc, tick_qty = g["tick_sec"], g["tick_prc"], g["tick_qty"]

    direction = _tick_rule_direction(tick_prc)
    large = large_trade_flag(tick_qty)
    large_buy_mask = large & (direction > 0)
    if not large_buy_mask.any():
        return None

    tick_idx = np.arange(1, len(tick_qty) + 1)
    avg_before = np.concatenate(([np.nan], np.cumsum(tick_qty)[:-1] / tick_idx[:-1])) if len(tick_qty) > 1 else np.array([np.nan])
    size_mult = tick_qty / avg_before

    large_buy_per_sec = np.bincount(tick_sec[large_buy_mask], minlength=N) > 0
    sell_value_per_sec = np.bincount(tick_sec, weights=np.where(direction < 0, tick_prc * tick_qty, 0.0), minlength=N)

    bounds = cluster_bounds(np.flatnonzero(large_buy_per_sec), gap=BURST_GAP)
    if not bounds:
        return None

    rows = []
    for start, end in bounds:
        in_cluster = large_buy_mask & (tick_sec >= start) & (tick_sec <= end)
        if not in_cluster.any():
            continue
        total_buy_value = float((tick_prc[in_cluster] * tick_qty[in_cluster]).sum())
        concurrent_sell = float(sell_value_per_sec[start:end + 1].sum())
        rows.append({
            "code": code, "date": date_str, "t_sec": start + SESSION_START,
            "price_t": px[start],
            "n_ticks": int(in_cluster.sum()),
            "duration_sec": end - start + 1,
            "total_buy_value": total_buy_value,
            "avg_size_mult": float(np.nanmean(size_mult[in_cluster])),
            "price_drift_pct": (px[end] / px[start] - 1) * 100,
            "concurrent_sell_value": concurrent_sell,
            "buy_share": total_buy_value / (total_buy_value + concurrent_sell) if (total_buy_value + concurrent_sell) > 0 else np.nan,
        })
    if not rows:
        return None

    df = pd.DataFrame(rows)
    for name, h in FORWARD_HORIZONS.items():
        t0 = (df["t_sec"] - SESSION_START).to_numpy()
        future_idx = t0 + h
        in_range = future_idx <= N - 1
        ret = np.full(len(df), np.nan)
        ret[in_range] = px[future_idx[in_range]] / px[t0[in_range]] - 1
        df[f"ret_{name}"] = ret
    return df


def scan_all(tick_dir: str = "data/stocks/tick_al") -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(tick_dir, "*", "*.parquet")))
    frames = []
    for path in files:
        code = os.path.basename(os.path.dirname(path))
        date_str = os.path.splitext(os.path.basename(path))[0]
        frame = compute_stock_day(path, code, date_str)
        if frame is not None and not frame.empty:
            frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def forward_return_report(train: pd.DataFrame, test: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for group_name, df in (("IS", train), ("OOS", test)):
        for name in FORWARD_HORIZONS:
            sub = df.dropna(subset=[f"ret_{name}"]).copy()
            if sub.empty:
                rows.append({"group": group_name, "horizon": name, "n": 0})
                continue
            sub["net_ret"] = sub[f"ret_{name}"] - round_trip_cost_pct(sub["price_t"].to_numpy())
            gross_mean, gross_se, n, n_days = _day_clustered_mean_se(sub, f"ret_{name}")
            net_mean, net_se, _, _ = _day_clustered_mean_se(sub, "net_ret")
            rows.append({
                "group": group_name, "horizon": name, "n": n, "n_days": n_days,
                "gross_mean_pct": gross_mean * 100, "gross_se_pct": gross_se * 100,
                "t_gross": gross_mean / gross_se if gross_se else np.nan,
                "net_mean_pct": net_mean * 100, "win_rate_pct": (sub[f"ret_{name}"] > 0).mean() * 100,
            })
    return pd.DataFrame(rows)


def pattern_contrast_table(df: pd.DataFrame, outcome_label: str = "ret_5m") -> pd.DataFrame:
    """대량매수 후 오른 경우(ret_5m>0) vs 안 오른 경우의 체결패턴 평균 대조표
    (핵심 산출물)."""
    sub = df.dropna(subset=[outcome_label])
    rose = sub[sub[outcome_label] > 0]
    not_rose = sub[sub[outcome_label] <= 0]
    rows = []
    for col in PATTERN_COLUMNS:
        rows.append({
            "feature": col,
            "오른_평균": rose[col].mean(), "안오른_평균": not_rose[col].mean(),
            "차이": rose[col].mean() - not_rose[col].mean(),
            "n_오름": len(rose), "n_안오름": len(not_rose),
        })
    return pd.DataFrame(rows)


def main():
    t0 = time.time()
    print("스캔 시작 (대량 매수체결 연속발생구간)...", flush=True)
    dataset = scan_all()
    dt = time.time() - t0
    os.makedirs("results", exist_ok=True)
    dataset.to_parquet("results/large_buy_bursts_dataset.parquet", index=False)
    print(f"완료 {dt:.1f}초 | 구간 {len(dataset):,}건", flush=True)

    train = dataset[dataset["date"].isin(TRAIN_DATES)].reset_index(drop=True)
    test = dataset[dataset["date"].isin(TEST_DATES)].reset_index(drop=True)

    report = forward_return_report(train, test)
    report.to_csv("results/large_buy_bursts_forward_return.csv", index=False)
    print("=== 전방수익 ===")
    print(report.to_string(index=False))

    print("=== 체결패턴 대조표 (IS) ===")
    contrast_is = pattern_contrast_table(train)
    contrast_is.to_csv("results/large_buy_bursts_pattern_contrast_is.csv", index=False)
    print(contrast_is.to_string(index=False))

    print("=== 체결패턴 대조표 (OOS) ===")
    contrast_oos = pattern_contrast_table(test)
    contrast_oos.to_csv("results/large_buy_bursts_pattern_contrast_oos.csv", index=False)
    print(contrast_oos.to_string(index=False))

    return dataset, report, contrast_is, contrast_oos


if __name__ == "__main__":
    main()
