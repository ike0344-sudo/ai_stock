"""전략 자동 탐색 루프 — 후보 생성 → 워크포워드 OOS → 홀드아웃 게이트 → 저널.

"스스로 전략을 만드는 봇"의 실체는 후보 생성기가 아니라 **기각 게이트**다.
후보 100개를 돌리면 순전히 우연으로 baseline을 이기는 놈이 반드시 나온다.
그래서 여기서 중요한 코드는 gate() 하나뿐이고 나머지는 배관이다.

설계 결정 3가지:
1. 스캔은 한 번만. 진입 임계값을 느슨하게 잡아 전부 스캔하고, 후보마다
   메모리에서 필터링한다. 후보당 재스캔하면 수 분 × 100 = 탐색 불가.
2. 홀드아웃(마지막 HOLDOUT_DAYS일)은 탐색 중 절대 건드리지 않는다.
   워크포워드 OOS도 후보를 고르는 데 쓰는 순간 in-sample이 된다.
3. 모든 후보는 대조군과 함께 평가한다. atr_stop_ab.py에서 ATR 변형이
   전부 상한에 붙어 사실상 고정 손절이었던 걸 대조군 없이는 못 잡았다.

실행: python evolve.py --scan     (최초 1회, 수 분)
      python evolve.py            (탐색 — 스캔 캐시 재사용)
"""
import argparse
import json
import os
from datetime import date, timedelta
from itertools import product

import numpy as np
import pandas as pd

from backtesting.breakout_reversal import simulate_trade_path
from backtesting.final_strategy import (
    DAY_RETURN_CEILING,
    DAY_RETURN_FLOOR,
    DRAWDOWN_THRESHOLD,
    MIN_RETURN_PCT,
    MIN_TRADE_VALUE,
    N_DAY_HIGH,
    RECOMMENDED_MAX_CONCURRENT_POSITIONS,
    RECOMMENDED_PROBA_THRESHOLD,
    STOP_LOSS_PCT,
    TIERS,
    TOP_N,
    UNREACHABLE_PCT,
    WINDOW_MINUTES,
    detect_final_entries,
    evaluate_tiered_exit_from_path_with_exit_idx,
    load_kospi_regime_by_day,
)
from backtesting.ml.walk_forward import split as wf_split
from backtesting.ml_entry_filter import (
    FEATURE_COLUMNS,
    InsufficientTrainingDataError,
    extract_entry_features,
    predict_quality_proba,
    train_entry_filter_model,
)
from backtesting.portfolio_sim import simulate_slot_portfolio
from backtesting.universe import daily_top_n_from_local

CACHE = os.path.join(".cache", "evolve_scan.pkl")
JOURNAL = "evolve_journal.jsonl"
MODEL_KWARGS = {"n_estimators": 300, "max_depth": 6, "min_samples_leaf": 20, "n_jobs": -1}
TRADE_COLUMNS = ["code", "entry_time", "exit_time", "pct"]

HOLDOUT_DAYS = 90       # 탐색 중 절대 안 보는 구간
MIN_TRADES = 100        # 표본 부족한 대박은 우연
EDGE_MARGIN = 1.15      # baseline 대비 15% 이상 나아야 후보로 인정

# 스캔용 느슨한 임계값 — 실제 후보 필터는 이보다 조이기만 한다(메모리 후처리).
SCAN_DAY_FLOOR = 0.04
SCAN_MIN_RETURN = 0.008
SCAN_TRADE_VALUE = 2_000_000_000


def scan(data_dir: str = "data") -> pd.DataFrame:
    """느슨한 조건으로 전부 스캔. 후보별 재스캔을 없애려고 조건 판정에 쓸 원본
    값(day_return, trade_value 등)을 컬럼으로 같이 저장한다."""
    daily_top = daily_top_n_from_local(os.path.join(data_dir, "stocks", "daily"), top_n=TOP_N)
    regime_by_day = load_kospi_regime_by_day(data_dir)
    minute_dir = os.path.join(data_dir, "stocks", "minute")
    daily_dir = os.path.join(data_dir, "stocks", "daily")

    rows = []
    files = sorted(f for f in os.listdir(minute_dir) if f.endswith(".csv"))
    for i, filename in enumerate(files):
        if i % 100 == 0:
            print(f"  scan {i}/{len(files)} ... rows={len(rows)}", flush=True)
        code = filename[: -len(".csv")]
        daily_path = os.path.join(daily_dir, filename)
        if not os.path.exists(daily_path):
            continue
        minute_df = pd.read_csv(os.path.join(minute_dir, filename), index_col=0, parse_dates=True)
        daily_df = pd.read_csv(daily_path, index_col=0, parse_dates=True)

        entries = detect_final_entries(minute_df, daily_df, code, daily_top, regime_by_day)
        if entries.sum() == 0:
            continue

        close, volume = minute_df["close"], minute_df["volume"]
        for pos in (j for j, v in enumerate(entries.to_numpy()) if v):
            ref = max(0, pos - WINDOW_MINUTES + 1)
            day_start = minute_df.index[pos].normalize()
            day_slice = minute_df.loc[day_start:minute_df.index[pos]]
            path = simulate_trade_path(
                minute_df, pos, take_profit_pct=UNREACHABLE_PCT, stop_loss_pct=UNREACHABLE_PCT
            ).path
            rows.append({
                "code": code,
                "entry_time": minute_df.index[pos],
                "path": path,
                # 후보 필터링에 쓸 원본 조건값
                "day_return": close.iloc[pos] / day_slice["open"].iloc[0] - 1,
                "win_trade_value": float((close.iloc[ref:pos + 1] * volume.iloc[ref:pos + 1]).sum()),
                "win_return": close.iloc[pos] / close.iloc[ref] - 1 if close.iloc[ref] else 0.0,
                **extract_entry_features(minute_df, pos, WINDOW_MINUTES, MIN_TRADE_VALUE, daily_df, N_DAY_HIGH),
            })
    return pd.DataFrame(rows)


def apply_candidate(df: pd.DataFrame, cand: dict) -> pd.DataFrame:
    """후보 파라미터로 진입 필터링 + 청산 재평가. 스캔 재실행 없음."""
    m = (
        (df["day_return"] >= cand["day_floor"])
        & (df["day_return"] < cand["day_ceiling"])
        & (df["win_trade_value"] >= cand["min_trade_value"])
        & (df["win_return"] >= cand["min_return"])
    )
    out = df[m].copy()
    stop = cand["stop_loss_pct"]
    tiers = tuple(t * stop / STOP_LOSS_PCT for t in TIERS)
    evaluated = [evaluate_tiered_exit_from_path_with_exit_idx(p, tiers, stop) for p in out["path"]]
    out["pct"] = [e[0] for e in evaluated]
    # exit_time은 진입 이후 exit_idx분 — 분봉 인덱스를 다시 안 들고 오려는 근사.
    # ponytail: 슬롯 점유 시간 근사, 정확한 체결시각이 필요해지면 스캔에 index를 저장.
    out["exit_time"] = [t + timedelta(minutes=int(e[1])) for t, e in zip(out["entry_time"], evaluated)]
    out["stop_pct"] = stop
    return out


def evaluate(trades: pd.DataFrame, lo: date, hi: date, cand: dict) -> dict:
    """[lo, hi] 구간을 워크포워드로 돌려 OOS 성과를 낸다."""
    t = trades[trades["entry_time"].dt.date.between(lo, hi)]
    if t.empty:
        return {"n_trades": 0, "total_return_pct": 0.0, "avg_r": 0.0, "mdd_pct": 0.0}

    oos = []
    for sp in wf_split(lo, hi, 240, 60, 60):
        is_df = t[t["entry_time"].dt.date.between(sp.train_start, sp.train_end)]
        oos_df = t[t["entry_time"].dt.date.between(sp.test_start, sp.test_end)]
        if oos_df.empty:
            continue
        try:
            model = train_entry_filter_model(
                is_df[FEATURE_COLUMNS], (is_df["pct"] > 0).astype(int),
                model_type="random_forest", **MODEL_KWARGS,
            )
        except InsufficientTrainingDataError:
            continue
        proba = predict_quality_proba(model, oos_df[FEATURE_COLUMNS])
        oos.append(oos_df.loc[proba[proba >= cand["proba_threshold"]].index])

    combined = pd.concat(oos) if oos else t.iloc[0:0]
    if combined.empty:
        return {"n_trades": 0, "total_return_pct": 0.0, "avg_r": 0.0, "mdd_pct": 0.0}

    res = simulate_slot_portfolio(combined[TRADE_COLUMNS], 10_000_000, cand["max_pos"])
    taken = res.taken_trades
    if not taken:
        return {"n_trades": 0, "total_return_pct": 0.0, "avg_r": 0.0, "mdd_pct": 0.0}

    equity = peak = res.initial_capital
    mdd = 0.0
    for tr in sorted(taken, key=lambda x: x.exit_time):
        equity += tr.profit
        peak = max(peak, equity)
        mdd = max(mdd, (peak - equity) / peak) if peak > 0 else mdd
    return {
        "n_trades": len(taken),
        "total_return_pct": (res.final_capital / res.initial_capital - 1) * 100,
        # 실거래는 risk_manager가 손절폭으로 수량을 나눈다 — 총수익%가 아니라 R이 진짜 지표.
        "avg_r": float(np.mean([tr.pct / cand["stop_loss_pct"] for tr in taken])),
        "mdd_pct": mdd * 100,
    }


def gate(cand_search: dict, cand_holdout: dict, base_search: dict, base_holdout: dict) -> tuple[bool, str]:
    """후보 채택 여부. 하나라도 걸리면 기각 — 통과가 어려운 게 정상이다."""
    if cand_search["n_trades"] < MIN_TRADES:
        return False, f"탐색구간 표본부족 {cand_search['n_trades']} < {MIN_TRADES}"
    if cand_holdout["n_trades"] < MIN_TRADES // 3:
        return False, f"홀드아웃 표본부족 {cand_holdout['n_trades']}"
    if cand_search["avg_r"] < base_search["avg_r"] * EDGE_MARGIN:
        return False, f"탐색구간 R 미달 {cand_search['avg_r']:.3f} vs {base_search['avg_r']:.3f}"
    if cand_holdout["avg_r"] < base_holdout["avg_r"]:
        return False, f"홀드아웃에서 baseline에 짐 {cand_holdout['avg_r']:.3f} vs {base_holdout['avg_r']:.3f}"
    if cand_holdout["mdd_pct"] > base_holdout["mdd_pct"] * 1.5:
        return False, f"홀드아웃 MDD 악화 {cand_holdout['mdd_pct']:.1f} vs {base_holdout['mdd_pct']:.1f}"
    return True, "통과"


BASELINE = {
    "day_floor": DAY_RETURN_FLOOR, "day_ceiling": DAY_RETURN_CEILING,
    "min_trade_value": MIN_TRADE_VALUE, "min_return": MIN_RETURN_PCT,
    "stop_loss_pct": STOP_LOSS_PCT, "proba_threshold": RECOMMENDED_PROBA_THRESHOLD,
    "max_pos": RECOMMENDED_MAX_CONCURRENT_POSITIONS,
}

SEARCH_SPACE = {
    "day_floor": [0.05, 0.07, 0.09],
    "min_trade_value": [3e9, 4e9, 6e9],
    "min_return": [0.012, 0.015, 0.02],
    "stop_loss_pct": [0.025, 0.04, 0.06],
    "proba_threshold": [0.5, 0.55, 0.6],
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--limit", type=int, default=30, help="평가할 후보 수 상한")
    args = ap.parse_args()

    if args.scan or not os.path.exists(CACHE):
        print("스캔 중 (수 분 소요)...", flush=True)
        df = scan(args.data_dir)
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        df.to_pickle(CACHE)
    else:
        df = pd.read_pickle(CACHE)

    lo, hi = df["entry_time"].min().date(), df["entry_time"].max().date()
    holdout_start = hi - timedelta(days=HOLDOUT_DAYS)
    print(f"진입 {len(df)}건 | 탐색 {lo}~{holdout_start - timedelta(days=1)} | 홀드아웃 {holdout_start}~{hi}")

    base_tr = apply_candidate(df, BASELINE)
    base_s = evaluate(base_tr, lo, holdout_start - timedelta(days=1), BASELINE)
    base_h = evaluate(base_tr, holdout_start, hi, BASELINE)
    print(f"baseline  탐색 R={base_s['avg_r']:.3f} n={base_s['n_trades']} | "
          f"홀드아웃 R={base_h['avg_r']:.3f} n={base_h['n_trades']} MDD={base_h['mdd_pct']:.1f}")

    keys = list(SEARCH_SPACE)
    combos = [dict(zip(keys, v)) for v in product(*SEARCH_SPACE.values())][: args.limit]
    passed = []
    with open(JOURNAL, "a", encoding="utf-8") as jf:
        for i, override in enumerate(combos, 1):
            cand = {**BASELINE, **override}
            tr = apply_candidate(df, cand)
            s = evaluate(tr, lo, holdout_start - timedelta(days=1), cand)
            if s["n_trades"] < MIN_TRADES or s["avg_r"] < base_s["avg_r"] * EDGE_MARGIN:
                ok, why = False, "탐색구간 탈락"       # 홀드아웃은 통과 후보만 열어본다
                h = None
            else:
                h = evaluate(tr, holdout_start, hi, cand)
                ok, why = gate(s, h, base_s, base_h)
            print(f"[{i}/{len(combos)}] {'✅' if ok else '  '} {override} — {why}")
            jf.write(json.dumps({"cand": override, "search": s, "holdout": h,
                                 "passed": ok, "reason": why}, default=str) + "\n")
            if ok:
                passed.append((cand, s, h))

    print(f"\n후보 {len(combos)}개 중 {len(passed)}개 통과 (0개가 정상입니다)")
    for cand, s, h in passed:
        print(f"  {({k: cand[k] for k in SEARCH_SPACE})} 홀드아웃 R={h['avg_r']:.3f} "
              f"수익={h['total_return_pct']:.1f}% MDD={h['mdd_pct']:.1f}")
    if len(passed) > len(combos) * 0.2:
        print("\n⚠ 통과율이 20%를 넘습니다 — 게이트가 느슨하거나 홀드아웃이 오염됐는지 확인하세요.")


def _selftest() -> None:
    """gate()가 실제로 기각하는지 — 이 로직이 봇의 전부라 여기만 검사한다."""
    strong = {"n_trades": 500, "avg_r": 0.60, "mdd_pct": 5.0}
    base = {"n_trades": 500, "avg_r": 0.40, "mdd_pct": 5.0}
    weak_h = {"n_trades": 200, "avg_r": 0.35, "mdd_pct": 5.0}
    assert gate(strong, strong, base, base)[0]
    assert not gate(strong, weak_h, base, base)[0], "홀드아웃 열세를 통과시킴"
    assert not gate({**strong, "n_trades": 10}, strong, base, base)[0], "표본부족을 통과시킴"
    assert not gate({**strong, "avg_r": 0.41}, strong, base, base)[0], "마진 미달을 통과시킴"
    assert not gate(strong, {**strong, "mdd_pct": 20.0}, base, base)[0], "MDD 악화를 통과시킴"
    print("selftest ok")


if __name__ == "__main__":
    import sys
    _selftest() if "--selftest" in sys.argv else main()
