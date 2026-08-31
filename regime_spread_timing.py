"""정배열 + 지수가 60선 위일 때, 60/120 이격별 클린20 도달 시간.

    python regime_spread_timing.py

지수 국면은 전부 **09:00 시점** 값으로 잡는다. 도달 시간을 예측하는 이야기라
장 시작 전에 알 수 있는 정보만 써야 한다 — 10:00 값을 쓰면 이미 끝난 케이스의
결과가 국면 판정에 섞여 들어간다.

두 번째 축(종가와 60선의 거리)도 같이 본다. 결론은 60/120 이격이 1%를 넘으면
종가 위치가 의미를 잃는다는 것이라, 볼 지표는 이격 하나로 충분하다.

마지막에 모집단을 도달 전체로 넓혀 국면 x 종목유형을 교차한다. 클린 9건에서 보이던
"이격 3%대는 빠르다"가 여기서는 남지 않는다 — 소요 시간을 정하는 건 국면이 아니라
종목의 성격이다.

유형은 갭과 주가 두 축으로만 나눈다. 둘 다 09:00 이전에 확정되는 값이다.
갭 12% 이상은 74%가 09:03 전에 끝나 살 수가 없다(기존 clean20_list.py의 MIN_MINUTES=3과
같은 기준). 이걸 섞으면 시가갭의 판별력이 부풀려진다 — 실제로 직행을 빼면 갭의 AUC가
0.721에서 0.624로 내려가고, 주가(0.340)가 갭보다 세진다. 그래서 따로 뺀다.
"""
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KOSPI_MINUTE = "data/index/minute/001.csv"
CLEAN_LIST = "results/clean20_dd5_list.csv"


def regime() -> pd.DataFrame:
    """코스피 15분봉 -> 60/120 이평과 두 가지 이격. 거래시간 봉만 이어붙인다."""
    close = pd.read_csv(KOSPI_MINUTE, index_col=0, parse_dates=True).sort_index()["close"]
    k = close.resample("15min").last().dropna()
    d = pd.DataFrame({"k": k, "ma60": k.rolling(60).mean(), "ma120": k.rolling(120).mean()}).dropna()
    d["spread"] = (d["ma60"] / d["ma120"] - 1) * 100     # 60선과 120선
    d["gap60"] = (d["k"] / d["ma60"] - 1) * 100          # 종가와 60선
    d["align"] = d["ma60"] > d["ma120"]
    d["above"] = d["k"] > d["ma60"]
    return d


def cases() -> pd.DataFrame:
    reg = regime()

    def at_open(day: pd.Timestamp):
        w = reg.loc[: f"{day:%Y-%m-%d} 09:00"]
        return w.iloc[-1] if len(w) else None

    clean = pd.read_csv(CLEAN_LIST, parse_dates=["date"], dtype={"stock_code": str})
    rows = []
    for _, r in clean.iterrows():
        s = at_open(r["date"])
        if s is None:
            continue
        rows.append({"m": r["minutes_to_20"], "dd": r["max_dd_pct"], "e": r["close_ret_pct"],
                     "spread": s["spread"], "gap60": s["gap60"],
                     "align": bool(s["align"]), "above": bool(s["above"])})
    return pd.DataFrame(rows)


def band(d: pd.DataFrame, col: str, cuts: list[tuple[float, float, str]], title: str) -> None:
    print(f"\n{title}")
    print(f"{'구간':<18}{'건수':>5}{'중앙값':>8}{'평균':>8}{'10시전':>8}{'2시간+':>8}")
    for lo, hi, lab in cuts:
        g = d[(d[col] >= lo) & (d[col] < hi)]
        if len(g) < 2:
            continue
        m = g["m"]
        print(f"  {lab:<16}{len(g):>5}{m.median():>7.0f}분{m.mean():>7.0f}분"
              f"{(m <= 60).mean() * 100:>7.0f}%{(m > 120).mean() * 100:>7.0f}%")


def classify(gap: float, price: float) -> str:
    """갭과 주가만으로 나눈다 — 둘 다 09:00 이전에 확정되는 값이다.

    이름은 정의 그대로 쓴다. '시초형' 같은 결론을 이름에 넣으면 데이터가 바뀔 때
    이름이 조용히 거짓이 된다.
    """
    if gap >= INSTANT_GAP:
        return "갭12%+ 직행"
    return ("갭5~12% · " if gap >= 5 else "갭<5% · ") + ("저가" if price < 30_000 else "고가")


TYPES = ["갭5~12% · 저가", "갭5~12% · 고가", "갭<5% · 저가", "갭<5% · 고가"]
INSTANT_GAP = 12.0


def cross() -> None:
    """국면 x 종목유형. 직행은 매수 자체가 안 되므로 교차에서 뺀다."""
    from clean20_conditions import load

    reg = regime()

    def at_open(day: pd.Timestamp):
        w = reg.loc[: f"{day:%Y-%m-%d} 09:00"]
        return w.iloc[-1] if len(w) else None

    df = load()
    rows = []
    for _, x in df[df["reached"]].iterrows():
        s = at_open(x["date"])
        if s is None:
            continue
        rows.append({"m": x["minutes_to_20"],
                     "type": classify(x["open_gap_pct"], 10 ** x["price_log"]),
                     "reg": "역배열" if not s["align"]
                            else ("정배열 0~2%" if s["spread"] < 2 else "정배열 2%+")})
    d = pd.DataFrame(rows)

    print()
    print(f"[유형별] 도달 {len(d)}건")
    print(f"{'유형':<16}{'건수':>5}{'중앙':>7}{'3분내':>7}{'30분내':>8}{'1시간+':>8}")
    for t in ["갭12%+ 직행", *TYPES]:
        g = d[d["type"] == t]["m"]
        print(f"  {t:<14}{len(g):>5}{g.median():>6.0f}분{(g <= 3).mean() * 100:>6.0f}%"
              f"{(g <= 30).mean() * 100:>7.0f}%{(g >= 60).mean() * 100:>7.0f}%")

    live = d[d["type"] != "갭12%+ 직행"]
    print()
    print(f"[국면 x 유형] 직행 제외 {len(live)}건 — 중앙값(건수)")
    print(f"{'국면':<13}" + "".join(f"{t:>16}" for t in TYPES))
    for g in ["역배열", "정배열 0~2%", "정배열 2%+"]:
        cells = []
        for t in TYPES:
            x = live[(live["reg"] == g) & (live["type"] == t)]["m"]
            cells.append(f"{x.median():.0f}분({len(x)})" if len(x) >= 5 else f"-({len(x)})")
        print(f"  {g:<11}" + "".join(f"{c:>16}" for c in cells))

    # 리포트의 주장: 유형이 국면보다 세다. 유형별 중앙값 폭이 국면별 폭보다 커야 한다.
    by_type = [live[live["type"] == t]["m"].median() for t in TYPES]
    spread_type = max(by_type) - min(by_type)
    by_reg = [live[live["reg"] == g]["m"].median() for g in ["역배열", "정배열 0~2%", "정배열 2%+"]]
    spread_reg = max(by_reg) - min(by_reg)
    assert spread_type > spread_reg, f"국면 폭({spread_reg})이 유형 폭({spread_type})을 넘었다 — 리포트 수정 필요"
    print(f"  유형별 중앙값 폭 {spread_type:.0f}분 > 국면별 폭 {spread_reg:.0f}분 (리포트 주장 유지)")


def main() -> None:
    d = cases()
    base = d[d["align"] & d["above"]]
    print(f"클린 {len(d)}건 · 그중 정배열 + 종가>60선 {len(base)}건")

    band(base, "spread",
         [(0, 1, "0~1% 초입"), (1, 2, "1~2%"), (2, 2.5, "2.0~2.5%"),
          (2.5, 3.5, "2.5~3.5%"), (3.5, 99, "3.5%+")],
         "60/120 이격별")
    band(base, "gap60",
         [(0, 0.3, "0~0.3%"), (0.3, 0.7, "0.3~0.7%"), (0.7, 1.2, "0.7~1.2%"), (1.2, 99, "1.2%+")],
         "종가-60선 이격별")

    print("\n교차 (중앙값 / 건수)")
    print(f"{'60/120 이격':<14}{'종가-60선 <0.5%':>18}{'>=0.5%':>14}")
    for lo, hi, lab in [(0, 1, "0~1%"), (1, 2, "1~2%"), (2, 99, "2%+")]:
        g = base[(base["spread"] >= lo) & (base["spread"] < hi)]
        cells = []
        for sub in (g[g["gap60"] < 0.5], g[g["gap60"] >= 0.5]):
            cells.append(f"{sub['m'].median():.0f}분({len(sub)})" if len(sub) >= 3 else f"-({len(sub)})")
        print(f"  {lab:<12}{cells[0]:>18}{cells[1]:>14}")

    # 이 분석의 결론 한 줄. 숫자가 바뀌어도 이 관계가 뒤집히면 리포트를 고쳐야 한다.
    fast = base[base["spread"] >= 2]
    assert (fast["m"] > 120).sum() == 0, "이격 2%+ 에서 2시간 초과가 생겼다 — 리포트 수정 필요"
    print(f"\n이격 2%+ {len(fast)}건 중 2시간 초과 0건 (리포트 주장 유지)")
    cross()


if __name__ == "__main__":
    main()
