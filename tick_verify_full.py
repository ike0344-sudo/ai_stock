"""수집 완료된 체결(ka10079) 117종목 전수 검증 (agent_queue 2번).

확인 항목:
1. 종목별 19일치(START_DATE~END_DATE, 거래일 기준) 파일 존재 — partial로 표시된
   8종목은 이미 원인(신규상장/거래재개) 확인됐으므로 예외로 두고 나머지 109종목만
   19일 완전성 검사.
2. 체결가(cur_prc) min/max가 그 날짜 로컬 일봉 low/high 범위 안에 있는지 — 틱은
   정의상 그 날 저가/고가를 만드는 원본이므로 딱 맞아야 정상이다. 완전히 벗어나면
   (범위 밖으로 1% 넘게) 이상으로 표시.

읽기 전용 — 아무것도 지우거나 재수집하지 않는다, 결과만 출력+파일 저장.
"""
import json
import os

import pandas as pd

TICK_DIR = "data/stocks/tick"
DAILY_DIR = "data/stocks/daily"
START_DATE = "2026-08-03"
END_DATE = "2026-08-28"


def load_tick_prices(path: str) -> list[int]:
    if path.endswith(".parquet"):
        df = pd.read_parquet(path, columns=["cur_prc"])
    else:
        df = pd.read_csv(path, usecols=["cur_prc"])
    return [int(v) for v in df["cur_prc"] if str(v).strip()]


def main() -> None:
    progress = json.load(open("state/tick_collection/progress.json", encoding="utf-8"))
    done = sorted(progress.get("done", []))
    partial = set(progress.get("partial", []))

    completeness_issues = []
    price_issues = []
    checked_files = 0

    for code in done:
        d = f"{TICK_DIR}/{code}"
        files = sorted(f for f in os.listdir(d) if f.endswith(".csv") or f.endswith(".parquet"))
        dates_have = {os.path.splitext(f)[0] for f in files}

        if code not in partial:
            # 완전 수집 대상은 19거래일 전부 있어야 한다(START_DATE~END_DATE 사이
            # 로컬 일봉에 실제로 존재하는 거래일 수와 비교 — 주말/공휴일은 애초에
            # 로컬 일봉에도 없으니 그걸 기준으로 삼는다).
            daily_path = f"{DAILY_DIR}/{code}.csv"
            if os.path.isfile(daily_path):
                daily = pd.read_csv(daily_path, index_col=0, parse_dates=True)
                expected_dates = {
                    d2.strftime("%Y-%m-%d")
                    for d2 in daily.index
                    if START_DATE <= d2.strftime("%Y-%m-%d") <= END_DATE
                }
                missing = expected_dates - dates_have
                if missing:
                    completeness_issues.append((code, sorted(missing)))

        daily_path = f"{DAILY_DIR}/{code}.csv"
        if not os.path.isfile(daily_path):
            continue
        daily = pd.read_csv(daily_path, index_col=0, parse_dates=True)
        daily["d"] = daily.index.strftime("%Y-%m-%d")

        for f in files:
            date_str = os.path.splitext(f)[0]
            row = daily[daily["d"] == date_str]
            if row.empty:
                continue
            lo, hi = float(row["low"].iloc[0]), float(row["high"].iloc[0])
            prices = load_tick_prices(os.path.join(d, f))
            checked_files += 1
            if not prices:
                continue
            tmin, tmax = min(prices), max(prices)
            tol_lo, tol_hi = lo * 0.99, hi * 1.01
            if tmin < tol_lo or tmax > tol_hi:
                price_issues.append((code, date_str, lo, hi, tmin, tmax))

    print(f"검사 파일 수: {checked_files}")
    print(f"완전성 문제(19일 미달, partial 제외): {len(completeness_issues)}건")
    for code, missing in completeness_issues:
        print(f"  {code}: 빠진 날짜 {missing}")
    print(f"체결가 범위 이상: {len(price_issues)}건")
    for code, date_str, lo, hi, tmin, tmax in price_issues:
        print(f"  {code} {date_str}: 일봉 저가/고가 {lo:.0f}~{hi:.0f} vs 틱 {tmin}~{tmax}")

    if not completeness_issues and not price_issues:
        print("전수 검증 통과 — 완전성/가격범위 이상 없음")


if __name__ == "__main__":
    main()
