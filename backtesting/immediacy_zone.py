"""사자마자 오르는 구간 (즉시성) — 사용자 직접지시(2026-09-01), 큐 2번째.
**통합(AL) 8월 체결데이터**(`data/stocks/tick_al/`, 2026-08-04~08-28, 18거래일 x
118종목 — KRX전용 tick 저장소는 이미 삭제됐고 이 디렉터리 자체가 AL이라 별도
보장조치 불필요, standing.md).

지금까지는 "평균적으로 오르나"만 봤다. 이건 다른 질문이다: 진입 직후 빠지지 않고
바로 오르는 구간이 따로 있는가.

## 재사용 — 새로 튼 것은 ret_30s 스캔 하나뿐
- MFE/MAE: `results/mfe_mae_dataset.parquet`(mfe_mae.py 산출물)에서 `mae_1m`만
  가져온다("안 빠졌다" 판정에 필요한 전부).
- price_speed/tick_speed/value_surge/ret_1m/3m/5m/10m: `results/t0_forward_return_
  dataset.parquet` 그대로(다시 스캔 안 함).
- divergence: `execution_price_divergence.build_dataset()`을 그대로 호출한다(그
  함수가 이미 t0 데이터셋에 divergence 컬럼만 얹어 반환 — 재계산 아님).
- 대금20위 등락률1등 여부: 오늘 만든 `chgtop_leader_persistence.load_full_frames`
  (큐 1번 항목 산출물)를 재사용해 분당 리더 맵을 만들고 T0의 소속 분에 매칭한다.
- **ret_30s만 새로 스캔했다** — 기존 어느 산출물에도 30초 시점 점수익률이 없어서다.
  `t0_forward_return.py`의 `ret_{k}=px[T0+k]/px[T0]-1` 패턴을 k=30 하나에만 적용한
  것으로 새 로직이 아니다.

## 정의 (지시 그대로, 숫자로 고정)
- **안 빠졌다** = `mae_1m`([T0,T0+60초] 최저가/진입가-1) `>= -0.001`
- **바로 올랐다_h**(h=30/60/180초) = `ret_h > 0`. ret_60s=ret_1m, ret_180s=ret_3m을
  그대로 재사용(새 컬럼 아님).
- **즉시성_h** = 안빠졌다 AND 바로올랐다_h — h(30/60/180초)별로 따로 낸다. 지시문이
  "안 빠졌다"·"바로 올랐다" 둘을 동시에 만족한 비율이라고만 했지 세 호라이즌을 전부
  동시에 만족해야 하는지는 명시하지 않아 **h별로 따로 보고하는 쪽으로 해석했다**
  (해석 판단, 명시).

## 시간대 사전등록 (holding_horizon 7번 "개장 유리해 보임"의 사후관찰을 검증)
**개장30분**=09:00:00~09:29:59, **마감30분**=15:00:00~15:29:59, **중반**=그 사이.
지금 정하고 그대로 쓴다 — 결과 보고 안 바꾼다.

## 조건축 — 전부 기존에 살아있던 것만, 새로 안 만듦
`w3_price_speed`(최강·최일관), `w1_tick_speed`(10~60초창 체결속도의 이 데이터셋
내 최근접값 — 원래 연구의 10/20/../60초 다중창과 완전히 같지는 않음, 명시),
`w3_divergence`(execution_price_divergence의 "느린"=하위10%), `time_bucket`,
`is_chgtop_leader`. 문턱은 전부 **IS에서만** 고르고 OOS엔 그대로 적용.

실행: python -m backtesting.immediacy_zone
"""
import glob
import os

import numpy as np
import pandas as pd

from _precursor_fastpath import N, SESSION_START, to_grid
from backtesting.chgtop_leader_persistence import load_full_frames
from backtesting.execution_price_divergence import build_dataset as build_divergence_dataset
from backtesting.shooting_precursor import TEST_DATES, TRAIN_DATES
from backtesting.t0_forward_return import T0_GRID, _day_clustered_mean_se, round_trip_cost_pct
from backtesting.theme_rank_prereg_measure import load_name_to_code

MAE_FLOOR = -0.001
FORWARD_HORIZONS = {"30s": "ret_30s", "60s": "ret_1m", "180s": "ret_3m"}
TICK_DIR = "data/stocks/tick_al"

OPEN_END = 9 * 3600 + 30 * 60      # 09:30:00, 자정기준 초
CLOSE_START = 15 * 3600            # 15:00:00


def scan_ret_30s(tick_dir: str = TICK_DIR) -> pd.DataFrame:
    """t0_forward_return.py 의 ret_{k} 계산과 완전히 같은 패턴, k=30 하나만."""
    rows = []
    for path in sorted(glob.glob(os.path.join(tick_dir, "*", "*.parquet"))):
        code = os.path.basename(os.path.dirname(path))
        date_str = os.path.splitext(os.path.basename(path))[0]
        g = to_grid(path)
        if g is None:
            continue
        px = g["px"]
        future_idx = T0_GRID + 30
        in_range = future_idx <= N - 1
        ret = np.full(len(T0_GRID), np.nan)
        ret[in_range] = px[future_idx[in_range]] / px[T0_GRID[in_range]] - 1
        rows.append(pd.DataFrame({"code": code, "date": date_str,
                                   "t_sec": T0_GRID + SESSION_START, "ret_30s": ret}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def time_bucket(t_sec: np.ndarray) -> np.ndarray:
    """t_sec 은 이미 자정 기준 절대초(SESSION_START 포함)다."""
    return np.select([t_sec < OPEN_END, t_sec >= CLOSE_START],
                      ["개장30분", "마감30분"], default="중반")


def minute_leader_map(date_iso: str, name_to_code: dict) -> dict[str, str]:
    """그 날 분마다 '대금20위 등락률1등' 코드 - chgtop_leader_persistence 산출물 재사용."""
    frames = load_full_frames(date_iso)
    if frames is None:
        return {}
    out = {}
    for fr in frames:
        chgtop = fr.get("chgtop")
        if chgtop:
            code = name_to_code.get(chgtop[0])
            if code:
                out[fr["t"]] = code
    return out


def build_dataset() -> pd.DataFrame:
    df = build_divergence_dataset()  # t0_forward_return 전체 + divergence, 재계산 없음
    mae = pd.read_parquet("results/mfe_mae_dataset.parquet")[["code", "date", "t_sec", "mae_1m"]]
    df = df.merge(mae, on=["code", "date", "t_sec"], how="left")

    ret30 = scan_ret_30s()
    df = df.merge(ret30, on=["code", "date", "t_sec"], how="left")

    df["no_dip"] = df["mae_1m"] >= MAE_FLOOR
    for name, ret_col in FORWARD_HORIZONS.items():
        df[f"immediacy_{name}"] = df["no_dip"] & (df[ret_col] > 0)

    df["time_bucket"] = time_bucket(df["t_sec"].to_numpy())

    name_to_code = load_name_to_code()
    leader_maps = {d: minute_leader_map(d, name_to_code) for d in sorted(df["date"].unique())}
    hh = (df["t_sec"] // 3600).astype(int).astype(str).str.zfill(2)
    mm = (df["t_sec"] % 3600 // 60).astype(int).astype(str).str.zfill(2)
    minute_str = hh + ":" + mm
    df["is_chgtop_leader"] = [
        leader_maps.get(d, {}).get(m) == c
        for d, m, c in zip(df["date"], minute_str, df["code"])
    ]
    return df


def immediacy_rate_table(train: pd.DataFrame, test: pd.DataFrame) -> pd.DataFrame:
    """전체 표본 즉시성 비율(조건 없음) - 베이스라인."""
    rows = []
    for label, df in (("IS", train), ("OOS", test)):
        for h in FORWARD_HORIZONS:
            col = f"immediacy_{h}"
            valid = df[col].notna() & df["no_dip"].notna()
            rows.append({"set": label, "horizon": h, "n_valid": int(valid.sum()),
                         "immediacy_rate_pct": df.loc[valid, col].mean() * 100})
    return pd.DataFrame(rows)


def _axis_group_report(train: pd.DataFrame, test: pd.DataFrame, axis: str,
                        is_high) -> pd.DataFrame:
    """축 하나(연속형은 IS 상/하위10% 문턱, 범주형은 값 그대로)에 대해 그룹별
    즉시성 비율 + 순수익(비용반영)을 IS/OOS 로 낸다."""
    rows = []
    for label, df in (("IS", train), ("OOS", test)):
        mask = is_high(df)
        sub_all = df[mask]
        n_days_total = df["date"].nunique()
        for h, ret_col in FORWARD_HORIZONS.items():
            col = f"immediacy_{h}"
            sub = sub_all.dropna(subset=[col, ret_col])
            if sub.empty:
                rows.append({"set": label, "axis": axis, "horizon": h, "n": 0})
                continue
            net = sub[ret_col] - round_trip_cost_pct(sub["price_t"].to_numpy())
            net_mean, net_se, n, n_days = _day_clustered_mean_se(
                sub.assign(net=net), "net")
            rows.append({
                "set": label, "axis": axis, "horizon": h, "n": n, "n_days": n_days,
                "signals_per_day": n / max(n_days_total, 1),
                "immediacy_rate_pct": sub[col].mean() * 100,
                "net_ret_mean_pct": net_mean * 100, "net_ret_se_pct": net_se * 100,
            })
    return pd.DataFrame(rows)


def axis_reports(train: pd.DataFrame, test: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out = {}
    lo_speed = train["w3_price_speed"].quantile(0.10)
    out["w3_price_speed(하위10%)"] = _axis_group_report(
        train, test, "w3_price_speed(하위10%)", lambda d: d["w3_price_speed"] <= lo_speed)

    hi_tick = train["w1_tick_speed"].quantile(0.90)
    out["w1_tick_speed(상위10%)"] = _axis_group_report(
        train, test, "w1_tick_speed(상위10%)", lambda d: d["w1_tick_speed"] >= hi_tick)

    lo_div = train["w3_divergence"].quantile(0.10)
    out["w3_divergence(느린,하위10%)"] = _axis_group_report(
        train, test, "w3_divergence(느린,하위10%)", lambda d: d["w3_divergence"] <= lo_div)

    for bucket in ("개장30분", "중반", "마감30분"):
        out[f"time_bucket={bucket}"] = _axis_group_report(
            train, test, f"time_bucket={bucket}", lambda d, b=bucket: d["time_bucket"] == b)

    out["is_chgtop_leader"] = _axis_group_report(
        train, test, "is_chgtop_leader", lambda d: d["is_chgtop_leader"])

    return out


def mae_distribution(df: pd.DataFrame, mask, label: str) -> pd.DataFrame:
    sub = df[mask]["mae_1m"].dropna()
    if sub.empty:
        return pd.DataFrame([{"group": label, "n": 0}])
    q = sub.quantile([0.05, 0.10, 0.25, 0.50]).to_dict()
    return pd.DataFrame([{"group": label, "n": len(sub),
                          "p05": q[0.05] * 100, "p10": q[0.10] * 100,
                          "p25": q[0.25] * 100, "median": q[0.50] * 100}])


def main() -> None:
    print("데이터셋 조립(재사용 3개 + ret_30s 신규스캔 1개)...", flush=True)
    dataset = build_dataset()
    os.makedirs("results", exist_ok=True)
    dataset.to_parquet("results/immediacy_zone_dataset.parquet", index=False)
    print(f"완료 - 표본 {len(dataset):,}행", flush=True)

    train = dataset[dataset["date"].isin(TRAIN_DATES)].reset_index(drop=True)
    test = dataset[dataset["date"].isin(TEST_DATES)].reset_index(drop=True)

    pd.set_option("display.width", 220)
    print("\n=== 베이스라인 즉시성 비율(조건 없음) ===")
    print(immediacy_rate_table(train, test).to_string(index=False))

    print("\n=== 축별 즉시성 비율 + 순수익(비용반영) ===")
    reports = axis_reports(train, test)
    all_axes = pd.concat(reports.values(), ignore_index=True)
    all_axes.to_csv("results/immediacy_zone_axis_report.csv", index=False)
    print(all_axes.to_string(index=False))

    print("\n=== MAE 분포 - 손절폭 참고(즉시성_60s 높은 부분집합 vs 전체) ===")
    high60 = dataset["immediacy_60s"] == True  # noqa: E712
    mae_all = mae_distribution(dataset, pd.Series(True, index=dataset.index), "전체")
    mae_high = mae_distribution(dataset, high60, "즉시성_60s=True")
    print(pd.concat([mae_all, mae_high]).to_string(index=False))


if __name__ == "__main__":
    main()
