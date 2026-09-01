import numpy as np
import pandas as pd

from backtesting.immediacy_zone import minute_leader_map, time_bucket


def test_time_bucket_boundaries():
    # 자정기준초: 09:00:00=32400, 09:29:59=34199, 09:30:00=34200,
    # 14:59:59=53999, 15:00:00=54000
    t = np.array([32400, 34199, 34200, 53999, 54000, 55800])
    got = time_bucket(t)

    assert list(got) == ["개장30분", "개장30분", "중반", "중반", "마감30분", "마감30분"]


def test_minute_leader_map_maps_name_to_code_and_skips_unmapped(monkeypatch):
    frames = [
        {"t": "09:01", "chgtop": ["A전자", 3.0, 1.0]},
        {"t": "09:02", "chgtop": None},
        {"t": "09:03", "chgtop": ["모르는이름", 5.0, 2.0]},
    ]
    monkeypatch.setattr("backtesting.immediacy_zone.load_full_frames", lambda d: frames)

    m = minute_leader_map("2026-07-01", {"A전자": "000001"})

    assert m == {"09:01": "000001"}  # None 프레임/미매핑 이름은 안 들어간다


def test_minute_leader_map_missing_day_returns_empty(monkeypatch):
    monkeypatch.setattr("backtesting.immediacy_zone.load_full_frames", lambda d: None)

    assert minute_leader_map("2026-07-01", {}) == {}


def test_immediacy_flag_requires_both_no_dip_and_positive_return():
    df = pd.DataFrame({
        "mae_1m": [-0.0005, -0.0005, -0.002, -0.002],   # 안빠짐, 안빠짐, 빠짐, 빠짐
        "ret_1m": [0.001, -0.001, 0.001, -0.001],       # 오름, 내림, 오름, 내림
    })
    no_dip = df["mae_1m"] >= -0.001
    immediacy = no_dip & (df["ret_1m"] > 0)

    assert list(immediacy) == [True, False, False, False]
