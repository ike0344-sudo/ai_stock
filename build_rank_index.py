"""날짜별 순위 기록을 한 페이지로 묶는다 — 달력에서 날짜를 골라 그날 표를 본다.

    python build_rank_index.py

날짜마다 페이지를 따로 만들면 링크를 찾아다녀야 한다. 한 파일에 전부 담고 날짜를
클릭해 갈아끼운다. 하루치가 20KB 남짓이라 30일이면 600KB — 아티팩트 16MB 한도 안이다.
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "kospi-theme-engine" / "results"
OUT = ROOT / "results" / "rank_archive.html"


def compact(day: str) -> dict:
    """페이지가 쓰는 최소 형태로 줄인다. 원본을 그대로 실으면 파일이 몇 배가 된다."""
    d = json.loads((RAW / f"rank_timeline_{day}.json").read_text(encoding="utf-8"))
    frames = d["frames"]
    themes = sorted({r["theme"] for f in frames for r in f["rows"]})
    rank = {t: [] for t in themes}
    score = {t: [] for t in themes}
    top5 = []
    for f in frames:
        order = {r["theme"]: i + 1 for i, r in enumerate(f["rows"])}
        by = {r["theme"]: r for r in f["rows"]}
        for t in themes:
            rank[t].append(order.get(t))
            score[t].append(round(by[t]["score"], 1) if t in by else None)
        top5.append([[r["theme"], round(r["score"], 1), r["leader"], r["lead_pct"],
                      r["top"][0], r["top"][1]] for r in f["rows"][:5]])
    return {"times": [f["t"] for f in frames], "themes": themes,
            "rank": rank, "score": score, "top5": top5}


def main() -> None:
    days = sorted(p.stem.replace("rank_timeline_", "")
                  for p in RAW.glob("rank_timeline_*.json"))
    if not days:
        print("계산된 날이 없습니다 — rank_archive.py 를 먼저 돌리세요")
        return
    data = {"days": days, "byDay": {d: compact(d) for d in days}}
    tpl = (ROOT / "results" / "_archive_template.html").read_text(encoding="utf-8")
    OUT.write_text(tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False,
                                                      separators=(",", ":"))), encoding="utf-8")
    print(f"{OUT.name} · {len(days)}일 · {OUT.stat().st_size // 1024}KB "
          f"({days[0]} ~ {days[-1]})")


if __name__ == "__main__":
    main()
