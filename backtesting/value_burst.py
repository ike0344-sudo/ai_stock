"""거래대금 폭발 — 최근 20거래일 안에 통합(AL) 실거래대금이 역대/4년/1년 최대이거나 1년 최대에 근접한 종목. 사용자 2026-10-04.

    python -m backtesting.value_burst        # → static/dashboard/value_burst.json (화면: /burst.html)

## 등급 (그날 대금을 그날 **제외** 이전 기간 최대와 비교, 높은 등급이 이긴다)
- 역대 = 우리 통합 일봉 전체 기간(처음 받을 때 3페이지 ≈ 7년) 최대 초과 — "데이터 기간 최고"이지 상장 이후 전체가 아니다.
- 4년 = 직전 980거래일 최대 초과 · 1년 = 직전 245거래일 최대 초과
- 1년 유의미 = 직전 245거래일 최대의 70% 이상(처음 80% — 10-04 사용자가 70% 로 낮춤, 알테오젠 2024-02-22(78%) 같은 날을 잡으려고)
- 평소 대비 = 1,000억 이상 + 직전 20일 평균의 2.5배 이상 + 그날 종가 +7% 이상(10-04 사용자) — 과거 최대와 비교하는 위 등급으로는
  작년에 크게 터진 종목의 '조용하다 갑자기 터진 날'이 안 잡힌다(디아이 2026-09-21 1년 최대의 39%·평소 6배, 알테오젠 2024-02-21 26%·2.5배).
  2025년 기준 하루 7.6건, 그중 위 등급에 없던 날 3.9건. 등락은 통합 종가로 잰다(화면의 폭발일 등락과 같은 값).
- 한 종목에 여러 날이면 가장 높은 등급, 같으면 최근 날을 보여 주고 횟수를 같이 단다.

대금은 통합(data/stocks/daily_al, scripts/collect_daily_al.py) — KRX 일봉으로 재면 NXT 가 빠져 2025-03 뒤로 반 토막 난다(심텍 09-22).
가격(등락률·현재가·240일 고점·옛 고점)은 통합·KRX 두 벌을 싣고 화면에서 고른다(기본 통합 = 영웅문 통합 차트와 같은 값 —
디아이 1/30 고가 KRX 41,700 vs 통합 42,500, 10-05). 240일 고점은 **오늘 포함** 최근 240거래일 고가, 남은 거리 = 고점 ÷ 현재가 − 1.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

from backtesting import rs_rating as R
from datahub import catalog

OUT_PATH = "static/dashboard/value_burst.json"
OHLC_PATH = "static/dashboard/value_burst_ohlc.json"  # 마우스 오버 일봉 — 처음 오버할 때만 받는다(휴대폰은 안 받음)
WINDOW_DAYS = 20
MIN_EOK = 300          # 저장 하한 — 화면 기본 필터는 1,000억
HIGH_DAYS = 240
OHLC_DAYS = HIGH_DAYS + 19  # 마우스 오버 240일봉 — 20일선이 첫 봉부터 그려지게 19일 더
TIERS = ("역대", "4년", "1년", "1년 유의미", "평소 대비")
Y4, Y1, NEAR = 980, 245, 0.7
SPIKE_EOK, SPIKE_MULT, SPIKE_CHG, SPIKE_AVG = 1000, 2.5, 0.07, 20


def tiers_of(val: pd.Series, close: pd.Series | None = None) -> pd.Series:
    """날짜별 등급(없으면 None). val 은 억 단위, close 는 같은 날짜의 종가(없으면 '평소 대비'를 안 매긴다), 날짜 오름차순."""
    prev = val.shift(1)
    # 1년치가 안 찬 날은 등급을 매기지 않는다(상장 초기엔 아무 날이나 '역대'가 된다)
    all_max = prev.expanding(min_periods=Y1).max()
    y4 = prev.rolling(Y4, min_periods=Y1).max()
    y1 = prev.rolling(Y1, min_periods=Y1).max()
    t = pd.Series(None, index=val.index, dtype=object)
    if close is not None:
        avg = prev.rolling(SPIKE_AVG, min_periods=SPIKE_AVG).mean()
        t[(val >= SPIKE_EOK) & (val >= SPIKE_MULT * avg) & (close / close.shift(1) - 1 >= SPIKE_CHG)] = "평소 대비"
    t[val >= NEAR * y1] = "1년 유의미"
    t[val > y1] = "1년"
    t[val > y4] = "4년"
    t[val > all_max] = "역대"
    return t


def price_view(d: pd.DataFrame, bdate: str) -> tuple[dict, list] | None:
    """한 가격 기준(통합 또는 KRX 일봉, date=YYYYMMDD 문자열)으로 화면 가격 칸과 마우스 오버 일봉. 폭발일 행이 없으면 None."""
    bi = d.index[d.date == bdate]
    if not len(bi) or bi[0] == 0:
        return None
    b = bi[0]
    recent = d.tail(HIGH_DAYS)
    hi_i = recent.high.idxmax()
    cur, hi = float(d.close.iloc[-1]), float(recent.high.max())
    prior_hi = d.high.iloc[max(0, b - HIGH_DAYS):b].max()            # 옛 고점 = 폭발일 전날까지 240일 최고 고가
    after = d.index[(d.index >= b) & (d.high >= prior_hi)]
    closed = d.index[(d.index >= b) & (d.close > prior_hi)]          # 종가가 옛 고점 위로 마감한 첫날 = 돌파(같으면 아님 — 디아이 10/1)
    ymd = lambda i: f"{d.date[i][:4]}-{d.date[i][4:6]}-{d.date[i][6:]}"
    view = {
        "폭발일등락": round(float(d.close[b] / d.close[b - 1] - 1) * 100, 1),
        "터치일": ymd(after[0]) if len(after) else None, "터치까지일": int(after[0] - b) if len(after) else None,
        "기준고점": float(prior_hi), "돌파일": ymd(closed[0]) if len(closed) else None,
        "돌파까지일": int(closed[0] - b) if len(closed) else None,
        "현재가": cur, "고점240": hi, "고점일": ymd(hi_i), "남은거리": round((hi / cur - 1) * 100, 1),
        "현재등락": round(float(d.close.iloc[-1] / d.close.iloc[-2] - 1) * 100, 1), "시세일": ymd(len(d) - 1),
    }
    # 마우스 오버 240일봉(+20일선 워밍업) — value_burst_ohlc.json 으로 따로 쓴다(두 기준이라 2.9MB, 본 파일에 실으면 휴대폰도 매번 받는다)
    bars = [[int(r.date), *(int(round(float(x))) for x in (r.open, r.high, r.low, r.close)), int(r.volume)]  # 원 단위 정수 — 파일 크기 절반
            for r in d.tail(OHLC_DAYS).itertuples(index=False)]
    return view, bars


def build(window_days: int = WINDOW_DAYS) -> dict:
    names = R.load_names()
    skip = R.excluded_codes(names)
    se_path = "data/sectors_stockeasy.csv"
    se = pd.read_csv(se_path, dtype=str, encoding="utf-8-sig") if os.path.isfile(se_path) else pd.DataFrame(columns=["code", "sector", "sub_sector"])
    sectors, subs = dict(zip(se.code, se.sector)), dict(zip(se.code, se.sub_sector))
    # RS 는 야간 갱신이 바로 앞에서 만든 캐시(rs_rating.save)를 읽는다. 섹터 RS = 그 섹터 전 종목 RS종합 중앙값(신고가 화면과 같은 정의)
    rs_day = pd.read_parquet(R.RS_PATH).iloc[-1] if os.path.isfile(R.RS_PATH) else pd.Series(dtype=float)
    rs1m_day = pd.read_parquet(R.PERIOD_PATH["1m"]).iloc[-1] if os.path.isfile(R.PERIOD_PATH["1m"]) else pd.Series(dtype=float)
    sec_rs, sub_rs = R.sector_rs_median(rs_day, sectors), R.sector_rs_median(rs_day, subs)
    al_dir = catalog.path("daily_al", code="X").parent
    krx_dir = catalog.path("daily", code="X").parent
    days = pd.read_csv(krx_dir / "005930.csv", usecols=["date"]).date.str.replace("-", "").tolist()
    cutoff, last_day = days[-window_days], days[-1]
    rows, ohlc = [], {}
    for p in sorted(al_dir.glob("*.csv")):
        code = p.stem
        if code in skip:
            continue
        a = pd.read_csv(p, dtype={"date": str}).dropna(subset=["value_mw"]).sort_values("date").reset_index(drop=True)
        if len(a) <= Y1 or a.date.iloc[-1] < cutoff:
            continue
        val = a.value_mw / 100  # 백만원 → 억
        t = tiers_of(val, a.close)
        hit = a.index[(a.date >= cutoff) & t.notna() & (val >= MIN_EOK)]
        if not len(hit):
            continue
        k = max(hit, key=lambda i: (-TIERS.index(t[i]), a.date[i]))
        if k == 0:
            continue
        bdate = a.date[k]
        kp = krx_dir / f"{code}.csv"
        krx = None
        if kp.exists():
            krx = pd.read_csv(kp)
            krx["date"] = krx.date.str.replace("-", "")
        # 가격(옛 고점·240일 고점·현재가·등락·터치/돌파)은 통합과 KRX 두 벌을 싣고 화면에서 고른다(10-05 사용자).
        # 거래대금 등급은 언제나 통합 — KRX 대금은 NXT 가 빠져 반 토막이다.
        views = {"통합": price_view(a, bdate)}
        if krx is not None and (kv := price_view(krx, bdate)) is not None:
            views["KRX"] = kv
        if views["통합"] is None:
            continue
        y1max = val.shift(1).rolling(Y1, min_periods=Y1).max()[k]
        base = {"역대": val.shift(1).expanding().max()[k], "4년": val.shift(1).rolling(Y4, min_periods=Y1).max()[k],
                "평소 대비": val.shift(1).rolling(SPIKE_AVG).mean()[k]}.get(t[k], y1max)  # 평소 대비의 비교 대금 = 직전 20일 평균
        for basis, (_, bars) in views.items():
            ohlc.setdefault(basis, {})[code] = bars
        rows.append({
            "코드": code, "이름": names.get(code, code), "섹터": sectors.get(code, "미분류"), "세부섹터": subs.get(code, "미분류"),
            "rs": R._int_or_none(rs_day.get(code)), "rs_1m": R._int_or_none(rs1m_day.get(code)),
            "섹터rs": sec_rs.get(sectors.get(code)), "세부섹터rs": sub_rs.get(subs.get(code)),
            "등급": t[k], "폭발일": f"{a.date[k][:4]}-{a.date[k][4:6]}-{a.date[k][6:]}", "대금": round(float(val[k])),
            "비교대금": round(float(base)), "배수": round(float(val[k] / base), 2),
            "횟수": int(len(hit)), "가격": {basis: v for basis, (v, _) in views.items()},
            "데이터시작": a.date.iloc[0][:4],
        })
    rows.sort(key=lambda r: (TIERS.index(r["등급"]), -r["대금"]))
    day = f"{last_day[:4]}-{last_day[4:6]}-{last_day[6:]}"
    return {"date": day, "window_days": window_days, "since": f"{cutoff[:4]}-{cutoff[4:6]}-{cutoff[6:]}", "rows": rows, "ohlc": ohlc}


def write_json(payload: dict, path: str = OUT_PATH) -> str:
    """본 자료(path)와 일봉(OHLC_PATH)을 나눠 쓴다."""
    payload = dict(payload)
    for p, obj in ((OHLC_PATH, payload.pop("ohlc", {})), (path, payload)):
        tmp = f"{p}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, p)
    return path


def demo() -> None:
    v = pd.Series([100.0] * 300 + [90, 50, 300, 250])
    t = tiers_of(v)
    assert t[300] == "1년 유의미" and pd.isna(t[301]) and t[302] == "역대" and t[303] == "1년 유의미", t.tail(4).tolist()
    assert pd.isna(tiers_of(pd.Series([100.0] * 10 + [999])).iloc[-1])  # 1년 안 찬 종목
    v2 = pd.Series([500.0] + [100.0] * 1000 + [200])  # 4년 밖 500 > 오늘 200 > 최근 4년 100
    assert tiers_of(v2).iloc[-1] == "4년"
    c = pd.Series([100.0] * 300 + [110])  # 평소 100억대 → 1,200억 +10%
    assert tiers_of(pd.Series([100.0] * 300 + [1200]), c).iloc[-1] == "역대"
    v3 = pd.Series([100.0] * 300 + [5000] + [100.0] * 30 + [1200])  # 한 달 전 5,000억이라 위 등급은 안 되지만 평소의 12배·+10%
    c3 = pd.Series([100.0] * 331 + [110])
    assert tiers_of(v3, c3).iloc[-1] == "평소 대비" and pd.isna(tiers_of(v3).iloc[-1])
    assert pd.isna(tiers_of(v3, pd.Series([100.0] * 331 + [105])).iloc[-1])  # +5% 면 아님
    print("demo ok")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--demo" in sys.argv:
        demo()
    else:
        p = build()
        print(f"저장: {write_json(p)} — {len(p['rows'])}종목 ({p['since']}~{p['date']})")
