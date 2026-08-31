"""보유시간 축 확장 — 사용자 직접지시(2026-08-31), `t0_forward_return.py`의
결론("신호는 있는데 크기가 왕복비용보다 작다")을 받아 **비용은 보유시간과
무관하게 왕복 한 번**이라는 점을 이용해 보유를 늘려서 넘을 수 있는지 본다.

## 재사용 (T0/피처/비용모델은 그대로, 라벨만 바꾼다)
`t0_forward_return.py`의 T0_GRID·6피처x3창·비용모델(`round_trip_cost_pct`)·
IS/OOS 분리·일자클러스터SE를 전부 그대로 가져온다. 저장된
`results/t0_forward_return_dataset.parquet`(피처+price_t, 재계산 안 함)에
이 파일에서 새로 낸 라벨만 조인한다 - 피처를 다시 스캔하지 않는다(스캔은
새 라벨 4개(장중 30/60/120분+세션마지막체결)를 위해 `to_grid`만 다시
부른다, O(1)).

## 라벨
- 장중(틱, 그대로 세션 안): `ret_30m/60m/120m/session_last`. **[정정
  2026-08-31, lead 판단]** `ret_session_last`는 애초 `ret_eod`(당일종가)로
  불렀으나 이름이 틀렸다 — `backtest-agent_20260831-195143_session_boundary_
  and_eod_staleness.md`에서 밝혔듯 정규장 정각(15:30:00)엔 원본에 틱이 없고
  세션필터(`SESSION_END<=15:30:00`)가 진짜 종가단일가(15:30:01+)를 전부
  버려서, 이 값은 실제로는 **정규장 마지막 체결가(대개 15:19~15:20대)**다
  - 당일종가가 아니다. 진짜 종가가 필요하면 아래 일 단위 라벨(`ret_1d`)처럼
  `data/stocks/daily/<code>.csv`의 `close`를 쓴다(재구성 안 함). 미래창이
  세션을 넘으면 그 라벨만 NaN(행은 살린다) - 30/60/120분은 오후 T0에서
  자주 NaN이 난다.
- 일 단위(일봉 종가청산): `ret_1d/3d/5d/10d`. T0 체결가로 진입, **그 종목의
  일봉 거래일 캘린더 기준** k거래일 뒤 종가로 청산 - 달력일이 아니라
  거래일이라 주말/휴장을 자동으로 건너뛴다.

## 데이터 정합 검증 — "여기서 틀리면 전부 무의미해진다"
틱 마지막 체결가(그 (code,date) 그리드의 최댓값 t_sec행 price_t)와 같은 날
일봉 종가를 전부 대조했다(2,017개 (code,date) 쌍). 비율 분포: 중앙값 1.0000,
평균 0.9997, 표준편차 0.0077 - 대체로 일치. **2% 넘게 벗어난 건 4행/3종목**:
- **196170 2026-08-04: 비율 1.309(+30.9%)** - 기존에 이미 알려진 문제
  (수정주가 미반영, `data-agent` 확인·이전 리포트 기록)와 정확히 일치한다.
  **이 (code,date) 한 쌍만 제외**한다(196170의 다른 날짜는 비율 정상이라
  종목 전체를 빼지 않는다 - 문제가 그 날짜에 국한된 걸로 이미 확인돼 있다).
- 298040 2026-08-13(-2.15%), 950260 2026-08-18(-3.9%)/08-19(+2.5%) - 소형주
  저유동성 종목의 마지막 체결가와 동시호가 종가 차이로 보인다(부호가
  왔다갔다 해서 분할/병합 특유의 일방향 점프 패턴이 아니다) - **제외하지
  않았다**, 근거와 함께 여기 남긴다.
- 정합 확인 코드는 `verify_price_consistency()` - 재실행 가능.

미래 구간(라벨 계산용 미래 종가)까지는 틱으로 대조할 수 없다. 처음엔
|수익률|>50%를 분할/병합 잔여로 보고 자동 제외했으나, 스팟체크(001210:
2026-08-10~08-31 3,140→12,480원, 실제 일봉 고가/저가로 확인되는 진짜
모멘텀 랠리 - 데이터 오류 아님)에서 **이 유니버스엔 실제로 며칠 새 3~4배
가는 소형 모멘텀 종목이 섞여 있어 자동 제외가 진짜 신호를 지운다는 걸
확인했다** - 그래서 **자동 제외를 접었다.** 대신 `extreme_{k}` 플래그
컬럼만 남기고, 평균 옆에 항상 중앙값을 같이 보고해 왜곡 여부를 드러낸다
(`condition_horizon_report`의 `*_median_pct`/`n_extreme_flagged`).

## 데이터 한계 — "오늘"이 2026-08-31이라 미래 거래일이 짧다
일봉 데이터가 2026-08-31까지만 있다(그게 "오늘"이라 그 이후가 없다). 틱은
2026-08-04~08-28이 마지막이라, **08-28에서 미래로 쓸 수 있는 거래일이
08-31 단 하루뿐이다.** OOS(뒤6일=08-21~08-28) 쪽 ret_10d/ret_5d는 커버리지가
극히 얇다 - 라벨별 유효 표본수·유효 일수를 전부 표로 남긴다(3번 참고).

## 갭/장중 분해 (로그수익률로 정확히 가법 분해)
`log(exit_close/T0가) = 갭합(거래일 전환 시 종가->익일시가, k개) + 나머지
(T0->당일종가 + 그 뒤 각 거래일의 시가->종가)`. 갭합은 (code,origin_date,k)
당 한 번만 계산(그날 어느 T0든 동일) - `daily_gap_log_sum()`.

## 동시보유 근사
"실전이면 몇 개나 동시에 들고 있게 되는가"는 종목별로 관측된 18거래일 안에서
신호 발생건수의 k거래일 롤링합(평균/최대)으로 근사한다 - 자본 제약을 완전히
무시한 숫자라는 걸 리포트에서 명시한다.

## 산출
`main()`이 IS(첫12일)/OOS(뒤6일)로 나눠 라벨별 IC(price_speed 부호 뒤집히는
지점 포함)와, 3번 조건(price_speed 세창 동시 극단 10%, `t0_forward_return.py`와
같은 문턱)의 보유시간별 총/순수익·유효표본·갭분해·동시보유를 낸다.
실행: python -m backtesting.holding_horizon
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
    round_trip_cost_pct,
)

DAILY_DIR = "data/stocks/daily"
INTRADAY_LONG_HORIZONS = {"30m": 1_800, "60m": 3_600, "120m": 7_200}  # 초
DAILY_HORIZONS_TRADING_DAYS = {"1d": 1, "3d": 3, "5d": 5, "10d": 10}
EXCLUDED_PAIRS = {("196170", "2026-08-04")}  # 검증(위 문서) - 수정주가 미반영
EXTREME_DAILY_RET_THRESHOLD = 0.50  # 이 이상은 분할/병합 잔여 의심 - 별도 집계 후 제외


def verify_price_consistency(dataset: pd.DataFrame, daily_dir: str = DAILY_DIR,
                              tolerance: float = 0.02) -> pd.DataFrame:
    """(code,date)별 틱 마지막 체결가 vs 일봉 종가 비율. tolerance 밖이면 flag=True."""
    last = dataset.loc[dataset.groupby(["code", "date"])["t_sec"].idxmax()][["code", "date", "price_t"]]
    rows = []
    for code, g in last.groupby("code"):
        path = os.path.join(daily_dir, f"{code}.csv")
        if not os.path.exists(path):
            for _, r in g.iterrows():
                rows.append({"code": code, "date": r["date"], "tick_last": r["price_t"], "daily_close": np.nan, "ratio": np.nan})
            continue
        daily_close = pd.read_csv(path).set_index("date")["close"]
        for _, r in g.iterrows():
            dc = daily_close.get(r["date"], np.nan)
            ratio = r["price_t"] / dc if pd.notna(dc) and dc != 0 else np.nan
            rows.append({"code": code, "date": r["date"], "tick_last": r["price_t"], "daily_close": dc, "ratio": ratio})
    result = pd.DataFrame(rows)
    result["flagged"] = (result["ratio"] < 1 - tolerance) | (result["ratio"] > 1 + tolerance)
    return result


def _load_daily_calendar(code: str, daily_dir: str = DAILY_DIR) -> pd.DataFrame | None:
    path = os.path.join(daily_dir, f"{code}.csv")
    if not os.path.exists(path):
        return None
    return pd.read_csv(path).reset_index(drop=True)


def daily_labels_and_gap_decomposition(code: str, origin_date: str, daily_dir: str = DAILY_DIR) -> dict:
    """origin_date 기준 k거래일 뒤 종가(라벨용) + 갭 로그수익률 합(분해용).
    origin_date가 캘린더에 없거나 k거래일 뒤가 데이터 범위를 벗어나면 그 k는 NaN."""
    cal = _load_daily_calendar(code, daily_dir)
    out = {f"exit_close_{k}": np.nan for k in DAILY_HORIZONS_TRADING_DAYS}
    out.update({f"gap_log_{k}": np.nan for k in DAILY_HORIZONS_TRADING_DAYS})
    if cal is None or origin_date not in set(cal["date"]):
        return out
    idx0 = cal.index[cal["date"] == origin_date][0]
    for name, k in DAILY_HORIZONS_TRADING_DAYS.items():
        idx_exit = idx0 + k
        if idx_exit >= len(cal):
            continue
        out[f"exit_close_{name}"] = cal.loc[idx_exit, "close"]
        # 갭 로그수익률 합: day0->day1, day1->day2, ..., day(k-1)->day k 전환마다
        # log(그날 시가 / 전날 종가)
        gap_sum = 0.0
        for i in range(idx0 + 1, idx_exit + 1):
            gap_sum += np.log(cal.loc[i, "open"] / cal.loc[i - 1, "close"])
        out[f"gap_log_{name}"] = gap_sum
    return out


def compute_intraday_long_labels(path: str, code: str, date_str: str) -> pd.DataFrame | None:
    g = to_grid(path)
    if g is None:
        return None
    px = g["px"]
    cols = {"code": code, "date": date_str, "t_sec": T0_GRID + SESSION_START}
    for name, k in INTRADAY_LONG_HORIZONS.items():
        future_idx = T0_GRID + k
        in_range = future_idx <= N - 1
        ret = np.full(len(T0_GRID), np.nan)
        ret[in_range] = px[future_idx[in_range]] / px[T0_GRID[in_range]] - 1
        cols[f"ret_{name}"] = ret
    # 이름 주의: 진짜 당일종가가 아니다 - 위 docstring "[정정]" 참고.
    cols["ret_session_last"] = px[N - 1] / px[T0_GRID] - 1
    return pd.DataFrame(cols)


def scan_intraday_long_labels(tick_dir: str = "data/stocks/tick_al") -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(tick_dir, "*", "*.parquet")))
    frames = []
    for path in files:
        code = os.path.basename(os.path.dirname(path))
        date_str = os.path.splitext(os.path.basename(path))[0]
        frame = compute_intraday_long_labels(path, code, date_str)
        if frame is not None and not frame.empty:
            frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build_dataset() -> pd.DataFrame:
    """t0_forward_return의 저장된 피처+price_t에 새 라벨(장중 장기+일단위)을
    조인한다. EXCLUDED_PAIRS는 여기서 제거한다(가격정합 검증 결과)."""
    base = pd.read_parquet("results/t0_forward_return_dataset.parquet")
    base = base[~base.apply(lambda r: (r["code"], r["date"]) in EXCLUDED_PAIRS, axis=1)].reset_index(drop=True)
    base = base[["code", "date", "t_sec", "price_t"] + FEATURE_COLUMNS].copy()

    intraday_long = scan_intraday_long_labels()
    merged = base.merge(intraday_long, on=["code", "date", "t_sec"], how="left")

    pairs = merged[["code", "date"]].drop_duplicates()
    daily_rows = []
    for _, r in pairs.iterrows():
        info = daily_labels_and_gap_decomposition(r["code"], r["date"])
        info["code"] = r["code"]
        info["date"] = r["date"]
        daily_rows.append(info)
    daily_df = pd.DataFrame(daily_rows)
    merged = merged.merge(daily_df, on=["code", "date"], how="left")

    # |수익률|>50%는 분할/병합 잔여만이 아니라 이 유니버스의 실제 극단
    # 모멘텀 소형주(예: 001210, 8/10~8/31 3,140→12,480원 약 4배 - 스팟체크로
    # 실제 랠리임을 확인, 데이터 오류 아님)도 걸린다 - **자동 제외하지 않는다.**
    # 대신 진단용 플래그 컬럼만 남겨 리포트에서 투명하게 다룬다(평균 옆에
    # 중앙값을 같이 보여줘 왜곡 여부를 판단하게 한다).
    extreme_count = 0
    for name in DAILY_HORIZONS_TRADING_DAYS:
        ret = merged[f"exit_close_{name}"] / merged["price_t"] - 1
        extreme = ret.abs() > EXTREME_DAILY_RET_THRESHOLD
        extreme_count += int(extreme.sum())
        merged[f"extreme_{name}"] = extreme
        merged[f"ret_{name}"] = ret
    merged.attrs["extreme_daily_labels_flagged_not_dropped"] = extreme_count

    merged["seconds_since_open"] = merged["t_sec"] - SESSION_START
    return merged


LABEL_COLUMNS_ALL = ["ret_1m", "ret_3m", "ret_5m", "ret_10m", "ret_30m", "ret_60m", "ret_120m", "ret_session_last",
                      "ret_1d", "ret_3d", "ret_5d", "ret_10d"]


def spearman_ic_for_labels(df: pd.DataFrame, feature: str) -> pd.Series:
    out = {}
    for label in LABEL_COLUMNS_ALL:
        if label not in df.columns:
            continue
        sub = df[[feature, label]].dropna()
        out[label] = sub[feature].corr(sub[label], method="spearman") if len(sub) >= 100 else np.nan
    return pd.Series(out)


def label_sample_sizes(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label in LABEL_COLUMNS_ALL:
        if label not in df.columns:
            continue
        valid = df[label].notna()
        n_days = df.loc[valid, "date"].nunique()
        rows.append({"label": label, "n_valid": int(valid.sum()), "n_days_with_valid": n_days,
                     "pct_valid": valid.mean() * 100})
    return pd.DataFrame(rows)


def concurrent_position_estimate(signal_df: pd.DataFrame, trading_days_held: int) -> dict:
    """종목별 (date별 신호 건수)의 trading_days_held 거래일 롤링합 - 관측된 18일
    안에서만 근사(자본무제한 가정, 리포트에 명시)."""
    per_code_day = signal_df.groupby(["code", "date"]).size().rename("n").reset_index()
    peaks = []
    for code, g in per_code_day.groupby("code"):
        g = g.sort_values("date")
        rolling = g["n"].rolling(trading_days_held, min_periods=1).sum()
        peaks.append(rolling)
    all_roll = pd.concat(peaks) if peaks else pd.Series(dtype=float)
    return {"mean_concurrent": float(all_roll.mean()) if len(all_roll) else np.nan,
            "max_concurrent": float(all_roll.max()) if len(all_roll) else np.nan}


def condition_horizon_report(train: pd.DataFrame, test: pd.DataFrame, thresholds: dict[str, float]) -> pd.DataFrame:
    rows = []
    for group_name, df in (("IS", train), ("OOS", test)):
        mask = pd.Series(True, index=df.index)
        for feat, thr in thresholds.items():
            mask &= df[feat] <= thr
        sub_all = df[mask]
        n_days_total = df["date"].nunique()
        for label in LABEL_COLUMNS_ALL:
            if label not in df.columns:
                continue
            sub = sub_all.dropna(subset=[label]).copy()
            if sub.empty:
                rows.append({"group": group_name, "label": label, "n": 0})
                continue
            sub["net_ret"] = sub[label] - round_trip_cost_pct(sub["price_t"].to_numpy())
            gross_mean, gross_se, n, n_days = _day_clustered_mean_se(sub, label)
            net_mean, net_se, _, _ = _day_clustered_mean_se(sub, "net_ret")
            extreme_col = f"extreme_{label.replace('ret_', '')}"
            rows.append({
                "group": group_name, "label": label, "n": n, "n_days_triggered": n_days,
                "signals_per_day": n / n_days_total,
                "gross_mean_pct": gross_mean * 100, "gross_se_pct": gross_se * 100,
                "gross_median_pct": sub[label].median() * 100,
                "net_mean_pct": net_mean * 100, "net_se_pct": net_se * 100,
                "net_median_pct": sub["net_ret"].median() * 100,
                "t_gross": gross_mean / gross_se if gross_se else np.nan,
                "win_rate_pct": (sub[label] > 0).mean() * 100,
                "n_extreme_flagged": int(sub[extreme_col].sum()) if extreme_col in sub.columns else 0,
            })
    return pd.DataFrame(rows)


def main():
    t0 = time.time()
    print("일봉 정합 검증...", flush=True)
    base = pd.read_parquet("results/t0_forward_return_dataset.parquet")
    consistency = verify_price_consistency(base)
    flagged = consistency[consistency["flagged"]]
    print(f"불일치(2% 초과) {len(flagged)}행:\n{flagged.to_string(index=False)}", flush=True)
    consistency.to_csv("results/holding_horizon_price_consistency.csv", index=False)

    print("라벨(장중 장기+일단위) 스캔/조인...", flush=True)
    dataset = build_dataset()
    dt = time.time() - t0
    dataset.to_parquet("results/holding_horizon_dataset.parquet", index=False)
    print(f"완료 {dt:.1f}초 | 표본 {len(dataset):,}행 | 극단(|ret|>50%) 일단위 라벨 플래그(제외 안 함) "
          f"{dataset.attrs.get('extreme_daily_labels_flagged_not_dropped', 0)}건", flush=True)

    train = dataset[dataset["date"].isin(TRAIN_DATES)].reset_index(drop=True)
    test = dataset[dataset["date"].isin(TEST_DATES)].reset_index(drop=True)

    print("=== 라벨별 유효표본 (IS) ===")
    print(label_sample_sizes(train).to_string(index=False))
    print("=== 라벨별 유효표본 (OOS) ===")
    print(label_sample_sizes(test).to_string(index=False))

    print("=== w3_price_speed IC (라벨 전체, IS vs OOS) - 부호 뒤집히는 지점 ===")
    is_ic = spearman_ic_for_labels(train, "w3_price_speed")
    oos_ic = spearman_ic_for_labels(test, "w3_price_speed")
    print(pd.DataFrame({"IS": is_ic, "OOS": oos_ic}).to_string())

    q = {feat: train[feat].quantile(0.10) for feat in ("w3_price_speed", "w1_price_speed", "w10_price_speed")}
    print("진입조건 문턱(IS 하위10%):", q)
    horizon_report = condition_horizon_report(train, test, q)
    horizon_report.to_csv("results/holding_horizon_condition_report.csv", index=False)
    print("=== 진입조건(price_speed 세창 하위10%) 보유시간별 성적 ===")
    print(horizon_report.to_string(index=False))

    mask_train = pd.Series(True, index=train.index)
    for feat, thr in q.items():
        mask_train &= train[feat] <= thr
    mask_test = pd.Series(True, index=test.index)
    for feat, thr in q.items():
        mask_test &= test[feat] <= thr
    signal_df = pd.concat([train[mask_train], test[mask_test]])
    for name, k in DAILY_HORIZONS_TRADING_DAYS.items():
        est = concurrent_position_estimate(signal_df, k)
        print(f"동시보유 근사({name}, 관측 18일 내): 평균 {est['mean_concurrent']:.1f}건, "
              f"최대 {est['max_concurrent']:.1f}건")

    return dataset, train, test, horizon_report


if __name__ == "__main__":
    main()
