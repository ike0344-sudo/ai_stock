"""큐(6) 최종 모델 — 체결데이터 상승전조 연구 마지막 단계.

사전등록: docs/PRECURSOR_FINAL_MODEL_PREREGISTRATION.md (반드시 먼저 읽을 것 —
피처 선정 근거, 60초 예산 제약, 라벨 정의, 기각조건이 전부 거기 못박혀 있다).

## 재사용 (중복 구현 금지)
`_precursor_fastpath.to_grid`(tie-break 수정본)/`label_shoot`/`window_sum`,
`shooting_precursor.TRAIN_DATES`/`TEST_DATES`/`_tick_rule_direction`/`_shift_window_sum`,
`t0_forward_return._expanding_period_avg`/`round_trip_cost_pct`/`_day_clustered_mean_se`,
`precursor_10_60s.classify_stock_day`(§7.3 온셋격리 민감도 점검에만 사용, 주 라벨에는
안 씀 — 사전등록 §2 구현결정 참고), `backtesting.ml.model.train`/`predict`
(RandomForestClassifier 래퍼, 새 학습기 안 만듦).

## 피처 — 60초 예산 (사전등록 §1)
tick_speed(10/20/30/60초)·buy_sell_gap(10/20/30/60초, 부호반전 주의)·
value_surge(1/3/5/10초, 초단위 축)·price_speed(60초만)·divergence(60초만) — 총 14개.
전부 T0 이전 60초 이내 데이터로만 계산된다(window_sum/_expanding_period_avg는 둘 다
[T0-w, T0) 구간만 본다 - 미래 정보 없음).

## 라벨
`label_shoot(px, horizon=300, thresh=0.02)` — 5분 안에 최고가가 +2% 이상.
평가용 실현수익은 별도로 `ret_5m`(T0+300초 시점 **종가** 수익률, 고정청산) — 예측력
(AUC, label 기준)과 수익성(순수익, ret_5m 기준)을 절대 안 섞는다(사전등록 §5).

실행: python -m backtesting.precursor_final_model
"""
import glob
import os
import time

import numpy as np
import pandas as pd

from _precursor_fastpath import N, SESSION_START, label_shoot, to_grid, window_sum
from backtesting.ml import model as ml_model
from backtesting.precursor_10_60s import classify_stock_day
from backtesting.shooting_precursor import TEST_DATES, TRAIN_DATES, _shift_window_sum, _tick_rule_direction
from backtesting.t0_forward_return import _day_clustered_mean_se, _expanding_period_avg, round_trip_cost_pct

GRID_STEP = 10       # 초
LABEL_HORIZON = 300  # 초 (5분)
LABEL_THRESH = 0.02  # +2%
GAP_STEPS = LABEL_HORIZON // GRID_STEP  # 30그리드 - §7.3 온셋격리 민감도 점검용

FEATURE_WINDOWS = {"w10": 10, "w20": 20, "w30": 30, "w60": 60}       # tick_speed/buy_sell_gap (초)
VALUE_SURGE_WINDOWS = {"vs1": 1, "vs3": 3, "vs5": 5, "vs10": 10}     # value_surge 초단위 축
PRICE_SPEED_WINDOW = 60  # price_speed/divergence - 60초 예산상 이것만

T0_GRID = np.arange(0, N - LABEL_HORIZON, GRID_STEP)

FEATURE_COLUMNS = (
    [f"{k}_tick_speed" for k in FEATURE_WINDOWS]
    + [f"{k}_buy_sell_gap" for k in FEATURE_WINDOWS]
    + [f"{k}_value_surge" for k in VALUE_SURGE_WINDOWS]
    + ["w60_price_speed", "w60_divergence"]
)


def compute_stock_day(path: str, code: str, date_str: str) -> pd.DataFrame | None:
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

    label_full = label_shoot(px, horizon=LABEL_HORIZON, thresh=LABEL_THRESH)
    label_grid = label_full[T0_GRID]
    # §7.3 민감도 점검 전용(주 라벨엔 안 씀) - precursor_10_60s와 동일 함수 재사용.
    onset_category = classify_stock_day(label_grid, GAP_STEPS, GAP_STEPS)

    future_idx = T0_GRID + LABEL_HORIZON
    ret_5m = px[future_idx] / px[T0_GRID] - 1

    cols = {
        "code": code, "date": date_str, "t_sec": T0_GRID + SESSION_START,
        "price_t": px[T0_GRID], "label": label_grid.astype(int),
        "ret_5m": ret_5m, "onset_category": onset_category,
    }

    np.seterr(divide="ignore", invalid="ignore")
    for key, w in FEATURE_WINDOWS.items():
        win_cnt = window_sum(cnt, w)
        win_buy = window_sum(buy_qty_per_sec, w)
        win_sell = window_sum(sell_qty_per_sec, w)
        win_vol = window_sum(vol, w)

        tick_speed = win_cnt / w
        buy_sell_gap = (win_buy - win_sell) / win_vol
        buy_sell_gap[win_vol == 0] = np.nan

        cols[f"{key}_tick_speed"] = tick_speed[T0_GRID]
        cols[f"{key}_buy_sell_gap"] = buy_sell_gap[T0_GRID]

    for key, w in VALUE_SURGE_WINDOWS.items():
        win_value = window_sum(value_per_sec, w)
        avg_value = _expanding_period_avg(cs_value, T0_GRID, w)
        value_surge = win_value / avg_value
        value_surge[avg_value == 0] = np.nan
        cols[f"{key}_value_surge"] = value_surge[T0_GRID]

    w = PRICE_SPEED_WINDOW
    drift = np.full(N, np.nan)
    start_idx = np.clip(T0_GRID - w, 0, N - 1)
    end_idx = np.clip(T0_GRID - 1, 0, N - 1)
    valid_drift = T0_GRID - w >= 0
    drift[T0_GRID[valid_drift]] = px[end_idx[valid_drift]] / px[start_idx[valid_drift]] - 1
    price_speed = drift / w
    cols["w60_price_speed"] = price_speed[T0_GRID]

    win_value_60 = window_sum(value_per_sec, w)
    avg_value_60 = _expanding_period_avg(cs_value, T0_GRID, w)
    value_surge_60 = win_value_60 / avg_value_60
    value_surge_60[avg_value_60 == 0] = np.nan
    divergence_60 = price_speed[T0_GRID] / value_surge_60[T0_GRID]
    divergence_60[value_surge_60[T0_GRID] == 0] = np.nan
    cols["w60_divergence"] = divergence_60

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


def indicator_auc_table(df: pd.DataFrame) -> pd.DataFrame:
    """단일피처 AUC 스크리닝. category 마스킹 없음(온셋격리 안 함, 사전등록 §2)."""
    from sklearn.metrics import roc_auc_score
    y = df["label"].to_numpy()
    rows = []
    for col in FEATURE_COLUMNS:
        x = df[col]
        mask = x.notna()
        n = int(mask.sum())
        if n < 100 or y[mask].sum() == 0 or y[mask].sum() == n:
            rows.append({"indicator": col, "n": n, "auc": np.nan, "auc_abs": np.nan, "note": "표본부족/단일클래스"})
            continue
        auc = roc_auc_score(y[mask], x[mask])
        rows.append({"indicator": col, "n": n, "auc": auc, "auc_abs": max(auc, 1 - auc), "note": ""})
    return pd.DataFrame(rows).sort_values("auc_abs", ascending=False, na_position="last")


def evaluate_condition(train: pd.DataFrame, test: pd.DataFrame, conditions: dict,
                        label: str = "ret_5m") -> pd.DataFrame:
    """conditions: {feature: (direction, threshold)}, direction는 '>=' 또는 '<='.

    t0_forward_return.entry_condition_stats와 같은 통계(총수익/순수익/승률/
    일자클러스터SE)를 내지만, 그쪽은 "<=" 방향만 지원해서(price_speed 전용으로
    짜여 있음) 여기서는 피처마다 방향이 다를 수 있어(예: tick_speed는 높을수록,
    buy_sell_gap은 낮을수록) 방향을 파라미터화한 버전을 따로 둔다 - 통계 계산
    자체(_day_clustered_mean_se/round_trip_cost_pct)는 그대로 재사용."""
    rows = []
    for group_name, df in (("IS", train), ("OOS", test)):
        mask = pd.Series(True, index=df.index)
        for feat, (direction, thr) in conditions.items():
            mask &= (df[feat] >= thr) if direction == ">=" else (df[feat] <= thr)
        sub = df[mask].dropna(subset=[label]).copy()
        n_days_total = df["date"].nunique()
        if sub.empty:
            rows.append({"group": group_name, "n": 0})
            continue
        sub["net_ret"] = sub[label] - round_trip_cost_pct(sub["price_t"].to_numpy())
        gross_mean, gross_se, n, n_days = _day_clustered_mean_se(sub, label)
        net_mean, net_se, _, _ = _day_clustered_mean_se(sub, "net_ret")
        rows.append({
            "group": group_name, "n": n, "n_days": n_days,
            "signals_per_day": n / n_days_total,
            "gross_mean_pct": gross_mean * 100, "gross_se_pct": gross_se * 100,
            "t_gross": gross_mean / gross_se if gross_se else np.nan,
            "net_mean_pct": net_mean * 100, "net_se_pct": net_se * 100,
            "win_rate_pct": (sub[label] > 0).mean() * 100,
        })
    return pd.DataFrame(rows)


def random_baseline(test: pd.DataFrame, n_select: int, label: str = "ret_5m",
                     n_draws: int = 200, seed: int = 42) -> dict:
    """같은 건수를 OOS 전체에서 무작위 재추첨(복원없이), n_draws회 반복한 net EV
    평균들의 평균/표준편차 - 규율(4)(RL_DISCIPLINE_PREREGISTRATION.md)와 같은
    무작위 대조군 개념."""
    rng = np.random.default_rng(seed)
    net_costs = round_trip_cost_pct(test["price_t"].to_numpy())
    net_all = (test[label] - net_costs).to_numpy()
    n_select = min(n_select, len(test))
    means = [net_all[rng.choice(len(test), size=n_select, replace=False)].mean() for _ in range(n_draws)]
    return {"n_select": n_select, "net_mean_pct": float(np.mean(means)) * 100,
            "net_std_pct": float(np.std(means)) * 100}


def always_enter_baseline(test: pd.DataFrame, label: str = "ret_5m") -> dict:
    net = test[label] - round_trip_cost_pct(test["price_t"].to_numpy())
    mean, se, n, n_days = _day_clustered_mean_se(test.assign(net_ret=net), "net_ret")
    return {"n": n, "net_mean_pct": mean * 100, "net_se_pct": se * 100}


def main():
    t0 = time.time()
    n_files = len(glob.glob("data/stocks/tick_al/*/*.parquet"))
    print(f"스캔 시작 (tick_al {n_files}개 파일, 10초 그리드, 60초 예산 피처 14개)...", flush=True)
    print("ETA 추정: 큐(1)이 비슷한 규모(4.7M행)로 33.4초였다 - 이번은 피처 수가 비슷하니 "
          "스캔은 30~60초대, RF 학습(n_jobs=-1)까지 합쳐 총 5분 이내로 예상.", flush=True)

    dataset = scan_all()
    dt_scan = time.time() - t0
    os.makedirs("results", exist_ok=True)
    dataset.to_parquet("results/precursor_final_model_dataset.parquet", index=False)
    print(f"스캔 {dt_scan:.1f}초 | 표본 {len(dataset):,}행 | 양성비율 {dataset['label'].mean()*100:.3f}%", flush=True)

    train = dataset[dataset["date"].isin(TRAIN_DATES)].reset_index(drop=True)
    test = dataset[dataset["date"].isin(TEST_DATES)].reset_index(drop=True)

    # 1) 단일피처 AUC 스크리닝
    train_auc = indicator_auc_table(train)
    test_auc = indicator_auc_table(test)
    train_auc.to_csv("results/precursor_final_model_auc_train.csv", index=False)
    test_auc.to_csv("results/precursor_final_model_auc_test.csv", index=False)
    print("=== IS 단일피처 AUC ===")
    print(train_auc.to_string(index=False))
    print("=== OOS 단일피처 AUC ===")
    print(test_auc.to_string(index=False))

    # 2) RandomForest (IS 학습, OOS 1회 적용)
    t1 = time.time()
    trained = ml_model.train(train[FEATURE_COLUMNS], train["label"], model_type="random_forest", n_jobs=-1)
    proba_is = ml_model.predict(trained, train[FEATURE_COLUMNS])
    proba_oos = ml_model.predict(trained, test[FEATURE_COLUMNS])
    print(f"RF 학습+예측 {time.time()-t1:.1f}초", flush=True)

    from sklearn.metrics import roc_auc_score
    model_auc_is = roc_auc_score(train["label"], proba_is)
    model_auc_oos = roc_auc_score(test["label"], proba_oos)
    print(f"모델 AUC: IS {model_auc_is:.4f} / OOS {model_auc_oos:.4f}")

    # IS 상위 10% 문턱(고정값)을 OOS에 그대로 적용
    threshold = proba_is.quantile(0.90)
    train_top = train[proba_is >= threshold].copy()
    test_top = test[proba_oos >= threshold].copy()
    print(f"IS 상위10% 문턱값(고정) = {threshold:.4f}")

    def _top_stats(df, name):
        if df.empty:
            return {"group": name, "n": 0}
        net = df["ret_5m"] - round_trip_cost_pct(df["price_t"].to_numpy())
        gross_mean, gross_se, n, n_days = _day_clustered_mean_se(df, "ret_5m")
        net_mean, net_se, _, _ = _day_clustered_mean_se(df.assign(net_ret=net), "net_ret")
        return {"group": name, "n": n, "n_days": n_days,
                "gross_mean_pct": gross_mean * 100, "net_mean_pct": net_mean * 100,
                "net_se_pct": net_se * 100, "t_net": net_mean / net_se if net_se else np.nan,
                "win_rate_pct": (df["ret_5m"] > 0).mean() * 100}

    model_top_report = pd.DataFrame([_top_stats(train_top, "IS_모델상위10%"), _top_stats(test_top, "OOS_모델상위10%")])
    print("=== 모델 상위10% 신호 성과 ===")
    print(model_top_report.to_string(index=False))

    # 3) 해석가능 규칙 (IS AUC 상위, 서로 다른 계열에서 누적 결합)
    direction_by_feature = {row["indicator"]: (">=" if row["auc"] >= 0.5 else "<=")
                             for _, row in train_auc.dropna(subset=["auc"]).iterrows()}
    candidates = ["w60_tick_speed", "w10_buy_sell_gap", "w60_price_speed"]
    conditions = {}
    rule_reports = []
    for feat in candidates:
        direction = direction_by_feature.get(feat, ">=")
        q = 0.90 if direction == ">=" else 0.10
        thr = train[feat].quantile(q)
        conditions[feat] = (direction, thr)
        report = evaluate_condition(train, test, dict(conditions))
        report["conditions"] = " & ".join(f"{k}{d}{v:.4g}" for k, (d, v) in conditions.items())
        rule_reports.append(report)
    rule_report = pd.concat(rule_reports, ignore_index=True)
    rule_report.to_csv("results/precursor_final_model_rule_conditions.csv", index=False)
    print("=== 해석가능 규칙 (누적 결합 1~3개) ===")
    print(rule_report.to_string(index=False))

    # 4) 대조군
    always = always_enter_baseline(test)
    random_ctrl = random_baseline(test, n_select=len(test_top))
    print(f"=== 대조군(OOS) === 상시진입: {always} | 무작위(같은건수 {len(test_top)}, 200회): {random_ctrl}")

    # 5) §7.3 온셋격리 민감도 점검 (평가표본만 재필터, 재학습 없음)
    test_isolated = test[test["onset_category"] != "excluded"].copy()
    test_isolated_label = (test_isolated["onset_category"] == "positive").astype(int)
    proba_oos_isolated = proba_oos.loc[test_isolated.index]
    auc_isolated = roc_auc_score(test_isolated_label, proba_oos_isolated) if test_isolated_label.nunique() > 1 else np.nan
    test_top_isolated = test_isolated[proba_oos_isolated >= threshold]
    top_isolated_stats = _top_stats(test_top_isolated, "OOS_모델상위10%_온셋격리")
    print(f"=== §7.3 민감도: 온셋격리 재평가 OOS AUC={auc_isolated:.4f} (전체 OOS AUC={model_auc_oos:.4f}) ===")
    print(top_isolated_stats)

    dt_total = time.time() - t0
    print(f"전체 파이프라인 {dt_total:.1f}초", flush=True)

    return {
        "dataset": dataset, "train_auc": train_auc, "test_auc": test_auc,
        "model_auc_is": model_auc_is, "model_auc_oos": model_auc_oos,
        "model_top_report": model_top_report, "rule_report": rule_report,
        "always": always, "random_ctrl": random_ctrl,
        "auc_isolated": auc_isolated, "top_isolated_stats": top_isolated_stats,
    }


if __name__ == "__main__":
    main()
