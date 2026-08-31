import pandas as pd

from _precursor_fastpath import SESSION_START
from backtesting.shooting_precursor import _tick_rule_direction, compute_stock_day


def test_tick_rule_direction_carries_forward_through_flat_ticks():
    price = [100, 101, 101, 99, 99, 99, 100]

    direction = _tick_rule_direction(pd.Series(price, dtype=float).to_numpy())

    assert list(direction) == [0, 1, 1, -1, -1, -1, 1]


def _make_synthetic_tick_file(path, jump_time_str="090600", jump_price=103.0):
    """09:00~09:14, 1분마다 1틱. jump_time_str부터 가격이 100->jump_price로 점프해
    그 뒤로 유지 - 실제 tick_al 파일처럼 역시간순(최신이 먼저)으로 저장한다."""
    times = [f"09{m:02d}00" for m in range(15)]  # 090000..091400
    prices = [100.0 if t < jump_time_str else jump_price for t in times]
    df = pd.DataFrame({
        "time": times, "cur_prc": prices, "trde_qty": [10] * len(times), "pred_pre_sig": [2] * len(times),
    })
    df.iloc[::-1].reset_index(drop=True).to_parquet(path)  # 역시간순으로 뒤집어 저장


def test_compute_stock_day_labels_shoot_only_while_forward_window_reaches_the_jump(tmp_path):
    path = tmp_path / "20260804.parquet"
    _make_synthetic_tick_file(path)

    dataset, meta = compute_stock_day(str(path), "TEST", "2026-08-04")

    assert meta["raw_rows"] == 15
    assert meta["kept_rows"] == 15
    by_t = dataset.set_index("t_sec")
    t_0900 = SESSION_START
    t_0905 = SESSION_START + 5 * 60
    t_0906 = SESSION_START + 6 * 60
    # 09:00~09:05는 price_t(점프 전, 100)가 아직 점프를 안 본 상태고 forward window
    # 안에 09:06의 +3% 점프가 들어온다 -> 슈팅. 09:06부터는 price_t 자체가 이미
    # 점프를 반영(=103)해서 분자/분모가 같아져 슈팅이 아니다.
    for t in range(t_0900, t_0905 + 1, 60):
        assert bool(by_t.loc[t, "label"]) is True, f"t={t} 는 슈팅이어야 함"
    assert bool(by_t.loc[t_0906, "label"]) is False
    assert by_t.loc[t_0900, "price_t"] == 100.0
    assert by_t.loc[t_0906, "price_t"] == 103.0
    # 고가 대비 위치는 항상 0 이하(당일 최고가를 넘어설 수 없음)
    assert (dataset["high_position"] <= 1e-9).all()


def test_compute_stock_day_breaks_same_second_ties_in_true_chronological_order(tmp_path):
    """같은 초에 여러 체결이 있을 때 진짜 마지막(시간순) 체결가가 남아야 한다 -
    fastpath 원본 버그(역시간순 tie를 그대로 보존)가 재발하면 이 테스트가 깨진다."""
    df = pd.DataFrame({
        "time": ["090000", "090000", "090000"],
        "cur_prc": [100.0, 101.0, 102.0],  # 시간순으로 100->101->102 체결(102가 진짜 마지막)
        "trde_qty": [1, 1, 1],
        "pred_pre_sig": [2, 2, 2],
    })
    # 원본 파일 관례대로 역시간순(최신이 먼저)으로 저장 -> 102,101,100 순
    path = tmp_path / "20260804.parquet"
    df.iloc[::-1].reset_index(drop=True).to_parquet(path)

    dataset, _ = compute_stock_day(str(path), "TEST", "2026-08-04")

    assert dataset.set_index("t_sec").loc[SESSION_START, "price_t"] == 102.0
