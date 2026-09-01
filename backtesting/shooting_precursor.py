"""슈팅(급등) 직전 전조 지표 탐색 — lead 지시(2026-08-31), 통합(_AL) 체결데이터.

## 고속 경로 재사용 (lead 제공 `_precursor_fastpath.py`)
최초 구현(이 파일의 이전 버전)은 그리드 t마다 틱을 다시 훑어 2017파일 스캔에
3분 5초가 걸렸다. lead가 실측·제공한 `_precursor_fastpath.py`는 1초 격자로
한 번 접고(`np.bincount`) 누적합(`window_sum`)으로 임의 창 합계를 O(1)에
내는 방식으로 **24.4초**에 끝낸다(직접 재실행해 확인: `2017파일 24.4초`,
`_precursor_fastpath.py` 하단 참고). 그 4개 함수(`to_grid`/`label_shoot`/
`window_sum`/`cluster`)를 그대로 가져다 쓴다.

## 검증(지시 — "그대로 믿지 말고 검증해라") — 버그 발견·수정
`to_grid`를 그대로 쓰기 전에 000150/2026-08-04 한 파일로 직접 대조했다.
원본 `to_grid`는 `d`를 뒤집지 않고 바로 정렬해서, 같은 초 안에 여러 체결이
있으면(원본이 역시간순이므로) stable sort가 tie 순서를 역시간순 그대로
보존해버려 "그 초의 마지막 체결가"가 실제로는 종종 그 초의 *첫* 체결가가
됐다 — 같은 초에 2건 이상 체결된 4,192초 중 1,914초(45.7%)가 실제 마지막
체결가와 달랐다(직접 groupby 대조). **`_precursor_fastpath.py`를 고쳤다**
(`d.iloc[::-1]`로 먼저 시간순 정렬 후 argsort) — 같은 파일로 재검증하니
4,192초 전부 일치(0건 불일치)로 바뀌었다. `vol`/`cnt`(bincount 합산)는 순서
무관이라 애초에 안 틀렸다 — 영향은 `px`(따라서 라벨·드리프트·변동성·
고가위치)에만 있었다. 전체 스캔 결과도 수정 전후로 달라졌다: 원본 98,092,069행
→ 정규장 88,600,905행(시간외 9.7%)은 필터 로직이라 안 바뀌었지만, **클러스터
슈팅 이벤트가 2,736건(수정 전) → 2,797건(수정 후)으로 바뀌었다** — 버그가
실제로 라벨에 영향을 줬다는 뜻이라 무시하지 않고 수정된 버전으로 아래 전부를
돌린다.

## pred_pre_sig 실증 (지시: 추측 금지, 실측)
`pred_pre_sig`는 **틱 간 상승/하락(직전 체결가 대비)이 아니라 "전일 종가 대비"
부호다.** 000150 2026-08-04(전일종가 1,238,000, data/stocks/daily/000150.csv
직접확인) 틱을 시간순 정렬해 보면 cur_prc가 1,238,000을 넘나들 때마다 정확히
pred_pre_sig가 2(위)/3(=)/5(아래)로 바뀐다(하루 85회 전환, 매 전환이 전일종가
교차와 100% 일치 - 직접 대조). 전체 분포도 5(3300만)>2(6350만)로 장중 대부분
시간이 한쪽에 고정돼 있다는 사실과 일치한다(틱마다 바뀌는 매수/매도 판정에는
못 쓴다는 뜻). **"매수우위"는 pred_pre_sig 대신 표준 tick rule(직전 체결가
대비 상승=매수주도/하락=매도주도, 보합은 직전 판정 계승)로 cur_prc 시퀀스에서
직접 계산한다** — 이것도 그 틱까지만 보는 인과적 계산이라 look-ahead가 아니다.

## 라벨(슈팅) / 세션 경계
`_precursor_fastpath.label_shoot`: 1초 격자에서 max(px[t..t+600초])/px[t]-1
>= 0.03. 세션 경계는 fastpath 기준 09:00:00<=t<=15:30:00(15:30:00 포함) —
기존 사전등록(`backtest-agent_20260831-115500`, 15:30:00 미포함)과 다르지만
**전체 9800만 틱 중 정확히 15:30:00인 틱이 0건**이라(직접 duckdb 집계 확인)
실질적 차이는 없다.

## 전조 피처 — 1분 그리드(09:00~15:20)에서 [t-W,t) 두 창(3분/10분)
9개 전부 `window_sum`(누적합, O(1))으로 전 구간을 한 번에 계산한 뒤 그리드
위치만 뽑는다 - 그리드 지점마다 틱을 다시 훑는 루프는 하나도 없다(lead 지적
그대로 반영). 대량체결비중/변동성은 원래 퍼센타일·표준편차라 누적합으로 바로
안 풀리는데, **그리드 지점에서 틱을 다시 스캔하는 대신 정의를 바꿔서** O(1)로
만들었다 — 정밀도를 조금 내주고 속도를 그대로 지키는 절충이라 근거를 남긴다:
- **대량체결비중**: "이 창 자체의 90퍼센타일"(원래 지시안) 대신 "그 순간까지의
  확장평균 체결크기의 3배 이상"으로 재정의(LARGE_TRADE_MULT=3.0, 임의값 -
  ponytail: 필요하면 나중에 튜닝). 틱 하나하나를 그 틱 시점까지의 인과적
  평균과 비교하는 O(n_tick) 1회 계산이라 미래 정보가 안 섞이고, 결과를
  bincount+window_sum으로 O(1) 집계할 수 있다.
- **변동성**: 틱 수익률 표준편차 대신 **초단위 수익률**(px 기반, 거래 없는
  초는 수익률 0)의 표준편차 - var=E[r²]-E[r]²를 sum(r)/sum(r²) 누적합
  두 개로 O(1)에 낸다. 거래가 뜸한 초를 0으로 채우는 만큼 실제 체결
  변동성보다 다소 낮게 나올 수 있다(체결밀도가 이미 그 정보를 따로 잡고
  있어 완전히 새는 정보는 아니다) - 결과 해석 시 명시.

## 산출
scan_all()이 IS(앞 12거래일)/OOS(뒤 6거래일)로 나눠 지표별 AUC·상위 1%/5%
정밀도를 낸다. 실행: python -m backtesting.shooting_precursor
"""
import glob
import os
import time

import numpy as np
import pandas as pd

from _precursor_fastpath import (
    N,
    SESSION_END,
    SESSION_START,
    cluster,
    label_shoot,
    to_grid,
    window_sum,
)

GRID_STEP = 60  # 1분
LABEL_HORIZON = 600  # 10분
FEATURE_WINDOWS = {"w3": 180, "w10": 600}
LARGE_TRADE_MULT = 3.0  # 그 순간까지의 평균 체결크기의 몇 배부터 "대량"으로 볼지

def large_trade_flag(tick_qty: np.ndarray, mult: float = LARGE_TRADE_MULT) -> np.ndarray:
    """"그 순간까지의 평균 체결크기"의 mult배 이상인 체결을 "대량"으로 본다
    (과거 정보만 쓰는 인과적 확장평균 - window_sum으로 O(1) 집계하려면
    percentile 대신 이 근사가 필요, `precursor_lead_lag.py`/큐(4)에서도
    같은 정의를 재사용한다 - 중복 구현 금지)."""
    tick_idx = np.arange(1, len(tick_qty) + 1)
    cs_tick_qty = np.cumsum(tick_qty)
    avg_before = (np.concatenate(([np.nan], cs_tick_qty[:-1] / tick_idx[:-1]))
                  if len(tick_qty) > 1 else np.array([np.nan]))
    return np.nan_to_num(tick_qty >= mult * avg_before, nan=0.0).astype(bool)


TRAIN_DATES = ["2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10",
               "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14", "2026-08-18",
               "2026-08-19", "2026-08-20"]  # 앞 12거래일 = IS
TEST_DATES = ["2026-08-21", "2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27",
              "2026-08-28"]  # 뒤 6거래일 = OOS

GRID = np.arange(0, N - LABEL_HORIZON, GRID_STEP)  # 09:00:00~15:20:00, 1초격자 기준 오프셋


def _tick_rule_direction(price: np.ndarray) -> np.ndarray:
    """표준 tick rule: 상승체결=+1(매수주도)/하락체결=-1(매도주도)/보합은 직전
    판정 계승(0-tick rule). 최초 틱은 방향정보가 없어 0."""
    diff = np.diff(price, prepend=price[0])
    direction = np.sign(diff)
    direction[0] = 0
    s = pd.Series(direction).replace(0, np.nan).ffill().fillna(0)
    return s.to_numpy(dtype=np.int8)


def _shift_window_sum(full_window_sum: np.ndarray, w: int) -> np.ndarray:
    """window_sum(series,w)[t] = sum over [t-w,t). 그 창을 한 칸 더 과거로 민 것
    = sum over [t-2w,t-w) = full_window_sum[t-w]. 밀도 증가율(직전 동일길이
    구간 대비) 계산에 쓴다."""
    out = np.full(N, np.nan)
    out[w:] = full_window_sum[:N - w]
    return out


def compute_stock_day(path: str, code: str, date_str: str):
    g = to_grid(path)
    if g is None:
        return None, g

    px, vol, cnt = g["px"], g["vol"], g["cnt"]
    tick_sec, tick_prc, tick_qty = g["tick_sec"], g["tick_prc"], g["tick_qty"]

    direction = _tick_rule_direction(tick_prc)
    buy_qty_per_sec = np.bincount(tick_sec, weights=np.where(direction > 0, tick_qty, 0.0), minlength=N)
    cum_high = np.maximum.accumulate(px)
    day_high_before = np.concatenate(([-np.inf], cum_high[:-1]))
    new_high_flag_per_sec = (px > day_high_before).astype(float)

    large_flag = large_trade_flag(tick_qty)
    large_qty_per_sec = np.bincount(tick_sec, weights=np.where(large_flag, tick_qty, 0.0), minlength=N)

    # 변동성: 틱마다 되짚는 대신 초단위 수익률(px 기반, 거래 없는 초는 0)의
    # 분산을 누적합(sum, sum of squares)만으로 O(1)에 낸다 - var=E[r^2]-E[r]^2.
    r_sec = np.zeros(N)
    r_sec[1:] = px[1:] / px[:-1] - 1
    r_sec_sq = r_sec ** 2

    lab_full = label_shoot(px, horizon=LABEL_HORIZON, thresh=0.03)
    events = len(cluster(lab_full, gap=LABEL_HORIZON))

    cs_vol = np.concatenate(([0.0], np.cumsum(vol)))

    cols = {
        "code": code, "date": date_str, "t_sec": GRID + SESSION_START,
        "price_t": px[GRID], "label": lab_full[GRID],
        "high_position": px[GRID] / cum_high[GRID] - 1,
    }

    np.seterr(divide="ignore", invalid="ignore")  # 0/0, x/0 은 의도된 NaN - 경고 억제
    for key, w in FEATURE_WINDOWS.items():
        win_vol = window_sum(vol, w)
        win_buy = window_sum(buy_qty_per_sec, w)
        win_cnt = window_sum(cnt, w)
        win_new_high = window_sum(new_high_flag_per_sec, w)
        prev_cnt = _shift_window_sum(win_cnt, w)

        # 거래량비 분모: cs_vol[k] = vol[0:k].sum() (창 시작 전까지의 누적거래량,
        # k=t-w) / 그때까지 지난 동일길이(w) 구간 수(인과적 - 미래 정보 없음).
        elapsed_periods = np.full(N, np.nan)
        hist_vol = np.full(N, np.nan)
        k = GRID - w
        ok = k >= 0
        elapsed_periods[GRID[ok]] = k[ok] / w
        hist_vol[GRID[ok]] = cs_vol[k[ok]]
        avg_period_vol = hist_vol / elapsed_periods
        vol_ratio = win_vol / avg_period_vol
        vol_ratio[elapsed_periods < 1] = np.nan

        buy_ratio = win_buy / win_vol
        buy_ratio[win_vol == 0] = np.nan
        tick_density = win_cnt / w
        density_growth = win_cnt / prev_cnt
        density_growth[prev_cnt == 0] = np.nan

        drift = np.full(N, np.nan)
        start_idx = np.clip(GRID - w, 0, N - 1)
        end_idx = np.clip(GRID - 1, 0, N - 1)
        valid_drift = GRID - w >= 0
        drift[GRID[valid_drift]] = px[end_idx[valid_drift]] / px[start_idx[valid_drift]] - 1

        win_large = window_sum(large_qty_per_sec, w)
        large_share = win_large / win_vol
        large_share[win_vol == 0] = np.nan

        win_r = window_sum(r_sec, w)
        win_r_sq = window_sum(r_sec_sq, w)
        mean_r = win_r / w
        volatility = np.sqrt(np.clip(win_r_sq / w - mean_r ** 2, 0, None))

        cols[f"{key}_vol_ratio"] = vol_ratio[GRID]
        cols[f"{key}_buy_ratio"] = buy_ratio[GRID]
        cols[f"{key}_tick_density"] = tick_density[GRID]
        cols[f"{key}_density_growth"] = density_growth[GRID]
        cols[f"{key}_drift"] = drift[GRID]
        cols[f"{key}_new_high_count"] = win_new_high[GRID]
        cols[f"{key}_large_trade_share"] = large_share[GRID]
        cols[f"{key}_volatility"] = volatility[GRID]

    df = pd.DataFrame(cols)
    df = df[df["price_t"].notna() & (df["price_t"] > 0)].reset_index(drop=True)
    return df, {"raw_rows": g["raw_rows"], "kept_rows": g["kept_rows"], "events": events}


def scan_all(tick_dir: str = "data/stocks/tick_al") -> tuple[pd.DataFrame, dict]:
    files = sorted(glob.glob(os.path.join(tick_dir, "*", "*.parquet")))
    frames = []
    total_raw = total_kept = total_events = 0
    for path in files:
        code = os.path.basename(os.path.dirname(path))
        date_str = os.path.splitext(os.path.basename(path))[0]
        frame, meta = compute_stock_day(path, code, date_str)
        if frame is not None and not frame.empty:
            frames.append(frame)
        if meta is not None:
            total_raw += meta["raw_rows"]
            total_kept += meta["kept_rows"]
            total_events += meta["events"]
    dataset = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    summary = {"n_files": len(files), "raw_rows": total_raw, "kept_rows": total_kept,
               "cluster_events": total_events}
    return dataset, summary


FEATURE_COLUMNS = ["high_position"] + [
    f"{key}_{name}" for key in FEATURE_WINDOWS
    for name in ("vol_ratio", "buy_ratio", "tick_density", "density_growth",
                  "large_trade_share", "drift", "volatility", "new_high_count")
]


def indicator_auc_table(df: pd.DataFrame) -> pd.DataFrame:
    from sklearn.metrics import roc_auc_score
    rows = []
    y = df["label"].to_numpy().astype(int)
    for col in FEATURE_COLUMNS:
        x = df[col]
        mask = x.notna()
        n = int(mask.sum())
        if n < 100 or y[mask].sum() == 0 or y[mask].sum() == n:
            rows.append({"indicator": col, "n": n, "auc": np.nan, "auc_abs": np.nan, "note": "표본부족/단일클래스"})
            continue
        auc = roc_auc_score(y[mask], x[mask])
        rows.append({"indicator": col, "n": n, "auc": auc, "auc_abs": max(auc, 1 - auc), "note": ""})
    result = pd.DataFrame(rows).sort_values("auc_abs", ascending=False, na_position="last")
    result.attrs["base_rate"] = float(y.mean())
    return result


def precision_at_top(df: pd.DataFrame, col: str, pct: float) -> tuple[float, int]:
    """상위 pct%(예: 0.01=1%) 구간의 정밀도(슈팅 비율)와 그 구간 표본수. 지표값이
    label과 음의 상관이면(값이 작을수록 슈팅) 하위 pct%를 "상위 판정 구간"으로 본다."""
    sub = df[[col, "label"]].dropna()
    if sub.empty:
        return float("nan"), 0
    n_top = max(1, int(len(sub) * pct))
    negative = sub[col].corr(sub["label"].astype(int)) < 0
    ranked = sub.sort_values(col, ascending=negative).head(n_top)
    return float(ranked["label"].astype(int).mean()), n_top


def main():
    t0 = time.time()
    print("스캔 시작 (tick_al 전체, fastpath 재사용 + 전조지표)...", flush=True)
    dataset, summary = scan_all()
    dt = time.time() - t0
    os.makedirs("results", exist_ok=True)
    dataset.to_parquet("results/shooting_precursor_dataset.parquet", index=False)

    print(f"{summary['n_files']}파일 {dt:.1f}초 | 원본 {summary['raw_rows']:,}행 -> "
          f"정규장 {summary['kept_rows']:,}행 (시간외 {100*(1-summary['kept_rows']/summary['raw_rows']):.1f}%) "
          f"| 클러스터 슈팅 이벤트 {summary['cluster_events']:,}건", flush=True)
    print(f"1분그리드 표본 {len(dataset):,}건, 슈팅(label=1) {int(dataset['label'].sum()):,}건 "
          f"({dataset['label'].mean()*100:.3f}%, 기저율)", flush=True)

    train = dataset[dataset["date"].isin(TRAIN_DATES)].reset_index(drop=True)
    test = dataset[dataset["date"].isin(TEST_DATES)].reset_index(drop=True)

    train_auc = indicator_auc_table(train)
    test_auc = indicator_auc_table(test)
    print("=== IS(앞12일) 지표별 AUC ===")
    print(train_auc.to_string(index=False))
    print("=== OOS(뒤6일) 지표별 AUC ===")
    print(test_auc.to_string(index=False))

    train_auc.to_csv("results/shooting_precursor_auc_train.csv", index=False)
    test_auc.to_csv("results/shooting_precursor_auc_test.csv", index=False)

    for pct in (0.01, 0.05):
        print(f"--- 상위 {pct*100:.0f}% 정밀도 (IS 상위지표 기준) ---")
        for col in train_auc.head(5)["indicator"]:
            p_train, n_train = precision_at_top(train, col, pct)
            p_test, n_test = precision_at_top(test, col, pct)
            print(f"{col}: IS n={n_train} precision={p_train:.4f} | OOS n={n_test} precision={p_test:.4f}")

    return dataset, summary, train_auc, test_auc


if __name__ == "__main__":
    main()
