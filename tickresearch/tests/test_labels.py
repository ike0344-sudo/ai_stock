"""라벨 검증 — 사전등록 §4 정의대로 동작하는지.

라벨은 **미래를 봐야 정상**이다(Feature와 반대). 그래서 여기서 막을 것은
"미래를 보는가"가 아니라 **"진입 시점 t의 체결을 진입가로 쓰는가"**(낙관 편향)와
**"어느 barrier를 먼저 쳤는지 순서를 제대로 보는가"**다.
"""
import numpy as np
import pytest

from src.features.grid import N_SEC, SecondGrid
from src.labels.triple_barrier import (BARRIER_EXPIRE, BARRIER_NONE, BARRIER_SL, BARRIER_TP,
                                       breakeven_win_rate, label, round_trip_cost)


def _grid(path, hi=None, lo=None):
    """가격 경로(초 단위) → 최소 격자. 나머지 배열은 라벨이 안 쓴다."""
    px = np.full(N_SEC, float(path[-1]))
    px[:len(path)] = path
    h = px.copy() if hi is None else np.where(np.arange(N_SEC) < len(hi), np.pad(hi, (0, N_SEC - len(hi))), px)
    lw = px.copy() if lo is None else np.where(np.arange(N_SEC) < len(lo), np.pad(lo, (0, N_SEC - len(lo)), constant_values=1e9), px)
    z = np.zeros(N_SEC)
    return SecondGrid(symbol="A", date="2026-08-04", ref_price=1000, price=px, high=h,
                      low=lw, trades=z, volume=z, value=z, buy_volume=z, sell_volume=z,
                      buy_value=z, sell_value=z, has_trade=z.astype(bool),
                      side_source="tick_rule")


def test_entry_price_is_after_signal_not_at_signal():
    """**진입가는 t의 가격이 아니라 t 다음 체결가다.** t 가격으로 사면 낙관 편향."""
    path = [1000, 1010] + [1010] * 500

    r = label(_grid(path), np.array([0]), stop=0.01)

    assert r.entry_price[0] == 1010, "t 시점 가격 1000으로 진입하면 안 된다"


def test_take_profit_first():
    path = [1000] * 10 + [1021] + [1000] * 500      # t=10에 +2.1%

    r = label(_grid(path), np.array([0]), stop=0.01)

    assert r.barrier[0] == BARRIER_TP
    assert r.gross_return[0] == pytest.approx(0.02)          # 목표가에 체결로 본다
    assert r.net_return[0] == pytest.approx(0.02 - r.cost[0])


def test_stop_loss_first_even_if_target_reached_later():
    """**선행 라벨과 갈리는 자리.** 손절 먼저 맞고 나중에 +2% 가면 선행은 양성, 여기선 손절."""
    path = [1000] * 5 + [985] + [1000] * 10 + [1025] + [1000] * 500

    r = label(_grid(path), np.array([0]), stop=0.01)

    assert r.barrier[0] == BARRIER_SL
    assert r.net_return[0] == pytest.approx(-0.01 - r.cost[0])
    assert r.hit[0] == 1.0, "선행 정의(최고가 도달)로는 여전히 양성이어야 한다"


def test_expire_when_neither_barrier_touched():
    path = [1000] * 400

    r = label(_grid(path), np.array([0]), stop=0.01)

    assert r.barrier[0] == BARRIER_EXPIRE
    assert r.gross_return[0] == pytest.approx(0.0)
    assert r.net_return[0] == pytest.approx(-r.cost[0])           # 비용만 나간다


def test_same_second_touch_is_conservative_and_flagged():
    """한 초에 익절·손절이 둘 다 닿으면 순서를 모른다 → 손절로 보고 **표시**한다."""
    path = [1000] * 400
    hi = np.array([1000.0] * 5 + [1025.0])        # t=5의 고가가 +2.5%
    lo = np.array([1000.0] * 5 + [980.0])         # 같은 초 저가가 -2%

    r = label(_grid(path, hi=hi, lo=lo), np.array([0]), stop=0.01)

    assert r.ambiguous[0], "동시 도달을 표시하지 않으면 낙관 편향이 숨는다"
    assert r.barrier[0] == BARRIER_SL


def test_no_label_when_horizon_runs_past_session_end():
    """장 마감까지 5분을 못 채우는 진입은 **라벨을 안 만든다**.

    격자 끝은 마지막 가격이 유지돼 있어 그대로 두면 "5분 들고 있었다"고 착각한다.
    강제청산 값을 섞으면 정의가 다른 표본이 라벨에 들어간다.
    """
    r = label(_grid([1000] * 400), np.array([N_SEC - 10, 0]), stop=0.01)

    assert r.barrier[0] == BARRIER_NONE and np.isnan(r.net_return[0])
    assert r.barrier[1] == BARRIER_EXPIRE and np.isfinite(r.net_return[1])


def test_breakeven_win_rate_matches_preregistration():
    """사전등록 §2 표의 숫자와 같아야 한다 (결과 보기 전에 못 박은 값)."""
    assert breakeven_win_rate(0.005) == pytest.approx(0.408, abs=0.001)
    assert breakeven_win_rate(0.01) == pytest.approx(0.507, abs=0.001)
    assert breakeven_win_rate(0.02) == pytest.approx(0.630, abs=0.001)


def test_cost_is_actually_subtracted():
    """[회귀] 비용 미반영 결과를 성과로 보고하는 것은 금지 사항이다."""
    r = label(_grid([1000] * 10 + [1021] + [1000] * 500), np.array([0]), stop=0.01)

    assert r.net_return[0] < r.gross_return[0]
    assert r.gross_return[0] - r.net_return[0] == pytest.approx(r.cost[0])
    assert r.cost[0] > 0.004


def test_cost_matches_existing_backtesting_implementation():
    """[회귀] **기존 `backtesting/t0_forward_return.py`와 값이 갈리면 안 된다.**

    비용 모델을 복제했으므로 두 구현이 벌어지면 같은 전략이 저장소 안에서
    서로 다른 성적을 내게 된다.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from backtesting.t0_forward_return import round_trip_cost_pct

    px = np.array([1_500.0, 3_000.0, 10_000.0, 30_000.0, 91_500.0, 150_000.0, 600_000.0])

    assert round_trip_cost(px) == pytest.approx(round_trip_cost_pct(px))


def test_low_price_stock_costs_more_than_flat_rate():
    """저가주는 1틱 비율이 커서 고정 0.46%보다 **훨씬 비싸다** — 이걸 놓치면 낙관 편향."""
    cheap, mid = round_trip_cost(np.array([2_100.0])), round_trip_cost(np.array([91_500.0]))

    assert cheap[0] > mid[0]
    assert cheap[0] > 0.0046, "고정 합산값(0.46%)보다 커야 한다"
