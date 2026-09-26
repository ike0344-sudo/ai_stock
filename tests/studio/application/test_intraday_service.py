"""분봉(2단계)·모드 A(틱 정밀화)·모드 B(틱 조건 진입) — 체결에서 만든 합성 분봉/틱으로.

카나리아: C3(분봉 k 이후 + 당일 일봉 변조 -> k 이하 체결 불변) · C4(틱 s 이후 변조 -> s 이전 진입 불변, 진입은 신호 뒤 체결).
"""
import copy

import numpy as np
import pandas as pd
import pytest

from studio.application.backtest_service import BacktestError, run_backtest
from studio.application.optimize_service import run_optimize
from studio.domain.conditions.tick import detect_from_spec
from studio.domain.spec import Spec
from studio.domain.validation import OptimizeConfig

from .fakes_intraday import IntradayFake

CLOSE = {"kind": "field", "name": "close"}


def hi(n):
    return {"kind": "ind", "name": "highest", "params": {"src": "high", "n": n}}


def lo(n):
    return {"kind": "ind", "name": "lowest", "params": {"src": "low", "n": n}}


def intraday_dict(md, **over):
    d = {
        "version": 1, "name": "분봉 테스트", "mode": "intraday",
        "period": {"start": str(md.days[0].date()), "end": str(md.days[-1].date())},
        "universe": {"type": "all", "exclude": []},
        "strategy": {"source": "builder",
                     "entry": {"logic": "all", "items": [{"left": CLOSE, "op": "gt", "right": hi(6)}]},
                     "exit": {"logic": "any", "items": [{"left": CLOSE, "op": "lt", "right": lo(4)}]}},
        "intraday": {"bar_minutes": 5, "prefilter_top_value": 8, "eod_time": "15:20"},
        "portfolio": {"max_positions": 3}, "fills": {"volume_cap_pct": None},
    }
    d.update(over)
    return d


def tick_dict(md, **over):
    d = {
        "version": 1, "name": "틱 테스트", "mode": "tick",
        "period": {"start": str(md.days[0].date()), "end": str(md.days[-1].date())},
        "universe": {"type": "all", "exclude": []},
        "tick": {"entry_source": "catalog", "catalog": {"breakout_min": 1, "time_from": "09:05", "time_to": "15:00"},
                 "cooldown_sec": 300, "exclude_gap_open_pct": 5, "time_stop_sec": 600, "eod_time": "15:19:59"},
        "portfolio": {"max_positions": 3}, "fills": {"volume_cap_pct": None},
    }
    d.update(over)
    return d


@pytest.fixture(scope="module")
def md():
    return IntradayFake(n_days=12, drift=0.0)


# ------------------------------------------------------------------ 분봉 (2단계)
def test_intraday_smoke_and_session_rules(md):
    rec = run_backtest(Spec.model_validate(intraday_dict(md)), md)
    t = rec.trades
    assert len(t) > 20 and rec.meta["mode"] == "intraday" and rec.meta["bar_minutes"] == 5
    # 하루 안에서만: 진입·청산이 같은 날, 진입은 신호 봉 다음 봉이라 첫 봉(09:05) 진입 없음, EOD(15:20) 뒤 체결 없음
    assert (t["entry_ts"].dt.normalize() == t["exit_ts"].dt.normalize()).all()
    assert (t["entry_ts"].dt.time > pd.Timestamp("09:05").time()).all()
    assert (t["exit_ts"].dt.time <= pd.Timestamp("15:20").time()).all() and (t["entry_ts"].dt.time <= pd.Timestamp("15:20").time()).all()
    assert len(rec.equity) == 12 and (rec.equity["n_positions"] == 0).all()  # 일 단위 평가금, 매일 flat
    cov = rec.summary["intraday"]
    assert cov["expected_pairs"] == 96 and cov["used_pairs"] == 60 and cov["codes_with_minutes"] == 5
    assert set(cov["codes_without_minutes"]) == {"000060", "000070", "005930"} and cov["warmup_days"] == 8
    w = " ".join(rec.warnings)
    assert "분봉 커버리지" in w and "분봉 짧은 표본" in w and "종가×거래량 근사" in w and "15:30 종가 단일가" in w
    assert rec.summary["metrics"]["num_trades"] == len(t)


def test_all_exits_are_eod_at_1520_and_1535_bar_never_trades(md):
    """lead 확인 ④: 15:30 종가 단일가 봉(끝 라벨 15:35)이 eod_time 15:20 청산과 겹치지 않는다."""
    d = intraday_dict(md)
    d["strategy"]["exit"] = {"logic": "any", "items": [{"left": CLOSE, "op": "lt", "right": {"kind": "const", "value": 0}}]}  # 청산 신호 없음
    rec = run_backtest(Spec.model_validate(d), md)
    t = rec.trades
    assert len(t) > 5 and set(t["exit_reason"]) == {"eod"}
    assert (t["exit_ts"].dt.time == pd.Timestamp("15:20").time()).all()
    # 라벨 15:35 봉(종가 단일가)이 실제로 데이터에 있었지만 거래에 안 쓰였다
    mp = md.minute_panel(["000010"], md.days[0].date(), md.days[-1].date(), 5)
    assert (mp.close.index.time == pd.Timestamp("15:35").time()).any()
    assert not (t["exit_ts"].dt.time == pd.Timestamp("15:35").time()).any()


def test_c3_canary_bars_after_k_and_same_day_daily_row(md):
    """C3: 분봉 k 이후 + 그 날 일봉 행을 ×10 으로 망가뜨려도 k 이하 체결·앞선 날 체결은 불변(일봉 피연산자는 D-1)."""
    spec = Spec.model_validate(intraday_dict(md))
    base = run_backtest(spec, md)
    fills = lambda r: [(t.entry_ts, t.code, t.entry_price) for t in r.trades.itertuples()]  # noqa: E731
    D = md.days[8]
    k = D + pd.Timedelta(hours=11)  # 11:00 (봉 끝 라벨)

    bad = copy.copy(md)
    bad.ticks = {key: (s, np.where(s >= 2 * 3600, p * 10, p), q) if key[1] == D.date() else (s, p, q)
                 for key, (s, p, q) in md.ticks.items()}
    dp = md.panel
    m = dp.close.index == D
    tam = lambda df: df.where(pd.DataFrame(np.broadcast_to(~m[:, None], df.shape), index=df.index, columns=df.columns), df * 10)  # noqa: E731
    from studio.domain.models import Panel
    bad.panel = Panel(*(tam(getattr(dp, kk)) for kk in ("open", "high", "low", "close", "volume", "value", "prev_close")))
    bad_rec = run_backtest(spec, bad)
    b_before = [f for f in fills(base) if f[0] <= k]
    assert b_before and b_before == [f for f in fills(bad_rec) if f[0] <= k]  # k 이하 진입 불변(같은 날 앞부분 + 앞선 날 전부)
    assert [f for f in fills(base) if f[0] > k] != [f for f in fills(bad_rec) if f[0] > k]  # 변조가 뒤쪽은 실제로 바꿨다(둔감하지 않음)
    # 일봉 행 D 만 변조(분봉은 그대로): D 당일 체결은 통째로 불변 — 당일 일봉은 안 본다. D+1 부터는 순위가 바뀔 수 있다
    only_daily = copy.copy(md)
    only_daily.panel = bad.panel
    r2 = run_backtest(spec, only_daily)
    upto_D = [f for f in fills(base) if f[0] < D + pd.Timedelta(days=1)]
    assert upto_D == [f for f in fills(r2) if f[0] < D + pd.Timedelta(days=1)]


def test_intraday_errors(md):
    with pytest.raises(BacktestError, match="조건 조립기"):
        d = intraday_dict(md, strategy={"source": "legacy", "name": "ma_crossover", "params": {"short_window": 5, "long_window": 20}})
        run_backtest(Spec.model_validate(d), md)
    with pytest.raises(BacktestError, match="겹치지 않음"):
        run_backtest(Spec.model_validate(intraday_dict(md, period={"start": "2030-01-02", "end": "2030-02-01"})), md)
    # 그리드 최적화는 일봉 전용
    from studio.domain.validation import ValidationConfigError
    with pytest.raises(ValidationConfigError, match="일봉"):
        d = intraday_dict(md)
        d["strategy"]["entry"]["items"][0]["right"] = hi({"param": "n"})
        d["params"] = {"n": {"default": 6, "min": 3, "max": 9, "step": 3}}
        run_optimize(Spec.model_validate(d), md, OptimizeConfig(min_trades=1))


# ------------------------------------------------------------------ 모드 A — 틱 정밀화
def _refine_dict(md, **over):
    d = intraday_dict(md, mode="tick", tick={"entry_source": "minute_refine", "catalog": {"breakout_min": 5}})
    d.update(over)
    return d


def test_mode_a_consistent_ticks_give_zero_diff_and_same_net(md):
    d = _refine_dict(md, exits={"stop_loss_pct": 1.5, "take_profit_pct": 2.5})
    rec = run_backtest(Spec.model_validate(d), md)
    t, tr = rec.trades, rec.summary["tick_refine"]
    assert len(t) > 20 and tr["n_refined"] == tr["n_trades"] == len(t) and tr["n_without_ticks"] == 0
    assert (t["entry_diff_pct"].abs() < 1e-9).all()  # 같은 체결에서 만든 분봉이라 시가 == 봉 이후 첫 체결
    same = t["exit_reason"].isin(["signal", "eod"])
    assert (t.loc[same, "exit_diff_pct"].abs() < 1e-9).all()
    stops, targets = t["exit_reason"].isin(["stop"]), t["exit_reason"] == "target"
    assert stops.any() and (t.loc[stops, "exit_diff_pct"] <= 1e-9).all()  # 선을 뚫은 체결은 선과 같거나 나쁘다
    assert (t.loc[targets, "exit_diff_pct"] >= -1e-9).all()
    # 틱 가격으로 다시 계산한 순손익: 차이 0 인 거래는 엔진 순손익과 정확히 같다(비용 모델 동일성)
    z = (t["entry_diff_pct"].abs() < 1e-9) & (t["exit_diff_pct"].abs() < 1e-9)
    assert z.sum() > 5
    assert np.allclose(t.loc[z, "net_pnl_tick"], t.loc[z, "net_pnl"], rtol=1e-9)
    assert tr["definition"]
    assert any("시각이 어긋난 줄" in w for w in rec.warnings)


def test_mode_a_shifted_ticks_show_difference_and_missing_ticks_are_reported():
    md = IntradayFake(n_days=8, drift=0.0)
    d = _refine_dict(md)
    frozen = md.minute_panel(md.tick_codes(), md.days[0].date(), md.days[-1].date(), 5)
    md.minute_panel = lambda *a, **k: frozen  # 분봉은 그대로 두고 체결만 어긋나게 만든다
    md.ticks = {k: (s, p + 10.0, q) for k, (s, p, q) in md.ticks.items()}  # 모든 체결 +10원
    rec = run_backtest(Spec.model_validate(d), md)
    t = rec.trades
    assert len(t) > 5 and (t["entry_diff_pct"] > 0).all()  # 틱 기준가가 봉보다 높다 -> 진입 차이 양수
    assert rec.summary["tick_refine"]["entry_diff_pct"]["mean"] > 0
    # 체결 파일이 일부 (종목,날짜)에 없으면 정밀화 안 된 거래로 센다 — 조용히 넘어가지 않는다
    full = dict(md.ticks)
    victim = t.iloc[0]
    md.ticks = {k: v for k, v in full.items() if not (k[0] == victim["code"] and k[1] == victim["entry_ts"].date())}
    rec2 = run_backtest(Spec.model_validate(d), md)
    s2 = rec2.summary["tick_refine"]
    assert s2["n_without_ticks"] >= 1 and s2["n_refined"] < s2["n_trades"]
    assert any("틱으로 확인" in w for w in rec2.warnings)


# ------------------------------------------------------------------ 모드 B — 틱 조건 진입
@pytest.fixture(scope="module")
def md_up():
    return IntradayFake(n_days=10, drift=0.0001, seed=11)


def test_mode_b_runs_with_slots_costs_and_warnings(md_up):
    rec = run_backtest(Spec.model_validate(tick_dict(md_up)), md_up)
    t = rec.trades
    assert len(t) > 10 and rec.meta["mode"] == "tick" and rec.meta["entry_source"] == "catalog"
    assert (t["entry_ts"].dt.normalize() == t["exit_ts"].dt.normalize()).all()
    assert set(t["exit_reason"]) <= {"time", "eod", "stop", "target", "trailing"}
    assert (t["exit_ts"].dt.strftime("%H:%M:%S") <= "15:19:59").all() and (t["entry_ts"] < t["exit_ts"]).all() | (t["bars_held"] == 0).any()
    assert len(rec.equity) == 10
    cov = rec.summary["tick"]
    assert cov["expected_pairs"] == cov["used_pairs"] == 50 and cov["signals"] >= len(t)
    w = " ".join(rec.warnings)
    assert "틱 표본" in w and "시각이 어긋난" in w and "거래량 한도 미적용" in w
    # 동시 보유는 max_positions 를 넘지 않는다
    ev = [(x.entry_ts, 1) for x in t.itertuples()] + [(x.exit_ts, -1) for x in t.itertuples()]
    ev.sort(key=lambda e: (e[0], e[1]))  # 같은 시각이면 청산이 먼저
    cur = peak = 0
    for _, dlt in ev:
        cur += dlt
        peak = max(peak, cur)
    assert peak <= 3
    # 손절이 켜지면 손절 청산이 나온다
    rs = run_backtest(Spec.model_validate(tick_dict(md_up, exits={"stop_loss_pct": 0.3})), md_up)
    assert "stop" in set(rs.trades["exit_reason"])


def test_c4_canary_ticks_after_s_and_entry_after_signal(md_up):
    spec = Spec.model_validate(tick_dict(md_up))
    base = run_backtest(spec, md_up)
    S = 2 * 3600 + 30 * 60  # 11:30:00
    bad = copy.copy(md_up)
    bad.ticks = {k: (s, np.where(s >= S, p * 10, p), q) for k, (s, p, q) in md_up.ticks.items()}
    bad_rec = run_backtest(spec, bad)
    cut = lambda r: sorted((t.code, t.entry_ts, t.entry_price) for t in r.trades.itertuples()  # noqa: E731
                           if (t.entry_ts - t.entry_ts.normalize()).total_seconds() < 9 * 3600 + S)
    assert cut(base) and cut(base) == cut(bad_rec)  # s 이전 진입 불변
    px = lambda r: sorted((t.entry_ts, t.entry_price) for t in r.trades.itertuples())  # noqa: E731
    assert px(base) != px(bad_rec)  # 변조는 실제로 작용(S 이후 진입가가 달라짐 — 돌파 시점은 스케일 불변이라 시각은 같을 수 있다)
    # 진입가는 신호 뒤: 신호 초 s 마다 entry_sec > s (조건식 계약) — 서비스가 그 이벤트를 그대로 쓴다
    c = spec.tick
    n = 0
    for (code, d), (sec, prc, qty) in md_up.ticks.items():
        td = md_up.tick_day(code, d)
        ev = detect_from_spec(td, c)
        assert (ev.entry_sec > ev.signal_sec).all()
        n += len(ev.signal_sec)
    assert n > 0


def test_mode_b_gap_open_days_excluded_and_universe_top_value():
    md = IntradayFake(n_days=6, drift=0.0001, seed=3)
    # 첫 체결가가 전일 종가 +5% 이상인 날은 제외 — 전일 종가를 낮춰 모든 (종목,날) 을 갭시작으로 만든다
    p = md.panel
    low = p.close.copy()
    low.iloc[:] = 100.0
    from studio.domain.models import Panel
    md.panel = Panel(p.open, p.high, p.low, low, p.volume, p.value, low.shift(1))
    rec = run_backtest(Spec.model_validate(tick_dict(md, tick={**tick_dict(md)["tick"], "exclude_gap_open_pct": 5})), md)
    assert len(rec.trades) == 0 and rec.summary["tick"]["gap_open_days_skipped"] == rec.summary["tick"]["used_pairs"] > 0


def test_mode_b_errors():
    md = IntradayFake(n_days=5)
    with pytest.raises(BacktestError, match="겹치지 않음"):
        run_backtest(Spec.model_validate(tick_dict(md, period={"start": "2030-01-02", "end": "2030-02-01"})), md)


# ------------------------------------------------------------------ 분봉 모드의 시장(지수) 조건 — D-1 (strategy-agent 2026-09-26)
def _idx_cond(th):
    return {"logic": "all", "items": [{"left": {"kind": "market", "index": "kospi", "name": "close"}, "op": "gt",
                                       "right": {"kind": "const", "value": th}}]}


def test_intraday_market_filter_uses_previous_day_index_only():
    md = IntradayFake(n_days=12, drift=0.0)
    idx = md.panel.close.index
    # 지수(×100 저장): 앞 6거래일은 3000, 뒤는 3200 — 필터 "kospi 종가 > 3100" 은 전일 지수 기준이라 7번째 날 다음(8번째 날)부터 통과
    for k in ("kospi", "kosdaq"):
        v = np.full(len(idx), 300_000.0)
        v[len(idx) - 12 + 6:] = 320_000.0
        md._index[k] = pd.DataFrame({"close": v}, index=idx)
    base = run_backtest(Spec.model_validate(intraday_dict(md)), md)
    flt = run_backtest(Spec.model_validate(intraday_dict(md, market_filter=_idx_cond(3100))), md)
    days = [d for d in md.days]
    first_ok_day = days[7]  # 지수가 3200 으로 바뀐 날은 days[6], 그 D-1 값이 처음 쓰이는 날은 days[7]
    assert len(flt.trades) > 0 and len(base.trades) > len(flt.trades)
    assert (flt.trades["entry_ts"].dt.normalize() >= first_ok_day).all()
    assert (base.trades["entry_ts"].dt.normalize() < first_ok_day).any()  # 필터가 없으면 앞 날에도 거래가 있다


def test_c3_canary_index_rows_from_D_on_do_not_change_D_or_earlier_bars():
    md = IntradayFake(n_days=12, drift=0.0)
    idx = md.panel.close.index
    spec = Spec.model_validate(intraday_dict(md, market_filter=_idx_cond(0)))
    base = run_backtest(spec, md)
    D = md.days[8]
    bad = copy.copy(md)
    bad._index = {k: df.assign(close=df["close"].where(df.index < D, df["close"] * 10)) for k, df in md._index.items()}
    bad_rec = run_backtest(spec, bad)
    fills = lambda r: [(t.entry_ts, t.code, t.entry_price) for t in r.trades.itertuples()]  # noqa: E731
    upto = [f for f in fills(base) if f[0] < D + pd.Timedelta(days=1)]
    assert upto and upto == [f for f in fills(bad_rec) if f[0] < D + pd.Timedelta(days=1)]  # D 당일까지 불변(지수 D 행은 안 본다)
    # 필터가 실제로 지수를 읽는지(둔감하지 않음): 임계를 바꾸면 결과가 달라진다
    hi_th = run_backtest(Spec.model_validate(intraday_dict(md, market_filter=_idx_cond(10**9))), md)
    assert len(hi_th.trades) == 0 and len(base.trades) > 0


def test_stale_index_range_warns_via_validate(md):
    """지수 자료가 기간보다 일찍 끝나면 validate_against 경고가 결과 경고로 나온다(마지막 값이 조용히 계속 붙지 않게)."""
    stale = copy.copy(md)
    r = md.data_ranges()
    stale.data_ranges = lambda: {**r, "kospi": (r["kospi"][0], md.days[3].date()), "kosdaq": (r["kosdaq"][0], md.days[3].date())}
    rec = run_backtest(Spec.model_validate(intraday_dict(md, market_filter=_idx_cond(0))), stale)
    assert any("코스피 지수 데이터가" in w and "그 이후" in w for w in rec.warnings)


def test_spec_intraday_source_reaches_loader_range_key_and_warnings(md):
    """spec.intraday.source: 기본 al(통합). krx 는 로더에 그 출처가 전달되고, 범위 키·경고문·meta 가 출처별로 갈라진다."""
    al = run_backtest(Spec.model_validate(intraday_dict(md)), md)
    assert md.last_source == "al"
    assert al.summary["intraday"]["minute_source"] == "al" and al.meta["minute_source"] == "al"
    cp = al.summary["intraday"]["code_periods"]
    assert set(cp) == set(md.tick_codes()) and cp["000010"] == [str(md.days[0].date()), str(md.days[-1].date())]  # 종목별 사용 기간
    assert any("통합(AL) 보관소" in w for w in al.warnings) and not any("KRX 전용" in w for w in al.warnings)
    d = intraday_dict(md)
    d["intraday"]["source"] = "krx"
    kr = run_backtest(Spec.model_validate(d), md)
    assert md.last_source == "krx" and kr.meta["minute_source"] == "krx" and kr.summary["intraday"]["minute_source"] == "krx"
    w = " ".join(kr.warnings)
    assert "KRX 전용" in w and "20~40%" in w and "통합(AL) 보관소" not in w
    # 범위 키: krx 를 골랐는데 krx 범위 정보가 없으면 조용히 통과하지 않고 오류(출처를 섞지 않는다)
    class NoKrx(type(md)):
        def data_ranges(self):
            r = super().data_ranges()
            r.pop("minute_krx")
            return r
    nk = copy.copy(md)
    nk.__class__ = NoKrx
    with pytest.raises(BacktestError, match="KRX 분봉 데이터 범위 정보가 없음"):
        run_backtest(Spec.model_validate(d), nk)
    run_backtest(Spec.model_validate(intraday_dict(md)), nk)  # al 은 영향 없음
    # 모드 A: 봉은 krx 인데 체결은 통합 → 출처 차이 경고
    dm = _refine_dict(md)
    dm["intraday"]["source"] = "krx"
    assert any("봉은 KRX 분봉" in x for x in run_backtest(Spec.model_validate(dm), md).warnings)
