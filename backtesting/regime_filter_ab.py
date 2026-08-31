"""전략1 조건7(코스피 레짐 필터, 15분봉 60이평선 위)을 켠 경우/끈 경우 워크포워드 A/B.

final_strategy.detect_final_entries(disabled_conditions={"regime"})로 그 조건 하나만
빼고 나머지 조건(거래대금35위/당일상승률/3분거래대금/3분수익률/신고가/무하락이력/
top35)은 완전히 동일하게 스캔한다. 25위+상승률1등 조건(strategy-agent 구현 중)은
아직 안 넣는다 - 그 구현이 끝나면 별도로 돈다.

ML게이트 on/off는 gate_ab_check.gate_ab_per_fold를 그대로 재사용한다(신규
시뮬레이션 로직 없음) - 결과적으로 (레짐on/off) x (ML on/off) 2x2를 낸다.

레짐을 끄면 늘어나는 거래(레짐off에만 있고 레짐on엔 없는 거래)를 따로 떼어 그
거래들이 몰리는 시기(월별)와 raw 성과(승률/손익비/평균%, 슬롯 제약 없음 -
"선별력" 자체를 보려면 포트폴리오 자본배분 편향을 빼야 한다)를 비교한다.

홀드아웃(마지막 20%)은 열지 않는다 - gate_ab_per_fold에 넘기기 전에 trades_df를
그 경계 이전으로 자른다.

실행: python -m backtesting.regime_filter_ab
"""
import argparse
from datetime import timedelta

import pandas as pd

from . import gate_ab_check as gab
from .ml.walk_forward import split as wf_split
from .validate_strategy1 import scan_all_trades

HOLDOUT_FRACTION = 0.20
# breakout_reversal.simulate_trade_path가 scan_all_trades 경로에서 이미 반영하는
# 왕복비용(위탁수수료 0.015%x2 + 매도세 0.23% + 슬리피지 0.1%x2) - pct 컬럼은 이미
# 이 비용을 뺀 순수익률이다. 사용자가 물은 "0.2~0.4% 반영하면?"에 답하려면 이미
# 반영된 이 값을 먼저 밝히고, 그 위에서 민감도(다른 비용 가정)를 추가로 본다.
EMBEDDED_ROUNDTRIP_COST_PCT = 0.00015 * 2 + 0.0023 + 0.001 * 2


def _holdout_cutoff(trades_df: pd.DataFrame) -> "pd.Timestamp.date":
    start = trades_df["entry_time"].min().date()
    end = trades_df["entry_time"].max().date()
    total_days = (end - start).days
    return start + timedelta(days=round(total_days * (1 - HOLDOUT_FRACTION))), start, end


def _raw_stats(df: pd.DataFrame) -> dict:
    """포트폴리오 슬롯 제약 없이 신호 자체의 품질만 본다(daily_walk_forward.py의
    _raw_trade_stats와 같은 이유 - 슬롯이 거래를 떨어뜨리면 순수 비교가 아니게 된다)."""
    n = len(df)
    if n == 0:
        return {"n_trades": 0, "win_rate_pct": 0.0, "profit_factor": 0.0, "avg_pct": 0.0}
    wins = df[df["pct"] > 0]
    losses = df[df["pct"] <= 0]
    gross_profit = wins["pct"].sum()
    gross_loss = -losses["pct"].sum()
    return {
        "n_trades": n,
        "win_rate_pct": len(wins) / n * 100,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
        "avg_pct": df["pct"].mean() * 100,
    }


def diff_analysis(on_df: pd.DataFrame, off_df: pd.DataFrame) -> None:
    """레짐 필터가 실제로 뭘 걸러내는지 - off에만 있는(=레짐 필터가 껐으면 막았을)
    거래를 뽑아 시기별 분포와 raw 성과를 on과 나란히 본다."""
    key_cols = ["code", "entry_time"]
    merged = off_df.merge(on_df[key_cols], on=key_cols, how="left", indicator=True)
    added = merged[merged["_merge"] == "left_only"].drop(columns="_merge")

    print(f"\n=== 레짐 필터가 막던 거래(off에만 있음): {len(added)}건 ===")
    if added.empty:
        print("레짐 필터를 꺼도 늘어난 거래가 없다 - 조건7이 사실상 다른 조건에 가려 무효화된 상태일 수 있다.")
        return

    monthly = added["entry_time"].dt.to_period("M").value_counts().sort_index()
    print("월별 분포:")
    print(monthly.to_string())

    on_stats, added_stats = _raw_stats(on_df), _raw_stats(added)
    print(f"\n{'구분':12s} {'거래수':>6s} {'승률%':>7s} {'손익비':>7s} {'평균%':>7s}")
    for label, s in [("레짐on(기존)", on_stats), ("레짐이 막던 것", added_stats)]:
        pf = "inf" if s["profit_factor"] == float("inf") else f"{s['profit_factor']:.2f}"
        print(f"{label:12s} {s['n_trades']:>6d} {s['win_rate_pct']:>7.1f} {pf:>7s} {s['avg_pct']:>7.2f}")

    verdict = "필터링(품질 개선)" if added_stats["avg_pct"] < on_stats["avg_pct"] and added_stats["win_rate_pct"] < on_stats["win_rate_pct"] else "거래수만 축소(품질 개선 불명확)"
    print(f"판정: 레짐 필터는 {verdict} - 막힌 거래의 승률·평균%가 기존보다 낮아야 '진짜 필터링'이다.")


def overlap_analysis(
    on_df: pd.DataFrame, off_df: pd.DataFrame,
    train_days: int, test_days: int, step_days: int, start, end,
    proba_threshold: float = gab.RECOMMENDED_PROBA_THRESHOLD,
) -> None:
    """ML게이트가 레짐 필터와 같은 거래를 걸러내는지 직접 잰다. 레짐OFF의 각 폴드
    OOS후보에 ML을 그대로 돌려(gate_ab_check가 이미 하는 학습+예측을 재사용) 폴드별
    proba를 얻고, threshold 미만인 것을 "ML이 탈락시킨 거래"로 모은다. 그중 "레짐이
    막던 거래"(off에만 있던 546건류)가 얼마나 겹치는지가 핵심 수치다."""
    key_cols = ["code", "entry_time"]
    regime_rejected = off_df[~off_df.set_index(key_cols).index.isin(on_df.set_index(key_cols).index)]
    regime_rejected_keys = set(zip(regime_rejected["code"], regime_rejected["entry_time"]))

    splits = wf_split(start, end, train_days, test_days, step_days)
    fold_data = gab._train_and_predict_per_fold(off_df, splits)

    ml_rejected_keys, ml_kept_keys = set(), set()
    for fd in fold_data:
        if fd["status"] != "ok":
            continue
        oos_df, proba = fd["oos_df"], fd["proba"]
        rejected = oos_df.loc[proba[proba < proba_threshold].index]
        kept = oos_df.loc[proba[proba >= proba_threshold].index]
        ml_rejected_keys |= set(zip(rejected["code"], rejected["entry_time"]))
        ml_kept_keys |= set(zip(kept["code"], kept["entry_time"]))

    intersection = regime_rejected_keys & ml_rejected_keys
    print("\n=== ML 탈락집합 vs 레짐 탈락집합 교집합 ===")
    print(f"레짐이 막은 거래: {len(regime_rejected_keys)}건")
    print(f"ML이 탈락시킨 거래(레짐OFF 폴드 OOS 기준): {len(ml_rejected_keys)}건")
    print(f"교집합: {len(intersection)}건")
    if regime_rejected_keys:
        print(f"레짐이 막은 것 중 ML도 탈락시켰을 비율: {len(intersection)/len(regime_rejected_keys)*100:.1f}%")
    if ml_rejected_keys:
        print(f"ML이 탈락시킨 것 중 레짐도 막았을 비율: {len(intersection)/len(ml_rejected_keys)*100:.1f}%")
    print("겹침이 크면 ML은 레짐의 열등한 대체물, 겹침이 작으면 ML은 다른 걸 걸러내는데 성과가 안 나온다는 뜻.")


def cost_sensitivity(baseline_df: pd.DataFrame, cost_scenarios_pct: list[float]) -> None:
    """baseline_df["pct"]는 이미 왕복비용 EMBEDDED_ROUNDTRIP_COST_PCT를 뺀 순수익률이다
    (breakout_reversal.simulate_trade_path의 DEFAULT_COMMISSION_RATE/SLIPPAGE_RATE/
    TAX_RATE - 위탁수수료 0.015%x2 + 매도세 0.23% + 슬리피지 0.1%x2). 다른 비용
    가정에서는 어떻게 되는지 보려고, 그 기본 비용을 되돌린 근사 총수익률에서 각
    가정 비용을 다시 뺀다(선형 근사 - 슬리피지가 가격에 곱으로 붙는 걸 pct에
    더하기/빼기로 근사한 것이라 정밀하진 않지만 방향과 크기는 충분히 보여준다)."""
    gross_approx = baseline_df["pct"] + EMBEDDED_ROUNDTRIP_COST_PCT
    print(f"\n=== 비용 민감도 (레짐ON+ML off 기준, {len(baseline_df)}건) ===")
    print(f"현재 이미 반영된 왕복비용: {EMBEDDED_ROUNDTRIP_COST_PCT*100:.2f}%p (수수료 0.03% + 매도세 0.23% + 슬리피지 0.20%)")
    print(f"{'가정 왕복비용':>10s} {'승률%':>7s} {'손익비':>7s} {'평균%':>7s}")
    for cost in cost_scenarios_pct:
        adj = gross_approx - cost
        wins, losses = adj[adj > 0], adj[adj <= 0]
        pf = (wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else float("inf")
        wr = len(wins) / len(adj) * 100 if len(adj) else 0.0
        print(f"{cost*100:>9.2f}% {wr:>7.1f} {pf:>7.2f} {adj.mean()*100:>7.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--train-days", type=int, default=150)
    parser.add_argument("--test-days", type=int, default=45)
    parser.add_argument("--step-days", type=int, default=45)
    parser.add_argument("--on-trades-csv", default=None, help="레짐on 스캔 결과 캐시(읽기/쓰기 겸용)")
    parser.add_argument("--off-trades-csv", default=None, help="레짐off 스캔 결과 캐시(읽기/쓰기 겸용)")
    args = parser.parse_args()

    if args.on_trades_csv and __import__("os").path.exists(args.on_trades_csv):
        on_full = pd.read_csv(args.on_trades_csv, parse_dates=["entry_time", "exit_time"])
    else:
        print("스캔 중 (레짐 on)...")
        on_full = scan_all_trades(args.data_dir, disabled_conditions=frozenset())
        if args.on_trades_csv:
            on_full.to_csv(args.on_trades_csv, index=False)

    if args.off_trades_csv and __import__("os").path.exists(args.off_trades_csv):
        off_full = pd.read_csv(args.off_trades_csv, parse_dates=["entry_time", "exit_time"])
    else:
        print("스캔 중 (레짐 off)...")
        off_full = scan_all_trades(args.data_dir, disabled_conditions=frozenset({"regime"}))
        if args.off_trades_csv:
            off_full.to_csv(args.off_trades_csv, index=False)

    holdout_start, start, end = _holdout_cutoff(on_full)
    fold_end = holdout_start - timedelta(days=1)  # 폴드 생성은 여기까지만 — 그 너머가 홀드아웃.
    print(f"\n전체 커버기간(레짐on 기준) {start} ~ {end}, 홀드아웃 {holdout_start}~{end}(마지막 {HOLDOUT_FRACTION:.0%})은 열지 않음")
    print(f"폴드 시작일 고정: {start} (레짐on/off 두 표 모두 이 날짜에서 폴드를 센다 - 데이터가 아니라 달력에서 옴)")

    on_df = on_full[on_full["entry_time"].dt.date < holdout_start].reset_index(drop=True)
    off_df = off_full[off_full["entry_time"].dt.date < holdout_start].reset_index(drop=True)
    print(f"레짐on 거래 {len(on_full)}건 -> 홀드아웃 제외 {len(on_df)}건")
    print(f"레짐off 거래 {len(off_full)}건 -> 홀드아웃 제외 {len(off_df)}건")

    pd.set_option("display.width", 220)
    ab_tables = {}
    for key, label, df in [("on", "레짐 ON(현행 전략1)", on_df), ("off", "레짐 OFF(조건7 제거)", off_df)]:
        # start/end를 고정해서 넘긴다 - 안 넘기면 gate_ab_per_fold가 이 df 자신의
        # min(entry_time)으로 폴드 시작점을 잡아, on/off 표의 폴드 경계가 며칠씩
        # 어긋나는 버그가 났었다(실측으로 발견, 회귀 테스트로 고정됨).
        ab = gab.gate_ab_per_fold(df, args.train_days, args.test_days, args.step_days, start=start, end=fold_end)
        ab_tables[key] = ab
        print(f"\n########## {label} - 폴드별 ML게이트 off/on ##########")
        print(ab.to_string(index=False))

    diff_analysis(on_df, off_df)

    # 레짐ON+ML off = 지금 후보 기준선. 폴드별 손익비 방향 일관성(합산 PF가 한
    # 폴드에 견인된 건지 고르게 나온 건지)을 별도로 뽑는다.
    on_off_rows = ab_tables["on"][(ab_tables["on"]["side"] == "off") & (ab_tables["on"]["fold"] != "합산")]
    n_pf_ge1 = (on_off_rows["profit_factor"] >= 1.0).sum()
    print(f"\n=== 레짐ON+ML off 기준선: 폴드별 손익비 방향 일관성 ===")
    print(on_off_rows[["fold", "test_start", "test_end", "n_trades", "profit_factor"]].to_string(index=False))
    print(f"손익비>=1인 폴드: {n_pf_ge1}/{len(on_off_rows)}")

    splits = wf_split(start, fold_end, args.train_days, args.test_days, args.step_days)
    if splits:
        baseline = on_df[on_df["entry_time"].dt.date.between(splits[0].test_start, splits[-1].test_end)]
        cost_sensitivity(baseline, [0.0020, 0.0030, 0.0040, EMBEDDED_ROUNDTRIP_COST_PCT])

    overlap_analysis(on_df, off_df, args.train_days, args.test_days, args.step_days, start, fold_end)


if __name__ == "__main__":
    main()
