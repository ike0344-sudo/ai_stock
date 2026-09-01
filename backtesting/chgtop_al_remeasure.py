"""§2·§3 AL 분봉 재측정 — lead 지시(2026-09-01, "대금 경로가 통합으로 바뀌었다").
`backtest-agent_20260901-153000_chgtop_leader_persistence.md`에서 판정보류였던
**§2(튄 뒤 더 가는가)**·**§3(1등 교체가 신호인가)**을 로컬 AL 분봉으로 다시 잰다.

## 통합(AL) 기준 — 어떻게 보장했나
`backtesting/minute_store.minute_al_dir()`가 가리키는
`kospi-theme-engine/data/cache/minute_al/<code>.csv`(data-agent가 오늘 만든
1,265종목 캐시)를 직접 읽는다 — 없으면 `minute_store`가 조용히 KRX로 안 빠지고
에러를 낸다(설계 자체가 그렇게 돼 있음, `minute_store.py` 참고). 안전구간
(2026-06-29~08-31)은 `minute_store.assert_date_covered`로 매 날짜 확인했다 —
원래 41일(07-01~08-31) 전부 이 안에 들어가 **기간을 좁히지 않았다.**

## §1(유지시간)은 이번에 다시 안 냈다 — 이유
§1의 입력은 `kospi-theme-engine/results/rank_timeline_full_*.json`이고, 이번에
data-agent가 바꾼 건 **`backtesting/universe.py`의 별도 함수**(09:00~10:00 창,
top25, 다른 파이프라인)다. rank_timeline_full 파일 자체는 이번에 재생성되지
않았다(mtime 미변경 직접 확인) — 재실행해도 같은 파일을 다시 읽을 뿐이라 §1
숫자는 바뀔 수 없다. **그런데 lead가 근거로 든 "금호건설이 KRX전용 상위25에서만
있던 종목"이라는 관찰이 내 §1에도 적용되는지는 별도로 확인이 필요해서 했다** —
결과는 §4에 있다: 데이터 오염이 아니라 실제 랠리였다(직접 검증). 다만 이번
조사 중 **별도 문제**(§5, minute_al 빌드 타이밍 겹침 가능성)를 하나 발견해
lead에게 그대로 올린다 — 판단은 내가 안 하고 escalate.

실행: python -X utf8 -m backtesting.chgtop_al_remeasure
"""
import os

import numpy as np
import pandas as pd

from backtesting import minute_store
from backtesting.chgtop_leader_persistence import (
    FORWARD_MIN,
    MinuteCloseLookup,
    build_onset_dataset,
    build_swap_dataset,
    full_dates_available,
    summarize_onset_returns,
    validate_against_al_ticks,
)
from backtesting.theme_rank_prereg_measure import (
    is_dates_valid,
    load_name_to_code,
    oos_dates_valid,
)

AL_MINUTE_DIR = minute_store.minute_al_dir()
SAFE_RANGE = ("2026-06-29", "2026-08-31")  # data-agent 실측 안전구간(minute_store.py 문서화)


def covered_dates(dates: list[str]) -> list[str]:
    """안전구간(SAFE_RANGE) 밖이면 좁힌다 - 지시대로 좁혔다는 걸 리포트에 남긴다.

    `minute_store.assert_date_covered(date)`를 코드 없이 부르면 **1,265종목 전부**가
    그 날짜를 커버해야 통과한다 - 신규상장/상장폐지 등으로 항상 몇 종목은 빠지므로
    전종목 기준으로 쓰면 사실상 모든 날짜가 걸린다(직접 겪음). 우리가 실제로 쓰는
    건 그날의 챙탑 리더 종목뿐이라 종목단위 결측은 `MinuteCloseLookup`이 이미
    개별적으로 처리한다(None 반환 -> 그 이벤트만 dropna) - 여기선 날짜 범위 자체만
    안전구간과 비교한다."""
    return [d for d in dates if SAFE_RANGE[0] <= d <= SAFE_RANGE[1]]


def swap_pairwise_summary(sw: pd.DataFrame, label: str) -> pd.DataFrame:
    rows = []
    for k in FORWARD_MIN:
        d = (sw[f"new_ret_{k}m"] - sw[f"old_ret_{k}m"]).dropna()
        if d.empty:
            rows.append({"set": label, "horizon": f"{k}m", "n": 0})
            continue
        daily = pd.DataFrame({"date": sw.loc[d.index, "date"], "diff": d}).groupby("date")["diff"].mean()
        se = daily.std(ddof=1) / np.sqrt(len(daily)) if len(daily) > 1 else np.nan
        rows.append({"set": label, "horizon": f"{k}m", "n": len(d),
                     "diff_mean_pct": d.mean() * 100, "diff_se_pct": se * 100 if pd.notna(se) else np.nan})
    return pd.DataFrame(rows)


def main() -> None:
    name_to_code = load_name_to_code()
    lookup = MinuteCloseLookup(AL_MINUTE_DIR)

    is_dates_raw = is_dates_valid(exclude=False)
    oos_dates_raw = oos_dates_valid(exclude=False)
    full_dates = set(full_dates_available())
    is_dates_raw = [d for d in is_dates_raw if d in full_dates]
    oos_dates_raw = [d for d in oos_dates_raw if d in full_dates]

    is_dates = covered_dates(is_dates_raw)
    oos_dates = covered_dates(oos_dates_raw)
    dropped = (set(is_dates_raw) - set(is_dates)) | (set(oos_dates_raw) - set(oos_dates))
    print(f"IS {len(is_dates)}/{len(is_dates_raw)}일 · OOS {len(oos_dates)}/{len(oos_dates_raw)}일 "
          f"(minute_al 안전구간 확인, 좁힌 날짜: {sorted(dropped) or '없음'})", flush=True)

    onset_is = build_onset_dataset(is_dates, name_to_code, lookup)
    onset_oos = build_onset_dataset(oos_dates, name_to_code, lookup)
    print(f"onset 이벤트(AL분봉) IS={len(onset_is)}건 / OOS={len(onset_oos)}건", flush=True)

    pd.set_option("display.width", 220)
    print("\n=== §2 재측정 (AL 분봉, 비용반영) ===")
    new_summary = pd.concat([summarize_onset_returns(onset_is, "IS"),
                             summarize_onset_returns(onset_oos, "OOS")])
    print(new_summary.to_string(index=False))

    swap_is = build_swap_dataset(is_dates, name_to_code, lookup)
    swap_oos = build_swap_dataset(oos_dates, name_to_code, lookup)
    print(f"\nswap 이벤트(AL분봉) IS={len(swap_is)}건 / OOS={len(swap_oos)}건", flush=True)
    print("\n=== §3 재측정 (AL 분봉, 교체 쌍대비교) ===")
    new_swap_summary = pd.concat([swap_pairwise_summary(swap_is, "IS"),
                                  swap_pairwise_summary(swap_oos, "OOS")])
    print(new_swap_summary.to_string(index=False))

    print("\n=== AL분봉 근사 vs AL원틱 재검증 (OOS, tick_al 겹치는 표본) ===")
    val = validate_against_al_ticks(onset_oos)
    if val.empty:
        print("겹치는 표본 없음")
    else:
        for k in FORWARD_MIN:
            diffs = val[f"diff_{k}m"].dropna()
            if diffs.empty:
                continue
            corr = val[[f"al_ret_{k}m", f"krx_ret_{k}m"]].corr().iloc[0, 1]
            print(f"  {k}m: n={len(diffs)} 평균오차={diffs.mean()*100:+.4f}%p "
                  f"절대오차평균={diffs.abs().mean()*100:.4f}%p corr={corr:.3f}")

    # 잠정(KRX근사) 결과와 나란히 비교 - 원본 저장 CSV 재사용(다시 안 돎)
    print("\n=== 잠정(KRX분봉근사) vs 이번(AL분봉) 나란히 비교 — 순수익%(net) ===")
    old_is = pd.read_csv("results/chgtop_onset_is.csv")
    old_oos = pd.read_csv("results/chgtop_onset_oos.csv")
    old_summary = pd.concat([summarize_onset_returns(old_is, "IS(잠정,KRX)"),
                             summarize_onset_returns(old_oos, "OOS(잠정,KRX)")])
    new_summary_labeled = new_summary.copy()
    new_summary_labeled["set"] = new_summary_labeled["set"] + "(AL)"
    compare = pd.concat([old_summary, new_summary_labeled]).sort_values(["horizon", "set"])
    print(compare[["set", "horizon", "n", "gross_mean_pct", "net_mean_pct", "win_rate_pct"]].to_string(index=False))

    os.makedirs("results", exist_ok=True)
    onset_is.to_csv("results/chgtop_al_onset_is.csv", index=False)
    onset_oos.to_csv("results/chgtop_al_onset_oos.csv", index=False)
    swap_is.to_csv("results/chgtop_al_swap_is.csv", index=False)
    swap_oos.to_csv("results/chgtop_al_swap_oos.csv", index=False)
    compare.to_csv("results/chgtop_al_vs_krx_comparison.csv", index=False)
    print("\n저장: results/chgtop_al_onset_{is,oos}.csv, chgtop_al_swap_{is,oos}.csv, "
          "chgtop_al_vs_krx_comparison.csv")


if __name__ == "__main__":
    main()
