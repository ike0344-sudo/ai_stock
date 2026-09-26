"""청산 확장(studio-conditions c2) — 손계산 시나리오(SC-C7) + 진입 기준 집계 + 카나리아 C7.

모든 시나리오: 비용 0, 자본 100,000·슬롯 1 → 시가 100 에 1,000주. 신호는 0번 봉 종가, 체결은 1번 봉 시가(100).
"""
import numpy as np
import pandas as pd
import pytest

from studio.domain.conditions.evaluator import evaluate
from studio.domain.conditions.ast import Group
from studio.domain.conditions.position import PosExitPlan
from studio.domain.engine.fills import ExitRules, FillRules
from studio.domain.engine.portfolio import PortfolioRules, run_portfolio
from studio.domain.metrics import collapse_entries, standard_metrics
from studio.domain.models import ExitReason

from .test_engine import NOCOST, flat, mkpanel, sig

PORT = PortfolioRules(initial_capital=100_000, max_positions=1)
E = lambda **k: ExitRules(**k)  # noqa: E731


def go(bars, rules=ExitRules(), fill=FillRules(), ext=None, plan=None, at=0):
    p = mkpanel({"A": bars})
    return p, run_portfolio(p, sig(p, {at: ["A"]}), ext, NOCOST, rules, fill, PORT, pos_exit=plan)


def rows(r):
    return [(t.exit_ts.day, t.qty, round(t.exit_price, 6), t.exit_reason, t.entry_id, t.slice, round(t.net_pnl, 6)) for t in r.trades]


def path(closes):
    """종가 열 → 봉: 시가 = 전 봉 종가(0번 봉은 종가와 같다), 고저는 시가·종가 사이."""
    out, prev = [], closes[0]
    for k, c in enumerate(closes):
        o = c if k == 0 else prev
        out.append((o, max(o, c), min(o, c), c))
        prev = c
    return out


def day(p, i):
    return p.close.index[i].day


# ---------------------------------------------------------------- 분할 익절
def test_partial_take_profit_two_levels_hand_computed():
    bars = [(100, 100, 100, 100), (100, 103, 99, 102), (102, 106, 101, 105), (105, 111, 104, 110), (110, 110, 110, 110)]
    p, r = go(bars, E(take_profit_levels=((5, 0.5), (10, 1.0))))
    assert rows(r) == [
        (day(p, 2), 500, 105.0, ExitReason.TARGET, 0, 1, 2500.0),   # +5% 선(105) — 1,000주의 절반
        (day(p, 3), 500, 110.0, ExitReason.TARGET, 0, 2, 5000.0),   # +10% 선(110) — 남은 500주 전부
    ]
    assert [t.net_pct for t in r.trades] == [pytest.approx(0.05), pytest.approx(0.10)]
    assert r.equity["equity"].iloc[-1] == pytest.approx(107_500)
    m = standard_metrics(r, 100_000)
    # 진입 한 건: 순손익 7,500 · 수익률 7,500/100,000 — 조각 둘이 아니라 한 건으로 센다
    assert m["num_trades"] == 1 and m["num_slices"] == 2 and m["win_rate_pct"] == 100.0
    assert m["expectancy_pct"] == pytest.approx(7.5)


def test_win_rate_is_by_entry_not_by_slice():
    """첫 조각은 이익, 나머지는 손절 — 조각으로 세면 승률 50%, 진입으로 세면 0%(순손익 −2,500)."""
    bars = [(100, 100, 100, 100), (100, 103, 99, 102), (102, 106, 101, 105), (105, 106, 88, 89), (89, 89, 89, 89)]
    p, r = go(bars, E(take_profit_levels=((5, 0.5),), stop_loss_pct=10))
    assert rows(r) == [(day(p, 2), 500, 105.0, ExitReason.TARGET, 0, 1, 2500.0),
                       (day(p, 3), 500, 90.0, ExitReason.STOP, 0, 2, -5000.0)]
    m = standard_metrics(r, 100_000)
    assert m["num_trades"] == 1 and m["win_rate_pct"] == 0.0 and m["expectancy_pct"] == pytest.approx(-2.5)
    assert m["profit_factor"] == 0.0 and m["max_consec_losses"] == 1
    # 거래표(DataFrame) 쪽도 같다 — collapse_entries
    df = pd.DataFrame([{"code": t.code, "entry_ts": t.entry_ts, "entry_price": t.entry_price, "exit_ts": t.exit_ts,
                        "exit_price": t.exit_price, "qty": t.qty, "gross_pnl": t.gross_pnl, "commission": t.commission, "tax": t.tax,
                        "slippage_cost": t.slippage_cost, "net_pnl": t.net_pnl, "net_pct": t.net_pct, "bars_held": t.bars_held,
                        "exit_reason": str(t.exit_reason), "entry_id": t.entry_id, "slice": t.slice} for t in r.trades])
    c = collapse_entries(df)
    assert len(c) == 1 and c["qty"].iloc[0] == 1000 and c["net_pnl"].iloc[0] == pytest.approx(-2500)
    assert c["net_pct"].iloc[0] == pytest.approx(-0.025) and c["exit_price"].iloc[0] == pytest.approx(97.5)


def test_gap_over_levels_sells_them_all_at_the_open():
    bars = [(100, 100, 100, 100), (100, 103, 99, 102), (111, 112, 110, 111), (111, 111, 111, 111)]
    p, r = go(bars, E(take_profit_levels=((5, 0.5), (10, 1.0))))
    assert rows(r) == [(day(p, 2), 500, 111.0, ExitReason.TARGET, 0, 1, 5500.0), (day(p, 2), 500, 111.0, ExitReason.TARGET, 0, 2, 5500.0)]


def test_same_bar_stop_and_level_follow_same_bar_policy():
    bars = [(100, 100, 100, 100), (100, 103, 99, 102), (102, 106, 89, 95), (95, 95, 95, 95)]
    rules = E(take_profit_levels=((5, 0.5),), stop_loss_pct=10)
    p, r = go(bars, rules, FillRules("stop_first"))  # 보수적: 전량 손절선(90)
    assert rows(r) == [(day(p, 2), 1000, 90.0, ExitReason.STOP, 0, 1, -10000.0)]
    p, r = go(bars, rules, FillRules("target_first"))  # 선(105)에 절반 먼저, 남은 절반은 그 봉 손절선
    assert rows(r) == [(day(p, 2), 500, 105.0, ExitReason.TARGET, 0, 1, 2500.0), (day(p, 2), 500, 90.0, ExitReason.STOP, 0, 2, -5000.0)]


def test_level_qty_floor_min_one_and_full_when_one_share_left():
    from studio.domain.engine.fills import level_qty
    assert level_qty(1000, 0.5) == 500 and level_qty(7, 0.5) == 3 and level_qty(1, 0.5) == 1 and level_qty(3, 0.1) == 1
    assert level_qty(100, 0.29) == 29  # 부동소수 오차(28.999…)로 한 주 빠지지 않는다
    assert level_qty(5, 1.0) == 5


def test_partial_sells_split_the_entry_commission():
    """수수료 0.1%·세금 0.2%: 조각마다 매수 수수료를 판 수량만큼 나눠 싣는다(합 = 원래 수수료)."""
    cost = __import__("studio.domain.costs", fromlist=["CostModel"]).CostModel(0.001, 0.002, "rate", 0.0)
    bars = [(100, 100, 100, 100), (100, 103, 99, 102), (102, 106, 101, 105), (105, 111, 104, 110), (110, 110, 110, 110)]
    p = mkpanel({"A": bars})
    r = run_portfolio(p, sig(p, {0: ["A"]}), None, cost, E(take_profit_levels=((5, 0.5), (10, 1.0))), FillRules(), PORT)
    qty = int(100_000 // (100 * 1.001))  # 999
    a, b = r.trades
    assert a.qty + b.qty == qty
    buy_c = 100 * qty * 0.001
    assert a.commission + b.commission == pytest.approx(buy_c + 105 * a.qty * 0.001 + 110 * b.qty * 0.001)
    assert a.tax == pytest.approx(105 * a.qty * 0.002) and b.tax == pytest.approx(110 * b.qty * 0.002)
    assert sum(t.net_pnl for t in r.trades) == pytest.approx(r.equity["equity"].iloc[-1] - 100_000)


# ---------------------------------------------------------------- 종가 확인 익절
def test_take_profit_close_mode_sells_next_open_after_close_confirms():
    bars = [(100, 100, 100, 100), (100, 104, 99, 104), (104, 110, 103, 106), (107, 108, 106, 107), (107, 107, 107, 107)]
    p, r = go(bars, E(take_profit_pct=5, take_profit_mode="close"))
    # 1번 봉 종가 104 < 105 → 유지, 2번 봉 종가 106 ≥ 105 → 3번 봉 **시가**(107)에 판다(봉 안 즉시라면 2번 봉 105 에 팔렸을 것)
    assert rows(r) == [(day(p, 3), 1000, 107.0, ExitReason.TARGET, 0, 1, 7000.0)]
    p, r = go(bars, E(take_profit_pct=5))
    assert rows(r) == [(day(p, 2), 1000, 105.0, ExitReason.TARGET, 0, 1, 5000.0)]


def test_take_profit_close_mode_with_levels():
    bars = [(100, 100, 100, 100), (100, 104, 99, 104), (104, 113, 103, 112), (112, 113, 111, 112), (112, 112, 112, 112)]
    p, r = go(bars, E(take_profit_levels=((5, 0.5), (10, 1.0)), take_profit_mode="close"))
    assert rows(r) == [(day(p, 3), 500, 112.0, ExitReason.TARGET, 0, 1, 6000.0), (day(p, 3), 500, 112.0, ExitReason.TARGET, 0, 2, 6000.0)]


# ---------------------------------------------------------------- 트레일링 발동·본전
def test_trail_activation_waits_for_max_return():
    bars = [(100, 100, 100, 100), (100, 104, 99, 103), (103, 105, 97, 98), (98, 112, 98, 111), (111, 111, 105, 106), (106, 106, 106, 106)]
    # 발동 조건 없음: 2번 봉(저가 97)이 고점 105 대비 −5% 선(99.75)... 1번 봉 고점 104 → 선 98.8 에 걸린다
    p, r = go(bars, E(trailing_stop_pct=5))
    assert rows(r)[0][:4] == (day(p, 2), 1000, 98.8, ExitReason.TRAILING)
    # 발동 10%: 3번 봉 고가 112 로 넘은 뒤 **다음 봉(4)** 부터 — 고점 112 의 −5% = 106.4, 4번 봉 저가 105 → 106.4 에 청산
    p, r = go(bars, E(trailing_stop_pct=5, trail_activate_pct=10))
    (t,) = r.trades
    assert (t.exit_ts, t.exit_reason) == (p.close.index[4], ExitReason.TRAILING) and t.exit_price == pytest.approx(106.4)


def test_breakeven_moves_stop_to_entry_from_next_bar():
    bars = [(100, 100, 100, 100), (100, 106, 99, 105), (105, 105, 99.5, 100), (100, 100, 100, 100)]
    p, r = go(bars, E(stop_loss_pct=10, breakeven_after_pct=5))
    # 1번 봉 고가 106 ≥ 105 → 다음 봉부터 손절선 = 매수가 100. 2번 봉 저가 99.5 ≤ 100 → 100 에 청산(원래 손절선 90 은 안 닿음)
    assert rows(r) == [(day(p, 2), 1000, 100.0, ExitReason.STOP, 0, 1, 0.0)]
    p, r = go(bars, E(stop_loss_pct=10))
    assert r.trades[0].exit_reason == ExitReason.END_OF_DATA  # 본전 이동이 없으면 안 닿는다
    # 2번 봉 시가가 이미 100 아래면(갭) 시가에 청산
    bars2 = [(100, 100, 100, 100), (100, 106, 99, 105), (98, 99, 97, 98), (98, 98, 98, 98)]
    p, r = go(bars2, E(stop_loss_pct=10, breakeven_after_pct=5))
    assert rows(r)[0][:4] == (day(p, 2), 1000, 98.0, ExitReason.STOP)


def test_engine_rules_reject_inconsistent_combinations():
    with pytest.raises(ValueError, match="같이 쓸 수 없다"):
        ExitRules(take_profit_pct=5, take_profit_levels=((5, 1.0),))
    with pytest.raises(ValueError, match="오름차순"):
        ExitRules(take_profit_levels=((10, 0.5), (5, 1.0)))
    with pytest.raises(ValueError, match="trailing_stop_pct"):
        ExitRules(trail_activate_pct=5)


# ---------------------------------------------------------------- 포지션 조건 청산
def grp(*conds, logic="all", **kw):
    return Group.model_validate({"logic": logic, "items": list(conds), **kw})


POS = lambda n: {"kind": "pos", "name": n}  # noqa: E731
K = lambda v: {"kind": "const", "value": v}  # noqa: E731
C = lambda l, op, r=None, **k: {"left": l, "op": op, **({"right": r} if r is not None else {}), **k}  # noqa: E731


def plan_for(bars, group):
    p = mkpanel({"A": bars})
    return PosExitPlan(group, p)


def test_pos_return_pct_exit_executes_next_open():
    bars = [(100, 100, 100, 100), (100, 103, 99, 102), (102, 107, 101, 106), (107, 108, 106, 107), (107, 107, 107, 107)]
    plan = plan_for(bars, grp(C(POS("return_pct"), "gte", K(5))))
    p, r = go(bars, plan=plan)
    # 1번 봉 종가 +2% → 유지, 2번 봉 종가 +6% ≥ 5 → 3번 봉 시가(107)에 판다, 사유 signal
    assert rows(r) == [(day(p, 3), 1000, 107.0, ExitReason.SIGNAL, 0, 1, 7000.0)]


def test_pos_bars_held_counts_entry_bar_as_one():
    bars = flat(8)
    p, r = go(bars, plan=plan_for(bars, grp(C(POS("bars_held"), "gte", K(3)))))
    # 진입 봉(1)=1봉, 2번 봉=2봉, 3번 봉=3봉 → 3번 봉 종가에 참 → 4번 봉 시가에 청산
    assert rows(r)[0][0] == day(p, 4)


def test_pos_drawdown_and_max_return():
    bars = [(100, 100, 100, 100), (100, 110, 99, 108), (108, 109, 104, 105), (105, 105, 105, 105), (105, 105, 105, 105)]
    # 1번 봉: 최고가 110·종가 108 → 낙폭 1.82%(<3) / 2번 봉: 최고가 110·종가 105 → 4.55% ≥ 3 → 3번 봉 시가 105
    plan = plan_for(bars, grp(C(POS("drawdown_pct"), "gte", K(3)), C(POS("max_return_pct"), "gte", K(9.99))))
    p, r = go(bars, plan=plan)
    assert rows(r) == [(day(p, 3), 1000, 105.0, ExitReason.SIGNAL, 0, 1, 5000.0)]
    # max_return_pct 는 보유 중 고가 기준 — 종가가 아니라 110 → +10%
    plan2 = plan_for(bars, grp(C(POS("max_return_pct"), "gt", K(9.99)), C(POS("drawdown_pct"), "lt", K(1))))
    p, r = go(bars, plan=plan2)  # 1번 봉: 최고 +10%, 낙폭 1.82 → 거짓 / 이후 낙폭이 더 커져 계속 거짓 → 데이터 끝 청산
    assert r.trades[0].exit_reason == ExitReason.END_OF_DATA


def test_pos_mixed_with_static_condition_and_or():
    bars = [(100, 100, 100, 100), (100, 103, 99, 102), (102, 107, 101, 106), (107, 108, 106, 107), (107, 107, 107, 107), (107, 107, 107, 107)]
    static = C({"kind": "field", "name": "close"}, "gt", K(106.5))  # 3번 봉(종가 107)부터 참
    p, r = go(bars, plan=plan_for(bars, grp(C(POS("return_pct"), "gte", K(5)), static)))
    assert rows(r)[0][0] == day(p, 4)  # 둘 다 참인 첫 봉 = 3번 봉 → 4번 봉 시가
    p, r = go(bars, plan=plan_for(bars, grp(C(POS("return_pct"), "gte", K(5)), static, logic="any")))
    assert rows(r)[0][0] == day(p, 3)  # 하나만 참이면 되는 2번 봉 → 3번 봉 시가


def test_pos_cross_and_hold_use_the_position_own_history():
    closes = [100, 104, 106, 107, 103, 106, 106]
    bars = path(closes)
    # 수익률(진입 시가 100 기준): 1번 봉 4% · 2번 6% · 3번 7% · 4번 3% · 5번 6% · 6번 6%
    plan = plan_for(bars, grp(C(POS("return_pct"), "cross_above", K(5))))
    p, r = go(bars, plan=plan)
    assert rows(r)[0][0] == day(p, 3)  # 2번 봉 종가에 5% 를 아래→위로 넘었다 → 3번 봉 시가
    plan = plan_for(bars, grp(C(POS("return_pct"), "gte", K(5), hold=2)))
    p, r = go(bars, plan=plan)
    assert rows(r)[0][0] == day(p, 4)  # 2번·3번 봉 연속 만족 → 3번 봉 종가에 참 → 4번 봉 시가
    plan = plan_for(bars, grp(C(POS("return_pct"), "cross_above_within", K(5), within=3), C(POS("return_pct"), "lt", K(4))))
    p, r = go(bars, plan=plan)
    # 2번 봉에서 5% 를 넘었고(최근 3봉 = 2·3·4번 봉 안), 수익률이 4% 아래로 내려온 첫 봉 = 4번 봉(3%) → 5번 봉 시가(= 4번 봉 종가 103)
    assert rows(r)[0][:3] == (day(p, 5), 1000, 103.0)
    # negate: pos 조건의 반대 — 값이 있으면 뒤집힌다
    plan = plan_for(bars, grp(C(POS("return_pct"), "lt", K(5)), negate=True))
    p, r = go(bars, plan=plan)
    assert rows(r)[0][0] == day(p, 3)


def test_pos_state_is_per_position_and_reset_on_reentry():
    """hold 연속 횟수·cross 이전 값이 다음 진입으로 새지 않는다 — 두 번 진입해도 같은 결정."""
    closes = [100, 106, 106, 100, 100, 106, 106, 100, 100]
    bars = path(closes)
    p = mkpanel({"A": bars})
    plan = PosExitPlan(grp(C(POS("return_pct"), "gte", K(5), hold=2)), p)
    ent = sig(p, {0: ["A"], 4: ["A"]})
    r = run_portfolio(p, ent, None, NOCOST, ExitRules(), FillRules(), PORT, pos_exit=plan)
    exits = [t.exit_ts for t in r.trades]
    # 1차: 진입 1번 봉(시가 100) → 1·2번 봉 종가 +6% 연속 → 3번 봉 종가... hold=2 는 2번 봉 종가에 참 → 3번 봉 시가 106 에 청산
    assert exits[0] == p.close.index[3]
    assert len(r.trades) == 2 and r.trades[1].entry_ts == p.close.index[5]


def test_pos_condition_needs_pos_exit_plan_shape():
    bars = flat(4)
    p = mkpanel({"A": bars})
    other = PosExitPlan(grp(C(POS("return_pct"), "gte", K(5))), mkpanel({"A": flat(6)}))
    with pytest.raises(ValueError, match="pos_exit"):
        run_portfolio(p, sig(p, {0: ["A"]}), None, NOCOST, ExitRules(), FillRules(), PORT, pos_exit=other)


# ---------------------------------------------------------------- C7 카나리아
class _Log:
    """decide() 결과를 (봉, 종목, 결과) 로 남기는 감싸개 — 엔진 안 결정 시점을 직접 본다."""

    def __init__(self, plan):
        self.plan, self.log = plan, []
        self.shape, self.bar_minutes = plan.shape, plan.bar_minutes

    def new_state(self):
        return self.plan.new_state()

    def decide(self, i, c, st, vals):
        out = self.plan.decide(i, c, st, vals)
        self.log.append((i, c, out, tuple(round(v, 9) for v in vals.values() if v == v)))
        return out

    def sliced(self, mask):
        return self


def test_c7_tampering_after_t_never_changes_position_decisions_up_to_t():
    from tests.studio.conditions.helpers import synth_panel, tamper_after
    panel = synth_panel(n_days=160, n_codes=6, seed=5)
    t = panel.close.index[100]
    entry = Group.model_validate({"logic": "all", "items": [
        C({"kind": "field", "name": "close"}, "gt", {"kind": "ind", "name": "sma", "params": {"n": 10}})]})
    exit_ = Group.model_validate({"logic": "any", "items": [
        C(POS("return_pct"), "gte", K(6)), C(POS("drawdown_pct"), "gte", K(4)), C(POS("bars_held"), "gte", K(8)),
        {"logic": "all", "items": [C(POS("return_pct"), "lt", K(0)),
                                   C({"kind": "ind", "name": "rsi", "params": {"n": 5}}, "lt", K(45))]}]})

    def run_on(pn):
        ev = evaluate(entry, exit_, pn)
        log = _Log(ev.pos_exit)
        r = run_portfolio(pn, ev.entry, ev.exit, NOCOST, ExitRules(stop_loss_pct=8), FillRules(), PortfolioRules(max_positions=3), pos_exit=log)
        return r, log.log

    r0, log0 = run_on(panel)
    r1, log1 = run_on(tamper_after(panel, t))
    upto = lambda log: [x for x in log if x[0] <= 100]  # noqa: E731
    assert upto(log0) == upto(log1) and len(upto(log0)) > 50  # t 까지의 청산 결정(입력 값 포함)이 똑같다
    assert sum(1 for x in upto(log0) if x[2]) >= 3  # 카나리아가 살아 있다 — 실제로 참이 된 결정이 있다
    assert log0 != log1  # 그리고 변조가 t 이후엔 실제로 영향을 준다
    f0 = [f for f in r0.fills if f.ts <= t]
    f1 = [f for f in r1.fills if f.ts <= t]
    assert [(f.ts, f.code, f.side, f.qty, f.price) for f in f0] == [(f.ts, f.code, f.side, f.qty, f.price) for f in f1]
    assert any(t_.exit_reason == ExitReason.SIGNAL for t_ in r0.trades)


def test_c7_canary_detects_a_leaky_position_rule():
    """카나리아 자체 검증 — 다음 봉 종가를 엿보는 일부러 새는 규칙은 t 이하 결정이 달라져 잡힌다."""
    from tests.studio.conditions.helpers import synth_panel, tamper_after
    panel = synth_panel(n_days=160, n_codes=4, seed=5)
    t = panel.close.index[100]
    entry = Group.model_validate({"logic": "all", "items": [
        C({"kind": "field", "name": "close"}, "gt", {"kind": "ind", "name": "sma", "params": {"n": 10}})]})
    exit_ = Group.model_validate({"logic": "any", "items": [C(POS("return_pct"), "gte", K(1000))]})

    def run_on(pn):
        ev = evaluate(entry, exit_, pn)
        closes = pn.close.to_numpy()

        class Leaky(_Log):
            def decide(self, i, c, st, vals):
                out = bool(closes[min(i + 1, len(closes) - 1), c] > closes[i, c])  # 미래를 본다
                self.log.append((i, c, out, ()))
                return out
        log = Leaky(ev.pos_exit)
        run_portfolio(pn, ev.entry, ev.exit, NOCOST, ExitRules(), FillRules(), PortfolioRules(max_positions=3), pos_exit=log)
        return log.log

    a, b = run_on(panel), run_on(tamper_after(panel, t))
    assert [x for x in a if x[0] <= 100] != [x for x in b if x[0] <= 100]
