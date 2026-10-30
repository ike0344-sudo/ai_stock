"""재매수 금지(+24%, 시총 1조↑ +20%)를 우리 데이터로 학습한 작은 모델이 이기나(10-22 사용자 "백테스트 지금 바로").

데스크 60선 매수 규칙(ma60c23)·청산(xmvhkz70u)을 trader.backtest.simulate 로 두 번 돈다 — 재매수 금지 끈 판(모든 닿음 = 시험지)과 켠 판(규칙).
끈 판의 진입마다 [그 순간까지 알던 값] + [결과(청산 규칙대로 판 손익, 1·3·5일 뒤 종가 손익)]. 켠 판에도 있으면 '규칙이 샀다'.
날짜 순 앞 70% 학습(문턱도 여기서) / 뒤 30% 채점. 정규장(KRX) 1분봉 — 통합 분봉은 2026-08-24부터라 1년 표본은 정규장으로(애프터 60선 단계는 그 전엔 못 산다).
비용(수수료 각 0.015%·매도세 0.20%) 뺀 값, 슬리피지 없음. 로컬 데이터만(키움 조회 없음), 결과는 state/trader/learn_peak.json.

    python -m trader.learn_peak [--start 2025-07-01] [--end 2026-10-21]
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from bisect import bisect_left, bisect_right

import numpy as np

from . import backtest as bt
from . import engine

COST = bt.FEE * 2 + bt.TAX
FEATS = {  # 이름 -> 쉬운 말
    "rise": "기준일 종가 대비 그 뒤(어제까지) 최고가 상승률",
    "rise_anchor": "첫 신고대금 날 종가 대비 어제까지 최고가 상승률(규칙의 재료)",
    "days": "기준일 뒤 경과 거래일",
    "pull": "산 가격 / 기준일 종가 − 1",
    "chg_prev": "산 가격 / 전날 종가 − 1(그날 등락)",
    "rd_chg": "기준일 등락률",
    "rd_val": "기준일 정규장 대금(억, log)",
    "mcap": "시총(억, log)",
    "ma_slope": "15분봉 60선 하루 전 대비 기울기",
    "from_hi": "산 가격 / 어제까지 최고가 − 1",
}


def run(start: str, end: str) -> dict:
    bt._status = lambda **k: None
    R = json.loads((bt.STATE / "rules.json").read_text(encoding="utf-8"))
    base = next(r for r in R["rules"] if r["id"] == "ma60c23")
    ex = next(x for x in R["exits"] if x["id"] == base["exit"])["exits"]
    safety = {**R["safety"], "max_positions": "0", "buy_mode": "cash"}     # 진입끼리 자리·돈을 안 다투게 — 판단 하나하나를 독립으로
    rule = copy.deepcopy(base)
    rule["amount"] = "10000000"                                            # 종목당 1천만(단계 50%씩)

    def sim(pk_on: bool):
        r = copy.deepcopy(rule)
        r["ladder"]["peak_stop"]["on"] = pk_on
        t0 = time.time()
        out = bt.simulate(r, ex, safety, 1e13, start, end, 0, "reg", "ledger", None)
        print(f"  simulate 재매수 금지 {'켬' if pk_on else '끔'}: 진입 {len({t['entry_id'] for t in out[2]})} · {time.time() - t0:.0f}초 · 건너뜀 "
              f"{ {k: v for k, v in out[4].items() if v and k not in ('conds_ignored', 'conds_used')} }", flush=True)
        return out
    evs, codes, tr_off, _, _ = sim(False)
    _, _, tr_on, _, _ = sim(True)
    on_keys = {(t["code"], str(t["entry_ts"])) for t in tr_on}

    # 진입 묶기 — 같은 entry_id(같은 예약에서 처음 산 뒤 다 팔 때까지)
    ent: dict = {}
    for t in tr_off:
        e = ent.setdefault(t["entry_id"], {"code": t["code"], "name": t["name"], "ts": t["entry_ts"], "cost": 0.0, "net": 0.0, "px": t["entry_price"]})
        e["cost"] += t["entry_price"] * t["qty"]
        e["net"] += t["net_pnl"]
    off_keys = {(e["code"], str(e["ts"])) for e in ent.values()}
    on_only = len(on_keys - off_keys)

    from backtesting.value_ledger import regular_daily_rows
    facts = bt._daily_facts()
    MA = bt.load_ma(sorted({e["code"] for e in ent.values()}), "reg")
    ledger = json.loads((bt.ROOT / "static" / "dashboard" / "value_ledger.json").read_text(encoding="utf-8"))["rows"]
    ledger_days: dict = {}
    for x in ledger:
        if x[17] is not None:
            ledger_days.setdefault(x[1], []).append((x[0], x[20] if x[20] is not None else x[7]))
    evmap: dict = {}
    for rd, c, _, bp in evs:
        evmap.setdefault(c, []).append((rd.replace("-", ""), bp))
    chg_of = {(x[0].replace("-", ""), x[1]): x[20] for x in ledger}
    daily: dict = {}

    rows = []
    for e in sorted(ent.values(), key=lambda e: e["ts"]):
        c, ts = e["code"], e["ts"]
        d = ts.strftime("%Y%m%d")
        if c not in daily:
            dr = regular_daily_rows(c) or []
            daily[c] = ([x[0] for x in dr], dr)
        dd, dr = daily[c]
        cand = [x for x in evmap.get(c, []) if x[0] <= d]
        if not cand or not dd:
            continue
        rd, bp = max(cand)
        i_rd, i_d = bisect_left(dd, rd), bisect_left(dd, d)
        if i_d >= len(dd) or dd[i_d] != d or i_rd >= len(dd) or dd[i_rd] != rd:
            continue
        hi_prev = max((dr[i][2] for i in range(i_rd + 1, i_d)), default=dr[i_rd][2])
        anchor = engine.peak_anchor(ledger_days.get(c, []), f"{rd[:4]}-{rd[4:6]}-{rd[6:]}", 21, 10)
        ia = bisect_left(dd, anchor.replace("-", "")) if anchor else i_rd
        ac = dr[ia][4] if ia < len(dd) else bp
        hi_anchor = max((dr[i][2] for i in range(ia + 1, i_d)), default=dr[ia][2] if ia < len(dd) else bp)
        a = MA.get(c)
        slope = None
        if a:
            j = int(a[0].searchsorted(ts.value, "right")) - 1
            if j - 78 >= 0 and a[1][j - 78]:
                slope = float(a[1][j]) / float(a[1][j - 78]) - 1
        sh = facts.shares.get(c)
        px = e["px"]
        r = {"code": c, "name": e["name"], "ts": str(ts), "rule_buy": (c, str(ts)) in on_keys,
             "rise": hi_prev / bp - 1, "rise_anchor": hi_anchor / ac - 1 if ac else None, "days": i_d - i_rd, "pull": px / bp - 1,
             "chg_prev": px / dr[i_d - 1][4] - 1 if i_d else None, "rd_chg": chg_of.get((rd, c)),
             "rd_val": float(np.log10(max(dr[i_rd][4] * dr[i_rd][5] / 1e8, 1))), "mcap": float(np.log10(sh * bp / 1e8)) if sh else None,
             "ma_slope": slope, "from_hi": px / max(hi_prev, dr[i_rd][2]) - 1,
             "net": e["net"], "net_pct": e["net"] / e["cost"]}
        for n in (1, 3, 5):
            r[f"d{n}"] = dr[i_d + n][4] / px - 1 - COST if i_d + n < len(dd) else None
        rows.append(r)
    return {"rows": rows, "on_only": on_only, "n_on": len(on_keys)}


def evaluate(rows: list) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.tree import DecisionTreeClassifier
    keys = list(FEATS)
    X = np.array([[np.nan if r[k] is None else r[k] for k in keys] for r in rows], dtype=float)
    med = np.nanmedian(X[: int(len(X) * 0.7)], axis=0)                    # 빈 값은 학습 구간 중앙값으로
    X = np.where(np.isnan(X), med, X)
    y = np.array([r["net"] > 0 for r in rows])
    net = np.array([r["net"] for r in rows])
    cut = int(len(rows) * 0.7)
    sc = StandardScaler().fit(X[:cut])
    lr = LogisticRegression(max_iter=1000).fit(sc.transform(X[:cut]), y[:cut])
    tree = DecisionTreeClassifier(max_depth=3, min_samples_leaf=max(20, cut // 40), random_state=0).fit(X[:cut], y[:cut])

    def pick(p_tr):                                                       # 문턱: 학습 구간 손익 합이 가장 큰 확률 — 앞 구간에서만
        best = max(np.arange(0.2, 0.81, 0.02), key=lambda th: net[:cut][p_tr >= th].sum())
        return float(best)
    th_lr = pick(lr.predict_proba(sc.transform(X[:cut]))[:, 1])
    th_tr = pick(tree.predict_proba(X[:cut])[:, 1])
    buy = {"(a) 닿으면 전부 삼": np.ones(len(rows), bool),
           "(b) +24% 규칙": np.array([r["rule_buy"] for r in rows]),
           "(c) 로지스틱": lr.predict_proba(sc.transform(X))[:, 1] >= th_lr,
           "(c2) 얕은 트리": tree.predict_proba(X)[:, 1] >= th_tr}

    def score(m, idx):
        b, nb = idx[m[idx]], idx[~m[idx]]
        pct = np.array([rows[i]["net_pct"] for i in b])
        return {"n": int(len(b)), "win": round(float((net[b] > 0).mean()), 3) if len(b) else None, "avg_pct": round(float(pct.mean() * 100), 2) if len(b) else None,
                "sum": int(net[b].sum()), "avoided_loss": int(-net[nb][net[nb] < 0].sum()), "missed_profit": int(net[nb][net[nb] > 0].sum()),
                "d1": round(float(np.nanmean([rows[i]["d1"] if rows[i]["d1"] is not None else np.nan for i in b]) * 100), 2) if len(b) else None}
    te = np.arange(cut, len(rows))
    h = cut + (len(rows) - cut) // 2
    out = {"n_all": len(rows), "train": [rows[0]["ts"][:10], rows[cut - 1]["ts"][:10], cut], "test": [rows[cut]["ts"][:10], rows[-1]["ts"][:10], len(te)],
           "th": {"lr": th_lr, "tree": th_tr},
           "test_all": {k: score(m, te) for k, m in buy.items()},
           "test_h1": {k: score(m, np.arange(cut, h)) for k, m in buy.items()},
           "test_h2": {k: score(m, np.arange(h, len(rows))) for k, m in buy.items()},
           "train_all": {k: score(m, np.arange(cut)) for k, m in buy.items()}}
    # 특징 하나씩 — 학습 구간에서 이긴 진입/진 진입 평균, 로지스틱 무게(표준화), 트리 중요도
    feat = {}
    for j, k in enumerate(keys):
        w, l_ = X[:cut][y[:cut], j], X[:cut][~y[:cut], j]
        feat[k] = {"desc": FEATS[k], "win_mean": round(float(w.mean()), 4), "loss_mean": round(float(l_.mean()), 4),
                   "lr_w": round(float(lr.coef_[0][j]), 3), "tree_imp": round(float(tree.feature_importances_[j]), 3)}
    out["features"] = feat
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-07-01")
    ap.add_argument("--end", default="2026-10-21")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.time()
    data = run(a.start, a.end)
    res = evaluate(data["rows"])
    res.update(on_only=data["on_only"], n_on=data["n_on"], sec=round(time.time() - t0), start=a.start, end=a.end)
    (bt.STATE / "learn_peak.json").write_text(json.dumps({"result": res, "rows": data["rows"]}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
