"""52주 신고거래대금 장부 (사용자 2026-10-09) — 화면: /value_ledger.html (신고가 장부와 같은 월 칸 모양).

    python -m backtesting.value_ledger          # → static/dashboard/value_ledger.json
    python -m backtesting.value_ledger --csv    # + results/value_record_52w/{YYYY-MM}.csv·_summary.csv

52주 신고거래대금 = 그날 통합(AL) 실거래대금이 **그날 제외** 직전 245거래일 최대를 넘은 날
(value_burst 의 '1년' 등급과 같은 정의 · 245거래일이 안 찬 종목·날은 판정 안 함 — 상장 초기엔 아무 날이나 신고가 된다).
대금은 data/stocks/daily_al(value_mw, 백만원) — KRX 일봉은 NXT 가 빠져 2025-03 뒤로 반 토막이라 쓰지 않는다.
저장 하한 1,000억(10-09 사용자). 정규장_억(10-13 사용자) = 그날 대금 중 09:00~15:30 몫이 직전 245거래일의 정규장 대금 최대를 넘은 날에만 채운다(1,000억+). 몫을 구하는 차례:
①통합 분봉(2026-08-24~, 없으면 체결 틱)으로 잰다 ②NXT 거래가 없는 날은 1분봉(2025-07~)으로 잰다
③그 밖은 추정(정규장추정=1): KRX 몫 × 1분봉 정규장 비중 + NXT 몫 × 0.644 — 1,000억+ 983종목일에서 오차 중앙 1.9%·90%가 ±8% 안
④NXT 개장(2025-03-04) 전은 하루 전체와 같다(정규장추정=2 — 분봉이 없어 KRX 장후 시간외 거래를 못 뗀다, 보통 1% 안팎).
정규_* 칸 = 등락·뒤 수익·고점·MDD 를 정규장 가격(1분봉의 15:30 종가·정규장 고저, 없으면 KRX 일봉)으로 잰 값 — 일봉 종가·고가엔 장전·장후 가격이 들어 있다.
전체신고 = 하루 전체 기준 신고 여부(정규장 기준으로만 신고인 줄은 0).
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import numpy as np
import pandas as pd

OUT_PATH = "static/dashboard/value_ledger.json"
CSV_DIR = "results/value_record_52w"
Y1 = 245
Y4 = 980  # 역대 판정에 필요한 최소 이력(value_burst 의 4년과 같은 길이)
PEAK_DAYS = 20  # 고점을 찾는 창 — 20일뒤 칸과 같은 기간
MIN_EOK = 1000  # 10-09 사용자 "천억 이상만" (처음 300억 = value_burst 저장 하한)
RREFS: dict[str, int] = {}  # events() 가 채운다 — 종목별 직전 1년 정규장 대금 최대(억)
COLS = ["날짜", "코드", "종목명", "거래대금_억", "직전52주최대_억", "배수", "평소20일대비", "등락률%", "종가", "누적횟수", "5일뒤%", "20일뒤%", "역대", "고점%", "고점일", "저점%", "저점일", "정규장_억", "정규장역대", "정규장추정", "정규_등락률%", "정규_종가", "정규_5일뒤%", "정규_20일뒤%", "정규_고점%", "정규_고점일", "정규_저점%", "정규_저점일", "전체신고", "정규직전최대_억", "정규누적", "정규평소20일대비", "전체저점%", "전체저점일", "정규_전체저점%", "정규_전체저점일"]


DAILY_AL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "stocks", "daily_al")


def daily_al_rows(code: str, base: str = DAILY_AL_DIR) -> list[list] | None:
    """장부 화면 차트용(8765 /api/daily-al) — 통합 수정주가 일봉 [[YYYYMMDD, 시, 고, 저, 종, 거래량], ...]. 읽기만.
    코드가 6자리(숫자·대문자)가 아니면 ValueError(경로 조작 방지), 파일이 없으면 None."""
    if not (isinstance(code, str) and len(code) == 6 and code.isascii() and code.isalnum() and code == code.upper()):
        raise ValueError("code 는 6자리")
    p = os.path.join(base, f"{code}.csv")
    if not os.path.isfile(p):
        return None
    import csv
    out = []
    with open(p, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                out.append([r["date"], float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), float(r["volume"])])
            except (KeyError, ValueError):
                continue
    return out


def events() -> pd.DataFrame:
    names = json.load(open("data/stock_names.json", encoding="utf-8"))
    rows = []
    for p in glob.glob("data/stocks/daily_al/*.csv"):
        d = pd.read_csv(p, dtype={"date": str})
        if len(d) <= Y1:
            continue
        val = d.value_mw / 100  # 억
        if not (val >= MIN_EOK).any():
            continue
        prev_max = val.shift(1).rolling(Y1, min_periods=Y1).max().replace(0, np.nan)  # 1년 넘게 거래정지 뒤 재개는 비교 대상이 없어 뺀다
        full = (val > prev_max) & (val >= MIN_EOK)
        code = os.path.basename(p)[:6]
        c = d.close
        kp = f"data/stocks/daily/{code}.csv"  # KRX 전용 일봉 — 대금은 없고 거래량만 있다
        k = (pd.read_csv(kp).assign(date=lambda x: x.date.str.replace("-", "")).set_index("date") if os.path.isfile(kp)
             else pd.DataFrame(columns=["high", "low", "close", "volume"], dtype=float)).reindex(d.date).reset_index(drop=True)
        kr = (k.volume / d.volume.replace(0, np.nan)).clip(0, 1)  # 그날 통합 거래량 중 KRX 몫
        # 정규장 가격: 1분봉(2025-07~)이 있는 날은 09:00~15:30 봉으로, 없으면 KRX 일봉. KRX 일봉 종가는 20시 장후 종가다
        # (동국산업 10-08 KRX 일봉 4,635 = 19:59 가격, 15:30 종가는 4,710 · 안랩 10-06 90,200 vs 89,000 — 10-13 사용자 지적)
        recent = bool((val[d.date >= MIN_FROM] >= MIN_EOK).any())
        md = (minute_days(code) if recent else MD_EMPTY).reindex(d.date).reset_index(drop=True)
        md.loc[~md.close.between(d.low, d.high), ["high", "low", "close"]] = np.nan  # 분봉은 수정주가가 아니다 — 통합 일봉 범위를 벗어난 날(액면분할·감자 앞)은 버린다
        # 정규장 대금 = 대금 × 정규장 몫. 몫은 ①통합 분봉·틱(잰 값) ②NXT 거래 없는 날의 1분봉(잰 값)
        # ③KRX 몫 × 1분봉 정규장 비중 + NXT 몫 × NXT_REG(추정) ④NXT 개장 전은 1(장후 시간외를 못 뗀다)
        pre = d.date < NXT_OPEN.replace("-", "")
        exact = (al_shares(code, d, val) if recent else pd.Series(np.nan, index=d.index)).fillna(md.rk.where(kr >= 1))
        share = exact.fillna(kr * md.rk.fillna(1) + NXT_REG * (1 - kr)).mask(pre, 1.0)
        est = (exact.isna() & kr.notna()).astype(int).mask(pre, 2)  # 1 추정 · 2 장후 시간외 포함
        reg = val * share
        # 정규장 신고 = 정규장 대금이 직전 245거래일의 '정규장 대금' 최대를 넘은 날. 하루 전체 최대와 견주면 심텍 9/22(정규장 4,822억 vs
        # 2025-11-10 하루 전체 5,078억)처럼 장전·장후 대금에 밀려 빠진다(10-13 사용자)
        rpm = reg.shift(1).rolling(Y1, min_periods=Y1).max().replace(0, np.nan)
        rhit = (reg > rpm) & (reg >= MIN_EOK)
        rref = reg.tail(Y1).max()  # 장중 반영용 — 오늘 기준 '어제까지 1년 정규장 대금 최대'(정규장만 보기, 10-15 사용자 에스엠벡셀)
        if rref > 0:
            RREFS[code] = int(round(rref))
        hit = full | rhit
        if not hit.any():
            continue
        kc = md.close.fillna(k.close).ffill()                      # 쉰 날(거래정지)은 앞 종가로 메운다
        at = np.flatnonzero(hit.to_numpy())
        kpk = [_peak(md.high.fillna(k.high).fillna(kc).to_numpy(), i, kc.iat[i]) for i in at]
        kdp = [_peak(md.low.fillna(k.low).fillna(kc).to_numpy(), i, kc.iat[i], low=True, days=x[1]) for i, x in zip(at, kpk)]
        peak = [_peak(d.high.to_numpy(), i, c.iat[i]) for i in at]
        dip = [_peak(d.low.to_numpy(), i, c.iat[i], low=True, days=pk[1]) for i, pk in zip(at, peak)]
        klo = [_peak(md.low.fillna(k.low).fillna(kc).to_numpy(), i, kc.iat[i], low=True) for i in at]
        lo = [_peak(d.low.to_numpy(), i, c.iat[i], low=True) for i in at]  # 고점일과 상관없이 뒤 20거래일 최저 — 장중에 고점이 오늘로 옮겨 가면 화면이 MDD 를 다시 잡는 데 쓴다
        rows.append(pd.DataFrame({
            "날짜": pd.to_datetime(d.date[hit]).dt.strftime("%Y-%m-%d"), "코드": code, "종목명": names.get(code, code),
            "거래대금_억": val[hit].round(0), "직전52주최대_억": prev_max[hit].round(0), "배수": (val / prev_max)[hit].round(2),
            "평소20일대비": (val / val.shift(1).rolling(20).mean().replace(0, np.nan))[hit].round(1),  # 직전 20일 대금 0(거래정지 뒤 재개)이면 빈칸
            "등락률%": ((c / c.shift(1) - 1) * 100)[hit].round(2), "종가": c[hit],
            "5일뒤%": ((c.shift(-5) / c - 1) * 100)[hit].round(2), "20일뒤%": ((c.shift(-20) / c - 1) * 100)[hit].round(2),
            # 역대 = 데이터 전체 기간(2019-06 또는 상장 이후) 그날 제외 최대 초과. 앞선 데이터가 4년(980거래일) 안 되면 판정 안 함 —
            # 데이터가 2019-06 부터라 1년만 재면 2020~21년 신고의 92~98% 가 '역대'가 돼 52주와 구분이 안 된다(10-10)
            "역대": (full & (val > val.shift(1).expanding(min_periods=Y4).max()))[hit],
            "고점%": [x[0] for x in peak], "고점일": [x[1] for x in peak], "저점%": [x[0] for x in dip], "저점일": [x[1] for x in dip],
            "정규장_억": reg.where(rhit)[hit].round(0), "정규장역대": (rhit & (reg > reg.shift(1).expanding(min_periods=Y4).max()))[hit], "정규장추정": est[hit],
            "정규_등락률%": ((kc / kc.shift(1) - 1) * 100)[hit].round(2), "정규_종가": kc[hit],
            "정규_5일뒤%": ((kc.shift(-5) / kc - 1) * 100)[hit].round(2), "정규_20일뒤%": ((kc.shift(-20) / kc - 1) * 100)[hit].round(2),
            "정규_고점%": [x[0] for x in kpk], "정규_고점일": [x[1] for x in kpk], "정규_저점%": [x[0] for x in kdp], "정규_저점일": [x[1] for x in kdp],
            "전체신고": full[hit], "정규직전최대_억": rpm[hit].round(0), "전체저점%": [x[0] for x in lo], "전체저점일": [x[1] for x in lo],
            "정규_전체저점%": [x[0] for x in klo], "정규_전체저점일": [x[1] for x in klo],
            "정규평소20일대비": (reg / reg.shift(1).rolling(20).mean().replace(0, np.nan))[hit].round(1)}))
    out = pd.concat(rows).sort_values(["날짜", "거래대금_억"], ascending=[True, False]).reset_index(drop=True)
    out["누적횟수"] = out[out["전체신고"]].groupby("코드").cumcount() + 1  # 데이터 시작 이후 그 종목의 몇 번째 52주 신고인지
    out["정규누적"] = out[out["정규장_억"].notna()].groupby("코드").cumcount() + 1
    return out[COLS].reset_index(drop=True)


def al_shares(code: str, d: pd.DataFrame, val: pd.Series) -> pd.Series:
    """통합 분봉(보관소 ∪ 캐시)으로 잰 날짜별 정규장 대금 비중(d 와 같은 줄). 분봉이 없는 1,000억+ 날은 체결 틱으로 메운다."""
    from datahub import minute_al_archive as arch
    m = pd.concat([arch.read(code), arch.read_cache(code)])
    m = m[~m.index.duplicated(keep="last")]
    sh = pd.Series(np.nan, index=d.index)
    if len(m):
        v, t, day = m.close * m.volume, m.index.hour * 60 + m.index.minute, m.index.strftime("%Y%m%d")
        r = (t >= 540) & (t <= 930)
        sh = (v[r].groupby(day[r]).sum() / v.groupby(day).sum().replace(0, np.nan)).reindex(d.date).reset_index(drop=True)
    for i in np.flatnonzero((sh.isna() & (val >= MIN_EOK) & (d.date >= REG_FROM.replace("-", ""))).to_numpy()):
        ymd = d.date.iat[i]
        p = f"data/stocks/tick_al/{code}/{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}.parquet"
        if os.path.isfile(p):
            x = pd.read_parquet(p, columns=["time", "cur_prc", "trde_qty"])
            v, t = x.cur_prc.abs() * x.trde_qty.abs(), x.time.str[:2].astype(int) * 60 + x.time.str[2:4].astype(int)
            sh.iat[i] = v[(t >= 540) & (t <= 930)].sum() / v.sum() if v.sum() else np.nan
    return sh


REG_FROM = "2026-08-24"  # 통합 분봉 보관소가 시작된 날 — 그 앞은 정규장 몫을 잴 수 없다(추정)
NXT_OPEN = "2025-03-04"  # 넥스트레이드 개장. 그 전엔 장전·장후 시장이 없어 하루 전체 = 정규장(KRX 거래량 = 통합 거래량 확인)
NXT_REG = 0.644          # NXT 거래 중 정규장(09:00~15:30) 몫 — 2026-08-25~10-02 분봉으로 잰 1,000억+ 종목일의 중앙값


MIN_FROM = "20250701"  # data/stocks/minute 1분봉이 시작되는 달
MD_EMPTY = pd.DataFrame(columns=["rk", "high", "low", "close"], dtype=float)


def minute_days(code: str) -> pd.DataFrame:
    """data/stocks/minute 1분봉의 날짜(YYYYMMDD)별 정규장(09:00~15:30) 거래량 비중 rk 와 정규장 고가·저가·종가.
    일봉 거래량·가격엔 장후 거래가 들어 있다(동국산업 10-08: 정규장 946억 + 장후 103억). 09:05 전에 시작해 15:19 뒤까지 있는 날만 쓴다."""
    p = f"data/stocks/minute/{code}.csv"
    if not os.path.isfile(p):
        return MD_EMPTY
    m = pd.read_csv(p)
    t = m.date.str[11:13].astype(int) * 60 + m.date.str[14:16].astype(int)
    day = m.date.str[:10].str.replace("-", "")
    r = m[(t >= 540) & (t <= 930)].assign(t=t, day=day)
    g = r.groupby("day")
    out = pd.DataFrame({"rk": g.volume.sum() / m.volume.groupby(day).sum().replace(0, np.nan),
                        "high": g.high.max(), "low": g.low.min(), "close": g.close.last()})
    return out[(g.t.min() <= 545) & (g.t.max() >= 919)].astype(float)


def _peak(px: np.ndarray, i: int, buy: float, low: bool = False, days: float = PEAK_DAYS) -> tuple:
    """i 번째 날 종가(buy)에 산 뒤 PEAK_DAYS 거래일 안의 장중 최고가(low=True 면 최저가) 수익률(%)과 며칠째인지. 뒷날이 없으면 (nan, nan)."""
    if days != days:                                   # 고점이 없으면(nan) 저점도 없다
        return (np.nan, np.nan)
    w = px[i + 1:i + 1 + int(days)]
    if not w.size or not buy:
        return (np.nan, np.nan)
    k = int(w.argmin() if low else w.argmax())
    return (round((w[k] / buy - 1) * 100, 2), k + 1)


def build(e: pd.DataFrame) -> dict:
    rows = e.replace({np.nan: None}).values.tolist()
    i_ = lambda x: None if x is None else int(x)
    rows = [[r[0], r[1], r[2], int(r[3]), i_(r[4]), r[5], r[6], r[7], int(r[8]), i_(r[9]), r[10], r[11], int(bool(r[12])), r[13], None if r[14] is None else int(r[14]), r[15], None if r[16] is None else int(r[16]),
             None if r[17] is None else int(r[17]), int(bool(r[18])), int(r[19]),
             r[20], None if r[21] is None else int(r[21]), r[22], r[23], r[24], None if r[25] is None else int(r[25]), r[26], i_(r[27]),
             int(bool(r[28])), i_(r[29]), i_(r[30]), r[31], r[32], i_(r[33]), r[34], i_(r[35])] for r in rows]
    try:  # 장중 반영용 — 종목별 '어제까지 1년 최대 대금'(억). value_burst 가 밤마다 쓰는 기준을 그대로 싣는다(같은 245일·같은 통합 일봉)
        from .value_burst import REFS_PATH
        refs = {c: v["y1"] for c, v in json.load(open(REFS_PATH, encoding="utf-8"))["codes"].items() if v.get("y1")}
    except (OSError, KeyError, ValueError):
        refs = {}
    return {"date": e["날짜"].max(), "min_value_eok": MIN_EOK, "days": Y1, "regular_from": REG_FROM, "refs": refs, "rrefs": RREFS, "rows": rows,
            "tail": pd.read_csv("data/stocks/daily_al/005930.csv", dtype={"date": str}).date.tail(PEAK_DAYS).map(lambda x: f"{x[:4]}-{x[4:6]}-{x[6:]}").tolist()}  # 마지막 20거래일 — 이 안의 신고는 고점 창이 아직 열려 있다  # rows 28~31 = 하루 전체 신고 여부 · 정규장 직전 최대 · 정규장 누적 · 정규장 평소대비


def write_json(payload: dict, path: str = OUT_PATH) -> str:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)  # NaN·inf 는 브라우저 JSON 이 못 읽는다
    os.replace(tmp, path)
    return path


def write_csv(e: pd.DataFrame) -> None:
    os.makedirs(CSV_DIR, exist_ok=True)
    e = e[e["전체신고"]]
    m = e["날짜"].str[:7]
    for k, g in e.groupby(m):
        g.to_csv(f"{CSV_DIR}/{k}.csv", index=False, encoding="utf-8-sig")
    e.groupby(m).agg(건수=("코드", "size"), 종목수=("코드", "nunique"), 거래일수=("날짜", "nunique"),
                     대금합_억=("거래대금_억", "sum"), 대금중앙_억=("거래대금_억", "median"),
                     등락률중앙=("등락률%", "median")).rename_axis("월").to_csv(f"{CSV_DIR}/_summary.csv", encoding="utf-8-sig")


def demo() -> None:
    """정의 점검: 245일 평탄 뒤 큰 날 → 신고, 그보다 작은 다음 날 → 아님."""
    v = pd.Series([1200.0] * 250 + [1500, 1300, 1600])
    pm = v.shift(1).rolling(Y1, min_periods=Y1).max()
    assert list(((v > pm) & (v >= MIN_EOK)).iloc[-3:]) == [True, False, True]
    assert _peak(np.array([100.0, 105, 120, 110]), 0, 100.0) == (20.0, 2)      # 이틀째 고가 120
    assert _peak(np.array([100.0, 95, 80, 90]), 0, 100.0, low=True) == (-20.0, 2)  # 이틀째 저가 80
    assert _peak(np.array([100.0, 95, 80, 90]), 0, 100.0, low=True, days=1) == (-5.0, 1)  # 고점이 첫날이면 첫날 저가까지만
    assert np.isnan(_peak(np.array([100.0]), 0, 100.0)[0])                     # 뒷날이 없다


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="store_true")
    a = ap.parse_args()
    demo()
    e = events()
    p = build(e)
    print(f"52주 신고거래대금 {len(p['rows'])}건 → {write_json(p)} (기준일 {p['date']})")
    if a.csv:
        write_csv(e)
