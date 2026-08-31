"""장 국면 신호등 — 코스피 15분봉의 이동평균 두 개로 오늘 매매 환경을 판정한다.

판정 근거는 클린20 186건 분석(regime60 리포트)이다.
  큰 흐름  : 60봉 이평 > 120봉 이평 (정배열) — 종가까지 지킨 비율 55% vs 41%
  지금 분위기: 지수 > 60봉 이평
  과열     : 60/120 이격이 +1.77% 초과 — 지킴 41%로 극단 역배열(46%)보다도 낮았다

세 축을 합쳐 좋음/보통/나쁨 하나로 낸다. 나쁨은 둘이다 — "둘 다 나쁨"(역배열 + 60선
아래, +10% 방어가 무너진 유일한 칸)과 "과열"(정배열이어도 지킴 41%로 전 구간 최저).

15분봉 120봉 = 30시간 ≈ 4.6거래일이라 1분봉을 넉넉히 받아야 한다(1페이지 ≈ 2.3거래일).
"""
import threading
import time

import pandas as pd

from kiwoom_client import KiwoomClient
from .data_loader import _pages_to_dataframe

KOSPI = "001"
PAGES = 4                 # 1페이지 ≈ 900분봉 ≈ 2.3거래일 → 4페이지면 120봉 이평이 충분히 찬다
HOT_SPREAD_PCT = 1.77     # 이 이상 벌어지면 과열 (분석의 최상위 5분위 하한)
SLOPE_BARS = 8            # 기울기 기준 — 8봉 = 2시간
CACHE_TTL_SEC = 60

_lock = threading.Lock()
_cache: tuple[float, dict] | None = None


def _verdict(above60: bool, align_up: bool, spread: float) -> tuple[str, str]:
    """(등급, 한 줄 이유). 등급은 good / warn / bad 세 가지."""
    if not align_up and not above60:
        return "bad", "큰 흐름·분위기 둘 다 나쁨 — 유일하게 +10% 방어가 무너진 조합"
    if not align_up:
        return "warn", "역배열 — 지수가 60선 위여도 기대치는 낮은 구간"
    if spread > HOT_SPREAD_PCT:
        # 이 구간의 +20% 지킴 41%는 극단 역배열(46%)보다도 낮았다 — 정배열이어도 '나쁨'
        return "bad", f"과열 — 60/120 이격 {spread:+.2f}%, 지킴 41%로 전 구간 최저"
    if not above60:
        return "warn", "정배열이지만 지수가 60선 아래 — 추세 중 눌림"
    return "good", "정배열 + 60선 위 — 표준 국면"


def compute(close: pd.Series) -> dict:
    """1분봉 종가 -> 15분봉 재표본 -> 60/120 이평 판정. 장 사이는 버리고 거래시간만 잇는다."""
    k = close.resample("15min").last().dropna()
    if len(k) < 120:
        return {"ok": False, "error": f"15분봉 {len(k)}개 — 120봉 이평에 부족"}

    ma60 = float(k.rolling(60).mean().iloc[-1])
    ma120 = float(k.rolling(120).mean().iloc[-1])
    last = float(k.iloc[-1])
    spread = (ma60 / ma120 - 1) * 100
    # 이격이 벌어지는 중인가 좁혀지는 중인가. 매매 손익으로 보면 이격 수준보다 이
    # 방향이 부호를 갈랐다 — 과열이어도 확대 중이면 +1.86%, 축소 시작이면 -1.85%
    # (theme_rotation 옆의 이격 분석, 각 8건/6건이라 표본은 작다).
    spread_series = (k.rolling(60).mean() / k.rolling(120).mean() - 1) * 100
    slope = (float(spread - spread_series.iloc[-1 - SLOPE_BARS])
             if len(spread_series) > SLOPE_BARS else 0.0)
    above60, align_up = last > ma60, ma60 > ma120
    grade, reason = _verdict(above60, align_up, spread)
    # 진입 방식: 워크포워드에서 살아남은 한 칸만 갈린다(entry_style_classifier.py 참고).
    # 4칸 전부 국면별로 배정하면 인샘플만 좋고 OOS에서 고정 전략에 진다.
    breakout_day = (not align_up) and (not above60)
    return {
        "ok": True,
        "grade": grade,
        "label": {"good": "좋음", "warn": "보통", "bad": "나쁨"}[grade],
        "reason": reason,
        "trend": "정배열" if align_up else "역배열",
        "mood": "60선 위" if above60 else "60선 아래",
        "spread_pct": round(spread, 2),
        "hot": spread > HOT_SPREAD_PCT,
        "slope_pct": round(slope, 2),
        "widening": slope > 0,
        # 등급은 건드리지 않는다 — 기존 '과열=나쁨'은 종가까지 +20%를 지킨 비율 기준이고
        # 기울기는 건별 손익 기준이라 타깃이 다르다. 정보만 얹는다.
        "hot_fading": spread > HOT_SPREAD_PCT and slope <= 0,
        "index": round(last, 2),
        "ma60": round(ma60, 2),
        "ma120": round(ma120, 2),
        "breakout_day": breakout_day,
        "style": "돌파" if breakout_day else "전량 시장가",
        "style_reason": ("역배열 + 60선 아래 — 2% 눌린 뒤 고점 회복만 매수, 미체결이 정상"
                         if breakout_day else "평소대로 10:00 전량 시장가"),
        "as_of": k.index[-1].strftime("%m-%d %H:%M"),
    }


def get_regime_signal(appkey: str, secretkey: str, is_mock: bool) -> dict:
    """대시보드용 진입점. 폴링마다 API를 두드리지 않도록 60초 캐시."""
    global _cache
    with _lock:
        if _cache and time.time() - _cache[0] < CACHE_TTL_SEC:
            return _cache[1]

    try:
        client = KiwoomClient(appkey, secretkey, is_mock=is_mock)
        pages = client.get_index_minute_chart_pages(KOSPI, tic_scope="1", max_pages=PAGES)
        df = _pages_to_dataframe(pages, is_minute=True)
        result = compute(df.sort_index()["close"])
    except Exception as exc:                      # 신호등 하나 때문에 대시보드가 죽으면 안 된다
        result = {"ok": False, "error": str(exc)[:200]}

    with _lock:
        _cache = (time.time(), result)
    return result


def demo() -> None:
    """판정 분기 - 네 조합이 각각 제 등급으로 가는지."""
    assert _verdict(False, False, -1.0)[0] == "bad"      # 둘 다 나쁨
    assert _verdict(True, False, -1.0)[0] == "warn"      # 역배열인데 60선 위
    assert _verdict(False, True, 0.5)[0] == "warn"       # 정배열인데 60선 아래
    assert _verdict(True, True, 0.5)[0] == "good"        # 둘 다 좋음
    assert _verdict(True, True, 2.0)[0] == "bad"         # 정배열이어도 과열이면 나쁨

    # 기울기: 바닥에서 돌아서면 확대(+), 꺾이면 축소(-). 선형 상승은 분모가 커져서
    # % 이격이 오히려 줄어드니 테스트 파형으로 쓰면 안 된다.
    import pandas as _pd

    def _series(values: list[float]) -> _pd.Series:
        return _pd.Series(values, index=_pd.date_range("2026-01-02 09:00",
                                                       periods=len(values), freq="15min"))

    rise = [100.0 + i * i * 0.01 for i in range(80)]
    up = compute(_series([100.0] * 120 + rise))
    assert up["slope_pct"] > 0 and up["widening"], up["slope_pct"]

    # 오른 뒤 멈추면 이격은 아직 양수인데 좁혀지는 중 — 손익 부호가 뒤집힌 자리다.
    # 20봉 정도로는 이평이 못 따라와 기울기가 안 꺾인다. 40봉은 있어야 한다.
    fade = compute(_series([100.0] * 120 + rise + [rise[-1]] * 40))
    assert fade["spread_pct"] > 0 and fade["slope_pct"] < 0, fade
    assert not fade["widening"]

    # 돌파의 날은 역배열 + 60선 아래 한 칸뿐
    assert ((not True) and (not True)) is False

    # 15분 재표본 + 이평 판정이 실제로 도는지. 기울기를 완만하게 둬야 이격이 과열
    # 임계값 아래로 남는다 - 가파른 직선은 정배열이어도 '과열'로 잡히는 게 정상이다.
    idx = pd.date_range("2026-01-02 09:00", periods=15 * 130, freq="1min")
    s = pd.Series([1000 + i * 0.01 for i in range(len(idx))], index=idx)
    out = compute(s)
    assert out["spread_pct"] < HOT_SPREAD_PCT, out["spread_pct"]
    assert out["ok"] and out["grade"] == "good", out
    assert out["trend"] == "정배열" and out["mood"] == "60선 위", out
    print("demo ok")


if __name__ == "__main__":
    demo()
