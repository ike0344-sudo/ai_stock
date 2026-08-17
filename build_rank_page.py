"""rank_timeline JSON → 순위 이동 페이지 HTML.

    python build_rank_page.py 20260814 20260813

헤더 문구와 타일 숫자는 페이지가 데이터에서 직접 계산한다. 날짜마다 손으로 고치면
숫자가 조용히 어긋난다 — 실제로 첫 판에서 1위 시각과 최고점이 둘 다 틀렸다.
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "results" / "_rank_template.html"
RAW = ROOT / "kospi-theme-engine" / "results"
OUT = ROOT / "results"


def payload(day: str) -> str:
    src = RAW / f"rank_timeline_{day}.json"
    d = json.loads(src.read_text(encoding="utf-8"))
    frames = d["frames"]
    times = [f["t"] for f in frames]
    themes = sorted({r["theme"] for f in frames for r in f["rows"]})
    rank = {t: [] for t in themes}
    score = {t: [] for t in themes}
    top5 = []
    for f in frames:
        order = {r["theme"]: i + 1 for i, r in enumerate(f["rows"])}
        by = {r["theme"]: r for r in f["rows"]}
        for t in themes:
            rank[t].append(order.get(t))
            score[t].append(by[t]["score"] if t in by else None)
        top5.append([[r["theme"], r["score"], r["leader"], r["lead_pct"], r["top"][0], r["top"][1]]
                     for r in f["rows"][:5]])
    out = {"day": d["day"], "times": times, "themes": themes,
           "rank": rank, "score": score, "top5": top5}
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def build(day: str) -> Path:
    html = TEMPLATE.read_text(encoding="utf-8")
    html = re.sub(r'(<script id="payload" type="application/json">).*?(</script>)',
                  lambda m: m.group(1) + payload(day) + m.group(2), html, flags=re.DOTALL)
    path = OUT / f"rank_timeline_{day}.html"
    path.write_text(html, encoding="utf-8")
    return path


def main() -> None:
    days = [a for a in sys.argv[1:] if a.isdigit()]
    if not days:
        print("사용법: python build_rank_page.py 20260814 [20260813 ...]")
        return
    for day in days:
        p = build(day)
        print(f"{p.name}  {p.stat().st_size // 1024}KB")


if __name__ == "__main__":
    main()
