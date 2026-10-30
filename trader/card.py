"""종목 한 장(10-23 사용자 "종목 한 장부터") — 흩어진 기록을 종목 코드 하나로 모은다. 읽기만 한다.

섹터(스탁이지 표) · 소피 테마(소피 attribution 기록) · 신고대금 장부 · 소피 프로그램 주도 신호 ·
고른 기록(journal) · 데스크 계획·보유·미체결 · 성적표(outcomes).
소피증권(8770)에는 요청하지 않고 kospi-theme-engine/dist/logs 의 파일만 읽는다(소피 부담 금지).
빈칸은 숨기지 않고 gaps 로 돌려준다 — 이어지지 않은 곳을 보는 게 이 화면의 목적 중 하나.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from . import feed, outcomes, themes
from .desk import _read

ROOT = Path(__file__).resolve().parents[1]
SOPHIE_LOGS = ROOT / "kospi-theme-engine" / "dist" / "logs"
LEDGER = ROOT / "static" / "dashboard" / "value_ledger.json"
SECTORS = ROOT / "data" / "sectors_stockeasy.csv"
COST = outcomes.COST                                                   # 수수료 각 0.015% + 매도세 0.20%
_cache: dict = {}


def _cached(p: Path, load):
    """파일이 바뀔 때만 다시 읽는다(mtime)."""
    try:
        mt = p.stat().st_mtime
    except OSError:
        return None
    hit = _cache.get(p)
    if not hit or hit[0] != mt:
        hit = _cache[p] = (mt, load(p))
    return hit[1]


def _by_code_ledger(p: Path) -> dict:
    out: dict = {}
    for r in json.loads(p.read_text(encoding="utf-8"))["rows"]:
        out.setdefault(r[1], []).append(r)
    return out


def _by_code_program(p: Path) -> dict:
    out: dict = {}
    with p.open(encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            out.setdefault(r.get("code"), []).append(r)
    return out


def _sectors(p: Path) -> dict:
    with p.open(encoding="utf-8-sig", newline="") as f:
        return {r["code"]: r for r in csv.DictReader(f)}


def _last_line(p: Path) -> dict | None:
    with p.open("rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 262144))
        lines = f.read().splitlines()
    for raw in reversed(lines):
        try:
            return json.loads(raw)
        except ValueError:
            continue
    return None


def theme(code: str, days: int = 20) -> dict:
    """소피 테마 소속 — 최근 날짜 파일의 마지막 기록부터 거슬러 올라가 처음 값이 있는 날. 줄 = [코드, 테마, 세부, …, 태그들]."""
    files = sorted((SOPHIE_LOGS / "attribution").glob("*.jsonl"), reverse=True)[:days]
    seen = None
    for p in files:
        j = _cached(p, _last_line) or {}
        r = next((x for x in j.get("rows") or () if x and x[0] == code), None)
        if r is None:
            continue
        seen = seen or p.stem
        if r[1]:
            return {"theme": r[1], "sub": r[2], "tags": r[-1] if isinstance(r[-1], list) else [], "day": p.stem}
    return {"theme": None, "seen": seen}


def ledger_rows(code: str) -> list:
    rows = (_cached(LEDGER, _by_code_ledger) or {}).get(code, [])
    pick = lambda r, i: r[i] if len(r) > i else None
    return [{"day": r[0], "eok": r[3], "prev": r[4], "x": r[5], "chg": r[7], "close": r[8], "n": r[9],
             "d5": r[10], "d20": r[11], "reg_eok": pick(r, 17), "reg_chg": pick(r, 20),
             "full": bool(pick(r, 28)) if len(r) > 28 else True} for r in sorted(rows, key=lambda r: r[0], reverse=True)]


def program(code: str, n: int = 30) -> list:
    rs = (_cached(SOPHIE_LOGS / "program_signals.jsonl", _by_code_program) or {}).get(code, [])
    keep = ("d", "t", "kind", "price", "chg", "pnl", "share", "session")
    return [{k: r.get(k) for k in keep} for r in rs[-n:]][::-1]


def trade_pnl(j: dict) -> dict | None:
    """고른 기록 한 건의 손익(비용 뺀 값) — 다 팔았을 때만. buys/sells = [[시각, 수량, 가격, 사유], …]."""
    bq, sq = sum(b[1] for b in j.get("buys") or ()), sum(s[1] for s in j.get("sells") or ())
    if not bq or bq != sq:
        return None
    bw, sw = sum(b[1] * b[2] for b in j["buys"]), sum(s[1] * s[2] for s in j["sells"])
    fee, tax = (bw + sw) * 0.00015, sw * 0.0020
    net = sw - bw - fee - tax
    return {"gross": round(sw - bw), "fee": round(fee), "tax": round(tax), "net": round(net), "pct": round(net / bw * 100, 2)}


def build(code: str, D, fetch=None) -> dict:
    sec = (_cached(SECTORS, _sectors) or {}).get(code)
    q = feed.quotes.get(code, {})
    held = next((h for h in D.holdings if h["code"] == code), None)
    plans = [p for p in D.plans if p["code"] == code]
    journal = [{**j, "pnl": trade_pnl(j), "themes_at": [t["theme"] for t in themes.recent(code, (j.get("picked") or "")[:10] or None)[:3]]}
               for j in D.journal if j["code"] == code][::-1]                # 고를 때(그날까지) 인포스탁 테마 — 어느 테마로 골랐나
    grades = {k.split(":", 1)[1]: v.get("g") for k, v in _read("grades.json", {}).items() if k.startswith(code + ":")}
    try:
        outs = outcomes.rows(plans, fetch) if plans else []
    except Exception:                                                  # noqa: BLE001 — 성적표만 빼고 보여준다
        outs = []
    th = theme(code)
    led = ledger_rows(code)
    prog = program(code)
    gaps = []
    if not sec:
        gaps.append("스탁이지 섹터표에 없음")
    info = themes.recent(code)
    if not th.get("theme") and not info:
        gaps.append("테마 빈칸 — 소피 판정·인포스탁 최근 20거래일 둘 다 없음")
    if journal and not any(j.get("why") for j in journal):
        gaps.append("고른 이유 기록 없음")
    if any(p.get("active") for p in plans) and not outs:
        gaps.append("진행 중인 계획은 끝나야 성적표에 들어감")
    return {"code": code, "name": D.name(code), "px": q.get("px"), "chg": q.get("chg"),
            "sector": {"sector": sec["sector"], "sub": sec["sub_sector"]} if sec else None, "theme": th,
            "info_themes": info[:6], "theme_history": themes.history(code)[:15],
            "ledger": [{**r, "grade": grades.get(r["day"])} for r in led], "program": prog,
            "watch": code in D.watch, "holding": held, "pending": [p for p in D.pending if p["code"] == code],
            "plans": [{k: p.get(k) for k in ("id", "tag", "status", "active", "created", "ref_day", "until", "stages")} for p in plans[-10:]][::-1],
            "journal": journal, "outcomes": outs, "gaps": gaps}


if __name__ == "__main__":                                             # 셀프 체크 — 손익 계산(엘리스 10-23 오전 실제 체결)
    j = {"buys": [["2026-10-23T09:55", 80, 91000, "예약"]], "sells": [["2026-10-23T10:03", 80, 93700, "일괄 매도"]]}
    r = trade_pnl(j)
    assert r == {"gross": 216000, "fee": 2216, "tax": 14992, "net": 198792, "pct": 2.73}, r
    assert trade_pnl({"buys": [["t", 10, 100, ""]], "sells": []}) is None
    print("ok", r)
