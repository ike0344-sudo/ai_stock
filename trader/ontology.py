"""온톨로지 관리(10-23 사용자 "온톨로지 관리 페이지") — 이어 놓은 선이 실제로 살아 있는지 한 번에 본다. 읽기만 한다.

자료 신선도(신고대금 장부 · 인포스탁 · 소피 기록) · 종목 연결률(테마·섹터 빈칸) · 고른 기록 · Jev 두 번 묻기 · 허브 경보.
판정은 good / warn / bad, 맨 위 problems 에 나쁜 것만 모은다(10-23 톡속보 2주 침묵·엘리스 테마 빈칸 같은 일이 바로 보이게).
"""
from __future__ import annotations

import json
from datetime import date, datetime, time as dtime
from pathlib import Path

from . import card, shadow, themes

ROOT = Path(__file__).resolve().parents[1]
LOGS = card.SOPHIE_LOGS
_cache: dict = {}


def _by_mtime(key: str, p: Path, load):
    try:
        mt = p.stat().st_mtime
    except OSError:
        return None
    hit = _cache.get(key)
    if not hit or hit[0] != mt:
        hit = _cache[key] = (mt, load(p))
    return hit[1]


def _latest_stem(folder: Path, pat: str = "*") -> str | None:
    xs = sorted(p.stem.split(".")[0] for p in folder.glob(pat))
    return xs[-1] if xs else None


def _cal():
    from datahub.calendar import Calendar
    return Calendar()


def _fresh(cal, now: datetime, last: str | None, ready: str) -> tuple[str, str]:
    """기대일 = 오늘(거래일이고 ready 시각 지남) 아니면 전 거래일. 마지막 날짜가 기대일이면 good, 한 거래일 늦으면 warn, 더 늦으면 bad."""
    today = now.date()
    exp = today if cal.is_trading_day(today) and now.time() >= dtime.fromisoformat(ready) else cal.prev_trading_day(today)
    if not last:
        return "bad", "기록 없음"
    d = date.fromisoformat(last[:10])
    if d >= exp:
        return "good", "최신"
    lag = len(cal.trading_days(d, exp)) - 1
    return ("warn" if lag <= 1 else "bad"), f"{lag}거래일 늦음 (기대 {exp.isoformat()})"


def sources(now: datetime) -> list[dict]:
    cal = _cal()
    led = _by_mtime("ledger_date", card.LEDGER, lambda p: json.loads(p.read_text(encoding="utf-8")).get("date"))
    att_day = _latest_stem(LOGS / "attribution", "*.jsonl")
    att_at = (card._cached(LOGS / "attribution" / f"{att_day}.jsonl", card._last_line) or {}).get("at") if att_day else None
    prog = _by_mtime("prog_last", LOGS / "program_signals.jsonl", card._last_line) or {}
    rows = [
        # (이름, 마지막 날짜, 덧붙일 말, 준비 시각, 쓰는 곳)
        ("신고대금 장부", led, "", "23:59", "종목 한 장 · 데스크 기준일 · Jev 배경"),
        ("인포스탁 데일리 테마", _latest_stem(themes.DAILY, "*.json"), "", "17:30", "테마 잇기(가장 믿을 만한 소속)"),
        ("인포스탁 톡속보(오전·오후장)", _latest_stem(ROOT / "data" / "news" / "infostock", "*.json"), "", "15:10", "소피 '오늘 테마' 화면"),
        ("소피 테마 판정", att_day, f"마지막 {att_at}" if att_at else "", "09:10", "테마 잇기(소피 표기)"),
        ("소피 대금 순위 기록", _latest_stem(LOGS / "rank_tape", "*.jsonl"), "", "09:10", "신고대금 장부 정규장 대금 메움"),
        ("소피 프로그램 주도 신호", prog.get("d"), f"마지막 {prog.get('t', '')[:5]} {prog.get('name', '')}" if prog else "", "10:00", "종목 한 장 · Jev 배경"),
    ]
    out = []
    for name, last, extra, ready, used in rows:
        v, why = _fresh(cal, now, last, ready)
        if name.startswith("소피 프로그램") and v == "bad":
            v = "warn"                                                 # 신호가 없는 날도 있다 — 기록이 없다고 고장은 아님
        out.append({"name": name, "last": last, "extra": extra, "verdict": v, "why": why, "used": used})
    return out


def _coverage(codes: list[str], D, upto: dict | None = None) -> dict:
    """종목들의 테마·섹터 연결 — 빈칸 종목은 이름까지."""
    secs = card._cached(card.SECTORS, card._sectors) or {}
    rows = []
    for c in codes:
        info = themes.recent(c, (upto or {}).get(c))
        so = card.theme(c).get("theme")
        rows.append({"code": c, "name": D.name(c), "sector": bool(secs.get(c)), "sophie": bool(so), "info": bool(info),
                     "theme": (info[0]["theme"] if info else so)})
    n = len(rows) or 1
    pct = lambda k: round(sum(r[k] for r in rows) / n * 100)
    blank = [r for r in rows if not r["info"] and not r["sophie"]]
    return {"n": len(rows), "theme": round((len(rows) - len(blank)) / n * 100), "info": pct("info"), "sophie": pct("sophie"),
            "sector": pct("sector"), "blank": [{"code": r["code"], "name": r["name"]} for r in blank],
            "no_sector": [{"code": r["code"], "name": r["name"]} for r in rows if not r["sector"]]}


def coverage(D, now: datetime) -> dict:
    held = [h["code"] for h in D.holdings]
    mine = list(dict.fromkeys(list(D.watch) + held))
    cal = _cal()
    since = now.date()
    for _ in range(20):
        since = cal.prev_trading_day(since)
    by = card._cached(card.LEDGER, card._by_code_ledger) or {}
    recent = {c: max(r[0] for r in rs) for c, rs in by.items() if any(r[0] >= since.isoformat() for r in rs)}
    return {"mine": _coverage(mine, D), "ledger": _coverage(sorted(recent), D, recent), "ledger_since": since.isoformat()}


def journal(D, days: int = 30) -> dict:
    cut = (datetime.now().date().toordinal() - days)
    js = [j for j in D.journal if j.get("picked") and date.fromisoformat(j["picked"][:10]).toordinal() >= cut]
    n = len(js) or 1
    why = sum(1 for j in js if j.get("why"))
    th = sum(1 for j in js if themes.recent(j["code"], j["picked"][:10]))
    return {"n": len(js), "why": round(why / n * 100), "theme": round(th / n * 100)}


def jev() -> dict:
    rs = shadow.rows(2000)
    asked = [r for r in rs if r.get("kind") == "entry" and not r.get("test")]
    g = shadow.graded_entry(rs)
    return {"asked": len(asked), "ctx_asked": sum(1 for r in asked if r.get("ctx")), "ctx_err": sum(1 for r in asked if (r.get("ctx") or {}).get("err")),
            "graded": g["n"], "ctx_n": g["ctx_n"], "ctx": g["ctx"], "ctx_base": g["ctx_base"], "need": 50, "on": shadow.stat.get("on"),
            "err": shadow.stat.get("err")}


def hub(now: datetime) -> dict:
    from datahub import alerts, catalog
    out = {"active": [], "given_up": [], "sent_today": []}
    titles = alerts.titles()
    try:
        act = json.loads((catalog.state_base() / "state" / "datahub" / "alerts_active.json").read_text(encoding="utf-8"))
        out["active"] = [{"id": k.split("|")[0], "title": titles.get(k.split("|")[0], k), "target": k.split("|", 1)[-1], "since": v} for k, v in act.items()]
    except (OSError, ValueError):
        pass
    try:
        from jobrunner.store import JobStore
        from datahub.scheduler import Scheduler
        labels = {s.id: s.label for s in catalog.load().schedules}
        out["given_up"] = [{**g, "label": labels.get(g["sid"], g["sid"])} for g in Scheduler(JobStore(catalog.root())).given_up(now)]
    except Exception:                                                  # noqa: BLE001 — 허브를 못 읽어도 페이지는 뜬다
        pass
    last = alerts.last_sent()
    out["sent_today"] = [{"id": k, "title": titles.get(k, k), **v} for k, v in last.items() if (v.get("ts") or "")[:10] == now.date().isoformat()]
    return out


def links(src: list, cov: dict, jr: dict, jv: dict) -> list:
    """설계도의 선마다 지금 상태. none = 아직 안 이음(계획만)."""
    f = {s["name"]: s["verdict"] for s in src}
    worst = lambda *v: "bad" if "bad" in v else "warn" if "warn" in v else "good"
    pct = lambda p: "good" if p >= 90 else "warn" if p >= 70 else "bad"
    return [
        {"from": "통합 일봉·소피 순위 기록", "to": "신고대금 날", "state": worst(f["신고대금 장부"], f["소피 대금 순위 기록"]), "note": "밤마다 장부 다시 만듦"},
        {"from": "신고대금 날", "to": "데스크 기준일 · 계획", "state": f["신고대금 장부"], "note": "장부 파일이 바뀌면 데스크가 바로 읽음"},
        {"from": "인포스탁 데일리 + 소피 판정", "to": "테마", "state": worst(f["인포스탁 데일리 테마"], f["소피 테마 판정"], pct(cov["ledger"]["theme"])),
         "note": f"최근 신고대금 종목 테마 연결 {cov['ledger']['theme']}%"},
        {"from": "테마", "to": "고른 기록", "state": pct(jr["theme"]) if jr["n"] else "warn", "note": f"최근 30일 고른 {jr['n']}건 중 {jr['theme']}% 테마 있음"},
        {"from": "테마", "to": "성적표(테마별)", "state": "good", "note": "성적표 탭 테마별 표"},
        {"from": "소피 프로그램 신호", "to": "종목 한 장 · Jev 배경", "state": f["소피 프로그램 주도 신호"], "note": "기록 파일만 읽음"},
        {"from": "종목 배경", "to": "Jev 두 번 묻기", "state": ("bad" if jv["ctx_err"] and jv["ctx_err"] == jv["ctx_asked"] else "good" if jv["ctx_asked"] else "warn"),
         "note": f"배경 넣고 물은 {jv['ctx_asked']}건 · 채점 {jv['ctx_n']}/{jv['need']}"},
        {"from": "소피 장중 신호", "to": "데스크 관심 후보", "state": "none", "note": "아직 안 이음(설계도의 다음 단계)"},
    ]


def build(D) -> dict:
    now = datetime.now()
    src, cov, jr, jv, hb = sources(now), coverage(D, now), journal(D), jev(), hub(now)
    probs = [f"{s['name']} — {s['why']}" for s in src if s["verdict"] == "bad"]
    probs += [f"{g['label']} 오늘 {g['tries']}번 다 실패" for g in hb["given_up"]]
    probs += [f"허브 경보: {a['title']} ({a['target']})" for a in hb["active"]]
    if cov["mine"]["blank"]:
        probs.append("관심·보유 종목 테마 빈칸: " + ", ".join(x["name"] for x in cov["mine"]["blank"]))
    if jv["ctx_asked"] and jv["ctx_err"] == jv["ctx_asked"]:
        probs.append("Jev 두 번째 질문이 전부 오류")
    return {"now": now.isoformat(timespec="seconds"), "problems": probs, "sources": src, "coverage": cov, "journal": jr, "jev": jv, "hub": hb,
            "links": links(src, cov, jr, jv)}


if __name__ == "__main__":                                             # 셀프 체크 — 신선도 판정(거래일 달력 기준)
    cal = _cal()
    now = datetime(2026, 10, 23, 18, 0)                                # 금요일 장 마감 뒤
    assert _fresh(cal, now, "2026-10-23", "17:30")[0] == "good"
    assert _fresh(cal, now, "2026-10-22", "17:30") == ("warn", "1거래일 늦음 (기대 2026-10-23)")
    assert _fresh(cal, now, "2026-10-02", "15:10")[0] == "bad"          # 톡속보 2주 침묵
    assert _fresh(cal, now, "2026-10-22", "23:59")[0] == "good"         # 장부는 밤에 만들어 전 거래일이 최신
    print("ok")
