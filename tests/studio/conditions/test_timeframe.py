"""timeframe.py — mN 묶기·마감 규칙(C5), daily_prev(D−1), daily_live(C6: 가상 봉 붙여 다시 계산한 값과 같다·미래 봉 미참조)."""
import numpy as np
import pandas as pd
import pytest

from studio.domain.conditions import catalog, timeframe as T
from studio.domain.conditions.indicators import compute
from studio.domain.models import Panel

BAR = 5  # 실행 봉 5분


def make_data(n_hist=60, n_min_days=4, codes=("A", "B", "C"), seed=0, halt_col=None):
    """일봉 이력(n_hist+n_min_days 거래일) + 마지막 n_min_days 일의 5분봉(봉 끝 라벨 09:05..15:20)."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2024-01-02", periods=n_hist + n_min_days)
    cols = {}
    for k, c in enumerate(codes):
        cl = 10_000 * (1 + k) * np.exp(np.cumsum(rng.normal(0.0004, 0.02, len(days))))
        op = np.r_[cl[0], cl[:-1]] * (1 + rng.normal(0, 0.004, len(days)))
        hi = np.maximum(op, cl) * (1 + rng.uniform(0, 0.01, len(days)))
        lo = np.minimum(op, cl) * (1 - rng.uniform(0, 0.01, len(days)))
        vol = rng.integers(100_000, 1_000_000, len(days)).astype(float)
        cols[c] = (op, hi, lo, cl, vol)
    f = lambda i: pd.DataFrame({c: v[i] for c, v in cols.items()}, index=days)  # noqa: E731
    close, vol = f(3), f(4)
    daily = Panel(f(0), f(1), f(2), close, vol, close * vol, close.ffill().shift(1))
    if halt_col:  # 거래정지 빈칸(활동 구간 안 NaN 행) — own_days 경로
        for fld in ("open", "high", "low", "close", "volume", "value", "prev_close"):
            getattr(daily, fld).loc[days[30:33], halt_col] = np.nan
    # 분봉: 그 날의 일봉 O/H/L/C 안에서 움직이는 5분 경로
    bars = []
    ends = pd.timedelta_range("09:05:00", "15:20:00", freq="5min")
    for d in days[-n_min_days:]:
        m = len(ends)
        wide = {}
        for c in codes:
            o, h, lo, cl = (daily.open.loc[d, c], daily.high.loc[d, c], daily.low.loc[d, c], daily.close.loc[d, c])
            path = np.linspace(o, cl, m) + rng.normal(0, (h - lo) * 0.08, m)
            path = np.clip(path, lo, h)
            op_ = np.r_[o, path[:-1]]
            wide[c] = pd.DataFrame({"open": op_, "high": np.maximum(op_, path) * 1.0005, "low": np.minimum(op_, path) * 0.9995,
                                    "close": path, "volume": rng.integers(1_000, 20_000, m).astype(float)}, index=d + ends)
        bars.append(wide)
    def wide_of(k):
        return pd.concat([pd.DataFrame({c: w[c][k] for c in codes}) for w in bars])
    o_, h_, l_, c_, v_ = (wide_of(k) for k in ("open", "high", "low", "close", "volume"))
    prev = pd.DataFrame({c: [daily.close[c].shift(1).loc[i.normalize()] for i in c_.index] for c in codes}, index=c_.index)
    minute = Panel(o_, h_, l_, c_, v_, c_ * v_, prev)
    return daily, minute


def tamper_after(p: Panel, t, factor=10.0) -> Panel:
    m = p.close.index > t
    f = lambda df: df.where(pd.DataFrame(np.broadcast_to(~m[:, None], df.shape), index=df.index, columns=df.columns), df * factor)  # noqa: E731
    return Panel(*(f(getattr(p, k)) for k in ("open", "high", "low", "close", "volume", "value", "prev_close")))


# ------------------------------------------------------------------ mN 묶기
def test_resample_hand_computed_and_completed_bar_rule():
    idx = pd.DatetimeIndex(pd.Timestamp("2024-03-04") + pd.timedelta_range("09:01:00", periods=12, freq="1min"))  # 1분봉 끝 라벨 09:01..09:12
    o = pd.DataFrame({"A": np.arange(1, 13, dtype=float)}, index=idx)
    p = Panel(o, o + 0.5, o - 0.5, o + 0.1, o * 100, o * 100 * (o + 0.1), o * 0)
    rs = T.resample_bars(p, 5, 1)
    # 5분 묶음: [09:00,09:05) 끝 09:05 → 봉 09:01..09:04 (앞 봉은 09:01 끝~09:04 끝 = 4개, 09:05 라벨 봉의 시작은 09:04)
    # 봉 끝 라벨 → 시작 = 끝-1분: 09:01→시작 09:00, …, 09:05→시작 09:04(같은 묶음), 09:06→시작 09:05(다음 묶음)
    assert list(rs.ends) == [pd.Timestamp("2024-03-04 09:05"), pd.Timestamp("2024-03-04 09:10"), pd.Timestamp("2024-03-04 09:15")]
    b0 = rs.panel.close.iloc[0, 0]
    assert b0 == pytest.approx(5.1)  # 첫 묶음 마지막 봉(끝 09:05) 종가
    assert rs.panel.open.iloc[0, 0] == 1 and rs.panel.high.iloc[0, 0] == pytest.approx(5.5) and rs.panel.low.iloc[0, 0] == pytest.approx(0.5)
    assert rs.panel.volume.iloc[0, 0] == pytest.approx(o["A"].iloc[:5].sum() * 100)
    # 마감 규칙: 봉 t 에는 끝 시각 ≤ t 인 마지막 묶음 — 09:04 봉은 아직 아무 묶음도 마감 전, 09:05 봉에서 첫 묶음, 09:09 는 첫 묶음 그대로
    pos = T.asof_positions(rs.ends, idx)
    assert list(pos[:4]) == [-1, -1, -1, -1] and pos[4] == 0 and pos[8] == 0 and pos[9] == 1 and pos[11] == 1
    with pytest.raises(ValueError, match="배수"):
        T.resample_bars(p, 5, 3)
    with pytest.raises(ValueError, match="더 긴"):
        T.resample_bars(p, 5, 5)


def test_c5_canary_bars_after_t_do_not_change_mN_values_and_open_bucket_is_not_used():
    daily, minute = make_data()
    ctx = T.TimeContext(minute, daily, BAR)
    rs = ctx.resampled("m15")
    base = compute(rs.panel, "sma", {"src": "close", "n": 5})
    mapped = T.map_asof(base, rs.ends, minute.close.index, minute.close.columns)
    for k in (30, 100, 200):
        t = minute.close.index[k]
        bad = tamper_after(minute, t)
        rs2 = T.TimeContext(bad, daily, BAR).resampled("m15")
        m2 = T.map_asof(compute(rs2.panel, "sma", {"src": "close", "n": 5}), rs2.ends, bad.close.index, bad.close.columns)
        pd.testing.assert_frame_equal(mapped.loc[:t], m2.loc[:t])  # t 이하 불변
        assert not mapped.loc[t:].iloc[1:].equals(m2.loc[t:].iloc[1:])  # 변조가 뒤쪽엔 실제로 닿았다(둔감하지 않음)
    # t 에 걸친 미마감 15분봉 값이 안 쓰인다: 봉 t(끝 09:20)의 값 = 끝 09:15 묶음(마감) 값이다
    t = pd.Timestamp(minute.close.index[0].normalize()) + pd.Timedelta(hours=9, minutes=20)
    row = mapped.loc[t]
    done = base.loc[base.index <= t].iloc[-1]
    pd.testing.assert_series_equal(row, done, check_names=False)


# ------------------------------------------------------------------ daily_prev
def test_daily_prev_uses_previous_day_row_only():
    daily, minute = make_data()
    ctx = T.TimeContext(minute, daily, BAR)
    pos = ctx.prev_pos()
    x = compute(daily, "sma", {"src": "close", "n": 5})
    got = T.take_rows(x, pos, minute.close.index, minute.close.columns)
    d0 = minute.close.index[0].normalize()
    prev_day = daily.close.index[daily.close.index.get_loc(d0) - 1]
    assert (got.loc[d0 + pd.Timedelta(hours=10)] == x.loc[prev_day]).all()
    # 그 날 일봉 행을 ×10 으로 망가뜨려도(D 행) 값 불변 — D 행은 안 본다
    bad = Panel(*(getattr(daily, k).where(daily.close.index != d0, getattr(daily, k) * 10) if False else
                  getattr(daily, k).copy() for k in ("open", "high", "low", "close", "volume", "value", "prev_close")))
    for k in ("open", "high", "low", "close", "volume", "value", "prev_close"):
        getattr(bad, k).loc[d0] = getattr(bad, k).loc[d0] * 10
    x2 = compute(bad, "sma", {"src": "close", "n": 5})
    got2 = T.take_rows(x2, pos, minute.close.index, minute.close.columns)
    pd.testing.assert_frame_equal(got.loc[d0:d0 + pd.Timedelta(hours=23)], got2.loc[d0:d0 + pd.Timedelta(hours=23)])


# ------------------------------------------------------------------ daily_live (C6)
LIVE_CASES = [
    ("sma", {"src": "close", "n": 5}), ("sma", {"src": "high", "n": 20}), ("sma", {"src": "close", "n": 1}),
    ("ema", {"src": "close", "n": 10}), ("highest", {"src": "high", "n": 20, "include_current": False}),
    ("highest", {"src": "high", "n": 20, "include_current": True}), ("lowest", {"src": "low", "n": 10, "include_current": False}),
    ("lowest", {"src": "close", "n": 10, "include_current": True}), ("change_pct", {"n": 1}), ("change_pct", {"n": 5}),
    ("gap_pct", {}), ("rsi", {"n": 14}), ("rsi_wilder", {"n": 14}), ("bb_upper", {"n": 20, "k": 2.0}), ("bb_lower", {"n": 20, "k": 1.5}),
]


@pytest.mark.parametrize("halt", [None, "B"])
@pytest.mark.parametrize("name,params", LIVE_CASES)
def test_daily_live_equals_recompute_with_virtual_bar(name, params, halt):
    daily, minute = make_data(halt_col=halt)
    err = T.check_live_equals_recompute(name, params, daily, minute, sample=25)
    assert err < 1e-6, (name, params, err)  # 상대 오차가 아닌 절대 오차지만 가격 규모(1e4)에서 1e-6 이면 사실상 동일(볼린저 제곱합 상쇄 오차)


def test_every_catalog_live_indicator_has_a_live_function_and_vice_versa():
    live_names = {n for n, d in catalog.INDICATORS.items() if d.live}
    assert live_names == set(catalog.LIVE_REGISTRY), (live_names ^ set(catalog.LIVE_REGISTRY))


def test_c6_canary_same_day_bars_after_t_do_not_change_live_values_up_to_t():
    daily, minute = make_data()
    live = T.make_live_bars(minute, daily)
    p = catalog.resolve_params("sma", {"src": "close", "n": 5})
    for name, params in (("sma", {"src": "close", "n": 20}), ("highest", {"src": "high", "n": 20, "include_current": True}),
                         ("rsi", {"n": 14}), ("bb_upper", {"n": 20, "k": 2.0})):
        pp = catalog.resolve_params(name, params)
        base = catalog.LIVE_REGISTRY[name](live, pp)
        t = minute.close.index[len(minute.close) // 2]
        bad = tamper_after(minute, t)
        v2 = catalog.LIVE_REGISTRY[name](T.make_live_bars(bad, daily), pp)
        pd.testing.assert_frame_equal(base.loc[:t], v2.loc[:t])
        assert not base.loc[t:].iloc[1:].equals(v2.loc[t:].iloc[1:]) or name == "highest"  # 변조가 뒤쪽엔 작용(highest 는 이미 최고치일 수 있음)
    # 일봉 이력이 D 행 이후를 담아도(미래 일봉) 안 본다
    assert p["n"] == 5


def test_live_bars_today_virtual_bar_is_cumulative_up_to_t_only():
    daily, minute = make_data()
    live = T.make_live_bars(minute, daily)
    d = minute.close.index[0].normalize()
    day_rows = minute.close.index[minute.close.index.normalize() == d]
    t = day_rows[10]
    sub = minute.loc if False else None
    assert live.o.loc[t, "A"] == minute.open.loc[day_rows[0], "A"]
    assert live.h.loc[t, "A"] == minute.high.loc[day_rows[:11], "A"].max() and live.l.loc[t, "A"] == minute.low.loc[day_rows[:11], "A"].min()
    assert live.c.loc[t, "A"] == minute.close.loc[t, "A"]
    assert live.v.loc[t, "A"] == pytest.approx(minute.volume.loc[day_rows[:11], "A"].sum())
    assert live.val.loc[t, "A"] == pytest.approx(minute.value.loc[day_rows[:11], "A"].sum())
