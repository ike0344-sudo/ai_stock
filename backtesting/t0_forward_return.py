"""T0 기준 전방수익 회귀 — 사용자 직접지시(2026-08-31), 희귀사건 분류(1차/onset)
대신 회귀로 전환. 기저율 0.2% 문제(표본이 대부분 버려지는 문제)에서 벗어나는
것이 목적 - **T0는 1분 그리드 전 지점**이다(onset처럼 거르지 않는다).

## 재사용
`_precursor_fastpath.to_grid`(tie-break 수정본, `shooting_precursor.py`에서
검증·수정 완료) 그대로 쓴다. tick rule 방향판정(`_tick_rule_direction`)과
"이전 동일길이 창" 시프트(`_shift_window_sum`)도 `shooting_precursor.py`에서
그대로 가져온다 - 로직 중복 금지.

## 라벨
`ret_1m/3m/5m/10m = px[T0+k]/px[T0]-1` (k=60/180/300/600초). 미래창이 세션
끝(15:30:00)을 넘으면 **그 라벨만** NaN - 행 전체를 버리지 않는다(1분 라벨은
막판까지 거의 다 살아있다).

## 피처 6개 x 창 3개(1분/3분/10분) - 전부 O(1)
1. **체결금액 순간증가** = 창 거래대금(가격x수량) 합 / 그 시점까지의 동일길이
   확장평균(인과적, `shooting_precursor.py`의 vol_ratio와 같은 패턴이지만
   거래량이 아니라 **거래대금**).
2. **매수체결비율** = tick rule 매수주도 거래량 / 창 전체 거래량. pred_pre_sig는
   전일종가 대비 부호라 못 쓴다(`shooting_precursor.py`에서 실증).
3. **체결속도** = 창 내 초당 틱 수.
4. **가격상승속도** = 창 수익률 / 창 길이(초) - 창 간 비교 가능하게 초당 정규화.
5. **거래대금 가속도** = 창 거래대금 / 직전 동일길이 창 거래대금 - 1 (레벨이
   아니라 변화율).
6. **체결강도 변화율** = 체결강도(매수체결량/매도체결량x100, tick rule 기준)의
   창 대비 직전 동일길이 창 변화율.

## 비용 모델 (지시 — "이게 빠지면 결론이 뒤집힌다")
이 저장소의 `breakout_reversal.DEFAULT_*` 그대로 쓰되, 슬리피지는 "1틱 이상
보수적으로" - KRX 호가단위표로 각 행의 실제 가격(`price_t`)에서 1틱이
몇 %인지 계산해 `max(DEFAULT_SLIPPAGE_RATE, 1틱/가격)`을 그 행의 편도
슬리피지로 쓴다(정액이 아니라 정률 하한이라 저가주에서 과소평가되는 걸 막는다).
왕복비용 = 수수료x2 + 세금(매도 1회) + 슬리피지x2(편도 각각).

## 평가
- Spearman IC(피처 vs 라벨 4개, 전부 표) - 상관이 상수 이동(비용 차감)에
  불변이라 총수익/순수익 구분 없이 계산한다.
- 십분위 분석은 방대해지는 걸 막으려 **IC로 먼저 스크리닝한 뒤 상위만** 전체
  10분위(평균 ret_5m + 일자클러스터 SE + 표본수)로 낸다 - "다 해보고 되는
  것만 남긴다" 원칙을 IC표(전체) + 십분위표(상위) 2단으로 구현.
- 유의성은 1분 간격 표본의 자기상관을 감안해 **일자 단위로 묶어 일별 평균의
  분산**으로 낸다(`_day_clustered_mean_se`).

## 산출
scan_all()이 전 구간 T0 표본을 만들고, main()이 IS(첫12일)/OOS(뒤6일)로 나눠
IC·십분위·진입조건(2~3개 피처 문턱 조합, IS선정→OOS적용)을 낸다.
실행: python -m backtesting.t0_forward_return
"""
import glob
import os
import time

import numpy as np
import pandas as pd

from _precursor_fastpath import N, SESSION_START, to_grid, window_sum
from backtesting.breakout_reversal import (
    DEFAULT_COMMISSION_RATE,
    DEFAULT_SLIPPAGE_RATE,
    DEFAULT_TAX_RATE,
)
from backtesting.shooting_precursor import (
    TEST_DATES,
    TRAIN_DATES,
    _shift_window_sum,
    _tick_rule_direction,
)

GRID_STEP = 60
FEATURE_WINDOWS = {"w1": 60, "w3": 180, "w10": 600}  # 1분/3분/10분
LABEL_HORIZONS = {"1m": 60, "3m": 180, "5m": 300, "10m": 600}
T0_GRID = np.arange(0, N, GRID_STEP)  # 세션 전체(09:00:00~15:30:00), 필터 없음

FEATURE_NAMES = ("value_surge", "buy_ratio", "tick_speed", "price_speed",
                  "value_accel", "intensity_change")
FEATURE_COLUMNS = [f"{key}_{name}" for key in FEATURE_WINDOWS for name in FEATURE_NAMES]
LABEL_COLUMNS = [f"ret_{k}" for k in LABEL_HORIZONS]


def krx_tick_size(price: float) -> float:
    """KRX 호가단위표(원). 종목 가격대별 최소 호가 간격."""
    if price < 2_000:
        return 1.0
    if price < 5_000:
        return 5.0
    if price < 20_000:
        return 10.0
    if price < 50_000:
        return 50.0
    if price < 200_000:
        return 100.0
    if price < 500_000:
        return 500.0
    return 1_000.0


def round_trip_cost_pct(price: np.ndarray, commission_rate=DEFAULT_COMMISSION_RATE,
                         slippage_rate=DEFAULT_SLIPPAGE_RATE, tax_rate=DEFAULT_TAX_RATE) -> np.ndarray:
    """가격별 왕복비용(%, 소수) = 수수료x2 + 세금(매도1회) + 슬리피지x2(편도씩,
    각 편도는 기본율과 "1틱/가격" 중 큰 쪽 - 저가주에서 슬리피지가 과소평가되는
    걸 막는다)."""
    tick_pct = np.vectorize(krx_tick_size)(price) / price
    per_side_slippage = np.maximum(slippage_rate, tick_pct)
    return commission_rate * 2 + tax_rate + per_side_slippage * 2


def _expanding_period_avg(cum_series: np.ndarray, grid: np.ndarray, w: int) -> np.ndarray:
    """grid[i] 지점 창 시작(=grid[i]-w) 이전까지의 누적값 / 그때까지 지난
    동일길이(w) 구간 수(인과적 - 미래 정보 없음). cum_series[k] = series[0:k].sum()."""
    out = np.full(N, np.nan)
    k = grid - w
    ok = k >= 0
    elapsed = k[ok] / w
    valid = elapsed >= 1
    idx = grid[ok][valid]
    out[idx] = cum_series[k[ok][valid]] / elapsed[valid]
    return out


def compute_stock_day(path: str, code: str, date_str: str):
    g = to_grid(path)
    if g is None:
        return None

    px, vol, cnt = g["px"], g["vol"], g["cnt"]
    tick_sec, tick_prc, tick_qty = g["tick_sec"], g["tick_prc"], g["tick_qty"]

    direction = _tick_rule_direction(tick_prc)
    buy_qty_per_sec = np.bincount(tick_sec, weights=np.where(direction > 0, tick_qty, 0.0), minlength=N)
    sell_qty_per_sec = np.bincount(tick_sec, weights=np.where(direction < 0, tick_qty, 0.0), minlength=N)
    value_per_sec = np.bincount(tick_sec, weights=tick_prc * tick_qty, minlength=N)
    cs_value = np.concatenate(([0.0], np.cumsum(value_per_sec)))

    cols = {"code": code, "date": date_str, "t_sec": T0_GRID + SESSION_START, "price_t": px[T0_GRID]}

    for name, k in LABEL_HORIZONS.items():
        future_idx = T0_GRID + k
        in_range = future_idx <= N - 1
        ret = np.full(len(T0_GRID), np.nan)
        ret[in_range] = px[future_idx[in_range]] / px[T0_GRID[in_range]] - 1
        cols[f"ret_{name}"] = ret

    np.seterr(divide="ignore", invalid="ignore")
    for key, w in FEATURE_WINDOWS.items():
        win_value = window_sum(value_per_sec, w)
        win_vol = window_sum(vol, w)
        win_cnt = window_sum(cnt, w)
        win_buy = window_sum(buy_qty_per_sec, w)
        win_sell = window_sum(sell_qty_per_sec, w)

        avg_value = _expanding_period_avg(cs_value, T0_GRID, w)
        value_surge = win_value / avg_value

        buy_ratio = win_buy / win_vol
        buy_ratio[win_vol == 0] = np.nan

        tick_speed = win_cnt / w

        drift = np.full(N, np.nan)
        start_idx = np.clip(T0_GRID - w, 0, N - 1)
        end_idx = np.clip(T0_GRID - 1, 0, N - 1)
        valid_drift = T0_GRID - w >= 0
        drift[T0_GRID[valid_drift]] = px[end_idx[valid_drift]] / px[start_idx[valid_drift]] - 1
        price_speed = drift / w

        prev_value = _shift_window_sum(win_value, w)
        value_accel = win_value / prev_value - 1
        value_accel[prev_value == 0] = np.nan

        intensity = win_buy / win_sell * 100
        intensity[win_sell == 0] = np.nan
        prev_intensity = _shift_window_sum(intensity, w)
        intensity_change = intensity / prev_intensity - 1
        intensity_change[(prev_intensity == 0) | np.isnan(prev_intensity)] = np.nan

        cols[f"{key}_value_surge"] = value_surge[T0_GRID]
        cols[f"{key}_buy_ratio"] = buy_ratio[T0_GRID]
        cols[f"{key}_tick_speed"] = tick_speed[T0_GRID]
        cols[f"{key}_price_speed"] = price_speed[T0_GRID]
        cols[f"{key}_value_accel"] = value_accel[T0_GRID]
        cols[f"{key}_intensity_change"] = intensity_change[T0_GRID]

    df = pd.DataFrame(cols)
    df = df[df["price_t"].notna() & (df["price_t"] > 0)].reset_index(drop=True)
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


def _day_clustered_mean_se(df: pd.DataFrame, value_col: str) -> tuple[float, float, int, int]:
    """겹치는 1분 표본의 자기상관 문제 - 일자별 평균을 먼저 낸 뒤 그 일자평균들의
    표준오차로 유의성을 본다. 반환: (전체평균, 일자클러스터SE, 표본수, 일수)."""
    daily = df.groupby("date")[value_col].mean()
    n_days = len(daily)
    se = daily.std(ddof=1) / np.sqrt(n_days) if n_days > 1 else np.nan
    return float(df[value_col].mean()), float(se), len(df), n_days


def spearman_ic_table(df: pd.DataFrame) -> pd.DataFrame:
    cols = FEATURE_COLUMNS + LABEL_COLUMNS
    corr = df[cols].corr(method="spearman")
    rows = []
    for feat in FEATURE_COLUMNS:
        for label in LABEL_COLUMNS:
            n = df[[feat, label]].dropna().shape[0]
            rows.append({"feature": feat, "label": label, "ic": corr.loc[feat, label], "n": n})
    return pd.DataFrame(rows)


def decile_table(df: pd.DataFrame, feature: str, label: str = "ret_5m") -> pd.DataFrame:
    sub = df[[feature, label, "date"]].dropna()
    if sub.empty:
        return pd.DataFrame()
    sub = sub.copy()
    try:
        sub["decile"] = pd.qcut(sub[feature], 10, labels=False, duplicates="drop")
    except ValueError:
        return pd.DataFrame()
    rows = []
    for d, g in sub.groupby("decile"):
        mean, se, n, n_days = _day_clustered_mean_se(g, label)
        rows.append({"decile": int(d), "mean_ret5m": mean, "se": se, "n": n, "n_days": n_days})
    return pd.DataFrame(rows).sort_values("decile")


def entry_condition_stats(train: pd.DataFrame, test: pd.DataFrame, thresholds: dict[str, float],
                           label: str = "ret_5m") -> pd.DataFrame:
    """`thresholds`(피처->IS 하위분위 문턱값, 전부 "이 값 이하"로 AND 결합)를 IS에서
    구해 그대로 OOS에 적용 - 그룹(IS/OOS)별 발생빈도·총수익·순수익·중앙값·승률·
    최악일평균·일자클러스터SE를 낸다. 순수익은 `round_trip_cost_pct(price_t)`를
    그 행 그대로 차감."""
    rows = []
    for group_name, df in (("IS", train), ("OOS", test)):
        mask = pd.Series(True, index=df.index)
        for feat, thr in thresholds.items():
            mask &= df[feat] <= thr
        sub = df[mask].dropna(subset=[label]).copy()
        n_days_total = df["date"].nunique()
        if sub.empty:
            rows.append({"group": group_name, "n": 0})
            continue
        sub["net_ret"] = sub[label] - round_trip_cost_pct(sub["price_t"].to_numpy())
        gross_mean, gross_se, n, n_days = _day_clustered_mean_se(sub, label)
        net_mean, net_se, _, _ = _day_clustered_mean_se(sub, "net_ret")
        daily_gross = sub.groupby("date")[label].mean()
        rows.append({
            "group": group_name, "n": n, "n_days_triggered": n_days,
            "signals_per_day": n / n_days_total,
            "gross_mean_pct": gross_mean * 100, "gross_se_pct": gross_se * 100,
            "net_mean_pct": net_mean * 100, "net_se_pct": net_se * 100,
            "median_pct": sub[label].median() * 100,
            "win_rate_pct": (sub[label] > 0).mean() * 100,
            "worst_day_mean_pct": daily_gross.min() * 100,
        })
    return pd.DataFrame(rows)


def main():
    t0 = time.time()
    print("스캔 시작 (tick_al 전체, T0 회귀용 피처+라벨)...", flush=True)
    dataset = scan_all()
    dt = time.time() - t0
    os.makedirs("results", exist_ok=True)
    dataset.to_parquet("results/t0_forward_return_dataset.parquet", index=False)
    print(f"스캔 {dt:.1f}초 | 표본 {len(dataset):,}행", flush=True)

    train = dataset[dataset["date"].isin(TRAIN_DATES)].reset_index(drop=True)
    test = dataset[dataset["date"].isin(TEST_DATES)].reset_index(drop=True)
    print(f"IS {len(train):,}행 / OOS {len(test):,}행", flush=True)

    train_ic = spearman_ic_table(train)
    test_ic = spearman_ic_table(test)
    train_ic.to_csv("results/t0_ic_train.csv", index=False)
    test_ic.to_csv("results/t0_ic_test.csv", index=False)
    print("=== IS Spearman IC (feature x label) ===")
    print(train_ic.pivot(index="feature", columns="label", values="ic").to_string())
    print("=== OOS Spearman IC ===")
    print(test_ic.pivot(index="feature", columns="label", values="ic").to_string())

    # IS 상위(|IC| 기준) 지표로 10분위표 - IS→OOS 재현 여부 확인
    for feat in ("w3_price_speed", "w10_buy_ratio", "w10_tick_speed"):
        print(f"=== {feat} 10분위(ret_5m) IS ===")
        print(decile_table(train, feat).to_string(index=False))
        print(f"=== {feat} 10분위(ret_5m) OOS ===")
        print(decile_table(test, feat).to_string(index=False))

    # 진입조건 - IS 하위10% 문턱, 피처 1/2/3개 누적
    q = {feat: train[feat].quantile(0.10) for feat in ("w3_price_speed", "w1_price_speed", "w10_price_speed")}
    combos = {
        "w3_price_speed 단독(하위10%)": {"w3_price_speed": q["w3_price_speed"]},
        "w3+w1 price_speed(둘다 하위10%)": {"w3_price_speed": q["w3_price_speed"], "w1_price_speed": q["w1_price_speed"]},
        "w3+w1+w10 price_speed(셋다 하위10%)": dict(q),
    }
    all_cond = []
    for name, thr in combos.items():
        stats = entry_condition_stats(train, test, thr)
        stats.insert(0, "condition", name)
        print(f"=== 진입조건: {name} ===")
        print(stats.to_string(index=False))
        all_cond.append(stats)
    pd.concat(all_cond, ignore_index=True).to_csv("results/t0_entry_conditions.csv", index=False)

    return dataset, train, test, train_ic, test_ic


if __name__ == "__main__":
    main()
