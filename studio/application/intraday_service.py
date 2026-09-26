"""분봉·틱 백테스트 유스케이스 — 설계서 §2.2(e), §3.5 7번, §3.7 시점 규칙, module-6.

  run_intraday(spec, md, ...)   mode="intraday"      2단계: 일봉 D−1 사전 필터(거래대금 상위 N + 조건) → 분봉 신호 → 일봉 엔진 + 세션 규칙
                                mode="tick", entry_source="minute_refine"   같은 분봉 실행 + **틱 정밀화**(모드 A, SC-7)
  run_tick(spec, md, ...)       mode="tick", entry_source="catalog"          틱 조건 진입 시뮬레이션(모드 B)

시점 규칙(look-ahead 차단): 분봉 신호는 봉 t 까지, 일봉 피연산자·순위는 **D−1**(`previous_day_flags`), 진입은 신호 봉 **다음 봉 시가**
(같은 날 안에서만), 틱 진입은 신호 초 s 보다 **엄격히 뒤** 체결. 지표는 날 경계를 넘어 굴러간다(lead 결정 2026-09-26 — 기존 분봉 전략·차트와 같게).
데이터: 통합(AL) 분봉 보관소·체결. 분봉·체결은 종목마다 기간이 다르고 짧다 — 실제로 쓴 (날짜,종목) 쌍을 기대 쌍과 함께 결과에 남긴다.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import time
from typing import Mapping

import numpy as np
import pandas as pd

from studio.domain.conditions.evaluator import evaluate, evaluate_group
from studio.domain.conditions.indicators import compute
from studio.domain.conditions.prefilter import previous_day_flags
from studio.domain.conditions.tick import detect_from_spec, is_gap_open_day, prior_n_high
from studio.domain.engine.intraday import bar_sessions
from studio.domain.engine.portfolio import run_portfolio
from studio.domain.engine.tick import (
    Candidate, TickRules, hms_to_sec, refine_entry, refine_exit, repriced_net, simulate_tick_days,
)
from studio.domain.models import ExitReason
from studio.domain.spec import BuilderStrategy, Intraday, Spec, bind_params, validate_against

from .backtest_service import (
    WARMUP_BARS, BacktestError, Progress, _slice, assemble_record, eligible_codes, to_engine_rules,
)
from .ports import MarketData, RunRecord

MIN_INTRADAY_DAYS = 60  # 설계서 §8.9 기준 — 이보다 짧으면 "분봉 짧은 표본" 경고
MAX_WARM_BARS = 500  # 지표 기간 상한(카탈로그 N_MAX)


def _check_spec(bound: Spec, ranges: dict) -> list[str]:
    problems = validate_against(bound, ranges)
    errors = [p.message for p in problems if p.severity == "error"]
    if errors:
        raise BacktestError("; ".join(errors))
    return [p.message for p in problems if p.severity == "warning"]


def _daily_frame(bound: Spec, md: MarketData, info: pd.DataFrame, warmup: int, available: list[str] | None = None):
    """유니버스 규칙을 통과한 종목의 일봉 패널(사전 필터·D−1 순위·prev_close 재료)."""
    want = list(bound.universe.codes) if bound.universe.type == "codes" else None
    full = md.load_panel(bound.period.start, bound.period.end, warmup, want)
    avail = list(full.close.columns) if available is None else [c for c in full.close.columns if c in set(available)]
    codes, ustats = eligible_codes(bound, info, md.mega_cap_codes(), avail)
    if not codes:
        raise BacktestError("유니버스에 종목이 없다 (조건·제외 규칙 확인)")
    return _slice(full, np.ones(len(full.close), dtype=bool), codes), codes, ustats


def _period_rows(index: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp) -> tuple[int, int]:
    """일봉 index 에서 기간 [start, end] 의 위치 [p0, p1)."""
    return int(index.searchsorted(start, side="left")), int(index.searchsorted(end, side="right"))


# =========================================================================== 분봉 (+ 모드 A 정밀화)


def run_intraday(spec: Spec, md: MarketData, progress: Progress | None = None, *, legacy=None,
                 overrides: Mapping[str, float] | None = None) -> RunRecord:
    t_start = time.perf_counter()
    tick = progress or (lambda stage, frac: None)
    bound = bind_params(spec, overrides)
    refine = bound.mode == "tick"
    if refine and (bound.tick is None or bound.tick.entry_source != "minute_refine"):
        raise BacktestError("run_intraday 는 mode='intraday' 또는 tick.entry_source='minute_refine' 만 처리한다")
    strat = bound.strategy
    if not isinstance(strat, BuilderStrategy):
        raise BacktestError("분봉 모드는 조건 조립기 전략만 지원한다(기존 전략 8종은 일봉 전용)")
    cfg = bound.intraday or Intraday()
    ranges = md.data_ranges()
    warnings = _check_spec(bound, ranges)
    start, end = pd.Timestamp(bound.period.start), pd.Timestamp(bound.period.end)

    # ---- 1단계: 일봉 D−1 사전 필터 → 이 기간에 한 번이라도 통과한 종목만 분봉을 읽는다
    tick("load", 0.03)
    info = md.stock_info()
    daily, dcodes, ustats = _daily_frame(bound, md, info, WARMUP_BARS)
    flags = compute(daily, "value_rank", {"lookback": 1}) <= cfg.prefilter_top_value
    if cfg.prefilter is not None:
        flags = flags & evaluate_group(cfg.prefilter, daily, market=md.index_frames())
    flags = flags.fillna(False).astype(bool)
    didx = daily.close.index
    p0, p1 = _period_rows(didx, start, end)
    if p1 <= p0:
        raise BacktestError("기간 안에 일봉 거래일이 없다")
    rows = flags.iloc[max(p0 - 1, 0): max(p1 - 1, 1)]  # 날짜 D 에는 D−1 행의 값을 쓴다
    union = [c for c in rows.columns if rows[c].any()]
    if not union:
        raise BacktestError("사전 필터(전일 거래대금 상위·조건)를 통과하는 종목이 기간 안에 하나도 없다")

    # ---- 분봉 로드(워밍업 일 포함) — 지표가 첫날부터 채워지게
    bars_per_day = max(1, 390 // cfg.bar_minutes)
    warm_days = int(np.ceil(MAX_WARM_BARS / bars_per_day)) + 1
    load_from = didx[max(0, p0 - warm_days)].date()
    tick("minute", 0.10)
    mp = md.minute_panel(union, load_from, bound.period.end, cfg.bar_minutes, cfg.source)
    if mp.close.empty:
        raise BacktestError("통합 분봉 보관소에 이 기간·종목의 분봉이 없다")
    cols = list(mp.close.columns)
    pre = previous_day_flags(flags, mp.close.index, cols)  # D−1 값을 그날 전 봉에 — 당일 일봉은 안 본다(C3)

    # ---- 신호(분봉, t 까지) → 진입은 사전 필터와 AND
    tick("signals", 0.30)
    # 시장(지수) 피연산자는 평가기가 분봉 표에서 D−1 지수 값을 붙여 준다(strategy-agent 2026-09-26) — 당일 지수는 안 본다
    ev = evaluate(strat.entry, strat.exit, mp, market=md.index_frames(), market_filter=bound.market_filter,
                  daily=daily, bar_minutes=cfg.bar_minutes)  # 시간 단위(mN·daily_prev·daily_live)용 일봉·봉 길이
    entry = ev.entry & pre
    bar_day = mp.close.index.normalize()
    in_period = np.asarray((bar_day >= start) & (bar_day <= end))
    if not in_period.any():
        raise BacktestError("기간 안에 분봉이 없다")
    sub = _slice(mp, in_period)
    ent, ext = entry.loc[in_period], ev.exit.loc[in_period]

    # ---- 엔진(일봉 엔진 + 세션 규칙: EOD 종가 청산·EOD 이후 봉 거래 불가·날 경계 체결 없음)
    tick("engine", 0.55)
    cost, exit_rules, fill_rules, port = to_engine_rules(bound)
    session = bar_sessions(sub.close.index, cfg.eod_time)
    result = run_portfolio(sub, ent, ext, cost, exit_rules, fill_rules, port, session=session,
                           pos_exit=ev.pos_exit.sliced(in_period) if ev.pos_exit is not None else None)

    # ---- 커버리지: 쓴 (날짜,종목) 쌍 / 기대 쌍 — 조용히 줄이지 않는다(기간의 모든 일봉 거래일 기준: 분봉이 통째로 없는 날도 센다)
    days_in = pd.DatetimeIndex(sorted(set(sub.close.index.normalize())))
    period_daily = list(didx[p0:p1])
    pd_idx = pd.DatetimeIndex(period_daily)
    prev_pos = didx.searchsorted(pd_idx, side="left") - 1
    ok_day = prev_pos >= 0
    exp_flags = flags.iloc[prev_pos[ok_day]].reindex(columns=cols, fill_value=False)
    has = sub.close.notna().groupby(sub.close.index.normalize()).any().reindex(
        index=pd_idx[ok_day], columns=cols, fill_value=False)
    expected_pairs = int(flags.iloc[prev_pos[ok_day]].to_numpy().sum())
    used_pairs = int((exp_flags.to_numpy() & has.to_numpy()).sum())
    missing_days = len(period_daily) - len(days_in)
    coverage = {
        "expected_pairs": expected_pairs, "used_pairs": used_pairs,
        "pairs_share": (used_pairs / expected_pairs) if expected_pairs else None,
        "days_with_bars": len(days_in), "days_in_period": len(period_daily), "codes_requested": len(union),
        "codes_with_minutes": len(cols), "codes_without_minutes": sorted(set(union) - set(cols))[:30],
        "warmup_days": warm_days, "bar_minutes": cfg.bar_minutes,
    }
    if expected_pairs and used_pairs < expected_pairs:
        warnings.append(f"분봉 커버리지: 기대 (날짜,종목) {expected_pairs}쌍 중 {used_pairs}쌍만 분봉이 있어 나머지는 거래 기회가 없었다"
                        f"({used_pairs / expected_pairs:.0%}) — 종목별 보관 기간이 다르다")
    if len(days_in) < MIN_INTRADAY_DAYS:
        warnings.append(f"분봉 짧은 표본: 분봉이 있는 거래일 {len(days_in)}일(<{MIN_INTRADAY_DAYS}) — 결과의 통계적 의미가 약하다")
    if missing_days > 0:
        warnings.append(f"기간의 거래일 {len(period_daily)}일 중 {missing_days}일은 분봉이 하나도 없어 거래가 없다")
    warnings.append("분봉 거래대금(value)은 종가×거래량 근사값이다 — 분 단위에선 실제 거래대금과 크게 다를 수 있다. 사전 필터의 일봉 거래대금도 KRX 근사")
    src = cfg.source  # spec.intraday.source — 기본 al(통합), krx 는 사용자가 고를 때만
    if src == "al":
        warnings.append("분봉 출처: 통합(AL) 보관소(정규장 09:00~15:30, NXT 체결 포함). 15:30 종가 단일가 봉은 EOD 이후라 거래하지 않는다")
    else:
        warnings.append("분봉 출처: **KRX 전용**(통합 아님) — NXT 체결이 빠져 거래량·거래대금이 통합보다 20~40% 작다(삼성전자 0.76 등, data-agent 실측). "
                        "가격은 거의 같다. 거래량·거래대금 조건의 임계값을 통합(AL) 결과와 섞어 해석하지 말 것. 15:30 종가 단일가 봉은 EOD 이후라 거래하지 않는다")

    # ---- 일 단위 평가금(EOD) — 표준 지표·벤치마크는 일 단위로
    eq = result.equity
    daily_eq = (eq.assign(_d=eq["ts"].dt.normalize()).groupby("_d").last().drop(columns="ts")
                .rename_axis("ts").reset_index())
    result_d = dataclasses.replace(result, equity=daily_eq)

    coverage["minute_source"] = src
    coverage["code_periods"] = {c: [str(a), str(b)] for c, (a, b) in md.minute_coverage(cols, src).items()}  # 쓴 종목별 그 출처의 보관 기간
    extra_summary: dict = {"intraday": coverage}
    extra_meta: dict = {"minute_source": src, "bar_minutes": cfg.bar_minutes, "eod_time": cfg.eod_time, "prefilter_top_value": cfg.prefilter_top_value}
    trades_patch = None
    if refine:
        trades_patch, tr_summary, tr_warn = _refine(bound, md, result, cfg, cost)
        if src != "al":
            tr_warn.append("틱 정밀화의 봉은 KRX 분봉, 체결은 통합(AL) — 차이에 NXT 체결 유무(출처 차이)가 섞여 있다")
        extra_summary["tick_refine"] = tr_summary
        warnings += tr_warn
    tick("metrics", 0.85)
    rec = assemble_record(
        spec=spec, bound=bound, result=result_d, port=port, market=md.index_frames(), info=info, ranges=ranges,
        warnings=warnings, compat=False, legacy_m=None, ustats=ustats, n_codes=len(cols), n_bars=len(daily_eq),
        period_used=[str(sub.close.index[0].date()), str(sub.close.index[-1].date())], warmup_bars=warm_days,
        overrides=overrides, t_start=t_start, tick=tick, extra_summary=extra_summary, extra_meta=extra_meta,
        extra_value_warning=True)
    if trades_patch is not None and len(rec.trades):
        rec.trades = pd.concat([rec.trades.reset_index(drop=True), trades_patch.reset_index(drop=True)], axis=1)
    return rec


# ---------------------------------------------------------------------------- 모드 A: 틱 정밀화


def _refine(bound: Spec, md: MarketData, result, cfg: Intraday, cost):
    """분봉 엔진 거래 → 매매별 봉 기준가 vs 틱 기준가(SC-7). 반환: (거래표에 붙일 열, 요약, 경고)."""
    bm = cfg.bar_minutes
    sells = {(f.code, f.ts): f for f in result.fills if f.side == "sell"}
    buys = {(f.code, f.ts): f for f in result.fills if f.side == "buy"}
    tick_cache: dict[tuple[str, dt.date], object] = {}

    def ticks(code: str, day: dt.date):
        k = (code, day)
        if k not in tick_cache:
            tick_cache[k] = md.tick_day(code, day)
        return tick_cache[k]

    rows = []
    no_ticks = no_hit = 0
    for t in result.trades:
        day = t.entry_ts.date()
        td = ticks(t.code, day) if t.exit_ts is not None and t.exit_ts.date() == day else None
        row = {"entry_ref_bar": np.nan, "entry_ref_tick": np.nan, "entry_diff_pct": np.nan, "exit_ref_bar": np.nan,
               "exit_ref_tick": np.nan, "exit_diff_pct": np.nan, "net_pnl_tick": np.nan, "net_pct_tick": np.nan,
               "tick_refined": False}
        bf = buys.get((t.code, t.entry_ts))
        sf = sells.get((t.code, t.exit_ts)) if t.exit_ts is not None else None
        if td is None or bf is None or sf is None:
            no_ticks += 1
            rows.append(row)
            continue
        sec = np.asarray(td.sec)
        prc = np.asarray(td.prc, dtype=float)
        base = 9 * 3600
        e_start = int((t.entry_ts - pd.Timedelta(minutes=bm) - pd.Timestamp(day)).total_seconds()) - base
        x_end = int((t.exit_ts - pd.Timestamp(day)).total_seconds()) - base
        x_start = x_end - bm * 60
        er = refine_entry(sec, prc, e_start, bf.reference_price)
        xr = refine_exit(sec, prc, t.exit_reason, x_start, x_end, sf.reference_price, sf.reference_price)
        row.update(entry_ref_bar=er.bar_ref, entry_ref_tick=er.tick_ref, entry_diff_pct=er.diff_pct,
                   exit_ref_bar=xr.bar_ref, exit_ref_tick=xr.tick_ref, exit_diff_pct=xr.diff_pct)
        if er.tick_ref is not None and xr.tick_ref is not None:
            net, pct = repriced_net(cost, t.qty, er.tick_ref, xr.tick_ref)
            row.update(net_pnl_tick=net, net_pct_tick=pct, tick_refined=True)
        else:
            no_hit += 1
        rows.append(row)
    df = pd.DataFrame(rows)
    ok = df["tick_refined"] if len(df) else pd.Series(dtype=bool)
    bar_net_sum = float(sum(t.net_pnl for t, r in zip(result.trades, rows) if r["tick_refined"]))

    def dist(s: pd.Series) -> dict | None:
        s = s.dropna()
        return None if s.empty else {"mean": float(s.mean()), "median": float(s.median()),
                                     "p5": float(s.quantile(.05)), "p95": float(s.quantile(.95)), "n": int(len(s))}

    summary = {
        "n_trades": len(df), "n_refined": int(ok.sum()) if len(df) else 0, "n_without_ticks": no_ticks, "n_no_matching_tick": no_hit,
        "entry_diff_pct": dist(df["entry_diff_pct"]) if len(df) else None,
        "exit_diff_pct": dist(df["exit_diff_pct"]) if len(df) else None,
        "net_pnl_bar": bar_net_sum if len(df) and ok.any() else None,
        "net_pnl_tick": float(df.loc[ok, "net_pnl_tick"].sum()) if len(df) and ok.any() else None,
        "definition": "diff = 틱 기준가 ÷ 봉 기준가 − 1 (슬리피지 전). 진입·시그널 청산=봉이 끝난 시각 이후 첫 체결, 선 청산=봉 안에서 선을 처음 넘은 체결, "
                      "종가 청산=봉의 마지막 체결. net_pnl_tick 은 같은 비용 모델로 다시 계산(정밀화된 거래만).",
    }
    warns = []
    if len(df) and summary["n_refined"] < len(df):
        warns.append(f"틱 정밀화: 거래 {len(df)}건 중 {summary['n_refined']}건만 틱으로 확인했다(체결 파일 없음 {no_ticks}건, "
                     f"봉 구간에 대응 체결 없음 {no_hit}건) — 체결 데이터는 수집한 종목·날짜에만 있다")
    warns.append("체결 파일 상당수(실측 40%)에 시각이 어긋난 줄이 있어 같은 초 안 체결 순서는 원본 그대로라 불확실하다(초 단위 순서는 맞음)")
    return df, summary, warns


# =========================================================================== 틱 모드 B


def run_tick(spec: Spec, md: MarketData, progress: Progress | None = None, *, legacy=None,
             overrides: Mapping[str, float] | None = None) -> RunRecord:
    t_start = time.perf_counter()
    tick = progress or (lambda stage, frac: None)
    bound = bind_params(spec, overrides)
    tcfg = bound.tick
    if tcfg is None or tcfg.entry_source != "catalog":
        raise BacktestError("run_tick 은 mode='tick', tick.entry_source='catalog' 만 처리한다")
    ranges = md.data_ranges()
    warnings = _check_spec(bound, ranges)
    start, end = bound.period.start, bound.period.end

    tick("load", 0.02)
    info = md.stock_info()
    tick_codes = md.tick_codes()
    if not tick_codes:
        raise BacktestError("체결(tick_al) 데이터가 없다")
    db = getattr(tcfg.catalog, "daily_breakout", None)
    daily, dcodes, ustats = _daily_frame(bound, md, info, max(100, (db.n + 5) if db is not None else 0))  # D−1 순위(lookback ≤ 60)·n일 고가 재료
    elig = [c for c in tick_codes if c in set(dcodes)] if bound.universe.type != "codes" else \
        [c for c in bound.universe.codes if c in set(tick_codes)]
    if not elig:
        raise BacktestError("체결 데이터가 있는 종목이 유니버스에 없다")
    didx = daily.close.index
    rank_ok = None
    if bound.universe.type == "top_value":
        rank = compute(daily, "value_rank", {"lookback": bound.universe.lookback_days})
        rank_ok = (rank <= bound.universe.n).fillna(False)

    cands: dict[dt.date, list[Candidate]] = {}
    all_days: set[dt.date] = set()
    pairs_expected = pairs_used = gap_skipped = n_signals = n_no_entry = 0
    for k, code in enumerate(elig):
        days = [d for d in md.tick_days(code) if start <= d <= end]
        for d in days:
            all_days.add(d)
            if rank_ok is not None:  # D−1 순위
                pos = int(didx.searchsorted(pd.Timestamp(d), side="left")) - 1
                if pos < 0 or code not in rank_ok.columns or not rank_ok.iloc[pos][code]:
                    continue
            pairs_expected += 1
            td = md.tick_day(code, d)
            if td is None:
                continue
            pairs_used += 1
            if tcfg.exclude_gap_open_pct is not None and is_gap_open_day(td, tcfg.exclude_gap_open_pct):
                gap_skipped += 1
                continue
            level = None
            if db is not None:  # D−1 까지 n일 최고가 — 일봉 고가에서(당일 행은 안 봄: prior_n_high 가 day 미만만 센다)
                level = prior_n_high(didx.date, daily.high[code].to_numpy(), d, db.n) if code in daily.high.columns else float("nan")
            ev = detect_from_spec(td, tcfg, daily_high_level=level)
            n_no_entry += ev.n_no_entry
            for s, j in zip(ev.signal_sec, ev.entry_idx):
                cands.setdefault(d, []).append(Candidate(code, d, td.sec, td.prc, td.prev_close, int(s), int(j)))
                n_signals += 1
        tick("ticks", 0.05 + 0.75 * (k + 1) / len(elig))
    if not all_days:
        raise BacktestError("기간 안에 체결 데이터가 있는 날이 없다")

    tick("engine", 0.85)
    cost, exit_rules, _, port = to_engine_rules(bound)
    if exit_rules.max_holding_bars is not None:
        warnings.append("틱 모드는 max_holding_bars 를 쓰지 않는다 — time_stop_sec 로 대신한다")
    trules = TickRules(tcfg.time_stop_sec, tcfg.eod_time, tcfg.exclude_gap_open_pct)
    result = simulate_tick_days(cands, sorted(all_days), cost, exit_rules, port, trules)

    coverage = {"expected_pairs": pairs_expected, "used_pairs": pairs_used, "days": len(all_days), "codes": len(elig),
                "signals": n_signals, "gap_open_days_skipped": gap_skipped, "signals_without_entry_tick": n_no_entry,
                "eod_time": tcfg.eod_time}
    if pairs_expected and pairs_used < pairs_expected:
        warnings.append(f"틱 커버리지: 기대 (날짜,종목) {pairs_expected}쌍 중 {pairs_used}쌍만 체결 파일이 있다")
    warnings.append(f"틱 표본: 체결 데이터가 있는 거래일 {len(all_days)}일 · 종목 {len(elig)}개 — 수집 조회창이 짧아 통계적 의미가 약하다")
    warnings.append("체결 파일 상당수(실측 40%)에 시각이 어긋난 줄이 있다 — 초 단위 순서는 맞고 같은 초 안 체결 순서만 불확실하다(로더가 to_grid 식 안정 정렬)")
    warnings.append("틱 모드 근사: 거래량 한도 미적용, 청산가가 상하한가에 잠겨도 그 가격으로 청산(다음 날 이월 없음), bars_held 는 초 단위, "
                    "우선순위는 진입 시각 순(rank_by 무시)")
    if result.diagnostics.get("exit_at_limit"):
        warnings.append(f"상하한가에 잠긴 가격으로 청산된 거래 {result.diagnostics['exit_at_limit']}건 — 실제론 청산 불가였을 수 있다")
    tick("metrics", 0.95)
    return assemble_record(
        spec=spec, bound=bound, result=result, port=port, market=md.index_frames(), info=info, ranges=ranges,
        warnings=warnings, compat=False, legacy_m=None, ustats=ustats, n_codes=len(elig), n_bars=len(all_days),
        period_used=[str(min(all_days)), str(max(all_days))], warmup_bars=0, overrides=overrides, t_start=t_start,
        tick=tick, extra_summary={"tick": coverage}, extra_meta={"entry_source": "catalog"}, extra_value_warning=False)
