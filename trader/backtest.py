"""매매 데스크 규칙 백테스트 → 백테스트 스튜디오 실행 기록(results/studio/<run_id>).

rules.json 의 매수 규칙(기준일 종가 분할매수)·청산 규칙·안전장치를 신고대금 장부의 신고일에 그대로 대입한다.
청산 판단과 1종목 금액은 데스크와 같은 함수(trader.engine.exit_actions·take_orders·per_stock_amount)를 쓴다.

5분봉: session=all 통합 분봉(2026-08-24 부터) · reg KRX 정규장 1분봉(2025-07 부터). 둘을 섞지 않는다(통합 원칙, 정규장은 사용자가 고른 실행만).
봉 안 순서는 모르니 보수적으로 — 지정가 매수는 저가가 닿으면(시가가 이미 아래면 시가), 같은 봉에서 손절·되밀림을 익절보다 먼저 본다.
대기 순번은 안 따진다(닿으면 체결 — 실제보다 조금 유리).

  python -m trader.backtest --rule closeladder --start 2026-01-01 --end 2026-10-16 --session reg
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import sys
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trader import engine  # noqa: E402

STATE = ROOT / "state" / "trader"
STATUS = STATE / "backtest_status.json"
AL_FROM = "2026-08-24"                              # 통합 1분봉 보관소가 시작된 날
FEE, TAX = 0.00015, 0.002                           # 수수료(양쪽 0.015%) · 매도 세금 0.20%(10-20 사용자 — 2026 세율로)
REASON = {"stop": "stop", "trail": "trailing", "take": "target", "close": "eod", "days": "time", "end": "end_of_data"}


def _status(**kw) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    cur = {}
    try:
        cur = json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    cur.update(kw, t=datetime.now().isoformat(timespec="seconds"))
    STATUS.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")


@functools.lru_cache(maxsize=4096)
def _market_day(d: date) -> bool:
    """거래일 — 원본은 부를 때마다 휴장일 파일을 다시 읽어 1.7ms(10-20 측정, 백테스트 시간의 60%)라 날짜별로 기억한다."""
    from backtesting.value_burst_live import _is_market_day
    return _is_market_day(d)


def _next_days(rd: str, n: int) -> list[str]:
    d, out = date.fromisoformat(rd), []
    while len(out) < n:
        d += timedelta(days=1)
        if _market_day(d):
            out.append(d.strftime("%Y%m%d"))
    return out


def events(start: str, end: str, min_chg: float, base: str, session: str, reg_only: bool = False) -> list[tuple[str, str, str, int]]:
    """(신고일, 코드, 이름, 기준가) — 신고대금 장부에서 그날 상승률 ≥ min_chg. 등락·종가는 실행 세션 기준(정규장 / 통합)."""
    rows = json.loads((ROOT / "static" / "dashboard" / "value_ledger.json").read_text(encoding="utf-8"))["rows"]
    out = []
    for x in rows:
        if not (start <= x[0] <= end) or (reg_only and x[17] is None):
            continue                                                # reg_only: 정규장 몫으로도 신고대금인 날만(통합으로만 신고대금인 날 빼기)
        chg = x[20] if session == "reg" else x[7]
        px = x[21] if base == "reg" else x[8]
        # 장부 '종가'(통합 일봉)는 수정주가라 액면분할·권리락이 있으면 실제 분봉 가격과 어긋난다(한화 2025-07-01 130,614 vs 실제 108,800,
        # 중앙첨단소재 10배). 정규장 종가와 5% 넘게 다르면 장후 움직임이 아니라 수정주가 차이로 보고 정규장 종가를 쓴다(10-19 확인: 2025-07~ 1,736건 중 94건)
        if base != "reg" and x[21] and px and abs(px / x[21] - 1) > 0.05:
            px = x[21]
        if chg is not None and chg >= min_chg and px:
            out.append((x[0], x[1], x[2], int(px)))
    return out


_BARS: dict = {}                                    # 같은 대상·기간을 여러 청산 규칙으로 돌릴 때(비교 실행) 다시 안 읽는다


CACHE = STATE / "bt_cache"


def _disk(name: str, make):
    """하루 동안 디스크에 둔다(밤 갱신 뒤엔 새로) — 같은 대상·기간 백테스트를 다시 돌릴 때 분봉·일봉을 다시 안 읽는다(10-20 측정: 첫 실행의 대부분)."""
    import hashlib
    import pickle
    p = CACHE / f"{date.today():%Y%m%d}-{hashlib.sha1(name.encode()).hexdigest()[:16]}.pkl"
    if p.exists():
        try:
            return pickle.loads(p.read_bytes())
        except Exception:                                           # noqa: BLE001 — 깨졌으면 새로 만든다
            pass
    v = make()
    CACHE.mkdir(parents=True, exist_ok=True)
    for old in sorted(CACHE.glob("*.pkl"))[:-12]:                   # 최근 12개만
        old.unlink(missing_ok=True)
    for old in CACHE.glob("*.pkl"):
        if not old.name.startswith(f"{date.today():%Y%m%d}"):
            old.unlink(missing_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_bytes(pickle.dumps(v, protocol=pickle.HIGHEST_PROTOCOL))
        os.replace(tmp, p)
    except OSError:                                                 # 다른 백테스트가 같은 파일을 쓰는 중 — 캐시만 못 남길 뿐
        tmp.unlink(missing_ok=True)
    return v


def _src_mtime(code: str) -> float:
    """그 종목 분봉·일봉 파일 중 가장 늦게 바뀐 시각 — 낮에 분봉을 더 받으면(10-30 한국콜마 7월분) 캐시를 다시 만들게."""
    from backtesting.value_ledger import DAILY_AL_DIR, MINUTE_AL_ARCHIVE_DIR, MINUTE_AL_CACHE_DIR, MINUTE_KRX_DIR
    fs = (os.path.join(MINUTE_AL_ARCHIVE_DIR, code + ".parquet"), os.path.join(MINUTE_AL_CACHE_DIR, code + ".csv"),
          os.path.join(MINUTE_KRX_DIR, code + ".csv"), os.path.join(MINUTE_KRX_DIR, code + ".parquet"), os.path.join(DAILY_AL_DIR, code + ".csv"))
    return max((os.path.getmtime(f) for f in fs if os.path.isfile(f)), default=0.0)


def _per_code(kind: str, code: str, make):
    """종목 하나씩 하루 디스크 캐시 — 조건(상승률·기간)이 바뀌어 대상 묶음이 달라도 한 번 읽은 종목은 다시 안 읽는다(10-20: 첫 실행 123초 중 118초가 CSV 읽기)."""
    import pickle
    import shutil
    day = f"{date.today():%Y%m%d}"
    p = CACHE / "codes" / day / kind / f"{code}.pkl"
    mt = _src_mtime(code)
    try:
        hit = pickle.loads(p.read_bytes())
        if isinstance(hit, tuple) and len(hit) == 2 and hit[0] == ("mt", mt):
            return hit[1]                                           # 파일이 그대로면 저장본(바뀌었으면 아래에서 새로)
    except Exception:                                               # noqa: BLE001 — 없거나 깨졌으면 새로
        pass
    if not getattr(_per_code, "swept", False):                      # 지난 날짜 폴더는 지운다(밤마다 데이터가 갱신된다)
        _per_code.swept = True
        for old in (CACHE / "codes").glob("*"):
            if old.name != day:
                shutil.rmtree(old, ignore_errors=True)
    v = make()
    if v is None:
        return v                                                    # 없음은 남기지 않는다 — 낮에 받은 새 종목 분봉(10-30 엘리스 보충)을 그날 바로 쓰게
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_bytes(pickle.dumps((("mt", mt), v), protocol=pickle.HIGHEST_PROTOCOL))
        os.replace(tmp, p)
    except OSError:
        tmp.unlink(missing_ok=True)
    return v


def _code_bars(c: str, session: str):
    """한 종목 5분봉 전체 — (시각 ns int64, 시·고·저·종 int64) numpy 배열. 없으면 None."""
    import numpy as np
    from backtesting.value_ledger import _load_minute
    raw = _load_minute(c, "all" if session == "all" else "regular")[0]
    if raw is None or raw.empty:
        return None
    raw = raw.copy()
    raw.columns = [x.lower() for x in raw.columns]
    r = raw.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return (r.index.as_unit("ns").asi8.copy(), r["open"].to_numpy(np.int64), r["high"].to_numpy(np.int64), r["low"].to_numpy(np.int64), r["close"].to_numpy(np.int64))


def _code_vcum(c: str, reg_only: bool = False):
    """신고대금 당일(10-21 사용자) — 1분봉마다 그날 누적 대금(종가×거래량)과 등락률(직전 거래일 정규장 종가 대비, 데스크 등락률과 같은 기준).
    통합(_AL) 분봉이 있는 날은 통합, 없는 날은 정규장 분봉(NXT 몫이 빠져 대금이 작게 나온다 — 늦게 잡히거나 못 잡힘).
    reg_only: 정규장 분봉 09:00~15:30 만 — 규칙이 '정규장 신고대금'이면(10-22 사용자, 데스크 _reg_today 와 같은 몫).
    (1분봉 끝 시각 ns, 날짜 'YYYY-MM-DD' 배열, 누적 대금(원), 등락률%) — 없으면 None."""
    import numpy as np
    from backtesting.value_ledger import _load_minute
    parts = []
    for sess in (("regular",) if reg_only else ("all", "regular")):
        raw = _load_minute(c, sess)[0]
        if raw is not None and not raw.empty:
            raw = raw.copy()
            raw.columns = [x.lower() for x in raw.columns]
            if reg_only:
                hm = raw.index.hour * 100 + raw.index.minute
                raw = raw[(hm >= 900) & (hm <= 1530)]
            parts.append(raw[["close", "volume"]])
    if not parts:
        return None
    df = parts[0]
    if len(parts) > 1:                                               # 통합에 없는 날만 정규장으로
        have = set(df.index.normalize())
        df = pd.concat([df, parts[1][~parts[1].index.normalize().isin(have)]]).sort_index()
    day = df.index.normalize()
    cum = (df["close"] * df["volume"]).groupby(day).cumsum()
    t = df.index
    reg = df[(t.hour * 100 + t.minute) <= 1530]["close"].groupby(day[(t.hour * 100 + t.minute) <= 1530]).last()
    prev = reg.shift(1).reindex(day).to_numpy(np.float64)          # 그 전 거래일 정규장 종가
    chg = (df["close"].to_numpy(np.float64) / prev - 1) * 100
    return ((t.as_unit("ns").asi8 + 60 * 10 ** 9).copy(), np.asarray(day.strftime("%Y-%m-%d")), cum.to_numpy(np.float64), chg)


def same_day_cross(evs: list, min_chg: float, reg_only: bool = False) -> dict:
    """(신고일, 코드) → 장중에 신고대금이 된 1분봉 끝 시각(ns). 데스크 value_high_now 와 같은 기준: 그날 누적 대금 ≥ 직전 52주 최대(장부)·1,000억
    이고 그때 등락률 ≥ min_chg. 못 잡으면 빠진다(그 신고일은 예전처럼 다음 거래일부터).
    reg_only: 정규장 누적 대금 ≥ 직전 정규장 최대(장부 '정규직전최대_억')·1,000억."""
    import numpy as np
    rows = json.loads((ROOT / "static" / "dashboard" / "value_ledger.json").read_text(encoding="utf-8"))["rows"]
    thr = {(x[0], x[1]): max((x[29] if reg_only else x[4]) or 0, 1000) * 1e8 for x in rows if not reg_only or (len(x) > 29 and x[29])}
    out = {}
    for rd, c, *_ in evs:
        a = _per_code("vcum_reg" if reg_only else "vcum", c, lambda: _code_vcum(c, reg_only))
        if a is None or (rd, c) not in thr:
            continue
        t, dd, cum, chg = a
        i = np.flatnonzero((dd == rd) & (cum >= thr[(rd, c)]) & (chg >= min_chg))
        if len(i):
            out[(rd, c)] = int(t[i[0]])
    return out


def _code_ma15(c: str, src: str):
    """15분봉 60선 — 데스크 ma60_15 와 같은 봉(reg = KRX 정규장 09:00~15:30 / aft = 통합 08~20시). 데스크는 만드는 중인 15분봉도
    지금가로 넣는다 — 여기선 5분 단위로: 5분봉 i 가 끝난 때의 60선 = (앞 15분봉 59개 종가 + 그 5분봉 종가) / 60.
    (5분봉 끝 시각 ns, 그때 60선) — 앞 15분봉이 59개가 안 되면 0. 없으면 None."""
    import numpy as np
    from backtesting.value_ledger import _load_minute
    raw = _load_minute(c, "regular" if src == "reg" else "all")[0]
    if raw is None or raw.empty:
        return None
    cl = raw[[x for x in raw.columns if x.lower() == "close"][0]]
    s5, s15 = cl.resample("5min").last().dropna(), cl.resample("15min").last().dropna()
    q = 15 * 60 * 10 ** 9
    t5, k15 = s5.index.as_unit("ns").asi8, s15.index.as_unit("ns").asi8
    k = np.searchsorted(k15, (t5 // q) * q)                          # 그 5분봉이 들어 있는 15분봉 번호
    cs = np.concatenate([[0.0], np.cumsum(s15.to_numpy(np.float64))])
    ma, ok = np.zeros(len(t5)), k >= 59
    ma[ok] = (cs[k[ok]] - cs[k[ok] - 59] + s5.to_numpy(np.float64)[ok]) / 60
    return t5 + 5 * 60 * 10 ** 9, ma


def ma_range(m: float, pct: float, band: float) -> tuple[float, float]:
    """60선 단계의 살 범위 — 중심 60선×(1+pct%) 의 ±band%. band 는 % (0.6 = ±0.6%, 데스크 ma_band 와 같다).
    10-22 전엔 band 를 비율로 써서 ±60% 였다 — 60선보다 한참 위에서도 샀다(라온시큐어 10-07 17,380원 · 60선 14,210원)."""
    cen = m * (1 + pct / 100)
    return cen * (1 - band / 100), cen * (1 + band / 100)


def _code_c15(c: str, src: str):
    """15분봉 시작 시각(ns)과 종가 누적합(앞에 0) — '60선 꺾이면 끝'을 데스크처럼(지금가 포함 60선 vs 전 거래일 마지막 60선) 보려고(10-30). 없으면 None."""
    import numpy as np
    from backtesting.value_ledger import _load_minute
    raw = _load_minute(c, "regular" if src == "reg" else "all")[0]
    if raw is None or raw.empty:
        return None
    s15 = raw[[x for x in raw.columns if x.lower() == "close"][0]].resample("15min").last().dropna()
    return s15.index.as_unit("ns").asi8.copy(), np.concatenate([[0.0], np.cumsum(s15.to_numpy(np.float64))])


def load_c15(codes: list[str], src: str) -> dict:
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex:
        return dict(zip(codes, ex.map(lambda c: _per_code("c15-" + src, c, lambda: _code_c15(c, src)), codes)))


def load_ma(codes: list[str], src: str) -> dict:
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex:
        return dict(zip(codes, ex.map(lambda c: _per_code("ma15-" + src, c, lambda: _code_ma15(c, src)), codes)))


def load_bars(codes: list[str], evs: list, session: str, until: str) -> list[tuple]:
    from backtesting.value_ledger import MINUTE_AL_ARCHIVE_DIR, MINUTE_AL_CACHE_DIR, MINUTE_KRX_DIR
    dirs = ((MINUTE_AL_ARCHIVE_DIR, ".parquet"), (MINUTE_AL_CACHE_DIR, ".csv")) if session == "all" else ((MINUTE_KRX_DIR, ".csv"), (MINUTE_KRX_DIR, ".parquet"))
    have = tuple((c, _src_mtime(c)) for c in codes if any(os.path.isfile(os.path.join(d, c + x)) for d, x in dirs))   # 분봉 파일이 생기거나 바뀌면 캐시 키가 바뀐다(10-30)
    key = (tuple(codes), tuple(e[:2] for e in evs), session, until, have)
    if key not in _BARS:
        _BARS.clear()
        _BARS[key] = _disk("bars" + repr(key), lambda: _load_bars(codes, evs, session, until))
    return _BARS[key]


def _load_bars(codes: list[str], evs: list, session: str, until: str) -> list[tuple]:
    import numpy as np
    bars, TS = [], {}                                # TS: 같은 시각은 같은 Timestamp 하나(수백 종목이 공유)
    win: dict = {}
    for rd, cc, *_ in evs:
        win.setdefault(cc, []).append(rd)
    hi_all = pd.Timestamp(until + " 23:59").value
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex:                # 파일 읽기(pyarrow)는 GIL 을 놓아 여러 종목을 함께 읽는 게 빠르다(10-20)
        arrs = list(ex.map(lambda c: _per_code("bars-" + session, c, lambda: _code_bars(c, session)), codes))
    for i, (c, arr) in enumerate(zip(codes, arrs)):
        if arr is None:
            continue
        t, o, h, l, cl = arr
        keep = np.zeros(len(t), dtype=bool)
        for rd in win.get(c, []):                    # 신고 다음 날부터 60일(달력)만 — 메모리 절약
            b = min((pd.Timestamp(rd) + pd.Timedelta(days=60)).value, hi_all + 1)
            keep |= (t > pd.Timestamp(rd).value) & (t < b)    # 예전과 같은 범위(rd 자정 초과 ~ 60일 미만, until 23:59 까지)
        idx = np.flatnonzero(keep)
        for j in idx.tolist():
            tv = int(t[j])
            ts = TS.get(tv)
            if ts is None:
                ts = TS[tv] = pd.Timestamp(tv)
            bars.append((ts, c, int(o[j]), int(h[j]), int(l[j]), int(cl[j])))
        if i % 20 == 0:
            _status(stage="데이터 읽기", pct=round(5 + 45 * i / max(1, len(codes))))
    bars.sort()
    return bars


# 매수 조건(rule.conds) — 데스크와 같은 판단(engine.conds_met)에 그날까지 알 수 있던 값만 넣는다.
# 일봉 사실(52주 고가·직전 종가)은 그날 '전'까지, 장중 값(현재가·당일 고가)은 그 봉까지. 거래대금·체결강도·테마·장대양봉은 아직 백테스트에 못 넣는다
BT_CONDS = {"52주 신고가 대비", "시장", "시가총액", "정규장 종가 대비", "애프터 종가 대비", "고점 대비 하락률(첫 도달)", "등락률", "60선 차이(애프터−정규장)"}


class DailyFacts:
    def __init__(self) -> None:
        from bisect import bisect_left
        self._bl = bisect_left
        self.al, self.reg = {}, {}
        try:
            self.market = json.loads((ROOT / "data" / "cache" / "rs_market.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.market = {}
        try:
            self.shares = json.loads((ROOT / "data" / "cache" / "rs_shares.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.shares = {}

    def preload(self, codes) -> None:
        """여러 종목 일봉을 한 번에(하루 디스크 캐시) — 정규장 일봉은 1분봉 파일에서 만들어 종목당 수백 ms 걸린다."""
        need = [c for c in codes if c not in self.al]
        if not need:
            return
        def make(c):
            self._rows(c)
            return self.al[c], self.reg[c]
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(8) as ex:
            got = list(ex.map(lambda c: _per_code("facts", c, lambda: make(c)), need))
        for c, (a, r) in zip(need, got):
            self.al[c], self.reg[c] = a, r

    def _rows(self, code: str):
        if code not in self.al:
            from backtesting.value_ledger import daily_al_rows, regular_daily_rows
            a, r = daily_al_rows(code) or [], regular_daily_rows(code) or []
            self.al[code] = ([x[0] for x in a], [x[2] for x in a], [x[4] for x in a])
            self.reg[code] = ([x[0] for x in r], [x[4] for x in r], [x[2] for x in r])
        return self.al[code], self.reg[code]

    def close_on(self, code: str, d: str, base: str):
        (ad, ah, ac), (rd, rc, rh) = self._rows(code)
        dd, cc = (rd, rc) if base == "reg" else (ad, ac)
        i = self._bl(dd, d)
        return cc[i] if i < len(dd) and dd[i] == d else None

    def high_on(self, code: str, d: str, base: str):
        (ad, ah, ac), (rd, rc, rh) = self._rows(code)
        dd, hh = (rd, rh) if base == "reg" else (ad, ah)
        i = self._bl(dd, d)
        return hh[i] if i < len(dd) and dd[i] == d else None

    def snap(self, code: str, d: str, px: int, day_high: int) -> dict:
        (ad, ah, ac), (rd, rc, _rh) = self._rows(code)
        i, j = self._bl(ad, d), self._bl(rd, d)                  # 그날 '전'까지
        hi52 = max(ah[max(0, i - 250):i]) if i else None
        reg, aft = (rc[j - 1] if j else None), (ac[i - 1] if i else None)
        return {"px": px, "high": day_high, "reg": reg, "aft": aft, "chg": (px / reg - 1) * 100 if reg else None,
                "facts": {"hi52": hi52, "market": self.market.get(code), "shares": self.shares.get(code)}}


_DF: list = []


def _daily_facts() -> DailyFacts:
    if not _DF:
        _DF.append(DailyFacts())
    return _DF[0]


def manual_ref_entries() -> list:
    """종목에 손으로 정한 기준일(데스크 ref_days.json, 매매 화면 '기준일') — 데스크도 이게 규칙보다 먼저다. 일지 모양으로."""
    p = STATE / "ref_days.json"
    M = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    J = json.loads((STATE / "journal.json").read_text(encoding="utf-8")) if (STATE / "journal.json").exists() else []
    names = {j["code"]: j.get("name") for j in J}
    return [{"code": c, "name": names.get(c) or c, "ref_days": [d]} for c, d in M.items() if d and d != "prev"]


def journal_events(start: str, end: str, base: str, missing: list | None = None, entries: list | None = None) -> list[tuple[str, str, str, int]]:
    """선정 일지에 직접 고른 종목만 — (기준일, 코드, 이름, 기준일 종가), 일지에 남은 기준일마다. 종가는 장부 줄이 있으면 그 값, 없으면 정규장 일봉.
    missing 을 주면 기준일·종가가 없어 빠진 종목 이름을 넣는다(화면에 보인다)."""
    from backtesting.value_ledger import daily_al_rows, regular_daily_rows
    J = entries if entries is not None else json.loads((STATE / "journal.json").read_text(encoding="utf-8")) if (STATE / "journal.json").exists() else []
    rows = {(x[0], x[1]): x for x in json.loads((ROOT / "static" / "dashboard" / "value_ledger.json").read_text(encoding="utf-8"))["rows"]}
    out = []
    for j in J:
        name = j.get("name") or j["code"]
        rds = j.get("ref_days") or ([j["ref_day"]] if j.get("ref_day") else [])
        if not rds and missing is not None:
            missing.append(f"{name}(기준일 없음)")
        for rd in rds:
            iso = f"{rd[:4]}-{rd[4:6]}-{rd[6:]}"
            if not (start <= iso <= end):
                continue
            x = rows.get((iso, j["code"]))
            px = (x[21] if base == "reg" else x[8]) if x else None
            if not px:
                r = next((r for r in ((regular_daily_rows(j["code"]) if base == "reg" else daily_al_rows(j["code"])) or []) if r[0] == rd), None)
                px = r[4] if r else None
            if px:
                out.append((iso, j["code"], name, int(px)))
            elif missing is not None:
                missing.append(f"{name}({rd[4:6]}.{rd[6:]} 종가 없음)")
    return sorted(set(out))


def journal_codes() -> set:
    """선정 일지에 고른 종목 — 백테스트 기간 전체의 신고대금 날을 대입한다(고른 날과 무관, 10-22 사용자 "8·9·10월 각각 신고가 있어").
    목록에서 뺀 종목(dropped)은 뺀다 — 10-22 사용자 "삭제했는데 과거 종목까지 백테스트". 산 적 있는 종목은 남는다(뺌 표시가 안 붙는다)."""
    J = json.loads((STATE / "journal.json").read_text(encoding="utf-8")) if (STATE / "journal.json").exists() else []
    return {j["code"] for j in J if not j.get("dropped")}


def _kosdaq_change() -> tuple[dict, dict]:
    """코스닥 지수 5분 종가(시각 → 값)와 전날 종가(날짜 → 값) — data/index/minute/101.csv(2025-07~)."""
    p = ROOT / "data" / "index" / "minute" / "101.csv"
    if not p.exists():
        return {}, {}
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    df = df[(df.index.time >= pd.Timestamp("09:00").time()) & (df.index.time <= pd.Timestamp("15:30").time())]
    c5 = df["close"].resample("5min").last().dropna()
    day_close = df["close"].groupby(df.index.normalize()).last()
    prev = {d.strftime("%Y%m%d"): v for d, v in zip(day_close.index[1:], day_close.to_numpy()[:-1])}
    return {t: v for t, v in zip(c5.index, c5.to_numpy())}, prev


def simulate(rule: dict, exits: dict, safety: dict, capital: float, start: str, end: str, min_chg: float, session: str,
             universe: str = "ledger", fexits: dict | None = None):
    L = rule["ladder"]
    # 단계 [pct, 금액%, {옵션}] — 60선 단계는 15분봉 60선 × (1+pct%) ±근접% 안에 들어오면 산다 · from/to 시각 안에서만(데스크와 같다)
    levels = [(engine._num(lv[0]), (engine._num(lv[1], 0) or 0) / 100, engine.level_opts(lv)) for lv in L["levels"] if engine._num(lv[0]) is not None]
    keep = L.get("keep") or {"mode": "today"}
    keep_n = {"today": 1, "days": int(engine._num(keep.get("days"), 1) or 1)}.get(keep.get("mode"), 60)
    guard = L.get("guard") or {}
    g_until, g_pct = (guard.get("until") or "09:30").replace(":", "")[:4], abs(engine._num(guard.get("pct"), 5) or 5)
    max_pos = int(engine._num(safety.get("max_positions"), 0) or 0)
    # 미수·신용: 종목별 증거금률·신용 가능은 과거 값을 몰라 설정 배수를 그대로 쓴다. 미수는 산 날 15:15 정리, 신용은 빌린 몫에 연 이자(하루 이상)
    lev, how = engine.leverage(safety)
    rate = (engine._num(safety.get("credit_rate"), 9.5) or 0) / 100 if how == "credit" else 0.0
    if how == "margin" and safety.get("margin_intraday", True):
        exits = {**exits, "close": [True, "15:15"]}
        fexits = fexits and {**fexits, "close": [True, "15:15"]}
    conds = [c for c in (rule.get("conds") or []) if c and c[0] and str(c[2]).strip() != ""]
    use_conds = [c for c in conds if c[0] in BT_CONDS]
    times = [(a.replace(":", ""), b.replace(":", "")) for a, b in (rule.get("times") or [])]
    follow = (L.get("follow_high") or {}).get("on")
    follow_once = follow and (L.get("follow_high") or {}).get("once")       # 판 뒤엔 다시 안 따라감(10-20 사용자)
    follow_run = follow and (L.get("follow_high") or {}).get("def") == "run"   # 고점 = 기준일 뒤 최고가 돌파(예전 정의)
    follow_keep = follow and (L.get("follow_high") or {}).get("keep_today")   # 오늘 고점 갱신 중에도 예약 유지(예전)
    pk = (L.get("peak_stop") or {}).get("on")                     # 종목마다 % 는 시총으로(engine.peak_pct)
    rest_close = (L.get("rest_close") or {}).get("on")          # 한 단계를 산 날, 못 산 나머지 60선 단계는 15:15 봉 시가에(10-21 사용자)
    pk_close = (L.get("peak_stop") or {}).get("by") == "close"     # 기준일 종가 대비(10-21 사용자 "종가 대비 24%") / 기본 고가 대비
    pk_base = (L.get("peak_stop") or {}).get("base") or L.get("base", "reg")   # 재매수 금지 선의 봉 — 매수 기준과 따로(10-22 사용자 "정규장 종가로")
    pk_first = pk and (L.get("peak_stop") or {}).get("first")      # 연달아 나온 신고대금의 첫 날 기준(engine.peak_anchor)
    ledger_days: dict = {}
    if pk_first:
        for x in json.loads((ROOT / "static" / "dashboard" / "value_ledger.json").read_text(encoding="utf-8"))["rows"]:
            if (L.get("peak_stop") or {}).get("first_reg_only") and x[17] is None:
                continue                                           # 통합으로만 신고대금인 날은 잇지 않는다(정규장 몫은 못 넘음)
            ledger_days.setdefault(x[1], []).append((x[0], x[20] if x[20] is not None else x[7]))   # 데스크 ledger_day 와 같은 상승률
    facts = _daily_facts() if (use_conds or follow or pk) else None
    min_chg = max(min_chg, engine._num(L.get("ref_min_chg"), 0) or 0)   # 규칙의 '신고일 상승률 ≥' 가 더 높으면 그걸로
    evs = events(start, end, min_chg, L.get("base", "reg"), session, bool(L.get("ref_reg_only")))
    scope = None
    if universe == "journal":
        # 선정 일지 = 고른 종목만. 기준일 = 일지에 남은 날 + 지금 규칙 기준(정규장/애프터·상승률)으로 장부에서 본 그 기간 신고일 전부.
        # 일지엔 그때 규칙 기준의 날만 남아 있어 규칙을 바꾸면 빠진다(10-22 사용자: 애프터로 바꿨는데 HT로보틱스 10-14 통합 신고대금 → 10-15 안 삼).
        # 고른 날 앞 며칠로 자르면 오늘 고른 종목(한국콜마 08-12·JW신약 09-08·심텍 09-22)이 다 빠진다(10-22 사용자) — 기간 전체를 본다
        # 일지에 남은 기준일은 데스크가 자동으로 채운 날(그날 규칙 조건 없이 장부 최근 신고일)이라 쓰지 않는다 — 규칙 조건(정규장·상승률)을 안 거쳐
        # 금호전기 10-13(+3.9%)이 12% 규칙에 들어갔다(10-22 사용자). 손으로 정한 기준일(ref_days.json)만 조건 없이 먼저
        scope = journal_codes()
        evs = sorted({e[:2]: e for e in journal_events(start, end, L.get("base", "reg"), entries=[m for m in manual_ref_entries() if m["code"] in scope])
                      + [e for e in evs if e[1] in scope]}.values())
    # 신고대금 당일부터(10-21 사용자): 장중에 신고대금이 된(그때 등락률 ≥ 문턱) 날은 그 시각부터 그날 산다 — 그날 마감 등락률이 문턱 아래여도
    # 데스크는 장중에 산다. 장중에 못 잡힌 신고일은 예전처럼 다음 거래일부터
    xt: dict = {}
    if L.get("ref_today") and (L.get("ref_mode") or "ledger") == "ledger":
        ev_all = events(start, end, -1e9, L.get("base", "reg"), session)
        if scope is not None:
            ev_all = [e for e in ev_all if e[1] in scope]
        xt = same_day_cross(ev_all, min_chg, bool(L.get("ref_reg_only")))
        evs = sorted({e[:2]: e for e in evs + [e for e in ev_all if e[:2] in xt]}.values())
    # 새 매수 멈춤(데스크 안전장치와 같다): 코스닥이 그 시각 전날 종가 대비 −mkt_drop% 이하 · 그날 손절 max_stops 번
    md, ms = engine._num(safety.get("mkt_drop"), None), int(engine._num(safety.get("max_stops"), 0) or 0)
    kq, kq_prev = _kosdaq_change() if md else ({}, {})
    stops_day: dict = {}
    codes = sorted({e[1] for e in evs})
    _status(stage="데이터 읽기", pct=5, n_events=len(evs), n_codes=len(codes))
    bars = load_bars(codes, evs, session, end)
    # 15분봉 60선(매수 60선 단계 · 60선 엔벨로프 손절) — 매수는 규칙의 기준(정규장/애프터), 손절은 청산 규칙에 고른 봉
    ma_buy = L.get("base", "reg") if any(o["band"] is not None for *_, o in levels) else None
    mt_src = L.get("base", "reg") if (L.get("ma_turn") or {}).get("on") else None   # 60선 꺾이면 끝(10-21 사용자)
    mt_pause = (L.get("ma_turn") or {}).get("mode") == "pause"     # 꺾인 동안만 멈춤(10-30)
    magap_on = any(c[0] == "60선 차이(애프터−정규장)" for c in use_conds)
    ma_srcs = ({"reg", "aft"} if magap_on else set()) | {ma_buy, mt_src} | {o["src"] for *_, o in levels if o["band"] is not None and o["src"]} | {(x.get("ma_env") + [None, None])[2] or "reg" for x in (exits, fexits) if x and (x.get("ma_env") or [False])[0]}
    MA = {src: load_ma(codes, src) for src in ma_srcs if src}
    C15 = load_c15(codes, mt_src) if mt_src else {}

    def ma_at(c, src, ts):
        """그 봉이 시작될 때 알 수 있던 60선(끝난 5분봉까지) — 없으면 0."""
        a = MA.get(src, {}).get(c)
        if not a:
            return 0
        i = int(a[0].searchsorted(ts.value, "right")) - 1
        return float(a[1][i]) if i >= 0 else 0

    def ma_live(c, ts, px):
        """그 봉 시작 때 데스크가 보는 60선 — 앞 15분봉 59개 종가 + 지금가(px)(만드는 중인 봉도 지금가로, 데스크 ma60_15 와 같다). 없으면 0."""
        a = C15.get(c)
        if not a:
            return 0
        k = int(a[0].searchsorted((ts.value // (15 * 60 * 10 ** 9)) * (15 * 60 * 10 ** 9), "left"))
        return (a[1][k] - a[1][k - 59] + px) / 60 if k >= 59 else 0

    def ma_prevday(c, ts):
        """전 거래일 마지막 60선 — 오늘 전 마지막 15분봉 60개 평균(데스크 ma60_15_prev 와 같다). 없으면 0."""
        a = C15.get(c)
        if not a:
            return 0
        k = int(a[0].searchsorted(ts.normalize().value, "left"))
        return (a[1][k] - a[1][k - 60]) / 60 if k >= 60 else 0
    if facts:
        facts.preload(codes)
    starts: dict[str, list] = {}
    for e in evs:
        starts.setdefault(e[0].replace("-", "") if e[:2] in xt else _next_days(e[0], 1)[0], []).append(e)

    cash, P, trades, eq_rows, day0, eid = float(capital), {}, [], [], None, 0
    last_px: dict[str, int] = {}
    skipped = {"guard": 0, "slots_full": 0, "cash": 0}

    held: set = set()                                              # 지금 보유한 종목(봉마다 P 전체를 세지 않게)

    def equity() -> float:
        return cash + sum(P[c]["qty"] * last_px.get(c, P[c]["avg"]) for c in held)

    def sell(c, p, q, px, kind, ts):
        nonlocal cash
        gross = (px - p["avg"]) * q
        com, tax = (p["avg"] + px) * q * FEE, px * q * TAX
        if rate:                                                   # 신용 이자 — 빌린 몫(1 − 1/배수) × 연 이자 × 보유 일수(최소 1일)
            days = max(1, (pd.Timestamp(ts).normalize() - pd.Timestamp(p["t0"]).normalize()).days)
            com += p["avg"] * q * (1 - 1 / lev) * rate * days / 365
        cash += px * q - px * q * FEE - tax - (com - (p["avg"] + px) * q * FEE)
        p["slice"] += 1
        trades.append({"code": c, "name": p["name"], "entry_ts": p["t0"], "entry_price": round(p["avg"], 2), "exit_ts": ts, "exit_price": px,
                       "qty": q, "gross_pnl": gross, "commission": com, "tax": tax, "slippage_cost": 0.0, "net_pnl": gross - com - tax,
                       "net_pct": (gross - com - tax) / (p["avg"] * q) * 100, "exit_reason": REASON[kind], "bars_held": p["bars"],
                       "mfe_pct": (p["high"] / p["avg"] - 1) * 100, "mae_pct": (p["low"] / p["avg"] - 1) * 100,
                       "entry_id": p["eid"], "slice": p["slice"], "follow": bool(p.get("fbuy")), "buys": json.dumps(p.get("fills") or [])})
        p["qty"] -= q
        if p["qty"] <= 0:
            held.discard(c)

    n_bars = len(bars)
    tstr: dict = {}                                                # 봉 시각 → (날짜, 시분) — 같은 시각을 수백 종목이 공유한다(10-20 최적화)
    gap_on = (L.get("gap") or {}).get("on")
    rebuy_n = int(engine._num((L.get("rebuy") or {}).get("n"), 1) or 1) if (L.get("rebuy") or {}).get("on") else 0   # 손절 뒤 다시 사기(10-21)
    ms_pct = abs(engine._num((L.get("ma_stop") or {}).get("pct"), 6) or 6) / 100 if (L.get("ma_stop") or {}).get("on") and ma_buy else None
    cn_full = (L.get("c_near") or {}).get("full")
    cf_n = max(1, int(engine._num((L.get("ma_confirm") or {}).get("n"), 3) or 3)) if (L.get("ma_confirm") or {}).get("on") and ma_buy else 0   # 60선 위에서 N개 버팀(10-30)
    _hp = engine._num((L.get("ma_confirm") or {}).get("hold"), 2)
    cf_hold = 1 + abs(2 if _hp is None else _hp) / 100
    cn_pct = abs(engine._num((L.get("c_near") or {}).get("pct"), 3) if engine._num((L.get("c_near") or {}).get("pct"), 3) is not None else 3) / 100 if (L.get("c_near") or {}).get("on") and ma_buy else None   # C −N% 위에서만 60선 매수(10-30)
    for k, (ts, c, o, h, l, cl) in enumerate(bars):
        dh = tstr.get(ts)
        if dh is None:
            dh = tstr[ts] = (ts.strftime("%Y%m%d"), ts.strftime("%H%M"))
        d, hm = dh
        if d != day0:
            if day0:
                eq_rows.append({"ts": pd.Timestamp(day0), "cash": cash, "positions_value": equity() - cash, "equity": equity(),
                                "n_positions": len(held)})
            day0 = d
            for rd, cc, name, bp in starts.get(d, []):
                p = P.get(cc)
                if p and p["qty"] > 0:
                    continue                                       # 보유 중이면 새 신고일은 건너뛴다
                nd, x0 = _next_days(rd, keep_n), xt.get((rd, cc))
                live = set(nd) | ({d} if x0 else set())            # 당일 예약은 신고일 그날도
                if not p:
                    last_px[cc] = bp                               # 첫날 '전날 종가' = 기준일 종가(예전엔 그 종목 마지막 봉)
                if x0:
                    skipped["same_day"] = skipped.get("same_day", 0) + 1
                P[cc] = {"name": name, "rd": rd, "bp": bp, "c0": bp, "live": live, "d1": min(nd), "lmax": max(nd), "qty": 0, "avg": 0.0, "init": 0, "cost": 0.0,
                         "xt": x0, "xd": d if x0 else None, "hi_since": 0,
                         "rdh": ((facts.close_on(cc, rd.replace("-", ""), pk_base) or bp) if pk_close else facts.high_on(cc, rd.replace("-", ""), pk_base)) if pk else None,
                         "pk_ref": engine.peak_anchor(ledger_days.get(cc, []), rd, int(engine._num((L.get("peak_stop") or {}).get("first_days"), 21) or 21),
                                                      engine._num((L.get("peak_stop") or {}).get("first_min_chg"), None)) if pk_first else None,
                         "pk": engine.peak_pct(L.get("peak_stop"), facts.shares.get(cc) * bp / 1e8 if pk and facts.shares.get(cc) else None) / 100 if pk else None,
                         "stages": [{"pct": pct, "price": engine.floor_tick(bp * (1 + pct / 100)), "w": w, "done": False, "band": o["band"], "t0": o["t0"], "t1": o["t1"],
                                     "src": o["src"] or L.get("base", "reg")}
                                    for pct, w, o in levels],
                         "low_early": 10 ** 12, "guard": None, "takes_done": [], "be": False, "high": 0, "low": 10 ** 12,
                         "slice": 0, "bars": 0, "closed": False, "eid": -1, "t0": None, "ok": not use_conds, "dhigh": 0,
                         "runmax": (facts.high_on(cc, rd.replace("-", ""), L.get("base", "reg")) if follow else None) or 10 ** 12}
            if k % 2000 == 0:
                _status(stage="계산", pct=round(50 + 45 * k / max(1, n_bars)))
        p = P.get(c)
        if not p:
            continue                                               # 예약 없는 종목 봉은 바로 건너뛴다(직전 종가는 예약이 있는 동안만 쓴다)
        prev_cl = last_px.get(c)
        last_px[c] = cl
        if p["qty"] <= 0 and d > p["lmax"]:
            P.pop(c)                                               # 유지 기간이 끝난 빈 예약 — 고점이 나도 더는 안 옮긴다(데스크 '기간 끝')
            continue
        if p.get("day") != d:
            if follow and p.get("day") and not p["closed"] and d <= p["lmax"] and p["dhigh"] > p["runmax"]:   # 산 뒤에도 따라간다(10-20)
                # 고점 따라가기: 어제 고가가 그 전날 고가를 넘었으면 기준가 = 어제 종가, 유지 기간도 어제부터 다시
                p["bp"] = prev_cl
                for s in p["stages"]:
                    s["price"], s["done"] = engine.floor_tick(prev_cl * (1 + s["pct"] / 100)), False
                p["ma_dead"] = False                               # 새 기준 — 60선 매수 멈춤도 풀린다
                p["live"] = set(_next_days(f"{p['day'][:4]}-{p['day'][4:6]}-{p['day'][6:]}", keep_n))
                p["lmax"] = max(p["live"])
                skipped["follow"] = skipped.get("follow", 0) + 1
                p["moved"] = True
            if follow and p.get("day"):
                p["runmax"] = max(p["runmax"], p["dhigh"]) if follow_run else p["dhigh"]   # 전날 고가 돌파(기본) / 기준일 뒤 최고가 돌파(예전)
            p["day"], p["day_open"], p["dhigh"] = d, o, 0          # 이 종목의 그날 첫 봉 시가
            p["gap"] = bool(gap_on) and d != p["xd"] and o < min((x["price"] for x in p["stages"] if x["band"] is None), default=0)   # 60선 단계는 갭 판단에서 뺀다 · 신고일 당일은 안 본다
            dr = L.get("drop") or {}
            if dr.get("on") and not p["closed"] and p["init"] == 0 and prev_cl and prev_cl <= p["bp"] * (1 - abs(engine._num(dr.get("pct"), 5) or 5) / 100):
                p["closed"] = True                                 # A: 전날 종가가 기준가 −pct% 이하면 남은 예약 버림
                skipped["drop"] = skipped.get("drop", 0) + 1
        # ── 매수
        if guard.get("on") and d == p["d1"] and p["qty"] == 0 and p["guard"] is None:
            if hm < g_until:
                p["low_early"] = min(p["low_early"], l)
                continue
            p["guard"] = p["low_early"] <= p["bp"] * (1 - g_pct / 100)
            if p["guard"]:
                p["closed"] = True
                skipped["guard"] += 1
        if mt_src and not p["closed"] and d != p["rd"].replace("-", ""):
            m, m0 = ma_live(c, ts, o), ma_prevday(c, ts)       # 지금 60선(이 봉 시가 포함) vs 전날 마지막 60선(10-30)
            if mt_pause:
                p["mt_down"] = bool(m and m0 and m < m0)           # 꺾인 동안만 안 삼(데스크와 같다)
            elif m and m0 and m < m0:
                p["closed"] = True                                 # 60선 꺾임 — 재매수 금지(데스크와 같다)
                skipped["ma_turn"] = skipped.get("ma_turn", 0) + 1
        if p.get("pk_ref") and p["pk_ref"] != p["rd"] and not p.get("pk_set"):
            # 첫 신고대금 날 기준 — 선은 그날 고가(또는 종가), 지금까지 최고는 그 다음 날부터 기준일까지의 고가
            p["pk_set"] = True
            (ad, ah, ac), (rd_, rc_, rh_) = facts._rows(c)
            dd_, hh_, cc_ = (rd_, rh_, rc_) if pk_base == "reg" else (ad, ah, ac)
            a, r_ = p["pk_ref"].replace("-", ""), p["rd"].replace("-", "")
            ia = facts._bl(dd_, a)
            if ia < len(dd_) and dd_[ia] == a:
                p["rdh"] = cc_[ia] if pk_close else hh_[ia]
                p["hi_since"] = max([hh_[i] for i in range(ia + 1, len(dd_)) if (dd_[i] < r_ if p["xd"] else dd_[i] <= r_)] + [p["hi_since"]])
        early = bool(p.get("pk_ref") and p["pk_ref"] != p["rd"])   # 첫 신고대금이 더 앞 — 당일 예약도 선을 안다(데스크와 같다, 10-22)
        if pk and p["rdh"] and (d != p["xd"] or early) and not p["closed"] and p["hi_since"] >= p["rdh"] * (1 + p["pk"]):
            p["closed"] = True                                     # 기준일 고가 +N% 를 넘은 적 있음 — 재매수 금지(데스크와 같다)
            skipped["peak_stop"] = skipped.get("peak_stop", 0) + 1
        if d != p["rd"].replace("-", "") or early:
            p["hi_since"] = max(p["hi_since"], h)                  # 기준일 다음 날부터의 최고가 — 이 봉 고가는 다음 봉 판단부터(데스크는 장중 고가로 바로)
        p["dhigh"] = max(p["dhigh"], h)
        if cf_n:
            bk = (d, int(hm[:2]) * 4 + int(hm[2:]) // 15)          # 15분봉
            if p.get("cb") is not None and bk != p["cb"]:
                for s_ in p["stages"]:                             # 방금 끝난 15분봉 — 60선 위 0~hold% 마감이면 하나 셈(데스크와 같다)
                    if s_["band"] is None or s_["done"]:
                        continue
                    m_ = ma_at(c, s_["src"], ts)
                    if not m_ or p["cc"] <= m_:
                        s_["cnt"], s_["go"] = 0, None              # 60선 아래 마감 — 걸린 주문 거두고 처음부터
                    elif p["cc"] <= m_ * cf_hold:
                        s_["cnt"] = s_.get("cnt", 0) + 1
                        if s_["cnt"] >= cf_n:
                            s_["go"] = p["cc"]                     # 그 봉 종가에 지정가(더 버티면 새 종가로)
                    else:
                        s_["cnt"] = 0                              # 60선에서 멀어짐 — 걸린 주문은 그대로
            p["cb"], p["cc"] = bk, cl
        if not p["ok"]:
            # 데스크는 주문 가능 시간 안에서 조건이 맞는 순간 예약을 만든다 — 맞은 다음 봉부터 산다
            if d in p["live"] and not p["closed"] and (not times or any(a <= hm <= b for a, b in times)):
                sn = facts.snap(c, d, cl, p["dhigh"])
                if magap_on:
                    ma_a, ma_r = ma_at(c, "aft", ts), ma_at(c, "reg", ts)
                    sn["ma_gap"] = (ma_a / ma_r - 1) * 100 if ma_a and ma_r else None
                if engine.conds_met(use_conds, sn)[0]:
                    p["ok"] = True
            continue
        gap_skip = p["gap"]
        halt = (ms and stops_day.get(d, 0) >= ms) or (md and kq_prev.get(d) and (kq.get(ts) or kq_prev[d]) / kq_prev[d] - 1 <= -abs(md) / 100)
        if halt:
            skipped["halt"] = skipped.get("halt", 0) + 1
        new_today = follow and not follow_keep and p.get("day") and p["dhigh"] > p["runmax"]  # 오늘 전날 고가를 넘었으면 옛 기준 예약은 취소(데스크와 같다)
        if ms_pct and not p.get("ma_dead") and d in p["live"] and any(s["band"] is not None and not s["done"] for s in p["stages"]):
            m = ma_at(c, ma_buy, ts)
            if m and l < m * (1 - ms_pct):                         # 60선 엔벨로프 하단을 깼다 — 이 예약의 60선 단계는 그만(데스크와 같다)
                p["ma_dead"] = True
                skipped["ma_stop"] = skipped.get("ma_stop", 0) + 1
        in_win = not times or any(a <= hm <= b for a, b in times)   # 매수 규칙 주문 가능 시간 — 조건 없는 규칙도(데스크 _plan_window 와 같다, 10-22 "9시 30분부터")
        if d in p["live"] and ("0800" <= hm <= "1530" or "1540" <= hm < "2000") and in_win and not p["closed"] and not p.get("mt_down") and not gap_skip and not halt and not new_today and p.get("rb_day") != d:
            order = list(p["stages"])                              # 놓친 단계가 뒤에 덧붙는다(아래 catch)
            while order:
                s = order.pop(0)
                full = False                                       # C 이상이면 남은 단계를 합쳐 한 번에(10-30)
                if s["done"] or (s["t0"] and hm < s["t0"]) or (s["t1"] and hm >= s["t1"]) or (s["band"] is not None and p.get("ma_dead")):
                    continue
                if d == p["xd"] and (s["band"] is None or ts.value < p["xt"]):
                    continue                                       # 신고대금 당일: 신고대금이 된 뒤 봉부터, 60선 단계만(종가 % 는 그날 종가가 나와야 정해진다)
                if s.get("catch") is not None:
                    lim = px = s.pop("catch")                      # 놓친 단계 — 다른 단계가 산 가격에 같이(10-22 사용자 "다음 매수 자리에 같이")
                elif rest_close and s["band"] is not None and p.get("fd") == d and hm >= "1515":
                    lim = px = o                                   # 나머지 반 마감 매수(10-21 사용자 "못 산 반은 종가에") — 다른 단계를 오늘 샀고 이 단계는 15:15까지 못 샀다
                elif s["band"] is not None:
                    # 60선 단계: 봉이 60선×(1+pct%) ±band% 범위에 닿으면 산다. 시가가 범위 안이면 시가, 위에서 내려오면 위쪽 끝(지정가), 아래서 오르면 아래쪽 끝
                    m = ma_at(c, s["src"], ts)
                    if not m:
                        if s.get("mn") != d:                       # 60선을 못 구한 날(분봉이 없거나 앞 15분봉 59개가 안 됨) — 종목·날짜 단위로 센다
                            s["mn"] = d
                            skipped["ma_none"] = skipped.get("ma_none", 0) + 1
                        continue
                    lo, hi = ma_range(m, s["pct"], s["band"])
                    if cf_n:
                        if not s.get("go") or l > s["go"]:
                            continue                               # 버팀 확인 전이거나 그 종가까지 안 내려옴
                        lim = engine.floor_tick(s["go"]); px = min(o, lim)
                    elif l > hi or h < lo:
                        continue
                    else:
                        lim = engine.floor_tick(hi)
                    if cn_pct is not None and d != p["xd"] and lim < p["c0"] * (1 - cn_pct):
                        if s.get("cn") != d:                       # 사는 값이 기준일 종가 C −N% 아래 — 안 삼(데스크와 같다, 당일 예약은 C 를 몰라 안 막음)
                            s["cn"] = d
                            skipped["c_near"] = skipped.get("c_near", 0) + 1
                        continue
                    full = bool(cn_full and cn_pct is not None and d != p["xd"] and lim >= p["c0"] * (1 - cn_pct))
                    if not cf_n:
                        px = o if lo <= o <= hi else lim if o > hi else engine.ceil_tick(lo)
                elif l > s["price"]:
                    continue
                else:
                    lim, px = s["price"], min(s["price"], o)
                if p["qty"] == 0 and max_pos and len(held) >= max_pos:
                    skipped["slots_full"] += 1
                    break                                          # 자리가 나면 다시
                one = engine.per_stock_amount(rule.get("amount"), safety, equity(), lev)
                power = cash + (lev - 1) * equity()                    # 미수·신용으로 더 살 수 있는 돈(빌린 돈은 cash 가 음수로 남는다)
                oth = [x for x in p["stages"] if x is not s and not x["done"]] if full else []
                q = min(int(one * (s["w"] + sum(x["w"] for x in oth)) // lim), int(power // (px * (1 + FEE))))
                s["done"] = True
                for x in oth:
                    x["done"] = True                               # 합쳐서 같이 샀다(데스크와 같다)
                if q <= 0:
                    skipped["cash"] += 1
                    continue
                cash -= px * q * (1 + FEE)
                if p.get("moved"):
                    p["fbuy"] = True                               # 고점 따라가기로 산 것(분석용 표시)
                if p.get("moved") and fexits:                      # 데스크: 옮긴 뒤 산 게 체결되면 그 종목 전체를 고점 따라가기 청산으로
                    if p["qty"] > 0 and p.get("ex") is not fexits:
                        p["takes_done"] = []                       # 추가 매수 — 익절 단계를 새 수량으로(데스크 _sync_meta)
                    p["ex"] = fexits
                if p["qty"] == 0 and p["init"] == 0:
                    eid += 1
                    p["eid"], p["t0"], p["fills"] = eid, ts, []
                mv = ma_at(c, s["src"], ts) if s["band"] is not None else None
                p["fills"].append([str(ts), round(px, 2), q, p["stages"].index(s) + 1, round(mv) if mv else None, s["src"] if mv else None])   # 단계별 매수 + 그때 60선·봉 — 스튜디오 차트 타점(10-22 사용자)
                p["kbuy"] = k                                      # 산 봉 — 그 봉 고가로는 익절 안 함(봉 안에서 저가·고가 순서를 모른다)
                p["fd"] = d                                        # 이 예약에서 산 날(나머지 반 마감 매수용)
                p["cost"] += px * q
                p["qty"] += q
                held.add(c)
                p["init"] += q
                p["avg"] = p["cost"] / p["init"]
                p["high"] = max(p["high"], px)
                p["low"] = min(p["low"], px)
                for j in p["stages"]:
                    # 놓친 60선 단계 — 가격이 이미 그 범위 아래로 지나갔으면(시각 밖이었거나 건너뛰었거나) 이번에 산 값에 같이 산다
                    # (10-22 사용자: 라온시큐어 10-08 1차는 09:30 전에 지나가 2차만 사짐 → 2차 때 1차 몫도)
                    if j is not s and not j["done"] and j["band"] is not None and j.get("catch") is None and j not in order:
                        mj = ma_at(c, j["src"], ts)
                        if mj and px < ma_range(mj, j["pct"], j["band"])[0]:
                            j["catch"] = px
                            order.append(j)
        if p["qty"] <= 0:
            continue
        # ── 청산 — 데스크와 같은 판단(손절·되밀림·시각·기간을 봉 저가로 먼저, 익절은 봉 고가로)
        p["bars"] += 1
        ex = p.get("ex") or exits
        pos = {"qty": p["qty"], "avg": p["avg"], "init_qty": p["init"], "high": p["high"], "opened": pd.Timestamp(p["t0"]).date().isoformat(),
               "takes_done": p["takes_done"], "breakeven": p["be"]}
        if (ex.get("ma_env") or [False])[0]:
            pos["ma60"] = ma_at(c, (ex["ma_env"] + [None, None])[2] or "reg", ts)
        acts = engine.exit_actions(pos, l, ts.to_pydatetime(), ex)
        stopped = bool(acts) and acts[0]["kind"] == "stop"
        if acts:
            kind = acts[0]["kind"]
            if acts[0].get("line"):                                # 60선 엔벨로프 하단 이탈 — 그 선에서(시가가 이미 아래면 시가)
                fill = min(o, engine.floor_tick(acts[0]["line"]))
            elif kind == "stop":
                sp = p["avg"] * (1 - abs(engine._num(ex["stop"][1], 0) or 0) / 100)
                line = max(sp, p["avg"]) if p["be"] and ex.get("breakeven", [False])[0] else sp
                fill = min(o, engine.floor_tick(line))
            elif kind == "trail":
                fill = min(o, engine.floor_tick(p["high"] * (1 - abs(engine._num(ex["trail"][1], 0) or 0) / 100)))
            else:
                fill = cl
            sell(c, p, p["qty"], fill, kind, ts)
            if kind == "stop":
                stops_day[d] = stops_day.get(d, 0) + 1
        else:
            for t in (engine.take_orders(pos, ex) if p.get("kbuy") != k else []):
                if h >= t["price"]:
                    sell(c, p, t["qty"], max(t["price"], o), "take", ts)
                    p["takes_done"] = sorted(set(p["takes_done"]) | {t["stage"]})
                    p["be"] = True                                 # 데스크: 익절 체결 → breakeven 표시(되밀림·본전 손절이 이걸 본다)
            p["high"] = max(p["high"], h)
            p["low"] = min(p["low"], l)
        if p["qty"] <= 0:
            if stopped and p.get("rb", rebuy_n) > 0:               # 데스크: 손절로 다 팔리면 다음 거래일부터 같은 단계로 다시
                p.update(init=0, cost=0.0, avg=0.0, takes_done=[], be=False, high=0, low=10 ** 12, slice=0, bars=0, ex=None, fbuy=False,
                         rb=p.get("rb", rebuy_n) - 1, rb_day=d, ma_dead=False)
                for s in p["stages"]:
                    s["done"] = False
            elif follow and not follow_once:                         # 데스크: 예약은 남아 고점이 새로 나면 다시 산다
                p.update(init=0, cost=0.0, avg=0.0, takes_done=[], be=False, high=0, low=10 ** 12, slice=0, bars=0, ex=None, fbuy=False)
            else:
                p["closed"] = True
                P.pop(c)
    for c, p in list(P.items()):                                  # 기간 끝 — 남은 수량은 마지막 가격으로
        if p["qty"] > 0:
            sell(c, p, p["qty"], last_px.get(c, int(p["avg"])), "end", bars[-1][0] if bars else pd.Timestamp(end))
    if day0:
        eq_rows.append({"ts": pd.Timestamp(day0), "cash": cash, "positions_value": 0.0, "equity": cash, "n_positions": 0})
    skipped["conds_ignored"] = [c[0] for c in conds if c[0] not in BT_CONDS]
    skipped["conds_used"] = [f"{c[0]} {c[1]} {c[2]}" for c in use_conds]
    return evs, codes, trades, pd.DataFrame(eq_rows), skipped


def _lv_text(lv, base) -> str:
    o = engine.level_opts(lv)
    t = f"({(o['t0'] or '')[:2]}:{(o['t0'] or '')[2:]}~{(o['t1'] or '')[:2]}:{(o['t1'] or '')[2:]})".replace("(:~", "(~").replace("~:)", "~)") if o["t0"] or o["t1"] else ""
    if o["band"] is not None:
        return f"{'정규장' if base == 'reg' else '통합'} 15분봉 60선{engine._num(lv[0], 0):+g}% ±{o['band']:g}% 안에서 {lv[1]}%{t}"
    return f"{lv[0]}%에 {lv[1]}%{t}"


def to_studio(rule: dict, exit_rule: dict, safety: dict, capital: float, start: str, end: str, min_chg: float, session: str,
              evs, codes, trades, eq, skipped, universe: str = "ledger") -> str:
    """결과를 스튜디오 실행 기록으로 저장하고 run_id 를 돌려준다. spec 은 결과 화면용 자리표시(진입은 이 모듈이 했다)."""
    from studio.domain.models import BacktestResult, ExitReason, Trade
    from studio.domain.metrics import standard_metrics
    from studio.domain.robustness import robustness_report
    from studio.domain.spec import Spec
    from studio.application.ports import RunRecord
    from studio.infrastructure.run_store import FileRunStore

    ex = exit_rule["exits"]
    tk = [(engine._num(a), engine._num(b, 0) or 0) for a, b in (ex.get("take", [False, []])[1] or [])] if ex.get("take", [False])[0] else []
    levels, left = [], 100.0
    for pct, r in tk:
        if pct is None or r <= 0 or left <= 0:
            continue
        levels.append({"pct": pct, "fraction": round(min(1.0, r / left), 4)})
        left -= r
    if levels:
        levels[-1]["fraction"] = 1.0
    first_tp = tk[0][0] if tk else None
    tr = list(ex.get("trail", [False, ""])) + [None, None]
    spec_exits = {"stop_loss_pct": abs(engine._num(ex["stop"][1], 0) or 0) if ex.get("stop", [False])[0] else None,
                  "take_profit_levels": levels or None,
                  "trailing_stop_pct": abs(engine._num(tr[1], 0) or 0) if tr[0] else None,
                  "trail_activate_pct": (first_tp if (tr[2] or "take1") == "take1" else engine._num(tr[3]) if tr[2] == "gain" else None) if tr[0] else None,
                  "breakeven_after_pct": first_tp if ex.get("breakeven", [False])[0] else None}
    tail = f" · 신고 +{min_chg:g}%↑ · {'통합' if session == 'all' else '정규장'}"
    name = f"매매 데스크 · {rule['name']} · {exit_rule['name']}"
    name = (name if len(name) + len(tail) <= 100 else name[:99 - len(tail)] + "…") + tail   # 스튜디오 이름은 100자까지(10-20 긴 규칙 이름으로 저장 실패)
    spec = Spec.model_validate({
        "name": name, "mode": "daily_portfolio", "period": {"start": start, "end": end}, "portfolio": {"initial_capital": capital},
        "universe": {"type": "codes", "codes": codes or ["005930"]},
        "strategy": {"source": "builder", "entry": {"logic": "all", "items": [{"left": {"kind": "field", "name": "close"}, "op": "gt", "right": {"kind": "const", "value": 0}}]}},
        "exits": {k: v for k, v in spec_exits.items() if v is not None}})
    st = [Trade(code=t["code"], entry_ts=pd.Timestamp(t["entry_ts"]), entry_price=t["entry_price"], exit_ts=pd.Timestamp(t["exit_ts"]),
                exit_price=t["exit_price"], qty=t["qty"], gross_pnl=t["gross_pnl"], commission=t["commission"], tax=t["tax"],
                slippage_cost=0.0, net_pnl=t["net_pnl"], net_pct=t["net_pct"] / 100, exit_reason=ExitReason(t["exit_reason"]),
                bars_held=t["bars_held"], mfe_pct=t["mfe_pct"], mae_pct=t["mae_pct"], entry_id=t["entry_id"], slice=t["slice"]) for t in trades]
    if eq.empty:
        eq = pd.DataFrame([{"ts": pd.Timestamp(start), "cash": capital, "positions_value": 0.0, "equity": capital, "n_positions": 0}])
    result = BacktestResult(trades=st, equity=eq, fills=[], skipped=skipped)
    metrics = standard_metrics(result, capital)
    # 스튜디오는 비용 합계를 체결 기록(fills)에서 더하는데 여기선 fills 를 안 넘긴다 — 거래에서 직접(10-22 사용자 "비용이 왜 0원")
    metrics.update(commission_total=sum(t["commission"] for t in trades), tax_total=sum(t["tax"] for t in trades), slippage_total=0.0)
    eq = eq.copy()
    peak = eq["equity"].cummax().clip(lower=capital)
    eq["drawdown_pct"] = (eq["equity"] / peak - 1) * 100
    tdf = pd.DataFrame(trades)
    if len(tdf):
        tdf["sector"] = None
        tdf["net_pct"] = tdf["net_pct"] / 100                     # 여기선 %, 스튜디오는 비율(0.14 = 14%) — 10-22 거래 표에 1429% 로 나왔다
    ign = skipped.get("conds_ignored") or []
    skipped = {k: v for k, v in skipped.items() if isinstance(v, int)}
    warnings = ([f"매수 조건 중 백테스트에 못 넣은 것(무시함): {', '.join(ign)}"] if ign else []) + [
        f"매매 데스크 규칙을 그대로 대입한 실행 — 진입·청산은 trader.backtest 가 계산했다(스튜디오 명세의 진입 조건은 자리표시)",
        (f"대상: 선정 일지에 직접 고른 종목 {len(evs)}건(기준일 = 규칙 기준으로 장부에서 본 그 기간 신고일 전부 + 손으로 정한 기준일 — 고른 날과 무관)" if universe == "journal" else
         f"대상: 신고대금 장부 {start}~{end} 신고일 중 그날 {'정규장' if session == 'reg' else '통합'} 상승률 +{min_chg:g}% 이상 {len(evs)}건 전부(직접 고른 종목이 아님)"),
        "5분봉 근사: 지정가는 닿으면 체결(대기 순번 무시), 같은 봉에서는 손절·되밀림을 익절보다 먼저 본다",
        "생존 편향: 상장폐지 종목은 장부·분봉에 없다",
    ] + ([] if session == "all" else ["정규장(KRX 09:00~15:30) 분봉 — 장전·장후(NXT) 체결은 빠졌다(통합 아님)"])
    ex0 = exit_rule["exits"]
    if any(engine.level_opts(lv)["band"] is not None for lv in rule["ladder"]["levels"]) or (ex0.get("ma_env") or [False])[0]:
        warnings.append("15분봉 60선: 데스크는 만드는 중인 15분봉을 지금가로 넣는다 — 여기선 끝난 5분봉까지로 계산(최대 5분 늦다). "
                        "통합 15분봉은 2026-08-24 보관소부터, 정규장은 KRX 1분봉부터 · 앞 15분봉 59개가 안 되는 날은 60선 단계를 안 산다"
                        + (f"(그런 종목·날 {skipped['ma_none']}건)" if skipped.get("ma_none") else ""))
    from studio.application.backtest_service import spec_hash, structure_hash
    L, sf = rule["ladder"], safety
    tr_when = {"take1": "1차 익절이 체결된 뒤", "gain": f"+{tr[3]}% 오른 뒤", "always": "산 값 위로 오르면 바로"}.get(tr[2] or "take1")
    story = (f"신고대금 장부에서 신고일 {'정규장' if session == 'reg' else '통합'} 상승률 +{min_chg:g}% 이상인 종목을, 신고일 "
             f"{'정규장' if L.get('base') == 'reg' else '애프터'} 종가 대비 " + " · ".join(_lv_text(lv, L.get("base")) for lv in L["levels"])
             + f" 지정가로 다음 거래일부터 {(L.get('keep') or {}).get('days', 1)}거래일 동안 걸어 둔다"
             + (f" (다음 날 {(L.get('guard') or {}).get('until', '09:30')} 전에 기준가 −{(L.get('guard') or {}).get('pct', 5)}% 이하면 그 예약을 버림)" if (L.get("guard") or {}).get("on") else "")
             + (" (시가가 마지막 단계보다 아래로 갭 하락한 날은 안 삼)" if (L.get("gap") or {}).get("on") else "")
             + (f" (15분봉 60선 −{(L.get('ma_stop') or {}).get('pct', 6)}% 아래로 깨면 60선 단계는 그만 삼)" if (L.get("ma_stop") or {}).get("on") else "")
             + (f" (60선 사는 값이 기준일 종가 −{(L.get('c_near') or {}).get('pct', 3)}% 이상일 때만 삼" + (" · 그 선 위면 남은 단계 합쳐 한 번에" if (L.get("c_near") or {}).get("full") else "") + ")" if (L.get("c_near") or {}).get("on") else "")
             + (f" (15분봉이 60선 위 0~{(L.get('ma_confirm') or {}).get('hold', 2)}% 안에서 {(L.get('ma_confirm') or {}).get('n', 3)}개 연달아 마감하면 그 봉 종가에 삼, 60선 아래 마감이면 처음부터)" if (L.get("ma_confirm") or {}).get("on") else "")
             + (f" (손절로 다 팔리면 다음 거래일부터 같은 단계로 다시 삼, 최대 {(L.get('rebuy') or {}).get('n', 1)}번)" if (L.get("rebuy") or {}).get("on") else "")
             + (" (안 산 채 고점이 새로 나면 기준가를 그날 종가로 옮기고 유지 기간을 다시 셈" + (" · 판 뒤엔 다시 안 따라감" if (L.get("follow_high") or {}).get("once") else " · 판 뒤에도 따라가 다시 삼")
                  + (" · 고점 = 기준일 뒤 최고가 돌파" if (L.get("follow_high") or {}).get("def") == "run" else " · 고점 = 전날 고가 돌파")
                  + (" · 오늘 고점 갱신 중에도 예약 유지" if (L.get("follow_high") or {}).get("keep_today") else "") + ")" if (L.get("follow_high") or {}).get("on") else "")
             + (f" (아직 안 샀는데 전날 종가가 기준가 −{(L.get('drop') or {}).get('pct', 5)}% 이하면 예약을 버림)" if (L.get("drop") or {}).get("on") else "")
             + (f". 매수 조건: {' · '.join(f'{c[0]} {c[2]} {c[1]}' for c in (rule.get('conds') or []) if str(c[2]).strip())}" if any(str(c[2]).strip() for c in (rule.get('conds') or [])) else "")
             + f". 1종목 금액 {rule.get('amount') or '자동'} · 동시 보유 최대 {sf.get('max_positions') or '제한 없음'} · 원금 {capital:,.0f}원. "
             + f"청산: 손절 −{ex['stop'][1]}%" + (", 분할 익절 " + " · ".join(f"+{a}%에 {b}%" for a, b in ex['take'][1]) if ex.get('take', [False])[0] else "")
             + (f", 15분봉 60선 −{ex['ma_env'][1]}% 깨면 손절({'통합' if (ex['ma_env'] + [None, None])[2] == 'aft' else '정규장'} 15분봉)" if (ex.get("ma_env") or [False])[0] else "")
             + (f", 고점 대비 −{tr[1]}% ({tr_when})" if tr[0] else "") + (", 첫 익절 뒤 본전 손절" if ex.get("breakeven", [False])[0] else "") + ".")
    rec = RunRecord(spec=spec, meta={"name": name, "kind": "trader_rules", "mode": "daily_portfolio", "params": {}, "compat": False,
                                     "spec_hash": spec_hash(spec), "structure_hash": structure_hash(spec), "data": {"minute": [start, end]},
                                     "warmup_bars": 0, "elapsed_sec": 0, "period_used": [start, end], "warnings": warnings, "narration": story,
                                     "trader": {"rule": rule, "exit": exit_rule, "safety": safety, "capital": capital, "min_chg": min_chg, "session": session}},
                    summary=json.loads(json.dumps({"metrics": metrics, "legacy_metrics": None, "criteria": [], "universe_excluded": {},
                                                   "n_closed": len(trades), "n_bars": 0, "skipped": skipped, "n_trades": len(trades),
                                                   "n_entries": len({t["entry_id"] for t in trades}), "n_codes": len(codes),
                                                   "warnings": warnings,
                                                   "robustness": robustness_report(tdf, capital) if len(tdf) else None}, default=str)),
                    trades=tdf, equity=eq, warnings=warnings)
    return FileRunStore(ROOT / "results" / "studio").save(rec)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--capital", type=float, default=30_000_000)
    ap.add_argument("--session", choices=["all", "reg"], default="reg")
    ap.add_argument("--universe", choices=["ledger", "journal"], default="ledger")
    a = ap.parse_args()
    t0 = time.time()
    _status(state="running", stage="준비", pct=0, run_id=None, error=None, args=vars(a))
    try:
        rules = json.loads((STATE / "rules.json").read_text(encoding="utf-8"))
        rule = next(r for r in rules["rules"] if r["id"] == a.rule)
        if not rule.get("ladder", {}).get("on"):
            raise ValueError("이 매수 규칙은 '기준일 종가 분할매수'가 꺼져 있어 백테스트할 수 없습니다")
        mc = engine._num(rule["ladder"].get("ref_min_chg"), 0) or 0     # 신고일 상승률은 규칙 것만 — 데스크와 같은 종목(10-22 사용자)
        _status(args={**vars(a), "min_chg": mc})
        eid = rule.get("exit") or rules.get("manual_exit")
        exit_rule = next((x for x in rules.get("exits", []) if x["id"] == eid), None)
        if not exit_rule:
            raise ValueError("청산 규칙이 없습니다")
        start = a.start                                             # 통합 분봉이 없는 날은 봉이 없어 그날만 못 산다 — 08-24 전에 받아 둔 종목(10-30 한국콜마)도 쓰게 자르지 않는다
        fx = next((x["exits"] for x in rules.get("exits", []) if x["id"] == ((rule["ladder"].get("follow_high") or {}).get("exit"))), None)
        evs, codes, trades, eq, skipped = simulate(rule, exit_rule["exits"], rules["safety"], a.capital, start, a.end, mc, a.session,
                                                   a.universe, fx)
        _status(stage="저장", pct=97)
        run_id = to_studio(rule, exit_rule, rules["safety"], a.capital, start, a.end, mc, a.session, evs, codes, trades, eq, skipped,
                           a.universe)
        pnl = sum(t["net_pnl"] for t in trades)
        miss: list = []
        if a.universe == "journal":                                   # 그 기간에 대입할 신고대금 날이 하나도 없던 고른 종목(화면에 보인다)
            have = {e[1] for e in evs}
            J = json.loads((STATE / "journal.json").read_text(encoding="utf-8")) if (STATE / "journal.json").exists() else []
            keep = journal_codes()
            miss = list(dict.fromkeys(f"{j.get('name') or j['code']}(그 기간 신고대금 날 없음)" for j in J if j["code"] in keep and j["code"] not in have))
        _status(state="done", stage="끝", pct=100, run_id=run_id, sec=round(time.time() - t0), conds_used=skipped.get("conds_used"),
                conds_ignored=skipped.get("conds_ignored"),
                result={"pnl": round(pnl), "journal_missing": miss, "n_entries": len({t['entry_id'] for t in trades}),
                        # 손익은 수수료·세금을 뺀 값 — 화면에 비용을 같이 보인다(10-20 사용자 "수수료 세금 같이 계산해서")
                        "fee": round(sum(t["commission"] for t in trades)), "tax": round(sum(t["tax"] for t in trades)),
                        "gross": round(sum(t["gross_pnl"] for t in trades)), "fee_rate": FEE, "tax_rate": TAX,
                        "wins": sum(1 for e in {t["entry_id"] for t in trades}
                                    if sum(x["net_pnl"] for x in trades if x["entry_id"] == e) > 0)})
    except Exception as e:                                          # noqa: BLE001 — 화면에 이유를 보여 준다
        _status(state="error", error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-1500:])
        raise


if __name__ == "__main__":
    main()
