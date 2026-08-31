"""종목별 '직전 120거래일 최고가'를 한 줄씩 뽑아 data/high120.csv 로 저장한다.

    python build_high120.py          # data/stocks/daily/*.csv 전부 스캔
    python build_high120.py --demo

왜 요약값만 두는가: 거래대금 상위 화면은 10초마다 도는데, 그때마다 20종목 일봉을
API로 받으면 1.1초 페이싱에 걸려 22초가 걸린다. 종목당 숫자 하나만 캐시하면
폴링 비용이 0이 된다. 일봉 원본(34MB)은 이미 있으니 새로 모을 것도 없다.

120일이 안 되는 종목(신규 상장 등)은 아예 넣지 않는다 — 데이터가 모자란 채로
'신고가'라고 표시하면 거짓 신호가 된다.
"""
import csv, glob, os, sys
import pandas as pd

WINDOW = 120
DAILY_DIR = os.path.join("data", "stocks", "daily")
OUT = os.path.join("data", "high120.csv")


def high_of(path, window=WINDOW, exclude_last=False):
    """(종목코드, 120일 최고가, 기준일). 봉이 모자라면 None.

    기본은 마지막 봉까지 포함한다 — 장 마감 후에 만들어 **다음 세션**을 판정하는 값이라
    그래야 맞다. exclude_last=True 면 마지막 봉을 빼는데, 그날 데이터로 화면을 테스트할 때
    쓴다(포함해두면 '당일 고가 > 당일 고가'가 되어 신고가가 절대 안 잡힌다 — 실측).
    """
    try:
        d = pd.read_csv(path, usecols=["date", "high"])
    except (ValueError, OSError):
        return None
    if exclude_last:
        d = d.iloc[:-1]
    if len(d) < window:
        return None
    tail = d.tail(window)
    return os.path.basename(path)[:-4], float(tail.high.max()), str(d.date.iloc[-1])


def build(daily_dir=DAILY_DIR, out=OUT, exclude_last=False):
    rows, skipped = [], 0
    for p in sorted(glob.glob(os.path.join(daily_dir, "*.csv"))):
        r = high_of(p, exclude_last=exclude_last)
        if r is None:
            skipped += 1
            continue
        rows.append(r)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "high120", "asof"])
        w.writerows(rows)
    return rows, skipped


def load(path=OUT):
    """{코드: (120일최고가, 기준일)}. 파일이 없으면 빈 dict — 별표만 안 붙고 화면은 산다."""
    try:
        with open(path, encoding="utf-8") as f:
            return {r["code"]: (float(r["high120"]), r["asof"]) for r in csv.DictReader(f)}
    except (OSError, ValueError, KeyError):
        return {}


def demo():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        d = os.path.join(td, "daily"); os.makedirs(d)
        # 120봉 종목: 최고가 500이 뒤쪽 120봉 안에 있고, 900은 그 앞이라 제외돼야 한다
        long_ = pd.DataFrame({"date": pd.bdate_range("2024-01-01", periods=130).strftime("%Y-%m-%d"),
                              "high": [900] * 10 + [100] * 119 + [500], "low": 1, "close": 1, "open": 1})
        long_.to_csv(os.path.join(d, "000001.csv"), index=False)
        pd.DataFrame({"date": ["2026-08-21"], "high": [10], "low": [1], "close": [1], "open": [1]}
                     ).to_csv(os.path.join(d, "000002.csv"), index=False)   # 봉 부족
        out = os.path.join(td, "high120.csv")
        rows, skipped = build(d, out)
        assert skipped == 1, skipped
        assert len(rows) == 1 and rows[0][0] == "000001", rows
        assert rows[0][1] == 500, f"120봉 밖의 900이 섞이면 안 된다: {rows[0][1]}"
        # 마지막 봉(500)을 빼면 창이 하루 뒤로 밀려 그 앞의 900 하나가 들어온다.
        # 그날 데이터로 화면을 테스트할 때 '당일 고가 vs 당일 고가' 자기비교를 피하는 용도다.
        rows2, _ = build(d, os.path.join(td, "high120_x.csv"), exclude_last=True)
        assert rows2[0][1] == 900, f"창이 한 칸 밀려 900이 들어와야 한다: {rows2[0][1]}"
        m = load(out)
        assert m["000001"][0] == 500 and "000002" not in m
    print("demo ok: 120봉 미만 제외, 창 밖 고가 제외")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        rows, skipped = build(exclude_last="--exclude-last" in sys.argv)
        asof = max((r[2] for r in rows), default="-")
        print(f"{OUT}: {len(rows)}종목 (봉 부족 제외 {skipped}) 기준일 {asof} "
              f"{os.path.getsize(OUT)/1024:.0f}KB")
