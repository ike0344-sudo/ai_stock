"""엔진 진행 중 중간 곡선(실행 화면 "차트가 지나가는 모습") — 결과 불변 · 점 수 상한 · 취소 · 작업 처리기 누적.

핵심: **곡선 콜백을 켜고 꺼도 거래·체결·평가금·지표가 똑같다**(엔진은 읽기만 한다). 일봉 포트폴리오·분봉·틱 세 경로 모두.
"""
import copy

import numpy as np
import pandas as pd
import pytest

from studio.application import jobs
from studio.application.backtest_service import run_backtest
from studio.domain.engine.curve import MAX_POINTS, CurveEmitter
from studio.domain.spec import Spec

from .fakes import FakeMarketData, make_panel
from .fakes_intraday import IntradayFake
from .test_intraday_service import intraday_dict, tick_dict
from .test_optimize_service import lit_dict


def same_result(a, b):
    """거래표·평가금 곡선·지표 요약이 완전히 같다(시간 측정 칸만 제외)."""
    pd.testing.assert_frame_equal(a.trades.reset_index(drop=True), b.trades.reset_index(drop=True))
    pd.testing.assert_frame_equal(a.equity, b.equity)
    sa, sb = copy.deepcopy(a.summary), copy.deepcopy(b.summary)
    assert sa == sb
    assert a.warnings == b.warnings
    ma, mb = dict(a.meta), dict(b.meta)
    ma.pop("elapsed_sec"), mb.pop("elapsed_sec")
    assert ma == mb


def run_both(spec, md):
    calls_off, calls_on, pts = [], [], []
    off = run_backtest(spec, md, lambda s, f: calls_off.append((s, f)))
    on = run_backtest(spec, md, lambda s, f: calls_on.append((s, f)), curve=pts.append)
    return off, on, pts, calls_off, calls_on


def check_points(pts, rec, *, max_points=MAX_POINTS):
    assert 1 <= len(pts) <= max_points
    assert [p["frac"] for p in pts] == sorted(p["frac"] for p in pts) and pts[-1]["frac"] == 1.0
    dates = [p["date"] for p in pts]
    assert dates == sorted(dates) and len(set(dates)) == len(dates)
    assert all(a["n_trades"] <= b["n_trades"] for a, b in zip(pts, pts[1:]))
    # 마지막 점 = 엔진 마지막 봉의 평가금
    assert {"date", "equity", "cash", "n_positions", "n_trades", "last_event", "frac"} == set(pts[0])
    ev = [p["last_event"] for p in pts if p["last_event"]]
    assert ev and {"ts", "code", "side", "qty", "price", "reason"} == set(ev[0])


def test_daily_portfolio_result_is_identical_with_and_without_curve():
    md = FakeMarketData(make_panel(n=420, seed=5))
    off, on, pts, c_off, c_on = run_both(Spec.model_validate(lit_dict()), md)
    same_result(off, on)
    assert len(off.trades) > 5
    check_points(pts, on)
    n = on.summary["n_bars"]  # 엔진 봉 수 — 200 넘으면 step 개 봉마다 한 점(끝 봉은 항상)
    assert len(pts) == -(-n // -(-n // 200))
    assert pts[-1]["equity"] == pytest.approx(float(on.equity["equity"].iloc[-1]), abs=0.01)
    assert pts[-1]["n_trades"] == len(on.trades)
    # 곡선을 안 켠 실행의 진행 콜백은 그대로(엔진 단계 안 진행률이 움직이지 않는다), 켠 실행은 같은 단계 + 엔진 단계 안 추가 호출
    assert c_off == [c for c in c_on if not (c[0] == "engine" and c != ("engine", 0.55))]
    assert all(0.55 <= f <= 0.85 for s, f in c_on if s == "engine")


def test_intraday_curve_is_thinned_to_at_most_200_points_and_result_is_identical():
    md = IntradayFake(n_days=12, drift=0.0)
    off, on, pts, _, _ = run_both(Spec.model_validate(intraday_dict(md)), md)
    same_result(off, on)
    n_bars = md.minute_panel(md.tick_codes(), md.days[0].date(), md.days[-1].date(), 5).close.shape[0]
    assert n_bars > 200  # 솎아야 하는 크기
    check_points(pts, on)
    assert len(pts) <= 200
    assert all(":" in p["date"] for p in pts)  # 분봉은 시각까지


def test_tick_mode_curve_per_day_and_result_is_identical():
    md = IntradayFake(n_days=10, drift=0.0001, seed=11)
    off, on, pts, _, c_on = run_both(Spec.model_validate(tick_dict(md)), md)
    same_result(off, on)
    check_points(pts, on)
    assert len(pts) == 10 and all(len(p["date"]) == 10 for p in pts)  # 날 단위
    assert pts[-1]["n_trades"] == len(on.trades)
    assert all(0.85 <= f <= 0.95 for s, f in c_on if s == "engine")


def test_curve_callback_exception_stops_the_run_cooperative_cancel():
    md = FakeMarketData(make_panel(n=420, seed=5))

    def progress(stage, frac):
        if stage == "engine" and frac > 0.7:
            raise RuntimeError("취소 요청으로 중단")
    with pytest.raises(RuntimeError, match="취소"):
        run_backtest(Spec.model_validate(lit_dict()), md, progress, curve=lambda p: None)


def test_emitter_point_budget_and_last_bar_always_emitted():
    for n in (1, 7, 200, 201, 1000, 4099):
        got = []
        e = CurveEmitter(got.append, n)
        for i in range(n):
            e.emit(i, pd.Timestamp("2026-01-05") + pd.Timedelta(days=i), 1.0, 1.0, 0, 0, [])
        assert 1 <= len(got) <= 200 and got[-1]["frac"] == 1.0, n


# ------------------------------------------------------------------ 작업 처리기 — progress.json 누적
class _Ctx:
    def __init__(self, payload):
        self.payload, self.calls, self.run_id = payload, [], None

    def is_cancelled(self):
        return False

    def progress(self, pct, stage="", message="", **extra):
        import json
        self.calls.append((stage, pct, json.loads(json.dumps(extra))))  # 실제 JobContext 처럼 그 자리에서 직렬화(참조를 안 남긴다)

    def set_run_id(self, rid):
        self.run_id = rid


def test_live_curve_accumulator_caps_points_and_keeps_last():
    lc = jobs.LiveCurve(cap=10)
    for i in range(37):
        lc.add({"date": f"d{i}", "equity": float(i), "cash": 0.0, "n_positions": 0, "n_trades": i, "last_event": None, "frac": i / 37})
    assert len(lc.points) <= 10 and lc.points[-1]["date"] == "d36" and "frac" not in lc.points[0]
    assert [p["n_trades"] for p in lc.points] == sorted(p["n_trades"] for p in lc.points)
    assert jobs.LiveCurve().extra() == {}


def test_backtest_job_writes_live_curve_with_every_progress_write(tmp_path, monkeypatch):
    from studio.infrastructure.run_store import FileRunStore
    monkeypatch.setattr(jobs, "LIVE_WRITE_INTERVAL", 0.0)  # 간격 제한 없이 점마다 쓴다
    md = FakeMarketData(make_panel(n=420, seed=5))
    monkeypatch.setattr(jobs, "deps_factory", lambda: jobs.Deps(market_data=md, run_store=FileRunStore(tmp_path / "runs")))
    ctx = _Ctx({"spec": lit_dict(), "run_id": "20260926-170000-aaaaaa"})
    assert jobs.run_backtest_job(ctx) == {"run_id": "20260926-170000-aaaaaa"}
    with_curve = [c for c in ctx.calls if "live_curve" in c[2]]
    assert len(with_curve) > 50
    # 엔진 이후 단계(metrics·done)에도 곡선이 같이 써진다 — 안 그러면 다음 쓰기가 곡선을 지운다
    after = [c for c in ctx.calls if c[0] in ("metrics", "done")]
    assert after and all("live_curve" in c[2] for c in after)
    first = next(c for c in ctx.calls if c[0] == "engine" and "live_curve" in c[2])
    assert len(first[2]["live_curve"]) == 1
    final = ctx.calls[-1][2]["live_curve"]
    assert ctx.calls[-1][0] == "done" and 1 < len(final) <= jobs.LIVE_CURVE_MAX and "frac" not in final[0]
    import json
    assert len(json.dumps(final)) < 60_000  # 파일 크기 상한 근처
    assert "live_curve" not in ctx.calls[0][2]  # 곡선 없는 초기 단계엔 안 붙는다


def test_job_throttles_file_writes_but_last_write_has_the_whole_curve(tmp_path, monkeypatch):
    from studio.infrastructure.run_store import FileRunStore
    monkeypatch.setattr(jobs, "LIVE_WRITE_INTERVAL", 3600.0)  # 엔진 단계 중간 쓰기는 사실상 첫 번째만
    md = FakeMarketData(make_panel(n=420, seed=5))
    monkeypatch.setattr(jobs, "deps_factory", lambda: jobs.Deps(market_data=md, run_store=FileRunStore(tmp_path / "runs")))
    ctx = _Ctx({"spec": lit_dict(), "run_id": "20260926-170000-bbbbbb"})
    jobs.run_backtest_job(ctx)
    engine_writes = [c for c in ctx.calls if c[0] == "engine"]
    assert len(engine_writes) <= 3 and len(ctx.calls) < 20  # 점 175개인데 쓰기는 몇 번뿐
    assert len(ctx.calls[-1][2]["live_curve"]) > 100  # 그러나 단계 전환·완료 쓰기엔 곡선 전체가 실린다
    assert len([c for c in ctx.calls if c[0] == "metrics"][0][2]["live_curve"]) == len(ctx.calls[-1][2]["live_curve"])


def test_curve_n_trades_counts_entries_not_slices():
    md = FakeMarketData(make_panel(n=420, seed=5))
    d = lit_dict()
    d["exits"] = {"take_profit_levels": [{"pct": 4, "fraction": 0.5}, {"pct": 9, "fraction": 1}], "stop_loss_pct": 6}
    pts = []
    rec = run_backtest(Spec.model_validate(d), md, curve=pts.append)
    assert rec.summary["n_entries"] < rec.summary["n_trades"] and pts[-1]["n_trades"] == rec.summary["n_entries"]
