"""일봉 3축 측정 — strategy-agent 사전등록(방향 재설정 라운드)
(`state/agent_reports/strategy-agent_20260901-0040_daily_bar_prereg.md`)
그대로 실행. 틱(1차 라운드)의 "선후관계 59.6%/중앙값 -8초"(가격이 대금폭발
보다 먼저) 발견을 반영해, 이번엔 틱 대신 일봉으로 같은 "눌림 후 반등" 패턴을
훨씬 큰 자유도(IS≈5.7년/OOS≈1.7년)로 재검증한다.

## 재사용
`theme_rank_prereg_measure.py`의 `COST`(0.0052, 상속)/`T_CRIT`(1.65)/
`one_sample_ttest`/`two_sample_ttest`/`_verdict` 그대로 가져온다 - t검정
로직 중복 구현 금지.

## 데이터
`data/stocks/daily/<code>.csv`(2,413종목 - 사전등록의 "1,048은 구정보"
주장을 그대로 안 믿고 직접 Glob 재확인함, 일치). 컬럼 `date,open,high,low,
close,volume`뿐 - 매수/매도 구분 없음(사전등록이 이미 확인, H2를 CLV로
재정의한 이유).

## 캘린더·리밸런스 그리드
전 종목 date의 합집합을 거래일 캘린더로 쓴다(개별 종목의 상장일 이전/거래
정지일은 그 종목만 결측일 뿐 캘린더 자체는 왜곡 안 됨 - 다른 종목이 그날
거래했으면 캘린더에 남는다). 그 캘린더에서 **5거래일 간격**으로 리밸런스
시점을 뽑되, `t-5`(ret_5d 계산용)와 `t+1..t+5`(진입~청산)가 전부 캘린더
안에 들어오는 지점만 쓴다.

## 신호/진입/청산 (look-ahead 차단)
신호(`ret_5d[t]`, `clv[t]`)는 t일 종가까지 확정된 값만 사용. **진입은
t+1일 시가**, 청산은 H1/H2 "종가-종가"(t+1+5거래일째 종가) 또는 H3
"장중전용"(매일 시가→종가 5일 복리, 갭 제외 — 신호의 갭-의존성만 분리하는
목적, 실전 재진입비용 계산 아님).

## 표본 단위
일(리밸런스 시점), 비중첩. 그 시점의 동일가중 포트폴리오 수익률 1개가
관측치 하나(종목x일 단위 아님 - 사전등록 근거: 날짜 간 공통 시장충격
자기상관을 리밸런스 단위로 흡수).

실행: python -m backtesting.daily_bar_prereg_measure
"""
import glob
import os
import time

import numpy as np
import pandas as pd

from backtesting.theme_rank_prereg_measure import COST, T_CRIT, _verdict, one_sample_ttest, two_sample_ttest

DAILY_DIR = "data/stocks/daily"
IS_RANGE = ("2019-04-23", "2024-12-31")
OOS_RANGE = ("2025-01-01", "2026-08-31")
REBALANCE_STEP = 5  # 거래일
HORIZON = 5  # 거래일 forward
MIN_CROSS_SECTION = 25  # 하루 퀸타일을 내기 위한 최소 유니버스 크기(임의값, 문서화)
MIN_PERIODS = 200  # 사전등록 최소표본


def load_panel(daily_dir: str = DAILY_DIR) -> pd.DataFrame:
    # lead 지시(20260901 일봉캐시 편지): 종목별 CSV 대신 합친 parquet 캐시를 쓴다 - 판단 로직은 그대로.
    from backtesting.daily_cache import load_daily_all

    panel = load_daily_all(daily_dir)[["date", "open", "high", "low", "close", "code"]]
    return panel.sort_values(["code", "date"]).reset_index(drop=True)


def add_features(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel.copy()
    panel["ret_5d"] = panel.groupby("code")["close"].transform(lambda s: s / s.shift(5) - 1)
    hl = panel["high"] - panel["low"]
    panel["clv"] = np.where(hl > 0, (panel["close"] - panel["low"]) / hl, np.nan)
    return panel


def build_calendar(panel: pd.DataFrame) -> list[str]:
    return sorted(panel["date"].unique().tolist())


def rebalance_grid(calendar: list[str]) -> list[int]:
    """t-5(피처)와 t+1..t+HORIZON(체결)이 전부 캘린더 안에 들어오는 그리드
    인덱스 목록."""
    n = len(calendar)
    idx = []
    i = 5
    while i + 1 + HORIZON < n:
        idx.append(i)
        i += REBALANCE_STEP
    return idx


def quintile_groups(cross: pd.DataFrame, col: str) -> tuple[list[str], list[str]]:
    """cross(그 날짜의 종목별 피처 표)를 col 기준 5분위해 (Q1=최하위,
    Q5=최상위) 종목코드 리스트를 반환. 동률이 많아 5분위가 안 나오면
    duplicates='drop'로 완화."""
    try:
        bins = pd.qcut(cross[col], 5, labels=False, duplicates="drop")
    except ValueError:
        return [], []
    n_bins = bins.nunique()
    if n_bins < 2:
        return [], []
    q1 = cross.loc[bins == bins.min(), "code"].tolist()
    q5 = cross.loc[bins == bins.max(), "code"].tolist()
    return q1, q5


def portfolio_return(codes: list[str], entry_date: str, exit_date: str,
                      pivot_open: pd.DataFrame, pivot_close: pd.DataFrame) -> tuple[float, int]:
    if not codes:
        return np.nan, 0
    opens = pivot_open.loc[entry_date, codes]
    closes = pivot_close.loc[exit_date, codes]
    valid = opens.notna() & closes.notna() & (opens > 0)
    rets = closes[valid] / opens[valid] - 1
    return (float(rets.mean()), int(valid.sum())) if valid.sum() > 0 else (np.nan, 0)


def intraday_only_return(codes: list[str], calendar: list[str], start_idx: int,
                          pivot_open: pd.DataFrame, pivot_close: pd.DataFrame) -> tuple[float, int]:
    """진입일부터 HORIZON거래일 동안 매일 시가->종가 수익률만 복리(갭 제외)."""
    if not codes:
        return np.nan, 0
    dates = calendar[start_idx:start_idx + HORIZON]
    opens = pivot_open.loc[dates, codes]
    closes = pivot_close.loc[dates, codes]
    daily_ret = closes / opens - 1
    compounded = (1 + daily_ret).prod(axis=0, skipna=False) - 1
    compounded = compounded.dropna()
    return (float(compounded.mean()), len(compounded)) if len(compounded) else (np.nan, 0)


def compute_portfolio_series(panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    calendar = build_calendar(panel)
    grid = rebalance_grid(calendar)
    pivot_open = panel.pivot(index="date", columns="code", values="open")
    pivot_close = panel.pivot(index="date", columns="code", values="close")
    group_by_date = dict(tuple(panel.groupby("date")))

    rows_h1, rows_h2, rows_h3 = [], [], []
    for i in grid:
        t = calendar[i]
        entry_date, exit_date = calendar[i + 1], calendar[i + 1 + HORIZON]
        cross = group_by_date.get(t)
        if cross is None:
            continue

        h1_cross = cross.dropna(subset=["ret_5d"])
        if len(h1_cross) >= MIN_CROSS_SECTION:
            q1, q5 = quintile_groups(h1_cross, "ret_5d")
            q1_ret, n_q1 = portfolio_return(q1, entry_date, exit_date, pivot_open, pivot_close)
            q5_ret, n_q5 = portfolio_return(q5, entry_date, exit_date, pivot_open, pivot_close)
            rows_h1.append({"date": t, "q1_ret": q1_ret, "q5_ret": q5_ret, "n_q1": n_q1, "n_q5": n_q5})

            intraday_ret, n_intraday = intraday_only_return(q1, calendar, i + 1, pivot_open, pivot_close)
            rows_h3.append({"date": t, "gap_included_ret": q1_ret, "intraday_only_ret": intraday_ret,
                             "n": n_intraday})

        h2_cross = cross.dropna(subset=["clv"])
        if len(h2_cross) >= MIN_CROSS_SECTION:
            q1c, q5c = quintile_groups(h2_cross, "clv")
            q1c_ret, n_q1c = portfolio_return(q1c, entry_date, exit_date, pivot_open, pivot_close)
            q5c_ret, n_q5c = portfolio_return(q5c, entry_date, exit_date, pivot_open, pivot_close)
            rows_h2.append({"date": t, "q1_ret": q1c_ret, "q5_ret": q5c_ret, "n_q1": n_q1c, "n_q5": n_q5c,
                             "excluded_pct": 1 - len(h2_cross) / len(cross)})

    return {"h1": pd.DataFrame(rows_h1), "h2": pd.DataFrame(rows_h2), "h3": pd.DataFrame(rows_h3)}


def _split(df: pd.DataFrame, date_range: tuple[str, str]) -> pd.DataFrame:
    if df.empty:
        return df
    return df[(df["date"] >= date_range[0]) & (df["date"] <= date_range[1])]


def evaluate_h1(is_df: pd.DataFrame, oos_df: pd.DataFrame) -> list[str]:
    lines = [f"[H1] IS 리밸런스 시점 {len(is_df)}건(최소표본 {MIN_PERIODS} "
             f"{'충족' if len(is_df) >= MIN_PERIODS else '미달-판단보류'})"]
    if len(is_df) < MIN_PERIODS:
        return lines + ["[H1] 판단보류 (표본부족)"]
    q1_net = is_df["q1_ret"].to_numpy(dtype=float) - COST
    mean, t, n = one_sample_ttest(q1_net)
    lines.append(f"[H1] IS Q1 순수익 평균={mean*100:.3f}% t={t:.2f} n={n}")
    cond1 = mean > 0 and t >= T_CRIT
    lines.append(f"[H1] 기각조건1: {_verdict(cond1, 'PASS' if cond1 else '기각')}")
    if not cond1:
        return lines

    diff = is_df["q1_ret"].to_numpy(dtype=float) - is_df["q5_ret"].to_numpy(dtype=float)
    dmean, dt, dn = one_sample_ttest(diff)
    lines.append(f"[H1] IS Q1-Q5 쌍대차 평균={dmean*100:.3f}% t={dt:.2f} n={dn}")
    cond2 = dmean > 0 and dt >= T_CRIT
    lines.append(f"[H1] 기각조건2: {_verdict(cond2, 'PASS' if cond2 else '기각')}")
    if not cond2:
        return lines

    oos_net = oos_df["q1_ret"].to_numpy(dtype=float) - COST
    omean, ot, on = one_sample_ttest(oos_net)
    lines.append(f"[H1] OOS Q1 순수익 평균={omean*100:.3f}% t={ot:.2f} n={on}")
    cond3 = omean > 0 and np.sign(omean) == np.sign(mean)
    lines.append(f"[H1] 기각조건3: {_verdict(cond3, 'PASS(잠정 채택)' if cond3 else '기각')}")
    return lines


def evaluate_h2(is_df: pd.DataFrame, oos_df: pd.DataFrame) -> list[str]:
    lines = [f"[H2] IS 리밸런스 시점 {len(is_df)}건"]
    if len(is_df) < MIN_PERIODS:
        return lines + ["[H2] 판단보류 (표본부족)"]
    lines.append(f"[H2] high==low 제외 비율(IS 평균) = {is_df['excluded_pct'].mean()*100:.2f}%")
    q1_net = is_df["q1_ret"].to_numpy(dtype=float) - COST
    mean, t, n = one_sample_ttest(q1_net)
    lines.append(f"[H2] IS Q1(CLV최저) 순수익 평균={mean*100:.3f}% t={t:.2f} n={n}")
    cond1 = mean > 0 and t >= T_CRIT
    lines.append(f"[H2] 기각조건1: {_verdict(cond1, 'PASS' if cond1 else '기각')}")
    if not cond1:
        return lines

    diff = is_df["q1_ret"].to_numpy(dtype=float) - is_df["q5_ret"].to_numpy(dtype=float)
    dmean, dt, dn = one_sample_ttest(diff)
    lines.append(f"[H2] IS Q1-Q5 쌍대차 평균={dmean*100:.3f}% t={dt:.2f} n={dn}")
    cond2 = dmean > 0 and dt >= T_CRIT
    lines.append(f"[H2] 기각조건2: {_verdict(cond2, 'PASS' if cond2 else '기각')}")
    if not cond2:
        return lines

    oos_net = oos_df["q1_ret"].to_numpy(dtype=float) - COST
    omean, ot, on = one_sample_ttest(oos_net)
    lines.append(f"[H2] OOS Q1 순수익 평균={omean*100:.3f}% t={ot:.2f} n={on}")
    cond3 = omean > 0 and np.sign(omean) == np.sign(mean)
    lines.append(f"[H2] 기각조건3: {_verdict(cond3, 'PASS(잠정 채택)' if cond3 else '기각')}")
    return lines


def evaluate_h3(is_df: pd.DataFrame, oos_df: pd.DataFrame) -> list[str]:
    lines = [f"[H3] IS 리밸런스 시점 {len(is_df)}건(H1과 동일 그리드, 종속 설계)"]
    if len(is_df) < MIN_PERIODS:
        return lines + ["[H3] 판단보류 (표본부족)"]
    intraday_net = is_df["intraday_only_ret"].to_numpy(dtype=float) - COST
    mean, t, n = one_sample_ttest(intraday_net)
    lines.append(f"[H3] IS 장중전용 순수익 평균={mean*100:.3f}% t={t:.2f} n={n}")
    gap_mean = is_df["gap_included_ret"].mean()
    lines.append(f"[H3] (비교) IS 갭포함(H1 Q1) 총수익 평균={gap_mean*100:.3f}%")
    cond1 = mean > 0 and t >= T_CRIT
    lines.append(f"[H3] 기각조건1: {_verdict(cond1, 'PASS' if cond1 else '기각(갭 의존적)')}")
    if not cond1:
        return lines

    same_sign = np.sign(mean) == np.sign(gap_mean)
    lines.append(f"[H3] (참고) 장중전용 부호==갭포함 부호: {same_sign}")

    oos_net = oos_df["intraday_only_ret"].to_numpy(dtype=float) - COST
    omean, ot, on = one_sample_ttest(oos_net)
    lines.append(f"[H3] OOS 장중전용 순수익 평균={omean*100:.3f}% t={ot:.2f} n={on}")
    cond3 = np.sign(omean) == np.sign(mean)
    lines.append(f"[H3] 기각조건3: {_verdict(cond3, 'PASS(잠정 채택)' if cond3 else '기각')}")
    return lines


def main():
    t0 = time.time()
    print("일봉 패널 로드...", flush=True)
    panel = add_features(load_panel())
    print(f"로드 {time.time()-t0:.1f}초 | {panel['code'].nunique():,}종목, {len(panel):,}행", flush=True)

    t1 = time.time()
    series = compute_portfolio_series(panel)
    print(f"포트폴리오 시계열 계산 {time.time()-t1:.1f}초", flush=True)

    os.makedirs("results", exist_ok=True)
    for name, df in series.items():
        df.to_csv(f"results/daily_bar_prereg_{name}.csv", index=False)

    h1_is, h1_oos = _split(series["h1"], IS_RANGE), _split(series["h1"], OOS_RANGE)
    h2_is, h2_oos = _split(series["h2"], IS_RANGE), _split(series["h2"], OOS_RANGE)
    h3_is, h3_oos = _split(series["h3"], IS_RANGE), _split(series["h3"], OOS_RANGE)
    print(f"IS/OOS 리밸런스 건수 - H1: {len(h1_is)}/{len(h1_oos)}, "
          f"H2: {len(h2_is)}/{len(h2_oos)}, H3: {len(h3_is)}/{len(h3_oos)}", flush=True)

    for lines in (evaluate_h1(h1_is, h1_oos), evaluate_h2(h2_is, h2_oos), evaluate_h3(h3_is, h3_oos)):
        for line in lines:
            print(line, flush=True)
        print(flush=True)

    return panel, series


if __name__ == "__main__":
    main()
