"""일반 모드 엔진(fills + portfolio) — 손으로 계산한 시나리오 + 항등식 + 카나리아 C1."""
import numpy as np
import pandas as pd
import pytest

from studio.domain.costs import CostModel
from studio.domain.engine.fills import ExitRules, FillRules
from studio.domain.engine.portfolio import PortfolioRules, run_portfolio
from studio.domain.models import ExitReason, Panel

RATE = CostModel(commission_rate=0.001, tax_rate=0.002, slippage_mode="rate", slippage_rate=0.01)
NOCOST = CostModel(0.0, 0.0, "rate", 0.0)


def mkpanel(bars: dict, n=None, volume=1_000_000.0):
    """bars[code] = [(open, high, low, close), ...]"""
    n = n or max(len(v) for v in bars.values())
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    def col(k):
        return pd.DataFrame({c: [b[k] for b in v] + [np.nan] * (n - len(v)) for c, v in bars.items()}, index=idx)
    o, h, l, c = col(0), col(1), col(2), col(3)
    vol = c.notna().astype(float) * volume
    return Panel(o, h, l, c, vol, c * vol, c.shift(1))


def sig(panel, at: dict[int, list[str]]):
    df = pd.DataFrame(False, index=panel.close.index, columns=panel.close.columns)
    for i, cs in at.items():
        for c in cs:
            df.iloc[i, df.columns.get_loc(c)] = True
    return df


def flat(n, px=100.0):
    return [(px, px, px, px)] * n


def run(panel, ent, ext=None, cost=RATE, exit_rules=ExitRules(), fill=FillRules(), port=PortfolioRules()):
    return run_portfolio(panel, ent, ext, cost, exit_rules, fill, port)


def test_signal_entry_exit_hand_computed():
    p = mkpanel({"A": flat(6)})
    r = run(p, sig(p, {0: ["A"]}), sig(p, {2: ["A"]}), port=PortfolioRules(initial_capital=100_000, max_positions=1))
    (t,) = r.trades
    # 진입 봉1 시가 100*(1.01)=101, 수량 floor(100000/(101*1.001))=989
    assert t.entry_ts == p.close.index[1] and t.entry_price == pytest.approx(101.0) and t.qty == 989
    assert t.exit_ts == p.close.index[3] and t.exit_price == pytest.approx(99.0)
    assert t.exit_reason == ExitReason.SIGNAL and t.bars_held == 2
    buy_c, sell_c = 101 * 989 * 0.001, 99 * 989 * 0.001
    tax = 99 * 989 * 0.002
    assert t.commission == pytest.approx(buy_c + sell_c) and t.tax == pytest.approx(tax)
    assert t.gross_pnl == pytest.approx((99 - 101) * 989)
    assert t.net_pnl == pytest.approx((99 - 101) * 989 - buy_c - sell_c - tax)
    assert t.slippage_cost == pytest.approx(1 * 989 + 1 * 989)  # 편도 1원씩
    assert r.equity["equity"].iloc[-1] == pytest.approx(100_000 + t.net_pnl)


def test_gap_stop_fills_at_open_not_line():
    bars = flat(2) + [(90, 91, 88, 89)] + flat(2, 89)
    p = mkpanel({"A": bars})
    r = run(p, sig(p, {0: ["A"]}), cost=NOCOST, exit_rules=ExitRules(stop_loss_pct=5))
    (t,) = r.trades
    assert t.exit_reason == ExitReason.STOP and t.exit_price == 90  # 손절선 95 가 아니라 시가


def test_intrabar_stop_at_line_with_slippage():
    bars = flat(2) + [(100, 101, 94, 96)] + flat(2, 96)
    p = mkpanel({"A": bars})
    r = run(p, sig(p, {0: ["A"]}), cost=RATE, exit_rules=ExitRules(stop_loss_pct=5))
    (t,) = r.trades
    line = 101 * 0.95  # 진입가(슬리피지 포함) 기준 손절선
    assert t.exit_reason == ExitReason.STOP and t.exit_price == pytest.approx(line * 0.99)


def test_same_bar_policy():
    bars = flat(2) + [(100, 110, 90, 100)] + flat(2)
    p = mkpanel({"A": bars})
    kw = dict(cost=NOCOST, exit_rules=ExitRules(stop_loss_pct=5, take_profit_pct=5))
    assert run(p, sig(p, {0: ["A"]}), **kw).trades[0].exit_reason == ExitReason.STOP
    r = run(p, sig(p, {0: ["A"]}), fill=FillRules(same_bar_policy="target_first"), **kw)
    assert r.trades[0].exit_reason == ExitReason.TARGET and r.trades[0].exit_price == pytest.approx(105)


def test_trailing_peak_updates_after_judgment():
    # 봉1: 시가 100 매수, 고가 120 저가 95 — 트레일링 10% 는 진입가 기준(90)이라 안 걸린다
    # 봉2: 고점 120 → 선 108, 저가 107 → 108 에 청산
    bars = [(100,) * 4, (100, 120, 95, 110), (110, 112, 107, 108), (100,) * 4]
    p = mkpanel({"A": bars})
    r = run(p, sig(p, {0: ["A"]}), cost=NOCOST, exit_rules=ExitRules(trailing_stop_pct=10))
    (t,) = r.trades
    assert t.exit_ts == p.close.index[2] and t.exit_reason == ExitReason.TRAILING
    assert t.exit_price == pytest.approx(108)
    assert t.mfe_pct == pytest.approx(20) and t.mae_pct == pytest.approx(-5)


def test_trailing_not_updated_before_same_bar_judgment():
    # 봉1 고가 200 → 같은 봉에서 선이 올라가 저가에 걸리면 안 된다(순서 5 는 판정 뒤)
    bars = [(100,) * 4, (100, 200, 95, 150), (150,) * 4]
    p = mkpanel({"A": bars})
    r = run(p, sig(p, {0: ["A"]}), cost=NOCOST, exit_rules=ExitRules(trailing_stop_pct=10))
    # 봉1 에선 안 걸림(고점 갱신은 판정 뒤) — 봉2 시가 150 이 선(200×0.9=180) 아래라 갭으로 시가 청산
    t = r.trades[0]
    assert t.exit_ts == p.close.index[2] and t.exit_reason == ExitReason.TRAILING and t.exit_price == 150


def test_max_holding_bars_exits_at_close():
    bars = [(100,) * 4, (100, 101, 99, 100), (100, 101, 99, 101), (100, 101, 99, 102), (100,) * 4]
    p = mkpanel({"A": bars})
    r = run(p, sig(p, {0: ["A"]}), cost=NOCOST, exit_rules=ExitRules(max_holding_bars=3))
    (t,) = r.trades
    assert t.exit_reason == ExitReason.TIME and t.exit_ts == p.close.index[3]  # 진입 봉1 포함 3번째 봉
    assert t.exit_price == 102 and t.bars_held == 3


def test_upper_limit_buy_cancelled_sell_carried():
    # 봉2 시가 130 = 전일 종가 100 의 상한가 → 매수 취소(그날만, 이월 없음)
    bars = flat(2) + [(130, 130, 130, 130)] + flat(3, 130)
    p = mkpanel({"A": bars})
    r = run(p, sig(p, {1: ["A"]}), cost=NOCOST)
    assert r.trades == [] and r.skipped["upper_limit"] == 1
    # 매도: 보유 중 하한가 잠김(봉3 시가 70) → 봉4 로 이월
    bars = flat(3) + [(70, 70, 70, 70), (75, 76, 74, 75), (75,) * 4]
    p = mkpanel({"A": bars})
    r = run(p, sig(p, {0: ["A"]}), sig(p, {2: ["A"]}), cost=NOCOST)
    (t,) = r.trades
    assert t.exit_ts == p.close.index[4] and t.exit_price == 75 and t.exit_reason == ExitReason.SIGNAL


def test_slots_rank_and_skips():
    p = mkpanel({"A": flat(4), "B": flat(4), "C": flat(4)})
    p.value.loc[:, "B"] *= 5  # B 가 거래대금 1위
    r = run(p, sig(p, {0: ["A", "B", "C"]}), cost=NOCOST, port=PortfolioRules(max_positions=2))
    assert {f.code for f in r.fills} == {"B", "A"} and r.skipped["slots_full"] == 1


def test_exit_slot_reused_same_bar():
    p = mkpanel({"A": flat(5), "B": flat(5)})
    r = run(p, sig(p, {0: ["A"], 1: ["B"]}), sig(p, {1: ["A"]}), cost=NOCOST, port=PortfolioRules(max_positions=1))
    # 봉2 시가: A 청산(순서1) 뒤 B 진입(순서2) — 같은 봉에서 슬롯 재사용
    assert {f.code for f in r.fills if f.ts == p.close.index[2]} == {"A", "B"} and r.skipped["slots_full"] == 0


def test_cash_limit_and_volume_cap():
    p = mkpanel({"A": flat(4)}, volume=1000)
    r = run(p, sig(p, {0: ["A"]}), cost=NOCOST, fill=FillRules(volume_cap_pct=10),
            port=PortfolioRules(initial_capital=1_000_000, max_positions=1))
    assert r.trades[0].qty == 100  # 거래량 1000 × 10%
    p = mkpanel({"A": flat(4)})
    r = run(p, sig(p, {0: ["A"]}), cost=NOCOST, port=PortfolioRules(initial_capital=50, max_positions=1))
    assert r.skipped["cash"] == 1 and not r.trades


def test_sizing_modes():
    bars = flat(2) + [(100, 100, 100, 200)] + flat(3, 200)
    p = mkpanel({"A": bars, "B": flat(6)})
    ent = sig(p, {0: ["A"], 3: ["B"]})
    ext = sig(p, {2: ["A"]})  # 봉3 시가 200 에 청산 → 현금 500+1000, 슬롯이 커진 뒤 B 진입
    base = dict(cost=NOCOST)
    fixed = run(p, ent, ext, **base, port=PortfolioRules(initial_capital=1000, max_positions=2))
    comp = run(p, ent, ext, **base, port=PortfolioRules(initial_capital=1000, max_positions=2,
                                                   sizing="equal_slot_compound"))
    assert fixed.fills[0].qty == 5 and comp.fills[0].qty == 5
    qty_b = lambda r: [f.qty for f in r.fills if f.code == "B"][0]  # noqa: E731
    assert qty_b(fixed) == 5
    assert qty_b(comp) == 7  # 전 봉 평가금 1500 → 슬롯 750 → 7주 (복리)
    fa = run(p, ent, **base, port=PortfolioRules(initial_capital=1000, sizing="fixed_amount", fixed_amount=300))
    assert fa.fills[0].qty == 3
    rk = run(p, ent, **base, exit_rules=ExitRules(stop_loss_pct=10),
             port=PortfolioRules(initial_capital=10_000, sizing="risk_pct", risk_pct=1, max_positions=5))
    assert rk.fills[0].qty == 10  # 손실 허용 100 ÷ (100×10%) = 10주
    cap = run(p, ent, **base, port=PortfolioRules(initial_capital=10_000, sizing="fixed_amount",
                                                  fixed_amount=9000, max_weight_pct=25))
    assert cap.fills[0].qty == 25


def test_end_of_data_closes_at_last_close():
    p = mkpanel({"A": flat(3), "B": flat(6, 50)})
    r = run(p, sig(p, {0: ["A"]}), cost=NOCOST, port=PortfolioRules(max_positions=2))
    (t,) = r.trades
    assert t.exit_reason == ExitReason.END_OF_DATA and t.exit_ts == p.close.index[2]
    assert r.diagnostics["end_of_data"] == ["A"]


def test_equity_identity_random():
    rng = np.random.default_rng(5)
    n, codes = 80, list("ABCDEFGH")
    bars = {}
    for c in codes:
        cl = 100 * np.cumprod(1 + rng.normal(0, 0.03, n))
        op = np.r_[cl[0], cl[:-1]] * (1 + rng.normal(0, 0.01, n))
        bars[c] = list(zip(op, np.maximum(op, cl) * 1.01, np.minimum(op, cl) * 0.99, cl))
    p = mkpanel(bars)
    ent = pd.DataFrame(rng.random((n, 8)) < 0.1, index=p.close.index, columns=codes)
    ext = pd.DataFrame(rng.random((n, 8)) < 0.05, index=p.close.index, columns=codes)
    r = run(p, ent, ext, cost=CostModel(), exit_rules=ExitRules(stop_loss_pct=6, take_profit_pct=12,
                                                                trailing_stop_pct=8, max_holding_bars=15),
            port=PortfolioRules(initial_capital=10_000_000, max_positions=3))
    eq = r.equity
    assert (eq["cash"] + eq["positions_value"] - eq["equity"]).abs().max() < 1e-6
    assert eq["cash"].min() >= -1e-6
    assert eq["n_positions"].max() <= 3
    assert len(r.trades) > 5
    # 마지막 봉에 전부 청산 → 최종 평가금 = 초기 + Σ순손익 (수수료·세금·슬리피지 전부 현금에 반영)
    assert eq["n_positions"].iloc[-1] == 0
    assert eq["equity"].iloc[-1] == pytest.approx(10_000_000 + sum(t.net_pnl for t in r.trades), abs=1e-4)
    for t in r.trades:  # 체결 후 봉 안에서 진입 → 청산 순서
        assert t.exit_ts >= t.entry_ts and t.bars_held >= 1


def test_c1_lookahead_canary():
    """C1 — t 이후 봉을 ×10 으로 망가뜨려도 t 이하 결과, (t+1 이후만 망가뜨리면) t+1 이하 체결이 불변."""
    rng = np.random.default_rng(9)
    n, codes = 60, list("ABCDE")
    bars = {}
    for c in codes:
        cl = 100 * np.cumprod(1 + rng.normal(0, 0.03, n))
        op = np.r_[cl[0], cl[:-1]] * (1 + rng.normal(0, 0.01, n))
        bars[c] = list(zip(op, np.maximum(op, cl) * 1.01, np.minimum(op, cl) * 0.99, cl))
    p = mkpanel(bars)
    ent = pd.DataFrame(rng.random((n, 5)) < 0.15, index=p.close.index, columns=codes)
    ext = pd.DataFrame(rng.random((n, 5)) < 0.08, index=p.close.index, columns=codes)
    kw = dict(cost=CostModel(), exit_rules=ExitRules(stop_loss_pct=5, take_profit_pct=10, trailing_stop_pct=7,
                                                     max_holding_bars=10),
              fill=FillRules(volume_cap_pct=50), port=PortfolioRules(max_positions=3, sizing="equal_slot_compound"))
    base = run_portfolio(p, ent, ext, kw["cost"], kw["exit_rules"], kw["fill"], kw["port"])

    def mutate(after: int) -> Panel:
        f = lambda df: df.where(pd.DataFrame(np.broadcast_to(np.arange(n)[:, None] <= after, df.shape), index=df.index, columns=df.columns), df * 10)  # noqa: E731
        return Panel(*(f(getattr(p, k)) for k in ("open", "high", "low", "close", "volume", "value")),
                     prev_close=f(p.prev_close))

    for t_ in (15, 30, 45):
        # (a) t 이후 전부 변조 → t 이하 체결·평가금 불변
        r = run_portfolio(mutate(t_), ent, ext, kw["cost"], kw["exit_rules"], kw["fill"], kw["port"])
        ts = p.close.index[t_]
        assert [f for f in r.fills if f.ts <= ts] == [f for f in base.fills if f.ts <= ts]
        pd.testing.assert_frame_equal(r.equity[r.equity.ts <= ts], base.equity[base.equity.ts <= ts])
        # (b) t+1 이후만 변조 → t+1 이하 체결 불변 (t+1 봉 체결은 t 신호 + t+1 봉만 쓴다)
        r = run_portfolio(mutate(t_ + 1), ent, ext, kw["cost"], kw["exit_rules"], kw["fill"], kw["port"])
        ts1 = p.close.index[t_ + 1]
        assert [f for f in r.fills if f.ts <= ts1] == [f for f in base.fills if f.ts <= ts1]
    assert len(base.fills) > 10
    # 변조가 실제로 뒤쪽 결과를 바꿨는지 — 카나리아가 둔감하면 위 불변은 아무것도 증명 못 한다
    r = run_portfolio(mutate(15), ent, ext, kw["cost"], kw["exit_rules"], kw["fill"], kw["port"])
    assert [f for f in r.fills if f.ts > p.close.index[15]] != [f for f in base.fills if f.ts > p.close.index[15]]


def test_volume_cap_uses_signal_bar_volume_canary():
    """거래량 한도는 전 봉(신호 봉) 거래량 기준 — 체결 봉 거래량을 바꿔도 체결·수량 불변, 전 봉을 바꾸면 변한다."""
    p = mkpanel({"A": flat(4)}, volume=1000)
    kw = dict(cost=NOCOST, fill=FillRules(volume_cap_pct=10), port=PortfolioRules(initial_capital=1_000_000,
                                                                                 max_positions=1))

    def with_vol(bar, k):
        v = p.volume.copy()
        v.iloc[bar] *= k
        return Panel(p.open, p.high, p.low, p.close, v, p.close * v, p.prev_close)

    ent = sig(p, {0: ["A"]})
    base = run(p, ent, **kw)
    assert base.trades[0].qty == 100  # 전 봉(봉0) 거래량 1000 × 10%
    for k in (0.01, 100):  # 체결 봉(봉1) 거래량
        assert run(with_vol(1, k), ent, **kw).fills == base.fills
    assert run(with_vol(0, 0.01), ent, **kw).trades[0].qty == 1  # 전 봉이 바뀌면 수량이 바뀐다
    r = run(with_vol(0, 0.0), ent, **kw)  # 전 봉 거래량 0 → 한도 0 → 막는다
    assert not r.trades and r.skipped["volume_cap"] == 1


def test_halted_bar_volume_zero_is_untradable():
    """일봉 캐시는 거래정지일을 직전 종가로 채우고 거래량 0 — 그 봉엔 체결하지 않는다."""
    p = mkpanel({"A": flat(6)})
    v = p.volume.copy()
    v.iloc[1] = 0.0  # 봉1(진입 예정 봉) 거래정지
    pn = Panel(p.open, p.high, p.low, p.close, v, p.close * v, p.prev_close)
    r = run(pn, sig(pn, {0: ["A"]}), cost=NOCOST)
    assert r.skipped["no_data"] == 1 and not r.trades  # 신호는 봉0 하나뿐 — 정지 봉엔 못 산다
    # 보유 중 정지 → 청산 신호는 다음 거래 가능 봉으로 이월
    v = p.volume.copy()
    v.iloc[3] = 0.0
    pn = Panel(p.open, p.high, p.low, p.close, v, p.close * v, p.prev_close)
    r = run(pn, sig(pn, {0: ["A"]}), sig(pn, {2: ["A"]}), cost=NOCOST)
    assert r.trades[0].exit_ts == pn.close.index[4] and r.trades[0].exit_reason == ExitReason.SIGNAL


def test_rank_by_change_pct():
    bars = {"A": flat(4), "B": [(100,) * 4, (100, 100, 100, 110), (110,) * 4, (110,) * 4], "C": flat(4)}
    p = mkpanel(bars)
    p.value.loc[:, "C"] *= 9  # 거래대금은 C 가 1위지만 등락률은 B — 신호 봉 = 봉1
    r = run(p, sig(p, {1: ["A", "B", "C"]}), cost=NOCOST, port=PortfolioRules(max_positions=1, rank_by="change_pct"))
    assert [f.code for f in r.fills if f.side == "buy"] == ["B"]
