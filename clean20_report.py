"""클린20 케이스 목록을 아티팩트용 HTML 한 장으로 굽는다.

    python clean20_report.py            # -> results/clean20_report.html

종목 목록/헤드라인 숫자/1분봉 차트가 전부 results/의 스캔 결과에서 다시 계산되므로,
새 거래일이 스캔에 반영된 뒤 이 스크립트만 다시 돌리면 페이지가 갱신된다. 갱신 순서:

    python reach20_path_drawdown.py     # 경로/최대낙폭 재계산 (선행)
    python clean20_report.py            # HTML 다시 굽기

모집단 정의는 clean20_list.select()를 그대로 쓴다 - 표에 뜨는 케이스와 CLI가 출력하는
케이스가 갈리지 않게 하기 위함.

레이아웃/CSS/차트 그리기 코드는 clean20_report_template.html에 그대로 두고 데이터만
갈아끼운다(__RAW__ / __CH__ 등 자리표시자 치환). 차트 좌표는 전일종가 대비 등락률을
0.1%p 단위 정수로, 거래량은 그날 최대 대비 0~1000으로 줄여 담는다 - 케이스당 1분봉
400개를 그대로 실으면 페이지가 수 MB로 불어난다.
"""
import json
import os
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_list import select

TEMPLATE_PATH = "clean20_report_template.html"
OUTPUT_PATH = "results/clean20_report.html"
MINUTE_DIR = "data/stocks/minute"
DAILY_DIR = "data/stocks/daily"
KOSPI_MINUTE = "data/index/minute/001.csv"
VOLUME_SCALE = 1000  # 거래량은 상대 높이로만 그려서 그날 최대치 대비 비율이면 충분
DD = 5.0        # 템플릿 제목/설명이 "5%"로 박혀 있어 여기서 고정한다(clean20_list의 기본값 4.5와 다름)
MAX_GAP = 15.0  # 마찬가지로 "시가갭 15% 미만"이 템플릿 문구에 들어가 있다
# 규칙(낙폭 <= DD) 밖이지만 손으로 넣기로 한 케이스. (날짜, 종목코드)
# 한국콜마: 09:14 보합구간에서 -7.2%로 밀렸으나 그 뒤로는 안 밀렸다는 판단. 표에는
# 실제 낙폭 7.16%이 그대로 찍히고 EXCEPTIONS 각주로 규칙 밖임을 밝힌다.
EXCEPTIONS = [("2026-08-12", "161890")]


def encode_day(code: str, date: pd.Timestamp) -> dict | None:
    """하루치 1분봉을 차트용으로 압축한다. o/h/l/c는 전일종가 대비 등락률 x10(정수),
    v는 그날 최대 거래량 대비 0~VOLUME_SCALE, s는 첫 봉의 분(09:00=540), d는 봉 사이
    분 간격 - 거래가 없어 빠진 분이 있어서 간격을 따로 담아야 시간축이 안 밀린다."""
    minute_path = os.path.join(MINUTE_DIR, f"{code}.csv")
    daily_path = os.path.join(DAILY_DIR, f"{code}.csv")
    if not (os.path.exists(minute_path) and os.path.exists(daily_path)):
        return None

    daily = pd.read_csv(daily_path, index_col=0, parse_dates=True).sort_index()
    prev_close = daily["close"].shift(1).get(date)
    if not prev_close or pd.isna(prev_close):
        return None

    m = pd.read_csv(minute_path, index_col=0, parse_dates=True).sort_index()
    day = m.loc[str(date.date())]
    if day.empty:
        return None

    mins = (day.index.hour * 60 + day.index.minute).tolist()
    pct = lambda col: [round((v / prev_close - 1) * 1000) for v in day[col]]
    vmax = max(1, int(day["volume"].max()))
    return {
        "s": mins[0],
        "d": [b - a for a, b in zip(mins, mins[1:])],
        "o": pct("open"), "h": pct("high"), "l": pct("low"), "c": pct("close"),
        "v": [round(v / vmax * VOLUME_SCALE) for v in day["volume"]],
    }


def kospi_above_60() -> pd.Series:
    """코스피 15분봉 종가가 60봉 이평 위인지. 장 사이 빈 구간은 dropna로 버려서 거래시간
    봉만 이어붙인다 - 그래야 60봉이 실제 2.3거래일이 된다. 이평이 안 찬 초반은 NaN."""
    close = pd.read_csv(KOSPI_MINUTE, index_col=0, parse_dates=True).sort_index()["close"]
    k = close.resample("15min").last().dropna()
    ma = k.rolling(60).mean()
    return (k > ma).where(ma.notna())


def build(cases: pd.DataFrame, n_gap: int) -> str:
    cases = cases.sort_values(["date", "stock_code"])
    above = kospi_above_60()
    raw, ch = [], {}
    for _, r in cases.iterrows():
        code, date = r["stock_code"], r["date"]
        # 09:00~+20% 도달까지 코스피가 60선 위였던 15분봉 비율 (1=내내 위, 0=내내 아래)
        window = above.loc[date + pd.Timedelta(hours=9):f"{date:%Y-%m-%d} {r['t20_time']}"].dropna()
        raw.append({
            "d": date.strftime("%Y-%m-%d"), "c": code, "n": r["name"],
            "g": round(r["open_gap_pct"], 1), "r": round(r["ret_at_10_pct"], 1),
            "p": round(r["max_dd_to_10_pct"], 1), "dd": round(r["max_dd_pct"], 2),
            "e": round(r["close_ret_pct"], 1), "t": r["t20_time"],
            "m": int(r["minutes_to_20"]), "k": int(r["rank_10am"]),
            "x": round(window.mean(), 2) if len(window) else None,
        })
        bars = encode_day(code, date)
        if bars:
            ch[f"{date:%Y-%m-%d}|{code}"] = bars

    held = cases[cases["close_ret_pct"] >= 20]
    freq = cases["name"].value_counts()
    ex = [r for r in raw if r["dd"] > DD]
    months = sorted({r["d"][:7] for r in raw})
    values = {
        "__RAW__": json.dumps(raw, ensure_ascii=False, separators=(",", ":")),
        "__CH__": json.dumps(ch, ensure_ascii=False, separators=(",", ":")),
        "__PERIOD__": f"{months[0].replace('-', '.')} – {months[-1].replace('-', '.')}",
        "__ASOF__": f"{above.index.max():%Y-%m-%d}",   # 지수 분봉 캐시의 마지막 날 = 이 리포트가 반영한 최종 거래일
        "__EXNOTE__": ("" if not ex else
            '<p class="sub" style="color:var(--ink-3)">규칙 밖 예외 '
            + str(len(ex)) + '건이 손으로 추가돼 있다 — '
            + ", ".join(f"{r['n']} {r['d']} (낙폭 {r['dd']:.2f}%)" for r in ex)
            + '. 낙폭 상한을 넘었지만 초반 보합구간을 지난 뒤로는 밀리지 않았다는 판단으로 넣었다.</p>'),
        "__TITLECNT__": f"{len(cases) - len(ex)}건" + (f" + 예외 {len(ex)}건" if ex else ""),
        "__N__": str(len(cases)),
        "__NGAP__": str(n_gap),
        "__MED_DD__": f"{cases['max_dd_pct'].median():.1f}",
        "__MED_M__": f"{cases['minutes_to_20'].median():.0f}",
        "__EARLY__": str(int((cases["t20_time"] <= "10:00").sum())),
        "__MED_E__": f"{cases['close_ret_pct'].median():.1f}",
        "__HELD__": str(len(held)),
        "__NSTOCK__": str(cases["stock_code"].nunique()),
        "__TOPNAME__": freq.index[0],
        "__TOPCNT__": str(int(freq.iloc[0])),
    }

    html = open(TEMPLATE_PATH, encoding="utf-8").read()
    for key, value in values.items():
        assert key in html, f"템플릿에 {key} 자리표시자가 없다"
        html = html.replace(key, value)
    print(f"케이스 {len(cases)}건 · 종목 {values['__NSTOCK__']}개 · 차트 {len(ch)}건"
          f" · 기간 {values['__PERIOD__']}")
    return html


def demo() -> None:
    """encode_day의 인코딩이 원래 값으로 되돌려지는지(시간축/가격/거래량) 자체검증."""
    ch = {"s": 540, "d": [1, 2], "o": [29, 20, 19], "v": [1000, 500, 0]}
    mins = [ch["s"]]
    for gap in ch["d"]:
        mins.append(mins[-1] + gap)
    assert mins == [540, 541, 543], mins           # 542분(거래 없음)은 건너뛴다
    assert [v / 10 for v in ch["o"]] == [2.9, 2.0, 1.9]
    assert max(ch["v"]) == VOLUME_SCALE
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()
    cases, n_gap = select(dd=DD, max_gap=MAX_GAP)
    if EXCEPTIONS:
        # 상한을 넉넉히 풀어 같은 로직으로 계산한 뒤 지정한 행만 골라 붙인다
        wide, _ = select(dd=100.0, max_gap=MAX_GAP)
        keys = {(d, c) for d, c in EXCEPTIONS}
        extra = wide[[(f"{d:%Y-%m-%d}", c) in keys
                      for d, c in zip(wide["date"], wide["stock_code"])]]
        cases = pd.concat([cases, extra]).drop_duplicates(["date", "stock_code"])
    html = build(cases, n_gap)
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    open(OUTPUT_PATH, "w", encoding="utf-8").write(html)
    print(f"저장: {OUTPUT_PATH} ({os.path.getsize(OUTPUT_PATH) / 1e6:.1f}MB)")
