"""오늘(또는 지정일) 특정 종목들의 10:00 지표를 찍는다 - 클린20 판단용.

    python today_check.py 006340 009830 058610 036930
    python today_check.py --date=20260810 006340

수식은 reach20_condition_scan.build()와 동일하게 맞춘다 - 과거 통계와 같은 자로 재야
비교가 된다. 분봉/일봉은 API에서 바로 받는다(로컬 캐시는 전일까지라 오늘이 없다).
"""
import os
import sys
from datetime import datetime, time as dtime

import pandas as pd
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backtesting.data_loader import _pages_to_dataframe
from kiwoom_client import KiwoomClient

CUTOFF = dtime(10, 0)
RULE4 = [("10시 등락률 >= 7%", "ret_at_10_pct", 7, "ge"),
         ("레인지 위치 >= 0.8", "pos_in_range_10", 0.8, "ge"),
         ("대금 >= 20일평균 1.5배", "value_vs_20d_avg", 1.5, "ge"),
         ("20일 신고가 돌파", "high_vs_20d_high_pct", 0, "ge")]


def features(bars: pd.DataFrame, daily: pd.DataFrame, date: pd.Timestamp) -> dict:
    """reach20_condition_scan.build()와 같은 정의. daily는 당일 행을 뺀 '전일까지'."""
    pc = float(daily["close"].iloc[-1])
    value_20 = (daily["close"] * daily["volume"]).tail(20).mean()
    high_20 = float(daily["high"].tail(20).max())

    am = bars[bars.index.time <= CUTOFF]
    value = float((am["close"] * am["volume"]).sum())
    hi, lo = float(am["high"].max()), float(am["low"].min())
    rng, peak, last = hi - lo, am["high"].cummax(), float(am["close"].iloc[-1])
    return {
        "prev_close": pc,
        "open_gap_pct": float(am["open"].iloc[0]) / pc * 100 - 100,
        "ret_at_10_pct": last / pc * 100 - 100,
        "high_at_10_pct": hi / pc * 100 - 100,
        "max_dd_to_10_pct": float(((peak - am["low"]) / peak).max()) * 100,
        "pos_in_range_10": (last - lo) / rng if rng > 0 else 0.5,
        "upper_wick_ratio": (hi - last) / rng if rng > 0 else 0.0,
        "cum_value_eok": value / 1e8,
        "value_vs_20d_avg": value / value_20,
        "high_vs_20d_high_pct": hi / high_20 * 100 - 100,
        "already_20_by_10": hi >= pc * 1.20,
        "day_high_pct": float(bars["high"].max()) / pc * 100 - 100,
        "day_close_pct": float(bars["close"].iloc[-1]) / pc * 100 - 100,
        "n_bars": len(am),
    }


def fetch(client: KiwoomClient, code: str, date: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    minute = _pages_to_dataframe(
        client.get_minute_chart_pages(code, tic_scope="1", max_pages=1), is_minute=True)
    daily = _pages_to_dataframe(
        client.get_daily_chart_pages(code, base_date=date.strftime("%Y%m%d"), max_pages=1), is_minute=False)
    bars = minute[minute.index.normalize() == date]
    prior = daily[daily.index < date]           # 당일 행 제외 = "전일까지"
    if bars.empty or len(prior) < 20:
        return None
    return bars, prior


def main() -> None:
    codes = [a for a in sys.argv[1:] if not a.startswith("--")]
    arg = next((a.split("=")[1] for a in sys.argv if a.startswith("--date=")), None)
    date = pd.Timestamp(datetime.strptime(arg, "%Y%m%d") if arg else datetime.now().date())
    if not codes:
        print(__doc__)
        return

    load_dotenv()
    client = KiwoomClient(os.environ["KIWOOM_APPKEY"], os.environ["KIWOOM_SECRETKEY"],
                          is_mock=os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true")
    names = dict(zip(*pd.read_csv("data/universe.csv", dtype={"stock_code": str})
                     [["stock_code", "name"]].values.T))

    rows = {}
    for code in codes:
        got = fetch(client, code, date)
        if got is None:
            print(f"{code}: {date.date()} 분봉/일봉 부족 - 건너뜀")
            continue
        rows[code] = features(*got, date)

    if not rows:
        return
    print(f"\n{date.date()} 10:00 기준\n" + "=" * 78)
    label = {"ret_at_10_pct": "10시 등락률(%)", "high_at_10_pct": "10시까지 고가(%)",
             "open_gap_pct": "시가갭(%)", "pos_in_range_10": "레인지 위치", "upper_wick_ratio": "윗꼬리 비율",
             "max_dd_to_10_pct": "10시까지 눌림(%)", "cum_value_eok": "10시 누적대금(억)",
             "value_vs_20d_avg": "대금/20일평균", "high_vs_20d_high_pct": "10시고가/20일고가(%)",
             "day_high_pct": "당일 고가(%)", "day_close_pct": "현재/종가(%)"}
    head = "".join(f"{names.get(c, c)[:8]:>12}" for c in rows)
    print(f"{'':>20}{head}")
    for key, name in label.items():
        print(f"{name:>20}" + "".join(f"{rows[c][key]:>12.2f}" for c in rows))

    print("\n4조건 판정" + "\n" + "-" * 78)
    print(f"{'':>20}{head}")
    for name, key, thr, _ in RULE4:
        print(f"{name:>20}" + "".join(f"{'O' if rows[c][key] >= thr else 'X':>12}" for c in rows))
    print(f"{'통과':>20}" + "".join(
        f"{'통과' if all(rows[c][k] >= t for _, k, t, _ in RULE4) else '-':>12}" for c in rows))


def demo() -> None:
    """features()가 reach20_condition_scan과 같은 값을 내는지 - 손으로 만든 봉으로 검증."""
    idx = pd.date_range("2026-01-02 09:00", periods=61, freq="1min")
    bars = pd.DataFrame({"open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0,
                         "volume": 1000.0}, index=idx)
    daily = pd.DataFrame({"close": [100.0] * 20, "high": [100.0] * 20, "low": [100.0] * 20,
                          "volume": [1000.0] * 20},
                         index=pd.date_range("2025-12-01", periods=20, freq="D"))
    f = features(bars, daily, pd.Timestamp("2026-01-02"))
    assert abs(f["ret_at_10_pct"] - 5.0) < 1e-9, f
    assert abs(f["pos_in_range_10"] - 0.75) < 1e-9          # (105-90)/(110-90)
    assert abs(f["upper_wick_ratio"] - 0.25) < 1e-9         # 둘의 합은 항상 1
    assert abs(f["high_vs_20d_high_pct"] - 10.0) < 1e-9
    assert f["already_20_by_10"] is False or f["high_at_10_pct"] < 20
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
