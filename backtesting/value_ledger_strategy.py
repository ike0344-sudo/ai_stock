"""신고대금 장부(52주 신고거래대금, 1,000억+) 종목의 매매법 찾기 — 사용자 "어디서 진입하고 어디서 청산하면 좋을지"(lead 2026-10-14).

    python -m backtesting.value_ledger_strategy [--prep 폴더]      # 폴더 = vl_ev.pkl·vl_fw.npy 가 있는 곳(vl_prep.py 결과)

읽기 전용 — data/ 에 안 쓰고 키움도 안 부른다. 신고 정의는 backtesting/value_ledger.py.
A(일봉, 통합 일봉): 진입 4종 × 청산 격자(보유일·손절·익절). 학습 2020~2023 에서만 고르고 검증 2024~2026 은 그대로 보고.
   같은 날 손절·익절이 다 닿으면 손절 먼저(보수적), 시가가 이미 넘었으면 시가 체결, 비용 왕복 0.25%.
   보유 N일 = 진입한 날을 1일째로 세어 N일째 종가에 판다(26거래일까지만 있어 넘으면 26일째 종가).
   지정가·재돌파로 들어간 날은 그날 안 순서를 몰라 손절만 본다(익절은 다음 날부터 — 보수적).
B(분봉): 신고 다음 날 09:00~10:30 — data/stocks/minute(카탈로그 minute_krx = **KRX 분봉**, 2025-07~) 로 재고,
   2026-08-24 뒤는 통합 분봉 보관소(datahub.minute_al_archive)로 따로 한 번 더(섞어 비교하지 않는다).
"""
from __future__ import annotations

import argparse
import itertools
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

PREP = r"C:/Users/ike03/AppData/Local/Temp/claude/C--Users-ike03-Desktop-code-ai-stock/e4a37627-d097-4f11-ab06-07f7055b9168/scratchpad"
COST = 0.0025
LAST = 26
HOLDS = (1, 3, 5, 10, 20)
STOPS = (0, 5, 8, 10)  # 0 = 손절 없음
TGTS = (0, 10, 15, 20, 30)  # 0 = 익절 없음
PULLS = (3, 5, 8, 10, 15)
FILTERS = ("chg", "pos", "vs52", "vs20", "val", "cnt")


# ====================================================================== 공통: 시뮬레이션
def simulate(fw: np.ndarray, e: np.ndarray, P: np.ndarray, hold: int, stop, tgt, entry_full_day: bool) -> np.ndarray:
    """fw (n,27,4) 시고저종 · e 진입일(0~26, -1=진입 없음) · P 진입가 → 순수익률(비용 뒤, 진입 없음·자료 부족은 NaN).
    entry_full_day: 진입이 그날 시가라 그날 전체가 진입 뒤다(손절·익절 다 본다) / 아니면 그날은 손절만(보수적)."""
    n = len(e)
    out = np.full(n, np.nan)
    ok = (e >= 0) & np.isfinite(P) & (P > 0)
    last = np.minimum(np.where(ok, e, 0) + hold - 1, LAST)
    idx = np.arange(n)
    ok &= np.isfinite(fw[idx, last, 3])
    S = P * (1 - stop / 100) if stop else np.full(n, -np.inf)
    T = P * (1 + tgt / 100) if tgt else np.full(n, np.inf)
    done = ~ok
    ex = np.full(n, np.nan)
    for k in range(hold):
        d = np.where(ok, e, 0) + k
        act = ~done & (d <= last)
        if not act.any():
            break
        dd = np.minimum(d, LAST)
        o, h, lo, c = (fw[idx, dd, j] for j in range(4))
        first = k == 0
        if first:
            hs = act & (lo <= S)
            ht = act & (h >= T) & ~hs & entry_full_day
        else:
            go = act & (o <= S)
            gt = act & (o >= T) & ~go
            ex[go], ex[gt] = o[go], o[gt]
            done |= go | gt
            act &= ~(go | gt)
            hs = act & (lo <= S)
            ht = act & (h >= T) & ~hs
        ex[hs], ex[ht] = S[hs], T[ht]
        done |= hs | ht
        end = act & ~(hs | ht) & (d == last)
        ex[end] = c[end]
        done |= end
    out[ok] = ex[ok] / P[ok] - 1 - COST
    return out


def entries(fw: np.ndarray) -> dict:
    """진입 방법 → (진입일, 진입가, 그날 전체가 진입 뒤인가)."""
    n = len(fw)
    c0, h0 = fw[:, 0, 3], fw[:, 0, 1]
    out = {"다음날시가": (np.ones(n, int), fw[:, 1, 0], True)}
    for p in PULLS:
        L = c0 * (1 - p / 100)
        e, P = np.full(n, -1), np.full(n, np.nan)
        for d in range(10, 0, -1):  # 거꾸로 돌며 덮어써서 '가장 이른 날'이 남게
            hit = fw[:, d, 2] <= L
            e[hit], P[hit] = d, np.minimum(fw[hit, d, 0], L[hit])
        out[f"눌림-{p}%"] = (e, P, False)
    e, P = np.full(n, -1), np.full(n, np.nan)
    for d in range(10, 0, -1):
        hit = fw[:, d, 1] > h0
        e[hit], P[hit] = d, np.maximum(fw[hit, d, 0], h0[hit])
    out["고가재돌파"] = (e, P, False)
    return out


def stats(x: np.ndarray) -> dict:
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return {"n": 0, "mean": np.nan, "med": np.nan, "win": np.nan}
    return {"n": len(x), "mean": x.mean() * 100, "med": np.median(x) * 100, "win": (x > 0).mean() * 100}


def robust_pick(grid: pd.DataFrame, axes: dict, score: str, min_n: int, n_col: str) -> pd.DataFrame:
    """격자 칸마다 '이웃(각 축 ±1칸) 평균' 점수 — 한 칸만 튄 최고값 대신 주변까지 좋은 칸을 고른다(표본 min_n 미만 칸은 빼고)."""
    g = grid.copy()
    pos = {a: {v: i for i, v in enumerate(vals)} for a, vals in axes.items()}
    keys = [tuple(pos[a][r[a]] for a in axes) for _, r in g.iterrows()]
    look = {(r["entry"], k): r[score] for k, (_, r) in zip(keys, g.iterrows()) if r[n_col] >= min_n}
    nb = []
    for k, (_, r) in zip(keys, g.iterrows()):
        vals = [look[(r["entry"], kk)] for kk in itertools.product(*[range(i - 1, i + 2) for i in k]) if (r["entry"], kk) in look]
        nb.append(np.mean(vals) if vals and r[n_col] >= min_n else np.nan)
    g["robust"] = nb
    return g


# ====================================================================== A: 일봉
def part_a(prep: str) -> dict:
    ev = pd.read_pickle(os.path.join(prep, "vl_ev.pkl"))
    fw = np.load(os.path.join(prep, "vl_fw.npy"))
    yr = ev.date.str[:4].astype(int).to_numpy()
    tr, te = yr <= 2023, yr >= 2024
    print(f"[A] 신고 {len(ev):,}건 · 학습(2020~2023) {tr.sum():,} · 검증(2024~2026) {te.sum():,}")
    # ① 하룻밤
    on = fw[:, 1, 0] / fw[:, 0, 3] - 1 - COST
    res = {"overnight": {"tr": stats(on[tr]), "te": stats(on[te]),
                         "years": {y: stats(on[yr == y])["mean"] for y in sorted(set(yr))}}}
    ent = entries(fw)
    rows = []
    for name, (e, P, full) in ent.items():
        fill_tr, fill_te = (e[tr] >= 0).mean() * 100, (e[te] >= 0).mean() * 100
        for hold, stop, tgt in itertools.product(HOLDS, STOPS, TGTS):
            r = simulate(fw, e, P, hold, stop, tgt, full)
            a, b = stats(r[tr]), stats(r[te])
            tr_years = [np.nanmean(r[yr == y]) for y in range(2020, 2024)]
            rows.append({"entry": name, "hold": hold, "stop": stop, "tgt": tgt, "fill_tr": fill_tr, "fill_te": fill_te,
                         "tr_pos_years": int(sum(v > 0 for v in tr_years)),
                         **{f"tr_{k}": v for k, v in a.items()}, **{f"te_{k}": v for k, v in b.items()}})
    grid = robust_pick(pd.DataFrame(rows), {"hold": HOLDS, "stop": STOPS, "tgt": TGTS}, "tr_mean", 200, "tr_n")
    grid.to_pickle(os.path.join(prep, "vl_grid_a.pkl"))
    res["grid"] = grid
    best = grid.sort_values("robust", ascending=False).dropna(subset=["robust"])
    res["per_entry"] = best.groupby("entry").head(1).sort_values("robust", ascending=False)
    # 추천 = 학습에서만: 이웃 평균이 양수이고 학습 4년 중 3년 이상 양수인 칸 중 이웃 평균 최고(검증 연도는 안 본다)
    elig = best[(best.robust > 0) & (best.tr_mean > 0) & (best.tr_pos_years >= 3)]
    res["eligible"] = elig
    res["top"] = top = elig.iloc[0] if len(elig) else best.iloc[0]
    e, P, full = ent[top.entry]
    r = simulate(fw, e, P, int(top.hold), int(top.stop), int(top.tgt), full)
    res["top_years"] = {y: stats(r[yr == y]) for y in sorted(set(yr))}
    res["top_worst"] = float(np.nanmin(r) * 100)
    res["filters"] = filter_search(ev, r, tr, te, yr)
    res["filters_overnight"] = filter_search(ev, on, tr, te, yr)
    return res


def filter_search(ev: pd.DataFrame, r: np.ndarray, tr, te, yr) -> list[dict]:
    """학습에서만: 조건 하나(분위 경계로 이상/이하) → 학습 평균이 가장 좋고 학습 4년 중 3년 이상 기본보다 나은 것. 최대 2개(두 번째는 첫째 위에서)."""
    picked, mask = [], np.ones(len(ev), bool)
    base_tr = np.nanmean(r[tr & mask]) * 100
    for step in range(2):
        best = None
        for f in FILTERS:
            if any(p["f"] == f for p in picked):
                continue
            x = ev[f].to_numpy(float)
            qs = np.nanquantile(x[tr & mask], [0.2, 0.4, 0.6, 0.8])
            for q in qs:
                for side in (">=", "<="):
                    m = mask & ((x >= q) if side == ">=" else (x <= q)) & np.isfinite(x)
                    if (m & tr & np.isfinite(r)).sum() < (300 if step == 0 else 200):
                        continue
                    mt = np.nanmean(r[m & tr]) * 100
                    cur = np.nanmean(r[mask & tr]) * 100
                    yrs_better = sum(np.nanmean(r[m & (yr == y)]) > np.nanmean(r[mask & (yr == y)]) for y in range(2020, 2024))
                    if yrs_better >= 3 and mt - cur >= 1.0 and (best is None or mt > best["tr_mean"]):
                        best = {"f": f, "side": side, "q": float(q), "tr_mean": mt, "tr_gain": mt - cur, "yrs_better": int(yrs_better), "_m": m}
        if best is None:
            break
        mask = best.pop("_m")
        best["tr"] = stats(r[mask & tr])
        best["te"] = stats(r[mask & te])
        best["te_base"] = stats(r[te])
        best["years"] = {y: stats(r[mask & (yr == y)])["mean"] for y in sorted(set(yr))}
        picked.append(best)
    return picked


# ====================================================================== B: 분봉
OPEN_MIN, END_MIN = 9 * 60, 10 * 60 + 30
NB = END_MIN - OPEN_MIN  # 09:00~10:29 봉 90개 (10:29 봉 종가 = 10:30 가격)
B_STOPS = (0, 2, 3, 5)
B_TGTS = (0, 3, 5, 8)
B_BREAK = (5, 15, 30)
B_PULL = (2, 3, 5)


def next_days(ev: pd.DataFrame) -> pd.Series:
    """신고일 → 그 종목의 다음 거래일(통합 일봉 날짜)."""
    out = {}
    for code, g in ev.groupby("code"):
        d = pd.read_csv(f"data/stocks/daily_al/{code}.csv", dtype={"date": str}, usecols=["date"]).date.to_numpy()
        pos = np.searchsorted(d, g.date.to_numpy(), side="right")
        for i, p in zip(g.index, pos):
            out[i] = d[p] if p < len(d) else None
    return pd.Series(out)


def _load_minute(code: str, source: str) -> pd.DataFrame | None:
    if source == "krx":
        p = f"data/stocks/minute/{code}.csv"
        if not os.path.isfile(p):
            return None
        d = pd.read_csv(p, index_col=0, parse_dates=True)
    else:
        from datahub import minute_al_archive as arch
        d = arch.read(code)
        if d.empty:
            return None
    d.index = pd.DatetimeIndex(d.index)
    return d[~d.index.duplicated(keep="last")].sort_index()


def minute_bars(ev: pd.DataFrame, nd: pd.Series, source: str, since: str | None = None):
    """이벤트마다 다음 날 09:00~10:29 1분봉 (n,90,4) — 빈 분은 직전 종가로 채운다(거래 없음 = 가격 그대로)."""
    sel = ev.index[nd.notna().to_numpy()]
    if since:
        sel = [i for i in sel if nd[i] >= since]
    by_code = {}
    for i in sel:
        by_code.setdefault(ev.at[i, "code"], []).append(i)

    def one(code):
        d = _load_minute(code, source)
        res = []
        if d is None:
            return res
        days = d.index.normalize()
        for i in by_code[code]:
            day = pd.Timestamp(nd[i])
            x = d[days == day]
            mod = x.index.hour * 60 + x.index.minute
            x = x[(mod >= OPEN_MIN) & (mod < END_MIN)]
            if len(x) < 10:
                continue
            arr = np.full((NB, 4), np.nan)
            k = (x.index.hour * 60 + x.index.minute).to_numpy() - OPEN_MIN
            arr[k] = x[["open", "high", "low", "close"]].to_numpy(float)
            if not np.isfinite(arr[0, 0]):
                continue  # 09:00 첫 봉이 없으면 시가를 모른다
            for t in range(1, NB):
                if not np.isfinite(arr[t, 0]):
                    arr[t] = arr[t - 1, 3]
            res.append((i, arr))
        return res

    with ThreadPoolExecutor(8) as ex:
        parts = list(ex.map(one, list(by_code)))
    got = [x for p in parts for x in p]
    if not got:
        return np.array([], int), np.zeros((0, NB, 4))
    ids = np.array([g[0] for g in got])
    return ids, np.stack([g[1] for g in got])


def b_entries(mb: np.ndarray) -> dict:
    n = len(mb)
    o0 = mb[:, 0, 0]
    out = {"09:00시가": (np.zeros(n, int), o0, True)}
    for N in B_BREAK:
        H = np.nanmax(mb[:, :N, 1], axis=1)
        e, P = np.full(n, -1), np.full(n, np.nan)
        for t in range(NB - 1, N - 1, -1):
            hit = mb[:, t, 1] > H
            e[hit], P[hit] = t, np.maximum(mb[hit, t, 0], H[hit])
        out[f"첫{N}분고가돌파"] = (e, P, False)
    for x in B_PULL:
        L = o0 * (1 - x / 100)
        e, P = np.full(n, -1), np.full(n, np.nan)
        for t in range(NB - 1, 0, -1):
            hit = mb[:, t, 2] <= L
            e[hit], P[hit] = t, np.minimum(mb[hit, t, 0], L[hit])
        out[f"시가대비-{x}%눌림"] = (e, P, False)
    return out


def b_simulate(mb, e, P, stop, tgt, full):
    """분봉판 simulate — 10:29 봉 종가(10:30)에 남은 것을 판다."""
    fw = mb
    n = len(e)
    ok = (e >= 0) & np.isfinite(P)
    S = P * (1 - stop / 100) if stop else np.full(n, -np.inf)
    T = P * (1 + tgt / 100) if tgt else np.full(n, np.inf)
    ex = np.full(n, np.nan)
    done = ~ok
    idx = np.arange(n)
    for t in range(NB):
        act = ~done & (t >= np.where(ok, e, NB))
        if not act.any():
            continue
        o, h, lo, c = (fw[:, t, j] for j in range(4))
        first = act & (t == e)
        later = act & ~first
        go = later & (o <= S)
        gt = later & (o >= T) & ~go
        ex[go], ex[gt] = o[go], o[gt]
        done |= go | gt
        act &= ~(go | gt)
        hs = act & (lo <= S)
        ht = act & (h >= T) & ~hs & (later | (first & full))
        ex[hs], ex[ht] = S[hs], T[ht]
        done |= hs | ht
        if t == NB - 1:
            end = act & ~(hs | ht)
            ex[end] = c[end]
            done |= end
    _ = idx
    return np.where(ok, ex / P - 1 - COST, np.nan)


def part_b(prep: str) -> dict:
    ev = pd.read_pickle(os.path.join(prep, "vl_ev.pkl"))
    nd = next_days(ev)
    res = {}
    for source, since, tag in (("krx", "20250701", "KRX 분봉"), ("al", "20260824", "통합 분봉 보관소")):
        ids, mb = minute_bars(ev, nd, source, since)
        dates = nd[ids].to_numpy() if len(ids) else np.array([])
        half = dates < "20260201" if source == "krx" else np.ones(len(ids), bool)
        rows = []
        for name, (e, P, full) in b_entries(mb).items():
            for stop, tgt in itertools.product(B_STOPS, B_TGTS):
                r = b_simulate(mb, e, P, stop, tgt, full)
                a, b = stats(r[half]), stats(r[~half])
                rows.append({"entry": name, "stop": stop, "tgt": tgt, "fill": (e >= 0).mean() * 100 if len(e) else np.nan,
                             **{f"h1_{k}": v for k, v in a.items()}, **{f"h2_{k}": v for k, v in b.items()}})
        g = pd.DataFrame(rows)
        if len(g):
            g = robust_pick(g, {"stop": B_STOPS, "tgt": B_TGTS}, "h1_mean", 30, "h1_n")
        res[tag] = {"n_events": len(ids), "n_h1": int(half.sum()), "n_h2": int((~half).sum()), "grid": g,
                    "range": (dates.min() if len(dates) else None, dates.max() if len(dates) else None)}
        print(f"[B:{tag}] 이벤트(다음 날 분봉 있음) {len(ids):,} · 앞 {int(half.sum())} / 뒤 {int((~half).sum())}")
    return res


# ====================================================================== 2차 (lead 10-14 2차 지시)
# C: 상한가 하룻밤을 '실제로 살 수 있는 판'으로 · D: 가설 카드 H-020·H-021·H-022 를 정의대로.
# 분봉 함정(state/agent_reports/data-agent_value_ledger_minute_coverage.md): 하루 정규장 봉 300개 미만 제외 · 10시 개장일 제외 ·
# 분봉/일봉 수정주가 어긋난 5종목 제외 · KRX 분봉만 쓴다(통합과 섞지 않음 — 결과에 'KRX 분봉' 표시).
COSTS = (0.0025, 0.0043)
BAD_CODES = {"001520", "348340", "196170", "012200", "008830"}
TEN_OPEN = {"20251113", "20260102"}
REG0, REG1 = 9 * 60, 15 * 60 + 30
LIMIT_TOUCH = 1.294  # 고가/전일종가 ≥ 이 값 = 상한가 도달(호가 내림으로 잃는 폭은 최대 0.4% — 그 아래로는 안 내려간다)


def cstats(gross: np.ndarray) -> dict:
    g = np.asarray(gross, float)
    g = g[np.isfinite(g)]
    out = {"n": int(len(g))}
    if not len(g):
        return out
    out["gross"] = g.mean() * 100
    for c in COSTS:
        x = g - c
        out[f"{c * 100:.2f}"] = {"mean": x.mean() * 100, "med": np.median(x) * 100, "win": (x > 0).mean() * 100}
    return out


def cfmt(s: dict) -> str:
    if not s.get("n"):
        return "n=0"
    a, b = s["0.25"], s["0.43"]
    return (f"n={s['n']:,} · 비용 전 {s['gross']:+.2f}% · 0.25% 뒤 평균 {a['mean']:+.2f}% 중앙 {a['med']:+.2f}% 승률 {a['win']:.0f}%"
            f" · 0.43% 뒤 평균 {b['mean']:+.2f}%")


def by_year(g: np.ndarray, yr: np.ndarray) -> dict:
    return {int(y): round(float(np.nanmean(g[yr == y]) * 100), 2) for y in sorted(set(yr)) if np.isfinite(g[yr == y]).any()}


def split_report(g: np.ndarray, yr: np.ndarray) -> dict:
    return {"tr": cstats(g[yr <= 2023]), "te": cstats(g[yr >= 2024]), "years": by_year(g, yr)}


def load_al_all() -> dict:
    """통합 일봉 전 종목(vl_prep.py 와 같은 손질: 0 가격은 종가로)."""
    import glob

    def one(p):
        d = pd.read_csv(p, dtype={"date": str})
        c = d.close.replace(0, np.nan).ffill()
        for k in ("open", "high", "low"):
            d[k] = d[k].where(d[k] > 0, c)
        d["close"] = c
        return os.path.basename(p)[:6], d
    with ThreadPoolExecutor(8) as ex:
        return dict(ex.map(one, glob.glob("data/stocks/daily_al/*.csv")))


def krx_days(code: str, want: set) -> dict:
    """KRX 분봉 → {날짜: (분, 시, 고, 저, 종, 량)} 정규장 09:00~15:30. 함정 3종(봉 300개 미만·10시 개장일·어긋난 5종목)은 뺀다."""
    if code in BAD_CODES or not want:
        return {}
    csv, pq = f"data/stocks/minute/{code}.csv", f"data/stocks/minute/{code}.parquet"
    if os.path.isfile(csv) and (not os.path.isfile(pq) or os.path.getmtime(csv) >= os.path.getmtime(pq)):
        d = pd.read_csv(csv, index_col=0, parse_dates=True)
    elif os.path.isfile(pq):
        d = pd.read_parquet(pq)
        d = d.set_index("date") if "date" in d.columns else d
    else:
        return {}
    d.index = pd.DatetimeIndex(d.index)
    days = d.index.strftime("%Y%m%d").to_numpy()
    d = d[np.isin(days, list(want))]
    d = d[~d.index.duplicated(keep="last")].sort_index()
    mod = (d.index.hour * 60 + d.index.minute).to_numpy()
    keep = (mod >= REG0) & (mod <= REG1)
    d, mod = d[keep], mod[keep]
    out = {}
    days = d.index.strftime("%Y%m%d").to_numpy()
    for day in np.unique(days):
        if day in TEN_OPEN:
            continue
        k = days == day
        if k.sum() < 300:
            continue
        x = d[k]
        out[day] = (mod[k], *(x[c].to_numpy(float) for c in ("open", "high", "low", "close", "volume")))
    return out


def load_krx_needed(need: dict) -> dict:
    """need = {code: set(날짜)} → {(code, 날짜): 배열}."""
    def one(code):
        return code, krx_days(code, need[code])
    out = {}
    with ThreadPoolExecutor(8) as ex:
        for code, dd in ex.map(one, list(need)):
            for day, arr in dd.items():
                out[(code, day)] = arr
    return out


def next_day_map(al: dict, code: str, day: str) -> str | None:
    d = al[code].date.to_numpy() if code in al else None
    if d is None:
        return None
    p = np.searchsorted(d, day, side="right")
    return d[p] if p < len(d) else None


def tick_of(p: float) -> float:
    return float(np.select([p < 2000, p < 5000, p < 20000, p < 50000, p < 200000, p < 500000], [1, 5, 10, 50, 100, 500], 1000))


def bar_exit(m, o, h, l, c, ie, P, stop, last_min, nohigh=0, trail_ticks=0):
    """1분봉 ie 봉 시가(P)에 산 뒤 — 손절(고정 stop, 또는 고점−n호가 추적)·last_min 봉 종가 시간청산·고가 갱신 없이 nohigh 분이면 청산. 반환 (청산가, 사유)."""
    last = int(np.searchsorted(m, last_min, side="right")) - 1
    if last < ie:
        return np.nan, "none"
    peak, since = P, 0
    for i in range(ie, last + 1):
        S = stop
        if trail_ticks:
            S = max(S, peak - trail_ticks * tick_of(peak))
        if i > ie and o[i] <= S:
            return o[i], "stop"
        if l[i] <= S:
            return S, "stop"
        if h[i] > peak:
            peak, since = h[i], 0
        else:
            since += 1
        if nohigh and since >= nohigh:
            return c[i], "nohigh"
    return c[last], "time"


# ------------------------------------------------------------------ C. 상한가 하룻밤 — 살 수 있는 판
def part_c(prep: str, al: dict) -> dict:
    ev = pd.read_pickle(os.path.join(prep, "vl_ev.pkl"))
    fw = np.load(os.path.join(prep, "vl_fw.npy"))
    yr = ev.date.str[:4].astype(int).to_numpy()
    prev = ev.prev.to_numpy(float)
    o0, h0, c0, o1 = fw[:, 0, 0], fw[:, 0, 1], fw[:, 0, 3], fw[:, 1, 0]
    touch = h0 / prev >= LIMIT_TOUCH
    locked = touch & (c0 >= h0 * 0.999)
    g_touch = o1 / h0 - 1  # 상한가(=그날 고가)에 첫 닿을 때 샀다 → 다음날 시가
    res = {"touch_all": split_report(np.where(touch, g_touch, np.nan), yr),
           "touch_locked": split_report(np.where(locked, g_touch, np.nan), yr),
           "touch_released": split_report(np.where(touch & ~locked, g_touch, np.nan), yr),
           "n_touch": int(touch.sum()), "n_locked": int(locked.sum())}
    g_close = o1 / c0 - 1
    pos = ev.pos.to_numpy(float)
    chg = ev.chg.to_numpy(float)
    strong = ~touch & (chg >= 20) & (chg < 29)
    res["strong_close_eq_high"] = split_report(np.where(strong & (pos >= 0.999), g_close, np.nan), yr)
    res["strong_pos95"] = split_report(np.where(strong & (pos >= 0.95), g_close, np.nan), yr)
    res["strong_all"] = split_report(np.where(strong, g_close, np.nan), yr)
    # ② 분봉(KRX) — 2025-07~ 상한가 닿은 날
    sel = np.flatnonzero(touch & (ev.date.to_numpy() >= "20250701"))
    need, nd = {}, {}
    for i in sel:
        code, day = ev.code.iat[i], ev.date.iat[i]
        nd[i] = next_day_map(al, code, day)
        need.setdefault(code, set()).update({day} | ({nd[i]} if nd[i] else set()))
    K = load_krx_needed(need)
    rows = []
    for i in sel:
        code, day = ev.code.iat[i], ev.date.iat[i]
        a = K.get((code, day))
        if a is None:
            continue
        m, o, h, l, c, v = a
        Lk = h.max()
        if Lk / prev[i] < LIMIT_TOUCH:
            rows.append({"i": i, "krx_touch": False})
            continue
        i0 = int(np.flatnonzero(h >= Lk * (1 - 1e-9))[0])
        after = slice(i0, None)
        vol_lo = v[after][l[after] >= Lk * (1 - 1e-9)].sum()
        vol_hi = v[after][h[after] >= Lk * (1 - 1e-9)].sum()
        cum = (c[: i0 + 1] * v[: i0 + 1]).sum() / 1e8
        prev_max = ev.val.iat[i] / ev.mult.iat[i]
        b = K.get((code, nd[i])) if nd[i] else None
        o_next = b[1][0] if (b is not None and b[0][0] == REG0) else np.nan
        rows.append({"i": i, "krx_touch": True, "t": int(m[i0]), "locked": bool(c[-1] >= Lk * (1 - 1e-9)),
                     "lim_val_lo": vol_lo * Lk / 1e8, "lim_val_hi": vol_hi * Lk / 1e8, "cum_at_touch": cum, "prev_max": prev_max,
                     "known": bool(cum > prev_max), "g_krx": o_next / Lk - 1, "g_al": o1[i] / h0[i] - 1})
    mt = pd.DataFrame(rows)
    res["minute"] = mt
    res["minute_n_target"] = int(len(sel))
    return res


# ------------------------------------------------------------------ D. 가설 카드
def _arrs(K, code, day):
    a = K.get((code, day))
    if a is None or a[0][0] != REG0:  # 09:00 봉이 없으면 시가를 모른다(함정 2)
        return None
    return a


def h020_one(a, flush=0.03, deadline=615, ref="open", exit_min=629, nohigh=0, fixed_entry_min=None):
    """H-020 한 건 — 반환 dict(신호 없음이면 None, 털림 없음이면 {'noflush':True})."""
    m, o, h, l, c, v = a
    O = o[0]
    win = m < 600
    fl = np.flatnonzero(win & (l <= O * (1 - flush)))
    if fixed_entry_min is not None:  # 대조군(가): 털림 없이 시가 위 — 처리군 진입 시각에 산다
        if len(fl):
            return None
        ie = int(np.searchsorted(m, fixed_entry_min))
        if ie >= len(o) or c[max(ie - 1, 0)] <= O:
            return None
    else:
        if not len(fl):
            return None
        refv = np.full(len(c), O) if ref == "open" else np.cumsum((h + l + c) / 3 * v) / np.maximum(np.cumsum(v), 1)
        idx = np.arange(len(c))
        cand = np.flatnonzero((idx > fl[0]) & (c > refv) & (m <= deadline))
        if not len(cand):
            return None
        ie = int(cand[0]) + 1
        if ie >= len(o):
            return None
    P = o[ie]
    x, why = bar_exit(m, o, h, l, c, ie, P, P * 0.98, exit_min, nohigh=nohigh)
    fake = bool((c[ie: ie + 10] < O).any())
    return {"g": x / P - 1, "why": why, "t": int(m[ie]), "fake": fake}


def h021_one(aD, a1, treated=True, exit_min=629, trail=0, use_5min=False):
    mD, oD, hD, lD, cD, vD = aD
    m, o, h, l, c, v = a1
    HD, LD, CD = hD.max(), lD.min(), cD[-1]
    pos = (CD - LD) / (HD - LD) if HD > LD else 1.0
    if (treated and pos < 0.8) or (not treated and pos > 0.4):
        return None
    gap = o[0] / CD - 1
    if not (-0.02 <= gap <= 0.05):
        return None
    if use_5min:  # H-006 비교: 같은 날 첫 5분 레인지 고가 돌파(기준선만 바꿈)
        H5 = h[m < REG0 + 5].max()
        cand = np.flatnonzero((m >= REG0 + 5) & (m <= 629) & (c > H5))
        level = H5
    else:
        cvD, cv1 = np.cumsum(cD * vD), np.cumsum(c * v)
        cvD_at = cvD[np.clip(np.searchsorted(mD, m, side="right") - 1, 0, len(mD) - 1)]
        cand = np.flatnonzero((m <= 629) & (c > HD) & (cv1 >= 0.5 * cvD_at))
        level = HD
    if not len(cand):
        return None
    ie = int(cand[0]) + 1
    if ie >= len(o) or m[ie] > 629:
        return None
    P = o[ie]
    x, why = bar_exit(m, o, h, l, c, ie, P, level * 0.985, exit_min, trail_ticks=trail)
    return {"g": x / P - 1, "why": why, "t": int(m[ie])}


_ARR: dict = {}


def _np(d: pd.DataFrame, code: str):
    if code not in _ARR:
        _ARR[code] = tuple(d[k].to_numpy(float) for k in ("open", "high", "low", "close", "value_mw"))
    return _ARR[code]


def h022_daily(d: pd.DataFrame, i: int, depth=0.08, cooled=True, stop=0.035, tgt=0.08, hold=5, code=""):
    """H-022 변형 b(일봉) — D=i. 반환 (진입일 인덱스, 진입가, 총수익, 손절로 끝났나) 또는 None."""
    o, h, l, c, val = _np(d, code)
    n = len(o)
    P = h[i]
    for j in range(i + 1, min(i + 11, n)):
        level = P * (1 - depth)
        if l[j] <= level:
            fill = min(o[j], level)
            if fill > l[i]:
                cool = val[j - 1] <= val[i] * 0.4
                if cool == cooled:
                    return _hold_daily(o, h, l, c, j, fill, stop, tgt, hold)
        P = max(P, h[j])
    return None


def _hold_daily(o, h, l, c, j, P, stop, tgt, hold, entry_day_checked=False):
    S, T = P * (1 - stop), P * (1 + tgt)
    last = min(j + hold - 1, len(o) - 1)
    for k in range(j, last + 1):
        if k > j:
            if o[k] <= S:
                return j, P, o[k] / P - 1, True
            if o[k] >= T:
                return j, P, o[k] / P - 1, False
        if not (k == j and entry_day_checked) and l[k] <= S:
            return j, P, S / P - 1, True
        if k > j and h[k] >= T:
            return j, P, T / P - 1, False
    if j + hold - 1 > len(o) - 1:
        return None  # 자료 끝 — 다 못 들고 감
    return j, P, c[last] / P - 1, False


def part_d(prep: str, al: dict) -> dict:
    ev = pd.read_pickle(os.path.join(prep, "vl_ev.pkl"))
    fw = np.load(os.path.join(prep, "vl_fw.npy"))
    yr = ev.date.str[:4].astype(int).to_numpy()
    prev = ev.prev.to_numpy(float)
    h0, c0, l0 = fw[:, 0, 1], fw[:, 0, 3], fw[:, 0, 2]
    limit_close = (h0 / prev >= LIMIT_TOUCH) & (c0 >= h0 * 0.999)
    res = {}
    ledger = set(zip(ev.code, ev.date))
    # ---------------- 분봉 대상(2025-07~): 장부 사건 + 대조(나) 일반 +10% 급등(장부 아님·상한가 마감 아님)
    rec = ev.date.to_numpy() >= "20250701"
    need, pairs = {}, []
    for i in np.flatnonzero(rec):
        code, day = ev.code.iat[i], ev.date.iat[i]
        nx = next_day_map(al, code, day)
        if nx:
            need.setdefault(code, set()).update({day, nx})
            pairs.append((i, code, day, nx))
    ctrl = []
    for code, d in al.items():
        if code in BAD_CODES or not os.path.isfile(f"data/stocks/minute/{code}.csv"):
            continue
        dt = d.date.to_numpy()
        cl = d.close.to_numpy(float)
        hi = d.high.to_numpy(float)
        for j in np.flatnonzero(dt >= "20250701"):
            if j < 1 or j + 1 >= len(dt) or (code, dt[j]) in ledger:
                continue
            r = cl[j] / cl[j - 1] - 1
            if r >= 0.10 and not (hi[j] / cl[j - 1] >= LIMIT_TOUCH and cl[j] >= hi[j] * 0.999):
                ctrl.append((code, dt[j], dt[j + 1]))
                need.setdefault(code, set()).add(dt[j + 1])
    K = load_krx_needed(need)
    half_cut = "20260201"
    # ---------------- H-020
    def run020(**kw):
        out = []
        for i, code, day, nx in pairs:
            if limit_close[i]:
                continue
            a = _arrs(K, code, nx)
            if a is None:
                continue
            r = h020_one(a, **kw)
            if r:
                out.append({**r, "i": i, "h1": nx < half_cut})
        return pd.DataFrame(out)
    h20 = {"본규칙(−3%·시가 재탈환·10:15까지·손절−2%·10:30)": run020()}
    h20["변형a VWAP 재탈환"] = run020(ref="vwap")
    h20["변형b 털림 −5%"] = run020(flush=0.05)
    h20["변형c 진입 09:45까지"] = run020(deadline=585)
    h20["청산 15:19"] = run020(exit_min=919)
    h20["청산 고가 20분 못 넘기면"] = run020(exit_min=919, nohigh=20)
    base = h20["본규칙(−3%·시가 재탈환·10:15까지·손절−2%·10:30)"]
    tmed = int(base.t.median()) if len(base) else 600
    h20["대조(가) 털림 없이 시가 위 — 같은 시각 매수"] = run020(fixed_entry_min=tmed)
    cc = []
    for code, day, nx in ctrl:
        a = _arrs(K, code, nx)
        if a is None:
            continue
        r = h020_one(a)
        if r:
            cc.append({**r, "h1": nx < half_cut})
    h20["대조(나) 장부 아닌 +10% 급등 — 같은 규칙"] = pd.DataFrame(cc)
    res["H020"] = {k: {"all": cstats(v.g.to_numpy()) if len(v) else {"n": 0},
                       "h1": cstats(v.g[v.h1].to_numpy()) if len(v) else {"n": 0},
                       "h2": cstats(v.g[~v.h1].to_numpy()) if len(v) else {"n": 0},
                       "fake": float(v.fake.mean()) if len(v) and "fake" in v else np.nan,
                       "stop_rate": float((v.why == "stop").mean()) if len(v) else np.nan} for k, v in h20.items()}
    res["H020_n_ctrl_events"] = len(ctrl)
    # ---------------- H-021 (분봉)
    def run021(treated=True, **kw):
        out = []
        for i, code, day, nx in pairs:
            if limit_close[i] or ev.chg.iat[i] < 5:
                continue
            aD, a1 = K.get((code, day)), _arrs(K, code, nx)
            if aD is None or a1 is None:
                continue
            r = h021_one(aD, a1, treated=treated, **kw)
            if r:
                out.append({**r, "i": i, "h1": nx < half_cut})
        return pd.DataFrame(out)
    h21 = {"본규칙(고가마감·전일고가 돌파·손절 H×0.985·10:30)": run021()}
    h21["청산 15:19"] = run021(exit_min=919)
    h21["청산 D+1 종가"] = run021(exit_min=REG1)
    h21["변형b 고점−4호가 추적"] = run021(trail=4)
    h21["대조 윗꼬리 마감(위치≤0.4)"] = run021(treated=False)
    h21["H-006 비교: 같은 사건, 첫 5분 고가 돌파"] = run021(use_5min=True)
    res["H021"] = {k: {"all": cstats(v.g.to_numpy()) if len(v) else {"n": 0},
                       "h1": cstats(v.g[v.h1].to_numpy()) if len(v) else {"n": 0},
                       "h2": cstats(v.g[~v.h1].to_numpy()) if len(v) else {"n": 0},
                       "stop_rate": float((v.why == "stop").mean()) if len(v) else np.nan} for k, v in h21.items()}
    a_, b_ = h21["본규칙(고가마감·전일고가 돌파·손절 H×0.985·10:30)"], h21["H-006 비교: 같은 사건, 첫 5분 고가 돌파"]
    if len(a_) and len(b_):
        mm = a_.merge(b_, on="i", suffixes=("", "_5"))
        res["H021_overlap"] = {"n_both": len(mm), "corr": float(np.corrcoef(mm.g, mm.g_5)[0, 1]) if len(mm) > 2 else np.nan,
                               "mean_diff": float((mm.g - mm.g_5).mean() * 100) if len(mm) else np.nan}
    # H-021 변형a(일봉, 2020~): 고가마감(위치≥0.8)·등락≥5·상한가 마감 아님·갭 −2~+5% → 다음날 고가>H_D 면 max(시가,H_D) 체결 → 다음날 종가
    pos = ev.pos.to_numpy(float)
    o1, h1, c1 = fw[:, 1, 0], fw[:, 1, 1], fw[:, 1, 3]
    gap = o1 / c0 - 1
    basecond = (ev.chg.to_numpy() >= 5) & ~limit_close & (gap >= -0.02) & (gap <= 0.05) & (h1 > h0)
    ga = c1 / np.maximum(o1, h0) - 1
    res["H021a"] = split_report(np.where(basecond & (pos >= 0.8), ga, np.nan), yr)
    res["H021a_ctrl"] = split_report(np.where(basecond & (pos <= 0.4), ga, np.nan), yr)
    # ---------------- H-022 (일봉 변형 b, 2020~ 전 기간) — 장부 사건 / 대조(가) 거래 안 식음 / 대조(나) 장부 아닌 +10% 양봉
    pos_idx = {}
    for code, d in al.items():
        pos_idx[code] = {x: k for k, x in enumerate(d.date.to_numpy())}
    kq = None
    try:
        from studio.infrastructure.market_data import LocalMarketData
        kq = LocalMarketData().stock_info()["market"]
    except Exception:  # noqa: BLE001
        pass

    def run022(rows_iter, **kw):
        g, y, st = [], [], []
        for code, k in rows_iter:
            r = h022_daily(al[code], k, code=code, **kw)
            if r is None:
                continue
            g.append(r[2])
            y.append(int(al[code].date.iat[k][:4]))
            st.append(r[3])
        g, y, st = np.array(g), np.array(y), np.array(st)
        out = split_report(g, y)
        out["stop_rate"] = float(st.mean()) if len(st) else np.nan
        return out

    led = []
    for i in range(len(ev)):
        code, day = ev.code.iat[i], ev.date.iat[i]
        k = pos_idx.get(code, {}).get(day)
        if k is None or ev.chg.iat[i] < 10 or not fw[i, 0, 3] > fw[i, 0, 0]:
            continue
        led.append((code, k, i))
    L2 = [(c_, k_) for c_, k_, _ in led]
    h22 = {"본규칙(−8%·거래 식음·손절−3.5%·익절+8%·5일)": run022(L2)}
    h22["변형c 눌림 −5%"] = run022(L2, depth=0.05)
    h22["변형c 눌림 −12%"] = run022(L2, depth=0.12)
    if kq is not None:
        L2d = [(c_, k_) for c_, k_, i in led if kq.get(c_) == "코스닥" and np.isfinite(ev.vs52.iat[i]) and ev.vs52.iat[i] <= 0.10]
        h22["변형d(일부) 코스닥·52주 고가+10% 이내"] = run022(L2d)
    h22["대조(가) 거래 안 식은 눌림"] = run022(L2, cooled=False)
    ctrl22 = []
    for code, d in al.items():
        dt, o, c = d.date.to_numpy(), d.open.to_numpy(float), d.close.to_numpy(float)
        for k in range(1, len(dt) - 1):
            if dt[k] < "20200602" or (code, dt[k]) in ledger:
                continue
            if c[k] / c[k - 1] - 1 >= 0.10 and c[k] > o[k]:
                ctrl22.append((code, k))
    h22["대조(나) 장부 아닌 +10% 양봉"] = run022(ctrl22)
    res["H022"] = h22
    # H-022 분봉판(2025-07~, KRX 분봉): 첫 신호일(일봉 조건)의 −8% 도달이 09:00~10:30 안이면 다음 봉 시가 매수 → 그날 분봉으로 손절/익절 → 뒤 4일 일봉
    need2, plan = {}, []
    for code, k, i in led:
        d = al[code]
        if d.date.iat[k] < "20250701":
            continue
        o, h, l, c, val = (d[x].to_numpy(float) for x in ("open", "high", "low", "close", "value_mw"))
        P = h[k]
        for j in range(k + 1, min(k + 11, len(o))):
            level = P * 0.92
            if l[j] <= level and min(o[j], level) > l[k] and val[j - 1] <= val[k] * 0.4:
                plan.append((code, k, j, level))
                need2.setdefault(code, set()).add(d.date.iat[j])
                break
            P = max(P, h[j])
    K2 = load_krx_needed(need2)
    gm, st, n_late = [], [], 0
    for code, k, j, level in plan:
        d = al[code]
        a = _arrs(K2, code, d.date.iat[j])
        if a is None:
            continue
        m, o, h, l, c, v = a
        hit = np.flatnonzero((m < 630) & (l <= level))
        if not len(hit) or hit[0] + 1 >= len(o):
            n_late += 1
            continue
        ie = int(hit[0]) + 1
        P = o[ie]
        S, T = P * 0.965, P * 1.08
        x, stp = None, False
        for t in range(ie, len(o)):
            if t > ie and o[t] <= S:
                x, stp = o[t], True
                break
            if l[t] <= S:
                x, stp = S, True
                break
            if h[t] >= T:
                x = T
                break
        if x is None:  # 그날 못 끝냄 → 뒤 4일 일봉(시가 갭·손절 먼저)
            oo, hh, ll, cc = (d[q].to_numpy(float) for q in ("open", "high", "low", "close"))
            r = _hold_daily(oo, hh, ll, cc, j, P, 0.035, 0.08, 5, entry_day_checked=True)
            if r is None:
                continue
            gm.append(r[2])
            st.append(r[3])
        else:
            gm.append(x / P - 1)
            st.append(stp)
    res["H022_minute"] = {"stats": cstats(np.array(gm)), "stop_rate": float(np.mean(st)) if st else np.nan,
                          "n_plan": len(plan), "n_after_1030": n_late}
    return res


def print_part2(C: dict, D: dict) -> None:
    print("\n========== 2차 C. 상한가 하룻밤 — 실제로 살 수 있는 판(통합 일봉) ==========")
    print(f"상한가 닿은 신고일 {C['n_touch']:,}건(그중 상한가 마감 {C['n_locked']:,})")
    for k, lab in (("touch_all", "① 닿은 날 전부, 상한가에 첫 닿을 때 샀다 → 다음날 시가"), ("touch_locked", "   그중 상한가 마감"),
                   ("touch_released", "   그중 상한가에서 풀린 날"),
                   ("strong_close_eq_high", "③ 상한가 못 간 강한 마감(등락 20~29%, 종가=고가)"), ("strong_pos95", "③' 등락 20~29%, 종가가 범위 95% 위"),
                   ("strong_all", "③'' 등락 20~29% 전부(참고)")):
        r = C[k]
        print(f"{lab}\n   학습 {cfmt(r['tr'])}\n   검증 {cfmt(r['te'])}\n   연도별 비용 전 {r['years']}")
    mt = C["minute"]
    print(f"\n② KRX 분봉(2025-07~): 상한가 닿은 장부 사건 {C['minute_n_target']}건 중 분봉 쓸 수 있는 {len(mt)}건")
    if len(mt):
        t = mt[mt.krx_touch]
        print(f"   KRX 정규장에서 상한가 닿음 {len(t)} / 정규장엔 안 닿음(NXT 장후 등) {int((~mt.krx_touch).sum())}")
        b = pd.cut(t.t, [0, 600, 720, 840, 2000], right=False, labels=["10시 전", "10~12시", "12~14시", "14시 뒤"])
        for lab, g in t.groupby(b, observed=True):
            print(f"   첫 닿음 {lab}: {cfmt(cstats(g.g_krx.to_numpy()))} (KRX 09:00 시가 매도) · 마감까지 묶임 {g.locked.mean() * 100:.0f}%"
                  f" · 닿은 뒤 상한가 체결 대금 중앙 {g.lim_val_lo.median():.0f}~{g.lim_val_hi.median():.0f}억")
        print(f"   전체: {cfmt(cstats(t.g_krx.to_numpy()))} (KRX 09:00 시가) | 통합 시가로는 {cfmt(cstats(t.g_al.to_numpy()))}")
        print(f"   닿는 순간 KRX 누적 대금이 이미 직전 1년 최대를 넘었나(장부 종목인 걸 알 수 있었나): {t.known.mean() * 100:.0f}%")
        for lab, g in t.groupby(t.known):
            print(f"      {'알 수 있었음' if lab else '아직 모름'}: {cfmt(cstats(g.g_krx.to_numpy()))}")
    print("\n========== 2차 D. 가설 카드 ==========")
    print("[H-020] 신고 다음날 −3% 털림 뒤 시가 재탈환 (KRX 분봉, 2025-07~) — all / 앞 반쪽(~2026-01) / 뒤 반쪽")
    for k, r in D["H020"].items():
        print(f" {k}\n   전체 {cfmt(r['all'])} · 손절로 끝 {r['stop_rate'] * 100:.0f}% · 재탈환 뒤 10분 안 시가 아래 {r['fake'] * 100:.0f}%")
        print(f"   앞 {cfmt(r['h1'])}\n   뒤 {cfmt(r['h2'])}")
    print(f"   (대조(나) 후보 일반 +10% 급등 {D['H020_n_ctrl_events']:,}건)")
    print("[H-021] 고가 마감 신고 → 다음날 전일 고가 돌파 (KRX 분봉, 2025-07~)")
    for k, r in D["H021"].items():
        print(f" {k}\n   전체 {cfmt(r['all'])} · 손절로 끝 {r['stop_rate'] * 100:.0f}%\n   앞 {cfmt(r['h1'])}\n   뒤 {cfmt(r['h2'])}")
    if "H021_overlap" in D:
        print(f"   H-006 겹침: 둘 다 진입한 사건 {D['H021_overlap']['n_both']} · 결과 상관 {D['H021_overlap']['corr']:.2f} · 평균 차이 {D['H021_overlap']['mean_diff']:+.2f}%p")
    for k, lab in (("H021a", "[H-021 변형a 일봉 2020~] 고가 마감"), ("H021a_ctrl", "   대조 윗꼬리 마감")):
        r = D[k]
        print(f"{lab}\n   학습 {cfmt(r['tr'])}\n   검증 {cfmt(r['te'])}\n   연도별 비용 전 {r['years']}")
    print("[H-022] 신고 뒤 거래 식은 첫 −8% 눌림 (일봉 변형 b, 2020~)")
    for k, r in D["H022"].items():
        print(f" {k} · 손절로 끝 {r['stop_rate'] * 100:.0f}%\n   학습 {cfmt(r['tr'])}\n   검증 {cfmt(r['te'])}\n   연도별 비용 전 {r['years']}")
    r = D["H022_minute"]
    print(f"[H-022 분봉판 KRX 2025-07~] 계획 {r['n_plan']} · 10:30 뒤에 닿아 못 산 {r['n_after_1030']} · {cfmt(r['stats'])} · 손절로 끝 {r['stop_rate'] * 100:.0f}%")


# ====================================================================== 3차 (lead 10-14 3차 지시) — 좋은 눌림 vs 나쁜 눌림
# 사용자: "고점이 많이 나온 종목은 눌림에서 사서 어느 정도 수익 낼 수 있다, 난 구별이 된다" → 평균 규칙이 아니라 '가르는 조건'을 찾는다.
DEPTHS = (0.08, 0.12, 0.15, 0.20, 0.25)
E_TGTS = (0.07, 0.10, 0.15, 0.20)
E_STOPS = ("none", "D저가", "-10%", "-15%")
E_HOLDS = (5, 10, 15)


def market_proxy(al: dict) -> dict:
    """시장 국면 대용 — 지수 일봉이 2021-07 부터라 학습 앞부분이 비어서, 통합 일봉 전 종목 등가 평균(일 수익 중앙값 누적)으로 만든다.
    반환 {시장: Series(날짜→ 대용지수가 20일선 위인가)} — 시장 = 거래소/코스닥/전체."""
    try:
        from studio.infrastructure.market_data import LocalMarketData
        mk = LocalMarketData().stock_info()["market"]
    except Exception:  # noqa: BLE001
        mk = pd.Series(dtype=str)
    parts = {"거래소": [], "코스닥": [], "전체": []}
    for code, d in al.items():
        r = pd.Series((d.close / d.close.shift(1) - 1).to_numpy(), index=d.date.to_numpy()).clip(-0.3, 0.3)
        parts["전체"].append(r)
        if mk.get(code) in parts:
            parts[mk.get(code)].append(r)
    out = {}
    for k, rs in parts.items():
        if not rs:
            continue
        med = pd.concat(rs, axis=1).median(axis=1).sort_index()
        lvl = (1 + med.fillna(0)).cumprod()
        out[k] = (lvl > lvl.rolling(20).mean())
    out["_mk"] = mk
    return out


def e_candidates(prep: str, al: dict) -> pd.DataFrame:
    """신고 뒤 1~15일, 그날까지 고점 대비 −p 첫 도달 지정가 매수 후보 + 진입 때 알 수 있는 특징 + 결과(10일 안 +10% 먼저 = 성공)."""
    ev = pd.read_pickle(os.path.join(prep, "vl_ev.pkl"))
    mp = market_proxy(al)
    mk = mp["_mk"]
    n_same = ev.groupby("date").size()
    rows = []
    for i, r in enumerate(ev.itertuples(index=False)):
        d = al.get(r.code)
        if d is None:
            continue
        o, h, l, c, val = _np(d, r.code)
        dates = d.date.to_numpy()
        k = int(np.searchsorted(dates, r.date))
        if k >= len(dates) or dates[k] != r.date or k < 20:
            continue
        reg_s = mp[mk.get(r.code)] if mk.get(r.code) in ("거래소", "코스닥") and mk.get(r.code) in mp else mp["전체"]
        for p in DEPTHS:
            P, pk_day = h[k], k
            for t in range(1, 16):
                j = k + t
                if j >= len(o):
                    break
                lim = P * (1 - p)
                if l[j] <= lim:
                    buy = min(o[j], lim)
                    seg = slice(k + 1, j)
                    body = (o[k] + c[k]) / 2
                    cj = c[max(j - 20, 0): j]
                    rng = (h[k + 1:j] - l[k + 1:j])
                    lw = np.where(rng > 0, (np.minimum(o[k + 1:j], c[k + 1:j]) - l[k + 1:j]) / np.where(rng > 0, rng, 1), 0)
                    reg = reg_s.get(dates[j - 1], np.nan)
                    rows.append({
                        "ev": i, "code": r.code, "D": r.date, "entry": dates[j], "yr": int(r.date[:4]), "depth": p, "t": t, "j": j, "k": k, "buy": buy,
                        "rel_c0": buy / c[k] - 1, "rel_body": buy / body - 1, "rel_o0": buy / o[k] - 1, "rel_l0": buy / l[k] - 1,
                        "runup": P / c[k] - 1, "since_peak": j - 1 - pk_day, "v_vs_peak": val[j - 1] / val[pk_day] if val[pk_day] > 0 else np.nan,
                        "v_vs_D": val[j - 1] / val[k] if val[k] > 0 else np.nan,
                        "ma5": buy / c[j - 5:j].mean() - 1, "ma10": buy / c[j - 10:j].mean() - 1, "ma20": buy / cj.mean() - 1,
                        "n_down": int((c[seg] < o[seg]).sum()), "n_lowwick": int((lw >= 0.5).sum()),
                        "cnt": r.cnt, "chg0": r.chg, "val0": r.val, "mult0": r.mult, "x20": r.x20, "pos0": r.pos,
                        "is52": float(r.vs52 > 0) if r.vs52 == r.vs52 else np.nan, "mkt_up": float(reg) if reg == reg else np.nan,
                        "n_same": int(n_same.get(r.date, 0)), "kosdaq": float(mk.get(r.code) == "코스닥"),
                    })
                    break
                if h[j] > P:
                    P, pk_day = h[j], j
    E = pd.DataFrame(rows)
    E = E.drop_duplicates(["code", "entry", "depth"], keep="first").reset_index(drop=True)
    # 결과 표시(라벨): 진입 뒤 10일 안 +10% 먼저 = 성공, −10% 먼저 또는 10일 뒤 손해 = 실패(같은 날 둘 다면 실패 — 보수적)
    lab, g10 = [], []
    for e_ in E.itertuples(index=False):
        o, h, l, c, _ = _ARR[e_.code]
        res = _exit_daily(o, h, l, c, e_.j, e_.buy, 0.10, 0.10, 10)
        lab.append(res[1])
        g10.append(res[0])
    E["label"] = lab  # 'win' | 'lose' | 'flat'(둘 다 안 닿고 10일 뒤 본전 이상)
    E["succ"] = (E.label == "win").astype(int)
    return E


def _exit_daily(o, h, l, c, j, P, tgt, stop, hold, stop_price=None, at_close=False):
    """j 날 P 에 산 뒤: 들어간 날은 손절만(보수적), 그 뒤 시가 갭·손절 먼저·익절, hold 일 뒤 종가. 반환 (총수익, 'win'/'lose'/'flat'/'time').
    at_close=True: j 날 종가에 샀다 — 그날 남은 움직임이 없으니 들어간 날 검사는 건너뛴다."""
    S = stop_price if stop_price is not None else (P * (1 - stop) if stop else -np.inf)
    T = P * (1 + tgt) if tgt else np.inf
    n = len(o)
    if not at_close and l[j] <= S:
        return S / P - 1, "lose"
    for k in range(j + 1, min(j + hold, n - 1) + 1):
        if o[k] <= S:
            return o[k] / P - 1, "lose"
        if o[k] >= T:
            return o[k] / P - 1, "win"
        if l[k] <= S:
            return S / P - 1, "lose"
        if h[k] >= T:
            return T / P - 1, "win"
    last = min(j + hold, n - 1)
    g = c[last] / P - 1
    return g, ("flat" if g >= 0 else "lose")


E_FEATS = ["depth", "t", "rel_c0", "rel_body", "rel_o0", "rel_l0", "runup", "since_peak", "v_vs_peak", "v_vs_D", "ma5", "ma10", "ma20",
           "n_down", "n_lowwick", "cnt", "chg0", "val0", "mult0", "x20", "pos0", "is52", "mkt_up", "n_same", "kosdaq"]


def e_returns(E: pd.DataFrame, tgt, stop, hold) -> np.ndarray:
    out = np.full(len(E), np.nan)
    for n_, e_ in enumerate(E.itertuples(index=False)):
        o, h, l, c, _ = _ARR[e_.code]
        if stop == "D저가":
            sp = l[e_.k]
            if e_.buy <= sp:
                continue  # 이미 신고일 저가 아래에서 사는 경우 — 이 손절 규칙엔 해당 없음
            out[n_] = _exit_daily(o, h, l, c, e_.j, e_.buy, tgt, None, hold, stop_price=sp)[0]
        else:
            s = {"none": None, "-10%": 0.10, "-15%": 0.15}[stop]
            out[n_] = _exit_daily(o, h, l, c, e_.j, e_.buy, tgt, s, hold)[0]
    return out


def tail5(x):
    x = x[np.isfinite(x)]
    return float(np.percentile(x, 5) * 100) if len(x) else np.nan


def rule_search(E: pd.DataFrame, ret: np.ndarray, min_n=150, beam=25, max_k=3) -> list[dict]:
    """학습(2020~2023)만으로: 조건(특징 ≥/≤ 학습 분위 20·40·60·80) 최대 3개 묶음 — 빔 탐색. 점수 = 학습 평균(비용 0.25% 뒤),
    단 학습 4년 중 3년 이상 플러스·건수 ≥ min_n. 검증은 고른 뒤 그대로 잰다."""
    tr = (E.yr <= 2023).to_numpy()
    yrs = E.yr.to_numpy()
    net = ret - 0.0025
    ok = np.isfinite(net)
    atoms = []
    for f in E_FEATS:
        x = E[f].to_numpy(float)
        fin = np.isfinite(x) & tr
        if fin.sum() < min_n:
            continue
        qs = np.unique(np.round(np.nanquantile(x[fin], [0.2, 0.4, 0.6, 0.8]), 4))
        for q in qs:
            for side in (">=", "<="):
                m = np.isfinite(x) & ((x >= q) if side == ">=" else (x <= q))
                atoms.append(((f, side, float(q)), m))

    def score(m):
        mt = m & tr & ok
        if mt.sum() < min_n:
            return None
        yr_pos = sum(np.nanmean(net[m & ok & (yrs == y)]) > 0 for y in range(2020, 2024) if (m & ok & (yrs == y)).sum() >= 10)
        if yr_pos < 3:
            return None
        return float(net[mt].mean())
    level = [((), np.ones(len(E), bool))]
    found = []
    for _ in range(max_k):
        nxt = []
        for conds, m0 in level:
            used = {c[0] for c in conds}
            for a, ma in atoms:
                if a[0] in used:
                    continue
                m = m0 & ma
                s = score(m)
                if s is not None:
                    nxt.append((s, tuple(sorted(conds + (a,))), m))
        uniq = {}
        for s, conds, m in nxt:
            if conds not in uniq or uniq[conds][0] < s:
                uniq[conds] = (s, m)
        best = sorted(((s, c, m) for c, (s, m) in uniq.items()), key=lambda z: -z[0])[:beam]
        found += best
        level = [(c, m) for s, c, m in best]
    out = []
    for s, conds, m in sorted(found, key=lambda z: -z[0])[:15]:
        out.append({"conds": conds, "tr_mean": s, "m": m})
    return out


def describe(E, ret, m, label="") -> dict:
    tr, te = (E.yr <= 2023).to_numpy(), (E.yr >= 2024).to_numpy()
    out = {}
    for nm, mm in (("tr", m & tr), ("te", m & te)):
        g = ret[mm]
        s = cstats(g)
        s["tail5"] = tail5(g - 0.0025)
        s["succ"] = float(E.succ.to_numpy()[mm].mean() * 100) if mm.sum() else np.nan
        out[nm] = s
    out["years"] = by_year(np.where(m, ret, np.nan), E.yr.to_numpy())
    return out


def part_e(prep: str, al: dict) -> dict:
    E = e_candidates(prep, al)
    res = {"n": len(E), "by_depth": {}}
    base_ret = e_returns(E, 0.10, "none", 10)
    E["r_base"] = base_ret
    tr = (E.yr <= 2023).to_numpy()
    for p in DEPTHS:
        m = (E.depth == p).to_numpy()
        res["by_depth"][p] = describe(E, base_ret, m)
    # 특징 하나씩: 성공 비율·평균을 위/아래 절반으로(학습) — 어떤 특징이 가르나 감 잡기
    uni = []
    for f in E_FEATS:
        x = E[f].to_numpy(float)
        fin = np.isfinite(x)
        if (fin & tr).sum() < 300:
            continue
        q = np.nanmedian(x[fin & tr])
        hi, lo = fin & (x > q), fin & (x <= q)
        a_tr = (np.nanmean(base_ret[hi & tr]) - np.nanmean(base_ret[lo & tr])) * 100
        a_te = (np.nanmean(base_ret[hi & ~tr]) - np.nanmean(base_ret[lo & ~tr])) * 100
        s_tr = (E.succ[hi & tr].mean() - E.succ[lo & tr].mean()) * 100
        s_te = (E.succ[hi & ~tr].mean() - E.succ[lo & ~tr].mean()) * 100
        uni.append({"f": f, "median": q, "diff_mean_tr": a_tr, "diff_mean_te": a_te, "diff_succ_tr": s_tr, "diff_succ_te": s_te})
    res["univariate"] = pd.DataFrame(uni).sort_values("diff_mean_tr", key=abs, ascending=False)
    # 규칙 찾기(학습만) → 검증 그대로
    rules = rule_search(E, base_ret)
    res["rules"] = [{"conds": r["conds"], "tr_mean": r["tr_mean"], **describe(E, base_ret, r["m"])} for r in rules]
    # 1위 규칙의 청산 격자(이웃 칸)
    if rules:
        m = rules[0]["m"]
        grid = []
        for tgt, stop, hold in itertools.product(E_TGTS, E_STOPS, E_HOLDS):
            rr = e_returns(E[m].reset_index(drop=True), tgt, stop, hold)
            Em = E[m].reset_index(drop=True)
            d = describe(Em, rr, np.ones(len(Em), bool))
            grid.append({"tgt": tgt, "stop": stop, "hold": hold, "tr_n": d["tr"]["n"], "tr_net": d["tr"].get("0.25", {}).get("mean", np.nan),
                         "tr_win": d["tr"].get("0.25", {}).get("win", np.nan), "te_n": d["te"]["n"], "te_net": d["te"].get("0.25", {}).get("mean", np.nan),
                         "te_med": d["te"].get("0.25", {}).get("med", np.nan), "te_win": d["te"].get("0.25", {}).get("win", np.nan),
                         "te_net43": d["te"].get("0.43", {}).get("mean", np.nan), "te_tail5": d["te"]["tail5"]})
        res["exit_grid"] = pd.DataFrame(grid)
    # 깊이 3 나무(학습) — 성공(+10% 먼저) 예측, 잎별 검증
    try:
        from sklearn.tree import DecisionTreeClassifier, export_text
        X = E[E_FEATS].astype(float)
        Xf = X.fillna(X[tr].median())
        tree = DecisionTreeClassifier(max_depth=3, min_samples_leaf=200, random_state=0).fit(Xf[tr], E.succ[tr])
        leaf = tree.apply(Xf)
        res["tree_text"] = export_text(tree, feature_names=E_FEATS, decimals=3)
        lv = []
        for lf in np.unique(leaf):
            m = leaf == lf
            d = describe(E, base_ret, m)
            lv.append({"leaf": int(lf), "tr_n": d["tr"]["n"], "tr_succ": d["tr"]["succ"], "tr_net": d["tr"].get("0.25", {}).get("mean", np.nan),
                       "te_n": d["te"]["n"], "te_succ": d["te"]["succ"], "te_net": d["te"].get("0.25", {}).get("mean", np.nan),
                       "te_med": d["te"].get("0.25", {}).get("med", np.nan)})
        res["tree_leaves"] = pd.DataFrame(lv).sort_values("tr_net", ascending=False)
    except Exception as ex:  # noqa: BLE001
        res["tree_text"] = f"나무 실패: {ex}"
    E.to_pickle(os.path.join(prep, "vl_pull_candidates.pkl"))
    return res


def part_f(prep: str, al: dict) -> dict:
    """뒤 20일 고점 +30% 이상 종목(약 26%) vs 아닌 종목 — 신고일과 다음 1~3일 모습 비교(미리 알아볼 신호가 있나)."""
    ev = pd.read_pickle(os.path.join(prep, "vl_ev.pkl"))
    fw = np.load(os.path.join(prep, "vl_fw.npy"))
    O, H, L, C = (fw[:, :, q] for q in range(4))
    c0 = C[:, 0]
    big = (np.nanmax(H[:, 1:21], axis=1) / c0 - 1) >= 0.30
    yr = ev.date.str[:4].astype(int).to_numpy()
    tr = yr <= 2023
    mp = market_proxy(al)
    mk = mp["_mk"]
    n_same = ev.groupby("date").size()
    F = pd.DataFrame({"chg0": ev.chg, "pos0": ev.pos, "val0": ev.val, "mult0": ev.mult, "x20": ev.x20, "cnt": ev.cnt, "vs52": ev.vs52, "vs20": ev.vs20,
                      "n_same": ev.date.map(n_same).to_numpy(), "kosdaq": (ev.code.map(mk) == "코스닥").astype(float)})
    F["mkt_up"] = [float((mp[mk.get(c_)] if mk.get(c_) in ("거래소", "코스닥") and mk.get(c_) in mp else mp["전체"]).get(d_, np.nan))
                   for c_, d_ in zip(ev.code, ev.date)]
    vals = []
    for c_, d_ in zip(ev.code, ev.date):
        d = al.get(c_)
        if d is None:
            vals.append([np.nan] * 3)
            continue
        dt = d.date.to_numpy()
        k = int(np.searchsorted(dt, d_))
        v = d.value_mw.to_numpy(float)
        vals.append([v[k + q] / v[k] if (k + q < len(v) and dt[k] == d_ and v[k] > 0) else np.nan for q in (1, 2, 3)])
    vals = np.array(vals)
    for q in (1, 2, 3):
        F[f"gap{q}"] = O[:, q] / C[:, q - 1] - 1
        F[f"ret{q}"] = C[:, q] / c0 - 1
        rg = H[:, q] - L[:, q]
        F[f"pos{q}"] = np.where(rg > 0, (C[:, q] - L[:, q]) / np.where(rg > 0, rg, 1), 1)
        F[f"vkeep{q}"] = vals[:, q - 1]
    # 그 뒤에 사도 늦지 않나 — q 일째 종가에 산다고 보고 그 뒤 고점(q+1~20일)이 +20% 이상
    late = {q: (np.nanmax(H[:, q + 1:21], axis=1) / C[:, q] - 1) >= 0.20 for q in (1, 2, 3)}
    rows = []
    for f in F.columns:
        x = F[f].to_numpy(float)
        fin = np.isfinite(x)
        r = {"f": f, "큰고점_중앙": np.nanmedian(x[big & fin]), "나머지_중앙": np.nanmedian(x[~big & fin])}
        for nm, mm in (("tr", tr), ("te", ~tr)):
            try:
                from sklearn.metrics import roc_auc_score
                r[f"auc_{nm}"] = roc_auc_score(big[mm & fin], x[mm & fin])
            except Exception:  # noqa: BLE001
                r[f"auc_{nm}"] = np.nan
        rows.append(r)
    res = {"base_rate": {"all": float(big.mean() * 100), "tr": float(big[tr].mean() * 100), "te": float(big[~tr].mean() * 100)},
           "table": pd.DataFrame(rows)}
    # 'q일째 종가에 사도 늦지 않나'를 다음날 특징으로 가를 수 있나(누수 없는 판)
    late_rows = []
    for q in (1, 2, 3):
        y = late[q]
        for f in [f"gap{q}", f"ret{q}", f"pos{q}", f"vkeep{q}", "chg0", "pos0", "cnt", "mult0"]:
            x = F[f].to_numpy(float)
            fin = np.isfinite(x)
            try:
                from sklearn.metrics import roc_auc_score
                a1, a2 = roc_auc_score(y[tr & fin], x[tr & fin]), roc_auc_score(y[~tr & fin], x[~tr & fin])
            except Exception:  # noqa: BLE001
                a1 = a2 = np.nan
            late_rows.append({"q": q, "f": f, "base_tr": y[tr].mean() * 100, "base_te": y[~tr].mean() * 100, "auc_tr": a1, "auc_te": a2})
    res["late"] = pd.DataFrame(late_rows)
    return res


def print_part3(Ex: dict, Fx: dict) -> None:
    pd.set_option("display.width", 250)
    print(f"\n========== 3차 E. 좋은 눌림 vs 나쁜 눌림 — 후보 {Ex['n']:,}건(종목·진입일·깊이 중복 제거) ==========")
    print("[깊이별 기본(손절 없음·+10% 익절·10일)] 학습 / 검증 — 성공 = 10일 안 +10% 먼저")
    for p, d in Ex["by_depth"].items():
        print(f" 고점 −{int(p * 100)}%: 학습 {cfmt(d['tr'])} 성공 {d['tr']['succ']:.0f}% 최악5% {d['tr']['tail5']:.1f}\n            검증 {cfmt(d['te'])} 성공 {d['te']['succ']:.0f}% 최악5% {d['te']['tail5']:.1f}")
    print("\n[특징 하나씩 — 학습 중앙값 위 vs 아래의 차이(평균 %p·성공 %p), 학습/검증]")
    print(Ex["univariate"].round(2).to_string(index=False))
    print("\n[규칙(조건 ≤3, 학습만으로 고름) 상위 — 검증 그대로]")
    for r in Ex["rules"][:10]:
        c = " 그리고 ".join(f"{f} {s} {q:.3g}" for f, s, q in r["conds"])
        print(f" {c}\n   학습 {cfmt(r['tr'])} 성공 {r['tr']['succ']:.0f}% 최악5% {r['tr']['tail5']:.1f}\n   검증 {cfmt(r['te'])} 성공 {r['te']['succ']:.0f}% 최악5% {r['te']['tail5']:.1f}\n   연도별 비용 전 {r['years']}")
    if "exit_grid" in Ex:
        print("\n[1위 규칙의 청산 격자 — 학습 평균 순]")
        print(Ex["exit_grid"].sort_values("tr_net", ascending=False).round(2).to_string(index=False))
    print("\n[깊이 3 나무(학습)]")
    print(Ex.get("tree_text"))
    if "tree_leaves" in Ex:
        print(Ex["tree_leaves"].round(2).to_string(index=False))
    print(f"\n========== 3차 F. 뒤 20일 고점 +30% 이상 종목(전체 {Fx['base_rate']['all']:.0f}%, 학습 {Fx['base_rate']['tr']:.0f}% · 검증 {Fx['base_rate']['te']:.0f}%) vs 나머지 ==========")
    print("(auc 0.5 = 못 가름, 0.6 이상이면 약하게라도 가름. gap/ret/pos/vkeep 1~3 은 결과 기간과 겹친다 — 그대로는 '미리'가 아님)")
    print(Fx["table"].round(3).to_string(index=False))
    print("\n[q일째 종가에 사도 그 뒤 +20% 고점이 나나 — 그날까지 본 것만으로 가르기(누수 없음)]")
    print(Fx["late"].round(3).to_string(index=False))


# ====================================================================== 4차 (lead 10-14 4차 지시) — 3차 추천 굳히기·테마 묶음·식은 뒤 사기
G_POS, G_X20, G_VD, G_DEPTH, G_TGT, G_HOLD = 0.8, 20.0, 0.6, 0.20, 0.10, 10


def pull_trade(o, h, l, c, val, k, depth=G_DEPTH, vmin=G_VD, maxday=15, tgt=G_TGT, hold=G_HOLD):
    """3차 E 와 같은 뜻: 신고일 k 뒤 1~maxday 일, '전날까지 최고가' 대비 −depth 첫 닿음에 지정가(시가가 더 낮으면 시가).
    첫 닿음날 전날 대금 < 신고일 대금×vmin 이면 그 사건은 버린다(다음 닿음 안 기다림).
    반환 None | dict(j, buy, ret(비용 전), xk(나온 날), why('익절'/'기간'/'진행 중'))."""
    n = len(o)
    P = h[k]
    for j in range(k + 1, min(k + maxday, n - 1) + 1):
        lim = P * (1 - depth)
        if l[j] <= lim:
            if not (val[k] > 0 and val[j - 1] >= val[k] * vmin):
                return None
            buy = min(o[j], lim)
            T = buy * (1 + tgt)
            for x in range(j + 1, min(j + hold, n - 1) + 1):
                if o[x] >= T:
                    return {"j": j, "buy": buy, "ret": o[x] / buy - 1, "xk": x, "why": "익절"}
                if h[x] >= T:
                    return {"j": j, "buy": buy, "ret": tgt, "xk": x, "why": "익절"}
            last = min(j + hold, n - 1)
            return {"j": j, "buy": buy, "ret": c[last] / buy - 1, "xk": last, "why": "기간" if j + hold <= n - 1 else "진행 중"}
        P = max(P, h[j])
    return None


def g_trades(ev: pd.DataFrame, al: dict, mask: np.ndarray) -> pd.DataFrame:
    rows = []
    for i in np.flatnonzero(mask):
        r = ev.iloc[i]
        d = al.get(r.code)
        if d is None:
            continue
        o, h, l, c, val = _np(d, r.code)
        dt = d.date.to_numpy()
        k = int(np.searchsorted(dt, r.date))
        if k >= len(dt) or dt[k] != r.date or k < 20:
            continue
        t = pull_trade(o, h, l, c, val, k)
        if t:
            rows.append({"ev": i, "code": r.code, "name": r.get("name", ""), "D": r.date, "entry": dt[t["j"]], "exit": dt[t["xk"]], "buy": t["buy"],
                         "ret": t["ret"], "why": t["why"], "j": t["j"], "xk": t["xk"], "yr": int(r.date[:4]), "c0": c[k]})
    T = pd.DataFrame(rows)
    return T.drop_duplicates(["code", "entry"]).reset_index(drop=True) if len(T) else T


def waves(T: pd.DataFrame) -> pd.DataFrame:
    """같은 종목에서 앞 거래를 아직 들고 있는 동안 또 걸린 건은 같은 파동 → 앞 것 하나만(실제로 한 번만 살 수 있다)."""
    keep = []
    for _, g in T.sort_values(["code", "j"]).groupby("code"):
        last_x = -1
        for idx, r in g.iterrows():
            if r.j > last_x:
                keep.append(idx)
                last_x = r.xk
    return T.loc[sorted(keep)]


def slot_filter(T: pd.DataFrame, slots: int) -> pd.DataFrame:
    """칸(slots) 수만큼만 동시에 든다 — 산 날 순서대로, 빈 칸 없으면 그 거래는 건너뜀."""
    keep, busy = [], []
    for idx, r in T.sort_values(["entry", "code"]).iterrows():
        busy = [x for x in busy if x >= r.entry]  # 판 날 = 그날 칸이 비는 것으로(어림)
        if len(busy) < slots:
            keep.append(idx)
            busy.append(r.exit)
    return T.loc[keep]


def account_curve(T: pd.DataFrame, al: dict, cost=0.0025, K: int | None = None) -> dict:
    """종목당 같은 금액(계좌 ÷ K, K 없으면 최대 동시 보유 수), 날마다 종가로 평가, 복리 없이 더함(어림)."""
    span = []
    for r in T.itertuples(index=False):
        dt = al[r.code].date.to_numpy()
        span.append(dt[r.j:r.xk + 1])
    cnt = pd.Series(np.concatenate(span)).value_counts() if span else pd.Series(dtype=int)
    K = K or (int(cnt.max()) if len(cnt) else 1)
    inc = {}
    for r, sp in zip(T.itertuples(index=False), span):
        c = _ARR[r.code][3]
        prev = r.buy
        for q, day in enumerate(sp):
            px = r.buy * (1 + r.ret) if q == len(sp) - 1 else c[r.j + q]
            v = (px - prev) / r.buy - (cost if q == len(sp) - 1 else 0)
            inc[day] = inc.get(day, 0) + v / K
            prev = px
    s = pd.Series(inc).sort_index()
    eq = 1 + s.cumsum()
    dd = eq / eq.cummax() - 1
    yrs = {}
    for y in sorted({d[:4] for d in s.index}):
        sy = s[s.index.str[:4] == y]
        ey = 1 + sy.cumsum()
        yrs[int(y)] = {"ret": float(sy.sum() * 100), "mdd": float((ey / np.maximum.accumulate(np.r_[1.0, ey.to_numpy()])[1:] - 1).min() * 100),
                       "n": int((T.entry.str[:4] == y).sum())}
    return {"K": K, "mean_hold": float(cnt.mean()) if len(cnt) else 0, "years": yrs, "mdd": float(dd.min() * 100), "total": float(s.sum() * 100)}


def surge_events(al: dict, ledger: set) -> pd.DataFrame:
    """장부가 아닌 일반 급등: +10% 이상·양봉·종가 위치 ≥ 0.8·대금 ≥ 평소(앞 20일 평균) 20배."""
    rows = []
    for code, d in al.items():
        o, h, l, c, val = _np(d, code)
        if len(c) < 30:
            continue
        prev = np.r_[np.nan, c[:-1]]
        chg = c / prev - 1
        avg = pd.Series(val).shift(1).rolling(20).mean().to_numpy()
        rng = h - l
        pos = np.where(rng > 0, (c - l) / np.where(rng > 0, rng, 1), 1)
        with np.errstate(invalid="ignore", divide="ignore"):
            m = (chg >= 0.10) & (c > o) & (pos >= G_POS) & (val >= avg * G_X20) & (avg > 0)
        dt = d.date.to_numpy()
        for k in np.flatnonzero(m):
            if dt[k] >= "20200602" and (code, dt[k]) not in ledger:
                rows.append({"date": dt[k], "code": code, "name": "", "val": val[k] / 100, "x20": val[k] / avg[k], "chg": chg[k] * 100, "pos": pos[k]})
    return pd.DataFrame(rows)


def tstat(x: np.ndarray, yr: np.ndarray) -> str:
    out = []
    for nm, m in (("학습", yr <= 2023), ("검증", yr >= 2024)):
        g = x[m & np.isfinite(x)]
        out.append(f"{nm} {cfmt(cstats(g))} 최악5% {tail5(g - 0.0025):.1f}%" if len(g) else f"{nm} n=0")
    return " | ".join(out)


def part_g(prep: str, al: dict) -> dict:
    ev = pd.read_pickle(os.path.join(prep, "vl_ev.pkl"))
    core = ((ev.pos >= G_POS) & (ev.x20 >= G_X20)).to_numpy()
    T = g_trades(ev, al, core)
    done = T[T.why != "진행 중"]
    res = {"T": T}
    res["all"] = tstat(done.ret.to_numpy(), done.yr.to_numpy())
    W = waves(done)
    res["waves"] = tstat(W.ret.to_numpy(), W.yr.to_numpy())
    res["n_waves"] = (len(done), len(W))
    res["acct"] = account_curve(W, al)
    res["acct43"] = account_curve(W, al, 0.0043)
    # ④ 일반 급등에 같은 규칙
    led = set(zip(ev.code, ev.date))
    sv = surge_events(al, led)
    res["surge_n"] = len(sv)
    for nm, m in (("일반 급등 전부", np.ones(len(sv), bool)), ("일반 급등·대금 1,000억↑", (sv.val >= 1000).to_numpy())):
        Ts = g_trades(sv, al, m)
        Ts = Ts[Ts.why != "진행 중"]
        res[nm] = (len(sv[m]), tstat(Ts.ret.to_numpy(), Ts.yr.to_numpy()))
    lm = core & (ev.chg >= 10).to_numpy() & (ev.chg.to_numpy() > 0)
    Tl = g_trades(ev, al, lm)
    Tl = Tl[Tl.why != "진행 중"]
    res["장부·+10%↑만"] = (int(lm.sum()), tstat(Tl.ret.to_numpy(), Tl.yr.to_numpy()))
    # ⑤ 지금(자료 마지막 날) 대기·보유 목록
    now = []
    for i in np.flatnonzero(core):
        r = ev.iloc[i]
        d = al.get(r.code)
        o, h, l, c, val = _np(d, r.code)
        dt = d.date.to_numpy()
        k = int(np.searchsorted(dt, r.date))
        n = len(o)
        if n - 1 - k > 15 + G_HOLD or k >= n or dt[k] != r.date:
            continue
        t = pull_trade(o, h, l, c, val, k)
        if t and t["why"] == "진행 중":
            now.append({"상태": "보유 중", "code": r.code, "name": r["name"], "D": r.date, "산 날": dt[t["j"]], "산 값": round(t["buy"]),
                        "지금": c[-1], "수익%": round((c[-1] / t["buy"] - 1) * 100, 1), "익절가": round(t["buy"] * 1.1), "남은 날": t["j"] + G_HOLD - (n - 1)})
        elif t is None and n - 1 - k < 15:
            P = h[k:].max()
            # 이미 닿았는데 거래가 식어 버려진 사건은 빼기
            touched = any(l[j] <= max(h[k:j]) * (1 - G_DEPTH) for j in range(k + 1, n))
            if touched:
                continue
            now.append({"상태": "눌림 대기", "code": r.code, "name": r["name"], "D": r.date, "고점": P, "살 값(−20%)": round(P * 0.8), "지금": c[-1],
                        "거리%": round((P * 0.8 / c[-1] - 1) * 100, 1), "오늘대금/신고일": round(val[-1] / val[k], 2),
                        "내일 살 수 있나": "예" if val[-1] >= val[k] * G_VD else "아니오(거래 식음)", "남은 날": 15 - (n - 1 - k)})
    res["now"] = pd.DataFrame(now)
    res["last_day"] = al["005930"].date.iloc[-1]
    return res


def _sector_map() -> pd.DataFrame:
    s = pd.read_csv("data/sectors_stockeasy.csv", dtype={"code": str, "sub_code": str}, encoding="utf-8-sig")
    return s.drop_duplicates("code").set_index("code")


def part_h(prep: str, al: dict) -> dict:
    ev = pd.read_pickle(os.path.join(prep, "vl_ev.pkl")).reset_index(drop=True)
    fw = np.load(os.path.join(prep, "vl_fw.npy"))
    c0 = fw[:, 0, 3]
    yr = ev.date.str[:4].astype(int).to_numpy()
    out_ret = {"1일": fw[:, 1, 3] / c0 - 1, "5일": fw[:, 5, 3] / c0 - 1, "20일": fw[:, 20, 3] / c0 - 1}
    big = (np.nanmax(fw[:, 1:21, 1], axis=1) / c0 - 1) >= 0.30
    # 눌림: 조건 없는 −20% 첫 눌림(3차 기본) + 3차 추천 규칙
    E = pd.read_pickle(os.path.join(prep, "vl_pull_candidates.pkl"))
    e20 = E[E.depth == 0.20]
    pull_any = pd.Series(e20.r_base.to_numpy(), index=e20.ev.to_numpy()).groupby(level=0).first()
    core = e20[(e20.pos0 >= G_POS) & (e20.x20 >= G_X20) & (e20.v_vs_D >= G_VD)]
    pull_core = pd.Series(core.r_base.to_numpy(), index=core.ev.to_numpy()).groupby(level=0).first()
    sm = _sector_map()
    res = {"cover": float(ev.code.isin(sm.index).mean() * 100)}
    for key in ("sector", "sub_sector"):
        sec = ev.code.map(sm[key] if key == "sector" else sm["sector"] + "/" + sm["sub_sector"])
        grp = ev.assign(sec=sec).groupby(["date", "sec"])
        size = grp.code.transform("size").to_numpy()
        rank = grp.val.rank(ascending=False, method="first").to_numpy()
        has = sec.notna().to_numpy()
        cats = {"혼자": has & (size == 1), "2개": has & (size == 2), "3개 이상": has & (size >= 3),
                "  └ 2개↑ 대장(대금 1등)": has & (size >= 2) & (rank == 1), "  └ 2개↑ 나머지": has & (size >= 2) & (rank > 1),
                "섹터 표에 없음": ~has}
        rows = []
        for nm, m in cats.items():
            row = {"묶음": nm}
            for half, hm in (("학습", yr <= 2023), ("검증", yr >= 2024)):
                mm = m & hm
                row[f"{half} 건수"] = int(mm.sum())
                for rk, rv in out_ret.items():
                    row[f"{half} {rk}"] = np.nanmean(rv[mm]) * 100 - 0.25
                row[f"{half} +30%고점"] = big[mm].mean() * 100 if mm.sum() else np.nan
                pa = pull_any.reindex(np.flatnonzero(mm)).dropna()
                row[f"{half} 눌림−20%"] = (pa.mean() - 0.0025) * 100 if len(pa) else np.nan
                row[f"{half} 눌림n"] = len(pa)
                pc = pull_core.reindex(np.flatnonzero(mm)).dropna()
                row[f"{half} 추천규칙"] = (pc.mean() - 0.0025) * 100 if len(pc) else np.nan
                row[f"{half} 추천n"] = len(pc)
            rows.append(row)
        res[key] = pd.DataFrame(rows)
    return res


def part_i(prep: str, al: dict) -> dict:
    """신고 뒤 20~40일, 대금이 식었을 때(그날까지 5일 평균 ≤ 신고 전 20일 평균×2) 가격이 신고일 종가 근처(±3%)/시가 근처(±3%)/저가 아래면 그날 종가에 사서 10·20일."""
    ev = pd.read_pickle(os.path.join(prep, "vl_ev.pkl"))
    kinds = ("종가 근처", "시가 근처", "저가 아래", "(대조) 식은 첫날 아무 값")
    rows = {kd: [] for kd in kinds}
    for r in ev.itertuples(index=False):
        d = al.get(r.code)
        if d is None:
            continue
        o, h, l, c, val = _np(d, r.code)
        dt = d.date.to_numpy()
        k = int(np.searchsorted(dt, r.date))
        if k >= len(dt) or dt[k] != r.date or k < 20:
            continue
        base = val[k - 20:k].mean()
        v5 = pd.Series(val).rolling(5).mean().to_numpy()
        for kd in kinds:
            for j in range(k + 20, min(k + 40, len(c) - 1) + 1):
                if not (base > 0 and v5[j] <= base * 2):
                    continue
                ok = {"종가 근처": abs(c[j] / c[k] - 1) <= 0.03, "시가 근처": abs(c[j] / o[k] - 1) <= 0.03,
                      "저가 아래": c[j] < l[k], "(대조) 식은 첫날 아무 값": True}[kd]
                if ok:
                    rr = {hd: (c[j + hd] / c[j] - 1 if j + hd < len(c) else np.nan) for hd in (10, 20)}
                    rows[kd].append({"code": r.code, "entry": dt[j], "yr": int(r.date[:4]), "r10": rr[10], "r20": rr[20], "vs_c0": c[j] / c[k] - 1})
                    break
    res = {}
    for kd, rs in rows.items():
        X = pd.DataFrame(rs).drop_duplicates(["code", "entry"])
        yr = X.yr.to_numpy()
        res[kd] = {hd: (tstat(X[f"r{hd}"].to_numpy(), yr), by_year(X[f"r{hd}"].to_numpy() - 0.0025, yr)) for hd in (10, 20)}
        res[kd]["vs_c0"] = float(X.vs_c0.median() * 100)
    return res


def print_part4(G: dict, H: dict, I: dict) -> None:
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 300)
    T = G["T"]
    print(f"\n========== 4차 G. 3차 추천 규칙 굳히기 (자료 마지막 날 {G['last_day']}) ==========")
    print("[① 검증(2024~) 거래 전부 — 최근 것부터, 수익은 비용 0.25% 뒤]")
    te = T[T.yr >= 2024].sort_values("entry", ascending=False).copy()
    te["수익%"] = ((te.ret - 0.0025) * 100).round(2)
    te["buy"] = te.buy.round(0)
    print(te[["name", "code", "D", "entry", "buy", "exit", "why", "수익%"]].to_string(index=False))
    print(f"\n[전체(끝난 거래)] {G['all']}")
    print(f"[② 같은 파동 묶기] {G['n_waves'][0]}건 → {G['n_waves'][1]}건: {G['waves']}")
    for nm in ("acct", "acct43"):
        A = G[nm]
        print(f"[③ 계좌 어림 — 비용 {'0.25' if nm == 'acct' else '0.43'}%] 최대 동시 보유 {A['K']}종목(계좌를 {A['K']}등분), 보유일 평균 동시 {A['mean_hold']:.1f}종목, 전체 합 {A['total']:+.1f}%, 최대 낙폭 {A['mdd']:.1f}%")
        for y, v in A["years"].items():
            print(f"     {y}: 계좌 {v['ret']:+.1f}% · 그해 최대 낙폭 {v['mdd']:.1f}% · 거래 {v['n']}건")
    print(f"\n[④ 장부 아닌 일반 급등(+10%·양봉·위치≥0.8·평소 20배) {G['surge_n']:,}일에 같은 눌림 규칙]")
    for nm in ("일반 급등 전부", "일반 급등·대금 1,000억↑", "장부·+10%↑만"):
        print(f"  {nm}({G[nm][0]:,}일): {G[nm][1]}")
    print("\n[⑤ 지금 걸려 있는 종목]")
    print(G["now"].to_string(index=False) if len(G["now"]) else "  없음")
    print(f"\n========== 4차 H. 테마 묶음(스탁이지 섹터, 장부 종목 {H['cover']:.0f}% 가 표에 있음) — 비용 0.25% 뒤 평균 % ==========")
    for key in ("sector", "sub_sector"):
        print(f"[{'큰 섹터' if key == 'sector' else '세부 섹터'}]")
        print(H[key].round(2).to_string(index=False))
    print("\n========== 4차 I. 식은 뒤 사기(신고 뒤 20~40일, 대금 5일 평균 ≤ 신고 전 평소×2, 그날 종가 매수) ==========")
    for kd, v in I.items():
        print(f"[{kd}] (산 값이 신고일 종가 대비 중앙 {v['vs_c0']:+.1f}%)")
        for hd in (10, 20):
            print(f"   {hd}일: {v[hd][0]}\n        연도별(비용 뒤) {v[hd][1]}")


# ====================================================================== 5차 (lead 10-14 5차 지시) — 1단계 선별 점수 → 2단계 진입·청산
# 자료 경로·함정은 state/agent_reports/data-agent_value_ledger_selection_features.md 그대로.
FACT_KW = r"실적|영업이익|순이익|흑자|매출|수주|계약|공급|인수|합병|자사주|자기주식|무상증자|승인|허가|임상|특허|공시|배당|지분|투자 유치"


def news_index() -> tuple[dict, set]:
    """인포스탁 데일리(장 마감 뒤 16~17시 글 → 다음날 09:00 판단용). {(날짜, 코드): 특징}, 글 있는 날짜 집합.
    한 종목이 여러 섹션에 나오면 같이 불린 종목이 가장 많은 섹션을 쓴다."""
    import glob
    import json
    import re
    fact_re = re.compile(FACT_KW)
    out, days = {}, set()
    for f in glob.glob("data/news/infostock_daily/*.json"):
        d = json.load(open(f, encoding="utf-8"))
        day = d["date"].replace("-", "")
        days.add(day)
        for s in d.get("sections", []):
            codes = [x.get("code") for x in s.get("stocks", []) if x.get("code")]
            tbl = s.get("table", [])
            br = 0
            for t in tbl:
                try:
                    br += float(str(t.get("chg", "0")).replace("%", "").replace("+", "").replace(",", "")) >= 5
                except ValueError:
                    pass
            # 테마 표(그날 테마 구성 종목 등락)는 2024 부터만 있다 → 그 전엔 폭 B 를 비운다. 대금 순위는 해마다 같게 '글에 나온 종목' 안에서만.
            members = set(codes)
            for c in codes:
                rec = {"news": 1.0, "co_named": len(codes) - 1, "fact": float(bool(fact_re.search(s.get("head", "")))),
                       "breadth": br if tbl else np.nan, "members": members}
                if (day, c) not in out or out[(day, c)]["co_named"] < rec["co_named"]:
                    out[(day, c)] = rec
    return out, days


S_FEATS_OLD = ["chg", "pos", "lval", "mult", "x20", "cnt", "vs52", "vs20", "n_same"]
S_FEATS_NEW = ["turn", "mshare", "kosdaq", "rs", "rs1", "rs3", "rs6", "rs12", "n60", "n120", "n250", "since_max", "quiet", "w60", "pos3y",
               "body", "upper", "gap", "sec_n", "sec_lead", "news", "co_named", "fact", "breadth", "theme_rank"]
NEWS_FEATS = {"news", "co_named", "fact", "breadth", "theme_rank"}


def s_features(prep: str, al: dict) -> pd.DataFrame:
    """신고일 장 마감(뉴스는 그날 밤 글 → 다음날 09:00)까지 알 수 있는 특징 + 결과 두 개(가·나)."""
    import json
    ev = pd.read_pickle(os.path.join(prep, "vl_ev.pkl")).reset_index(drop=True)
    shares = json.load(open("data/cache/rs_shares.json", encoding="utf-8"))
    mkt = json.load(open("data/cache/rs_market.json", encoding="utf-8"))
    mval = {m: pd.read_csv(f"data/index/daily/{f}_value.csv").assign(date=lambda x: x.date.str.replace("-", "")).set_index("date").value_mw
            for m, f in (("코스피", "001"), ("코스닥", "101"))}
    rsd = {}
    for nm, f in (("rs", "rs_rating"), ("rs1", "rs_1m"), ("rs3", "rs_3m"), ("rs6", "rs_6m"), ("rs12", "rs_12m")):
        x = pd.read_parquet(f"data/cache/{f}.parquet")
        x.index = pd.DatetimeIndex(x.index).strftime("%Y%m%d")
        rsd[nm] = x
    news, ndays = news_index()
    sm = _sector_map()
    sec = ev.code.map(sm["sector"])
    g = ev.assign(sec=sec).groupby(["date", "sec"])
    sec_n = g.code.transform("size").to_numpy(float) - 1
    sec_lead = (g.val.rank(ascending=False, method="first") == 1).to_numpy(float)
    sec_n[sec.isna().to_numpy()] = np.nan
    sec_lead[sec.isna().to_numpy()] = np.nan
    led_days = ev.groupby("code").date.apply(set).to_dict()
    n_same = ev.groupby("date").size()
    E = pd.read_pickle(os.path.join(prep, "vl_pull_candidates.pkl"))
    yb = E[E.depth == 0.20].groupby("ev").succ.first()
    rows = []
    for i, r in enumerate(ev.itertuples(index=False)):
        d = al.get(r.code)
        o, h, l, c, val = _np(d, r.code)
        dt = d.date.to_numpy()
        k = int(np.searchsorted(dt, r.date))
        n = len(c)
        f = {"i": i, "code": r.code, "date": r.date, "yr": int(r.date[:4]), "k": k,
             "chg": r.chg, "pos": r.pos, "lval": np.log(r.val), "mult": r.mult, "x20": r.x20, "cnt": r.cnt, "vs52": r.vs52, "vs20": r.vs20,
             "n_same": n_same[r.date]}
        sh = shares.get(r.code)
        f["turn"] = val[k] * 1e6 / (c[k] * sh) if sh else np.nan
        m = mkt.get(r.code)
        f["kosdaq"] = float(m == "코스닥") if m else np.nan
        mv = mval[m].get(r.date, np.nan) if m in mval else np.nan
        f["mshare"] = val[k] / mv if mv == mv and mv > 0 else np.nan
        for nm, x in rsd.items():
            f[nm] = x.at[r.date, r.code] if (r.date in x.index and r.code in x.columns) else np.nan
        mine = [int(np.searchsorted(dt, q)) for q in led_days[r.code] if q < r.date]
        for w in (60, 120, 250):
            f[f"n{w}"] = sum(1 for q in mine if k - q <= w)
        lo = max(0, k - 250)
        f["since_max"] = k - (lo + int(np.argmax(val[lo:k])))
        quiet = 0
        while k - quiet - 1 >= 0 and val[k - quiet - 1] < 0.1 * val[k]:
            quiet += 1
        f["quiet"] = quiet
        f["w60"] = c[max(0, k - 60):k].max() / c[max(0, k - 60):k].min() - 1
        f["pos3y"] = c[k] / h[max(0, k - 750):k].max() if k >= 245 else np.nan
        rg = h[k] - l[k]
        f["body"] = (c[k] - o[k]) / c[k - 1]
        f["upper"] = (h[k] - max(o[k], c[k])) / rg if rg > 0 else 0
        f["gap"] = o[k] / c[k - 1] - 1
        f["sec_n"], f["sec_lead"] = sec_n[i], sec_lead[i]
        if r.date in ndays:
            nw = news.get((r.date, r.code))
            f["news"] = 1.0 if nw else 0.0
            f["co_named"] = nw["co_named"] if nw else 0
            f["fact"] = nw["fact"] if nw else np.nan
            f["breadth"] = nw["breadth"] if nw else np.nan
            if nw:
                vals = []
                for mc in nw["members"]:
                    a = al.get(mc)
                    if a is not None:
                        kk = int(np.searchsorted(a.date.to_numpy(), r.date))
                        if kk < len(a) and a.date.iat[kk] == r.date:
                            vals.append(a.value_mw.iat[kk])
                f["theme_rank"] = 1 + sum(v > val[k] for v in vals)
            else:
                f["theme_rank"] = np.nan
        else:
            f.update({q: np.nan for q in NEWS_FEATS})
        # (가) 뒤 20일 안 +20% 고점이 −10% 저점보다 먼저 (같은 날 둘 다면 실패)
        ya = np.nan
        if k + 20 < n:
            ya = 0.0
            for q in range(k + 1, k + 21):
                if l[q] <= c[k] * 0.9:
                    break
                if h[q] >= c[k] * 1.2:
                    ya = 1.0
                    break
        f["ya"] = ya
        f["yb"] = float(yb.get(i, np.nan))
        rows.append(f)
    F = pd.DataFrame(rows)
    for col in S_FEATS_OLD + S_FEATS_NEW + ["ya", "yb"]:
        F[col] = pd.to_numeric(F[col], errors="coerce").astype(float)
    return F


def quint_table(F: pd.DataFrame, feats, y: str) -> pd.DataFrame:
    """특징별 5분위(학습 구간 경계) 성공률 — 학습·검증. 뉴스 특징은 학습 2022~2023."""
    rows = []
    for f in feats:
        x, yy, yr = F[f].to_numpy(float), F[y].to_numpy(float), F.yr.to_numpy()
        ok = np.isfinite(x) & np.isfinite(yy)
        tr, te = ok & (yr <= 2023), ok & (yr >= 2024)
        if tr.sum() < 200 or te.sum() < 100:
            continue
        uq = np.unique(x[tr])
        cuts = uq[1:] if len(uq) <= 6 else np.unique(np.nanquantile(x[tr], [0.2, 0.4, 0.6, 0.8]))  # 값이 몇 개뿐인 특징은 값마다 한 칸
        b = np.searchsorted(cuts, x, side="right")
        nb = len(cuts) + 1
        rt = [yy[tr & (b == q)].mean() * 100 if (tr & (b == q)).sum() >= 20 else np.nan for q in range(nb)]
        re_ = [yy[te & (b == q)].mean() * 100 if (te & (b == q)).sum() >= 20 else np.nan for q in range(nb)]
        d_tr, d_te = rt[-1] - rt[0], re_[-1] - re_[0]
        rows.append({"f": f, "칸": nb, "학습": " ".join(f"{v:.0f}" for v in rt), "검증": " ".join(f"{v:.0f}" for v in re_),
                     "차_학습": d_tr, "차_검증": d_te, "일치": bool(np.sign(d_tr) == np.sign(d_te) and abs(d_tr) >= 3 and abs(d_te) >= 3),
                     "학습만_강함": bool(abs(d_tr) >= 5), "cuts": cuts, "sign": float(np.sign(d_tr))})
    return pd.DataFrame(rows)


def _design(F: pd.DataFrame, feats, med=None):
    X = F[feats].astype(float).copy()
    med = X[F.yr <= 2023].median() if med is None else med
    for f in feats:
        if f in NEWS_FEATS:
            X[f + "_없음"] = X[f].isna().astype(float)
    X = X.fillna(med).fillna(0)
    return X, med


def logit_score(F: pd.DataFrame, feats, y: str, train_mask: np.ndarray, C=0.05):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    X, _ = _design(F, feats)
    yy = F[y].to_numpy(float)
    m = train_mask & np.isfinite(yy)
    mdl = make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=2000)).fit(X[m], yy[m].astype(int))
    return mdl.predict_proba(X)[:, 1], mdl


def oof_scores(F: pd.DataFrame, feats, y: str, C=0.05) -> np.ndarray:
    """학습 해(2020~2023)는 '그 해를 뺀 나머지 학습 해'로 맞춘 점수, 검증 해는 학습 전체로 맞춘 점수 → 둘 다 표본 밖 점수."""
    yr = F.yr.to_numpy()
    s = np.full(len(F), np.nan)
    full, _ = logit_score(F, feats, y, yr <= 2023, C)
    s[yr >= 2024] = full[yr >= 2024]
    for y0 in range(2020, 2024):
        p, _ = logit_score(F, feats, y, (yr <= 2023) & (yr != y0), C)
        s[yr == y0] = p[yr == y0]
    return s


def top_eval(F, score, y, yr_mask_tr=None) -> list[dict]:
    from sklearn.metrics import roc_auc_score
    yy, yr = F[y].to_numpy(float), F.yr.to_numpy()
    tr = (yr <= 2023) & np.isfinite(yy) & np.isfinite(score)
    te = (yr >= 2024) & np.isfinite(yy) & np.isfinite(score)
    out = []
    for top in (0.1, 0.2, 0.3):
        thr = np.nanquantile(score[tr], 1 - top)
        row = {"상위": f"{int(top * 100)}%"}
        for nm, m in (("학습", tr), ("검증", te)):
            sel = m & (score >= thr)
            row[f"{nm}_건수"] = int(sel.sum())
            row[f"{nm}_성공%"] = yy[sel].mean() * 100
            row[f"{nm}_전체%"] = yy[m].mean() * 100
            row[f"{nm}_나머지%"] = yy[m & (score < thr)].mean() * 100
        out.append(row)
    auc = {nm: roc_auc_score(yy[m], score[m]) for nm, m in (("학습", tr), ("검증", te))}
    return out, auc


def loyo(F, feats, y, C=0.05) -> pd.DataFrame:
    """한 해씩 빼고 나머지 해로 맞춘 뒤 그 해를 잰다 — 안정성."""
    from sklearn.metrics import roc_auc_score
    yr, yy = F.yr.to_numpy(), F[y].to_numpy(float)
    rows = []
    for y0 in sorted(set(yr)):
        p, _ = logit_score(F, feats, y, yr != y0, C)
        m = (yr == y0) & np.isfinite(yy)
        if m.sum() < 50 or len(set(yy[m])) < 2:
            continue
        thr = np.quantile(p[m], 0.8)
        rows.append({"해": y0, "건수": int(m.sum()), "전체%": yy[m].mean() * 100, "상위20%": yy[m & (p >= thr)].mean() * 100,
                     "하위80%": yy[m & (p < thr)].mean() * 100, "가르는힘": roc_auc_score(yy[m], p[m])})
    return pd.DataFrame(rows)


ENTRIES5 = ("D종가", "다음날시가", "눌림5", "눌림8", "눌림12", "눌림15", "눌림20", "몸통중간", "D시가")


def entry5(o, h, l, c, k, kind):
    """반환 (j, 진입가, 종가매수?) 또는 None. 눌림·몸통·시가 자리는 신고 뒤 15일 안 첫 닿음 지정가(시가가 더 낮으면 시가)."""
    n = len(o)
    if kind == "D종가":
        if c[k] >= c[k - 1] * 1.29 and c[k] >= h[k]:
            return None  # 상한가로 묶여 끝난 날 — 종가에 살 수 없다(사려는 사람이 줄 서 있다). 1차의 '+2.9%' 가 바로 이것
        return k, c[k], True
    if k + 1 >= n:
        return None
    if kind == "다음날시가":
        return k + 1, o[k + 1], False
    P = h[k]
    for j in range(k + 1, min(k + 15, n - 1) + 1):
        lim = {"몸통중간": (o[k] + c[k]) / 2, "D시가": o[k]}.get(kind)
        if lim is None:
            lim = P * (1 - int(kind[2:]) / 100)
        if l[j] <= lim:
            return j, min(o[j], lim), False
        P = max(P, h[j])
    return None


def stage2(F: pd.DataFrame, score: np.ndarray, top_thr: float) -> pd.DataFrame:
    """점수 상위(≥ top_thr) vs 나머지 — 진입 9 × 익절 4 × 손절 4 × 보유 3. (종목·진입일) 중복 제거, 끝나지 않은 거래 뺌."""
    rows = []
    hi = score >= top_thr
    for kind in ENTRIES5:
        ent = []
        for r, h_ in zip(F.itertuples(index=False), hi):
            o, h, l, c, _ = _ARR[r.code]
            e = entry5(o, h, l, c, r.k, kind)
            if e:
                ent.append((r.code, e[0], e[1], e[2], r.k, r.yr, h_))
        Ed = pd.DataFrame(ent, columns=["code", "j", "buy", "atc", "k", "yr", "hi"]).drop_duplicates(["code", "j"])
        for tgt, stop, hold in itertools.product(E_TGTS, E_STOPS, E_HOLDS):
            g = np.full(len(Ed), np.nan)
            for q, e in enumerate(Ed.itertuples(index=False)):
                o, h, l, c, _ = _ARR[e.code]
                if e.j + hold > len(o) - 1:
                    continue
                if stop == "D저가":
                    if e.buy <= l[e.k]:
                        continue
                    g[q] = _exit_daily(o, h, l, c, e.j, e.buy, tgt, None, hold, stop_price=l[e.k], at_close=e.atc)[0]
                else:
                    g[q] = _exit_daily(o, h, l, c, e.j, e.buy, tgt, {"none": None, "-10%": 0.10, "-15%": 0.15}[stop], hold, at_close=e.atc)[0]
            yr, hm = Ed.yr.to_numpy(), Ed.hi.to_numpy()
            row = {"entry": kind, "tgt": tgt, "stop": stop, "hold": hold}
            for grp, gm in (("상위", hm), ("하위", ~hm)):
                for half, ym in (("tr", yr <= 2023), ("te", yr >= 2024)):
                    x = g[gm & ym & np.isfinite(g)] - 0.0025
                    row[f"{grp}_{half}_n"] = len(x)
                    row[f"{grp}_{half}"] = x.mean() * 100 if len(x) else np.nan
                    row[f"{grp}_{half}_med"] = np.median(x) * 100 if len(x) else np.nan
                    row[f"{grp}_{half}_win"] = (x > 0).mean() * 100 if len(x) else np.nan
                    row[f"{grp}_{half}_t5"] = np.percentile(x, 5) * 100 if len(x) else np.nan
            x = g[hm & np.isfinite(g)]
            row["상위_해"] = by_year(np.where(hm, g - 0.0025, np.nan), yr)
            rows.append(row)
    G = pd.DataFrame(rows)
    # 이웃 평균(학습, 상위): 같은 진입에서 익절·손절·보유 한 칸씩 옆
    idx = {(r.entry, r.tgt, r.stop, r.hold): r.상위_tr for r in G.itertuples()}
    ax = {"tgt": list(E_TGTS), "stop": list(E_STOPS), "hold": list(E_HOLDS)}
    nb = []
    for r in G.itertuples():
        vals = [r.상위_tr]
        for a, lst in ax.items():
            p = lst.index(getattr(r, a))
            for d_ in (-1, 1):
                if 0 <= p + d_ < len(lst):
                    key = {"tgt": r.tgt, "stop": r.stop, "hold": r.hold, a: lst[p + d_]}
                    vals.append(idx[(r.entry, key["tgt"], key["stop"], key["hold"])])
        nb.append(np.nanmean(vals))
    G["상위_tr_이웃"] = nb
    return G


def stage2_focus(F: pd.DataFrame, score: np.ndarray, kinds=("D종가", "D시가", "몸통중간", "눌림20"), tgt=0.10, stop="none", hold=10) -> pd.DataFrame:
    """점수 구간(학습 경계: 상위 10% / 10~20% / 20~30% / 나머지)별로 같은 청산 칸을 잰다 — 선별이 보탠 것을 칸 하나로 보기."""
    yr = F.yr.to_numpy()
    q = np.nanquantile(score[yr <= 2023], [0.7, 0.8, 0.9])
    band = np.select([score >= q[2], score >= q[1], score >= q[0]], ["상위10%", "10~20%", "20~30%"], "나머지70%")
    rows = []
    for kind in kinds:
        ent = []
        for r, bd in zip(F.itertuples(index=False), band):
            o, h, l, c, _ = _ARR[r.code]
            e = entry5(o, h, l, c, r.k, kind)
            if e and e[0] + hold <= len(o) - 1:
                if stop == "D저가":
                    if e[1] <= l[r.k]:
                        continue
                    g = _exit_daily(o, h, l, c, e[0], e[1], tgt, None, hold, stop_price=l[r.k], at_close=e[2])[0]
                else:
                    g = _exit_daily(o, h, l, c, e[0], e[1], tgt, {"none": None, "-10%": 0.10, "-15%": 0.15}[stop], hold, at_close=e[2])[0]
                ent.append((r.code, e[0], r.yr, bd, g - 0.0025))
        Ed = pd.DataFrame(ent, columns=["code", "j", "yr", "band", "net"]).drop_duplicates(["code", "j"])
        for bd in ("상위10%", "10~20%", "20~30%", "나머지70%"):
            row = {"entry": kind, "band": bd}
            for half, m in (("학습", Ed.yr <= 2023), ("검증", Ed.yr >= 2024)):
                x = Ed.net[m & (Ed.band == bd)].to_numpy()
                row[f"{half}_n"], row[f"{half}_평균"] = len(x), x.mean() * 100 if len(x) else np.nan
                row[f"{half}_중앙"] = np.median(x) * 100 if len(x) else np.nan
                row[f"{half}_승률"] = (x > 0).mean() * 100 if len(x) else np.nan
                row[f"{half}_최악5%"] = np.percentile(x, 5) * 100 if len(x) else np.nan
            x = Ed[Ed.band == bd]
            row["해별"] = {int(y): round(v * 100, 1) for y, v in x.groupby("yr").net.mean().items()}
            row["해별건수"] = {int(y): int(v) for y, v in x.groupby("yr").size().items()}
            rows.append(row)
    return pd.DataFrame(rows)


def part5(prep: str, al: dict) -> dict:
    F = s_features(prep, al)
    res = {"F": F}
    feats = S_FEATS_OLD + S_FEATS_NEW
    for y in ("ya", "yb"):
        Q = quint_table(F, feats, y)
        res[f"Q_{y}"] = Q
        agree = Q[Q.일치].f.tolist()
        tr_only = Q[Q.학습만_강함].f.tolist()
        res[f"agree_{y}"], res[f"tronly_{y}"] = agree, tr_only
        # (1) lead 방식: 학습·검증 방향 일치 특징만 분위 점수 합 (검증을 보고 골랐으니 검증 숫자는 낙관적)
        sc = np.zeros(len(F))
        for _, q in Q[Q.일치].iterrows():
            x = F[q.f].to_numpy(float)
            b = np.searchsorted(q.cuts, x, side="right") - (len(q.cuts)) / 2
            sc += np.where(np.isfinite(x), q.sign * b, 0)
        res[f"sum_{y}"] = top_eval(F, sc, y) if agree else None
        # (2) 깨끗한 방식: 전 특징 규제 로지스틱(학습만), 학습 해는 그 해 뺀 점수
        s_oof = oof_scores(F, feats, y)
        res[f"logit_{y}"] = top_eval(F, s_oof, y)
        res[f"score_{y}"] = s_oof
        res[f"loyo_{y}"] = loyo(F, feats, y)
        _, mdl = logit_score(F, feats, y, F.yr.to_numpy() <= 2023)
        X, _ = _design(F, feats)
        res[f"coef_{y}"] = pd.Series(mdl[-1].coef_[0], index=X.columns).sort_values(key=abs, ascending=False)
    # 카드 5장 — 정의 구간 그대로, (가)(나) 성공률 학습/검증
    cards = []
    def card(name, lab, m):
        for y in ("ya", "yb"):
            yy, yr = F[y].to_numpy(float), F.yr.to_numpy()
            for half, hm in (("학습", yr <= 2023), ("검증", yr >= 2024)):
                mm = m & hm & np.isfinite(yy)
                cards.append({"카드": name, "구간": lab, "목표": y, "반": half, "건수": int(mm.sum()), "성공%": yy[mm].mean() * 100 if mm.sum() else np.nan})
    news_ok = F.news.notna().to_numpy()
    fct = F.fact.to_numpy()
    card("H-023 재료(뉴스 문장 근사)", "사실(실적·수주 등 낱말)", news_ok & (fct == 1))
    card("H-023 재료(뉴스 문장 근사)", "테마·기대", news_ok & (fct == 0))
    card("H-023 재료(뉴스 문장 근사)", "글에 이름 없음", news_ok & (F.news.to_numpy() == 0))
    t = F.turn.to_numpy()
    for lab, lo, hi_ in (("<5%", 0, .05), ("5~15%", .05, .15), ("15~40%", .15, .40), ("≥40%", .40, 99)):
        card("H-024 회전율", lab, (t >= lo) & (t < hi_))
    card("H-025 누가 샀나", "못 잼(종목별 투자자 자료 없음)", np.zeros(len(F), bool))
    n245 = F.n250.to_numpy()
    for lab, m in (("첫 폭증(0회)", n245 == 0), ("1~2회", (n245 >= 1) & (n245 <= 2)), ("3회↑", n245 >= 3)):
        card("H-026 쉰 뒤 첫 폭증 — N245", lab, m)
    qq = F.quiet.to_numpy()
    for lab, m in (("<20일", qq < 20), ("20~60일", (qq >= 20) & (qq <= 60)), (">60일", qq > 60)):
        card("H-026 쉰 기간 Q", lab, m)
    w = F.w60.to_numpy()
    for lab, m in (("≤20%", w <= .2), ("20~50%", (w > .2) & (w <= .5)), (">50%", w > .5)):
        card("H-026 횡보 폭 W", lab, m)
    card("H-026 조합", "0회·Q>60·W≤20%", (n245 == 0) & (qq > 60) & (w <= .2))
    br, tr_ = F.breadth.to_numpy(), F.theme_rank.to_numpy()
    for lab, m in (("단독(0)", br == 0), ("1~2", (br >= 1) & (br <= 2)), ("3↑", br >= 3)):
        card("H-027 테마 폭 B(그날 글의 테마 +5% 종목 수)", lab, m & news_ok & (F.news.to_numpy() == 1))
    for lab, m in (("대장(1위)", tr_ == 1), ("2~3위", (tr_ >= 2) & (tr_ <= 3)), ("4위↓", tr_ >= 4)):
        card("H-027 테마 안 대금 순위 L", lab, m)
    card("H-027 조합", "B≥3·대장", (br >= 3) & (tr_ == 1))
    res["cards"] = pd.DataFrame(cards).pivot_table(index=["카드", "구간"], columns=["목표", "반"], values=["성공%", "건수"], sort=False)
    # 2단계: (가) 깨끗한 점수(뉴스 빼고 — 뉴스는 장 마감 뒤에 나와 '신고일 종가' 진입엔 못 쓴다) 상위 30% vs 나머지
    feats_nn = [f for f in feats if f not in NEWS_FEATS]
    s = oof_scores(F, feats_nn, "ya")
    res["logit_ya_nonews"] = top_eval(F, s, "ya")
    res["score_ya_nonews"] = s
    thr = np.nanquantile(s[F.yr.to_numpy() <= 2023], 0.7)
    res["thr"] = thr
    res["S2"] = stage2(F, s, thr)
    res["focus"] = stage2_focus(F, s)
    # 점수의 1등 무게(3년 고가 대비 위치)만 남긴 단순 선별 — 사람이 쓸 수 있게. 경계는 학습 분위(0.98·1.07) 근처 둥근 값.
    P3, UP = F.pos3y.to_numpy(), F.upper.to_numpy()
    nb = []
    for p3, up in itertools.product((0.8, 0.9, 1.0, 1.1), (0.1, 0.2, 1.0)):
        m = (P3 >= p3) & (UP <= up)
        nb.append({"3년고가대비≥": p3, "윗꼬리≤": up, **{f"{h}_(가)%": np.nanmean(F.ya.to_numpy()[m & hm]) * 100 for h, hm in (("학습", F.yr <= 2023), ("검증", F.yr >= 2024))}})
    res["simple_sel"] = pd.DataFrame(nb)
    simple = np.nan_to_num(P3) >= 1.0
    res["S2_simple"] = stage2(F, simple.astype(float), 0.5)
    ev = pd.read_pickle(os.path.join(prep, "vl_ev.pkl")).reset_index(drop=True)
    rows = []
    for r, ok in zip(F.itertuples(index=False), simple):
        if not ok:
            continue
        o, h, l, c, val = _ARR[r.code]
        t = pull_trade(o, h, l, c, val, r.k, vmin=0.0)
        dt = al[r.code].date.to_numpy()
        if t:
            rows.append({"code": r.code, "name": ev.name.iat[r.i], "D": r.date, "entry": dt[t["j"]], "exit": dt[t["xk"]], "buy": t["buy"], "ret": t["ret"],
                         "why": t["why"], "j": t["j"], "xk": t["xk"], "yr": r.yr})
        elif len(o) - 1 - r.k < 15:
            P = h[r.k:].max()
            rows.append({"code": r.code, "name": ev.name.iat[r.i], "D": r.date, "why": "눌림 대기", "buy": P * 0.8, "now": c[-1], "yr": r.yr,
                         "left": 15 - (len(o) - 1 - r.k)})
    T = pd.DataFrame(rows)
    res["final_T"] = T
    done = T[T.why.isin(["익절", "기간"])].drop_duplicates(["code", "entry"])
    W = waves(done)
    res["final_n"] = (len(done), len(W))
    res["final_stat"] = tstat(W.ret.to_numpy(), W.yr.to_numpy())
    res["final_years"] = by_year(W.ret.to_numpy() - 0.0025, W.yr.to_numpy())
    res["final_acct"] = account_curve(W, al)
    res["final_acct43"] = account_curve(W, al, 0.0043)
    W10 = slot_filter(W, 10)
    res["final_slot10"] = (len(W10), account_curve(W10, al, K=10), account_curve(W10, al, 0.0043, K=10))
    return res


def print_part5(R: dict) -> None:
    pd.set_option("display.width", 300)
    pd.set_option("display.max_rows", 500)
    pd.set_option("display.max_columns", 60)
    F = R["F"]
    print(f"\n========== 5차 1단계 선별 — 사건 {len(F):,}건, (가) 기본 성공률 학습 {F.ya[F.yr <= 2023].mean() * 100:.1f}% 검증 {F.ya[F.yr >= 2024].mean() * 100:.1f}%"
          f" · (나) 학습 {F.yb[F.yr <= 2023].mean() * 100:.1f}% 검증 {F.yb[F.yr >= 2024].mean() * 100:.1f}% (눌림 닿은 {F.yb.notna().sum():,}건) ==========")
    print("특징 붙은 비율:", {f: round(F[f].notna().mean() * 100) for f in S_FEATS_NEW})
    for y, nm in (("ya", "(가) 20일 안 +20%가 −10%보다 먼저"), ("yb", "(나) −20% 눌림 매수 성공(+10% 먼저)")):
        print(f"\n[{nm} — 특징별 5분위 성공률(%) 낮은→높은, 차 = 5분위−1분위 %p]")
        print(R[f"Q_{y}"].drop(columns=["cuts", "sign"]).round(1).to_string(index=False))
        print(f"  학습·검증 방향 일치: {R[f'agree_{y}']}")
        if R[f"sum_{y}"]:
            print("  [일치 특징 분위 합산 점수 — 검증을 보고 고른 특징이라 낙관적]")
            print(pd.DataFrame(R[f"sum_{y}"][0]).round(1).to_string(index=False), " 가르는 힘", {k: round(v, 3) for k, v in R[f"sum_{y}"][1].items()})
        print("  [규제 로지스틱(학습만, 학습 해는 그 해 뺀 점수) — 깨끗한 판]")
        print(pd.DataFrame(R[f"logit_{y}"][0]).round(1).to_string(index=False), " 가르는 힘", {k: round(v, 3) for k, v in R[f"logit_{y}"][1].items()})
        print("  [한 해씩 빼고 맞춘 점수의 그 해 성적]")
        print(R[f"loyo_{y}"].round(3).to_string(index=False))
        print("  [로지스틱 무게 상위 12]", R[f"coef_{y}"].head(12).round(3).to_dict())
    print("\n[(가) 뉴스 특징 뺀 로지스틱 — 2단계에 쓰는 점수]")
    print(pd.DataFrame(R["logit_ya_nonews"][0]).round(1).to_string(index=False), " 가르는 힘", {k: round(v, 3) for k, v in R["logit_ya_nonews"][1].items()})
    print("\n[선별 카드 5장 — 성공률(%)과 건수]")
    print(R["cards"].round(1).to_string())
    G = R["S2"]
    print(f"\n========== 5차 2단계 — (가) 점수 상위 30%(점수 ≥ {R['thr']:.3f}) vs 나머지, 비용 0.25% 뒤 평균 % ==========")
    cols = ["entry", "tgt", "stop", "hold", "상위_tr_n", "상위_tr", "상위_tr_이웃", "상위_te_n", "상위_te", "상위_te_med", "상위_te_win", "상위_te_t5", "하위_tr", "하위_te"]
    print("[진입마다 학습 이웃 평균 최고 칸]")
    print(G.loc[G.groupby("entry").상위_tr_이웃.idxmax(), cols].round(2).to_string(index=False))
    print("\n[전체 상위 20 — 학습 이웃 평균 순]")
    print(G.sort_values("상위_tr_이웃", ascending=False)[cols].head(20).round(2).to_string(index=False))
    print("\n[같은 칸 기준(손절 없음·+10%·10일) 진입별 상위 vs 하위]")
    print(G[(G.stop == "none") & (G.tgt == 0.10) & (G.hold == 10)][cols].round(2).to_string(index=False))
    print("\n[점수 구간별 — +10% 익절·손절 없음·10일, 비용 0.25% 뒤]")
    print(R["focus"].drop(columns=["해별", "해별건수"]).round(2).to_string(index=False))
    for r in R["focus"].itertuples(index=False):
        if r.band == "상위10%" or r.band == "나머지70%":
            print(f"   {r.entry} {r.band} 해별 {r.해별} 건수 {r.해별건수}")
    print("\n[단순 선별: 종가가 직전 3년 최고가 대비 몇 배 이상 × 윗꼬리 — (가) 성공률]")
    print(R["simple_sel"].round(1).to_string(index=False))
    G2 = R["S2_simple"]
    print("\n[단순 선별(3년 신고가 = 종가 ≥ 직전 3년 최고가) 안 vs 밖 — 진입마다 학습 이웃 평균 최고 칸]")
    print(G2.loc[G2.groupby("entry").상위_tr_이웃.idxmax(), cols].round(2).to_string(index=False))
    print("[같은 칸(+10%·손절 없음·10일)]")
    print(G2[(G2.stop == "none") & (G2.tgt == 0.10) & (G2.hold == 10)][cols].round(2).to_string(index=False))
    print("[눌림20 안 청산 격자 — 학습 순]")
    print(G2[G2.entry == "눌림20"].sort_values("상위_tr", ascending=False)[cols].round(2).to_string(index=False))
    print(f"\n[최종 규칙: 3년 신고가 장부 + −20% 눌림 지정가 + 10% 익절·10일] 끝난 거래 {R['final_n'][0]}건 → 같은 파동 묶어 {R['final_n'][1]}건: {R['final_stat']}")
    print(f"   해별(비용 뒤) {R['final_years']}")
    for nm in ("final_acct", "final_acct43"):
        A = R[nm]
        print(f"   계좌 어림({'0.25' if nm == 'final_acct' else '0.43'}%): 최대 동시 {A['K']}종목, 평균 {A['mean_hold']:.1f}, 합 {A['total']:+.1f}%, 최대 낙폭 {A['mdd']:.1f}% · "
              + " · ".join(f"{y} {v['ret']:+.1f}%(낙폭 {v['mdd']:.1f})" for y, v in A["years"].items()))
    n10, A, A43 = R["final_slot10"]
    print(f"   10칸(한 종목 계좌 10%, 빈 칸 있을 때만 삼) {n10}건: 합 {A['total']:+.1f}%(0.43%면 {A43['total']:+.1f}%), 최대 낙폭 {A['mdd']:.1f}% · "
          + " · ".join(f"{y} {v['ret']:+.1f}%(낙폭 {v['mdd']:.1f}, {v['n']}건)" for y, v in A["years"].items()))
    T = R["final_T"]
    print("[지금(자료 마지막 날) 보유 중·대기 중]")
    print(T[T.why.isin(["진행 중", "눌림 대기"])].to_string(index=False))
    b = G.loc[G.상위_tr_이웃.idxmax()]
    print(f"\n[학습 1위 칸 연도별(상위, 비용 뒤)] {b.entry} +{b.tgt} {b.stop} {b.hold}일: {b.상위_해}")


# ====================================================================== 6차 (lead 10-14 6차 지시) — 손절 있는 규칙으로 다시 고르기
# 선별은 5차 그대로(3년 신고가). 진입·손절·익절·보유를 같이 다시 고른다. 같은 날 순서는 보수적(손절 먼저).
P6_ENTRIES = ("눌림10", "눌림15", "눌림20", "눌림25", "D종가")
P6_STOPS = ([("none", 0)] + [("fix", x) for x in (0.05, 0.08, 0.10, 0.15, 0.20, 0.30)] + [("close", x) for x in (0.08, 0.10, 0.15, 0.20)]
            + [("D저가종가", 0)] + [("trail", x) for x in (0.10, 0.15)])
P6_TGTS = (0.07, 0.10, 0.15, 0.20)
P6_HOLDS = (5, 10, 15)


def exit6(o, h, l, c, j, P, tgt, kind, x, hold, l0=np.nan, at_close=False):
    """j 날 P 에 산 뒤 hold 거래일. 반환 (총수익, 나온 날, '익절'/'손절'/'기간').
    fix: 장중 −x 닿으면 그 값(시가가 더 낮으면 시가). close: 종가가 −x 아래로 끝나면 다음날 시가. D저가종가: 종가가 신고일 저가 아래로 끝나면 다음날 시가.
    trail: 들고 있는 동안 최고가(전날까지, 첫날은 산 값) 대비 −x 장중. 하루 안 순서: 시가 갭 → 장중 손절 → 장중 익절 → 종가 손절 판정(보수적).
    산 날(종가 매수가 아니면): 장중 손절만 보고, 익절은 안 센다. 종가 손절 판정은 산 날 종가부터."""
    T = P * (1 + tgt)
    last = j + hold
    peak = P
    pending = False

    def istop():
        if kind == "fix":
            return P * (1 - x)
        if kind == "trail":
            return peak * (1 - x)
        return -np.inf

    for d in range(j, last + 1):
        if d == j and at_close:
            pass
        else:
            S = istop()
            if d > j:
                if pending:
                    return o[d] / P - 1, d, "손절"
                if o[d] <= S:
                    return o[d] / P - 1, d, "손절"
                if o[d] >= T:
                    return o[d] / P - 1, d, "익절"
            if l[d] <= S:
                return min(S, o[d] if d > j else S) / P - 1, d, "손절"
            if d > j and h[d] >= T:
                return tgt, d, "익절"
            peak = max(peak, h[d]) if d > j else peak
        if d == last:
            break
        if kind == "close" and c[d] < P * (1 - x):
            pending = True
        elif kind == "D저가종가" and c[d] < l0:
            pending = True
    return c[last] / P - 1, last, "기간"


def part6(prep: str, al: dict) -> dict:
    F = s_features(prep, al)
    sel = np.nan_to_num(F.pos3y.to_numpy()) >= 1.0
    up_short = F.upper.to_numpy() <= 0.2
    yr_all = F.yr.to_numpy()
    rows, trades = [], {}
    for ent in P6_ENTRIES:
        E = []
        for r, ok, us in zip(F.itertuples(index=False), sel, up_short):
            if not ok:
                continue
            o, h, l, c, _ = _ARR[r.code]
            e = entry5(o, h, l, c, r.k, ent)
            if e and e[0] + max(P6_HOLDS) <= len(o) - 1:
                E.append((r.code, e[0], e[1], e[2], r.k, r.yr, us, l[r.k], al[r.code].date.iat[e[0]]))
        Ed = pd.DataFrame(E, columns=["code", "j", "buy", "atc", "k", "yr", "us", "l0", "entry"]).drop_duplicates(["code", "j"]).reset_index(drop=True)
        yr = Ed.yr.to_numpy()
        for (kind, x), tgt, hold in itertools.product(P6_STOPS, P6_TGTS, P6_HOLDS):
            out = [exit6(*_ARR[e.code][:4], e.j, e.buy, tgt, kind, x, hold, e.l0, e.atc) for e in Ed.itertuples(index=False)]
            g = np.array([q[0] for q in out]) - 0.0025
            why = np.array([q[2] for q in out])
            row = {"entry": ent, "stop": kind, "x": x, "tgt": tgt, "hold": hold}
            for half, m in (("tr", yr <= 2023), ("te", yr >= 2024)):
                v = g[m]
                row[f"{half}_n"], row[f"{half}"] = len(v), v.mean() * 100
                row[f"{half}_med"], row[f"{half}_win"] = np.median(v) * 100, (v > 0).mean() * 100
                row[f"{half}_stop%"], row[f"{half}_t5"] = (why[m] == "손절").mean() * 100, np.percentile(v, 5) * 100
                row[f"{half}_43"] = (v - 0.0018).mean() * 100
            row["tr_posyrs"] = sum(g[yr == y].mean() > 0 for y in range(2020, 2024))
            row["years"] = {int(y): round(g[yr == y].mean() * 100, 2) for y in sorted(set(yr))}
            row["us_te"] = g[(yr >= 2024) & Ed.us.to_numpy()].mean() * 100
            row["us_tr"] = g[(yr <= 2023) & Ed.us.to_numpy()].mean() * 100
            rows.append(row)
            trades[(ent, kind, x, tgt, hold)] = (Ed, out)
    G = pd.DataFrame(rows)
    # 이웃: 같은 진입·같은 손절 종류 안에서 손절 폭·익절·보유 한 칸씩 + 진입 깊이 한 칸(눌림끼리)
    key = {(r.entry, r.stop, r.x, r.tgt, r.hold): r.tr for r in G.itertuples()}
    xs = {k_: sorted({x for kk, x in P6_STOPS if kk == k_}) for k_ in {kk for kk, _ in P6_STOPS}}
    pulls = [e for e in P6_ENTRIES if e.startswith("눌림")]
    nbv = []
    for r in G.itertuples():
        v = [r.tr]
        for ax, lst in (("x", xs[r.stop]), ("tgt", list(P6_TGTS)), ("hold", list(P6_HOLDS)), ("entry", pulls if r.entry in pulls else [r.entry])):
            p = lst.index(getattr(r, ax))
            for d_ in (-1, 1):
                if 0 <= p + d_ < len(lst):
                    kk = {"entry": r.entry, "stop": r.stop, "x": r.x, "tgt": r.tgt, "hold": r.hold, ax: lst[p + d_]}
                    v.append(key[(kk["entry"], kk["stop"], kk["x"], kk["tgt"], kk["hold"])])
        nbv.append(np.mean(v))
    G["tr_nb"] = nbv
    res = {"G": G}
    # 채택: 손절 있는 칸 중 학습 이웃 평균 1위(학습 4년 중 3년 이상 플러스) — 검증은 그대로 본다
    cand = G[(G.stop != "none") & (G.tr_posyrs >= 3)].sort_values("tr_nb", ascending=False)
    res["cand"] = cand
    best = cand.iloc[0]
    # 손절이 실제로 작동하는 칸만(폭 20% 이하 — −30% 는 거의 안 걸려 '손절 없음'과 같다)
    cand_r = cand[cand.x <= 0.20]
    res["cand_r"] = cand_r
    best_r = cand_r.iloc[0]
    res["best_r"] = best_r
    # 익절·보유를 5차(학습에서 고른 +10%·10일)에 묶고 손절·진입만 학습으로 고른 판 — 고를 칸이 적어 덜 우연이다
    cand_f = cand_r[(cand_r.tgt == 0.10) & (cand_r.hold == 10)]
    res["cand_f"] = cand_f
    best_f = cand_f.iloc[0]
    res["best_f"] = best_f
    base = G[(G.entry == "눌림20") & (G.stop == "none") & (G.tgt == 0.10) & (G.hold == 10)].iloc[0]
    res["best"], res["base"] = best, base
    acc = {}
    for nm, r in (("5차(손절 없음)", base), ("6차 기계적 1위", best), ("6차 채택(손절 폭 ≤20%)", best_r), ("6차 익절·보유 5차 고정", best_f), ("(비교) 같은 진입 손절 없음", G[(G.entry == best_f.entry) & (G.stop == "none") & (G.tgt == 0.10) & (G.hold == 10)].iloc[0])):
        Ed, out = trades[(r.entry, r.stop, r.x, r.tgt, r.hold)]
        T = Ed.assign(ret=[q[0] for q in out], xk=[q[1] for q in out], why=[q[2] for q in out])
        T["exit"] = [al[cd].date.iat[xk] for cd, xk in zip(T.code, T.xk)]
        W = waves(T)
        W10 = slot_filter(W, 10)
        acc[nm] = {"n": (len(T), len(W), len(W10)), "a25": account_curve(W10, al, K=10), "a43": account_curve(W10, al, 0.0043, K=10)}
    res["acct"] = acc
    return res


def print_part6(R: dict) -> None:
    pd.set_option("display.width", 300)
    pd.set_option("display.max_rows", 500)
    G = R["G"]
    cols = ["entry", "stop", "x", "tgt", "hold", "tr_n", "tr", "tr_nb", "tr_win", "tr_stop%", "tr_posyrs", "te_n", "te", "te_med", "te_win", "te_stop%", "te_t5", "te_43"]
    print("\n========== 6차 손절 있는 규칙 — 선별: 3년 신고가 장부, 비용 0.25% 뒤 % ==========")
    print("[손절 종류·폭마다 학습 이웃 평균 최고 칸]")
    print(G.loc[G.groupby(["stop", "x"]).tr_nb.idxmax(), cols].sort_values("tr_nb", ascending=False).round(2).to_string(index=False))
    print("\n[진입마다 손절 있는 칸 학습 이웃 평균 최고]")
    g2 = G[G.stop != "none"]
    print(g2.loc[g2.groupby("entry").tr_nb.idxmax(), cols].round(2).to_string(index=False))
    print("\n[채택 후보 상위 15 — 손절 있음·학습 3년↑ 플러스, 학습 이웃 평균 순]")
    print(R["cand"][cols].head(15).round(2).to_string(index=False))
    print("\n[손절 폭 20% 이하만 — 채택 후보 상위 15]")
    print(R["cand_r"][cols].head(15).round(2).to_string(index=False))
    b, s = R["best_r"], R["base"]
    for nm, r in (("5차(손절 없음)", s), ("6차 기계적 1위", R["best"]), ("6차 채택(손절 폭 ≤20%)", b), ("6차 익절·보유 5차 고정", R["best_f"]), ("(비교) 같은 진입 손절 없음", G[(G.entry == R["best_f"].entry) & (G.stop == "none") & (G.tgt == 0.10) & (G.hold == 10)].iloc[0])):
        print(f"\n[{nm}] {r.entry} · 손절 {r.stop} {r.x} · 익절 +{r.tgt} · {r.hold}일 → 학습 {r.tr_n}건 {r.tr:+.2f}% 중앙 {r.tr_med:+.2f} 승 {r.tr_win:.0f}% 손절로끝 {r['tr_stop%']:.0f}%"
              f" | 검증 {r.te_n}건 {r.te:+.2f}%(0.43% {r.te_43:+.2f}) 중앙 {r.te_med:+.2f} 승 {r.te_win:.0f}% 손절로끝 {r['te_stop%']:.0f}% 최악5% {r.te_t5:.1f}"
              f" | 윗꼬리 짧은 쪽 학습 {r.us_tr:+.2f} 검증 {r.us_te:+.2f}\n   해별 {r.years}")
        A, A43 = R["acct"][nm]["a25"], R["acct"][nm]["a43"]
        print(f"   거래 {R['acct'][nm]['n']} → 10칸 계좌 7년 {A['total']:+.1f}%(0.43% {A43['total']:+.1f}%) 최대 낙폭 {A['mdd']:.1f}% · "
              + " · ".join(f"{y} {v['ret']:+.1f}%(낙폭 {v['mdd']:.1f})" for y, v in A["years"].items()))
    # 채택 칸 주변 표
    print("\n[익절 +10%·10일 고정, 손절 폭 ≤20% — 학습 이웃 평균 순]")
    print(R["cand_f"][cols].head(12).round(2).to_string(index=False))
    nb = G[(G.entry == b.entry) & (G.stop == b.stop)]
    print(f"\n[채택 칸 주변 — {b.entry} · 손절 {b.stop}: 폭 × 익절 × 보유, 학습/검증]")
    print(nb[cols].round(2).to_string(index=False))
    print(f"\n[같은 손절·익절·보유로 진입 깊이만 바꾸면]")
    print(G[(G.stop == b.stop) & (G.x == b.x) & (G.tgt == b.tgt) & (G.hold == b.hold)][cols].round(2).to_string(index=False))


# ====================================================================== 7차 (lead 10-14 7차 지시) — 사용자가 고른 심텍·코리아써키트 같은 종목 고르기
P7_MODEL = {"222800": "심텍", "007810": "코리아써키트"}
P7_PEERS = {"007660": "이수페타시스", "353200": "대덕전자", "195870": "해성디에스", "356860": "티엘비"}
P7_EXITS = {"6차 청산(종가 −20%·+10%·10일)": ("close", 0.20, 0.10, 10), "추세 청산(종가 −10%·+20%·15일)": ("close", 0.10, 0.20, 15)}
P7_ENTRIES = ("눌림25", "D종가", "다음날시가", "눌림5", "눌림10")


def p7_features(prep: str, al: dict) -> pd.DataFrame:
    """5차 특징 + 일봉으로 신고 전 1년 흐름: 1년 수익(ret250), 1년 고가 대비 신고 전날 위치(dd_pre), 1년 고저 배수(run52), 1년 고가 뒤 며칠(since_hi),
    이평 정배열(종가>20>60>120일선), 같은 날 같은 세부 섹터 장부 수(sub_n — 섹터는 오늘 값이라 과거엔 미래 엿봄)."""
    F = s_features(prep, al)
    ev = pd.read_pickle(os.path.join(prep, "vl_ev.pkl")).reset_index(drop=True)
    F["name"], F["val"] = ev.name.to_numpy(), ev.val.to_numpy()
    sm = _sector_map()
    F["sub"] = F.code.map(sm.sector + "/" + sm.sub_sector)
    F["sub_n"] = F.groupby(["date", "sub"]).code.transform("size") - 1
    rows = []
    for r in F.itertuples(index=False):
        o, h, l, c, _ = _ARR[r.code]
        k, lo = r.k, max(0, r.k - 250)
        ma = [c[max(0, k - w + 1):k + 1].mean() for w in (20, 60, 120)]
        rows.append({"ret250": c[k - 1] / c[lo] - 1, "dd_pre": c[k - 1] / h[lo:k].max() - 1, "run52": h[lo:k].max() / l[lo:k].min(),
                     "since_hi": k - (lo + int(np.argmax(h[lo:k]))), "align": float(c[k] > ma[0] > ma[1] > ma[2])})
    return pd.concat([F.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def p7_trades(F: pd.DataFrame, mask: np.ndarray, entry: str, exit_key: str) -> pd.DataFrame:
    kind, x, tgt, hold = P7_EXITS[exit_key]
    rows = []
    for r, ok in zip(F.itertuples(index=False), mask):
        if not ok:
            continue
        o, h, l, c, _ = _ARR[r.code]
        e = entry5(o, h, l, c, r.k, entry)
        if e and e[0] + hold <= len(o) - 1:
            g, xk, why = exit6(o, h, l, c, e[0], e[1], tgt, kind, x, hold, l[r.k], e[2])
            rows.append({"code": r.code, "name": r.name, "D": r.date, "j": e[0], "xk": xk, "buy": e[1], "ret": g, "why": why, "yr": r.yr})
    T = pd.DataFrame(rows, columns=["code", "name", "D", "j", "xk", "buy", "ret", "why", "yr"])
    return T.drop_duplicates(["code", "j"]).reset_index(drop=True)


def p7_rule(F: pd.DataFrame, a: float, b: int, c_: float) -> np.ndarray:
    """1년 수익 ≥ a · 1년 안 앞선 신고 ≥ b 번 · 신고 전날이 1년 고가보다 c_ 이상 아래(조정 뒤 재점화). c_=0 이면 그 조건 없음."""
    return ((F.ret250 >= a) & (F.n250 >= b) & (F.dd_pre <= -c_)).to_numpy()


def part7(prep: str, al: dict) -> dict:
    F = p7_features(prep, al)
    res = {"F": F}
    yr = F.yr.to_numpy()
    tr, te = yr <= 2023, yr >= 2024
    ya = F.ya.to_numpy()
    # 1) 프로파일: 2026-09 장부 전부 + 본보기·같은 무리
    s9 = F[(F.date >= "20260901") & (F.date <= "20260930")].copy()
    s9["본보기"] = s9.code.map(lambda c: "★" if c in P7_MODEL else ("기판" if c in P7_PEERS else ""))
    res["sept"] = s9
    res["peers"] = F[F.code.isin(list(P7_MODEL) + list(P7_PEERS)) & (F.date >= "20260101")]
    # 2) 학습에서 문턱 고르기 — 목표 (가)(뒤 20일 +20% 가 −10% 보다 먼저). 이웃(각 축 한 칸) 평균으로, 학습 건수 ≥ 150
    A, B, C = (0.3, 0.5, 1.0, 2.0), (0, 1, 2), (0.0, 0.10, 0.15, 0.20, 0.30)
    grid = {}
    for a, b, c_ in itertools.product(A, B, C):
        m = p7_rule(F, a, b, c_)
        grid[(a, b, c_)] = (np.nanmean(ya[m & tr]) * 100 if (m & tr).sum() else np.nan, int((m & tr).sum()),
                            np.nanmean(ya[m & te]) * 100 if (m & te).sum() else np.nan, int((m & te).sum()))
    rows = []
    for (a, b, c_), (s_tr, n_tr, s_te, n_te) in grid.items():
        nb = [s_tr]
        for ax, lst in ((0, A), (1, B), (2, C)):
            key = [a, b, c_]
            p = lst.index(key[ax])
            for d_ in (-1, 1):
                if 0 <= p + d_ < len(lst):
                    key2 = list(key)
                    key2[ax] = lst[p + d_]
                    nb.append(grid[tuple(key2)][0])
        rows.append({"1년수익≥": a, "앞선신고≥": b, "1년고가대비≤−": c_, "학습n": n_tr, "학습(가)%": s_tr, "이웃": np.nanmean(nb), "검증n": n_te, "검증(가)%": s_te})
    Gd = pd.DataFrame(rows)
    res["grid"] = Gd
    pick = Gd[Gd.학습n >= 150].sort_values("이웃", ascending=False).iloc[0]
    res["pick"] = pick
    rule = p7_rule(F, pick["1년수익≥"], int(pick["앞선신고≥"]), pick["1년고가대비≤−"])
    sel3 = np.nan_to_num(F.pos3y.to_numpy()) >= 1.0
    res["rule"] = rule
    # 섹터 동반(미래 엿봄 표시) 변형: 셋째 조건을 '같은 날 같은 세부 섹터 장부 ≥1' 로 바꾼 판
    rule_sec = ((F.ret250 >= pick["1년수익≥"]) & (F.n250 >= int(pick["앞선신고≥"])) & (F.sub_n >= 1)).to_numpy()
    sets = {"7차 규칙": rule, "7차 규칙 ∧ 3년 신고가": rule & sel3, "(참고) 7차 앞 두 조건 + 섹터 동반[미래 엿봄]": rule_sec,
            "5·6차 선별(3년 신고가)": sel3, "장부 전체": np.ones(len(F), bool)}
    res["sel_stats"] = {nm: (int((m & tr).sum()), np.nanmean(ya[m & tr]) * 100, int((m & te).sum()), np.nanmean(ya[m & te]) * 100) for nm, m in sets.items()}
    # 3a) 2026-09 에 걸린 종목
    res["sept_hits"] = F[rule & (F.date >= "20260901") & (F.date <= "20260930")][["name", "code", "date", "chg", "ret250", "n250", "dd_pre", "sub"]]
    # 3b) 해마다 걸린 종목 예시(대금 큰 순 5개)
    res["examples"] = {int(y): F[rule & (yr == y)].sort_values("val", ascending=False).drop_duplicates("code").name.head(6).tolist() for y in range(2020, 2027)}
    res["per_year_n"] = {int(y): int((rule & (yr == y)).sum()) for y in range(2020, 2027)}
    # 3c) 매매 성적 — 선별 × 진입 × 청산
    perf, acct = [], {}
    for nm in ("7차 규칙", "7차 규칙 ∧ 3년 신고가", "5·6차 선별(3년 신고가)", "장부 전체"):
        for ent in P7_ENTRIES:
            for ex in P7_EXITS:
                if ent == "눌림25" and ex != "6차 청산(종가 −20%·+10%·10일)":
                    continue
                T = p7_trades(F, sets[nm], ent, ex)
                g = T.ret.to_numpy() - 0.0025
                y_ = T.yr.to_numpy()
                row = {"선별": nm, "진입": ent, "청산": ex}
                for half, m in (("학습", y_ <= 2023), ("검증", y_ >= 2024)):
                    row[f"{half}n"], row[f"{half}평균"] = int(m.sum()), g[m].mean() * 100 if m.sum() else np.nan
                    row[f"{half}승률"] = (g[m] > 0).mean() * 100 if m.sum() else np.nan
                row["검증손절%"] = (T.why[y_ >= 2024] == "손절").mean() * 100 if (y_ >= 2024).sum() else np.nan
                row["검증최악5%"] = np.percentile(g[y_ >= 2024], 5) * 100 if (y_ >= 2024).sum() else np.nan
                row["해별"] = by_year(g, y_)
                perf.append(row)
                if nm != "장부 전체" and (ent, ex) in (("눌림25", "6차 청산(종가 −20%·+10%·10일)"), ("다음날시가", "추세 청산(종가 −10%·+20%·15일)"),
                                                     ("눌림10", "6차 청산(종가 −20%·+10%·10일)")):
                    T["entry"] = [al[cd].date.iat[j] for cd, j in zip(T.code, T.j)]
                    T["exit"] = [al[cd].date.iat[x] for cd, x in zip(T.code, T.xk)]
                    W10 = slot_filter(waves(T), 10)
                    acct[(nm, ent, ex)] = (len(W10), account_curve(W10, al, K=10), account_curve(W10, al, 0.0043, K=10))
    res["perf"], res["acct"] = pd.DataFrame(perf), acct
    # 3d) 지금(자료 마지막 날) 걸린 종목: 신고 뒤 15거래일 안
    now = []
    for r, ok in zip(F.itertuples(index=False), rule):
        o, h, l, c, _ = _ARR[r.code]
        left = 15 - (len(o) - 1 - r.k)
        if ok and left > 0:
            P = h[r.k:].max()
            touched = any(l[j] <= h[r.k:j].max() * 0.75 for j in range(r.k + 1, len(o)))
            now.append({"종목": r.name, "code": r.code, "신고일": r.date, "1년수익%": round(r.ret250 * 100), "앞선신고": int(r.n250), "1년고가대비%": round(r.dd_pre * 100),
                        "신고 뒤 고점": P, "10-13 종가": c[-1], "−25% 살 값": round(P * 0.75), "닿음": "예" if touched else "아니오", "남은 날": left})
    res["now"] = pd.DataFrame(now)
    return res


def print_part7(R: dict) -> None:
    pd.set_option("display.width", 320)
    pd.set_option("display.max_rows", 400)
    cols = ["본보기", "name", "date", "chg", "pos", "val", "x20", "cnt", "n60", "n250", "ret250", "dd_pre", "run52", "since_hi", "since_max", "pos3y", "rs12", "align", "sub", "sub_n", "ya"]
    print("\n========== 7차 1) 2026-09 장부 전부(★ 본보기, 기판 = 같은 무리) ==========")
    print(R["sept"].sort_values("date")[cols].round(2).to_string(index=False))
    print("\n[기판 무리 2026 장부 줄]")
    print(R["peers"][[c for c in cols if c != "본보기"]].round(2).to_string(index=False))
    print("\n========== 2) 문턱 격자(학습에서 고름, 목표 (가)) — 이웃 평균 상위 15 ==========")
    print(R["grid"][R["grid"].학습n >= 150].sort_values("이웃", ascending=False).head(15).round(1).to_string(index=False))
    print(f"[고른 규칙] {dict(R['pick'].round(2))}")
    print("\n[선별별 (가) 성공률 — 학습 n·% / 검증 n·%]")
    for nm, v in R["sel_stats"].items():
        print(f"  {nm}: 학습 {v[0]}건 {v[1]:.1f}% | 검증 {v[2]}건 {v[3]:.1f}%")
    print("\n========== 3a) 2026-09 에 걸린 종목 ==========")
    print(R["sept_hits"].round(2).to_string(index=False))
    print(f"\n[3b) 해마다 걸린 건수] {R['per_year_n']}")
    for y, nm in R["examples"].items():
        print(f"   {y}: {', '.join(nm)}")
    print("\n========== 3c) 매매 성적(비용 0.25% 뒤) ==========")
    print(R["perf"].drop(columns=["해별"]).round(2).to_string(index=False))
    for r in R["perf"].itertuples(index=False):
        if r.선별 != "장부 전체":
            print(f"   {r.선별} · {r.진입} · {r.청산}: {r.해별}")
    print("\n[10칸 계좌(한 종목 10%, 복리 없이 어림)]")
    for (nm, ent, ex), (n, A, A43) in R["acct"].items():
        print(f"  {nm} · {ent} · {ex}: {n}건, 7년 {A['total']:+.1f}%(0.43% {A43['total']:+.1f}%) 최대 낙폭 {A['mdd']:.1f}% · "
              + " · ".join(f"{y} {v['ret']:+.1f}%" for y, v in A["years"].items()))
    print("\n========== 3d) 지금 걸린 종목(신고 뒤 15거래일 안) ==========")
    print(R["now"].to_string(index=False) if len(R["now"]) else "  없음")


# ====================================================================== 8차 (lead 10-15 8차 지시) — 수급(누가 샀나, H-025)을 선별에 넣기
# 자료: data/stocks/investor_daily/{code}.csv (KRX 집계·장 마감 뒤 확정). 비율은 같은 파일의 KRX value_mw 로 나눈다. 가격은 수정주가가 아니라 안 쓴다.
P8_GROUPS = {"외인": ("frgn",), "기관": ("orgn",), "외인+기관": ("frgn", "orgn"), "연기금": ("penfnd",), "사모": ("samo",), "개인": ("ind",)}
P8_WINDOWS = ("D", "앞5", "앞20", "조정중")  # 신고일 · 신고 전 5일 · 신고 전 20일 · 신고 다음날~진입 전날
P8_EXIT = "6차 청산(종가 −20%·+10%·10일)"


def flow_ratio(inv: pd.DataFrame, d0: str, d1: str, cols) -> float:
    """[d0, d1] 날짜(포함) 안 순매수 합 ÷ 거래대금 합(둘 다 KRX). 날이 없으면 NaN."""
    dt = inv.date.to_numpy()
    a, b = np.searchsorted(dt, d0), np.searchsorted(dt, d1, side="right")
    if b <= a:
        return np.nan
    v = inv.value_mw.to_numpy()[a:b].sum()
    return float(sum(inv[c].to_numpy()[a:b].sum() for c in cols) / v) if v > 0 else np.nan


def p8_trades(F: pd.DataFrame, mask: np.ndarray, al: dict) -> pd.DataFrame:
    """6차 매매(−25% 지정가·종가 −20% 손절·+10%·10일) 거래마다 진입 때 알 수 있는 수급 특징을 붙인다(진입 전날까지)."""
    T = p7_trades(F, mask, "눌림25", P8_EXIT)
    cache, feats = {}, []
    for r in T.itertuples(index=False):
        if r.code not in cache:
            p = f"data/stocks/investor_daily/{r.code}.csv"
            cache[r.code] = pd.read_csv(p, dtype={"date": str}) if os.path.isfile(p) else None
        inv = cache[r.code]
        dts = al[r.code].date.to_numpy()
        k = int(np.searchsorted(dts, r.D))
        f = {}
        for g, cols in P8_GROUPS.items():
            for w in P8_WINDOWS:
                if inv is None:
                    f[f"{g}_{w}"] = np.nan
                    continue
                d0, d1 = {"D": (dts[k], dts[k]), "앞5": (dts[max(0, k - 5)], dts[k - 1]), "앞20": (dts[max(0, k - 20)], dts[k - 1]),
                          "조정중": (dts[k + 1], dts[r.j - 1])}[w]
                f[f"{g}_{w}"] = flow_ratio(inv, d0, d1, cols) if (w != "조정중" or r.j - 1 >= k + 1) else np.nan
        feats.append(f)
    T = pd.concat([T, pd.DataFrame(feats)], axis=1)
    T["entry"] = [al[c].date.iat[j] for c, j in zip(T.code, T.j)]
    T["exit"] = [al[c].date.iat[x] for c, x in zip(T.code, T.xk)]
    return T


def p8_search(T: pd.DataFrame, min_n: int, max_k: int = 3) -> tuple[list, pd.DataFrame]:
    """학습만으로: 특징 ≥/≤ 학습 분위(20·30·…·80%) 한 조건씩 욕심내어 최대 3개. 점수 = 학습 평균(비용 뒤),
    단 학습 4년 중 3년 이상 플러스 · 건수 ≥ min_n · 문턱 앞뒤 분위(±10%p) 칸도 학습 평균이 기준(조건 전)보다 높아야 채택."""
    yr = T.yr.to_numpy()
    tr = yr <= 2023
    g = T.ret.to_numpy() - 0.0025
    feats = [c for c in T.columns if "_" in c and c.split("_")[0] in P8_GROUPS]
    qs = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)

    def sc(m):
        mt = m & tr
        if mt.sum() < min_n:
            return None
        if sum(g[m & (yr == y)].mean() > 0 for y in range(2020, 2024) if (m & (yr == y)).sum() >= 5) < 3:
            return None
        return float(g[mt].mean())
    chosen, m0, log = [], np.ones(len(T), bool), []
    for _ in range(max_k):
        base = sc(m0)
        best = None
        for f in feats:
            if any(c[0] == f for c in chosen):
                continue
            x = T[f].to_numpy(float)
            cut = np.nanquantile(x[tr & m0], qs)
            for qi, q in enumerate(qs):
                for side in (">=", "<="):
                    mm = m0 & np.isfinite(x) & ((x >= cut[qi]) if side == ">=" else (x <= cut[qi]))
                    s = sc(mm)
                    if s is None or base is None or s <= base:
                        continue
                    nbs = []
                    for d_ in (-1, 1):
                        if 0 <= qi + d_ < len(qs):
                            m2 = m0 & np.isfinite(x) & ((x >= cut[qi + d_]) if side == ">=" else (x <= cut[qi + d_]))
                            nbs.append(sc(m2))
                    if any(v is None or v <= base for v in nbs):
                        continue
                    if best is None or s > best[0]:
                        best = (s, f, side, float(cut[qi]), q, mm)
        if best is None:
            break
        chosen.append(best[1:5])
        m0 = best[5]
        log.append({"조건": f"{best[1]} {best[2]} {best[3]:.4f}(학습 {int(best[4] * 100)}% 분위)", "학습평균": best[0] * 100, "학습n": int((m0 & tr).sum()),
                    "검증평균": g[m0 & ~tr].mean() * 100, "검증n": int((m0 & ~tr).sum())})
    return chosen, pd.DataFrame(log)


def p8_mask(T: pd.DataFrame, conds) -> np.ndarray:
    m = np.ones(len(T), bool)
    for f, side, thr, _ in conds:
        x = T[f].to_numpy(float)
        m &= np.isfinite(x) & ((x >= thr) if side == ">=" else (x <= thr))
    return m


def p8_quint(T: pd.DataFrame) -> pd.DataFrame:
    yr, g = T.yr.to_numpy(), T.ret.to_numpy() - 0.0025
    tr = yr <= 2023
    rows = []
    for f in [c for c in T.columns if "_" in c and c.split("_")[0] in P8_GROUPS]:
        x = T[f].to_numpy(float)
        ok = np.isfinite(x)
        if (ok & tr).sum() < 100:
            continue
        cuts = np.nanquantile(x[ok & tr], [0.2, 0.4, 0.6, 0.8])
        b = np.searchsorted(cuts, x, side="right")
        rt = [g[ok & tr & (b == q)].mean() * 100 for q in range(5)]
        re_ = [g[ok & ~tr & (b == q)].mean() * 100 for q in range(5)]
        rows.append({"특징": f, "학습 1→5분위": " ".join(f"{v:+.1f}" for v in rt), "검증 1→5분위": " ".join(f"{v:+.1f}" for v in re_),
                     "차_학습": rt[-1] - rt[0], "차_검증": re_[-1] - re_[0], "같은방향": bool(np.sign(rt[-1] - rt[0]) == np.sign(re_[-1] - re_[0]))})
    return pd.DataFrame(rows).sort_values("차_학습", key=abs, ascending=False)


def p8_summary(T: pd.DataFrame, m: np.ndarray, al: dict) -> dict:
    yr, g = T.yr.to_numpy(), T.ret.to_numpy()
    out = {}
    for half, hm in (("학습", yr <= 2023), ("검증", yr >= 2024)):
        x = g[m & hm] - 0.0025
        out[half] = {"n": len(x), "평균": x.mean() * 100 if len(x) else np.nan, "중앙": np.median(x) * 100 if len(x) else np.nan,
                     "승률": (x > 0).mean() * 100 if len(x) else np.nan, "손절%": (T.why.to_numpy()[m & hm] == "손절").mean() * 100 if len(x) else np.nan,
                     "최악5%": np.percentile(x, 5) * 100 if len(x) else np.nan, "평균43": (x - 0.0018).mean() * 100 if len(x) else np.nan}
    out["해별"] = by_year(np.where(m, g - 0.0025, np.nan), yr)
    W10 = slot_filter(waves(T[m]), 10)
    out["acct"] = (len(W10), account_curve(W10, al, K=10), account_curve(W10, al, 0.0043, K=10))
    return out


def part8(prep: str, al: dict) -> dict:
    F = p7_features(prep, al)
    sel3 = np.nan_to_num(F.pos3y.to_numpy()) >= 1.0
    s7 = p7_rule(F, 0.5, 2, 0.15)
    res = {}
    for nm, mask, min_n in (("3년 신고가(6차)", sel3, 150), ("2차 상승(7차)", s7, 50)):
        T = p8_trades(F, mask, al)
        conds, log = p8_search(T, min_n)
        m = p8_mask(T, conds)
        # 문턱 흔들기: 고른 조건마다 분위를 ±10%p·±20%p 옮겨 검증까지 본다
        shake = []
        tr = T.yr.to_numpy() <= 2023
        for i, (f, side, thr, q) in enumerate(conds):
            x = T[f].to_numpy(float)
            others = p8_mask(T, [c for jx, c in enumerate(conds) if jx != i])
            for dq in (-0.2, -0.1, 0.0, 0.1, 0.2):
                q2 = min(max(q + dq, 0.05), 0.95)
                t2 = np.nanquantile(x[tr & np.isfinite(x)], q2)
                mm = others & np.isfinite(x) & ((x >= t2) if side == ">=" else (x <= t2))
                g = T.ret.to_numpy() - 0.0025
                shake.append({"조건": f"{f} {side}", "분위": round(q2, 2), "학습n": int((mm & tr).sum()), "학습평균": g[mm & tr].mean() * 100,
                              "검증n": int((mm & ~tr).sum()), "검증평균": g[mm & ~tr].mean() * 100})
        res[nm] = {"T": T, "quint": p8_quint(T), "conds": conds, "log": log, "shake": pd.DataFrame(shake),
                   "base": p8_summary(T, np.ones(len(T), bool), al), "flow": p8_summary(T, m, al) if conds else None,
                   "cover": float(np.isfinite(T["외인_D"]).mean() * 100)}
    return res


def print_part8(R: dict) -> None:
    pd.set_option("display.width", 300)
    pd.set_option("display.max_rows", 300)
    for nm, r in R.items():
        print(f"\n========== 8차 [{nm}] 6차 매매에 수급 붙이기 — 거래 {len(r['T']):,}건, 수급 붙은 비율 {r['cover']:.1f}% ==========")
        print("[특징별 5분위 거래당 평균(비용 뒤 %) — 학습 / 검증]")
        print(r["quint"].round(2).to_string(index=False))
        print("\n[학습에서 고른 조건(욕심내어 하나씩, 최대 3개)]")
        print(r["log"].round(2).to_string(index=False) if len(r["log"]) else "  고를 조건 없음(문턱 앞뒤 칸까지 받쳐 주는 조건이 없다)")
        if len(r["shake"]):
            print("[문턱 흔들기]")
            print(r["shake"].round(2).to_string(index=False))
        for lab, s in (("수급 안 붙임(6차)", r["base"]), ("수급 붙임(8차)", r["flow"])):
            if s is None:
                continue
            a, b = s["학습"], s["검증"]
            n10, A, A43 = s["acct"]
            print(f"\n[{lab}] 학습 {a['n']}건 {a['평균']:+.2f}% 중앙 {a['중앙']:+.2f} 승 {a['승률']:.0f}% 손절 {a['손절%']:.0f}% | 검증 {b['n']}건 {b['평균']:+.2f}%(0.43% {b['평균43']:+.2f})"
                  f" 중앙 {b['중앙']:+.2f} 승 {b['승률']:.0f}% 손절 {b['손절%']:.0f}% 최악5% {b['최악5%']:.1f}\n   해별 {s['해별']}\n   10칸 {n10}건 7년 {A['total']:+.1f}%(0.43% {A43['total']:+.1f}%)"
                  f" 최대 낙폭 {A['mdd']:.1f}% · " + " · ".join(f"{y} {v['ret']:+.1f}%(낙폭 {v['mdd']:.1f})" for y, v in A["years"].items()))


# ====================================================================== 출력
def fmt(s: dict) -> str:
    return f"n={s['n']:,} 평균 {s['mean']:+.2f}% 중앙 {s['med']:+.2f}% 승률 {s['win']:.0f}%" if s["n"] else "n=0"


def _self_check() -> None:
    """손계산 한 건: 진입 100, 둘째 날 시가 99·저가 94(손절 5% = 95 먼저), 익절 10% 는 안 닿음 → 95 − 비용."""
    fw = np.full((1, LAST + 1, 4), 100.0)
    fw[0, 1] = (100, 101, 99, 100)
    fw[0, 2] = (99, 112, 94, 100)
    r = simulate(fw, np.array([1]), np.array([100.0]), 5, 5, 10, True)
    assert abs(r[0] - (0.95 - 1 - COST)) < 1e-12, r
    fw[0, 2] = (90, 91, 89, 90)  # 시가가 이미 손절선 아래 → 시가 체결
    r = simulate(fw, np.array([1]), np.array([100.0]), 5, 5, 10, True)
    assert abs(r[0] - (0.90 - 1 - COST)) < 1e-12, r
    # 2차: 분봉 청산 — 손절 98 이 둘째 봉 저가 97 에 먼저 닿는다
    m = np.array([540, 541, 542]); o = np.array([100.0, 99.5, 99.0]); h = np.array([101.0, 100.0, 99.5])
    l = np.array([99.5, 97.0, 98.5]); c = np.array([100.0, 98.0, 99.0])
    assert bar_exit(m, o, h, l, c, 0, 100.0, 98.0, 629) == (98.0, "stop")
    assert bar_exit(m, o, h, l, c, 0, 100.0, 90.0, 629) == (99.0, "time")
    # 4차: 신고 고가 100 → 이틀째 저가 79 (−20% = 80 지정가), 전날 대금 70% 유지 → 80 매수, 다음날 고가 90 → +10%(88) 익절
    o = np.array([90.0, 95, 85, 86, 86]); h = np.array([100.0, 96, 86, 90, 87]); l = np.array([88.0, 90, 79, 85, 85]); c = np.array([99.0, 92, 82, 86, 85])
    t = pull_trade(o, h, l, c, np.array([10.0, 7, 5, 5, 5]), 0, maxday=3, hold=2)
    assert t["buy"] == 80 and t["why"] == "익절" and t["xk"] == 3 and abs(t["ret"] - 0.10) < 1e-12, t
    assert pull_trade(o, h, l, c, np.array([10.0, 5, 5, 5, 5]), 0, maxday=3, hold=2) is None  # 전날 대금 50% → 식음 → 안 산다
    # 6차 exit6: (1) 종가 손절 — 산 날 종가 91 < 92(−8%) → 다음날 시가 90 에 판다
    o = np.array([100.0, 90, 95]); h = np.array([101.0, 96, 99]); l = np.array([95.0, 89, 94]); c = np.array([91.0, 95, 96])
    assert exit6(o, h, l, c, 0, 100.0, 0.5, "close", 0.08, 2) == (-0.09999999999999998, 1, "손절") or abs(exit6(o, h, l, c, 0, 100.0, 0.5, "close", 0.08, 2)[0] + 0.10) < 1e-12
    # (2) 트레일 −15%: 다음날 고가 120(최고가 갱신) → 그다음 날 저가 100 이 120×0.85=102 아래 → 102 에 판다(+2%)
    o = np.array([100.0, 105, 110]); h = np.array([101.0, 120, 112]); l = np.array([99.0, 104, 100]); c = np.array([100.0, 115, 101])
    r6 = exit6(o, h, l, c, 0, 100.0, 0.5, "trail", 0.15, 2)
    assert abs(r6[0] - 0.02) < 1e-12 and r6[1:] == (2, "손절"), r6
    # (3) 같은 날 손절(−5% = 95)·익절(+10% = 110) 둘 다 → 손절 먼저
    o = np.array([100.0, 100]); h = np.array([100.0, 111]); l = np.array([100.0, 94]); c = np.array([100.0, 105])
    assert exit6(o, h, l, c, 0, 100.0, 0.10, "fix", 0.05, 1)[2] == "손절"
    # 7차 규칙: 1년 수익·앞선 신고 횟수·1년 고가 대비 — 셋 다 맞아야 걸린다
    t7 = pd.DataFrame({"ret250": [2.0, 2.0, 0.2, 2.0], "n250": [2, 0, 3, 2], "dd_pre": [-0.3, -0.3, -0.3, -0.05]})
    assert p7_rule(t7, 1.0, 1, 0.15).tolist() == [True, False, False, False]
    assert p7_rule(t7, 1.0, 1, 0.0).tolist() == [True, False, False, True]
    # 8차 수급 비율: 이틀 합 순매수 (10+30) ÷ 대금 (100+100) = 0.2, 범위 밖 날은 안 센다
    inv = pd.DataFrame({"date": ["20200101", "20200102", "20200103"], "value_mw": [100.0, 100.0, 100.0], "frgn": [10.0, 30.0, 99.0], "orgn": [5.0, 5.0, 5.0]})
    assert abs(flow_ratio(inv, "20200101", "20200102", ("frgn",)) - 0.2) < 1e-12
    assert abs(flow_ratio(inv, "20200102", "20200102", ("frgn", "orgn")) - 0.35) < 1e-12
    assert np.isnan(flow_ratio(inv, "20200104", "20200105", ("frgn",)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prep", default=PREP)
    ap.add_argument("--skip-b", action="store_true")
    ap.add_argument("--part2", action="store_true", help="2차(C·D)만")
    ap.add_argument("--part3", action="store_true", help="3차(E·F)만")
    ap.add_argument("--part4", action="store_true", help="4차(G·H·I)만")
    ap.add_argument("--part5", action="store_true", help="5차(선별 점수 → 진입·청산)만")
    ap.add_argument("--part6", action="store_true", help="6차(손절 있는 규칙)만")
    ap.add_argument("--part7", action="store_true", help="7차(심텍·코리아써키트 같은 종목 고르기)만")
    ap.add_argument("--part8", action="store_true", help="8차(수급을 선별에)만")
    a = ap.parse_args()
    _self_check()
    pd.set_option("display.width", 250)
    if a.part8:
        al = load_al_all()
        R = part8(a.prep, al)
        print_part8(R)
        pd.to_pickle(R, os.path.join(a.prep, "vl_strategy_part8.pkl"))
        return
    if a.part7:
        al = load_al_all()
        R = part7(a.prep, al)
        print_part7(R)
        pd.to_pickle(R, os.path.join(a.prep, "vl_strategy_part7.pkl"))
        return
    if a.part6:
        al = load_al_all()
        R = part6(a.prep, al)
        print_part6(R)
        pd.to_pickle({k: v for k, v in R.items()}, os.path.join(a.prep, "vl_strategy_part6.pkl"))
        return
    if a.part5:
        al = load_al_all()
        R = part5(a.prep, al)
        print_part5(R)
        pd.to_pickle(R, os.path.join(a.prep, "vl_strategy_part5.pkl"))
        return
    if a.part4:
        al = load_al_all()
        G, H, I = part_g(a.prep, al), part_h(a.prep, al), part_i(a.prep, al)
        print_part4(G, H, I)
        pd.to_pickle({"G": G, "H": H, "I": I}, os.path.join(a.prep, "vl_strategy_part4.pkl"))
        return
    if a.part3:
        al = load_al_all()
        Ex, Fx = part_e(a.prep, al), part_f(a.prep, al)
        print_part3(Ex, Fx)
        pd.to_pickle({"E": {k: v for k, v in Ex.items()}, "F": Fx}, os.path.join(a.prep, "vl_strategy_part3.pkl"))
        return
    if a.part2:
        al = load_al_all()
        C, D = part_c(a.prep, al), part_d(a.prep, al)
        print_part2(C, D)
        pd.to_pickle({"C": C, "D": D}, os.path.join(a.prep, "vl_strategy_part2.pkl"))
        return
    A = part_a(a.prep)
    print("\n[A ①] 신고일 종가 → 다음날 시가(하룻밤):", "학습", fmt(A["overnight"]["tr"]), "| 검증", fmt(A["overnight"]["te"]))
    print("     연도별 평균:", {int(y): round(float(v), 2) for y, v in A["overnight"]["years"].items()})
    cols = ["entry", "hold", "stop", "tgt", "fill_tr", "fill_te", "tr_n", "tr_mean", "tr_med", "tr_win", "robust", "te_n", "te_mean", "te_med", "te_win"]
    print("\n[A] 진입 종류마다 학습 '이웃 평균' 최고 칸 (검증은 그대로)")
    print(A["per_entry"][cols].round(2).to_string(index=False))
    print("\n[A] 전체 상위 15 (이웃 평균 순)")
    print(A["grid"].sort_values("robust", ascending=False)[cols].head(15).round(2).to_string(index=False))
    print("\n[A] 기준선 — 다음날 시가 사서 N일 들고 가기(손절·익절 없음)")
    print(A["grid"][(A["grid"].entry == "다음날시가") & (A["grid"].stop == 0) & (A["grid"].tgt == 0)][cols].round(2).to_string(index=False))
    print("\n[A] 추천 후보(학습만으로: 이웃 평균>0·학습 평균>0·학습 4년 중 3년 이상 양수) 상위 10")
    print(A["eligible"][cols + ["tr_pos_years"]].head(10).round(2).to_string(index=False))
    t = A["top"]
    print(f"\n[A] 추천 1위 {t.entry} · 보유 {t.hold}일 · 손절 {t.stop} · 익절 {t.tgt} (한 건 최악 {A['top_worst']:.1f}%) 연도별:")
    for y, s in A["top_years"].items():
        print(f"   {y}: {fmt(s)}")
    for label, flist in (("추천 규칙", A["filters"]), ("하룻밤", A["filters_overnight"])):
        print(f"\n[A] 조건 필터 — {label} (학습에서만 고름)")
        for f in flist:
            print(f"   {f['f']} {f['side']} {f['q']:.3g} — 학습 {fmt(f['tr'])} (+{f['tr_gain']:.2f}%p, 4년 중 {f['yrs_better']}년 나음) | 검증 {fmt(f['te'])} (필터 없는 검증 {fmt(f['te_base'])})")
            print("      연도별:", {int(y): round(float(v), 2) for y, v in f["years"].items()})
        if not flist:
            print("   뚜렷한 조건 없음")
    if a.skip_b:
        return
    B = part_b(a.prep)
    bcols = ["entry", "stop", "tgt", "fill", "h1_n", "h1_mean", "h1_med", "h1_win", "robust", "h2_n", "h2_mean", "h2_med", "h2_win"]
    for tag, b in B.items():
        g = b["grid"]
        print(f"\n[B:{tag}] 다음 날 09:00~10:30 · 날짜 {b['range']} · 앞 반쪽(~2026-01)에서 고르고 뒤 반쪽 그대로" if tag == "KRX 분봉" else f"\n[B:{tag}] 다음 날 09:00~10:30 · 날짜 {b['range']} (전부 한 묶음 — h1 칸)")
        if not len(g):
            print("   자료 없음")
            continue
        print(g.sort_values("robust", ascending=False)[bcols].head(12).round(2).to_string(index=False))
        print("   손절·익절 없는 기본(진입 종류별):")
        print(g[(g.stop == 0) & (g.tgt == 0)][bcols].round(2).to_string(index=False))
    pd.to_pickle({"A": {k: v for k, v in A.items()}, "B": B}, os.path.join(a.prep, "vl_strategy_result.pkl"))


if __name__ == "__main__":
    sys.path.insert(0, os.getcwd())
    main()
