"""슈팅 "발생 전(onset)" 재측정 — lead 후속지시(2026-08-31), §6 의심(전조 vs
진행중) 직접 검증.

## 표본 재정의 (지시)
1분 그리드에서 클러스터(겹치는 슈팅 묶음, `shooting_precursor.FEATURE_WINDOWS`
그대로) 별로:
- **positive** = 클러스터의 첫 t(그 클러스터에서 label=1이 처음 켜진 지점)
- **제외** = 클러스터의 나머지 label=1 t 전부 + 클러스터 종료 후 10분(=
  LABEL_HORIZON, 미래창 길이) — 슈팅 한복판·직후 잔열이 negative로 잘못
  들어가는 것을 막는다
- **negative** = 그 외 나머지

클러스터 경계는 `shooting_precursor.py`가 이미 저장한 `label` 컬럼
(results/shooting_precursor_dataset.parquet)으로 그리드 인덱스 상에서
사슬병합(chain-merge, gap=LABEL_HORIZON/GRID_STEP=10그리드=10분)한다 -
`_precursor_fastpath.cluster()`와 같은 "겹치면 합친다" 원칙이지만 구간의
끝(마지막 t)까지 같이 알아야 해서 직접 구현했다(cluster()는 시작점만 준다).

## 리드타임 · "이미 움직였는가"는 초단위로 - 재스캔 필요
1분 그리드로는 "30초냐 90초냐"를 못 가른다. positive t마다 원본 틱을 다시
읽어(`to_grid`/`label_shoot` 재사용, 지표는 재계산 안 함 - 11번 근사 그대로)
그 t부터 실제 +3% 를 처음 찍는 초까지 걸린 시간을 잰다. 지표값 자체는
기존 `results/shooting_precursor_dataset.parquet`(1차 결과, 안 바꿈)에서
그대로 갖다 쓴다 - (code,date,t_sec)로 조인.

## 산출
지표별 AUC(IS/OOS)·상위1%/5%정밀도를 새 표본(positive=1/negative=0,
제외 행은 뺀 뒤)으로 다시 내고 1차 결과와 나란히 비교, 리드타임 분포
(중앙값·사분위수), [t-3분,t) 상승률 분포(이미 +1%/+2% 이상 오른 비율)를 낸다.
실행: python -m backtesting.shooting_precursor_onset
"""
import glob
import os

import numpy as np
import pandas as pd

from _precursor_fastpath import N, SESSION_START, label_shoot, to_grid
from backtesting.shooting_precursor import (
    FEATURE_COLUMNS,
    GRID,
    GRID_STEP,
    LABEL_HORIZON,
    TEST_DATES,
    TRAIN_DATES,
    indicator_auc_table,
    precision_at_top,
)

GAP_STEPS = LABEL_HORIZON // GRID_STEP  # 10 그리드(=10분) 이내면 같은 클러스터
POST_EXCLUDE_STEPS = GAP_STEPS  # 클러스터 종료 후 10분(=미래창 길이) 제외


def cluster_bounds(true_grid_idx: np.ndarray, gap: int) -> list[tuple[int, int]]:
    """그리드 인덱스(0-based) 중 label=1 인 것들을 사슬병합한다 - 연속 원소
    간격이 gap 이하면 같은 클러스터. (시작idx, 끝idx) 리스트 반환."""
    if len(true_grid_idx) == 0:
        return []
    bounds = []
    start = prev = int(true_grid_idx[0])
    for i in true_grid_idx[1:]:
        i = int(i)
        if i - prev <= gap:
            prev = i
        else:
            bounds.append((start, prev))
            start = prev = i
    bounds.append((start, prev))
    return bounds


def classify_stock_day(label_grid: np.ndarray) -> np.ndarray:
    """길이 381(그리드 수)의 label bool 배열 -> 같은 길이의 카테고리 배열
    ("positive"/"excluded"/"negative")."""
    n = len(label_grid)
    category = np.full(n, "negative", dtype=object)
    true_idx = np.flatnonzero(label_grid)
    for start, end in cluster_bounds(true_idx, GAP_STEPS):
        category[start] = "positive"
        if end > start:
            category[start + 1:end + 1] = "excluded"
        post_end = min(end + POST_EXCLUDE_STEPS, n - 1)
        category[end + 1:post_end + 1] = "excluded"
    return category


def first_crossing_lead_time(px: np.ndarray, t: int, thresh: float = 0.03, horizon: int = LABEL_HORIZON) -> int:
    """t초(px 배열 인덱스)부터 처음으로 px가 px[t]*(1+thresh)를 찍는 **절대** 초
    인덱스를 반환한다(t가 아니라 t부터 걸린 시간을 원하면 호출부에서 t를 빼라).
    label=1인 t에서만 호출 - 반드시 horizon 안에서 찾아진다(그렇지 않으면
    애초에 label=1이 될 수 없었다)."""
    base = px[t]
    target = base * (1 + thresh)
    end = min(t + horizon, N - 1)
    seg = px[t:end + 1]
    hits = np.flatnonzero(seg >= target)
    return t + int(hits[0]) if len(hits) else -1  # -1이면 라벨 로직과 모순 - 발견되면 버그


def scan_all(tick_dir: str = "data/stocks/tick_al") -> pd.DataFrame:
    """전체 종목x일을 재스캔해 (code,date,t_sec,category,lead_time_sec) 표를 낸다."""
    files = sorted(glob.glob(os.path.join(tick_dir, "*", "*.parquet")))
    rows = []
    for path in files:
        code = os.path.basename(os.path.dirname(path))
        date_str = os.path.splitext(os.path.basename(path))[0]
        g = to_grid(path)
        if g is None:
            continue
        px = g["px"]
        lab_full = label_shoot(px, horizon=LABEL_HORIZON, thresh=0.03)
        label_grid = lab_full[GRID]
        category = classify_stock_day(label_grid)
        t_sec_abs = GRID + SESSION_START
        lead_time = np.full(len(GRID), -1, dtype=np.int64)
        pos_positions = np.flatnonzero(category == "positive")
        for i in pos_positions:
            t = GRID[i]
            cross = first_crossing_lead_time(px, t)
            lead_time[i] = cross - t if cross >= 0 else -1
        rows.append(pd.DataFrame({
            "code": code, "date": date_str, "t_sec": t_sec_abs,
            "category": category, "lead_time_sec": lead_time,
        }))
    return pd.concat(rows, ignore_index=True)


def main():
    import time
    t0 = time.time()
    print("재스캔 시작 (클러스터 분류 + 리드타임)...", flush=True)
    cat_df = scan_all()
    dt = time.time() - t0
    print(f"재스캔 {dt:.1f}초, 표본 {len(cat_df):,}행", flush=True)

    dataset = pd.read_parquet("results/shooting_precursor_dataset.parquet")
    merged = dataset.merge(cat_df, on=["code", "date", "t_sec"], how="inner")
    assert len(merged) == len(dataset), (
        f"조인 후 행수가 달라짐(1차 {len(dataset)} vs 조인 {len(merged)}) - "
        "그리드 정의가 어긋났다는 뜻, 원인 확인 필요"
    )
    # positive 행은 1차 label=1과 반드시 일치해야 한다(같은 label 컬럼에서 클러스터를 냈으므로).
    mismatch = merged[(merged["category"] == "positive") & (~merged["label"])]
    assert mismatch.empty, f"positive인데 1차 label=0인 행 {len(mismatch)}건 - 로직 불일치"

    print(merged["category"].value_counts().to_string())
    excluded_n = int((merged["category"] == "excluded").sum())
    kept = merged[merged["category"] != "excluded"].copy()
    kept["label_onset"] = (kept["category"] == "positive").astype(int)
    print(f"제외된 표본: {excluded_n:,}건 (1차 전체 {len(dataset):,}건 중 "
          f"{excluded_n/len(dataset)*100:.2f}%)")
    print(f"새 기저율: {kept['label_onset'].mean()*100:.4f}% "
          f"(1차 {dataset['label'].mean()*100:.4f}%)")

    kept.to_parquet("results/shooting_precursor_onset_dataset.parquet", index=False)
    cat_df.to_parquet("results/shooting_precursor_onset_categories.parquet", index=False)

    # --- 리드타임 분포 (positive만) ---
    pos = cat_df[cat_df["category"] == "positive"]
    lt = pos["lead_time_sec"]
    bad = (lt < 0).sum()
    if bad:
        print(f"경고: lead_time_sec<0(라벨-크로싱 불일치) {bad}건 - 조사 필요")
    lt_ok = lt[lt >= 0]
    print("=== 리드타임(초) 분포 (positive t -> 실제 +3% 첫 도달) ===")
    print(lt_ok.describe(percentiles=[0.25, 0.5, 0.75]).to_string())

    # --- [t-3분,t) 이미 상승 여부 (positive만, w3_drift 재사용 - 11번 근사 그대로) ---
    pos_rows = kept[kept["category"] == "positive"]
    drift = pos_rows["w3_drift"].dropna()
    thresholds = [0.0, 0.005, 0.01, 0.02, 0.03]
    print("=== positive t 시점 [t-3분,t) 드리프트 분포 ===")
    print(drift.describe(percentiles=[0.25, 0.5, 0.75]).to_string())
    for th in thresholds:
        print(f"  이미 {th*100:.1f}% 이상 상승한 비율: {(drift >= th).mean()*100:.1f}%")

    # --- IS/OOS AUC 재계산 (label -> label_onset) ---
    kept2 = kept.rename(columns={"label": "label_old", "label_onset": "label"})
    train = kept2[kept2["date"].isin(TRAIN_DATES)].reset_index(drop=True)
    test = kept2[kept2["date"].isin(TEST_DATES)].reset_index(drop=True)
    train_auc = indicator_auc_table(train)
    test_auc = indicator_auc_table(test)
    print("=== [onset] IS AUC ===")
    print(train_auc.to_string(index=False))
    print("=== [onset] OOS AUC ===")
    print(test_auc.to_string(index=False))
    train_auc.to_csv("results/shooting_precursor_onset_auc_train.csv", index=False)
    test_auc.to_csv("results/shooting_precursor_onset_auc_test.csv", index=False)

    # --- 1차 대비 비교표 ---
    old_train = pd.read_csv("results/shooting_precursor_auc_train.csv")
    old_test = pd.read_csv("results/shooting_precursor_auc_test.csv")
    cmp_is = old_train[["indicator", "auc_abs"]].merge(
        train_auc[["indicator", "auc_abs"]], on="indicator", suffixes=("_1차", "_onset"))
    cmp_is["delta"] = cmp_is["auc_abs_onset"] - cmp_is["auc_abs_1차"]
    cmp_oos = old_test[["indicator", "auc_abs"]].merge(
        test_auc[["indicator", "auc_abs"]], on="indicator", suffixes=("_1차", "_onset"))
    cmp_oos["delta"] = cmp_oos["auc_abs_onset"] - cmp_oos["auc_abs_1차"]
    print("=== IS 비교(1차 vs onset) ===")
    print(cmp_is.sort_values("auc_abs_onset", ascending=False).to_string(index=False))
    print("=== OOS 비교(1차 vs onset) ===")
    print(cmp_oos.sort_values("auc_abs_onset", ascending=False).to_string(index=False))
    cmp_is.to_csv("results/shooting_precursor_onset_auc_compare_is.csv", index=False)
    cmp_oos.to_csv("results/shooting_precursor_onset_auc_compare_oos.csv", index=False)

    # --- 상위 1%/5% 정밀도 (onset 표본 기준 상위 5개 지표) ---
    for pct in (0.01, 0.05):
        print(f"--- [onset] 상위 {pct*100:.0f}% 정밀도 ---")
        for col in train_auc.head(5)["indicator"]:
            p_train, n_train = precision_at_top(train, col, pct)
            p_test, n_test = precision_at_top(test, col, pct)
            print(f"{col}: IS n={n_train} precision={p_train:.4f} | OOS n={n_test} precision={p_test:.4f}")

    return kept, train_auc, test_auc, cmp_is, cmp_oos


if __name__ == "__main__":
    main()
