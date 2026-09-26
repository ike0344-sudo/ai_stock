"""최적화·워크포워드·홀드아웃 유스케이스 — 설계서 §3.8, 계획서 BT-10~12.

    run_optimize(spec, market_data, config, progress, ...)       그리드 → IS 로만 선택 → OOS 는 확인용 → grid.parquet
    run_walkforward(spec, market_data, config, progress, ...)    폴드마다 학습에서 선택 → 검증 구간만 이은 곡선 → folds.json
    run_holdout_check(spec, overrides, market_data, ledger, ...) 마지막 N% 거래일을 **한 번씩만** 연다(장부 기록·재열람 경고)

원칙(검증의 핵심이라 코드 구조로 강제한다)
  · 최적화 구간(홀드아웃 제외)의 데이터만 패널에 올린다 — 조합을 돌릴 때 홀드아웃 봉은 메모리에도 없다(`restrict_context`).
  · 후보 선택은 IS 점수만 받는 `validation.select_best` 로 한다.
  · 조합마다 최적화 구간을 **한 번** 돌리고 평가금 곡선을 IS/OOS/폴드로 자른다(구간 경계 보유는 이어짐).
병렬: `workers > 1` 이면 프로세스 풀(워커마다 패널을 한 번 만들어 재사용). 워커 수는 정책 함수가 정해 넘긴다
(소피증권 가동 시간 cpu//4, 야간 cpu//2 — `datahub.policy.cpu_workers`). 워커 프로세스의 의존은 `bootstrap`
("모듈:함수" 문자열)로 만든다 — 응용 계층은 infrastructure 를 import 하지 못해서 이름으로만 부른다(§9.3).
"""
from __future__ import annotations

import concurrent.futures as cf
import importlib
import multiprocessing
import time
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from studio.domain.metrics import collapse_entries, equity_stats, trade_stats
from studio.domain.spec import Period, Spec
from studio.domain.validation import (
    OBJECTIVE_KEY, WARN_COMBOS, OptimizeConfig, TradeArrays, ValidationConfigError, WalkForwardConfig,
    combinations, evaluate_criteria, grid_axes, neighbor_stability, objective_value, params_drift, select_best,
    split_days, stitch_equity, walk_forward_efficiency, walkforward_folds, window_metrics,
)

from .backtest_service import (
    BacktestError, RunContext, _jsonable, family_hash, prepare_context, restrict_context, run_backtest,
    structure_hash,
)
from .ports import HoldoutLedger, LegacyStrategies, MarketData, RunRecord, TradingCalendar

Progress = Callable[[str, float], None]
_TRADE_COLS = ["code", "entry_ts", "exit_ts", "entry_price", "qty", "gross_pnl", "commission", "tax", "slippage_cost",
               "net_pnl", "net_pct", "bars_held", "exit_reason", "mfe_pct", "mae_pct", "entry_id", "slice"]
MIN_FOLDS_WARN = 3
MIN_IS_DAYS_WARN = 120


# --------------------------------------------------------------------------- 조합 실행


@dataclass
class ComboRun:
    overrides: dict
    error: str | None = None
    ts: pd.DatetimeIndex | None = None
    equity: np.ndarray | None = None
    trades: pd.DataFrame | None = None  # 청산된 거래만, _TRADE_COLS


def _eval_one(spec: Spec, overrides: Mapping[str, float], md: MarketData, legacy: LegacyStrategies | None,
              ctx: RunContext) -> ComboRun:
    try:
        rec = run_backtest(spec, md, None, legacy=legacy, overrides=overrides, context=ctx)
    except ValueError as e:  # 변수 값이 Spec·기존 전략 검증을 못 넘는 조합(예: short >= long) — 무효로 표시하고 계속
        return ComboRun(dict(overrides), error=str(e).splitlines()[0][:200])
    t = rec.trades
    # 분할 청산 조각은 진입 한 건으로 합친다(collapse_entries) — 구간 승률·기대값·MC 가 조각이 아니라 진입 기준이 되게
    t = collapse_entries(t[t["net_pnl"].notna()][_TRADE_COLS].reset_index(drop=True)) if len(t) else pd.DataFrame(columns=_TRADE_COLS)
    return ComboRun(dict(overrides), ts=pd.DatetimeIndex(rec.equity["ts"]), equity=rec.equity["equity"].to_numpy(float),
                    trades=t)


_WORKER: dict[str, Any] = {}


def _pool_init(bootstrap: str, spec_json: str) -> None:
    """워커 프로세스 시작 시 1회 — 의존을 만들고 패널을 올린다. 우선순위를 낮춘다(소피증권 실시간 CPU 보호)."""
    mod_name, fn = bootstrap.split(":")
    mod = importlib.import_module(mod_name)
    deps = getattr(mod, fn)()
    lower = getattr(mod, "lower_priority", None)
    if lower:
        lower()
    spec = Spec.model_validate_json(spec_json)
    _WORKER.update(spec=spec, deps=deps, ctx=prepare_context(spec, deps.market_data))


def _pool_eval(overrides: dict) -> ComboRun:
    w = _WORKER
    return _eval_one(w["spec"], overrides, w["deps"].market_data, w["deps"].legacy, w["ctx"])


def run_combos(spec: Spec, combos: Sequence[dict], md: MarketData, legacy: LegacyStrategies | None, ctx: RunContext,
               progress: Progress, *, workers: int = 1, bootstrap: str | None = None,
               lo: float = 0.05, hi: float = 0.9) -> list[ComboRun]:
    """조합을 전부 돌려 입력 순서대로 돌려준다. 진행 콜백이 예외를 던지면(취소) 남은 조합을 취소하고 그대로 전파."""
    n = len(combos)
    out: list[ComboRun | None] = [None] * n
    tick = lambda done: progress("grid", lo + (hi - lo) * done / max(1, n))  # noqa: E731
    if workers > 1 and bootstrap and n > 1:
        pool = cf.ProcessPoolExecutor(max_workers=min(workers, n), mp_context=multiprocessing.get_context("spawn"),
                                      initializer=_pool_init, initargs=(bootstrap, spec.model_dump_json()))
        try:
            futs = {pool.submit(_pool_eval, dict(c)): i for i, c in enumerate(combos)}
            for k, f in enumerate(cf.as_completed(futs), 1):
                out[futs[f]] = f.result()
                tick(k)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    else:
        for i, c in enumerate(combos):
            out[i] = _eval_one(spec, c, md, legacy, ctx)
            tick(i + 1)
    return out  # type: ignore[return-value]


# --------------------------------------------------------------------------- 병렬 메모리 상한

# 실측(2026-09-26, 골든크로스 top100 최적화 구간 패널 3.77M 셀): 워커 시작(패널 로드·피벗) 피크 RSS 1,246MB = 셀당 331B,
# 정착 754MB = 셀당 200B, memo 지표 표 하나 ≈ 셀×8B(30MB)의 1.0~1.5배, 조합 실행 임시 ≈ 수백MB.
# 워커들이 동시에 시작하면 피크가 겹치므로 **피크**로 잡는다. 변수 하나가 훑는 값마다 SMA 등 지표 표가 하나씩 생긴다(memo 상한 64).
PEAK_BYTES_PER_CELL = 331
MEMO_TABLE_FACTOR = 1.3
WORKER_FIXED_BYTES = 300 * 1024 ** 2
MEMO_MAX_TABLES = 64
BASE_TABLES = 4


def estimate_worker_bytes(panel_cells: int, axes: Mapping[str, Sequence]) -> int:
    """워커 프로세스 하나가 그리드 동안 쓸 최대 메모리 추정(바이트) — 패널 피크 + memo 표(훑는 값 수 합, 상한 64) + 고정 여유."""
    tables = min(MEMO_MAX_TABLES, BASE_TABLES + sum(len(v) for v in axes.values() if len(v) > 1))
    return int(panel_cells * PEAK_BYTES_PER_CELL + tables * panel_cells * 8 * MEMO_TABLE_FACTOR + WORKER_FIXED_BYTES)


def _cap_workers(workers: int, memory_limit: Callable[[int], int] | None, per_worker: int, warnings: list[str]) -> int:
    """정책 워커 수를 메모리 여유로 더 줄인다. memory_limit(워커당 바이트) → 메모리가 허락하는 최대 워커 수(최소 1)."""
    if workers <= 1 or memory_limit is None:
        return workers
    allowed = max(1, int(memory_limit(per_worker)))
    if allowed >= workers:
        return workers
    if allowed == 1:
        warnings.append(f"메모리 부족으로 직렬 실행(요청 워커 {workers}개, 워커당 추정 {per_worker / 1024 ** 3:.1f}GB) — 다른 프로그램을 위한 예비 메모리를 남기려는 상한")
    else:
        warnings.append(f"메모리 여유로 워커 {workers}개 → {allowed}개로 줄였다(워커당 추정 {per_worker / 1024 ** 3:.1f}GB)")
    return allowed


# --------------------------------------------------------------------------- 분할 도우미


def _days(ctx: RunContext, spec: Spec, calendar: TradingCalendar | None) -> list[date]:
    if calendar is not None:  # 달력에 있어도 일봉이 아직 없는 미래·수집 전 날짜는 뺀다(홀드아웃이 빈 날로 채워지지 않게)
        last = ctx.panel.close.index[-1].date()
        return [d for d in calendar.trading_days(spec.period.start, spec.period.end) if d <= last]
    return [t.date() for t in ctx.panel.close.index[ctx.in_period]]


def _pos(ts: pd.DatetimeIndex, d0: date, d1: date) -> tuple[int, int]:
    """날짜 구간 → 봉 위치 [i0, i1](양끝 포함). 구간 안에 봉이 없으면 ValidationConfigError."""
    i0 = int(ts.searchsorted(pd.Timestamp(d0), side="left"))
    i1 = int(ts.searchsorted(pd.Timestamp(d1), side="right")) - 1
    if i0 > i1 or i1 < 0 or i0 >= len(ts):
        raise ValidationConfigError(f"{d0}~{d1} 안에 일봉 거래일이 없다")
    return i0, i1


def _trade_arrays(run: ComboRun) -> TradeArrays:
    t = run.trades
    if t is None or t.empty:
        return TradeArrays(np.array([], int), np.array([]), np.array([]))
    ex = run.ts.searchsorted(pd.DatetimeIndex(t["exit_ts"]), side="left")
    order = np.argsort(ex, kind="stable")
    return TradeArrays(ex[order].astype(int), t["net_pnl"].to_numpy(float)[order], t["net_pct"].to_numpy(float)[order])


def _opt_spec(spec: Spec, days_opt: Sequence[date]) -> Spec:
    return spec.model_copy(update={"period": Period(start=spec.period.start, end=days_opt[-1])})


def _base_setup(spec: Spec, md: MarketData, calendar: TradingCalendar | None, cfg: OptimizeConfig,
                progress: Progress, need_grid: bool = True):
    if spec.mode not in ("daily_single", "daily_portfolio"):
        raise ValidationConfigError("최적화는 일봉 모드(daily_single·daily_portfolio)만 지원한다")
    if need_grid and not spec.params:
        raise ValidationConfigError("변수({\"param\": ...})가 하나도 없어 최적화할 게 없다")
    progress("prepare", 0.01)
    full_ctx = prepare_context(spec, md, progress)
    days = _days(full_ctx, spec, calendar)
    return full_ctx, days


def _grid(spec: Spec, cfg: OptimizeConfig):
    axes = grid_axes(spec.params, cfg.vary)
    combos, idx = combinations(axes, min(cfg.max_combos, 5000))
    if len(combos) < 2:
        raise ValidationConfigError("훑을 조합이 1개뿐이다 — 변수에 min·max·step 을 모두 지정해야 한다")
    return axes, combos, idx


def _finite(x: float | None) -> float | None:
    return None if x is None or not np.isfinite(x) else float(x)


def _seg_cols(prefix: str, m: dict | None, objective: str) -> dict:
    if m is None:
        return {f"{prefix}_{objective}": np.nan, f"{prefix}_trades": 0, f"{prefix}_return_pct": np.nan,
                f"{prefix}_mdd_pct": np.nan}
    return {f"{prefix}_{objective}": m[OBJECTIVE_KEY[objective]], f"{prefix}_trades": m["num_trades"],
            f"{prefix}_return_pct": m["total_return_pct"], f"{prefix}_mdd_pct": m["max_drawdown_pct"]}


def _run_grid(spec, cfg, md, legacy, calendar, progress, workers, bootstrap, memory_limit=None):
    """공통: 준비 → 분할 → 조합 실행. (opt_spec, ctx_opt, segs, days, axes, combos, idx, runs, ts, warnings) 를 돌려준다."""
    full_ctx, days = _base_setup(spec, md, calendar, cfg, progress)
    axes, combos, idx = _grid(spec, cfg)
    segs = split_days(days, cfg.holdout_pct, cfg.train_pct, cfg.split_date)
    opt_spec = _opt_spec(spec, segs.opt_days)
    ctx_opt = restrict_context(full_ctx, opt_spec)  # 홀드아웃 봉을 패널에서 자른다 — 이후 어떤 조합도 못 본다
    warnings = list(full_ctx.warnings)
    if len(combos) > WARN_COMBOS:
        warnings.append(f"조합 {len(combos):,}개 — {WARN_COMBOS} 개를 넘으면 다중검정으로 우연히 좋아 보이는 조합이 나온다(과최적화 위험)")
    if segs.holdout_days:
        warnings.append(f"홀드아웃 {segs.holdout_days[0]}~{segs.holdout_days[-1]}({len(segs.holdout_days)}거래일)는 "
                        "최적화·선택·OOS 어디에도 쓰지 않았다 — holdout_check 로만 연다")
    else:
        warnings.append("홀드아웃 0% — 최적화에 안 쓴 데이터가 없다(최종 검증을 할 수 없음)")
    workers = _cap_workers(workers, memory_limit, estimate_worker_bytes(ctx_opt.panel.close.size, axes), warnings)
    runs = run_combos(opt_spec, combos, md, legacy, ctx_opt, progress, workers=workers, bootstrap=bootstrap)
    ok = [r for r in runs if r.error is None]
    if not ok:
        errs = sorted({r.error for r in runs if r.error})[:3]
        raise ValidationConfigError(f"모든 조합이 무효다: {errs}")
    bad = len(runs) - len(ok)
    if bad:
        errs = sorted({r.error for r in runs if r.error})[:3]
        warnings.append(f"무효 조합 {bad}개(예: {errs}) — 표에는 status 로 남겼고 선택에서 제외했다")
    return opt_spec, ctx_opt, segs, days, axes, combos, idx, runs, ok[0].ts, warnings, workers


# --------------------------------------------------------------------------- 최적화 (IS 선택 → OOS 확인)


def run_optimize(spec: Spec, market_data: MarketData, config: OptimizeConfig | None = None,
                 progress: Progress | None = None, *, legacy: LegacyStrategies | None = None,
                 calendar: TradingCalendar | None = None, workers: int = 1,
                 bootstrap: str | None = None, memory_limit: Callable[[int], int] | None = None) -> RunRecord:
    t0 = time.perf_counter()
    progress = progress or (lambda s, f: None)
    cfg = config or OptimizeConfig.from_validation(spec.validation)
    opt_spec, ctx, segs, days, axes, combos, idx, runs, ts, warnings, workers = _run_grid(
        spec, cfg, market_data, legacy, calendar, progress, workers, bootstrap, memory_limit)
    cap = float(spec.portfolio.initial_capital)
    is_pos = _pos(ts, segs.is_days[0], segs.is_days[-1])
    oos_pos = _pos(ts, segs.oos_days[0], segs.oos_days[-1])
    if len(segs.is_days) < MIN_IS_DAYS_WARN:
        warnings.append(f"IS 가 {len(segs.is_days)}거래일뿐이다(<{MIN_IS_DAYS_WARN}) — 선택이 우연에 크게 좌우된다")

    progress("select", 0.92)
    n = len(runs)
    m_is: list[dict | None] = [None] * n
    m_oos: list[dict | None] = [None] * n
    is_vals: list[float | None] = [None] * n
    for i, r in enumerate(runs):
        if r.error is not None:
            continue
        tr = _trade_arrays(r)
        m_is[i] = window_metrics(r.equity, *is_pos, cap, tr)
        m_oos[i] = window_metrics(r.equity, *oos_pos, cap, tr)
        is_vals[i] = objective_value(m_is[i], cfg.objective, cfg.min_trades)
    best = select_best(is_vals)  # ← IS 값만 받는다. OOS 는 여기서 보이지도 않는다
    if best is None:
        raise ValidationConfigError(f"IS 에서 거래 {cfg.min_trades}건 이상인 조합이 하나도 없다 — 기간·변수 범위·최소 거래 수를 확인")

    # 표 (되는 것만 남기지 않는다 — 전 조합, 무효·거래 부족 포함)
    order = sorted((v for v in is_vals if v is not None), reverse=True)
    rows = []
    for i, (c, r) in enumerate(zip(combos, runs)):
        status = f"invalid: {r.error}" if r.error else ("few_trades" if is_vals[i] is None else "ok")
        rows.append({**c, "status": status, **_seg_cols("is", m_is[i], cfg.objective),
                     **_seg_cols("oos", m_oos[i], cfg.objective),
                     "rank_is": (order.index(is_vals[i]) + 1) if is_vals[i] is not None else np.nan,
                     "selected": i == best})
    grid_df = pd.DataFrame(rows)

    stab = neighbor_stability(idx, is_vals, best)
    if stab["warn"]:
        warnings.append(f"이웃 안정성: {stab['reason']}")
    b_is, b_oos = m_is[best], m_oos[best]
    key = OBJECTIVE_KEY[cfg.objective]
    oos_v = b_oos[key]
    warnings += _overfit_warnings(cfg, b_is, b_oos, is_vals[best], oos_v, key)
    criteria = evaluate_criteria(cfg.criteria, b_oos) if cfg.criteria else []

    progress("final", 0.95)
    rec = run_backtest(opt_spec, market_data, None, legacy=legacy, overrides=combos[best], context=ctx)
    rec.spec = spec  # 저장하는 명세는 변수 범위가 살아 있는 원본(재실행·워크포워드에 필요)
    rec.grid = grid_df
    rec.warnings = warnings + [w for w in rec.warnings if w not in warnings]
    rec.summary["warnings"] = rec.warnings
    rec.summary["optimize"] = _jsonable({
        "objective": cfg.objective, "min_trades": cfg.min_trades, "n_combos": n,
        "n_valid": sum(v is not None for v in is_vals), "n_invalid": sum(r.error is not None for r in runs),
        "segments": {"is": [str(segs.is_days[0]), str(segs.is_days[-1]), len(segs.is_days)],
                     "oos": [str(segs.oos_days[0]), str(segs.oos_days[-1]), len(segs.oos_days)],
                     "holdout": ([str(segs.holdout_days[0]), str(segs.holdout_days[-1]), len(segs.holdout_days)]
                                 if segs.holdout_days else None)},
        "selected": {"params": combos[best], "is": b_is, "oos": b_oos, "is_objective": is_vals[best],
                     "oos_objective": oos_v, "selected_by": "IS 목표값만 사용"},
        "neighbor_stability": stab, "criteria_on_oos": criteria,
        "selection_note": "조합마다 최적화 구간 전체를 1회 실행해 곡선을 IS/OOS 로 잘랐다(경계에 걸친 보유는 이어짐)",
    })
    rec.meta.update(_jsonable({"kind": "optimize", "params": combos[best], "holdout_used": False,
                               "n_combos": n, "workers": workers, "warnings": rec.warnings,
                               "elapsed_sec": round(time.perf_counter() - t0, 3)}))
    progress("done", 1.0)
    return rec


def _overfit_warnings(cfg: OptimizeConfig, m_is: dict, m_oos: dict, is_v: float, oos_v: float, key: str) -> list[str]:
    w = []
    if m_oos["num_trades"] < cfg.min_trades:
        w.append(f"OOS 거래가 {m_oos['num_trades']}건(<{cfg.min_trades}) — OOS 점수는 통계적 의미가 없다")
    if oos_v is None or not np.isfinite(oos_v) or oos_v <= 0:
        w.append(f"OOS {key} 가 {oos_v} — IS 에서 고른 조합이 OOS 에서 이익을 못 냈다(과최적화 의심)")
    elif is_v and oos_v < 0.5 * is_v:
        w.append(f"OOS {key}({oos_v:.3g}) 가 IS({is_v:.3g}) 의 절반 미만 — 과최적화 의심")
    return w


# --------------------------------------------------------------------------- 워크포워드


def run_walkforward(spec: Spec, market_data: MarketData, config: WalkForwardConfig,
                    progress: Progress | None = None, *, legacy: LegacyStrategies | None = None,
                    calendar: TradingCalendar | None = None, workers: int = 1,
                    bootstrap: str | None = None, memory_limit: Callable[[int], int] | None = None) -> RunRecord:
    t0 = time.perf_counter()
    progress = progress or (lambda s, f: None)
    cfg = config.base
    opt_spec, ctx, segs, days, axes, combos, idx, runs, ts, warnings, workers = _run_grid(
        spec, cfg, market_data, legacy, calendar, progress, workers, bootstrap, memory_limit)
    cap = float(spec.portfolio.initial_capital)
    opt_days = segs.opt_days
    folds = walkforward_folds(len(opt_days), config.train_days, config.test_days, config.step, config.mode)
    if len(folds) < MIN_FOLDS_WARN:
        warnings.append(f"폴드가 {len(folds)}개뿐이다(<{MIN_FOLDS_WARN}) — 검증 구간 성과가 한두 구간에 좌우된다")

    progress("select", 0.92)
    ok_idx = [i for i, r in enumerate(runs) if r.error is None]
    arrays = {i: _trade_arrays(runs[i]) for i in ok_idx}
    key = OBJECTIVE_KEY[cfg.objective]
    fold_out: list[dict] = []
    windows: list[tuple[np.ndarray, int, int]] = []
    test_trades: list[pd.DataFrame] = []
    chosen_count = np.zeros(len(runs), int)
    skipped_folds = 0
    for f in folds:
        tr0, tr1 = _pos(ts, opt_days[f.train[0]], opt_days[f.train[1]])
        te0, te1 = _pos(ts, opt_days[f.test[0]], opt_days[f.test[1]])
        is_vals: list[float | None] = [None] * len(runs)
        for i in ok_idx:
            is_vals[i] = objective_value(window_metrics(runs[i].equity, tr0, tr1, cap, arrays[i]),
                                         cfg.objective, cfg.min_trades)
        b = select_best(is_vals)
        rec_f: dict[str, Any] = {"fold": f.index, "train": [str(opt_days[f.train[0]]), str(opt_days[f.train[1]])],
                                 "test": [str(opt_days[f.test[0]]), str(opt_days[f.test[1]])]}
        if b is None:  # 그 학습 구간엔 최소 거래 이상인 조합이 없다 — 이 폴드는 검증 없이 건너뜀(표에 남김)
            skipped_folds += 1
            fold_out.append({**rec_f, "skipped": f"학습 구간에서 거래 {cfg.min_trades}건 이상인 조합 없음"})
            continue
        chosen_count[b] += 1
        m_tr = window_metrics(runs[b].equity, tr0, tr1, cap, arrays[b])
        m_te = window_metrics(runs[b].equity, te0, te1, cap, arrays[b])
        fold_out.append({**rec_f, "params": combos[b], "is": m_tr, "oos": m_te, "is_objective": is_vals[b],
                         "oos_objective": m_te[key]})
        windows.append((runs[b].equity, te0, te1))
        t = runs[b].trades
        sel = (pd.DatetimeIndex(t["exit_ts"]) >= ts[te0]) & (pd.DatetimeIndex(t["exit_ts"]) <= ts[te1])
        test_trades.append(t[sel].assign(fold=f.index))
    if not windows:
        raise ValidationConfigError("검증할 수 있는 폴드가 하나도 없다(모든 학습 구간에서 최소 거래 미달)")
    if skipped_folds:
        warnings.append(f"학습 구간 거래 부족으로 건너뛴 폴드 {skipped_folds}개")

    stitched = stitch_equity(windows, cap)
    tt = pd.concat(test_trades, ignore_index=True) if test_trades else pd.DataFrame(columns=_TRADE_COLS + ["fold"])
    tt = tt.sort_values("exit_ts", kind="stable").reset_index(drop=True)
    oos_m = equity_stats(stitched, cap) | trade_stats(tt["net_pnl"].to_numpy(float), tt["net_pct"].to_numpy(float))
    done = [f for f in fold_out if "oos" in f]
    wfe = walk_forward_efficiency([f["is"]["cagr_pct"] for f in done], oos_m["cagr_pct"])
    if wfe is None:
        warnings.append("WFE 계산 불가 — 폴드별 IS 연환산 수익률 평균이 0 이하")
    elif wfe < 0.5:
        warnings.append(f"WFE {wfe:.2f} (<0.5) — 검증 구간 수익이 학습 구간의 절반에 못 미친다(과최적화 의심)")
    pos_folds = sum(1 for f in done if f["oos"]["total_return_pct"] > 0)
    if oos_m["num_trades"] < cfg.min_trades:
        warnings.append(f"검증 구간 거래 합계 {oos_m['num_trades']}건(<{cfg.min_trades}) — 통계적 의미가 약하다")
    drift = params_drift([f["params"] for f in done])
    criteria = evaluate_criteria(cfg.criteria, oos_m) if cfg.criteria else []

    # 기록: 이은 검증 곡선 + 검증 구간 거래
    stitched_ts = np.concatenate([ts[i0: i1 + 1] for _, i0, i1 in windows])
    peak = np.maximum.accumulate(np.maximum(stitched, cap))
    eq_df = pd.DataFrame({"ts": stitched_ts, "cash": np.nan, "positions_value": np.nan, "equity": stitched,
                          "n_positions": np.nan, "drawdown_pct": (stitched / peak - 1) * 100})
    info = market_data.stock_info()
    tt["name"] = tt["code"].map(info["name"]) if "name" in info.columns else None
    tt["sector"] = tt["code"].map(info["sector"]) if "sector" in info.columns else None
    grid_df = pd.DataFrame([{**c, "status": (f"invalid: {r.error}" if r.error else "ok"),
                             "chosen_folds": int(chosen_count[i])}
                            | (_seg_cols("full", window_metrics(r.equity, 0, len(ts) - 1, cap, arrays[i]), cfg.objective)
                               if r.error is None else {})
                            for i, (c, r) in enumerate(zip(combos, runs))])
    progress("final", 0.97)
    rec = RunRecord(spec=spec, meta={}, summary={}, trades=tt, equity=eq_df, grid=grid_df, warnings=warnings)
    rec.folds = _jsonable({"config": {"train_days": config.train_days, "test_days": config.test_days,
                                       "step_days": config.step, "mode": config.mode},
                           "folds": fold_out})
    rec.summary = _jsonable({
        "metrics": oos_m, "n_trades": len(tt), "n_closed": len(tt), "warnings": warnings,
        "criteria": criteria,
        "walkforward": {"objective": cfg.objective, "min_trades": cfg.min_trades, "n_folds": len(folds),
                        "n_validated": len(done), "positive_folds": pos_folds, "wfe": wfe,
                        "oos_metrics": oos_m, "params_drift": drift, "n_combos": len(runs),
                        "holdout": ([str(segs.holdout_days[0]), str(segs.holdout_days[-1])] if segs.holdout_days else None),
                        "note": "검증 구간만 이은 곡선(학습 구간은 건너뜀). 조합마다 최적화 구간 전체를 1회 실행해 잘랐다."},
    })
    rec.meta = _jsonable({"kind": "walkforward", "mode": opt_spec.mode, "warnings": warnings, "holdout_used": False,
                          "n_combos": len(runs), "workers": workers, "spec_hash": None,
                          "structure_hash": structure_hash(spec), "elapsed_sec": round(time.perf_counter() - t0, 3)})
    progress("done", 1.0)
    return rec


# --------------------------------------------------------------------------- 홀드아웃 열기


def run_holdout_check(spec: Spec, overrides: Mapping[str, float] | None, market_data: MarketData,
                      ledger: HoldoutLedger, config: OptimizeConfig | None = None,
                      progress: Progress | None = None, *, legacy: LegacyStrategies | None = None,
                      calendar: TradingCalendar | None = None, source_run_id: str | None = None,
                      run_id: str | None = None) -> RunRecord:
    """고른 변수로 홀드아웃 구간(마지막 N% 거래일)을 실행한다. 여는 즉시 장부에 남기고, 같은 구조를 다시 열면 경고한다
    (막지는 않는다). 홀드아웃은 '한 번만 보는 시험지' — 결과를 보고 조건을 고쳐 다시 열면 더는 시험지가 아니다."""
    t0 = time.perf_counter()
    progress = progress or (lambda s, f: None)
    cfg = config or OptimizeConfig.from_validation(spec.validation)
    if spec.mode not in ("daily_single", "daily_portfolio"):
        raise ValidationConfigError("홀드아웃 열기는 일봉 모드만 지원한다")
    full_ctx, days = _base_setup(spec, market_data, calendar, cfg, progress, need_grid=False)
    segs = split_days(days, cfg.holdout_pct, cfg.train_pct, cfg.split_date) if cfg.holdout_pct > 0 else None
    if segs is None or not segs.holdout_days:
        raise ValidationConfigError("홀드아웃 구간이 없다(holdout_pct 가 0 이거나 거래일이 너무 적다)")
    h0, h1 = segs.holdout_days[0], segs.holdout_days[-1]
    hold_spec = spec.model_copy(update={"period": Period(start=h0, end=h1)})
    ctx = restrict_context(full_ctx, hold_spec)
    progress("run", 0.5)
    rec = run_backtest(hold_spec, market_data, None, legacy=legacy, overrides=overrides, context=ctx)
    rec.spec = spec

    sh, fh = structure_hash(spec), family_hash(spec)
    open_id = uuid.uuid4().hex
    entry = {"opened_at": pd.Timestamp.now().isoformat(timespec="seconds"), "open_id": open_id, "run_id": run_id,
             "family_hash": fh, "structure_hash": sh, "period": [str(h0), str(h1)], "params": dict(overrides or {}),
             "source_run_id": source_run_id}
    nth_struct = ledger.record_open(sh, entry)
    # 열람 횟수는 골격(family_hash) 기준으로 센다 — 리터럴·청산 규칙 on/off 를 고쳐 횟수를 초기화하는 길을 막는다(lead 판정)
    fam = sorted(ledger.family_history(fh), key=lambda e: e.get("opened_at", ""))
    nth = len(fam)
    prev = [e for e in fam if e.get("open_id") != open_id]
    warnings = list(rec.warnings)
    if nth >= 2:
        warnings.append(
            f"홀드아웃을 {nth}번째 열었다 — 같은 전략 골격(조건식 숫자·손절 등 청산 규칙 값·켜고 끔만 다른 것 포함)의 이전 열람 {nth - 1}회"
            f"({', '.join(e['opened_at'][:16] for e in prev[-3:])}). 결과를 보고 고쳐 다시 여는 것은 엿보기다"
            f"(구조 해시 기준으로는 {nth_struct}번째).")
    rec.warnings = warnings
    rec.summary["warnings"] = warnings
    rec.summary["holdout"] = _jsonable({
        "period": [str(h0), str(h1), len(segs.holdout_days)], "nth_open": nth, "nth_open_structure": nth_struct,
        "previous_opens": prev, "params": dict(overrides or {}), "source_run_id": source_run_id,
        "structure_hash": sh, "family_hash": fh,
        "note": "열람 횟수는 골격 해시 기준. 이 구간은 최적화·선택에 쓰이지 않았다. 사전 판정 기준(criteria)은 이 구간 전체 지표로 판정했다."})
    rec.meta.update(_jsonable({"kind": "holdout_check", "holdout_open_count": nth, "params": dict(overrides or {}),
                               "warnings": warnings, "structure_hash": sh, "family_hash": fh,
                               "elapsed_sec": round(time.perf_counter() - t0, 3)}))
    progress("done", 1.0)
    return rec


def count_grid(spec: Spec, vary: Sequence[str] | None = None) -> int:
    """화면이 '조합 수' 를 미리 보여주고 5,000 초과를 비활성으로 만드는 데 쓴다(조합을 만들지 않고 센다)."""
    from studio.domain.validation import count_combinations
    return count_combinations(spec.params, vary)


__all__ = ["run_optimize", "run_walkforward", "run_holdout_check", "count_grid", "ComboRun", "run_combos", "estimate_worker_bytes",
           "BacktestError", "ValidationConfigError", "OptimizeConfig", "WalkForwardConfig"]
