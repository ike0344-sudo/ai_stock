"""지점 라벨링 파이프라인 — 규칙 우선이 아니라 지점(라벨) 우선.

배경(state/agent_reports/strategy-agent_20260830-203000.md 상세): 오늘 전략1에서
detect_final_entries(규칙)가 먼저 후보를 걸러내고 ML이 그 안에서만 고르는 구조가
"후보집합이 마이너스면 천장이 0"이라는 걸 실측으로 확인했다(기반 -12.8%, ML 붙여도
-0.4%). 돌파고(개인 개발자 자동매매 노트, 사용자 제공) 방식을 반영해 이번엔 반대로
간다 — 규칙으로 후보를 먼저 안 거르고, 실제로 오른/떨어진 "지점"을 라벨로 삼아 그
시점의 체결 상태(피처)를 학습한다. **detect_final_entries/final_strategy는 여기서
전혀 import하지 않는다 — 완전히 독립된 모듈(섞으면 둘 다 망가진다는 지시 그대로).**
가설C(ofi_divergence_scalp.py)의 두 함수만 "피처 하나"로 재사용한다(가설C는 이제
규칙이 아니라 이 파이프라인의 피처 공급원).

## 미래참조 경계 (가장 중요)
시점 t까지(포함)는 피처, t 이후는 라벨 전용 — 이 한 줄이 전부다. 라벨은 원래
미래를 본다(지도학습이니 당연함), 피처가 미래를 보면 안 된다. 아래 함수별로
어느 쪽인지 이름 자체에 분리해뒀다(label_* vs feature 계산 함수는 물리적으로도
분리된 함수, 같은 DataFrame에 몰아넣지 않는다).

## 자유 파라미터
- WINDOW_SECONDS(피처 계산 창, =가설C의 ACCUMULATION_WINDOW_SECONDS 재사용):
  가설에서 유도 안 됨(가설C 자체가 이미 그렇게 명시함) — 재사용값 그대로 유지.
- LOOKAHEAD_SECONDS=60초, MOVE_THRESHOLD_PCT=0.03(3.0%): **2026-08-30 6,700만
  틱 실측으로 확정**(state/agent_reports/strategy-agent_20260830-211500.md) —
  N=60초 시점 기준 상승폭 분포의 p99(2.84%)에 가장 가까운 값으로 M을 잡았다
  ("드문 사건=상위1%" 기준). 원래 이 값들은 가설C의 W/TIERS를 그대로 재사용한
  placeholder였는데(그 자체는 유도 아님), 실측 p99가 우연히 거의 같은 값이라
  숫자 자체는 안 바뀌었다 — 다만 이제는 "재사용값"이 아니라 "실측 근거가
  있는 값"으로 격상됐다는 게 차이다. 떡락(음의 방향)에도 **같은 M을 그대로**
  적용한다 — 애초에 방향별로 다르게 줬다면 결과를 보고 규칙을 조정하는 것
  (리크)이 됐을 것이다.
  **정정(2026-08-30, backtest-agent 발견)**: 여기 있던 "하락폭 분포가 상승폭보다
  훨씬 얕다(momentum 편향)"는 문장은 **퍼센타일 방향을 잘못 읽은 결과였다** —
  fwd_down은 대부분 0(안 떨어짐)이라 "드문 큰 하락"은 p90+가 아니라 p1/p5 같은
  하위 퍼센타일에 있는데, 그걸 못 보고 p90+가 0인 것만 보고 "떡락이 희소하다"고
  잘못 결론 냈다. 실측(2단계) 결과 SHOOT 591,756건 vs CRASH 521,564건으로
  **규모가 비슷했다**(비율 0.88) — 원래 예상과 반대. 상세:
  state/agent_reports/backtest-agent_20260830-182122.md,
  state/agent_reports/strategy-agent_20260830-183000.md(정정 보고).
**실측 후 다시 값을 슬쩍 바꾸지 않는다(사전 등록) — 바꾸려면 새 근거가 있어야
한다.**
"""
import pandas as pd

from .ofi_divergence_scalp import ACCUMULATION_WINDOW_SECONDS, TIERS, classify_tick_direction

WINDOW_SECONDS = ACCUMULATION_WINDOW_SECONDS      # 재사용, 새 값 아님
LOOKAHEAD_SECONDS = ACCUMULATION_WINDOW_SECONDS   # 재사용, 새 값 아님
MOVE_THRESHOLD_PCT = TIERS[0]                     # 재사용(0.03), 새 값 아님

SHOOT, CRASH, NEUTRAL = 1, -1, 0

# 4단계(대조군+Mann-Whitney U, 2026-08-30) 결과로 확정된 피처 신뢰도 — 상세:
# state/agent_reports/backtest-agent_20260830-193200_stage4-final.md,
# state/agent_reports/strategy-agent_20260830-194600.md
# 신뢰가능(6개) — SHOOT/CRASH가 CONTROL과 크게 갈리고 효과크기가 동시각-틱
# 처리방식(pandas 순차 vs SQL RANGE) 차이 노이즈보다 훨씬 크다. 각 항목은
# (피처명, "high"|"low") — SHOOT/CRASH가 CONTROL 대비 치우친 방향.
RELIABLE_FEATURES = (
    ("trade_speed_per_sec", "high"),
    ("avg_trade_size", "high"),
    ("max_trade_size_ratio", "high"),
    ("tick_interval_volatility", "low"),
    ("price_flatness", "high"),
    ("intraday_cum_return", "high"),
)
# 결론보류(2개) — 효과크기(0.005~0.44)가 컨벤션 노이즈(0.086~0.47)와 같거나
# 작아 "있다/없다" 판단 불가(SHOOT_vs_CONTROL도 SHOOT쪽 노이즈 미측정이라 보수적
# 포함). 규칙에는 안 쓴다 — 재구현(순차 타이브레이크) 필요해지면 그때 재평가.
UNRELIABLE_FEATURES = ("buy_initiated_ratio", "order_flow_imbalance")


def _forward_rolling_extreme(prices: pd.Series, window_seconds: float, how: str) -> pd.Series:
    """시점 t 기준 [t, t+window_seconds) 구간의 최댓값(how="max")/최솟값(how="min")을
    반환한다 — pandas rolling은 후방(과거)만 지원해서, 시간축을 뒤집어(간격은
    보존한 채) 후방 rolling을 걸고 다시 뒤집는 표준 트릭을 쓴다. **이 함수만 유일하게
    미래를 본다** — 라벨 계산 전용이고 피처 계산에서는 절대 호출하지 않는다.
    """
    reversed_prices = prices.iloc[::-1].copy()
    reversed_prices.index = prices.index[0] + (prices.index[-1] - prices.index[::-1])
    rolled = reversed_prices.rolling(f"{window_seconds}s")
    result = (rolled.max() if how == "max" else rolled.min()).iloc[::-1]
    result.index = prices.index
    return result


def label_shoot_crash_points(
    ticks: pd.DataFrame,
    lookahead_seconds: float = LOOKAHEAD_SECONDS,
    move_threshold_pct: float = MOVE_THRESHOLD_PCT,
) -> pd.Series:
    """ticks: DatetimeIndex(오름차순) + "cur_prc" 컬럼. 반환: 각 시점 t의 라벨
    {SHOOT: t 이후 lookahead_seconds 안에 +move_threshold_pct 이상 오른 적 있음,
     CRASH: 같은 구간에 -move_threshold_pct 이상 내린 적 있음, NEUTRAL: 둘 다 아님}.
    **미래를 보는 함수 — 학습 라벨 전용, 피처로 절대 쓰지 않는다.**
    경로가 "깨끗한지"(먼저 반대로 안 흔들렸는지)는 안 본다 — 파라미터를 늘리지
    않기 위해 가장 단순한 정의(최댓값/최솟값 기준)로 시작한다.
    """
    prices = ticks["cur_prc"]
    fwd_high = _forward_rolling_extreme(prices, lookahead_seconds, "max")
    fwd_low = _forward_rolling_extreme(prices, lookahead_seconds, "min")

    shoot = (fwd_high - prices) / prices >= move_threshold_pct
    crash = (fwd_low - prices) / prices <= -move_threshold_pct

    labels = pd.Series(NEUTRAL, index=ticks.index, dtype=int)
    labels[shoot] = SHOOT
    # 둘 다 걸리면(변동성이 커서 위아래 다 큰 폭으로 움직인 경우) 라벨이 모호하니
    # crash를 나중에 덮어써 "둘 다 걸리면 표본에서 아예 빼는" 대신 crash 우선으로
    # 단순화하지 않는다 - 대신 명시적으로 NEUTRAL 처리(모호한 표본은 버림).
    ambiguous = shoot & crash
    labels[crash & ~ambiguous] = CRASH
    labels[ambiguous] = NEUTRAL
    return labels


def compute_microstructure_features(ticks: pd.DataFrame, window_seconds: float = WINDOW_SECONDS) -> pd.DataFrame:
    """ticks: DatetimeIndex(오름차순) + "cur_prc" + "trde_qty". 반환: 시점 t까지의
    정보만 쓰는 피처 DataFrame(**미래참조 없음** — 전부 (t-window_seconds, t] 후방
    rolling 또는 당일 시작~t 누적). 전통지표(rsi_14 등)는 의도적으로 안 넣었다
    (기간이 스무딩된 지연값이고 "왜 그 기간인가"에 답이 없어서 - 돌파고/오늘
    재검토 결론 동일).
    """
    prices = ticks["cur_prc"]
    volumes = ticks["trde_qty"]
    window = f"{window_seconds}s"

    direction = classify_tick_direction(prices)
    signed_volume = direction * volumes

    buy_ratio = (direction.clip(lower=0)).rolling(window).sum() / direction.abs().rolling(window).sum().replace(0, pd.NA)
    ofi = (signed_volume.rolling(window).sum() / volumes.rolling(window).sum().replace(0, pd.NA)).fillna(0.0)
    flatness = (prices.rolling(window).max() - prices.rolling(window).min()) / prices
    trade_speed = prices.rolling(window).count() / window_seconds
    avg_trade_size = volumes.rolling(window).mean()
    max_trade_size_ratio = volumes.rolling(window).max() / avg_trade_size.replace(0, pd.NA)

    tick_interval = ticks.index.to_series().diff().dt.total_seconds()
    interval_volatility = tick_interval.rolling(window).std()

    day = ticks.index.normalize()
    day_open_price = prices.groupby(day).transform("first")
    intraday_cum_return = (prices - day_open_price) / day_open_price  # day_start~t 누적, EOD 아님(안전)

    return pd.DataFrame(
        {
            "buy_initiated_ratio": buy_ratio.fillna(0.5),
            "order_flow_imbalance": ofi,
            "price_flatness": flatness,
            "trade_speed_per_sec": trade_speed,
            "avg_trade_size": avg_trade_size,
            "max_trade_size_ratio": max_trade_size_ratio.fillna(1.0),
            "tick_interval_volatility": interval_volatility.fillna(0.0),
            "intraday_cum_return": intraday_cum_return,
        },
        index=ticks.index,
    )


def demo() -> None:
    """자체점검 3개: ①_forward_rolling_extreme이 손계산과 일치하는지 ②라벨 판정이
    맞는지 ③가장 중요 - 미래를 바꿔도 과거 시점의 피처가 안 바뀌는지(리크 점검
    자체를 코드로 남기라는 지시 반영)."""
    idx = pd.Timestamp("2026-08-04 09:00:00") + pd.to_timedelta([0, 5, 10, 15, 20], unit="s")
    prices = pd.Series([10.0, 11.0, 9.0, 12.0, 8.0], index=idx)

    # ① 손계산: i=0(t=0) -> [0,10)구간 값 [10,11] -> max11,min10
    #          i=2(t=10) -> [10,20)구간 값 [9,12] -> max12,min9
    #          i=4(t=20) -> [20,30)구간 값 [8]     -> max8,min8
    fwd_max = _forward_rolling_extreme(prices, window_seconds=10, how="max")
    fwd_min = _forward_rolling_extreme(prices, window_seconds=10, how="min")
    assert fwd_max.iloc[0] == 11.0 and fwd_min.iloc[0] == 10.0
    assert fwd_max.iloc[2] == 12.0 and fwd_min.iloc[2] == 9.0
    assert fwd_max.iloc[4] == 8.0 and fwd_min.iloc[4] == 8.0

    # ② 라벨: i=2(가격9)는 10초 안에 12까지 감(+33%) -> SHOOT(임계 3% 훌쩍 넘음)
    ticks = pd.DataFrame({"cur_prc": prices, "trde_qty": [100] * 5})
    labels = label_shoot_crash_points(ticks, lookahead_seconds=10, move_threshold_pct=0.03)
    assert labels.iloc[2] == SHOOT

    # ③ 리크 점검 - t=idx[2](10초 시점)까지는 동일하고 그 이후만 다른 두 시나리오를
    # 만들어, compute_microstructure_features가 그 시점에서 완전히 같은 값을
    # 내는지 확인한다(미래를 실제로 바꿔서 기계적으로 증명 - 눈으로 수식 읽는 것보다
    # 강한 증거).
    idx_long = pd.Timestamp("2026-08-04 09:00:00") + pd.to_timedelta(range(0, 60, 5), unit="s")
    base_prices = pd.Series([10.0, 10.2, 10.1, 10.3, 10.2, 10.4] + [0.0] * 6, index=idx_long)
    base_prices.iloc[6:] = [15.0, 20.0, 25.0, 30.0, 35.0, 40.0]  # 시나리오A: t=30s 이후 폭등
    scenario_a = pd.DataFrame({"cur_prc": base_prices, "trde_qty": [100] * 12})
    scenario_b = scenario_a.copy()
    scenario_b.loc[idx_long[6]:, "cur_prc"] = [1.0, 0.5, 0.3, 0.2, 0.1, 0.05]  # 시나리오B: t=30s 이후 폭락

    features_a = compute_microstructure_features(scenario_a, window_seconds=20)
    features_b = compute_microstructure_features(scenario_b, window_seconds=20)
    cutoff = idx_long[5]  # t=25s, 두 시나리오가 갈라지기 직전(idx6=t30s부터 다름)
    pd.testing.assert_frame_equal(features_a.loc[:cutoff], features_b.loc[:cutoff])

    print("demo ok: 순방향윈도우 손계산 일치 / 라벨판정 정상 / 미래변경-과거피처불변(리크 없음) 확인")


if __name__ == "__main__":
    demo()
