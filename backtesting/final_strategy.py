"""전략 1번 — 세션에서 확정한 최종 진입/청산 규칙.

진입: 거래대금 상위 35위 이내 AND 당일상승률[7%, 22%) AND 3분 거래대금≥40억
      AND 3분 수익률≥1.5% AND 당일 장중 신고가 AND 장중고점대비 -5% 하락 이력 없음
      AND 코스피지수 15분봉 60기간 이평선 위(그날 09시 기준)
청산: 손절 -2.5%, +2.5/4/5.5/7%에서 25%씩 분할매도, 무장 후 진입가 이하로
      떨어지면 잔량 본전청산
운용: ML 성공확률 0.5 이상만 채택, 동시보유 최대 5종목(종목당 원금의 20%)
      — 포트폴리오 시뮬레이션(portfolio_sim.py)으로 검증된 조합.

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

import pandas as pd

from .breakout_reversal import detect_entries, simulate_trade_path
from .entry_filters import (
    combine_and,
    compute_index_regime_by_day,
    day_return_ceiling_filter,
    day_return_filter,
    intraday_new_high_filter,
    market_regime_filter,
    no_prior_drawdown_filter,
)
from .ml_entry_filter import FEATURE_COLUMNS, extract_entry_features, save_model, train_entry_filter_model
from .universe import daily_top_n_from_local

WINDOW_MINUTES = 3
MIN_TRADE_VALUE = 4_000_000_000
MIN_RETURN_PCT = 0.015
DAY_RETURN_FLOOR = 0.07
DAY_RETURN_CEILING = 0.22
DRAWDOWN_THRESHOLD = 0.05
TOP_N = 35
N_DAY_HIGH = 5
UNREACHABLE_PCT = 0.999
STOP_LOSS_PCT = 0.025
TIERS = (0.025, 0.04, 0.055, 0.07)

KOSPI_INDEX_CODE = "001"
REGIME_MA_PERIOD = 60
REGIME_RESAMPLE_MINUTES = 15

# 운용 권장값 (portfolio_sim.py 시뮬레이션으로 검증됨 — 4개월 TEST 기준 +104.6%)
RECOMMENDED_PROBA_THRESHOLD = 0.5
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
            f"{WINDOW_MINUTES}분 수익률 {MIN_RETURN_PCT:.1%} 이상",
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
    minute_df: pd.DataFrame, daily_df: pd.DataFrame, code: str, daily_top35: dict, regime_by_day: dict
) -> pd.Series:
    day_floor_ok = day_return_filter(minute_df, daily_df, DAY_RETURN_FLOOR)
    day_ceiling_ok = day_return_ceiling_filter(minute_df, daily_df, DAY_RETURN_CEILING)
    new_high_ok = intraday_new_high_filter(minute_df)
    no_drawdown_ok = no_prior_drawdown_filter(minute_df, DRAWDOWN_THRESHOLD)
    regime_ok = market_regime_filter(minute_df, regime_by_day)
    minute_dates = minute_df.index.normalize()
    top35_ok = pd.Series([code in daily_top35.get(d, set()) for d in minute_dates], index=minute_df.index)
    base_entries = detect_entries(minute_df, WINDOW_MINUTES, MIN_TRADE_VALUE, MIN_RETURN_PCT)
    return combine_and(base_entries, day_floor_ok, day_ceiling_ok, new_high_ok, no_drawdown_ok, regime_ok, top35_ok)


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


def build_training_dataset(data_dir: str = "data") -> tuple[pd.DataFrame, pd.Series]:
    """로컬 유니버스 전체를 스캔해 (피처, 라벨=최종순손익>0) 학습 데이터를 만든다."""
    daily_top35 = daily_top_n_from_local(os.path.join(data_dir, "stocks", "daily"), top_n=TOP_N)
    regime_by_day = load_kospi_regime_by_day(data_dir)
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

        entries = detect_final_entries(minute_df, daily_df, code, daily_top35, regime_by_day)
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


def train_and_save_final_model(
    data_dir: str = "data", model_path: str = "models/strategy_1/entry_filter_model.joblib", **model_kwargs
):
    features_df, labels_s = build_training_dataset(data_dir)
    kwargs = {"n_estimators": 300, "max_depth": 6, "min_samples_leaf": 20, "n_jobs": -1, **model_kwargs}
    trained = train_entry_filter_model(features_df, labels_s, model_type="random_forest", **kwargs)

    model_dir = os.path.dirname(model_path)
    if model_dir:
        os.makedirs(model_dir, exist_ok=True)
    save_model(trained, model_path)
    return trained, features_df, labels_s
