"""전략 1번 — 세션에서 확정한 최종 진입/청산 규칙.

진입: 거래대금 상위 35위 이내 AND 당일상승률[7%, 15%) AND 3분 거래대금≥40억
      AND 3분 수익률≥1.5% AND 당일 장중 신고가 AND 장중고점대비 -5% 하락 이력 없음
      AND 코스피지수 15분봉 60기간 이평선 위(그날 09시 기준)
청산: 손절 -2.5%, +2.5/4/5.5/7%에서 25%씩 분할매도, 무장 후 진입가 이하로
      떨어지면 잔량 본전청산
운용: ML 성공확률 0.3 이상만 채택, 동시보유 최대 5종목(종목당 원금의 20%)
      — 포트폴리오 시뮬레이션(portfolio_sim.py)으로 검증된 조합.
      (위 상승률 상한/ML임계값은 실제 값이 바뀔 때마다 이 요약을 놓치기 쉬우니,
      정확한 값은 항상 아래 DAY_RETURN_CEILING/RECOMMENDED_PROBA_THRESHOLD와
      그 옆 코멘트를 기준으로 볼 것 — 여기는 요약일 뿐 출처가 아니다.)

이 규칙으로 로컬 데이터 전체를 스캔해 ML 진입필터 모델을 학습·저장한다.

거래소 기준: 학습/백테스트는 NXT(넥스트레이드) 출범 전 KRX 단독 이력으로 이뤄졌지만,
실전 매매에서는 "거래대금 상위 35위" 선정과 3분 거래대금/수익률·당일상승률·장중 신고가·
고점대비 하락 등 분봉 기반 조건 판정 모두 통합(KRX+NXT, stex_tp="3") 기준으로 맞췄다
(trading_loop.py가 live_monitor.py의 fetch_today_candles/scan_watchlist_once 호출 시
exchange="3"을 명시). 통합 분봉은 NXT 체결까지 섞여 같은 시각의 거래량/종가가 KRX
단독과 달라지므로 학습 당시 기준과 완전히 동일하지는 않지만, 실제 체결 가능 물량을
더 폭넓게 반영한다는 판단으로 전략1은 통합을 택했다(전략3은 여전히 KRX 단독 기준).
"""
import os

import numpy as np
import pandas as pd

from .breakout_reversal import detect_entries, simulate_trade_path
from .entry_filters import (
    _day_return,
    combine_and,
    compute_index_regime_by_day,
    intraday_new_high_filter,
    market_regime_filter,
    no_prior_drawdown_filter,
    top_return_rank1_filter,
)
from .ml_entry_filter import FEATURE_COLUMNS, extract_entry_features, save_model, train_entry_filter_model
from .universe import daily_top_n_from_local, intraday_top_n_return_rank1_by_minute
# 손절폭/익절 단계는 risk_limits.yaml 이 유일한 출처다 — 여기에 리터럴로 두면
# 실거래(trading_loop)와 배치(백테스트)가 다른 값으로 갈라져도 아무도 모른다.
# 재수출: 기존 `from .final_strategy import STOP_LOSS_PCT` 호출부를 그대로 둔다.
from .risk_manager import STOP_LOSS_PCT, TIERS

WINDOW_MINUTES = 3
# 2026-09-09 40억 -> 120억. 통합(KRX+NXT) 테이프로 재수집된 현재 데이터에서 이 하한
# 언저리 신호는 전부 손실이다 — 3분 거래대금이 하한의 1.0~3.0배인 구간을 0.2배 폭으로
# 8칸 쪼갠 결과 8칸 전부 원신호 기대값이 음수(-1.26 ~ -0.03%)이고, 3.0배를 넘어서야
# 부호가 바뀐다. 하한을 40/50/60/70/80/100/120억으로 올리면 원신호 기대값이
# -0.188 -> -0.159 -> -0.129 -> -0.088 -> -0.057 -> -0.029 -> +0.027%로 단조 상승한다.
# 120억보다 더 올리면 OOS 손익비는 더 좋아지지만(240억 1.20, 320억 1.25) 거래수가
# 20% 이상 깎여 채택 기준을 못 넘는다. 값의 근거는 "최적점"이 아니라 부호가 바뀌는
# 경계다 — 다시 볼 사람은 120억이 최적화된 값이라고 읽으면 안 된다.
MIN_TRADE_VALUE = 12_000_000_000
MIN_RETURN_PCT = 0.015
# 2026-09-30 3분 수익률 상한 추가. 통합 테이프 원신호 1261건에서 3분 수익률 4% 초과
# 160건의 기대값이 -0.6%(승률 36%)로, 4% 이하(+0.09%)와 부호가 갈린다 — 급하게 치솟은
# 분봉 끝을 따라 사는 추격매수다. 상한 3.5/4/4.5/5/6%에서 남는 표본 PF가 1.08/1.06/
# 1.03/1.02/1.01로 단조, 분기 5개 중 4개에서 초과 구간이 더 나쁘다. 4%는 최적점이
# 아니라 부호가 갈리는 경계다(3.5%는 거래수가 20% 가까이 깎인다).
MAX_RETURN_PCT = 0.04
DAY_RETURN_FLOOR = 0.07
# 2026-08-30 사용자 결정으로 0.22 -> 0.15. 정직하게 적어둔다: 원래 0.22가 어디서
# 왔는지 아무도 모른다 — 오늘 자유파라미터 점검에서 전략1 자유파라미터 8개 중
# 가설이 값까지 요구한 게 0개로 확인됐고, 이 값도 그 8개 중 하나였다. 0.15도
# 마찬가지로 가설에서 유도된 값이 아니다 — 그냥 새로 골라본 값이다. 나중에 이
# 상수를 다시 볼 사람은 "0.15가 맞다고 검증됐다"로 읽으면 안 된다, A/B로 재는
# 대상일 뿐이다. A/B는 detect_final_entries(..., day_return_ceiling=값)으로.
DAY_RETURN_CEILING = 0.15
DRAWDOWN_THRESHOLD = 0.05
TOP_N = 35
# 사용자 요청(2026-08-29) A/B 조건: 거래대금 상위 TOP25_TRADING_VALUE_RANK_N위 이내 +
# 그 중 상승률 1등(universe.intraday_top_n_return_rank1_by_minute). 값을 백테스트
# 결과 보고 바꾸지 않는다(사용자 지정값 그대로, 25도 "1등"도 고정) — 토글/관계는
# detect_final_entries 문서 참고.
#
# 2026-08-30 기각(backtest-agent). top35를 같이 안 끈 첫 실행(204건)은 오판(3+/1-)이었고,
# disabled_conditions={"top35"}로 제대로 끄고 재실행하니 566건 4폴드 전부 마이너스
# (avg_r -0.177, PF 0.774, p=0.084) — 이때는 채택 안 함.
#
# 2026-08-30 같은 날 사용자 결정으로 다시 켠다(기본값 ON, DAY_RETURN_CEILING 0.15
# 변경과 같이 감). 위 기각 결과를 뒤집을 새 근거가 나온 게 아니라 사용자가 그
# 결과를 알면서도 켜기로 한 것이다 — 이 상수/조건을 다시 볼 사람은 "재검증돼서
# 켜졌다"로 오해하면 안 된다. top35와의 대체관계는 이제 호출자가 기억할 규칙이
# 아니라 detect_final_entries가 강제한다(아래 함수 본문 참고, top25_return_rank1이
# 켜져 있으면 top35는 무조건 자동으로 꺼진다 — 오늘 이 순서를 사람이 기억하지
# 못해 top35를 같이 안 끈 채로 204건을 돌려 PF 1.31이라는 가짜 숫자가 나온
# 사고가 있었다).
TOP25_TRADING_VALUE_RANK_N = 25
N_DAY_HIGH = 5
UNREACHABLE_PCT = 0.999

KOSPI_INDEX_CODE = "001"
REGIME_MA_PERIOD = 60
REGIME_RESAMPLE_MINUTES = 15

# 운용 권장값. 출처: strategy1_verification(2026-07-25, test 2026-03-24~07-24
# 단일 구간, +104.6%) — 이 구간은 학습=검증(자체 과적합 라벨) 실행이었고, 진짜
# 워크포워드 OOS(2026-08-29 재측정, 동일 구간 아님)에서는 손익비가 0.99로
# 무너졌다(+139.7% → -0.4%). 즉 이 threshold/positions 값은 워크포워드로
# 검증된 적이 없다 — validate_strategy1.py가 기본값으로 그냥 물려받는 곳(아래
# run_walk_forward 기본 인자) 참고.
#
# 2026-08-29 사용자 결정으로 PROBA_THRESHOLD 0.5 -> 0.3 변경.
# 근거: 4조합 A/B에서 0.3이 모든 조합에서 0.5보다 나았다(조건ON PF 1.31 vs 1.14,
# 조건OFF PF 1.01 vs 1.00). 리크 없는 IS 기반 임계값 선택에서도 폴드3·4 둘 다
# 0.3을 골랐다.
# 약점(재검토 대상): 유효 폴드가 2개뿐이고 표본이 66건/44건으로 작다. 0.3과 0.5의
# 성과 차이가 이렇게 크다는 것 자체가 예측력이 임계값에 민감하다는 경고다(폴드3에서
# 0.5면 22건이 0건이 된다). 통계 유의성 검정은 아직 진행 중 — 결과가 나오면 재검토.
# 전파 주의: 이 값은 state/{strategy}/config.json에 실행 시점 스냅샷으로 저장되고
# (cli.py._write_strategy_config), 대시보드 "시작" 버튼은 그 스냅샷을 --proba-threshold로
# 그대로 재주입한다(dashboard_server.py.build_strategy_command) — 기존 스냅샷이 남아있는
# 한 이 코드 상수를 바꿔도 실거래에는 그 스냅샷 값이 계속 적용된다. 실거래 config.json도
# 같이 갱신하기 전까지는 코드와 실거래가 다른 값으로 도는 상태다(사용자 확인 대기 중).
RECOMMENDED_PROBA_THRESHOLD = 0.3
RECOMMENDED_MAX_CONCURRENT_POSITIONS = 5


def describe_strategy_1() -> dict:
    """대시보드 등 조회용으로 전략 1번의 진입/청산/운용 규칙을 사람이 읽을 수 있는
    구조로 반환한다 — 모듈 상단 docstring과 같은 내용이지만 실제 상수값으로 문구를
    만들어, 상수가 바뀌어도 설명이 코드와 어긋나지 않게 한다."""
    tier_pct = 100 / len(TIERS)
    return {
        "entry": [
            f"거래대금 상위 {TOP_N}위 이내",
            f"당일상승률 {DAY_RETURN_FLOOR:.0%} 이상 {DAY_RETURN_CEILING:.0%} 미만",
            f"{WINDOW_MINUTES}분 거래대금 {MIN_TRADE_VALUE / 1e8:.0f}억원 이상",
            f"{WINDOW_MINUTES}분 수익률 {MIN_RETURN_PCT:.1%} 이상 {MAX_RETURN_PCT:.1%} 이하",
            "당일 장중 신고가",
            f"장중고점 대비 -{DRAWDOWN_THRESHOLD:.1%} 하락 이력 없음",
            f"코스피지수 {REGIME_RESAMPLE_MINUTES}분봉 {REGIME_MA_PERIOD}기간 이평선 위(그날 09시 기준)",
        ],
        "exit": [
            f"손절 -{STOP_LOSS_PCT:.1%}",
            "+" + "/".join(f"{t:.1%}" for t in TIERS) + f"에서 각 {tier_pct:.0f}%씩 분할매도",
            "분할매도 시작(무장) 후 진입가 이하로 떨어지면 잔량 본전청산",
        ],
        "operation": [
            f"ML 진입필터 성공확률 {RECOMMENDED_PROBA_THRESHOLD} 이상만 채택",
            f"동시보유 최대 {RECOMMENDED_MAX_CONCURRENT_POSITIONS}종목(종목당 원금의 {100 / RECOMMENDED_MAX_CONCURRENT_POSITIONS:.0f}%)",
        ],
        "exchange_basis": [
            "워치리스트 선정(거래대금 상위): 통합(KRX+NXT)",
            f"진입 신호용 분봉({WINDOW_MINUTES}분 거래대금/수익률 등): 통합(KRX+NXT)",
            "청산 시 호가 조회 폴백: 실전 계좌 기준 통합(SOR) — 실제 매도 주문이 체결될 거래소와 일치",
        ],
    }


def load_kospi_regime_by_day(data_dir: str = "data") -> dict:
    """코스피 지수 로컬 분봉으로 날짜별 레짐(15분봉 60이평선 위/아래) 판단을 계산."""
    index_path = os.path.join(data_dir, "index", "minute", f"{KOSPI_INDEX_CODE}.csv")
    index_df = pd.read_csv(index_path, index_col=0, parse_dates=True)
    return compute_index_regime_by_day(index_df, ma_period=REGIME_MA_PERIOD, resample_minutes=REGIME_RESAMPLE_MINUTES)


def detect_final_entries(
    minute_df: pd.DataFrame, daily_df: pd.DataFrame, code: str, daily_top35: dict, regime_by_day: dict,
    disabled_conditions: frozenset[str] = frozenset(),
    top25_return_rank1_by_minute: dict | None = None,
    precomputed_base_entries: dict | None = None,
    precomputed_new_high: dict | None = None,
    precomputed_no_drawdown: dict | None = None,
    day_return_ceiling: float = DAY_RETURN_CEILING,
) -> pd.Series:
    """day_return_ceiling: 기본값은 모듈 상수 DAY_RETURN_CEILING(현재 0.15) — 인자로
    받게 한 이유는 이 값 하나를 코드 수정 없이 A/B로 재기 위함이다(예: 0.22와 0.15를
    같은 호출부에서 값만 바꿔 나란히 실행). 과설계 방지를 위해 day_return_floor 등
    다른 상수까지 전부 인자화하진 않았다 — 지금 A/B가 필요한 건 이 값 하나뿐이다.

    precomputed_base_entries/precomputed_new_high/precomputed_no_drawdown: 각각
    breakout_reversal.detect_entries_batch_duckdb / entry_filters.
    intraday_new_high_filter_batch_duckdb / entry_filters.no_prior_drawdown_filter_batch_duckdb
    로 로컬 유니버스 전체를 미리 한 번에 계산한 {code: pd.Series[bool]}. None(기본값,
    하위호환)이면 기존처럼 이 함수 안에서 종목별 pandas 버전을 그대로 호출한다 — 셋
    다 pandas 버전과 1:1 동치 검증됨(각 tests/backtesting/test_entry_filters.py,
    test_breakout_reversal.py). scan_all_trades가 속도를 위해 넘길 때만 그 경로를 탄다.

    disabled_conditions: A/B 비교용으로 특정 조건만 빼고 싶을 때 그 이름을 넣는다
    (예: {"regime"}, {"top35"}). 조건이 늘어날 때마다 불리언 파라미터를 추가하는 대신
    이름 하나만 집합에 더하면 되게 — 시그니처가 안 불어난다. 과설계 방지를 위해 이
    이상의 구조(조건 레지스트리 등)는 만들지 않는다: 그냥 문자열 집합 하나, 아래 각
    조건이 "내 이름이 꺼져 있나"만 스스로 확인한다.

    top25_return_rank1_by_minute: 사용자 요청(2026-08-29) 조건, 2026-08-30 기본 ON —
    universe.intraday_top_n_return_rank1_by_minute()로 미리 계산한 {타임스탬프: 그
    시점 거래대금상위 TOP25_TRADING_VALUE_RANK_N위 중 상승률 1등 코드} 매핑. 데이터를
    안 넘기면(None) 이 조건 자체가 없다 — top35가 그대로 적용된다. 끄고 싶으면(A/B용)
    데이터는 그대로 넘기되 disabled_conditions에 "top25_return_rank1"을 추가할 것.
    disabled_conditions가 아니라 별도 데이터 인자로 둔 이유: 이 조건 자체가 데이터
    없이는 계산이 안 되기 때문(불리언 하나로는 못 끔).

    top35와는 대체 관계이고, 이제 사람이 기억할 규칙이 아니라 코드가 강제한다 —
    top25_return_rank1이 켜져 있으면(데이터 있음 + "top25_return_rank1"으로 끄지
    않음) top35는 disabled_conditions에 뭐가 있든 무조건 자동으로 꺼진다(아래 본문
    참고). D-1 근사(top35)와 장중 재구성(top25_return_rank1)이라는 서로 다른 편향의
    유니버스 정의가 같이 AND로 걸리는 걸 원천 차단한다 — 2026-08-30 이 순서를 호출자가
    깜빡해 top35를 안 끈 채 204건을 돌려 PF 1.31이라는 가짜 숫자가 나온 적이 있다.
    """
    # day_return_filter/day_return_ceiling_filter를 각각 부르면 _day_return(내부에서
    # daily_df["close"] 전일종가를 분봉 인덱스 전체에 매핑)을 종목당 두 번 계산하게 된다
    # — 같은 값이라 한 번만 구해 재사용 (판단 로직은 원래 두 함수와 동일, fillna(False)도 그대로).
    day_return = _day_return(minute_df, daily_df)
    day_floor_ok = (day_return >= DAY_RETURN_FLOOR).fillna(False)
    day_ceiling_ok = (day_return < day_return_ceiling).fillna(False)
    if precomputed_new_high is not None:
        new_high_ok = precomputed_new_high.get(code, pd.Series(dtype=bool)).reindex(minute_df.index, fill_value=False)
    else:
        new_high_ok = intraday_new_high_filter(minute_df)
    if precomputed_no_drawdown is not None:
        no_drawdown_ok = precomputed_no_drawdown.get(code, pd.Series(dtype=bool)).reindex(minute_df.index, fill_value=False)
    else:
        no_drawdown_ok = no_prior_drawdown_filter(minute_df, DRAWDOWN_THRESHOLD)
    regime_ok = market_regime_filter(minute_df, regime_by_day)
    # detect_entries의 수익률과 같은 정의(일자별 리셋, pct_change(WINDOW_MINUTES-1)) — 거래일 경계를 넘지 않는다.
    window_ret = minute_df["close"].groupby(minute_df.index.normalize()).pct_change(WINDOW_MINUTES - 1)
    return_ceiling_ok = (window_ret <= MAX_RETURN_PCT).fillna(False)
    # market_regime_filter와 같은 이유로 분봉 전체가 아니라 고유 날짜만 파이썬 루프를 돈다.
    minute_dates = minute_df.index.normalize()
    day_codes, unique_days = pd.factorize(minute_dates)
    day_in_top35 = np.fromiter(
        (code in daily_top35.get(d, set()) for d in unique_days), dtype=bool, count=len(unique_days)
    )
    top35_ok = pd.Series(day_in_top35[day_codes], index=minute_df.index)
    if precomputed_base_entries is not None:
        base_entries = precomputed_base_entries.get(code, pd.Series(dtype=bool)).reindex(minute_df.index, fill_value=False)
    else:
        base_entries = detect_entries(minute_df, WINDOW_MINUTES, MIN_TRADE_VALUE, MIN_RETURN_PCT)
    # 조건 이름을 disabled_conditions에 넣으면 그 조건만 빼고 나머지는 전부 그대로 —
    # A/B 비교(regime_filter_ab.py, leave-one-out 조건 기여도 분해 등)가 나머지 조건
    # 동일성을 보장받는다. 전부 이 방식으로 통일(2026-08-30, leave-one-out 요청 계기) —
    # 기존엔 regime/top35만 토글 가능했고 나머지 5개는 항상 강제 포함이었다.
    cond_by_name = {
        "base": base_entries, "return_ceiling": return_ceiling_ok, "day_floor": day_floor_ok, "day_ceiling": day_ceiling_ok,
        "new_high": new_high_ok, "no_drawdown": no_drawdown_ok, "regime": regime_ok, "top35": top35_ok,
    }
    # top25_return_rank1이 실제로 켜져 있으면(데이터가 있고 "top25_return_rank1" 이름으로
    # 꺼두지 않았으면) top35는 호출자가 뭘 넘겼든 무조건 자동으로 끈다 — 대체관계를
    # 사람이 매번 disabled_conditions={"top35"}로 기억해서 넘기게 두면 언젠가 잊힌다
    # (2026-08-30 실제로 잊혀서 204건짜리 오염된 실행이 PF1.31이라는 가짜 숫자를 냈다).
    # 끄고 싶으면 disabled_conditions에 "top25_return_rank1"을 넣을 것 — 그러면 top35는
    # 자동으로 다시 살아난다(정상적인 A/B 끔 상태).
    top25_rank1_active = top25_return_rank1_by_minute is not None and "top25_return_rank1" not in disabled_conditions
    effective_disabled = set(disabled_conditions) | ({"top35"} if top25_rank1_active else set())
    conditions = [cond for name, cond in cond_by_name.items() if name not in effective_disabled]
    if top25_rank1_active:
        conditions.append(top_return_rank1_filter(minute_df, code, top25_return_rank1_by_minute))
    return combine_and(*conditions)


def _compute_exit_legs(path: list, tiers: tuple, stop_loss_pct: float) -> list:
    tier_fraction = 1.0 / len(tiers)
    tiers_remaining = list(tiers)
    remaining_fraction = 1.0
    armed = False
    legs: list = []

    for idx, net_pct, _peak in path:
        if not armed and net_pct <= -stop_loss_pct:
            legs.append((idx, "stop_loss", remaining_fraction, net_pct))
            remaining_fraction = 0.0
            break
        while tiers_remaining and remaining_fraction > 1e-9 and net_pct >= tiers_remaining[0]:
            tiers_remaining.pop(0)
            legs.append((idx, "take_profit_tier", tier_fraction, net_pct))
            remaining_fraction -= tier_fraction
            armed = True
        if armed and remaining_fraction > 1e-9 and net_pct <= 0:
            legs.append((idx, "breakeven", remaining_fraction, net_pct))
            remaining_fraction = 0.0
            break
        if remaining_fraction <= 1e-9:
            break

    if remaining_fraction > 1e-9 and path:
        last_idx, last_net_pct, _ = path[-1]
        legs.append((last_idx, "eod", remaining_fraction, last_net_pct))

    return legs


def evaluate_tiered_exit_from_path(path: list, tiers: tuple = TIERS, stop_loss_pct: float = STOP_LOSS_PCT) -> float:
    """simulate_trade_path(take_profit_pct=UNREACHABLE_PCT, stop_loss_pct=UNREACHABLE_PCT)로
    뽑은 (사실상 무제한 익절/손절) 전체 경로 하나로, 분할매도+본전청산 청산 규칙의
    최종 순손익률을 재시뮬레이션 없이 계산한다 (breakout_reversal.simulate_tiered_exit_trade와
    동일한 로직을, 캔들이 아닌 사전 기록된 경로 위에서 재사용하기 위한 버전)."""
    legs = _compute_exit_legs(path, tiers, stop_loss_pct)
    return sum(fraction * net_pct for _, _, fraction, net_pct in legs)


def evaluate_tiered_exit_from_path_with_exit_idx(
    path: list, tiers: tuple = TIERS, stop_loss_pct: float = STOP_LOSS_PCT
) -> tuple:
    """evaluate_tiered_exit_from_path와 같은 계산이지만, 잔량이 전량 청산되는 마지막
    leg의 idx(포지션이 완전히 종료되는 시점)도 함께 반환한다 — 포트폴리오 시뮬레이션이
    "이 포지션이 언제 슬롯을 비우는지" 알아야 하기 때문에 추가된 버전."""
    legs = _compute_exit_legs(path, tiers, stop_loss_pct)
    pct = sum(fraction * net_pct for _, _, fraction, net_pct in legs)
    exit_idx = legs[-1][0]
    return pct, exit_idx


def build_training_dataset(
    data_dir: str = "data", disabled_conditions: frozenset[str] = frozenset(),
    day_return_ceiling: float = DAY_RETURN_CEILING,
) -> tuple[pd.DataFrame, pd.Series]:
    """로컬 유니버스 전체를 스캔해 (피처, 라벨=최종순손익>0) 학습 데이터를 만든다.

    top25_return_rank1 조건은 2026-08-30 사용자 결정으로 기본 ON이라 여기서도
    항상 계산해서 넘긴다(끄려면 disabled_conditions={"top25_return_rank1"}) — 다만
    intraday_top_n_return_rank1_by_minute이 로컬 분봉 전체를 스캔하는 비용이 커서,
    이 함수를 부를 때마다(즉 모델을 재학습할 때마다) 그 비용이 매번 발생한다는 걸
    감안할 것(캐싱은 안 함 — 지금 요청 범위 밖)."""
    daily_top35 = daily_top_n_from_local(os.path.join(data_dir, "stocks", "daily"), top_n=TOP_N)
    regime_by_day = load_kospi_regime_by_day(data_dir)
    top25_return_rank1_by_minute = intraday_top_n_return_rank1_by_minute(data_dir, TOP25_TRADING_VALUE_RANK_N)
    minute_dir = os.path.join(data_dir, "stocks", "minute")
    daily_dir = os.path.join(data_dir, "stocks", "daily")

    all_codes = sorted(f.replace(".csv", "") for f in os.listdir(minute_dir))
    all_features, all_labels = [], []

    for code in all_codes:
        daily_path = os.path.join(daily_dir, f"{code}.csv")
        if not os.path.exists(daily_path):
            continue
        minute_df = pd.read_csv(os.path.join(minute_dir, f"{code}.csv"), index_col=0, parse_dates=True)
        daily_df = pd.read_csv(daily_path, index_col=0, parse_dates=True)

        entries = detect_final_entries(
            minute_df, daily_df, code, daily_top35, regime_by_day, disabled_conditions,
            top25_return_rank1_by_minute=top25_return_rank1_by_minute,
            day_return_ceiling=day_return_ceiling,
        )
        if entries.sum() == 0:
            continue

        for pos in (i for i, v in enumerate(entries.to_numpy()) if v):
            full_path = simulate_trade_path(
                minute_df, pos, take_profit_pct=UNREACHABLE_PCT, stop_loss_pct=UNREACHABLE_PCT
            ).path
            pct = evaluate_tiered_exit_from_path(full_path)
            all_features.append(
                extract_entry_features(minute_df, pos, WINDOW_MINUTES, MIN_TRADE_VALUE, daily_df, N_DAY_HIGH)
            )
            all_labels.append(1 if pct > 0 else 0)

    features_df = pd.DataFrame(all_features)[FEATURE_COLUMNS] if all_features else pd.DataFrame(columns=FEATURE_COLUMNS)
    return features_df, pd.Series(all_labels, dtype=int)


def generate_signals(
    df: pd.DataFrame, daily_df: pd.DataFrame, code: str, daily_top35: dict, regime_by_day: dict,
    disabled_conditions: frozenset[str] = frozenset(),
    top25_return_rank1_by_minute: dict | None = None,
    day_return_ceiling: float = DAY_RETURN_CEILING,
) -> pd.DataFrame:
    """Strategy 프로토콜 어댑터 — detect_final_entries의 bool Series를 signal 컬럼(1/0)으로
    매핑만 한다. daily_df/code/daily_top35/regime_by_day는 detect_final_entries가 이미
    요구하던 추가 컨텍스트로, OHLCV df 하나만으로는 채울 수 없어 그대로 필수 인자로 둔다.
    disabled_conditions/top25_return_rank1_by_minute/day_return_ceiling은 detect_final_entries에
    그대로 전달만 한다(전부 기본값이면 기존과 100% 동일)."""
    entries = detect_final_entries(
        df, daily_df, code, daily_top35, regime_by_day, disabled_conditions, top25_return_rank1_by_minute,
        day_return_ceiling=day_return_ceiling,
    )
    out = df.copy()
    out["signal"] = entries.astype(int)
    return out


generate_signals.name = "strategy_1"
generate_signals.params = {
    "window_minutes": WINDOW_MINUTES,
    "min_trade_value": MIN_TRADE_VALUE,
    "min_return_pct": MIN_RETURN_PCT,
    "day_return_floor": DAY_RETURN_FLOOR,
    "day_return_ceiling": DAY_RETURN_CEILING,
    "drawdown_threshold": DRAWDOWN_THRESHOLD,
    "top_n": TOP_N,
}


def train_and_save_final_model(
    data_dir: str = "data", model_path: str = "models/strategy_1/entry_filter_model.joblib",
    disabled_conditions: frozenset[str] = frozenset(), **model_kwargs
):
    features_df, labels_s = build_training_dataset(data_dir, disabled_conditions)
    kwargs = {"n_estimators": 300, "max_depth": 6, "min_samples_leaf": 20, "n_jobs": -1, **model_kwargs}
    trained = train_entry_filter_model(features_df, labels_s, model_type="random_forest", **kwargs)

    model_dir = os.path.dirname(model_path)
    if model_dir:
        os.makedirs(model_dir, exist_ok=True)
    save_model(trained, model_path)
    return trained, features_df, labels_s
