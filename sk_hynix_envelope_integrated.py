"""SK하이닉스(000660) 15분봉 "통합"(KRX+NXT) 차트로 60이평 엔벨로프 괴리율을 분석한다.
sk_hynix_envelope_correlation.py(정규장 09:00~15:30 전용)의 후속 — 이번엔 넥스트레이드(NXT)
거래시간(08:00~20:00)까지 포함한 연속 차트로 같은 분석을 재현해 정규장 전용 결과와 비교한다.

"통합" 데이터 확보 방법: 로컬 CSV(data/stocks/minute/000660.csv)에는 NXT 체결이 사실상
없다(08:00대 0건, 15:31~20:00은 하루 1틱뿐 — 시간외단일가 종가 1건). 대신 키움 분봉조회
(ka10080)에 종목코드를 "000660_AL"(통합) 접미사로 넘기면 08:00~20:00 49개 시각대(정규장
09:00~15:30의 27개보다 훨씬 촘촘함)를 포함한 분봉을 직접 받을 수 있다 — screener.py가
이미 같은 접미사 관례(_AL=통합, ka10032용)를 쓰고 있어 조회 자체는 새로운 방식이 아니다.
페이지네이션(cont-yn/next-key)으로 받을 수 있는 최대치가 정확히 2025-07-01(로컬 CSV
시작일과 동일)까지라 전체 가용 이력을 다 받는다.

⚠️ 주의: 모의투자 계좌로 조회했다 — get_account_evaluation/get_stock_quote에서 이미
확인했듯 모의투자는 KRX/NXT/SOR을 구분하지 않고 같은 값을 돌려주는 것으로 보인다
(앞선 대화에서 실측). 즉 08:00~09:00, 15:31~20:00 구간의 가격이 실제 NXT 체결가가
아니라 키움 모의서버가 만들어낸 값일 가능성이 있다 — 이 스크립트가 보여주는 것은
"통합 캘린더(더 촘촘한 시간대)로 60이평 엔벨로프를 계산하면 구간 분류가 어떻게
달라지는가"이지, "실제 NXT 시간대 가격 움직임"을 검증한 결과가 아니다. 실전 계좌로
재확인 전까지는 참고용으로만 볼 것.

실행: python sk_hynix_envelope_integrated.py
출력: 콘솔 요약 + sk_hynix_envelope_integrated.png
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from dotenv import load_dotenv

from fetch_chart import MINUTE_COLUMN_MAP, find_records, to_dataframe
from kiwoom_client import KiwoomClient
from sk_hynix_envelope_correlation import (
    MA_WINDOW,
    SPLIT_TRANCHE_PCTS,
    TIER_PCTS,
    backtest_split_entry_strategy,
    backtest_tier_entries,
    compute_envelope,
    extract_zones,
    load_regular_session_15min,
    print_backtest_summary,
    tier_label,
)

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

STOCK_CODE = "000660"
COMBINED_CODE = f"{STOCK_CODE}_AL"  # 통합(KRX+NXT) — screener.py의 stex_tp=3 접미사 관례
MAX_PAGES = 20  # 가용 이력을 다 받을 때까지(cont-yn이 끊기면 자동으로 그 전에 멈춤)
DATA_DIR = "data"


def fetch_combined_15min(client: KiwoomClient) -> pd.DataFrame:
    """ka10080을 "_AL" 접미사로 호출해 08:00~20:00 통합 15분봉을 페이지네이션으로
    끝까지(가용 이력 한계까지) 받는다."""
    pages = client.get_minute_chart_pages(COMBINED_CODE, tic_scope="15", max_pages=MAX_PAGES)
    records = [r for page in pages for r in find_records(page)]
    df = to_dataframe(records, MINUTE_COLUMN_MAP, "%Y%m%d%H%M%S")
    return df[~df.index.duplicated(keep="last")].sort_index()


def summarize_zones(label: str, zones: pd.DataFrame) -> None:
    if not len(zones):
        print(f"{label}: 구간 없음")
        return
    print(f"\n--- {label} 단계별 구간 수 (총 {len(zones)}개, {zones['bars'].sum()}봉) ---")
    for tier in range(1, len(TIER_PCTS) + 1):
        count = (zones["max_tier"] == tier).sum()
        print(f"  {tier_label(tier, TIER_PCTS)}: {count}개 구간")
    print(f"{label} 최대 괴리율 상위 5개 구간:")
    print(
        zones.sort_values("max_deviation_pct", ascending=False).head(5)
        .assign(max_deviation_pct=lambda d: d["max_deviation_pct"].round(1))
        .to_string(index=False)
    )


def main():
    load_dotenv()
    appkey = os.environ["KIWOOM_APPKEY"]
    secretkey = os.environ["KIWOOM_SECRETKEY"]
    is_mock = os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true"
    print(f"키움 {'모의투자' if is_mock else '실전투자'} 계좌로 통합(KRX+NXT) 15분봉 조회 중...")
    if is_mock:
        print("⚠️ 모의투자 계좌 — NXT 시간대 가격이 실제 체결가가 아닐 수 있습니다(스크립트 상단 docstring 참고).")

    client = KiwoomClient(appkey, secretkey, is_mock=is_mock)
    combined_raw = fetch_combined_15min(client)

    trading_days = combined_raw.index.normalize().unique()
    print(
        f"\n통합 차트 로딩 완료: {trading_days.min().date()} ~ {trading_days.max().date()} "
        f"(거래일 {len(trading_days)}일, 15분봉 {len(combined_raw)}개, 하루 평균 {len(combined_raw) / len(trading_days):.0f}봉)"
    )

    combined = compute_envelope(combined_raw, MA_WINDOW, TIER_PCTS)
    combined_oversold = extract_zones(
        combined["oversold"], combined["oversold_tier"], combined["deviation_pct"].abs(), "과대낙폭(통합)"
    )
    combined_overheated = extract_zones(
        combined["overheated"], combined["overheated_tier"], combined["deviation_pct"].abs(), "과열(통합)"
    )

    print(f"\n=== 통합(08:00~20:00) 15분봉 60이평 괴리율 다단계 구간 (임계값: {', '.join(f'{t:.0f}%' for t in TIER_PCTS)}) ===")
    print(f"과대낙폭: {len(combined_oversold)}개 구간, 총 {combined_oversold['bars'].sum() if len(combined_oversold) else 0}봉")
    print(f"과열:     {len(combined_overheated)}개 구간, 총 {combined_overheated['bars'].sum() if len(combined_overheated) else 0}봉")
    summarize_zones("과대낙폭(통합)", combined_oversold)
    summarize_zones("과열(통합)", combined_overheated)

    # ---- 정규장 전용(기존 스크립트) 결과와 같은 기간으로 비교 ----
    hynix_path = os.path.join(DATA_DIR, "stocks", "minute", f"{STOCK_CODE}.csv")
    regular_raw = load_regular_session_15min(hynix_path)
    regular_raw = regular_raw.loc[str(trading_days.min().date()):str(trading_days.max().date())]
    regular = compute_envelope(regular_raw, MA_WINDOW, TIER_PCTS)
    regular_oversold = extract_zones(regular["oversold"], regular["oversold_tier"], regular["deviation_pct"].abs(), "과대낙폭(정규장)")
    regular_overheated = extract_zones(regular["overheated"], regular["overheated_tier"], regular["deviation_pct"].abs(), "과열(정규장)")

    print(f"\n=== 같은 기간({trading_days.min().date()}~{trading_days.max().date()}) 정규장 전용(09:00~15:30) 대비 ===")
    print(f"과대낙폭 구간 수: 통합 {len(combined_oversold)}개 vs 정규장 {len(regular_oversold)}개")
    print(f"과열 구간 수:     통합 {len(combined_overheated)}개 vs 정규장 {len(regular_overheated)}개")
    print(
        "60이평이 60봉 기준이라, 통합 차트(하루 약 "
        f"{len(combined_raw) / len(trading_days):.0f}봉)에서는 약 "
        f"{60 / (len(combined_raw) / len(trading_days)):.1f}거래일치, 정규장 전용(하루 27봉)에서는 약 "
        f"{60 / 27:.1f}거래일치 구간을 반영한다 — 절대적인 구간 개수 비교보다 이 창 길이 차이를 먼저 감안할 것."
    )

    # ---- 분할매수 진입 tier별 백테스트(통합 차트 기준) ----
    # PDF 전략3(과대낙폭 분할매수, sk_hynix_envelope_correlation.py에 이미 구현됨)를
    # 통합 데이터에 그대로 적용 — "어느 tier에서 사면 좋았는가"를 실제 과거 체결가
    # 기준 승률/평균수익률로 답한다(투자 조언이 아니라 과거 구간 재현 결과).
    print(f"\n=== 분할매수 tier별 백테스트(통합 차트, 진입=tier 최초 터치 시점, 청산=60이평 회복) ===")
    for tier in range(1, len(TIER_PCTS) + 1):
        trades = backtest_tier_entries(combined, combined_oversold, tier=tier, exit_ma_col="ma")
        print_backtest_summary(f"과대낙폭 {tier_label(tier, TIER_PCTS)} 매수 → 60이평 터치 청산", trades)

    print(
        f"\n=== PDF 전략3 재현(통합 차트): -9% 터치 시 3분할 매수({'/'.join(f'-{p:.0f}%' for p in SPLIT_TRANCHE_PCTS)}) "
        "→ 60선 터치 전량 익절(하드스톱/시간청산 포함) ==="
    )
    split_trades = backtest_split_entry_strategy(combined, combined_oversold)
    print_backtest_summary("PDF 전략3 재현(통합)", split_trades)
    if not split_trades.empty:
        print(f"청산 사유별 건수: {split_trades['exit_reason'].value_counts().to_dict()}")
        print(f"평균 체결 분할 수: {split_trades['filled_tranches'].mean():.2f} / 3")

    print(
        "\n⚠️ 위 수치는 이 289일 표본에서의 과거 재현 결과이지 투자 조언이 아닙니다 — "
        "표본 수(과대낙폭 구간 14개)가 적어 통계적 신뢰도가 낮고, 모의투자 데이터라 NXT 구간 "
        "가격 자체의 신뢰성도 앞서 밝힌 caveat이 그대로 적용됩니다."
    )

    # ---- 차트 저장 ----
    try:
        fig, ax = plt.subplots(figsize=(16, 6))
        ax.plot(combined.index, combined["close"], label="종가(통합)", linewidth=0.6)
        ax.plot(combined.index, combined["ma"], label=f"{MA_WINDOW}이평", linewidth=0.8, color="orange")
        for i, t in enumerate(TIER_PCTS):
            band_style = {"linewidth": 0.6, "linestyle": "--", "color": "gray", "alpha": 0.3 + 0.2 * i}
            ax.plot(combined.index, combined["ma"] * (1 + t / 100), label=f"+{t:.0f}%", **band_style)
            ax.plot(combined.index, combined["ma"] * (1 - t / 100), label=f"-{t:.0f}%", **band_style)

        tier_alpha = {1: 0.12, 2: 0.2, 3: 0.32}
        for _, row in combined_oversold.iterrows():
            ax.axvspan(row["start"], row["end"], color="blue", alpha=tier_alpha[row["max_tier"]])
        for _, row in combined_overheated.iterrows():
            ax.axvspan(row["start"], row["end"], color="red", alpha=tier_alpha[row["max_tier"]])
        ax.set_title(
            "SK하이닉스 15분봉(통합 KRX+NXT, 08:00~20:00) 60이평 괴리율 다단계(9/12/16%) — "
            "과대낙폭(파랑)/과열(빨강), 진할수록 깊은 단계"
        )
        ax.legend(loc="upper left", fontsize=8, ncol=2)
        fig.tight_layout()
        fig.savefig("sk_hynix_envelope_integrated.png", dpi=120)
        print("\n차트 저장: sk_hynix_envelope_integrated.png")
    except Exception as exc:
        print(f"\n⚠️ 차트 저장 실패(분석 결과와는 무관한 환경 문제): {exc}")


if __name__ == "__main__":
    main()
