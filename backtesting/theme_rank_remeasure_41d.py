"""테마순위 3축 재측정 — 41일 균일 재생성본(오염 제외 없음) vs 잠정 라운드
(34일, 오염 7일 제외) 나란히 비교. lead 확인(0110): 큐 항목은 "3라운드
보류"(strategy-agent의 새 가설 생성 금지) 대상이 아니다 - 기존 사전등록
(`strategy-agent_20260831-2240_theme_rank_prereg.md`)을 그대로 재실행한다.

## 무엇이 달라졌나
1차(잠정) 라운드는 오염 7일(0701,02,03,06,07,08,0813)을 뺀 34일로 돌았다.
data-agent가 41일 전체를 한 배치로 재생성해(196170 lead_pct 이상도 해소,
`backtest-agent_20260831-232156` 참고) **이제 제외가 불필요**하다 -
`theme_rank_prereg_measure.is_dates_valid(exclude=False)`로 41일 전량을
쓴다. **문턱·기각조건은 그대로**(표본이 늘었다고 완화 안 함).

## 비교 방식
잠정 라운드는 재실행하지 않는다(저장된 `results/theme_rank_h{1,2,3}_
{is,oos}.csv`가 이미 그 라운드의 원자료라 그대로 재사용 - 다시 스캔하면
같은 결과가 나올 뿐 아니라 원본이 이미 있는데 다시 만드는 건 낭비다).
41일본만 새로 측정하고, 두 원자료에 각각 `evaluate_h{1,2,3}`를 돌려 나온
지표를 나란히 표로 낸다.

실행: python -X utf8 -m backtesting.theme_rank_remeasure_41d
"""
import os

import numpy as np
import pandas as pd

from backtesting.theme_rank_prereg_measure import (
    COST,
    DailyPriceLookup,
    T_CRIT,
    h1_measure,
    h2_measure,
    h3_measure,
    is_dates_valid,
    load_name_to_code,
    one_sample_ttest,
    oos_dates_valid,
    two_sample_ttest,
)


def _h1_summary(is_df: pd.DataFrame, oos_df: pd.DataFrame, label: str) -> dict:
    row = {"round": label, "hypothesis": "H1", "n_is": len(is_df), "n_oos": len(oos_df)}
    if len(is_df) < 20:
        row["verdict"] = "판단보류(표본부족)"
        return row
    mean, t, n = one_sample_ttest(is_df["change_net"].to_numpy(dtype=float))
    row.update({"is_mean_pct": mean * 100, "is_t": t})
    if not (mean > 0 and t >= T_CRIT):
        row["verdict"] = "기각(조건1)"
        return row
    diff = is_df["change_net"].to_numpy(dtype=float) - is_df["level_net"].to_numpy(dtype=float)
    dmean, dt, _ = one_sample_ttest(diff)
    if not (dmean > 0 and dt >= T_CRIT):
        row["verdict"] = "기각(조건2: 쌍대차)"
        return row
    omean, ot, on = one_sample_ttest(oos_df["change_net"].to_numpy(dtype=float))
    row.update({"oos_mean_pct": omean * 100, "oos_t": ot})
    row["verdict"] = "PASS(잠정 채택)" if (omean > 0 and np.sign(omean) == np.sign(mean)) else "기각(조건3: OOS)"
    return row


def _h2_summary(is_df: pd.DataFrame, oos_df: pd.DataFrame, label: str) -> dict:
    row = {"round": label, "hypothesis": "H2", "n_is": len(is_df), "n_oos": len(oos_df)}
    if len(is_df) < 20:
        row["verdict"] = "판단보류(표본부족)"
        return row
    thresh = is_df["mode_share"].median()
    is_fixed = is_df[is_df["mode_share"] >= thresh]["net"].to_numpy(dtype=float)
    is_varying = is_df[is_df["mode_share"] < thresh]["net"].to_numpy(dtype=float)
    mean, t, n = one_sample_ttest(is_fixed)
    row.update({"is_mean_pct": mean * 100, "is_t": t})
    if not (mean > 0 and t >= T_CRIT):
        row["verdict"] = "기각(조건1)"
        return row
    dmean, dt, _, _ = two_sample_ttest(is_fixed, is_varying)
    if not (dmean > 0 and dt >= T_CRIT):
        row["verdict"] = "기각(조건2: 고정-변동차)"
        return row
    oos_thresh_mask = oos_df["mode_share"] >= thresh
    omean, ot, on = one_sample_ttest(oos_df[oos_thresh_mask]["net"].to_numpy(dtype=float))
    row.update({"oos_mean_pct": omean * 100, "oos_t": ot})
    row["verdict"] = "PASS(잠정 채택)" if (omean > 0 and np.sign(omean) == np.sign(mean)) else "기각(조건3: OOS)"
    return row


def _h3_summary(is_df: pd.DataFrame, oos_df: pd.DataFrame, label: str) -> dict:
    row = {"round": label, "hypothesis": "H3", "n_is": len(is_df), "n_oos": len(oos_df)}
    if len(is_df) < 20:
        row["verdict"] = "판단보류(표본부족)"
        return row
    mean, t, n = one_sample_ttest(is_df["diff"].to_numpy(dtype=float))
    row.update({"is_mean_pct": mean * 100, "is_t": t})
    cond1 = mean > 0 and t >= T_CRIT
    cond2 = abs(mean) >= COST
    if not (cond1 and cond2):
        row["verdict"] = "기각(조건1/2)"
        return row
    omean, ot, on = one_sample_ttest(oos_df["diff"].to_numpy(dtype=float))
    row.update({"oos_mean_pct": omean * 100, "oos_t": ot})
    row["verdict"] = "PASS(잠정 채택)" if np.sign(omean) == np.sign(mean) else "기각(조건3: OOS)"
    return row


def main():
    print("41일 전량(오염 제외 없음) 측정...", flush=True)
    prices = DailyPriceLookup()
    name_to_code = load_name_to_code()
    is_dates = is_dates_valid(exclude=False)
    oos_dates = oos_dates_valid(exclude=False)
    print(f"41일본: IS {len(is_dates)}일 / OOS {len(oos_dates)}일 "
          f"(잠정 라운드는 IS 21일/OOS 13일이었음)", flush=True)

    h1_is41, h1_oos41 = h1_measure(is_dates, prices, name_to_code), h1_measure(oos_dates, prices, name_to_code)
    h2_is41, h2_oos41 = h2_measure(is_dates, prices, name_to_code), h2_measure(oos_dates, prices, name_to_code)
    h3_is41, h3_oos41 = h3_measure(is_dates, prices, name_to_code), h3_measure(oos_dates, prices, name_to_code)

    os.makedirs("results", exist_ok=True)
    for name, df in (("h1_is_41d", h1_is41), ("h1_oos_41d", h1_oos41), ("h2_is_41d", h2_is41),
                      ("h2_oos_41d", h2_oos41), ("h3_is_41d", h3_is41), ("h3_oos_41d", h3_oos41)):
        df.to_csv(f"results/theme_rank_{name}.csv", index=False)

    print("잠정 라운드(34일) 원자료 로드...", flush=True)
    h1_is_p = pd.read_csv("results/theme_rank_h1_is.csv")
    h1_oos_p = pd.read_csv("results/theme_rank_h1_oos.csv")
    h2_is_p = pd.read_csv("results/theme_rank_h2_is.csv")
    h2_oos_p = pd.read_csv("results/theme_rank_h2_oos.csv")
    h3_is_p = pd.read_csv("results/theme_rank_h3_is.csv")
    h3_oos_p = pd.read_csv("results/theme_rank_h3_oos.csv")

    rows = [
        _h1_summary(h1_is_p, h1_oos_p, "잠정(34일)"), _h1_summary(h1_is41, h1_oos41, "41일 전량"),
        _h2_summary(h2_is_p, h2_oos_p, "잠정(34일)"), _h2_summary(h2_is41, h2_oos41, "41일 전량"),
        _h3_summary(h3_is_p, h3_oos_p, "잠정(34일)"), _h3_summary(h3_is41, h3_oos41, "41일 전량"),
    ]
    table = pd.DataFrame(rows)
    table.to_csv("results/theme_rank_remeasure_comparison.csv", index=False)
    print("=== 잠정(34일) vs 41일 전량 비교 ===")
    print(table.to_string(index=False))

    return table


if __name__ == "__main__":
    main()
