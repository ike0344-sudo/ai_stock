"""기준봉이 같은 테마에서 몰려 나왔을 때 vs 혼자 나왔을 때 — 240일 신고가 돌파율 비교 (사용자 2026-10-04, 심텍·디아이·SFA반도체가 같이 움직인 것에서).

    python research/theme_cluster.py       (먼저 research/breakout_shapes.py 를 돌려 summary.csv 가 있어야 함)

- 사건 = breakout_shapes 의 976건(신고가 전 25% 이내 기준봉), 결과도 그대로(20거래일 안 종가 돌파/터치만/실패).
- 동료 기준봉 = 아무 종목이나 그날 통합 대금이 역대/4년/1년 최대 또는 평소 대비(tiers_of) + 1,000억 이상 + +7% 이상인 날
  (신고가 거리 조건 없음 — 테마에 돈이 들어왔는지만 본다).
- 같은 테마 판정 두 가지:
  A. 인포스탁 데일리 테마: 그날 글의 표(sections[].table)에 같은 테마로 묶인 종목(2022-02 이후만, 그날 표에 없으면 '판정 불가')
  B. 스탁이지 세부섹터(data/sectors_stockeasy.csv, 고정 분류)
- 몰림 = 사건일 ±1거래일 안에 같은 테마 동료 기준봉이 1개 이상.
"""
from __future__ import annotations

import glob
import json
import os
import sys

import pandas as pd

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from backtesting.value_burst import tiers_of  # noqa: E402

days = pd.read_csv("data/stocks/daily/005930.csv").date.tolist()
dix = {d: i for i, d in enumerate(days)}

# 동료 기준봉 전부
peers = []
for f in glob.glob("data/stocks/daily_al/*.csv"):
    code = os.path.basename(f)[:6]
    kp = f"data/stocks/daily/{code}.csv"
    if not os.path.exists(kp):
        continue
    a = pd.read_csv(f, dtype={"date": str}).dropna(subset=["value_mw"]).sort_values("date").reset_index(drop=True)
    if len(a) < 300:
        continue
    d = pd.read_csv(kp)
    d["d8"] = d.date.str.replace("-", "")
    t = tiers_of(a.value_mw / 100, a.date.map(dict(zip(d.d8, d.close))))
    a["tier"], a["val"] = t, a.value_mw / 100
    a["date"] = a.date.str[:4] + "-" + a.date.str[4:6] + "-" + a.date.str[6:]
    a["chg"] = a.date.map(dict(zip(d.date, d.close / d.close.shift(1) - 1)))
    for r in a[a.tier.notna() & (a.val >= 1000) & (a.chg >= 0.07)].itertuples():
        if r.date in dix:
            peers.append((code, dix[r.date]))
peers = pd.DataFrame(peers, columns=["code", "di"])
print("동료 기준봉", len(peers))

# 인포스탁: 날짜 → 코드 → 테마들
info = {}
for f in glob.glob("data/news/infostock_daily/*.json"):
    j = json.load(open(f, encoding="utf-8"))
    m = {}
    for s in j.get("sections", []):
        for row in s.get("table", []) or []:
            if row.get("code"):
                m.setdefault(row["code"], set()).add(row.get("theme", ""))
    info[j["date"]] = m
se = pd.read_csv("data/sectors_stockeasy.csv", dtype=str, encoding="utf-8-sig")
sub = dict(zip(se.code, se.sub_sector))

ev = pd.read_csv("results/breakout_shapes/summary.csv", dtype={"code": str})
ev["di"] = ev.date.map(dix)
rows = []
for r in ev.itertuples():
    near = peers[(peers.di - r.di).abs().le(1) & (peers.code != r.code)]
    # B. 세부섹터
    s = sub.get(r.code)
    nb = int((near.code.map(sub) == s).sum()) if s and s != "미분류" else None
    # A. 인포스탁 (사건일 표에 이 종목이 있어야 판정)
    mine = info.get(r.date, {}).get(r.code)
    if r.date not in info or not mine:
        na = None
    else:
        na = sum(1 for p in near.itertuples() if mine & info.get(days[p.di], {}).get(p.code, set()))
    rows.append(dict(outcome=r.outcome, days=r.days, info_peers=na, sub_peers=nb, year=r.date[:4]))
df = pd.DataFrame(rows)


def show(col, title):
    x = df.dropna(subset=[col]).copy()
    x["무리"] = pd.cut(x[col], [-1, 0, 2, 999], labels=["혼자", "1~2개 같이", "3개 이상 같이"])
    g = x.groupby("무리", observed=True)
    t = g.outcome.value_counts(normalize=True).unstack().reindex(columns=["돌파", "터치만", "실패"]) * 100
    t.insert(0, "건수", g.size())
    t["돌파까지(중앙)"] = g.apply(lambda q: q[q.outcome == "돌파"].days.median())
    print(f"\n[{title}] 판정 가능 {len(x)}건")
    print(t.round(1).to_string())


pd.set_option("display.width", 200)
show("info_peers", "A. 인포스탁 데일리 테마 (2022-02~)")
show("sub_peers", "B. 스탁이지 세부섹터")
# 기간 나눠 보기(B)
x = df.dropna(subset=["sub_peers"]).copy()
x["몰림"] = x.sub_peers > 0
x["기간"] = x.year.map(lambda y: "2020-21" if y < "2022" else ("2022-23" if y < "2024" else "2024-26"))
print("\n[B 기간별 돌파율 %]")
print((x.groupby(["기간", "몰림"]).outcome.apply(lambda s: (s == "돌파").mean() * 100).unstack().round(1)).to_string())
print(x.groupby(["기간", "몰림"]).size().unstack().to_string())
