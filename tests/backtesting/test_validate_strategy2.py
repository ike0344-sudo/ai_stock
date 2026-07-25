import pandas as pd

from backtesting.validate_strategy2 import compute_episode_metrics, simulate_all_episodes


def _bars(rows: list[tuple]) -> pd.DataFrame:
    """rows: (time, open, high, low, close) 튜플 목록."""
    idx = pd.DatetimeIndex([pd.Timestamp(t) for t, *_ in rows])
    return pd.DataFrame(
        [{"open": o, "high": h, "low": lo, "close": c, "volume": 1000} for _, o, h, lo, c in rows], index=idx
    )


def test_simulate_all_episodes_full_cycle_entry_then_touch_exit():
    # compute_ma는 close만 보므로 close=1000을 유지하는 한 60선은 정확히 1000으로
    # 고정된다 — low/high만 바꿔 밴드 터치(진입)/60선 터치(청산)를 유발한다.
    rows = [(f"2026-01-01 09:{i:02d}:00", 1000, 1000, 1000, 1000) for i in range(60)]
    rows.append(("2026-01-01 10:00:00", 1000, 1000, 900, 1000))  # 저가가 1차밴드(910) 하회 -> 진입
    rows.append(("2026-01-01 10:15:00", 1000, 1005, 1000, 1000))  # 고가가 60선(1000) 터치 -> 청산
    candles = _bars(rows)

    episodes = simulate_all_episodes(candles, ma_window=60)

    assert len(episodes) == 1
    ep = episodes[0]
    assert ep["n_tiers"] == 1
    assert ep["exit_reason"] == "touch_ma"
    assert ep["net_pct"] > 0  # 910대에 사서 1000 근처에 팔았으니 수수료/슬리피지 감안해도 순이익


def test_simulate_all_episodes_hard_stop_exit():
    rows = [(f"2026-01-01 09:{i:02d}:00", 1000, 1000, 1000, 1000) for i in range(60)]
    rows.append(("2026-01-01 10:00:00", 950, 950, 900, 1000))  # 1차 밴드 터치 -> 진입(평단≈910)
    rows.append(("2026-01-01 10:15:00", 950, 950, 700, 1000))  # 평단 대비 -20% 밑으로 급락 -> 하드스톱
    candles = _bars(rows)

    episodes = simulate_all_episodes(candles, ma_window=60)

    assert episodes[0]["exit_reason"] == "hard_stop"
    assert episodes[0]["net_pct"] < -0.15  # 하드스톱이므로 손실폭이 커야 함


def test_hard_stop_does_not_reopen_in_the_same_bar_it_closed():
    # 회귀 테스트 — 하드스톱 발동가(평단*0.8)는 항상 1차 밴드가(60선*0.91)보다 낮아,
    # "청산확인→진입확인"을 같은 봉/같은 가격으로 순서대로 실행하면 청산 직후 곧바로
    # 재매수(휩쏘)돼버리는 버그가 있었다(oversold_trading_loop.run_oversold_trading_loop도
    # 동일하게 수정). 막 청산된 봉에서는 재진입하지 않아야 한다.
    rows = [(f"2026-01-01 09:{i:02d}:00", 1000, 1000, 1000, 1000) for i in range(60)]
    rows.append(("2026-01-01 10:00:00", 950, 950, 900, 1000))  # 1차 밴드 터치 -> 진입(평단≈910)
    rows.append(("2026-01-01 10:15:00", 950, 950, 700, 1000))  # 하드스톱 -> 청산, 같은 봉 재진입 금지
    candles = _bars(rows)

    episodes = simulate_all_episodes(candles, ma_window=60)

    assert len(episodes) == 1  # 재진입 없이 하드스톱 청산 하나로 끝나야 함
    assert episodes[0]["exit_reason"] == "hard_stop"


def test_can_reenter_on_the_next_bar_after_a_close():
    # 재진입 자체가 막힌 건 아니고 "같은 봉"만 금지 — 청산된 다음 봉에서 다시 밴드를
    # 찍으면 정상적으로 새 에피소드가 열려야 한다.
    rows = [(f"2026-01-01 09:{i:02d}:00", 1000, 1000, 1000, 1000) for i in range(60)]
    rows.append(("2026-01-01 10:00:00", 950, 950, 900, 1000))  # 1차 밴드 터치 -> 진입
    rows.append(("2026-01-01 10:15:00", 950, 950, 700, 1000))  # 하드스톱 -> 청산 (재진입 금지)
    rows.append(("2026-01-01 10:30:00", 950, 950, 700, 1000))  # 다음 봉 -> 재진입 허용돼야 함
    candles = _bars(rows)

    episodes = simulate_all_episodes(candles, ma_window=60)

    assert len(episodes) == 2
    assert episodes[0]["exit_reason"] == "hard_stop"
    assert episodes[1]["entry_time"] == pd.Timestamp("2026-01-01 10:30:00")


def test_compute_episode_metrics_matches_hand_calculation():
    episodes = [
        {"entry_time": pd.Timestamp("2026-01-01"), "exit_time": pd.Timestamp("2026-01-02"), "net_pct": 0.04},
        {"entry_time": pd.Timestamp("2026-01-05"), "exit_time": pd.Timestamp("2026-01-05"), "net_pct": -0.02},
    ]
    metrics = compute_episode_metrics(episodes)

    assert metrics["n_trades"] == 2
    assert metrics["win_rate_pct"] == 50.0
    assert metrics["profit_factor"] == 2.0
    assert metrics["total_return_pct_simple_sum"] == 2.0


def test_compute_episode_metrics_empty_is_zero():
    metrics = compute_episode_metrics([])
    assert metrics["n_trades"] == 0
    assert metrics["total_return_pct_simple_sum"] == 0.0
