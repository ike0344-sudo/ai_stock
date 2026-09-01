"""큐(3) 선후관계 — "수익이 발생하기 시작하는 시점"과 "거래량(대금)이 폭발하는
시점" 중 무엇이 먼저 오는지 초 단위로 잰다. 대금폭발이 가격보다 뒤면 이
데이터로 전조 예측은 원리적으로 어렵다 — 그러면 그렇게 쓴다(지시대로).

## 재사용
`_precursor_fastpath.to_grid`(tie-break 수정본)/`label_shoot`/`window_sum`,
`shooting_precursor_onset.cluster_bounds`(사슬병합, gap 파라미터화),
`t0_forward_return._expanding_period_avg`/`round_trip_cost_pct`,
`shooting_precursor.TRAIN_DATES`/`TEST_DATES`,
`t0_forward_return._day_clustered_mean_se`. 새로 짠 건 이벤트 페어링(가격
온셋 vs 대금폭발 온셋의 최근접 매칭)과 가속구간 탐지뿐이다.

## 두 이벤트를 각각 온셋으로 정의(큐(1)과 같은 원리 - 한복판 아니라 시작점)
- **가격상승 온셋**: 큐(1)과 **동일 정의**(`label_shoot(px, horizon=60,
  thresh=0.005)`) - 일관성을 위해 새 임계값을 안 만들었다. 초 단위 전체
  배열에 바로 적용(그리드로 안 내림 - 이 항목은 "몇 초 차이인지"가 핵심이라
  1분/10초 그리드로 뭉개면 안 된다). 클러스터 첫 초만 온셋으로 남긴다
  (`cluster_bounds(gap=60)`).
- **대금폭발 온셋**: 10초 창 거래대금 / 그 시점까지의 확장평균 거래대금이
  `BURST_MULT`(=3.0, 임의값이지만 근거 있음 - 큐(4)에서 "대량체결" 정의에
  쓴 배수와 같은 자리수, 재사용 가능하게 통일) 이상이면 폭발로 본다. 역시
  클러스터 첫 초만 온셋(`cluster_bounds(gap=10)`, 창 길이만큼).

## 선후관계 측정 — 최근접 매칭
가격상승 온셋 하나마다 `LAG_SEARCH_WINDOW`(=180초) 안에서 가장 가까운
대금폭발 온셋을 찾는다. `lag = 가격온셋 - 대금폭발온셋`(**양수 = 대금폭발이
먼저**, 음수 = 가격상승이 먼저). 매칭 안 되는 가격온셋은 "선행 대금폭발
없음"으로 따로 집계한다(이 비율 자체가 중요한 결과다 - 지시대로).

## 가속구간 — "가격상승+체결속도증가가 동시에" 자동탐지
매칭 lag의 절대값이 `ACCEL_WINDOW`(=10초) 이내인 쌍만 "동시 가속구간"으로
본다(위 180초 탐색창보다 훨씬 좁게 - "동시에"라는 표현에 맞춰 근접한
경우만). 그 가격온셋 시점을 T0 삼아 전방수익(1/3/5/10분)을 낸다 - 미래정보
없음(T0 자신이 이미 두 이벤트의 관측 결과라 이 라벨은 사후 통계용이지 실시간
예측 입력이 아니다 - 명시).

## 표본/비용
117종목 18일 전부, IS(첫12일)/OOS(뒤6일) 분리. 비용은
`round_trip_cost_pct`(왕복, 1틱 이상 슬리피지). 유의성은 일자클러스터 SE.

실행: python -m backtesting.precursor_lead_lag
"""
import glob
import os
import time

import numpy as np
import pandas as pd

from _precursor_fastpath import N, SESSION_START, label_shoot, to_grid, window_sum
from backtesting.shooting_precursor import TEST_DATES, TRAIN_DATES
from backtesting.shooting_precursor_onset import cluster_bounds
from backtesting.t0_forward_return import _day_clustered_mean_se, _expanding_period_avg, round_trip_cost_pct

PRICE_LABEL_HORIZON = 60  # 초 - 큐(1)과 동일
PRICE_RISE_THRESH = 0.005  # 큐(1)과 동일
BURST_WINDOW = 10  # 초 - 대금폭발 관측창
BURST_MULT = 3.0  # 임의값(큐(4)와 같은 자리수로 통일) - 확장평균 대비 배수
LAG_SEARCH_WINDOW = 180  # 초 - 최근접 매칭 탐색 반경
ACCEL_WINDOW = 10  # 초 - "동시" 가속구간으로 볼 lag 절대값 상한
FORWARD_HORIZONS = {"1m": 60, "3m": 180, "5m": 300, "10m": 600}


def _cluster_onsets(label: np.ndarray, gap: int) -> np.ndarray:
    true_idx = np.flatnonzero(label)
    bounds = cluster_bounds(true_idx, gap)
    return np.array([b[0] for b in bounds], dtype=np.int64)


def compute_stock_day_events(path: str, code: str, date_str: str) -> dict | None:
    g = to_grid(path)
    if g is None:
        return None
    px, vol, cnt = g["px"], g["vol"], g["cnt"]
    tick_sec, tick_prc, tick_qty = g["tick_sec"], g["tick_prc"], g["tick_qty"]

    price_label = label_shoot(px, horizon=PRICE_LABEL_HORIZON, thresh=PRICE_RISE_THRESH)
    price_onsets = _cluster_onsets(price_label, gap=PRICE_LABEL_HORIZON)

    value_per_sec = np.bincount(tick_sec, weights=tick_prc * tick_qty, minlength=N)
    cs_value = np.concatenate(([0.0], np.cumsum(value_per_sec)))
    all_sec = np.arange(N)
    win_value = window_sum(value_per_sec, BURST_WINDOW)
    avg_value = _expanding_period_avg(cs_value, all_sec, BURST_WINDOW)
    np.seterr(divide="ignore", invalid="ignore")
    burst_ratio = win_value / avg_value
    burst_label = np.nan_to_num(burst_ratio, nan=0.0) >= BURST_MULT
    burst_onsets = _cluster_onsets(burst_label, gap=BURST_WINDOW)

    return {"code": code, "date": date_str, "px": px, "price_onsets": price_onsets, "burst_onsets": burst_onsets}


def match_lags(price_onsets: np.ndarray, burst_onsets: np.ndarray, search_window: int = LAG_SEARCH_WINDOW):
    """가격온셋마다 search_window 안에서 가장 가까운 대금폭발온셋을 찾는다.
    (lag, matched_burst_t) 리스트 - lag 양수=대금폭발이 먼저."""
    results = []
    if len(burst_onsets) == 0:
        return [(p, None) for p in price_onsets]
    for p in price_onsets:
        diffs = p - burst_onsets  # 양수=버스트가 과거(먼저), 음수=버스트가 미래
        within = np.abs(diffs) <= search_window
        if not within.any():
            results.append((p, None))
            continue
        idx = np.argmin(np.abs(diffs[within]))
        results.append((p, int(diffs[within][idx])))
    return results


def scan_all(tick_dir: str = "data/stocks/tick_al") -> tuple[pd.DataFrame, pd.DataFrame]:
    """반환: (lag_df: 가격온셋마다 매칭결과, accel_df: 동시가속구간 T0의 전방수익)."""
    files = sorted(glob.glob(os.path.join(tick_dir, "*", "*.parquet")))
    lag_rows = []
    accel_frames = []
    for path in files:
        code = os.path.basename(os.path.dirname(path))
        date_str = os.path.splitext(os.path.basename(path))[0]
        ev = compute_stock_day_events(path, code, date_str)
        if ev is None:
            continue
        px = ev["px"]
        pairs = match_lags(ev["price_onsets"], ev["burst_onsets"])
        for p, lag in pairs:
            lag_rows.append({"code": code, "date": date_str, "price_onset_sec": p + SESSION_START, "lag": lag})

        accel_t0 = [p for p, lag in pairs if lag is not None and abs(lag) <= ACCEL_WINDOW]
        if not accel_t0:
            continue
        accel_t0 = np.array(accel_t0, dtype=np.int64)
        cols = {"code": code, "date": date_str, "t_sec": accel_t0 + SESSION_START, "price_t": px[accel_t0]}
        for name, h in FORWARD_HORIZONS.items():
            future_idx = accel_t0 + h
            in_range = future_idx <= N - 1
            ret = np.full(len(accel_t0), np.nan)
            ret[in_range] = px[future_idx[in_range]] / px[accel_t0[in_range]] - 1
            cols[f"ret_{name}"] = ret
        accel_frames.append(pd.DataFrame(cols))

    lag_df = pd.DataFrame(lag_rows)
    accel_df = pd.concat(accel_frames, ignore_index=True) if accel_frames else pd.DataFrame()
    return lag_df, accel_df


def accel_forward_return_report(train: pd.DataFrame, test: pd.DataFrame) -> pd.DataFrame:
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
                "net_mean_pct": net_mean * 100, "net_se_pct": net_se * 100,
                "win_rate_pct": (sub[f"ret_{name}"] > 0).mean() * 100,
            })
    return pd.DataFrame(rows)


def main():
    t0 = time.time()
    print("스캔 시작 (가격상승 온셋 vs 대금폭발 온셋 선후관계)...", flush=True)
    lag_df, accel_df = scan_all()
    dt = time.time() - t0
    os.makedirs("results", exist_ok=True)
    lag_df.to_parquet("results/precursor_lead_lag_dataset.parquet", index=False)
    if not accel_df.empty:
        accel_df.to_parquet("results/precursor_lead_lag_accel_dataset.parquet", index=False)
    print(f"완료 {dt:.1f}초 | 가격온셋 {len(lag_df):,}건", flush=True)

    matched = lag_df.dropna(subset=["lag"])
    print(f"매칭됨(180초 내 대금폭발 존재): {len(matched):,} / {len(lag_df):,} "
          f"({len(matched)/len(lag_df)*100:.1f}%)", flush=True)
    lag = matched["lag"].astype(float)
    print("=== lag(초) 분포 (양수=대금폭발이 먼저, 음수=가격상승이 먼저) ===")
    print(lag.describe(percentiles=[0.25, 0.5, 0.75]).to_string())
    print(f"대금폭발이 먼저인 비율: {(lag > 0).mean()*100:.1f}%, "
          f"가격상승이 먼저인 비율: {(lag < 0).mean()*100:.1f}%, "
          f"동시(0초): {(lag == 0).mean()*100:.1f}%")

    print(f"=== 동시 가속구간(|lag|<={ACCEL_WINDOW}초) 표본: {len(accel_df):,}행 ===")
    if not accel_df.empty:
        train = accel_df[accel_df["date"].isin(TRAIN_DATES)].reset_index(drop=True)
        test = accel_df[accel_df["date"].isin(TEST_DATES)].reset_index(drop=True)
        report = accel_forward_return_report(train, test)
        report.to_csv("results/precursor_lead_lag_accel_report.csv", index=False)
        print(report.to_string(index=False))

    return lag_df, accel_df


if __name__ == "__main__":
    main()
