"""studio-conditions c8 — 틱 조건 진입(모드 B)에 분봉·일봉 조건 묶음(tick.filter)·일봉 사전 필터(tick.prefilter)를 AND 로.

SC-C8: "체결강도 ≥ 150 그리고 5분봉 20선 위 그리고 일봉 정배열(전일)" — 필터 부분(5분봉 20선 위 + 일봉 정배열)의 초 단위 마스크를 체결에서 손으로 다시 계산해 대조.
카나리아 C8: s 이후 분봉·체결을 변조해도 s 이하 신호·진입 불변, 진행 중인 봉(끝 시각 > s)의 값은 안 쓴다.
"""
import copy

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from studio.application.backtest_service import _strip_new_defaults, family_hash, run_backtest, spec_hash, structure_hash
from studio.application.intraday_service import _daily_frame, _MinuteFilter
from studio.domain.conditions.evaluator import evaluate_group
from studio.domain.conditions.tick import N, align_filter, detect_from_spec, detect_signals
from studio.domain.conditions.tick import TickDay
from studio.domain.spec import Spec, bind_params

from .fakes_intraday import IntradayFake, bars_from_ticks
from .test_intraday_service import tick_dict

F = lambda n="close", **k: {"kind": "field", "name": n, **k}  # noqa: E731
I = lambda n, p=None, **k: {"kind": "ind", "name": n, "params": p or {}, **k}  # noqa: E731
K = lambda v: {"kind": "const", "value": v}  # noqa: E731


def cond(l, op, r=None, **k):
    d = {"left": l, "op": op, **k}
    if r is not None:
        d["right"] = r
    return d


def grp(*items, logic="all", **kw):
    return {"logic": logic, "items": list(items), **kw}


ABOVE_M5_20 = cond(F(tf="m5"), "gt", I("sma", {"src": "close", "n": 20}, tf="m5"))
ALIGNED = [cond(I("sma", {"src": "close", "n": 5}, tf="daily_prev"), "gt", I("sma", {"src": "close", "n": 20}, tf="daily_prev")),
           cond(I("sma", {"src": "close", "n": 20}, tf="daily_prev"), "gt", I("sma", {"src": "close", "n": 60}, tf="daily_prev"))]
ALWAYS = cond(F(), "gt", K(0))
NEVER = cond(F(), "lt", K(0))


def tdict(md, filt=None, pre=None, **over):
    d = tick_dict(md, **over)
    d["tick"] = {**d["tick"], "cooldown_sec": 60}
    d["portfolio"] = {"max_positions": 50}
    if filt is not None:
        d["tick"]["filter"] = filt
    if pre is not None:
        d["tick"]["prefilter"] = pre
    return d


@pytest.fixture(scope="module")
def md():
    return IntradayFake(n_days=12, drift=0.0001, seed=11, bar_minutes=1)


# ------------------------------------------------------------------ 정렬 — 끝 시각 ≤ s 인 마지막 봉 (손계산)
def test_align_filter_uses_last_closed_bar_only():
    m = align_filter(np.array([60, 120, 180]), np.array([True, False, True]))
    assert not m[:60].any()  # 첫 봉이 마감되기 전 = 값 없음
    assert m[60:120].all() and not m[120:180].any() and m[180:].all()  # 봉 끝 시각 s 에 그 봉 값이 열린다(끝 시각 ≤ s)
    assert not align_filter(np.array([], dtype=int), np.array([], dtype=bool)).any()
    # 진행 중인 봉: 120 에 끝나는 봉(값 False)은 s<120 에 안 쓰인다 — 그 봉 값을 바꿔도 s<120 마스크 불변
    a = align_filter(np.array([60, 120]), np.array([True, False]))
    b = align_filter(np.array([60, 120]), np.array([True, True]))
    assert (a[:120] == b[:120]).all() and (a[120:] != b[120:]).all()


def test_detect_signals_ands_the_mask_before_cooldown_hand_calc():
    """틱 조건(일봉 기준선 돌파: 초 100 부터 참) AND 분봉 필터(초 180 부터 참) → 첫 신호는 180, 쿨다운 300 → 다음은 480."""
    sec = np.arange(0, 1200, 10)
    prc = np.where(sec >= 100, 110.0, 90.0)
    day = TickDay("A", pd.Timestamp("2026-01-05").date(), sec, prc, np.full(len(sec), 10), 100.0)
    kw = dict(daily_breakout=(20, 100.0), cooldown_sec=300)
    base = detect_signals(day, **kw)
    assert base.signal_sec[:3].tolist() == [100, 400, 700]
    mask = align_filter(np.array([180, 300]), np.array([True, True]))  # 180 초부터 참
    got = detect_signals(day, extra_mask=mask, **kw)
    assert got.signal_sec.tolist() == [180, 480, 780, 1080]
    assert (got.entry_sec > got.signal_sec).all()
    none = detect_signals(day, extra_mask=np.zeros(N, dtype=bool), **kw)
    assert len(none.signal_sec) == 0


# ------------------------------------------------------------------ SC-C8: 필터 마스크 = 체결에서 손으로 다시 계산
def _hand_masks(md, filt_daily_aligned=True):
    """(code, date) → 길이 N bool. 5분봉 종가 > 5분봉 20선(날을 넘어 이어짐) AND 일봉 정배열(D−1 행: SMA5>SMA20>SMA60)."""
    daily = md.panel.close
    out = {}
    for code in md.tick_codes():
        seq = []  # (date, 봉 끝 시각(초), 종가) — 날짜순, 봉 끝 라벨 기준(체결 없는 봉은 없다)
        for d in md.days:
            sec, prc, qty = md.ticks[(code, d.date())]
            bars = bars_from_ticks(sec, prc, qty, 5)
            for e, v in sorted(bars.items()):
                seq.append((d.date(), e, v[3]))
            last = prc[-1]
            seq.append((d.date(), 23400 + 300, last))  # 15:30 종가 단일가 봉 → 5분 묶음 끝 15:35
        closes = np.array([x[2] for x in seq])
        sma = pd.Series(closes).rolling(20).mean().to_numpy()
        val = closes > sma  # NaN 비교는 False
        for d in md.days:
            pos = daily.index.get_loc(d)
            c = daily[code]
            s5, s20, s60 = (c.iloc[pos - n: pos].mean() for n in (5, 20, 60))  # D−1 행 = D−n..D−1 종가 평균
            aligned = (s5 > s20) and (s20 > s60)
            day_idx = [i for i, x in enumerate(seq) if x[0] == d.date()]
            ends = np.array([seq[i][1] for i in day_idx])
            sec, prc, qty = md.ticks[(code, d.date())]
            m1_ends = np.array(sorted({(int(x) // 60 + 1) * 60 for x in sec}))  # 이 종목 체결이 있는 1분봉의 끝 시각(체결 없는 분은 봉이 없다)
            m = np.zeros(N, dtype=bool)
            for s in range(N):
                j = np.searchsorted(m1_ends, s, side="right") - 1  # s 이하에 마감된 이 종목의 마지막 1분봉
                if j < 0:
                    continue
                t1 = int(m1_ends[j])
                target = (t1 // 300) * 300  # 그 시각에 마감된 마지막 5분봉의 끝 시각(0 이면 아직 오늘 5분봉이 없다 → 전날 마지막 봉)
                k = np.searchsorted(ends, target, side="right") - 1
                gi = day_idx[k] if k >= 0 else (day_idx[0] - 1)  # 전날 마지막 봉(15:35 묶음)
                m[s] = bool(gi >= 0 and val[gi] and (aligned or not filt_daily_aligned))
            out[(code, d.date())] = m
    return out


def _service_masks(md, filt):
    spec = Spec.model_validate(tdict(md, filt))
    bound = bind_params(spec)
    daily, _, _ = _daily_frame(bound, md, md.stock_info(), 600)
    mp = md.minute_panel(md.tick_codes(), md.days[0].date(), md.days[-1].date(), 1)
    ok = evaluate_group(bound.tick.filter, mp, market=md.index_frames(), daily=daily, bar_minutes=1)
    fm = _MinuteFilter(mp, ok)
    return {(c, d.date()): fm.mask(c, d.date()) for c in md.tick_codes() for d in md.days}, daily


def test_sc_c8_filter_mask_equals_hand_calculation_from_ticks(md):
    filt = grp(ABOVE_M5_20, *ALIGNED)
    got, daily = _service_masks(md, filt)
    exp = _hand_masks(md)
    assert got.keys() == exp.keys()
    n_true = 0
    for k in exp:
        assert got[k] is not None
        assert (got[k] == exp[k]).all(), k
        n_true += int(exp[k].sum())
    assert 0 < n_true < len(exp) * N  # 손계산 표본이 의미 있다: 참도 거짓도 있다
    # 5분봉 20선 위만(일봉 정배열 없이)도 같다
    got2, _ = _service_masks(md, grp(ABOVE_M5_20))
    exp2 = _hand_masks(md, filt_daily_aligned=False)
    assert all((got2[k] == exp2[k]).all() for k in exp2) and sum(int(x.sum()) for x in exp2.values()) > n_true


def test_trades_are_signals_and(md):
    """서비스 결과: 필터 항상 참 = 필터 없음과 같은 거래, 항상 거짓 = 0건, 5분봉 20선 필터 = 손계산 마스크를 씌운 신호의 부분집합."""
    key = lambda r: sorted((t.code, t.entry_ts, t.entry_price, t.exit_ts) for t in r.trades.itertuples())  # noqa: E731
    base = run_backtest(Spec.model_validate(tdict(md)), md)
    always = run_backtest(Spec.model_validate(tdict(md, grp(ALWAYS))), md)
    assert len(base.trades) > 10 and key(base) == key(always)
    assert always.summary["tick"]["filter_pairs_without_minutes"] == 0
    never = run_backtest(Spec.model_validate(tdict(md, grp(NEVER))), md)
    assert len(never.trades) == 0
    filt = grp(ABOVE_M5_20)
    rec = run_backtest(Spec.model_validate(tdict(md, filt)), md)
    assert 0 < len(rec.trades) < len(base.trades)
    hand = _hand_masks(md, filt_daily_aligned=False)
    cfg = Spec.model_validate(tdict(md, filt)).tick
    allowed = set()
    for (code, d), mask in hand.items():
        ev = detect_from_spec(md.tick_day(code, d), cfg, extra_mask=mask)
        for es in ev.entry_sec:
            allowed.add((code, pd.Timestamp(d) + pd.Timedelta(seconds=9 * 3600 + int(es))))
    assert {(t.code, t.entry_ts) for t in rec.trades.itertuples()} <= allowed
    assert any("마감 봉" in w for w in rec.warnings)


# ------------------------------------------------------------------ C8 카나리아
@pytest.mark.parametrize("factor", [1.7, 0.3])
def test_c8_canary_ticks_and_minutes_after_s_do_not_change_signals_or_entries_up_to_s(md, factor):
    filt = grp(ABOVE_M5_20)
    spec = Spec.model_validate(tdict(md, filt))
    base = run_backtest(spec, md)
    D0 = md.days[6].date()
    S = 3 * 3600 + 44 * 60 + 30  # D0 12:44:30 — 1분·5분 봉 경계 한가운데(진행 중인 1분봉·5분봉이 변조된다)
    T0 = pd.Timestamp(D0) + pd.Timedelta(seconds=9 * 3600 + S)  # 시각 T0 이후의 체결(그 뒤 날 전체 + D0 의 S 초 이후)만 변조
    bad = copy.copy(md)
    bad.ticks = {k: (s, np.where(np.full(len(s), k[1] > D0) | ((k[1] == D0) & (s > S)), p * factor, p), q) for k, (s, p, q) in md.ticks.items()}
    bad._minute_cache = {}
    rec = run_backtest(spec, bad)
    cut = lambda r: sorted((t.code, t.entry_ts, t.entry_price) for t in r.trades.itertuples() if t.entry_ts <= T0)  # noqa: E731
    assert cut(base) and cut(base) == cut(rec)  # T0 이하 진입 불변
    assert sorted((t.entry_ts, t.entry_price) for t in base.trades.itertuples()) != sorted((t.entry_ts, t.entry_price) for t in rec.trades.itertuples())
    # 신호 단위: T0 이하의 마스크는 변조와 무관(진행 중 1분봉 값·이후 봉을 안 쓴다) — D0 안에서 S 초까지, 그 앞 날은 통째로
    good, _ = _service_masks(md, filt)
    tam, _ = _service_masks(bad, filt)
    for (c, d), m in good.items():
        if d < D0:
            assert (m == tam[(c, d)]).all(), (c, d)
        elif d == D0:
            assert (m[: S + 1] == tam[(c, d)][: S + 1]).all(), (c, d)
    assert any((good[(c, D0)][S + 1:] != tam[(c, D0)][S + 1:]).any() for c in md.tick_codes())  # 카나리아가 살아 있다


def test_c8_canary_daily_row_of_D_and_index_do_not_change_that_days_daily_filter(md):
    """일봉 조건은 D−1 까지 — 그 날(D) 일봉 행을 통째로 변조해도 그날 마스크 불변."""
    filt = grp(*ALIGNED)
    good, _ = _service_masks(md, filt)
    from studio.domain.models import Panel
    bad = copy.copy(md)
    p = md.panel
    d_last = md.days[-1]
    fr = {}
    for k in ("open", "high", "low", "close", "volume", "value", "prev_close"):
        x = getattr(p, k).copy()
        x.loc[d_last] = x.loc[d_last] * 10
        fr[k] = x
    bad.panel = Panel(**fr)
    tam, _ = _service_masks(bad, filt)
    for c in md.tick_codes():
        assert (good[(c, d_last.date())] == tam[(c, d_last.date())]).all()


# ------------------------------------------------------------------ 사전 필터(일봉 D−1)
def test_prefilter_gates_days_by_previous_day_daily_condition(md):
    base = run_backtest(Spec.model_validate(tdict(md)), md)
    yes = run_backtest(Spec.model_validate(tdict(md, pre=grp(ALWAYS))), md)
    no = run_backtest(Spec.model_validate(tdict(md, pre=grp(NEVER))), md)
    key = lambda r: sorted((t.code, t.entry_ts) for t in r.trades.itertuples())  # noqa: E731
    assert key(base) == key(yes) and len(no.trades) == 0
    assert no.summary["tick"]["prefilter_pairs_skipped"] == 60 and yes.summary["tick"]["prefilter_pairs_skipped"] == 0
    # D−1 만 본다: 마지막 날 일봉 행을 변조해도 마지막 날 진입 불변, 그 전날 행을 바꾸면 달라질 수 있다
    pre = grp(cond(F("close"), "gt", I("sma", {"src": "close", "n": 5})))
    from studio.domain.models import Panel
    p = md.panel
    d_last = md.days[-1]
    bad = copy.copy(md)
    fr = {}
    for k in ("open", "high", "low", "close", "volume", "value", "prev_close"):
        x = getattr(p, k).copy()
        x.loc[d_last] = x.loc[d_last] * 10
        fr[k] = x
    bad.panel = Panel(**fr)
    a = run_backtest(Spec.model_validate(tdict(md, pre=pre)), md)
    b = run_backtest(Spec.model_validate(tdict(bad, pre=pre)), bad)
    last = lambda r: sorted((t.code, t.entry_ts) for t in r.trades.itertuples() if t.entry_ts.normalize() == d_last)  # noqa: E731
    assert last(a) == last(b)


def test_missing_minutes_mean_no_entry_and_are_counted():
    md = IntradayFake(n_days=6, drift=0.0001, seed=11, bar_minutes=1)
    full = md.minute_panel

    def no_minutes_for_first_code(codes, start, end, bm, source="al"):
        return full([c for c in codes if c != md.tick_codes_[0]], start, end, bm, source)
    md.minute_panel = no_minutes_for_first_code
    rec = run_backtest(Spec.model_validate(tdict(md, grp(ALWAYS))), md)
    cov = rec.summary["tick"]
    assert cov["filter_pairs_without_minutes"] == 6 and not any(t == md.tick_codes_[0] for t in rec.trades["code"])
    assert any("분봉이 없어" in w for w in rec.warnings)


# ------------------------------------------------------------------ 명세 검증·해시
def test_spec_validation_and_hashes(md):
    with pytest.raises(ValidationError, match="포지션 값"):
        Spec.model_validate(tdict(md, grp(cond({"kind": "pos", "name": "return_pct"}, "gte", K(5)))))
    with pytest.raises(ValidationError, match="entry_source='catalog'"):
        d = tdict(md, grp(ALWAYS))
        d["tick"]["entry_source"] = "minute_refine"
        d["strategy"] = {"source": "builder", "entry": grp(ALWAYS), "exit": grp(ALWAYS, logic="any")}
        Spec.model_validate(d)
    with pytest.raises(ValidationError, match="사전 필터는 일봉"):
        Spec.model_validate(tdict(md, pre=grp(cond(F(tf="daily_prev"), "gt", K(1)))))
    with pytest.raises(ValidationError, match="분봉|배수"):  # m1 은 실행 봉(1분)과 같아 쓸 수 없다 — bar 를 써라
        Spec.model_validate(tdict(md, grp(cond(F(tf="m1"), "gt", K(1)))))
    Spec.model_validate(tdict(md, grp(cond(F(tf="m3"), "gt", K(1)), cond(F(tf="daily_live"), "gt", K(1)), cond(F(), "gt", K(1)))))
    # 해시: 새 칸이 없거나 None 이면 옛 명세와 같다, 켜면 다르다(홀드아웃 엿보기 방지 — 조건을 붙였다 떼는 것도 튜닝)
    base = Spec.model_validate(tdict(md))
    dumped = base.model_dump(mode="json")
    old = copy.deepcopy(dumped)
    old["tick"].pop("filter")
    old["tick"].pop("prefilter")
    assert _strip_new_defaults(dumped) == _strip_new_defaults(old)
    on = Spec.model_validate(tdict(md, grp(ABOVE_M5_20)))
    assert spec_hash(on) != spec_hash(base) and structure_hash(on) != structure_hash(base)
    # 데이터 범위 검사: 분봉 필터를 쓰면 분봉 데이터 범위도 필요
    from studio.domain.spec import validate_against
    probs = validate_against(on, {"tick_al": (md.days[0].date(), md.days[-1].date()), "daily": (md.days[0].date(), md.days[-1].date())})
    assert any(p.dataset == "minute_al" and p.severity == "error" for p in probs)


def test_c8_canary_catches_a_leaky_alignment(md, monkeypatch):
    """카나리아 자체 검증 — 진행 중인 다음 봉을 엿보는(끝 시각 ≤ s+60) 정렬은 s 이하 마스크가 변조에 흔들려 잡힌다."""
    import studio.application.intraday_service as svc

    def leaky(end_sec, ok):
        e = np.asarray(end_sec)
        k = np.searchsorted(e, np.arange(N) + 60, side="right") - 1
        return np.where(k >= 0, np.asarray(ok, dtype=bool)[np.maximum(k, 0)], False) if len(e) else np.zeros(N, dtype=bool)
    monkeypatch.setattr(svc, "align_filter", leaky)
    D0, S = md.days[6].date(), 3 * 3600 + 44 * 60 + 30
    bad = copy.copy(md)
    bad.ticks = {k: (s, np.where(np.full(len(s), k[1] > D0) | ((k[1] == D0) & (s > S)), p * 0.3, p), q) for k, (s, p, q) in md.ticks.items()}
    bad._minute_cache = {}
    filt = grp(ABOVE_M5_20)
    good, _ = _service_masks(md, filt)
    tam, _ = _service_masks(bad, filt)
    assert any((good[(c, D0)][: S + 1] != tam[(c, D0)][: S + 1]).any() for c in md.tick_codes())
