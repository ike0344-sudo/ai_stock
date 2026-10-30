"""데스크 판단 성적표 — 산 것 · 막은 것 · 안 사고 끝난 것이 그 뒤 어떻게 됐나(10-22 사용자 "학습").

예약 기록(state/trader/plans.json, 지우지 않고 쌓인다)을 다시 읽어 매번 처음부터 계산한다 — 따로 쌓는 장부 없음.
일봉은 데스크 차트(/api/chart, 통합 _AL · 데스크 앱키 · 캐시)로 받는다 — 소피증권 앱키를 안 쓴다.
수익률은 '걸렸던 첫 단계 가격'에 샀다고 치고, 수수료 각 0.015% + 매도세 0.20% 를 뺀 값(슬리피지 없음).

    python -m trader.outcomes          # 표 출력 + state/trader/outcomes.json
"""
from __future__ import annotations

import json
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state" / "trader"
DESK = "http://127.0.0.1:8790"
COST = 0.00015 * 2 + 0.0020
DAYS = (0, 1, 3, 5)                                                    # 0 = 그날 종가


def kind(p: dict) -> str | None:
    s = p.get("status", "")
    if any(st.get("filled") for st in p["stages"]) or p.get("bought"):
        return "산 것"
    if "재매수 금지" in s:
        return "재매수 금지로 막음"
    if "버림" in s:
        return "급락·전날 하락으로 버림"
    if p.get("active"):
        return None                                                   # 아직 진행 중 — 결과 없음
    return "안 사고 끝남(취소·기간 끝)"


def daily(code: str, cache: dict) -> list:
    if code not in cache:
        with urllib.request.urlopen(f"{DESK}/api/chart?code={code}&tf=D", timeout=30) as r:
            cache[code] = json.load(r)
    return cache[code]


def rows(plans: list, fetch=None) -> list:
    """fetch(code) -> 일봉 목록. 없으면 데스크 HTTP 로(따로 돌릴 때), 데스크 안에서는 chart 함수를 넘긴다."""
    out, seen, cache = [], set(), {}
    for p in plans:
        k = kind(p)
        d0 = (p.get("placed_day") or p["created"][:10]).replace("-", "")
        if not k or (p["code"], d0, k) in seen:                       # 같은 종목·같은 날을 규칙 여럿이 잡아도 한 번만
            continue
        seen.add((p["code"], d0, k))
        filled = [s for s in p["stages"] if s.get("filled")]
        price = (sum(s["price"] * s["filled"] for s in filled) / sum(s["filled"] for s in filled)) if filled \
            else min(s["price"] for s in p["stages"])                 # ponytail: 다시 사기로 단계가 초기화되면 앞선 체결은 안 보임 — 필요하면 journal.json 체결로
        try:
            bars = fetch(p["code"]) if fetch else daily(p["code"], cache)
        except Exception:                                              # noqa: BLE001 — 그 종목만 빼고
            continue
        i = next((j for j, b in enumerate(bars) if b["t"] >= d0), None)
        if i is None:
            continue
        r = {"day": d0, "code": p["code"], "name": p["name"], "kind": k, "price": round(price), "status": p.get("status", ""),
             "touched": bars[i]["l"] <= price}                        # 그날 저가가 닿았나 = 막지 않았으면 샀을까
        for n in DAYS:
            r[f"d{n}"] = round(bars[i + n]["c"] / price - 1 - COST, 4) if i + n < len(bars) else None
        win = bars[i + 1:i + 6]
        r["low5"] = round(min(b["l"] for b in win) / price - 1, 4) if win else None
        r["high5"] = round(max(b["h"] for b in win) / price - 1, 4) if win else None
        out.append(r)
    return out


def summary(rs: list) -> dict:
    g = defaultdict(list)
    for r in rs:
        g[r["kind"]].append(r)
    res = {}
    for k, xs in g.items():
        s = {"n": len(xs)}
        for n in DAYS:
            v = [x[f"d{n}"] for x in xs if x[f"d{n}"] is not None]
            s[f"d{n}"] = {"n": len(v), "avg": round(sum(v) / len(v), 4) if v else None,
                          "down": round(sum(x < 0 for x in v) / len(v), 3) if v else None}
        res[k] = s
    return res


def main() -> None:
    rs = rows(json.loads((STATE / "plans.json").read_text(encoding="utf-8")))
    sm = summary(rs)
    (STATE / "outcomes.json").write_text(json.dumps({"rows": rs, "summary": sm}, ensure_ascii=False, indent=1), encoding="utf-8")
    pct = lambda v: "  -  " if v is None else f"{v * 100:+.1f}%"
    for r in sorted(rs, key=lambda x: (x["kind"], x["day"])):
        print(f"{r['day']} {r['name']:<10} {r['kind']:<16} {r['price']:>8,} 닿음={'O' if r['touched'] else 'X'} "
              + " ".join(f"{n}일 {pct(r[f'd{n}'])}" for n in DAYS))
    print()
    for k, s in sm.items():
        print(f"{k:<20} {s['n']}건 · " + " · ".join(
            f"{n}일 뒤 평균 {pct(s[f'd{n}']['avg'])} (떨어진 비율 {'-' if s[f'd{n}']['down'] is None else f'{s[f'd{n}']['down'] * 100:.0f}%'}, {s[f'd{n}']['n']}건)"
            for n in DAYS))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
