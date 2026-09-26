import numpy as np
import pandas as pd
import pytest

from _precursor_fastpath import SESSION_START
from backtesting.leader_20pct import (
    FEATURE_COLUMNS,
    add_trade_returns,
    cohens_d,
    expected_value,
    lookup_prev_close,
    stock_day_scan,
)


def _hhmmss(sec_from_open: int) -> str:
    total = 9 * 3600 + sec_from_open
    return f"{total // 3600:02d}{total % 3600 // 60:02d}{total % 60:02d}"


def _write_ticks(path, secs, prices, qtys=None, extra=None):
    """정규장 오프셋(초) 리스트로 틱 파일 생성. 원본 관례대로 역시간순 저장."""
    times = [_hhmmss(s) for s in secs]
    prices = list(prices)
    if extra:  # (time문자열, 가격) 추가 - 장외 시간 등
        times += [t for t, _ in extra]
        prices += [p for _, p in extra]
    qtys = qtys or [10] * len(times)
    df = pd.DataFrame({"time": times, "cur_prc": prices, "trde_qty": qtys,
                       "pred_pre_sig": [2] * len(times)})
    df.iloc[::-1].reset_index(drop=True).to_parquet(path)


def test_t0_is_first_tick_over_10pct_and_group_a_needs_20pct(tmp_path):
    path = tmp_path / "2026-08-04.parquet"
    # 전일종가 100 기준: 100에서 시작 -> t=50에 110(+10%) -> t=100에 121(+21%)
    secs = list(range(0, 200))
    prices = [100.0] * 50 + [110.0] * 50 + [121.0] * 100
    _write_ticks(path, secs, prices)

    rec = stock_day_scan(str(path), "TEST", "2026-08-04", prev_close=100.0)

    assert rec["has_t0"] is True
    assert rec["t0_sec"] == 50          # +10%를 처음 넘은 틱
    assert rec["t0_price"] == 110.0
    assert rec["reached_20"] is True    # 이후 121 >= 120
    assert rec["gap_open_over_10"] is False


def test_exact_threshold_price_counts_despite_float_error(tmp_path):
    """[회귀] 100.0*1.10 == 110.00000000000001 이라 '정확히 +10%'인 체결이 조용히
    탈락했다(유닛테스트로 실제 재현). KRX 전일종가는 10의 배수가 흔해 문턱이 합법
    호가에 정확히 떨어지는 일이 드물지 않으므로 A/B 분류를 실제로 틀리게 만든다."""
    path = tmp_path / "2026-08-04.parquet"
    secs = list(range(0, 200))
    prices = [100.0] * 50 + [110.0] * 50 + [120.0] * 100  # 정확히 +10%, 정확히 +20%
    _write_ticks(path, secs, prices)

    rec = stock_day_scan(str(path), "TEST", "2026-08-04", prev_close=100.0)

    assert rec["t0_sec"] == 50       # 110.0 = 정확히 +10% -> T0로 인정돼야 함
    assert rec["reached_20"] is True  # 120.0 = 정확히 +20% -> A군


def test_group_b_when_20pct_never_touched(tmp_path):
    path = tmp_path / "2026-08-04.parquet"
    secs = list(range(0, 200))
    prices = [100.0] * 50 + [119.0] * 150  # +19%까지만 - B군
    _write_ticks(path, secs, prices)

    rec = stock_day_scan(str(path), "TEST", "2026-08-04", prev_close=100.0)

    assert rec["has_t0"] is True
    assert rec["reached_20"] is False
    assert rec["last_price"] == 119.0


def test_features_and_cum_value_use_only_pre_t0_information(tmp_path):
    """T0 이후를 크게 바꿔도 T0 직전 피처·누적대금·순위재료는 안 변해야 한다."""
    secs = list(range(0, 300))
    base = [100.0] * 100 + [110.0] * 200
    mutated = [100.0] * 100 + [110.0] * 50 + [500.0] * 150  # T0(=100) 이후만 변조
    p1, p2 = tmp_path / "2026-08-04.parquet", tmp_path / "2026-08-05.parquet"
    _write_ticks(p1, secs, base)
    _write_ticks(p2, secs, mutated, qtys=[10] * 100 + [999] * 200)  # 거래량까지 변조

    a = stock_day_scan(str(p1), "TEST", "2026-08-04", prev_close=100.0)
    b = stock_day_scan(str(p2), "TEST", "2026-08-05", prev_close=100.0)

    assert a["t0_sec"] == b["t0_sec"] == 100
    assert a["cum_value_eok"] == pytest.approx(b["cum_value_eok"])
    for col in FEATURE_COLUMNS:
        x, y = a.get(col), b.get(col)
        if x is None or (isinstance(x, float) and np.isnan(x)):
            continue
        assert x == pytest.approx(y), f"{col}이 T0 이후 변조에 영향받음(look-ahead)"
    # 음성대조: 라벨(+20% 도달)은 미래를 보므로 실제로 갈려야 한다
    assert a["reached_20"] is False and b["reached_20"] is True


def test_out_of_session_ticks_are_filtered(tmp_path):
    """README 경고: 정규장(09:00:00~15:30:00) 밖 체결은 반드시 빠져야 한다."""
    path = tmp_path / "2026-08-04.parquet"
    secs = list(range(0, 100))
    prices = [100.0] * 100
    # 장전 08:30 에 +50% 가격, 장후 16:00 에 +60% 가격을 심어둔다
    _write_ticks(path, secs, prices, extra=[("083000", 150.0), ("160000", 160.0)])

    rec = stock_day_scan(str(path), "TEST", "2026-08-04", prev_close=100.0)

    assert rec["has_t0"] is False       # 정규장 안에선 +10%를 못 넘었다
    assert rec["kept_rows"] < rec["raw_rows"]
    assert rec["last_price"] == 100.0   # 장후 160원이 종가로 잡히면 안 됨


def test_trade_returns_v1_sells_at_target_and_v2_at_close():
    df = pd.DataFrame({
        "prev_close": [100.0, 100.0], "t0_price": [110.0, 110.0],
        "last_price": [125.0, 95.0], "reached_20": [True, False],
    })

    out = add_trade_returns(df)

    # V1: A군은 +20%(=120)에 매도 -> 120/110-1, B군은 종가 95 -> 95/110-1
    assert out["gross_v1"].iloc[0] == pytest.approx(120 / 110 - 1)
    assert out["gross_v1"].iloc[1] == pytest.approx(95 / 110 - 1)
    # V2: 둘 다 종가 청산 (A군도 125로 청산, 목표가 가정 없음)
    assert out["gross_v2"].iloc[0] == pytest.approx(125 / 110 - 1)
    assert (out["net_v1"] < out["gross_v1"]).all()  # 비용이 반드시 차감됨


def test_expected_value_mixes_base_rate_and_both_groups():
    df = add_trade_returns(pd.DataFrame({
        "prev_close": [100.0] * 4, "t0_price": [110.0] * 4,
        "last_price": [125.0, 95.0, 95.0, 95.0], "reached_20": [True, False, False, False],
    }))

    ev = expected_value(df, "테스트")

    assert ev["base_rate_pct"] == pytest.approx(25.0)
    assert ev["net_v1_pct"] == pytest.approx(100 * df["net_v1"].mean())


def test_lookup_prev_close_takes_previous_trading_day_not_same_day():
    s = pd.Series([100.0, 200.0], index=pd.to_datetime(["2026-08-03", "2026-08-04"]))

    assert lookup_prev_close(s, "2026-08-04") == 100.0   # 당일(200) 아님
    assert lookup_prev_close(s, "2026-08-03") is None    # 직전 거래일 없음


def test_cohens_d_sign_and_scale():
    a = np.array([2.0, 2.0, 3.0, 3.0])
    b = np.array([0.0, 0.0, 1.0, 1.0])

    assert cohens_d(a, b) > 0
    assert cohens_d(b, a) == pytest.approx(-cohens_d(a, b))
