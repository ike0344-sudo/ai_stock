import numpy as np
import pandas as pd
import pytest

from _precursor_fastpath import SESSION_START
from backtesting.ladder_exit_scan import ENTRY_PCTS, simulate_ladder, stock_day_scan


def _hhmmss(sec_from_open: int) -> str:
    t = 9 * 3600 + sec_from_open
    return f"{t // 3600:02d}{t % 3600 // 60:02d}{t % 60:02d}"


def _write_ticks(path, secs, prices):
    df = pd.DataFrame({"time": [_hhmmss(s) for s in secs], "cur_prc": prices,
                       "trde_qty": [10] * len(secs), "pred_pre_sig": [2] * len(secs)})
    df.iloc[::-1].reset_index(drop=True).to_parquet(path)


def test_all_three_legs_fill_when_price_runs_past_20pct():
    # 전일종가 100, 진입 105. 가격이 120까지 쭉 오르면 3단 전부 체결.
    r = simulate_ladder(np.array([105.0, 116.0, 118.0, 121.0]), entry_price=105.0, prev_close=100.0)

    assert r["legs_filled"] == 3
    # 115/105-1, 117.5/105-1, 120/105-1 을 1/3씩
    expected = sum((100 * (1 + p) / 105 - 1) / 3 for p in (0.15, 0.175, 0.20))
    assert r["gross"] == pytest.approx(expected)


def test_partial_fill_leaves_remainder_to_close():
    """+15%만 닿고 되돌아 종가 108로 끝나면: 1/3은 115에, 2/3은 108에 청산."""
    r = simulate_ladder(np.array([105.0, 116.0, 110.0, 108.0]), entry_price=105.0, prev_close=100.0)

    assert (r["hit15"], r["hit175"], r["hit20"]) == (True, False, False)
    expected = (115 / 105 - 1) / 3 + (108 / 105 - 1) * (2 / 3)
    assert r["gross"] == pytest.approx(expected)


def test_no_target_hit_exits_entirely_at_close():
    r = simulate_ladder(np.array([105.0, 107.0, 99.0]), entry_price=105.0, prev_close=100.0)

    assert r["legs_filled"] == 0
    assert r["gross"] == pytest.approx(99 / 105 - 1)


def test_stop_loss_fires_before_target_when_it_comes_first():
    """-5% 손절이 먼저 오면 남은 수량 전부 손절가 청산 — 그 뒤 +20%를 찍어도 못 먹는다.
    틱 순서가 있으니 '어느 쪽이 먼저인지' 근사 없이 판정된다."""
    prices = np.array([105.0, 99.0, 125.0])  # 99 = 105*0.943 < 손절가 99.75

    with_stop = simulate_ladder(prices, 105.0, 100.0, stop_pct=-0.05)
    without = simulate_ladder(prices, 105.0, 100.0)

    assert with_stop["stopped"] is True
    assert with_stop["gross"] == pytest.approx(-0.05)
    assert without["legs_filled"] == 3 and without["gross"] > 0  # 손절 없으면 전부 먹는다


def test_stop_does_not_fire_if_target_hit_first():
    prices = np.array([105.0, 121.0, 90.0])  # 먼저 121(전단 체결) 후 폭락

    r = simulate_ladder(prices, 105.0, 100.0, stop_pct=-0.05)

    assert r["legs_filled"] == 3 and r["stopped"] is False  # 이미 전량 청산됨


def test_scan_produces_one_event_per_entry_threshold(tmp_path):
    path = tmp_path / "2026-08-04.parquet"
    # 100 → 109까지 천천히 오름: 5~9% 문턱 5개 전부 발동해야 한다
    secs = list(range(0, 200))
    prices = [100.0] * 50 + [105.0] * 30 + [106.0] * 20 + [107.0] * 20 + [108.0] * 40 + [109.0] * 40
    _write_ticks(path, secs, prices)

    recs = stock_day_scan(str(path), "TEST", "2026-08-04", prev_close=100.0)

    assert len(recs) == len(ENTRY_PCTS)
    by_x = {round(r["entry_pct"], 2): r for r in recs}
    assert by_x[0.05]["t0_sec"] == 50 and by_x[0.05]["entry_price"] == 105.0
    assert by_x[0.09]["t0_sec"] == 160 and by_x[0.09]["entry_price"] == 109.0
    assert all(not r["gap_open"] for r in recs)
    assert all(not r["hit15"] for r in recs)  # +15%엔 못 닿았다


def test_gap_open_flagged_for_low_thresholds_only(tmp_path):
    """첫 틱이 +7%면 5·6·7% 문턱은 갭시작, 8·9%는 정상 진입."""
    path = tmp_path / "2026-08-04.parquet"
    secs = list(range(0, 100))
    prices = [107.0] * 50 + [109.0] * 50
    _write_ticks(path, secs, prices)

    by_x = {round(r["entry_pct"], 2): r for r in stock_day_scan(str(path), "T", "2026-08-04", 100.0)}

    assert by_x[0.05]["gap_open"] and by_x[0.07]["gap_open"]
    assert not by_x[0.09]["gap_open"]


def test_features_use_only_pre_entry_information(tmp_path):
    """진입 이후를 크게 바꿔도 진입 시점 피처·누적대금은 안 변해야 한다."""
    secs = list(range(0, 300))
    base = [100.0] * 100 + [105.0] * 200
    mut = [100.0] * 100 + [105.0] * 50 + [130.0] * 150
    p1, p2 = tmp_path / "2026-08-04.parquet", tmp_path / "2026-08-05.parquet"
    _write_ticks(p1, secs, base)
    _write_ticks(p2, secs, mut)

    a = stock_day_scan(str(p1), "T", "2026-08-04", 100.0)[0]
    b = stock_day_scan(str(p2), "T", "2026-08-05", 100.0)[0]

    assert a["t0_sec"] == b["t0_sec"] == 100
    assert a["cum_value_eok"] == pytest.approx(b["cum_value_eok"])
    for col in ("w10_tick_speed", "w30_tick_speed", "vs3_value_surge", "vs10_value_surge"):
        if not (isinstance(a[col], float) and np.isnan(a[col])):
            assert a[col] == pytest.approx(b[col]), f"{col} look-ahead"
    # 음성대조: 청산 결과는 미래를 보므로 달라져야 한다
    assert a["gross_L3"] != pytest.approx(b["gross_L3"])
