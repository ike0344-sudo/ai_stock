"""52주 신고가 · 신고가 후보 — 스탁이지 new-high/new-high-candidates 화면 데이터. lead 편지 2026-09-28 22:30(사용자 요청).

데이터만 만든다 — 화면은 execution-agent. `backtesting.rs_rating.build()`(RS 계산)가 이미 만든 close/high/low/volume/rs/period_rs
를 그대로 받아 쓴다(같은 자리에서 야간 갱신 — 일봉을 두 번 안 읽는다). 그 모듈의 `market_of`·`load_shares`·
`avg_value`(당일 포함 5/20/60일 평균 거래대금, 09-28 22:10 편지로 이미 있음)를 재사용 — 새로 만들지 않는다.

    python -m backtesting.new_high            # 전체 재계산(rs_rating.build() 포함) 후 → static/dashboard/newhigh.json
    python -m backtesting.new_high --reuse-rs  # 이미 떠 있는 rs_rating 캐시(parquet)를 읽어 재사용(빠름, 야간 갱신에서 이 경로 사용)

## 정의 (편지 원문 — 스탁이지 화면을 lead 가 로그인해서 읽은 것)
- **52주 최고가** = 오늘 **제외** 직전 250거래일 고가 최댓값(`high.shift(1).rolling(250).max()` — 기존 `indicators.highest` 와 같은 t 제외 관례).
- **상태**(고가까지% = 52주최고가÷종가−1 기준, **터치 후 밀림이 최우선**):
  1. 터치 후 밀림 = 당일 고가 ≥ 52주 최고가 **인데** 종가 < 52주 최고가.
  2. 돌파(중/성공) = 종가 ≥ 52주 최고가. **우리 구분**(스탁이지 원문이 "돌파중/돌파성공"을 어떻게 가르는지 화면에 안 나와 있어 직접 정함,
     바뀌면 알려달라): **돌파중** = 어제는 아니었는데 오늘 처음 종가가 52주 최고가 이상(첫날) · **돌파성공** = 어제도 종가가 52주
     최고가 이상이었다(둘째 날 이후, 버텨냄).
  3. 임박 = 0% 초과 ~ 3% 이내. 4. 근접 = 3% 초과 ~ 7% 이내. 5. 관찰 = 7% 초과 ~ 20% 이내(스탁이지는 12% — 사용자 09-28 20% 로 넓힘).
- **후보 모집단** = 위 5 상태 중 하나에 해당하는 전 종목(= 고가까지 ≤20% 이거나 오늘 터치). ETF/ETN/스팩 제외(rs_rating 과 같은 규칙).
- **n_breaks_60** = 최근 60거래일(오늘 포함) 중 종가가 그날의 52주 최고가 이상이었던(=돌파 상태였던) 날 수.
- **ATR%** = 최근 14일 TR(고가−저가, |고가−전일종가|, |저가−전일종가| 중 최댓값) 단순평균 ÷ 오늘 종가.
- **value_mult20** = 오늘 거래대금 ÷ `rs_rating.avg_value(...,20)`(당일 포함 20일 평균 — 위 재사용 이유로 "오늘 제외" 아님, 화면 다른 칸과 기준 통일).
- **신선 후보** = n_breaks_60 ≤ 1, value_mult20 ≥ 1.0, RS종합 ≥ 80, 상태 ∈ {근접, 임박} (편지가 준 기본값 그대로 — 안 바꿈).
- **역사적 신고가** = 오늘 종가가 **우리 일봉 전체 기간**(2019-04~) 최고가 이상 — "데이터 기간 최고"로 명시(편지 지시대로).
- **섹터/세부섹터** = `data/sectors_stockeasy.csv`(스탁이지가 준 실제 대분류·중분류, 2,579종목 — 카탈로그 `sectors_stockeasy`, "RS·신고가
  화면 전용, 소피증권 테마와 안 섞는다"는 09-28 결정). **처음엔 `theme_group_map.csv`+`data/sectors.csv` 로 직접 추정했었는데, 그 뒤 이 파일이
  생겨서 바꿨다**(더 정확한 실제 분류 — 원래 우리 추정은 버림).

## 산출물
`static/dashboard/newhigh.json`: `{date, candidates:[...], new_highs:[...]}`. 필터(시총·RS·거래대금 하한)는 값만 담고 여기서 안 거른다
(스탁이지 "주요종목" 기준 비공개 — 화면에서 기본 시총 2,000억+·RS 80+·거래대금 100억+ 로 걸 것, 편지 지시).

## 장중 5분 갱신 — 설계만(이번엔 구현 안 함, 편지 지시)
1차는 장 마감 기준 일봉만 쓴다. 장중에는 8765 가 이미 돌리는 거래대금 순위 폴러(ka10032, 초당 약 1회 페이싱)가 종목별 **현재가·당일고가**를
들고 있다 — 그 스냅샷을 받아 `종가`·`당일고가` 자리에 대신 넣고 52주 최고가·RS 등 **일봉만으로 계산되는 값은 D-1 그대로 고정**하면(장중엔
새로 모르는 값이니 미래참조 없음) 상태·고가까지%·터치여부까지는 5분마다 다시 계산할 수 있다. 새 API 호출 없이 기존 폴러 결과를 얹기만
하면 되므로 REST 예산에 영향 없음 — 다만 8765 프로세스 안에서 밀어 주는 구조가 필요해 모니터링·백엔드 쪽 작업이다(이 스크립트는 배치 전용).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

from backtesting import rs_rating as R
from datahub import write

OUT_PATH = "static/dashboard/newhigh.json"
OHLC_PATH = "static/dashboard/newhigh_ohlc.json"  # 마우스 오버 52주 일봉 — 화면이 처음 오버할 때 한 번만 받는다
LEDGER_PATH = "static/dashboard/newhigh_ledger.json"  # 신고가 장부(ledger.html) — 대금 큰 돌파 전 기간 기록
LEDGER_MIN_VALUE = 1500e8  # 사용자 09-29: "거래대금 1500억 이상 터진 52주 신고가"
NEW_HIGH_RECENT_DAYS = 5  # 52주 신고가 탭: 최근 5거래일 안 종가 돌파면 남긴다(10-01 사용자)
LEDGER_SHORT_WINDOW = 120  # 장부의 짧은 기준(120일 신고가) — 09-30 사용자 요청으로 52주와 전환
OHLC_DAYS = 250
HIGH52_WINDOW = 250
BREAK_WINDOW = 60
ATR_WINDOW = 14
CANDIDATE_MAX_PCT = 0.20
BANDS = (("임박", 0.0, 0.03), ("근접", 0.03, 0.07), ("관찰", 0.07, CANDIDATE_MAX_PCT))
FRESH_MAX_BREAKS, FRESH_MIN_VALUE_MULT, FRESH_MIN_RS = 1, 1.0, 80
SECTORS_STOCKEASY_CSV = "data/sectors_stockeasy.csv"  # 섹터/세부섹터 — 스탁이지 실제 분류(카탈로그 sectors_stockeasy)


def high52_of(high: pd.DataFrame) -> pd.DataFrame:
    """오늘 제외 직전 250거래일 고가 최댓값."""
    return high.shift(1).rolling(HIGH52_WINDOW).max()


def atr_pct(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, n: int = ATR_WINDOW) -> pd.DataFrame:
    pc = close.shift(1)
    tr = np.fmax(np.fmax(high - low, (high - pc).abs()), (low - pc).abs())
    return tr.rolling(n).mean() / close


def load_sectors_stockeasy(path: str = SECTORS_STOCKEASY_CSV) -> tuple[dict[str, str], dict[str, str]]:
    """코드→섹터(대분류), 코드→세부섹터(중분류) — 스탁이지 실제 분류."""
    if not os.path.isfile(path):
        return {}, {}
    s = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    return dict(zip(s["code"], s["sector"])), dict(zip(s["code"], s["sub_sector"]))


def state_series(close: pd.DataFrame, high: pd.DataFrame, h52: pd.DataFrame, volume: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(state 문자열 전체 패널, breakout bool 전체 패널) — 둘 다 n_breaks_60·상태 계산에 같이 쓴다.
    **거래정지 방지**: 그날 거래량이 0(이하)이면 돌파·터치로 안 본다 — 거래정지 종목은 가격이 멈춰 있어(예: 삼부토건
    2026-09 내내 5,820원·거래량 0) 그게 우연히 52주 최고가와 같으면 매일 "돌파" 로 잘못 잡힌다(실측으로 발견해 고침)."""
    traded = (volume > 0).fillna(False)
    breakout = (close >= h52).fillna(False) & traded
    touch_pullback = ((high >= h52) & ~breakout).fillna(False) & traded
    to_high = h52 / close - 1
    state = pd.DataFrame(np.where(h52.isna(), None, "밖"), index=close.index, columns=close.columns, dtype=object)
    for label, lo, hi in reversed(BANDS):  # 넓은 구간부터 채우고 좁은 구간으로 덮어써 경계가 겹쳐도 좁은 쪽이 이긴다
        state = state.mask((to_high > lo) & (to_high <= hi), label)
    prev_breakout = breakout.shift(1).fillna(False).astype(bool)  # shift 가 NaN 을 넣어 object dtype 이 되면 `~`(bitwise)가
    # 파이썬 bool 을 정수로 취급해(~True=-2, 참으로 평가) 다음 줄의 부정이 조용히 틀어진다(실측으로 발견 — astype(bool) 로 고정)
    state = state.mask(breakout & prev_breakout, "돌파성공")
    state = state.mask(breakout & ~prev_breakout, "돌파중")
    state = state.mask(touch_pullback, "터치 후 밀림")
    return state, breakout


def build(b: dict | None = None) -> dict:
    """b(rs_rating.build() 결과)를 받으면 재사용, 없으면 새로 계산(단독 실행용)."""
    b = b or R.build()
    close, high, low, volume, rs, period_rs = b["close"], b["high"], b["low"], b["volume"], b["rs"], b["period_rs"]
    day = close.index[-1]
    h52 = high52_of(high)
    state, breakout = state_series(close, high, h52, volume)
    n_breaks_60 = breakout.rolling(BREAK_WINDOW).sum()
    atr = atr_pct(high, low, close)
    av20 = R.avg_value(close, volume, day, 20)
    today_value = (close * volume).loc[day]
    value_mult20 = today_value / av20.where(av20 > 0)
    to_high_pct = (h52.loc[day] / close.loc[day] - 1) * 100
    all_time_high = close.cummax().shift(1).loc[day]  # 오늘 제외 데이터 기간(2019-04~) 전체 최고 — "역사적 신고가" 판정용
    names = R.load_names()
    markets, sectors, sub_sectors, shares = R.market_of(names), *load_sectors_stockeasy(), R.load_shares()
    try:  # 적정시총(예상 순이익 × 업종 예상 PER 중앙값) — 스냅샷이 없으면 칸만 비운다
        from backtesting.valuation import fair_caps
        fair = fair_caps()
    except (IndexError, OSError, ValueError):
        fair = {}
    def fair_fields(code: str) -> dict:
        f = fair.get(code) or {}
        return {k: f.get(k) for k in ("fair_mcap", "per_fwd", "peer_per", "peer_group")}

    day_state = state.loc[day]
    in_band = (to_high_pct <= CANDIDATE_MAX_PCT * 100) | (high.loc[day] >= h52.loc[day]).fillna(False)
    cand_codes = [c for c in close.columns if day_state.get(c) not in (None, "밖") and (in_band.get(c) or day_state.get(c) in
                 ("돌파중", "돌파성공", "터치 후 밀림"))]

    def spark(code: str) -> list[float | None]:
        s = close[code].tail(60)
        return [None if pd.isna(v) else round(float(v), 2) for v in s]

    candidates = []
    for code in cand_codes:
        state_val = day_state.get(code)
        rs_comp, rs1m = rs.loc[day, code], period_rs["1m"].loc[day, code]
        fresh = (n_breaks_60.loc[day, code] <= FRESH_MAX_BREAKS and not pd.isna(value_mult20.get(code, np.nan))
                and value_mult20.get(code, 0) >= FRESH_MIN_VALUE_MULT and not pd.isna(rs_comp) and rs_comp >= FRESH_MIN_RS
                and state_val in ("근접", "임박"))
        candidates.append({
            "코드": code, "이름": names.get(code, ""), "시장": markets.get(code, ""), "섹터": (sectors.get(code) or "미분류"),
            "상태": state_val, "고가까지": None if pd.isna(to_high_pct.get(code)) else round(float(to_high_pct[code]), 2),
            "spark": spark(code), "high52": None if pd.isna(h52.loc[day, code]) else float(h52.loc[day, code]),
            "atr_pct": None if pd.isna(atr.loc[day, code]) else round(float(atr.loc[day, code]) * 100, 2),
            "현재가": None if pd.isna(close.loc[day, code]) else float(close.loc[day, code]),
            "등락률": _chg_pct(close, day, code),
            "거래대금": None if pd.isna(today_value.get(code)) else int(today_value[code]),
            "value_mult20": None if pd.isna(value_mult20.get(code, np.nan)) else round(float(value_mult20[code]), 2),
            "avg_value_20": None if pd.isna(av20.get(code, np.nan)) else int(av20[code]),
            "n_breaks_60": R._int_or_none(n_breaks_60.loc[day, code]),
            "mcap": int(close.loc[day, code] * shares[code]) if code in shares and not pd.isna(close.loc[day, code]) else None,
            "rs_comp": R._int_or_none(rs_comp), "rs_1m": R._int_or_none(rs1m), "fresh": bool(fresh),
            **fair_fields(code),
        })

    # 그날 하루 돌파만 담으면 다음 날 종가가 새 고가를 못 넘는 순간 사라진다(10-01 사용자: 피에스케이홀딩스 09-29 돌파 → 09-30 실종).
    # 최근 NEW_HIGH_RECENT_DAYS 거래일 안에 종가 돌파가 한 번이라도 있으면 남기고, 마지막 돌파일을 붙인다.
    recent = breakout.iloc[-NEW_HIGH_RECENT_DAYS:]
    last_break = {c: recent.index[recent[c].values][-1] for c in close.columns if recent[c].any()}
    new_high_codes = sorted(last_break, key=lambda c: (last_break[c] != day, c))
    new_highs = []
    for code in new_high_codes:
        new_highs.append({
            "최근돌파일": last_break[code].date().isoformat(), "오늘돌파": bool(last_break[code] == day),
            "코드": code, "이름": names.get(code, ""), "섹터": (sectors.get(code) or "미분류"), "세부섹터": (sub_sectors.get(code) or "미분류"),
            "현재가": None if pd.isna(close.loc[day, code]) else float(close.loc[day, code]),
            "등락률": _chg_pct(close, day, code),
            "당일고가": None if pd.isna(high.loc[day, code]) else float(high.loc[day, code]),
            "당일저가": None if pd.isna(low.loc[day, code]) else float(low.loc[day, code]),
            "시총": int(close.loc[day, code] * shares[code]) if code in shares and not pd.isna(close.loc[day, code]) else None,
            "거래대금": None if pd.isna(today_value.get(code)) else int(today_value[code]),
            "rs_comp": R._int_or_none(rs.loc[day, code]),
            "역사적_신고가": bool(not pd.isna(close.loc[day, code]) and not pd.isna(all_time_high.get(code, np.nan))
                              and close.loc[day, code] >= all_time_high[code]),
            **fair_fields(code),
        })
    cards = {
        "신선 후보": sum(1 for r in candidates if r["fresh"]),
        "돌파권": sum(1 for r in candidates if r["상태"] == "임박"),
        "돌파 중": sum(1 for r in candidates if r["상태"] in ("돌파중", "돌파성공")),
        "터치 후 밀림": sum(1 for r in candidates if r["상태"] == "터치 후 밀림"),
    }
    sector_avg_chg = {}
    for r in new_highs:
        sector_avg_chg.setdefault(r["섹터"], []).append(r["등락률"] or 0.0)  # "섹터" 는 이제 항상 문자열("미분류" 포함) — 위 표기와 통일
    sector_avg_chg = {k: round(sum(v) / len(v), 2) for k, v in sector_avg_chg.items()}
    sector_rs = R.sector_rs_median(rs.loc[day], sectors)  # 섹터 칩 색용(강함 주황~약함 파랑), 09-28 22:45 편지
    return {"date": day.date().isoformat(), "cards": cards, "candidates": candidates, "new_highs": new_highs,
           "sector_avg_chg": sector_avg_chg, "sector_rs": sector_rs}


def build_ohlc(codes: list[str], days: int = OHLC_DAYS, daily_dir: str = "data/stocks/daily") -> dict:
    """{코드: [[yyyymmdd, 시, 고, 저, 종, 거래량], ...]} 최근 days 거래일. 시가는 build() 가 안 들고 있어 CSV 에서 직접 읽는다."""
    out = {}
    for code in dict.fromkeys(codes):
        path = os.path.join(daily_dir, f"{code}.csv")
        if not os.path.exists(path):
            continue
        d = pd.read_csv(path, usecols=["date", "open", "high", "low", "close", "volume"]).tail(days)
        out[code] = [[int(r.date.replace("-", "")), *(round(float(x), 2) for x in (r.open, r.high, r.low, r.close)), int(r.volume)]
                     for r in d.itertuples(index=False)]
    return out


def _chg_pct(close: pd.DataFrame, day: pd.Timestamp, code: str) -> float | None:
    idx = close.index.get_loc(day)
    if idx == 0:
        return None
    c0, c1 = close.iloc[idx][code], close.iloc[idx - 1][code]
    return None if pd.isna(c0) or pd.isna(c1) or c1 == 0 else round(float(c0 / c1 - 1) * 100, 2)


def write_json(payload: dict, path: str = OUT_PATH, compact: bool = False) -> str:
    """rs_top2.json 과 같은 허브 잠금(rs_rating) — 같은 야간 갱신 자리에서 순서대로 도니 겹쳐 잡히지 않는다."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with write("rs_rating", writer="new_high.write_json", detail={"date": payload.get("date"), "n_candidates": len(payload.get("candidates", []))}):
        tmp = f"{path}.tmp"
        json.dump(payload, open(tmp, "w", encoding="utf-8"), ensure_ascii=False,
                  **({"separators": (",", ":")} if compact else {"indent": 1}))
        os.replace(tmp, path)
    return path


def publish(payload: dict) -> str:
    """newhigh.json + 화면 오버용 52주 일봉(newhigh_ohlc.json)을 같이 쓴다 — 야간 갱신도 이걸 부른다."""
    path = write_json(payload)
    codes = [r["코드"] for r in payload["candidates"]] + [r["코드"] for r in payload["new_highs"]]
    write_json(build_ohlc(codes), OHLC_PATH, compact=True)
    return path


def build_ledger(b: dict) -> dict:
    """신고가 장부 — **당일 고가**가 직전 120거래일 고가 이상이고 그날 대금 LEDGER_MIN_VALUE 이상인 전 기간 건.
    종가 기준(state_series 의 돌파)으로 거르면 장중에 뚫고 밀린 날이 통째로 빠진다(09-30 사용자: JW신약 9월 4번 누락) —
    HTS 신고가는 고가 기준이라 그쪽에 맞췄다. 120일 고가 ≤ 52주 고가라 52주 건은 120일 건의 부분집합이고, 화면이
    당일 고가 ≥ 52주 고가 로 다시 걸러 두 기준을 전환한다(현대약품 9월은 120일만 해당).
    행: [날짜, 코드, 이름, 대금(억), 52주고가, 120일고가, 당일고가, 종가, 당일등락%, 5일뒤%, 20일뒤%, RS종합,
         상장 후 거래일(250일 이하 신규상장주만, 아니면 null)]."""
    close, high, volume, rs = b["close"], b["high"], b["volume"], b["rs"]
    names = R.load_names()
    keep = [c for c in close.columns if c not in R.excluded_codes(names)]
    close, high, volume = close[keep], high[keep], volume[keep]
    # 갓 상장한 종목은 stock_names.json 에 아직 없다(09-30 스카이랩스·네오사피엔스가 코드로만 떴다) — 스탁이지 분류 파일 이름으로 메운다
    if os.path.isfile(SECTORS_STOCKEASY_CSV):
        se = pd.read_csv(SECTORS_STOCKEASY_CSV, dtype=str, encoding="utf-8-sig")
        names = {**dict(zip(se["code"], se["name"])), **names}
    h52 = high52_of(high)
    h120 = high.shift(1).rolling(LEDGER_SHORT_WINDOW).max()
    # 신규상장주는 250(120)일이 안 차 NaN 이라 통째로 빠졌다(09-30 사용자) — 상장 이후 최고가를 기준으로 쓴다.
    # 일봉이 데이터 시작일(2019-04)부터 있는 종목은 '신규'가 아니라 우리 기간이 짧은 것이라 그대로 둔다. 상장 첫날은 비교 대상이 없어 제외.
    new_cols = [c for c in keep if close[c].first_valid_index() is not None and close[c].first_valid_index() > close.index[0]]
    age = high[new_cols].notna().cumsum()  # 상장 후 거래일 수(상장일=1)
    h52[new_cols] = h52[new_cols].fillna(high[new_cols].shift(1).rolling(HIGH52_WINDOW, min_periods=1).max())
    h120[new_cols] = h120[new_cols].fillna(high[new_cols].shift(1).rolling(LEDGER_SHORT_WINDOW, min_periods=1).max())
    value = close * volume
    hit = ((high >= h120) & (volume > 0) & (value >= LEDGER_MIN_VALUE)).stack()
    prev, f5, f20 = close.shift(1), close.shift(-5) / close - 1, close.shift(-20) / close - 1
    rs = rs.reindex(index=close.index, columns=keep)
    pct = lambda x: None if pd.isna(x) else round(float(x) * 100, 1)
    num = lambda x: None if pd.isna(x) else round(float(x))
    rows = []
    for d, c in hit[hit].index:
        cl, r = close.at[d, c], rs.at[d, c]
        a = int(age.at[d, c]) if c in age.columns else None
        rows.append([d.strftime("%Y-%m-%d"), c, names.get(c, c), round(value.at[d, c] / 1e8), num(h52.at[d, c]), round(h120.at[d, c]),
                     round(high.at[d, c]), round(cl), pct(cl / prev.at[d, c] - 1), pct(f5.at[d, c]), pct(f20.at[d, c]),
                     None if pd.isna(r) else int(r), a if a is not None and a <= HIGH52_WINDOW else None])
    rows.sort()
    return {"date": close.index[-1].date().isoformat(), "min_value_eok": int(LEDGER_MIN_VALUE / 1e8), "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reuse-rs", action="store_true", help="rs_rating 캐시 parquet 를 읽어 재사용(빠름, 이미 그날 RS 를 만들어 둔 뒤에만)")
    a = ap.parse_args()
    b = None
    if a.reuse_rs:
        b = _load_cached_rs()
    b = b or R.build()
    payload = build(b)
    path = publish(payload)
    write_json(build_ledger(b), LEDGER_PATH, compact=True)
    print(f"저장: {path} — 후보 {len(payload['candidates'])}종목 · 신고가 {len(payload['new_highs'])}종목 · 카드 {payload['cards']}")


def _load_cached_rs() -> dict:
    close = R.wide_close()
    high, low = R.wide_high_low()
    volume = R.wide_volume()
    rs = pd.read_parquet(R.RS_PATH)
    period_rs = {k: pd.read_parquet(p) for k, p in R.PERIOD_PATH.items()}
    return {"close": close, "high": high, "low": low, "volume": volume, "raw": None, "rs": rs, "period_rs": period_rs}


if __name__ == "__main__":
    main()
