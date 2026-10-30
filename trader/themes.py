"""종목 ↔ 테마 잇기(10-23 사용자 "테마 잇기도 해줘") — 날짜가 붙은 살아 있는 소속. 읽기만 한다.

출처 둘을 같이 쓰고 어느 쪽인지 남긴다(이름 표기가 서로 다르다):
- 인포스탁 데일리 테마(data/news/infostock_daily/날짜.json, 장 마감 뒤) — 그날 '어느 테마로 올랐나'. 사람이 쓴 글이라 소속이 가장 믿을 만하다.
  소피 해석본(sections)이 놓치는 "또한, 엘리스, 플리토 … 등 AI 챗봇(챗GPT 등) … 테마도 상승" 같은 둘째 문장은 원문(raw)을
  종목 이름 사전으로 다시 읽어 채운다(10-21 엘리스가 그래서 빈칸이었다).
- 소피 테마 판정(card.theme — 소피 attribution 기록의 최신값).
고정 분류표를 새로 만들지 않는다(살아 있는 테마 지도) — 날짜별로 읽어 '그때 무슨 테마였나'를 답한다.
"""
from __future__ import annotations

import html
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "data" / "news" / "infostock_daily"
NAMES = ROOT / "data" / "stock_names.json"
_cache: dict = {}


def _names() -> dict:
    """이름 → 코드(데스크와 같은 사전)."""
    p = NAMES
    mt = p.stat().st_mtime
    if _cache.get("names", (None,))[0] != mt:
        m = json.loads(p.read_text(encoding="utf-8"))
        _cache["names"] = (mt, {n: c for c, n in m.items()})
    return _cache["names"][1]


_SEP = re.compile(r"(,\s*| 및 | 등 )")
_TAIL = re.compile(r"\s*(관련주|테마)?\s*(가|도|이)?\s*(상승|강세)\s*$")


def sentence_groups(s: str, name2code: dict) -> list:
    """'A, B 등 테마1, 테마2, C 등 테마3 … 등 큰테마 관련주가 상승' → [(코드들, 테마들)].
    이름 사전에 있으면 종목, 아니면 테마. 테마 뒤 ' 등 ' 다음 테마는 문장 전체에 걸리는 큰 테마."""
    masked = re.sub(r"\([^()]*\)", lambda m: m.group(0).replace(",", "\x00").replace(" 등", "\x01").replace(" 및 ", "\x02"), s)
    parts = _SEP.split(masked)
    toks = [(parts[i].replace("\x00", ",").replace("\x01", " 등").replace("\x02", " 및 ").strip(), parts[i - 1] if i else "")
            for i in range(0, len(parts), 2)]
    groups, prev_theme, umbrella = [], False, []
    for t, sep in toks:
        t = re.sub(r"^.*?속\s+", "", t) if "소식 속" in t else t
        t = re.sub(r"^또한\s*", "", t)
        t = _TAIL.sub("", t).strip(" .")
        if not t:
            continue
        code = name2code.get(t)
        if code:
            if not groups or groups[-1][1]:
                groups.append(([], []))
            groups[-1][0].append(code)
            prev_theme = False
        elif groups:
            if sep.strip() == "등" and prev_theme:
                umbrella.append(t)
            else:
                groups[-1][1].append(t)
            prev_theme = True
    return [(cs, ts + [u for u in umbrella if u not in ts]) for cs, ts in groups if ts]


def _raw_sentences(raw: str) -> list:
    text = html.unescape(re.sub(r"<!--.*?-->|<[^>]+>", "\n", raw or "", flags=re.S))
    out = []
    for para in text.split("▷")[1:]:
        for s in re.split(r"(?<=[가-힣)])\.\s", para):
            s = " ".join(s.split())
            if " 등 " in s and _TAIL.search(s.rstrip(". ")):
                out.append(s.rstrip(". "))
    return out


def _load_day(p: Path) -> dict:
    """하루 → {코드: [{"theme", "kind", "head"}]} — narrative(사람이 쓴 문장) 먼저, table(테마별 상위 표) 다음."""
    j = json.loads(p.read_text(encoding="utf-8"))
    n2c, out = _names(), {}

    def add(code, theme, kind, head=""):
        if code and theme and not str(theme).startswith("?") and not any(x["theme"] == theme for x in out.get(code, ())):
            out.setdefault(code, []).append({"theme": theme, "kind": kind, "head": head})
    for s in j.get("sections") or []:
        themes = [t for t in s.get("themes") or [] if not str(t).startswith("?")]
        for st in s.get("stocks") or []:
            for t in st.get("themes") or themes:
                add(st.get("code") or n2c.get(st.get("name")), t, "narrative", s.get("head", ""))
    raw = j.get("raw")
    for sent in _raw_sentences(raw.get("content", "") if isinstance(raw, dict) else raw):   # 해석본이 놓친 문장(또한 …)
        for codes, ts in sentence_groups(sent, n2c):
            for c in codes:
                for t in ts:
                    add(c, t, "narrative", sent[:80])
    for s in j.get("sections") or []:
        for row in s.get("table") or []:
            add(row.get("code") or n2c.get(row.get("name")), row.get("theme"), "table", s.get("head", ""))
    return out


def day(d: str) -> dict:
    p = DAILY / f"{d}.json"
    try:
        mt = p.stat().st_mtime
    except OSError:
        return {}
    hit = _cache.get(p)
    if not hit or hit[0] != mt:
        try:
            hit = _cache[p] = (mt, _load_day(p))
        except (OSError, ValueError, KeyError):
            return {}
    return hit[1]


def _days(upto: str | None, n: int) -> list:
    fs = sorted(x.stem for x in DAILY.glob("*.json") if upto is None or x.stem <= upto)
    return fs[-n:]


def history(code: str, upto: str | None = None, n: int = 60) -> list:
    """최근 n 거래일 글에서 이 종목이 나온 날 — [{"day", "themes": [...]}] 최신 먼저."""
    return [{"day": d, "themes": day(d)[code]} for d in reversed(_days(upto, n)) if code in day(d)]


def recent(code: str, upto: str | None = None, n: int = 20) -> list:
    """그때(upto, 'YYYY-MM-DD') 기준 최근 n 거래일 안 테마 — 사람이 쓴 문장 > 표, 나온 횟수, 최근 날짜 순. [{"theme","n","last","kind"}]."""
    cnt, last, kind = Counter(), {}, {}
    for h in history(code, upto, n):
        for t in h["themes"]:
            cnt[t["theme"]] += 1
            last.setdefault(t["theme"], h["day"])
            kind[t["theme"]] = "narrative" if t["kind"] == "narrative" or kind.get(t["theme"]) == "narrative" else "table"
    return sorted(({"theme": t, "n": k, "last": last[t], "kind": kind[t]} for t, k in cnt.items()),
                  key=lambda x: (x["kind"] != "narrative", -x["n"], x["last"]), reverse=False)


def label(code: str, upto: str | None = None) -> str | None:
    """한 줄 이름 — 성적을 테마별로 묶을 때. 인포스탁 최근 20거래일 첫째, 없으면 소피 판정(지금 값이라 과거 줄엔 근사)."""
    r = recent(code, upto)
    if r:
        return r[0]["theme"]
    from .card import theme
    return theme(code).get("theme")


if __name__ == "__main__":                                             # 셀프 체크 — 10-21 원문 두 문장(엘리스는 '또한' 문장에만 나온다)
    n2c = {"LS에코에너지": "A1", "산일전기": "A2", "미코": "A3", "대한광통신": "A4", "엘리스": "0158S0", "플리토": "B1", "유니셈": "C1", "한중엔시에스": "C2"}
    g = sentence_groups("이 같은 소식 속 LS에코에너지, 산일전기 등 전력설비/전선/원자력발전, 미코 등 고체산화물 연료전지(SOFC), 수소에너지(수소차/연료전지 등) "
                        "및 대한광통신 등 광통신(광케이블/광섬유), 5G(5세대 이동통신), 통신장비 등 AI 인프라 관련주가 상승", n2c)
    assert g[0] == (["A1", "A2"], ["전력설비/전선/원자력발전", "AI 인프라"]), g
    assert g[2] == (["A4"], ["광통신(광케이블/광섬유)", "5G(5세대 이동통신)", "통신장비", "AI 인프라"]), g
    g = sentence_groups("또한, 엘리스, 플리토 등 AI 챗봇(챗GPT 등), 지능형로봇/인공지능(AI), 유니셈, 한중엔시에스 등 냉각시스템(액침냉각 등) 테마도 상승", n2c)
    assert g == [(["0158S0", "B1"], ["AI 챗봇(챗GPT 등)", "지능형로봇/인공지능(AI)"]), (["C1", "C2"], ["냉각시스템(액침냉각 등)"])], g
    print("ok", recent("0158S0", "2026-10-23")[:3])
