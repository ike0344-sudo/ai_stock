"""-8% 눌림 매수 후보 — 장 마감 뒤 일봉으로 '내일 걸어 둘 지정가' 목록을 뽑는다(사용자 규칙, 2026-10-01 확정).

규칙:
- 장대양봉: 고가 +20%↑, 종가 +15%↑, 대금(종가×거래량) 1,500억↑, ETF·ETN·스팩 제외
- 필터: 코스닥 · 그날 고가가 직전 52주 고가 +4% 이상 돌파가 아님(신규상장주 포함) ·
  같은 테마(80종목 이하 테마) 다른 종목 3개 이상이 최근 10거래일 안에 +10% 마감
- 매수: 장대양봉 다음 날부터 5거래일 안, 그날 고가 -8%에 처음 닿을 때 한 번 · 손절 -3.5% · 익절 +8%
- 같은 종목은 한 번 사면 20거래일 재매수 안 함(여기선 '이미 -8% 닿음'이면 후보에서 빼는 것으로 대신)

검증(분봉, 비용 0.25% 포함): 2025-07~2026-03 70번 평균 +1.51%, 2026-04~09 56번 평균 +1.47%. 강한 장에서 더 잘 통한다.

    python pullback_candidates.py              # 최신 일봉 기준
    python pullback_candidates.py --date 2026-09-15
"""
from __future__ import annotations

import argparse
import json
import os

import pandas as pd

from backtesting import rs_rating as R

ENTRY_WIN, DIP, STOP, TAKE = 5, 0.08, 0.035, 0.08
MIN_VALUE, MAX_BREAK_52W, THEME_MAX_SIZE, THEME_MIN_MOVERS = 1500e8, 0.039, 80, 3
OUT_DIR = "results/pullback_candidates"


def build(asof: str | None = None) -> pd.DataFrame:
    close, (high, low), vol = R.wide_close(), R.wide_high_low(), R.wide_volume()
    names = R.load_names()
    keep = [c for c in close.columns if c not in R.excluded_codes(names)]
    close, high, low, vol = close[keep], high[keep], low[keep], vol[keep]
    if asof:
        close, high, low, vol = (x.loc[:asof] for x in (close, high, low, vol))
    idx, pc = close.index, close.shift(1)
    hi52 = high.shift(1).rolling(250).max()
    big = (high / pc - 1 >= 0.20) & (close / pc - 1 >= 0.15) & (close * vol >= MIN_VALUE)
    up10 = (close / pc - 1 >= 0.10).rolling(10, min_periods=1).max().astype(bool)
    market = json.load(open("data/cache/rs_market.json", encoding="utf-8"))
    th = pd.read_csv("data/themes.csv", dtype={"stock_code": str}, encoding="utf-8-sig")
    th = th[th.theme_size <= THEME_MAX_SIZE]
    themes_of = th.groupby("stock_code").theme.apply(list).to_dict()
    members = th.groupby("theme").stock_code.apply(list).to_dict()

    rows = []
    for d in idx[-ENTRY_WIN:]:                       # 매수 창(5거래일)이 아직 열린 장대양봉만
        i = idx.get_loc(d)
        for c in big.columns[big.loc[d].values]:
            if market.get(c) != "코스닥":
                continue
            h52 = hi52.at[d, c]
            if not pd.isna(h52) and high.at[d, c] > h52 * (1 + MAX_BREAK_52W):
                continue
            best_theme, movers = None, 0
            for t in themes_of.get(c, []):
                n = sum(1 for m in members[t] if m != c and m in up10.columns and up10.at[d, m])
                if n > movers:
                    best_theme, movers = t, n
            if movers < THEME_MIN_MOVERS:
                continue
            entry = high.at[d, c] * (1 - DIP)
            after = low[c].iloc[i + 1:]
            touched = bool((after <= entry).any())
            rows.append({
                "신호일": d.date().isoformat(), "종목": names.get(c, c), "코드": c,
                "고점%": round((high.at[d, c] / pc.at[d, c] - 1) * 100, 1), "종가%": round((close.at[d, c] / pc.at[d, c] - 1) * 100, 1),
                "대금(억)": round(close.at[d, c] * vol.at[d, c] / 1e8),
                "52주고가대비%": None if pd.isna(h52) else round((high.at[d, c] / h52 - 1) * 100, 1),
                "테마": best_theme, "테마동반": movers,
                "매수가": round(entry), "손절가": round(entry * (1 - STOP)), "익절가": round(entry * (1 + TAKE)),
                "현재가": round(close[c].iloc[-1]), "매수가까지%": round((entry / close[c].iloc[-1] - 1) * 100, 1),
                "남은일수": ENTRY_WIN - (len(idx) - 1 - i),
                "상태": "이미 -8% 닿음(진입 끝)" if touched else "대기",
            })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", help="이 날짜까지의 일봉으로 계산(YYYY-MM-DD)")
    a = ap.parse_args()
    df = build(a.date)
    day = a.date or R.wide_close().index[-1].date().isoformat()
    os.makedirs(OUT_DIR, exist_ok=True)
    path = f"{OUT_DIR}/{day}.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    print(f"{day} 기준 · 후보 {len(df)}종목 → {path}")
    if len(df):
        print(df.sort_values(["상태", "신호일"]).to_string(index=False))


if __name__ == "__main__":
    main()
