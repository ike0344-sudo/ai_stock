"""+10% 미만 진입 → +15~20% 분할매도 — 수익 나는 구간 탐색.

사전등록: docs/LADDER_EXIT_PREREGISTRATION.md (진입문턱 5개·청산 5변형·기각조건이 거기 있다).

## 직전 측정과 뭐가 다른가
`leader_20pct.py`는 "+10%에 사서 +20%에 한 번에 판다"였다. 이건 **진입이 +10% 미만**
(X=5~9%)이고 **청산이 +15%/+17.5%/+20% 3분할**이다. 진입·청산이 둘 다 달라 결과를
물려받지 않고 새로 잰다. 데이터도 33거래일로 늘었다(직전 18일).

## 재사용 (중복 구현 금지)
`_precursor_fastpath.to_grid`(정규장 필터+1초격자)/`window_sum`,
`shooting_precursor._tick_rule_direction`, `t0_forward_return._expanding_period_avg`/
`round_trip_cost_pct`/`_day_clustered_mean_se`,
`leader_20pct.threshold`(부동소수 경계 보정)/`prev_close_map`/`lookup_prev_close`/
`bootstrap_net_ci`/`cohens_d`.

## 청산 시뮬레이션 — 틱 순서 그대로
진입 틱 이후의 체결 시퀀스를 한 번 훑으며 목표가/손절 도달 순서를 **정확히** 판정한다
(봉 근사 없음 - 체결 순서가 원본에 있다).

실행: python -m backtesting.ladder_exit_scan
"""
import glob
import os
import time

import numpy as np
import pandas as pd

from _precursor_fastpath import N, SESSION_START, to_grid, window_sum
from backtesting.leader_20pct import (
    DAILY_DIR,
    bootstrap_net_ci,
    lookup_prev_close,
    prev_close_map,
    threshold,
)
from backtesting.shooting_precursor import _tick_rule_direction
from backtesting.t0_forward_return import (
    _day_clustered_mean_se,
    _expanding_period_avg,
    round_trip_cost_pct,
)

TICK_DIR = "data/stocks/tick_al"

ENTRY_PCTS = (0.05, 0.06, 0.07, 0.08, 0.09)   # 진입문턱 (전일종가 대비) - 전부 +10% 미만
LADDER = (0.15, 0.175, 0.20)                  # 분할매도 3단
STOP_PCT = -0.05                              # L3+손절 변형에서만 사용

FEATURE_WINDOWS = {"w10": 10, "w30": 30}       # 직전 측정에서 방향 재현된 것만
VALUE_SURGE_WINDOWS = {"vs3": 3, "vs10": 10}
FEATURE_COLUMNS = ([f"{k}_tick_speed" for k in FEATURE_WINDOWS]
                   + [f"{k}_value_surge" for k in VALUE_SURGE_WINDOWS]
                   + ["cum_value_eok"])

CLOSE_MISMATCH_TOL = 0.01
IS_MONTH, OOS_MONTH = "2026-08", "2026-09"


def simulate_ladder(prices: np.ndarray, entry_price: float, prev_close: float,
                    ladder=LADDER, stop_pct: float | None = None) -> dict:
    """진입 이후 체결 시퀀스(prices)를 한 번 훑어 분할매도를 그대로 시뮬레이션한다.

    각 단(1/n씩)은 해당 목표가에 **처음 닿는 순간** 체결된 것으로 본다(지정가 매도).
    stop_pct가 주어지면 그 가격에 먼저 닿는 순간 **남은 수량 전부** 청산한다.
    끝까지 남은 수량은 마지막 체결가(=종가)로 청산.
    반환: 총수익률(가중평균, 비용 전) + 각 단 체결 여부.
    """
    n_legs = len(ladder)
    stop_px = entry_price * (1 + stop_pct) if stop_pct is not None else None

    # 벡터화: 파이썬 루프로 틱을 훑으면 3,903파일 x 5문턱 x 5변형에서 20억 회 반복이
    # 돌아 스캔이 10분을 넘겼다(실측). 각 단은 "그 가격에 한 번이라도 닿았는가"로만
    # 정해지므로 최초 도달 인덱스만 구하면 되고, 손절이 있을 때만 그 인덱스와 비교하면
    # 순서 판정이 끝난다 - 결과는 루프 버전과 동일(유닛테스트로 고정).
    def _first_index(mask: np.ndarray) -> float:
        return float(np.argmax(mask)) if mask.any() else np.inf

    i_stop = _first_index(prices <= stop_px) if stop_px is not None else np.inf
    portion = 1.0 / n_legs
    realized, remaining = 0.0, 1.0
    filled = []
    for p in ladder:
        i_leg = _first_index(prices >= threshold(prev_close, 1 + p))
        hit = i_leg < i_stop            # 손절보다 먼저 닿아야 체결
        filled.append(bool(hit))
        if hit:
            realized += portion * (prev_close * (1 + p) / entry_price - 1)
            remaining -= portion

    stopped = bool(np.isfinite(i_stop) and remaining > 1e-12)
    if stopped:
        realized += remaining * (stop_px / entry_price - 1)
        remaining = 0.0
    if remaining > 1e-12:
        realized += remaining * (float(prices[-1]) / entry_price - 1)
    out = {"gross": realized, "legs_filled": sum(filled), "stopped": stopped, "filled": filled}
    # 단수가 다른 변형(S15/S20은 1단)도 같은 함수를 쓰므로 3단 전용 키는 3단일 때만 붙인다
    if n_legs == 3:
        out.update({"hit15": filled[0], "hit175": filled[1], "hit20": filled[2]})
    return out


def stock_day_scan(path: str, code: str, date_str: str, prev_close: float | None) -> list[dict]:
    """한 종목·일 → 진입문턱 X마다 이벤트 1건(있으면). 갭시작은 gap 플래그로 표시만."""
    g = to_grid(path)
    if g is None or prev_close is None or prev_close <= 0:
        return []
    tick_sec, tick_prc, tick_qty = g["tick_sec"], g["tick_prc"], g["tick_qty"]
    if len(tick_sec) == 0:
        return []

    value_per_sec = np.bincount(tick_sec, weights=tick_prc * tick_qty, minlength=N)
    cs_value = np.concatenate(([0.0], np.cumsum(value_per_sec)))
    cnt_per_sec, vol_per_sec = g["cnt"], g["vol"]
    direction = _tick_rule_direction(tick_prc)
    buy_q = np.bincount(tick_sec, weights=np.where(direction > 0, tick_qty, 0.0), minlength=N)
    sell_q = np.bincount(tick_sec, weights=np.where(direction < 0, tick_qty, 0.0), minlength=N)
    np.seterr(divide="ignore", invalid="ignore")

    out = []
    for x in ENTRY_PCTS:
        thr = threshold(prev_close, 1 + x)
        hits = np.flatnonzero(tick_prc >= thr)
        if len(hits) == 0:
            continue
        i0 = int(hits[0])
        t0_sec, entry_price = int(tick_sec[i0]), float(tick_prc[i0])
        rec = {
            "code": code, "date": date_str, "entry_pct": x,
            "t0_sec": t0_sec, "t0_hour": (t0_sec + SESSION_START) // 3600,
            "entry_price": entry_price, "prev_close": prev_close,
            "entry_actual_pct": entry_price / prev_close - 1,
            "gap_open": bool(tick_prc[0] >= thr),
            "last_price": float(tick_prc[-1]),
            "cum_value_eok": cs_value[t0_sec] / 1e8,
            "raw_rows": g["raw_rows"], "kept_rows": g["kept_rows"],
        }
        path_px = tick_prc[i0:]
        # 청산 변형들 (전부 같은 체결 경로로 판정)
        l3 = simulate_ladder(path_px, entry_price, prev_close)
        rec.update({"gross_L3": l3["gross"], "legs_filled": l3["legs_filled"],
                    "hit15": l3["hit15"], "hit175": l3["hit175"], "hit20": l3["hit20"]})
        rec["gross_S15"] = simulate_ladder(path_px, entry_price, prev_close, ladder=(0.15,))["gross"]
        rec["gross_S20"] = simulate_ladder(path_px, entry_price, prev_close, ladder=(0.20,))["gross"]
        rec["gross_CLOSE"] = float(path_px[-1]) / entry_price - 1
        stop = simulate_ladder(path_px, entry_price, prev_close, stop_pct=STOP_PCT)
        rec["gross_L3STOP"] = stop["gross"]
        rec["stopped"] = stop["stopped"]

        for key, w in FEATURE_WINDOWS.items():
            wc, wv, wb, ws = (window_sum(a, w) for a in (cnt_per_sec, vol_per_sec, buy_q, sell_q))
            rec[f"{key}_tick_speed"] = wc[t0_sec] / w
        grid = np.array([t0_sec])
        for key, w in VALUE_SURGE_WINDOWS.items():
            wv = window_sum(value_per_sec, w)
            avg = _expanding_period_avg(cs_value, grid, w)
            vs = wv[t0_sec] / avg[t0_sec] if avg[t0_sec] else np.nan
            rec[f"{key}_value_surge"] = np.nan if not np.isfinite(vs) else vs
        out.append(rec)
    return out


def scan_all(tick_dir: str = TICK_DIR) -> tuple[pd.DataFrame, dict]:
    codes = sorted(d for d in os.listdir(tick_dir) if os.path.isdir(os.path.join(tick_dir, d)))
    closes = prev_close_map(codes)
    rows, audit = [], {"stock_days": 0, "raw_rows": 0, "kept_rows": 0,
                        "no_prev_close": 0, "close_mismatch": 0}
    for code in codes:
        if code not in closes:
            continue
        daily_close = closes[code]
        for path in sorted(glob.glob(os.path.join(tick_dir, code, "*.parquet"))):
            date_str = os.path.splitext(os.path.basename(path))[0]
            pc = lookup_prev_close(daily_close, date_str)
            if pc is None:
                audit["no_prev_close"] += 1
                continue
            recs = stock_day_scan(path, code, date_str, pc)
            audit["stock_days"] += 1
            if recs:
                audit["raw_rows"] += recs[0]["raw_rows"]
                audit["kept_rows"] += recs[0]["kept_rows"]
                today = daily_close.get(pd.Timestamp(date_str))
                if today and today > 0 and abs(recs[0]["last_price"] / float(today) - 1) > CLOSE_MISMATCH_TOL:
                    audit["close_mismatch"] += 1
                    continue
                rows.extend(recs)
    return pd.DataFrame(rows), audit


EXIT_VARIANTS = ["L3", "S15", "S20", "CLOSE", "L3STOP"]


def add_net(df: pd.DataFrame, cost_mult: float = 1.0) -> pd.DataFrame:
    out = df.copy()
    cost = round_trip_cost_pct(out["entry_price"].to_numpy()) * cost_mult
    out["cost_pct"] = cost
    for v in EXIT_VARIANTS:
        out[f"net_{v}"] = out[f"gross_{v}"] - cost
    return out


def summarize(df: pd.DataFrame, group_label: str, variant: str = "L3") -> dict:
    if df.empty:
        return {"group": group_label, "variant": variant, "n": 0}
    net = df[f"net_{variant}"]
    mean, se, n, n_days = _day_clustered_mean_se(df.assign(_v=net), "_v")
    lo, hi = bootstrap_net_ci(100 * net.to_numpy())
    return {
        "group": group_label, "variant": variant, "n": len(df), "n_days": n_days,
        "trades_per_day": len(df) / max(n_days, 1),
        "hit15_pct": 100 * df["hit15"].mean(), "hit175_pct": 100 * df["hit175"].mean(),
        "hit20_pct": 100 * df["hit20"].mean(),
        "gross_pct": 100 * df[f"gross_{variant}"].mean(),
        "net_pct": 100 * net.mean(), "net_median_pct": 100 * net.median(),
        "t_day": mean / se if se else np.nan,
        "win_pct": 100 * (net > 0).mean(), "worst_pct": 100 * net.min(),
        "ci95": f"[{lo:.2f}, {hi:.2f}]",
    }


def main():
    t0 = time.time()
    n_files = len(glob.glob(os.path.join(TICK_DIR, "*", "*.parquet")))
    print(f"스캔 시작 ({n_files:,}개 종목·일, 진입문턱 {len(ENTRY_PCTS)}개 x 청산 {len(EXIT_VARIANTS)}변형)", flush=True)
    print("ETA 추정: 40~70초 (직전 2,017파일 20.5초의 1.9배)", flush=True)

    events, audit = scan_all()
    print(f"스캔 {time.time()-t0:.1f}초 | 종목·일 {audit['stock_days']:,} | "
          f"원본 {audit['raw_rows']:,}행 → 정규장 {audit['kept_rows']:,}행 "
          f"(시간외 {100*(1-audit['kept_rows']/max(audit['raw_rows'],1)):.1f}% 제거) | "
          f"전일종가없음 {audit['no_prev_close']} | 종가불일치 제외 {audit['close_mismatch']}", flush=True)

    gap = events[events["gap_open"]]
    events = events[~events["gap_open"]].reset_index(drop=True)
    events = add_net(events)
    os.makedirs("results", exist_ok=True)
    events.to_csv("results/ladder_exit_events.csv", index=False, encoding="utf-8-sig")
    print(f"갭시작 {len(gap)}건 제외 → 매매가능 {len(events):,}건", flush=True)

    events["month"] = events["date"].str[:7]
    is_ev = events[events["month"] == IS_MONTH]
    oos_ev = events[events["month"] == OOS_MONTH]
    print(f"IS(8월) {len(is_ev):,}건 / OOS(9월) {len(oos_ev):,}건\n")

    # --- 1) 진입문턱 x 청산변형 전수 (IS/OOS 나란히) ---
    rows = []
    for x in ENTRY_PCTS:
        for v in EXIT_VARIANTS:
            for lab, d in (("IS", is_ev), ("OOS", oos_ev)):
                r = summarize(d[d["entry_pct"] == x], f"{lab} X={x:.0%}", v)
                r["entry_pct"] = x
                rows.append(r)
    table = pd.DataFrame(rows)
    table.to_csv("results/ladder_exit_summary.csv", index=False, encoding="utf-8-sig")

    cols = ["group", "variant", "n", "trades_per_day", "hit15_pct", "hit20_pct",
            "gross_pct", "net_pct", "net_median_pct", "win_pct", "t_day", "ci95"]
    print("=== 진입문턱 x 청산변형 (전수, 안 되는 것 포함) ===")
    print(table[cols].to_string(index=False))

    # --- 2) 분할매도가 정말 나은가 (같은 진입에서 변형 대조) ---
    print("\n=== 분할매도 L3 vs 일괄 S15/S20 vs CLOSE (OOS 기준 순수익%) ===")
    piv = table[table["group"].str.startswith("OOS")].pivot(
        index="entry_pct", columns="variant", values="net_pct")
    print(piv.round(3).to_string())

    # --- 3) 공통종목 한정 (유니버스 구성 변화 통제, 사전등록 §5) ---
    per_code_days = events.groupby("code")["date"].nunique()
    both = set(is_ev["code"]) & set(oos_ev["code"])
    common = events[events["code"].isin(both)]
    print(f"\n=== 공통종목({len(both)}개) 한정 — 유니버스 변화 통제 ===")
    rows2 = []
    for x in ENTRY_PCTS:
        for lab, m in (("IS", IS_MONTH), ("OOS", OOS_MONTH)):
            d = common[(common["entry_pct"] == x) & (common["month"] == m)]
            r = summarize(d, f"{lab} X={x:.0%}", "L3")
            rows2.append(r)
    print(pd.DataFrame(rows2)[["group", "n", "hit15_pct", "hit20_pct", "net_pct",
                                "net_median_pct", "win_pct", "ci95"]].to_string(index=False))

    print(f"\n전체 파이프라인 {time.time()-t0:.1f}초", flush=True)
    return {"events": events, "table": table, "audit": audit, "gap": gap}


if __name__ == "__main__":
    main()
