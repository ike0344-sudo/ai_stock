"""미끄러짐(슬리피지) 실측 — 사용자 직접지시(2026-09-01), 큐. 오늘 여러 갈래가
비용에 막혔는데 왕복비용 구성 중 미끄러짐(왕복 0.20~0.26%)이 **가정값**
(`max(0.1%, 1틱)`, `DEFAULT_SLIPPAGE_RATE`)이었다 — 한 번도 실측한 적이 없다.
**통합(AL) 8월 체결데이터**(`data/stocks/tick_al/`, 2026-08-04~08-28, 118종목)
그대로 - 이 디렉터리 자체가 AL이라 별도 보장조치 불필요.

## 호가가 없다 — 체결만으로 잴 수 있는 것만
호가 잔량이 없어 "내 주문이 얼마나 밀어냈는가"는 원리적으로 못 잰다. 대신
**연속 체결 간 가격이 실제로 얼마나 뛰는지**를 잰다 - 시장가로 추격매수할 때
"마지막 호가보다 얼마나 나쁜 가격에 체결될 수 있는가"의 보수적 프록시다(방향을
안 가리고 절대값을 쓴다 - 유리한 쪽으로 안 잡으려고, "낙관적으로 잡지 마라"
지시 그대로).

## 재사용
`_precursor_fastpath.to_grid`(tie-break 수정본)가 이미 시간순으로 올바르게
정렬한 `tick_prc`/`tick_qty`/`tick_sec`를 그대로 쓴다 - 정렬 로직 재구현 없음.
`t0_forward_return.krx_tick_size`/`round_trip_cost_pct`, `immediacy_zone.
time_bucket`(개장30분/중반/마감30분 경계 동일)도 그대로.

## 세 가지 측정
1. **틱 점프 분포** — 연속 체결가 차이(0이 아닌 것만), 틱배수·%로.
2. **종목·시간대별 차이** — 종목을 표본기간 평균 일일거래대금 기준 상/하위로,
   시간대는 개장30/중반/마감30으로 쪼갠다.
3. **체결크기별 차이(근사)** — 체결수량 10분위별 다음 점프 크기.
   **호가잔량이 없어 진짜 주문크기 영향은 못 잰다** - 상관일 뿐임을 명시.

실행: python -X utf8 -m backtesting.slippage_measurement
"""
import glob
import os

import numpy as np
import pandas as pd

from _precursor_fastpath import SESSION_START, to_grid
from backtesting.breakout_reversal import DEFAULT_SLIPPAGE_RATE
from backtesting.immediacy_zone import time_bucket
from backtesting.shooting_precursor import TRAIN_DATES
from backtesting.t0_forward_return import krx_tick_size, round_trip_cost_pct

TICK_DIR = "data/stocks/tick_al"


def _jumps_from_ticks(prc: np.ndarray, qty: np.ndarray, sec: np.ndarray) -> pd.DataFrame | None:
    """정렬된 원틱(prc/qty/sec, `to_grid`가 이미 tie-break 수정본으로 정렬해 준 것)에서
    0이 아닌 연속체결가 점프만 뽑는다. 점프가 없으면 None."""
    if len(prc) < 2:
        return None
    diffs = np.diff(prc.astype(np.int64))
    nz = diffs != 0
    if not nz.any():
        return None
    base_px = prc[:-1][nz]
    jump_abs = np.abs(diffs[nz])
    tick_sz = np.vectorize(krx_tick_size)(base_px)
    return pd.DataFrame({
        "abs_sec": sec[:-1][nz] + SESSION_START,
        "base_px": base_px, "jump_pct": jump_abs / base_px,
        "jump_ticks": jump_abs / tick_sz,
        "qty": qty[:-1][nz],
    })


def scan_jumps(tick_dir: str = TICK_DIR) -> tuple[pd.DataFrame, dict[str, float]]:
    """(종목,일)마다 연속 체결가의 0이 아닌 점프를 전부 모은다 + 종목별 평균
    일일거래대금(대금 상/하위 분류용)."""
    rows = []
    value_by_code: dict[str, list[float]] = {}
    for path in sorted(glob.glob(os.path.join(tick_dir, "*", "*.parquet"))):
        code = os.path.basename(os.path.dirname(path))
        date_str = os.path.splitext(os.path.basename(path))[0]
        g = to_grid(path)
        if g is None:
            continue
        prc, qty, sec = g["tick_prc"], g["tick_qty"], g["tick_sec"]
        value_by_code.setdefault(code, []).append(float((prc * qty).sum()))
        frame = _jumps_from_ticks(prc, qty, sec)
        if frame is not None:
            frame["code"], frame["date"] = code, date_str
            rows.append(frame)
    jumps = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    daily_value = {c: float(np.mean(v)) for c, v in value_by_code.items()}
    return jumps, daily_value


def summarize(series: pd.Series) -> dict:
    if series.empty:
        return {"n": 0}
    q = series.quantile([0.25, 0.50, 0.75, 0.90]).to_dict()
    return {"n": len(series), "p25": q[0.25], "p50": q[0.50], "p75": q[0.75], "p90": q[0.90],
            "mean": series.mean()}


def main() -> None:
    print("전 종목 원틱 스캔(연속체결 점프)...", flush=True)
    jumps, daily_value = scan_jumps()
    print(f"완료 - 점프(0아닌것) {len(jumps):,}건, 종목 {jumps['code'].nunique()}개", flush=True)

    os.makedirs("results", exist_ok=True)
    jumps.to_parquet("results/slippage_jumps.parquet", index=False)

    print("\n=== 1) 틱 점프 분포 (전체) ===")
    pct_stats = summarize(jumps["jump_pct"])
    tick_stats = summarize(jumps["jump_ticks"])
    print(f"jump_pct(%): n={pct_stats['n']:,} p25={pct_stats['p25']*100:.4f}% p50={pct_stats['p50']*100:.4f}% "
          f"p75={pct_stats['p75']*100:.4f}% p90={pct_stats['p90']*100:.4f}% mean={pct_stats['mean']*100:.4f}%")
    print(f"jump_ticks(틱배수): p25={tick_stats['p25']:.2f} p50={tick_stats['p50']:.2f} "
          f"p75={tick_stats['p75']:.2f} p90={tick_stats['p90']:.2f} mean={tick_stats['mean']:.2f}")
    print(f"현재 가정(DEFAULT_SLIPPAGE_RATE, 편도): {DEFAULT_SLIPPAGE_RATE*100:.2f}%")

    print("\n=== 2) 종목(대금 상/하위) x 시간대 ===")
    values = pd.Series(daily_value)
    median_value = values.median()
    high_value_codes = set(values[values >= median_value].index)
    jumps["value_tier"] = np.where(jumps["code"].isin(high_value_codes), "대금상위", "대금하위")
    jumps["time_bucket"] = time_bucket(jumps["abs_sec"].to_numpy())

    rows = []
    for tier in ("대금상위", "대금하위"):
        for bucket in ("개장30분", "중반", "마감30분"):
            sub = jumps[(jumps["value_tier"] == tier) & (jumps["time_bucket"] == bucket)]
            s = summarize(sub["jump_pct"])
            rows.append({"종목군": tier, "시간대": bucket, **{k: (v * 100 if k != "n" else v) for k, v in s.items()}})
    seg_table = pd.DataFrame(rows)
    print(seg_table.to_string(index=False))

    print("\n=== 3) 체결크기(수량) 10분위별 다음 점프 크기 (근사 - 호가잔량 없음) ===")
    jumps["qty_decile"] = pd.qcut(jumps["qty"], 10, labels=False, duplicates="drop")
    by_decile = jumps.groupby("qty_decile")["jump_pct"].median() * 100
    print(by_decile.to_string())

    print("\n=== 4) 현재 가정 vs 실측 비교표 ===")
    measured_median = pct_stats["p50"]
    measured_p75 = pct_stats["p75"]
    compare = pd.DataFrame([
        {"항목": "현재 가정(편도)", "값(%)": DEFAULT_SLIPPAGE_RATE * 100},
        {"항목": "실측 중앙값(편도 대체)", "값(%)": measured_median * 100},
        {"항목": "실측 75%(보수적 대체)", "값(%)": measured_p75 * 100},
    ])
    print(compare.to_string(index=False))

    print("\n=== 5) 재계산 - 오늘 기각된 것들이 되살아나는가 (실제 진입가 분포 재사용) ===")
    t0 = pd.read_parquet("results/t0_forward_return_dataset.parquet")
    train = t0[t0["date"].isin(TRAIN_DATES)]
    thresholds = {feat: train[feat].quantile(0.10)
                  for feat in ("w3_price_speed", "w1_price_speed", "w10_price_speed")}
    mask = pd.Series(True, index=t0.index)
    for feat, thr in thresholds.items():
        mask &= t0[feat] <= thr
    entry_prices = t0.loc[mask, "price_t"].to_numpy()
    old_cost_mean = round_trip_cost_pct(entry_prices).mean()
    print(f"(a)(b) 공통 진입조건(price_speed 세창 하위10%, n={len(entry_prices):,}) 실제 진입가로 재계산:")
    print(f"  기존 가정(0.1%) 평균비용: {old_cost_mean*100:.4f}%")
    for label, rate in [("실측중앙값(0.109%)", measured_median), ("실측75%(0.160%)", measured_p75)]:
        new_cost_mean = round_trip_cost_pct(entry_prices, slippage_rate=rate).mean()
        delta = new_cost_mean - old_cost_mean
        print(f"  {label} 평균비용: {new_cost_mean*100:.4f}% (기존대비 {delta*100:+.4f}%p)")
    print("\n  exit_path_grid_search 최선조합(IS 기대값 -0.430%, 비용 0.514% 반영분)과 "
          "immediacy_zone 최고축(IS 순수익 -0.515%, 비용 0.515% 반영분)에")
    print("  위 비용변화(%p)를 그대로 더해 판정 - 실측이 가정보다 크면(비용 상승) 기존 마이너스는 "
          "**더 나빠지고**, 작으면(비용 하락) 완화된다:")
    for tag, base_verdict, base_cost in [("(a) exit_path_grid_search", -0.430, 0.514),
                                          ("(b) immediacy_zone", -0.515, 0.515)]:
        for label, rate in [("실측중앙값", measured_median), ("실측75%", measured_p75)]:
            new_cost_mean = round_trip_cost_pct(entry_prices, slippage_rate=rate).mean()
            delta_pct = (new_cost_mean - old_cost_mean) * 100
            new_verdict = base_verdict - delta_pct  # 비용이 오르면 기대값은 그만큼 더 나빠진다(부호 주의)
            tag_verdict = "되살아남(양전환)" if new_verdict > 0 else "여전히 마이너스"
            print(f"  {tag} x {label}: {base_verdict:.3f}% -> {new_verdict:.3f}% ({tag_verdict})")


if __name__ == "__main__":
    main()
