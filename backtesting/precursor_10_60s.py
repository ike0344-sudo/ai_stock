"""상승 직전 10~60초 — 큐 (1)번(2026-08-31 사용자 지시 5단계 중 1번, lead가
가장 먼저 하라고 지목). "사후적으로 당연히 좋아 보이는 지표"를 걸러내는 게
목적이라, 상승 후 구간이 표본에 섞이지 않도록 **격리 방법**이 이 스크립트의
핵심이다 — 아래 "격리" 절에서 어떻게 했는지 밝힌다.

## 재사용 (중복 구현 금지)
`_precursor_fastpath.to_grid`(tie-break 수정본)/`label_shoot`/`window_sum`,
`shooting_precursor._tick_rule_direction`/`_shift_window_sum`,
`shooting_precursor_onset.cluster_bounds`(사슬병합, gap 파라미터화돼 있어
그대로 재사용), `t0_forward_return._expanding_period_avg`/`round_trip_cost_pct`,
`shooting_precursor.TRAIN_DATES`/`TEST_DATES`,
`t0_forward_return._day_clustered_mean_se`. 새로 짠 건 이 스터디 고유의
초단위 그리드·피처·라벨·AUC/십분위 집계뿐이다.

## 격리 — "상승 후 구간"이 안 섞이게 (이 항목의 핵심)
`shooting_precursor_onset.py`(1차 리포트 §6 검증)에서 이미 검증한 3분할을
그대로 쓴다:
- **positive** = 상승 이벤트(라벨=1) 클러스터의 **첫 t만**(그 상승이 처음
  감지된 순간) - "이미 오르고 있는 중" 구간이 아니라 "막 오르기 시작한"
  순간만 남긴다.
- **제외** = 클러스터의 나머지 라벨=1 t 전부(=상승 한복판) + 클러스터 종료
  후 라벨호라이즌만큼(=상승 직후 잔열) - 둘 다 "상승 후"라 버린다.
- **negative** = 그 외 나머지(정말 아무 일도 없던 구간).

**관측창([T0-W,T0))은 T0 자신을 포함하지 않는다** - positive의 관측창도
"막 오르기 시작하기 **직전**"까지만 본다. 이게 "사후적으로 당연히 좋아
보이는" 오염(상승이 이미 시작된 뒤의 활동성을 "전조"라고 착각하는 것)을
차단하는 장치다.

## 라벨 정의 — 왜 이 값인가
60초 안에 +0.5% 이상 오르면 상승(`label_shoot(px, horizon=60, thresh=0.005)`
재사용). 60초를 horizon으로 고른 이유: 피처 관측창 4개(10/20/30/60초) 중
가장 긴 것과 맞춰 "그 창이 완성되는 시점에 무슨 일이 있었는가"를 일관되게
묻기 위함. +0.5%는 임의값이지만 근거가 있다: IS 표본 일부(3종목·일)로 60초
수익률 분포를 미리 찍어보니 97번째 백분위수가 0.50%였다(0.3%=91번째,
0.76%=99번째) - 상위 ~3%짜리 "의미있는 단기 튐"에 해당하는 반올림값을 골랐다.

## 그리드 — 왜 10초 단위인가
10~60초짜리 반응을 보려면 1분 그리드로는 못 잡는다(같은 1분 안에서 다
일어날 수 있음). **10초 그리드**(가장 짧은 관측창과 같은 해상도)로 세션
전체를 훑는다 - T0_GRID = 0,10,20,...,라벨호라이즌 전까지.

## 피처 — 두 축
1. **관측창 축**(10/20/30/60초, 4개): 초당 체결횟수(`tick_speed`), 매수-매도
   대금격차(`buy_sell_gap`, (매수대금-매도대금)/전체대금 - 종목간 비교 위해
   정규화), 체결강도 변화율(`intensity_change`, 매수체결량/매도체결량x100의
   직전 동일길이 창 대비 변화율 - `t0_forward_return.py`와 같은 정의).
2. **체결금액 증가율 축**(1/3/5/10초, 별도 4개, `value_surge`): 그 순간까지의
   확장평균 대비 창 거래대금 배율 - 지시문 "1/3/5/10초 체결금액 증가율"을
   관측창 축과 독립된 더 미세한 시간축으로 해석했다(그렇게 읽지 않으면
   10/20/30/60초 축과 정의가 겹친다) - 해석 판단이라 명시해 둔다.
전부 `window_sum`/누적합 기반 O(1), 그리드 지점마다 틱 재스캔 없음.

## 평가
라벨이 이진(상승/비상승)이라 `shooting_precursor_onset.py`와 같은 방식으로
AUC를 쓴다(IC/회귀는 다음 큐 항목들 쪽 - MFE/MAE, T0 회귀). IS(첫12일)/
OOS(뒤6일) 분리, 안 되는 피처도 표에 남긴다.

## 비용 · 표본 겹침
positive(상승 온셋) 표본의 실현 60초 수익률에 왕복비용(`round_trip_cost_pct`,
1틱 이상 슬리피지 포함)을 그대로 적용해 총수익/순수익을 같이 보고한다.
유의성은 일자클러스터 SE(`_day_clustered_mean_se`)로 낸다.

## 데이터 한계
호가잔량 없음(time/cur_prc/trde_qty/pred_pre_sig 넷뿐) - 필요한 항목은
없음. 117종목 18일 전부 사용.

실행: python -m backtesting.precursor_10_60s
"""
import glob
import os
import time

import numpy as np
import pandas as pd

from _precursor_fastpath import N, SESSION_START, label_shoot, to_grid, window_sum
from backtesting.shooting_precursor import TEST_DATES, TRAIN_DATES, _shift_window_sum, _tick_rule_direction
from backtesting.shooting_precursor_onset import cluster_bounds
from backtesting.t0_forward_return import _expanding_period_avg, round_trip_cost_pct

GRID_STEP = 10  # 초
LABEL_HORIZON = 60  # 초 - label_shoot 창
RISE_THRESH = 0.005  # 60초 내 +0.5% (근거: docstring 참고, IS 표본 97백분위수 반올림)
GAP_STEPS = LABEL_HORIZON // GRID_STEP  # 6그리드=60초 - 클러스터 병합/사후제외 폭

FEATURE_WINDOWS = {"w10": 10, "w20": 20, "w30": 30, "w60": 60}  # 초 - 관측창 축
VALUE_SURGE_WINDOWS = {"vs1": 1, "vs3": 3, "vs5": 5, "vs10": 10}  # 초 - 체결금액 증가율 축

T0_GRID = np.arange(0, N - LABEL_HORIZON, GRID_STEP)

FEATURE_COLUMNS = (
    [f"{k}_tick_speed" for k in FEATURE_WINDOWS]
    + [f"{k}_buy_sell_gap" for k in FEATURE_WINDOWS]
    + [f"{k}_intensity_change" for k in FEATURE_WINDOWS]
    + [f"{k}_value_surge" for k in VALUE_SURGE_WINDOWS]
)


def classify_stock_day(label_grid: np.ndarray, gap: int, post_exclude: int) -> np.ndarray:
    """label_grid(그리드 인덱스 순 bool) -> "positive"/"excluded"/"negative".
    병합 알고리즘은 `shooting_precursor_onset.cluster_bounds`를 그대로 쓰고,
    여기서는 gap/post_exclude를 이 스터디 값(6그리드=60초)으로 파라미터화만
    한다 - 로직 중복 없음."""
    n = len(label_grid)
    category = np.full(n, "negative", dtype=object)
    true_idx = np.flatnonzero(label_grid)
    for start, end in cluster_bounds(true_idx, gap):
        category[start] = "positive"
        if end > start:
            category[start + 1:end + 1] = "excluded"
        post_end = min(end + post_exclude, n - 1)
        category[end + 1:post_end + 1] = "excluded"
    return category


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

    lab_full = label_shoot(px, horizon=LABEL_HORIZON, thresh=RISE_THRESH)
    label_grid = lab_full[T0_GRID]
    category = classify_stock_day(label_grid, GAP_STEPS, GAP_STEPS)

    # label_shoot과 같은 계산(역순 rolling max)을 한 번 더 해서 실제 실현
    # 수익률(문턱 통과 여부가 아니라 그 크기)까지 같이 낸다 - onset 표본의
    # 진짜 수익 분포를 보려면 필요, label_shoot 내부 로직 재사용.
    fut_max = pd.Series(px[::-1]).rolling(LABEL_HORIZON, min_periods=1).max().to_numpy()[::-1]
    realized_ret = fut_max / px - 1

    cols = {
        "code": code, "date": date_str, "t_sec": T0_GRID + SESSION_START,
        "price_t": px[T0_GRID], "category": category,
        "realized_ret_60s": realized_ret[T0_GRID],
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

        intensity = win_buy / win_sell * 100
        intensity[win_sell == 0] = np.nan
        prev_intensity = _shift_window_sum(intensity, w)
        intensity_change = intensity / prev_intensity - 1
        intensity_change[(prev_intensity == 0) | np.isnan(prev_intensity)] = np.nan

        cols[f"{key}_tick_speed"] = tick_speed[T0_GRID]
        cols[f"{key}_buy_sell_gap"] = buy_sell_gap[T0_GRID]
        cols[f"{key}_intensity_change"] = intensity_change[T0_GRID]

    for key, w in VALUE_SURGE_WINDOWS.items():
        win_value = window_sum(value_per_sec, w)
        avg_value = _expanding_period_avg(cs_value, T0_GRID, w)
        value_surge = win_value / avg_value
        value_surge[avg_value == 0] = np.nan  # 그 시점까지 거래대금이 0이면 배율 무정의(inf 방지)
        cols[f"{key}_value_surge"] = value_surge[T0_GRID]

    return pd.DataFrame(cols)


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
    from sklearn.metrics import roc_auc_score
    kept = df[df["category"] != "excluded"]
    y = (kept["category"] == "positive").to_numpy().astype(int)
    rows = []
    for col in FEATURE_COLUMNS:
        x = kept[col]
        mask = x.notna()
        n = int(mask.sum())
        if n < 100 or y[mask].sum() == 0 or y[mask].sum() == n:
            rows.append({"indicator": col, "n": n, "auc": np.nan, "auc_abs": np.nan, "note": "표본부족/단일클래스"})
            continue
        auc = roc_auc_score(y[mask], x[mask])
        rows.append({"indicator": col, "n": n, "auc": auc, "auc_abs": max(auc, 1 - auc), "note": ""})
    return pd.DataFrame(rows).sort_values("auc_abs", ascending=False, na_position="last")


def onset_return_stats(df: pd.DataFrame) -> dict:
    """positive(onset) 표본의 실제 실현 60초 수익률(`realized_ret_60s`,
    라벨 정의상 전부 >=RISE_THRESH) + 비용 반영 순수익. 일자클러스터 SE로
    유의성 - 60초짜리 "완성된" 상승이라도 왕복비용(~0.5%대)을 넘는지가
    관심사(임계값 자체가 0.5%라 순수익이 딱 0 근처일 걸로 예상됨)."""
    from backtesting.t0_forward_return import _day_clustered_mean_se
    pos = df[df["category"] == "positive"].copy()
    if pos.empty:
        return {"n": 0}
    pos["net_ret"] = pos["realized_ret_60s"] - round_trip_cost_pct(pos["price_t"].to_numpy())
    gross_mean, gross_se, n, n_days = _day_clustered_mean_se(pos, "realized_ret_60s")
    net_mean, net_se, _, _ = _day_clustered_mean_se(pos, "net_ret")
    return {"n": n, "n_days": n_days, "gross_mean_pct": gross_mean * 100, "gross_se_pct": gross_se * 100,
            "net_mean_pct": net_mean * 100, "net_se_pct": net_se * 100,
            "median_gross_pct": pos["realized_ret_60s"].median() * 100}


def main():
    t0 = time.time()
    print("스캔 시작 (tick_al 전체, 10~60초 전조 피처+onset 격리)...", flush=True)
    dataset = scan_all()
    dt = time.time() - t0
    os.makedirs("results", exist_ok=True)
    dataset.to_parquet("results/precursor_10_60s_dataset.parquet", index=False)

    counts = dataset["category"].value_counts()
    print(f"스캔 {dt:.1f}초 | 표본 {len(dataset):,}행 | {counts.to_dict()}", flush=True)

    train = dataset[dataset["date"].isin(TRAIN_DATES)].reset_index(drop=True)
    test = dataset[dataset["date"].isin(TEST_DATES)].reset_index(drop=True)

    train_auc = indicator_auc_table(train)
    test_auc = indicator_auc_table(test)
    train_auc.to_csv("results/precursor_10_60s_auc_train.csv", index=False)
    test_auc.to_csv("results/precursor_10_60s_auc_test.csv", index=False)
    print("=== IS AUC ===")
    print(train_auc.to_string(index=False))
    print("=== OOS AUC ===")
    print(test_auc.to_string(index=False))

    print("=== onset(positive) 표본 수익 하한 vs 비용 ===")
    print("IS:", onset_return_stats(train))
    print("OOS:", onset_return_stats(test))

    return dataset, train_auc, test_auc


if __name__ == "__main__":
    main()
