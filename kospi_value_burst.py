"""09:30~10:00 코스피 거래대금이 얼마나 터지는가.

    python kospi_value_burst.py            # 과거 분포 + 오늘
    python kospi_value_burst.py --refresh  # 일봉 거래대금 다시 받기

키움 업종 분봉(ka20005)은 거래량(trde_qty)만 주고 거래대금 필드가 없다. 거래대금은
업종 일봉(ka20006)의 trde_prica에만 있고 그것도 하루 누적 한 덩어리다. 그래서
  구간 대금 ≈ 구간 거래량 x (그날 일봉 거래대금 / 그날 일봉 거래량)
로 근사한다 - 시간대별 매매 종목 구성이 달라서 오차가 있다. 거래량 비율(그날 대비,
첫 1시간 대비)은 근사가 아니라 정확한 값이니 신호로 쓸 거면 이쪽이 낫다.
"""
import os
import sys

import pandas as pd
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fetch_chart import find_records
from kiwoom_client import KiwoomClient

MINUTE = "data/index/minute/001.csv"
VALUE_CACHE = "data/index/daily/001_value.csv"
SEG = (570, 600)   # 09:30~09:59 (분 단위, 09:30 = 570)
HOUR = (540, 600)  # 09:00~09:59


def daily_value(index_code: str = "001", refresh: bool = False) -> pd.DataFrame:
    """일자별 거래대금(백만원)/거래량(천주). ka20006에만 있는 trde_prica를 캐시한다."""
    cache = VALUE_CACHE if index_code == "001" else VALUE_CACHE.replace("001_", f"{index_code}_")
    if os.path.exists(cache) and not refresh:
        return pd.read_csv(cache, index_col=0, parse_dates=True)

    load_dotenv()
    client = KiwoomClient(os.environ["KIWOOM_APPKEY"], os.environ["KIWOOM_SECRETKEY"],
                          is_mock=os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true")
    rows = [r for page in client.get_index_daily_chart_pages(index_code, max_pages=10)
            for r in find_records(page)]
    df = pd.DataFrame({
        "date": pd.to_datetime([r["dt"] for r in rows], format="%Y%m%d"),
        "value_mw": [float(r["trde_prica"]) for r in rows],
        "qty_kshare": [float(r["trde_qty"]) for r in rows],
    }).drop_duplicates("date").set_index("date").sort_index()
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    df.to_csv(cache)
    return df


def segments(index_code: str = "001") -> pd.DataFrame:
    """분봉 캐시에서 구간 거래량을 자르고, 일봉 평균단가로 대금을 근사한다."""
    m = pd.read_csv(MINUTE.replace("001", index_code), index_col=0, parse_dates=True).sort_index()
    mins = m.index.hour * 60 + m.index.minute
    cut = lambda a, b: m[(mins >= a) & (mins < b)].groupby(lambda t: t.normalize())["volume"].sum()

    d = pd.DataFrame({"seg": cut(*SEG), "hour": cut(*HOUR),
                      "day": m.groupby(m.index.normalize())["volume"].sum()}).dropna()
    v = daily_value(index_code)
    d["price"] = (v["value_mw"] / v["qty_kshare"]).reindex(d.index)   # 백만원/천주 = 천원/주
    d["seg_value_jo"] = d["seg"] * d["price"] / 1e6                   # 백만원 -> 조원
    d["hour_value_jo"] = d["hour"] * d["price"] / 1e6                 # 09:00~10:00 누적
    d["day_value_jo"] = (v["value_mw"] / 1e6).reindex(d.index)
    d["seg_of_day"] = d["seg"] / d["day"] * 100
    d["seg_of_hour"] = d["seg"] / d["hour"] * 100
    return d


def main() -> None:
    d = segments()
    print(f"코스피 09:30~10:00  |  {d.index.min().date()} ~ {d.index.max().date()} {len(d)}거래일")
    print("=" * 66)
    print(f"{'':>18}{'중앙':>10}{'25%':>10}{'75%':>10}{'최소':>10}{'최대':>10}")
    for col, name, unit in [("seg", "거래량(천주)", ""), ("seg_value_jo", "거래대금(조,근사)", ""),
                            ("seg_of_day", "그날 전체 대비(%)", ""), ("seg_of_hour", "첫1시간 대비(%)", "")]:
        q = d[col].quantile([0, .25, .5, .75, 1])
        print(f"{name:>18}{q[.5]:>10.1f}{q[.25]:>10.1f}{q[.75]:>10.1f}{q[0]:>10.1f}{q[1]:>10.1f}")

    d["z"] = (d["seg"] - d["seg"].rolling(20).mean().shift(1)) / d["seg"].rolling(20).std().shift(1)
    print(f"\n20일 평균 대비 배수 중앙 {(d['seg'] / d['seg'].rolling(20).mean().shift(1)).median():.2f}배")
    print("\n최근 10일")
    print(f"{'날짜':>12}{'거래량(천주)':>13}{'대금(조)':>10}{'전체대비':>9}{'첫1시간':>9}{'20일z':>8}")
    for dt, r in d.tail(10).iterrows():
        print(f"{dt.strftime('%Y-%m-%d'):>12}{r['seg']:>13,.0f}{r['seg_value_jo']:>10.2f}"
              f"{r['seg_of_day']:>8.1f}%{r['seg_of_hour']:>8.1f}%{r['z']:>8.2f}")

    out = "results/kospi_0930_1000.csv"
    d.to_csv(out, encoding="utf-8-sig")
    print(f"\n원본: {out}")


def demo() -> None:
    """구간 절단이 09:30~09:59만 잡는지 - 09:29/10:00이 새면 값이 통째로 달라진다."""
    idx = pd.date_range("2026-01-02 09:00", "2026-01-02 10:30", freq="1min")
    m = pd.DataFrame({"volume": 1.0}, index=idx)
    mins = m.index.hour * 60 + m.index.minute
    seg = m[(mins >= SEG[0]) & (mins < SEG[1])]
    assert len(seg) == 30, len(seg)
    assert seg.index[0].strftime("%H:%M") == "09:30"
    assert seg.index[-1].strftime("%H:%M") == "09:59"
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        if "--refresh" in sys.argv and os.path.exists(VALUE_CACHE):
            os.remove(VALUE_CACHE)
        main()
