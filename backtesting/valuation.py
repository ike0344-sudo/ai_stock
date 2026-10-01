"""적정 시가총액 — 예상 순이익 × 같은 업종(중분류) 예상 PER 중앙값.

    python -m backtesting.valuation            # 표본 몇 개 출력

- 예상 순이익 = 시총 ÷ 예상 PER (PER = 시총 ÷ 순이익 이라서). 기준 연도는 FWD_YEAR(2027E — 올해가 2026 이라 1년 앞).
- 적정 PER = 같은 중분류(스탁이지 분류, data/sectors_stockeasy.csv)에서 예상 PER 이 0~PER_CAP 인 종목들의 중앙값.
  같은 중분류가 PEER_MIN 개 미만이면 대분류 중앙값. 적자(예상 PER ≤ 0)·추정치 없음은 계산하지 않는다(None).
- 입력 PER 은 지금 스탁이지 밸류에이션 스냅샷(data/stockeasy_valuation_YYYYMMDD.json, 2026-09-28 받음)이다.
  사용자 09-28: "지금은 받지만 앞으로 내 시스템 안에서 해야 돼" — 자체 컨센서스 출처로 바꾸는 건 data-agent 큐에 있다.
  바꿀 때 load_forward_per() 만 갈아끼우면 된다.
"""
import csv
import glob
import json
import statistics

FWD_YEAR = "2027E"
PER_COL = {"2026E": 4, "2027E": 5, "2028E": 6}  # 스냅샷 cols: 시총억,RS,PER2025,PER직전4Q,PER2026E,PER2027E,PER2028E
PER_CAP = 100.0  # 이보다 큰 PER 은 이익이 거의 없다는 뜻이라 업종 중앙값에서 뺀다
PEER_MIN = 3
SECTORS_CSV = "data/sectors_stockeasy.csv"


def load_forward_per(year: str = FWD_YEAR) -> tuple[dict[str, float], dict[str, float], str]:
    """(코드→예상 PER, 코드→스냅샷 시총(원), 스냅샷 날짜). 가장 최근 스냅샷 파일을 쓴다."""
    path = sorted(glob.glob("data/stockeasy_valuation_*.json"))[-1]
    d = json.load(open(path, encoding="utf-8"))
    col = PER_COL[year]
    per = {c: r[col] for c, r in d["rows"].items() if r[col] is not None}
    cap = {c: r[0] * 1e8 for c, r in d["rows"].items() if r[0]}
    return per, cap, d.get("date", "")


def load_sectors(path: str = SECTORS_CSV) -> tuple[dict[str, str], dict[str, str]]:
    big, mid = {}, {}
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        big[r["code"]], mid[r["code"]] = r["sector"], r["sub_sector"]
    return big, mid


def peer_per(per: dict[str, float], group: dict[str, str]) -> dict[str, float]:
    by: dict[str, list[float]] = {}
    for c, p in per.items():
        if c in group and 0 < p <= PER_CAP:
            by.setdefault(group[c], []).append(p)
    return {g: statistics.median(v) for g, v in by.items() if len(v) >= PEER_MIN}


def fair_caps(year: str = FWD_YEAR) -> dict[str, dict]:
    """코드→{fair_mcap(원), per_fwd, peer_per, peer_group}. 계산 못 하는 종목은 빠진다."""
    per, cap, _ = load_forward_per(year)
    big, mid = load_sectors()
    mid_med, big_med = peer_per(per, mid), peer_per(per, big)
    out = {}
    for c, p in per.items():
        if p <= 0 or c not in cap:
            continue
        if mid.get(c) in mid_med:
            target, grp = mid_med[mid[c]], mid[c]
        elif big.get(c) in big_med:
            target, grp = big_med[big[c]], big[c]
        else:
            continue
        earnings = cap[c] / p
        out[c] = {"fair_mcap": int(earnings * target), "per_fwd": round(p, 2), "peer_per": round(target, 2), "peer_group": grp}
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    f = fair_caps()
    print(f"{FWD_YEAR} 기준 적정시총 계산 {len(f)}종목")
    for c in ("005930", "000660", "092870", "252990", "000500", "055550"):
        print(c, f.get(c))
