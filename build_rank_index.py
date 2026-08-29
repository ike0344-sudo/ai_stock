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
    # 대금 20위 안의 등락률 1등 — 화면의 🥇 알림이 고르는 것과 같은 규칙이다.
    # 테마와 무관하게 "그 순간 시장에서 가장 오른 주도주"라, 1위 테마와 어긋나는
    # 순간이 오히려 볼 값어치가 있다.
    chgtop = [f.get("chgtop") for f in frames]
    return {"times": [f["t"] for f in frames], "themes": themes,
            "rank": rank, "score": score, "top5": top5, "chgtop": chgtop}


def new_highs(days: list[str]) -> dict[str, list]:
    """날짜별 그날 신고가를 낸 종목 — [이름, 단계, 그날 대금순위].

    단계는 화면(소피증권)과 같은 정의다: 역대 고점을 넘었으면 '역사적', 4년 고점을
    넘었으면 '4년', 아니면 '120일'. 역대·4년 고가는 월봉(수정주가)에서 뽑는다 —
    일봉 캐시는 2.5년치뿐이라 그 앞을 못 본다.
    """
    import pandas as pd

    N, first, last = 120, min(days), max(days)
    lo = f"{first[:4]}-{first[4:6]}-{first[6:]}"
    hi = f"{last[:4]}-{last[4:6]}-{last[6:]}"
    uni = pd.read_csv(ROOT / "kospi-theme-engine" / "data" / "reference" / "universe.csv",
                      dtype=str)
    name_of = dict(zip(uni["code"], uni["name"]))
    daily_dir, month_dir = ROOT / "data" / "stocks" / "daily", ROOT / "data" / "stocks" / "monthly"
    if not daily_dir.is_dir():
        return {}

    hits: dict[str, list] = {d: [] for d in days}
    tv: dict[str, "pd.Series"] = {}
    for path in sorted(daily_dir.glob("*.csv")):
        code = path.stem
        try:
            d = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
        except (OSError, ValueError):
            continue
        win = d.loc[lo:hi]
        if win.empty:
            continue
        tv[code] = win["close"] * win["volume"]
        if len(d) < N + 1:
            continue
        prior = d["high"].shift(1).rolling(N).max()
        mpath = month_dir / f"{code}.csv"
        mh = None
        if mpath.is_file():
            try:
                mh = pd.read_csv(mpath, index_col=0, parse_dates=True).sort_index()["high"]
            except (OSError, ValueError):
                mh = None
        for day in days:
            stamp = pd.Timestamp(f"{day[:4]}-{day[4:6]}-{day[6:]}")
            if stamp not in win.index:
                continue
            base = prior.get(stamp)
            if base is None or pd.isna(base) or d.at[stamp, "high"] <= base:
                continue
            dh = int(d.at[stamp, "high"])
            dtop = int(d["high"][d.index < stamp].max())
            m4 = mall = 0
            if mh is not None:
                past = mh[mh.index.strftime("%Y-%m") < stamp.strftime("%Y-%m")]
                if len(past):
                    mall = int(past.max())
                    m4 = int(past[-48:].max()) if len(past) >= 48 else 0
            ath = max(mall, dtop) if mall else 0
            h4 = max(m4, dtop) if m4 else 0
            hits[day].append([code, "역사적" if ath and dh > ath
                              else "4년" if h4 and dh > h4 else "120일"])

    TV = pd.DataFrame(tv)
    rank = TV.rank(axis=1, ascending=False, method="min")
    out = {}
    for day, rows in hits.items():
        stamp = pd.Timestamp(f"{day[:4]}-{day[4:6]}-{day[6:]}")
        got = []
        for code, tier in rows:
            r = rank.at[stamp, code] if stamp in rank.index and code in rank.columns else None
            got.append([name_of.get(code, code), tier,
                        int(r) if r is not None and not pd.isna(r) else 0])
        got.sort(key=lambda x: x[2] or 9999)
        out[day] = got
    return out


def main() -> None:
    days = sorted(p.stem.replace("rank_timeline_", "")
                  for p in RAW.glob("rank_timeline_*.json"))
    if not days:
        print("계산된 날이 없습니다 — rank_archive.py 를 먼저 돌리세요")
        return
    data = {"days": days, "byDay": {d: compact(d) for d in days}}
    try:
        highs = new_highs(days)
        for d in days:
            data["byDay"][d]["highs"] = highs.get(d, [])
        print(f"신고가: {sum(len(v) for v in highs.values())}건")
    except Exception as e:                    # 일봉·월봉이 없어도 페이지는 나와야 한다
        print(f"신고가 계산 건너뜀 — {type(e).__name__}: {e}")
        for d in days:
            data["byDay"][d]["highs"] = []
    tpl = (ROOT / "results" / "_archive_template.html").read_text(encoding="utf-8")
    OUT.write_text(tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False,
                                                      separators=(",", ":"))), encoding="utf-8")
    print(f"{OUT.name} · {len(days)}일 · {OUT.stat().st_size // 1024}KB "
          f"({days[0]} ~ {days[-1]})")


if __name__ == "__main__":
    main()
