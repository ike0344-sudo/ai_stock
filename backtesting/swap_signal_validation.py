"""§3 교체신호 실전조건 검증 — lead 지시(2026-09-01), 사전등록
`backtest-agent_20260901-180000_swap_signal_prereg.md`을 그대로 실행한다.
문턱은 전부 사전등록에 이미 박혀 있다 — 여기서 새로 고르지 않는다.

## 재사용
`chgtop_leader_persistence.build_swap_dataset`(오늘 `lag_minutes` 인자 추가,
하위호환)을 그대로 쓴다 - 새 시뮬레이션 로직 없음, 인자 하나로 지연을 넣는다.
`chgtop_al_remeasure.AL_MINUTE_DIR`/`covered_dates`, `is/oos_dates_valid`도 그대로.

실행: python -X utf8 -m backtesting.swap_signal_validation
"""
import numpy as np
import pandas as pd

from backtesting.chgtop_al_remeasure import AL_MINUTE_DIR, covered_dates
from backtesting.chgtop_leader_persistence import (
    FORWARD_MIN,
    MinuteCloseLookup,
    build_swap_dataset,
    full_dates_available,
)
from backtesting.theme_rank_prereg_measure import (
    is_dates_valid,
    load_name_to_code,
    oos_dates_valid,
)

COST_CONSTANTS = {"0.46%(기존전략)": 0.0046, "0.52%(틱연구)": 0.0052}
LAG_MIN = 1
T_CRIT = 1.65  # 단측 5%
MIN_SAMPLE = 30
FREQ_MIN_PER_DAY = 1.0
DATE_CONCENTRATION_MAX = 0.30


def _day_clustered(df: pd.DataFrame, col: str) -> tuple[float, float, int, int]:
    daily = df.groupby("date")[col].mean()
    n_days = len(daily)
    se = daily.std(ddof=1) / np.sqrt(n_days) if n_days > 1 else np.nan
    return float(df[col].mean()), float(se), len(df), n_days


def standalone_net_table(sw: pd.DataFrame, label: str) -> pd.DataFrame:
    """단독 신규리더 매수 순수익 - 두 비용상수 나란히(지시 1번)."""
    rows = []
    for cost_label, cost in COST_CONSTANTS.items():
        for k in FORWARD_MIN:
            col = f"new_ret_{k}m"
            sub = sw.dropna(subset=[col]).copy()
            if sub.empty:
                rows.append({"set": label, "cost": cost_label, "horizon": f"{k}m", "n": 0})
                continue
            sub["net"] = sub[col] - cost
            mean, se, n, n_days = _day_clustered(sub, "net")
            rows.append({"set": label, "cost": cost_label, "horizon": f"{k}m", "n": n, "n_days": n_days,
                         "net_mean_pct": mean * 100, "t": mean / se if se else np.nan,
                         "signals_per_day": n / n_days if n_days else np.nan})
    return pd.DataFrame(rows)


def pairwise_table(sw: pd.DataFrame, label: str) -> pd.DataFrame:
    rows = []
    for k in FORWARD_MIN:
        d = (sw[f"new_ret_{k}m"] - sw[f"old_ret_{k}m"]).dropna()
        if d.empty:
            rows.append({"set": label, "horizon": f"{k}m", "n": 0})
            continue
        tmp = pd.DataFrame({"date": sw.loc[d.index, "date"], "diff": d})
        mean, se, n, n_days = _day_clustered(tmp, "diff")
        rows.append({"set": label, "horizon": f"{k}m", "n": n, "n_days": n_days,
                     "diff_mean_pct": mean * 100, "t": mean / se if se else np.nan})
    return pd.DataFrame(rows)


def date_concentration(sw: pd.DataFrame, horizon: str = "1m") -> pd.DataFrame:
    d = (sw[f"new_ret_{horizon}"] - sw[f"old_ret_{horizon}"]).dropna()
    tmp = pd.DataFrame({"date": sw.loc[d.index, "date"], "diff": d})
    by_day = tmp.groupby("date")["diff"].sum()
    total = by_day.sum()
    share = (by_day / total).sort_values(ascending=False) if total != 0 else by_day * 0
    return pd.DataFrame({"date": share.index, "share_of_total": share.values})


def main() -> None:
    name_to_code = load_name_to_code()
    lookup = MinuteCloseLookup(AL_MINUTE_DIR)
    full_dates = set(full_dates_available())
    is_dates = covered_dates([d for d in is_dates_valid(exclude=False) if d in full_dates])
    oos_dates = covered_dates([d for d in oos_dates_valid(exclude=False) if d in full_dates])

    pd.set_option("display.width", 220)

    print("=== (1) 비용 두 상수 - 단독 신규리더 매수 순수익 (지연 없음) ===")
    swap_is0 = build_swap_dataset(is_dates, name_to_code, lookup, lag_minutes=0)
    swap_oos0 = build_swap_dataset(oos_dates, name_to_code, lookup, lag_minutes=0)
    cost_tbl = pd.concat([standalone_net_table(swap_is0, "IS"), standalone_net_table(swap_oos0, "OOS")])
    print(cost_tbl.to_string(index=False))

    print("\n=== (2) 빈도 ===")
    n_days_is = len(is_dates)
    print(f"IS: {len(swap_is0)}건 / {n_days_is}일 = 일평균 {len(swap_is0)/n_days_is:.2f}건")
    freq_ok = (len(swap_is0) / n_days_is) >= FREQ_MIN_PER_DAY
    print(f"기각조건(b) 빈도<1건/일: {'걸림(기각)' if not freq_ok else '통과'}")

    print("\n=== (3) OOS 감쇠곡선 (지연 없음, 쌍대비교) ===")
    decay = pd.concat([pairwise_table(swap_is0, "IS"), pairwise_table(swap_oos0, "OOS")])
    print(decay.to_string(index=False))

    print(f"\n=== (4) 실행지연 {LAG_MIN}분 반영 재측정 (쌍대비교) ===")
    swap_is_lag = build_swap_dataset(is_dates, name_to_code, lookup, lag_minutes=LAG_MIN)
    swap_oos_lag = build_swap_dataset(oos_dates, name_to_code, lookup, lag_minutes=LAG_MIN)
    lag_tbl = pd.concat([pairwise_table(swap_is_lag, "IS(지연1분)"), pairwise_table(swap_oos_lag, "OOS(지연1분)")])
    print(lag_tbl.to_string(index=False))

    is_1m_lag = lag_tbl[(lag_tbl["set"] == "IS(지연1분)") & (lag_tbl["horizon"] == "1m")].iloc[0]
    lag_t = is_1m_lag["t"]
    lag_ok = pd.notna(lag_t) and lag_t >= T_CRIT
    lag_verdict = "통과" if lag_ok else "걸림(기각)"
    print(f"기각조건(c) 지연 후 IS 1분 t<{T_CRIT}: {lag_verdict}, t={lag_t:.2f}")

    print("\n=== (5) 날짜편중 (IS, 1분, 지연없음) ===")
    conc = date_concentration(swap_is0, "1m")
    print(conc.head(5).to_string(index=False))
    top_share = conc["share_of_total"].iloc[0] if len(conc) else np.nan
    conc_ok = pd.notna(top_share) and top_share < DATE_CONCENTRATION_MAX
    conc_verdict = "통과" if conc_ok else "걸림(기각)"
    print(f"기각조건(d) 상위1일 비중>={DATE_CONCENTRATION_MAX*100:.0f}%: {conc_verdict}, {top_share*100:.1f}%")

    print("\n=== 사전등록 판정 요약 ===")
    cost_ok = {}
    for cost_label in COST_CONSTANTS:
        row = cost_tbl[(cost_tbl["set"] == "IS") & (cost_tbl["cost"] == cost_label) & (cost_tbl["horizon"] == "1m")]
        if row.empty or row.iloc[0]["n"] == 0:
            cost_ok[cost_label] = False
            continue
        r = row.iloc[0]
        cost_ok[cost_label] = (r["net_mean_pct"] > 0) and (pd.notna(r["t"]) and r["t"] >= T_CRIT)
        print(f"  비용{cost_label}: IS 1분 순수익 {r['net_mean_pct']:.3f}%, t={r['t']:.2f} -> "
              f"{'통과' if cost_ok[cost_label] else '기각(a)'}")

    n_lag = int(is_1m_lag["n"]) if pd.notna(is_1m_lag["n"]) else 0
    if n_lag < MIN_SAMPLE:
        verdict = "판정보류(표본부족)"
    elif not freq_ok or not any(cost_ok.values()) or not lag_ok:
        verdict = "기각"
    elif not conc_ok:
        verdict = "유지하나 일화적 성격 강함(날짜편중)"
    else:
        verdict = "유지(사전등록 4조건 통과 - '검증됨'은 아님, 표본 1회분)"
    print(f"\n최종: {verdict}")


if __name__ == "__main__":
    main()
