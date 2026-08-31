"""[스캘핑 전략으로는 폐기, 2026-08-30] — 이유·근거는 아래 새 섹션 참고.
코드는 안 지운다: classify_tick_direction/ACCUMULATION_WINDOW_SECONDS/TIERS는
point_labeling.py가 피처 재료로 계속 import해서 쓰는 활성 의존성이다(폐기
대상은 compute_ofi_signal을 "매매 신호"로 쓰는 이 파일의 원래 용도뿐,
classify_tick_direction 자체는 안 죽는다).

## 폐기 사유 (state/agent_reports/backtest-agent_20260830-203500_ofi-hypothesis-measurement.md
§6.5, strategy-agent_20260830-204000/204800 최종판단)
실측(6,700만 틱, 193,091건 진입): median 손익 -0.36%가 편도 고정비용(수수료+
세금+슬리피지=0.36%)과 정확히 일치 — 60초 동안 가격이 거의 안 움직여 손익이
비용으로만 결정된다. take_profit_tier(3%/5%) 히트는 193,091건 중 4건(0.00%)뿐 —
직접 계산해보면 이 4건이 전부 최댓값(+5%)을 쳤다고 가정해도 전체 평균 기여는
+0.0001%p 수준이라 median 드래그를 상쇄 못한다. 청산시간을 2배(2W=120초)로
늘려도(탐색적 변형, 사전등록값 W는 그대로 두고 병기만 함) 승률은 5.48%→9.25%로
오르지만 **median은 -0.36% 그대로**, take_profit_tier도 19건(0.01%)으로 여전히
무의미한 수준 — 구조 자체가 안 바뀐다.

**완전 기각은 아니다(정직하게 구분)**: 신호 후 돌파확인율을 무작위시점
기준선과 비교하니 41.2% vs 30.16%로 +11.1%p(상대 +37%) 유의한 lift가 있다 —
"평탄+매수주도 누적이 돌파에 선행한다"는 원 가설의 핵심 직관 자체는 완전히
틀리진 않았다. 실패한 건 이 약한 신호를 **현재의 타이트한 분할익절(3%/5%)+
60~120초라는 짧은 시간 안에서 실거래비용을 뚫고 수익화하는 설계**다 — 신호가
아니라 신호를 돈으로 바꾸는 방식이 문제라는 뜻. 다른 시간축/페이오프 구조로
재도전할 여지는 남겨두되, 지금 당장 이어갈 계획은 없다.

---
[원문, 참고/회귀용으로 그대로 둠]
가설C 확정 — 누적 주문흐름 불균형(OFI) 다이버전스, 틱 전용 스캘핑 신호.

state/agent_reports/strategy-agent_20260830-200000.md의 가설C를 사용자 결정(2026-08-30)
으로 구현한다. 가설: 정보 있는 매수자가 가격을 티 안 나게 올리려고 공격적 매수를
반복하되 매도벽에 흡수되는 수준으로 조절한다 — 가격은 평탄한데 매수주도 체결이
꾸준히 쌓이다가, 매도벽이 소진되면 뒤늦게 돌파한다. 먼저 쌓임을 본 우리가, 돌파를
보고 뒤늦게 들어오는 기술적 매수자에게 판다.

## 방향 판정 규칙 (확정)
진짜 Lee-Ready는 호가 중간값이 있어야 하는데 우리 틱엔 호가가 없다 — **순수
틱룰**로 확정: 직전 체결가 대비 상승틱=매수주도(+1), 하락틱=매도주도(-1),
보합틱은 직전 판정을 그대로 이어받는다(classify_tick_direction). 첫 틱은 기준이
없어 중립(0).

**보합틱 비율 실측은 backtest-agent에게 별도로 요청한다(편지 참고) — 나는 코드
실행 도구가 없어 8월 실틱 데이터를 직접 집계하지 못한다.** 이 구현은 그 실측
결과를 기다리지 않고 먼저 낸다 — 방향판정 로직 자체는 보합틱 비율이 얼마든
동일하게 동작하기 때문(로직이 아니라 "신뢰도"의 문제라 실측이 나오는 대로
가설 자체의 존속 여부를 재판단하면 됨, 코드를 다시 짤 필요는 없음).

## 자유 파라미터 — 3개, 전부 가설에서 유도되지 않음(정직하게 명시)
원래 W(누적창)/B(기준선창)/T(임계값) 3개로 제안했던 것을 **W와 B를 하나로
합쳤다** — 절대 거래량 대신 "같은 창 안에서 매수주도-매도주도 체결량 차이가
전체 체결량 대비 몇 %인가"로 정규화하면 별도 기준선 창이 필요 없다(창 자체가
스스로의 기준선이 된다). 그래서 실제로는 W(창 길이) + T(정규화 불균형 임계값) +
F(가격 평탄 임계값) = **3개**로 유지된다(하나 줄이려던 시도는 성공했지만 평탄
조건이 새 파라미터라 도로 3개).
- W(ACCUMULATION_WINDOW_SECONDS): 가설에서 유도 안 됨 — "짧은 시간"이라는 정성적
  표현 말고는 근거가 없다. 정직하게 미정으로 남긴다(아래 값은 시작점일 뿐).
- T(IMBALANCE_THRESHOLD): 가설에서 유도 안 됨 — "꾸준히 쌓인다"가 구체적으로
  몇 %인지는 가설이 말해주지 않는다.
- F(FLATNESS_THRESHOLD): 가설에서 유도 안 됨 — "상대적으로 평탄"이 구체적으로
  얼마나 평탄한지는 가설이 말해주지 않는다.
**사전 등록**: 실측 결과를 보고 이 세 값을 슬쩍 바꾸지 않는다. 바꾸려면 그럴
근거(가설 자체의 재구성)가 따로 있어야 한다 — 그냥 "이 값에서 잘 나왔다"는
근거가 될 수 없다.

## 평가 주기 — 자유 파라미터 아님
30초 그리드로 평가한다. 임의로 정한 게 아니라 tick_holdout_verification.py가
이미 같은 근거(trading_loop.py의 실제 poll_interval_seconds=30.0)로 확정해둔
값을 그대로 재사용한다 — 새 근거를 만들지 않았다.

## 청산 규칙
사용자 지정값(목표 3~5%, 손절 -2%) 그대로 쓰되, 분할/단일/시간손절은 위임받아
판단함:
- **분할 익절 2단계 (3%, 5%, 각 50%)** — final_strategy.TIERS와 같은 관례(단일
  숫자로 못박기보다 사용자가 준 범위의 양끝을 다 반영). 새 숫자를 만든 게
  아니라 사용자가 준 두 값을 그대로 tier로 씀.
- **손절 -2%** — 사용자 지정.
- **시간손절 = W(누적창)와 동일** — 새 파라미터를 안 만들려고 일부러 W를
  재사용했다. 근거: "축적에 W만큼 걸렸는데 신호 후 같은 정도의 시간 안에도
  안 뚫리면 매수 압력이 흩어졌다고 본다"는 것 — 배수(2W, 3W 등)를 얹지 않고
  1배로 고정한 것도 새 자유파라미터를 안 늘리기 위한 선택.
- 청산 시뮬레이션(체결/비용 반영)은 이 전략 코드의 일이 아니다 — backtest-agent가
  `final_strategy._compute_exit_legs(path, tiers=(0.03, 0.05), stop_loss_pct=0.02)`를
  그대로 재사용하되(tick_holdout_verification.py와 같은 패턴), path를
  "진입시각 + W초"에서 자른 것을 넘기면 그 지점에서 "eod" 처리로 자동으로
  시간손절이 구현된다 — _compute_exit_legs 자체를 고칠 필요가 없다.

## 부수효과 — 반드시 측정해야 하는 것 (측정은 backtest-agent)
1. **신호 시점까지 가격이 평탄해야 한다.** 신호 발생 직전 W초 구간의 가격 레인지가
   FLATNESS_THRESHOLD 이내였는지는 신호 정의 자체에 이미 들어있지만, 별도로
   "신호 발생 *이전* 더 긴 구간(예: 3W)에서도 뚜렷한 선행 상승이 없었는지"를
   확인해야 한다 — **이게 안 나오면(신호 시점에 이미 크게 올라있는 경우가
   흔하면) 이건 축적 탐지가 아니라 상승 후행지표에 불과하다는 뜻이고, 그러면
   가설 기각이다.**
2. **신호 이후 실제 돌파(예: 신호 후 W~2W초 내 신고가 경신)가 뒤따르는 비율**이
   유의하게 높아야 한다.

## 현실 제약 재확인
호가/잔량 필요 없음(체결가·체결량·시각만 사용) — 확정.
"""
import pandas as pd

ACCUMULATION_WINDOW_SECONDS = 60  # 자유 파라미터, 가설 유도 아님(정직히 명시) — 시작점일 뿐
IMBALANCE_THRESHOLD = 0.3         # 자유 파라미터, 가설 유도 아님
FLATNESS_THRESHOLD = 0.01         # 자유 파라미터, 가설 유도 아님(가격레인지가 시작가의 1%p 이내)

EVAL_GRID_SECONDS = 30  # 자유 파라미터 아님 — tick_holdout_verification.py와 같은 근거(실제 폴링주기) 재사용

TIERS = (0.03, 0.05)      # 사용자 지정값 그대로
STOP_LOSS_PCT = 0.02      # 사용자 지정값 그대로
# 시간손절 = ACCUMULATION_WINDOW_SECONDS 그대로 재사용(위 문서 참고, 새 파라미터 아님)


def classify_tick_direction(prices: pd.Series) -> pd.Series:
    """틱룰: 상승틱=+1(매수주도), 하락틱=-1(매도주도), 보합틱은 직전 방향을 그대로
    이어받는다. 첫 틱은 비교 대상이 없어 0(중립)."""
    diff = prices.diff()
    direction = pd.Series(0, index=prices.index, dtype="float64")
    direction[diff > 0] = 1.0
    direction[diff < 0] = -1.0
    direction = direction.mask(diff == 0.0).ffill().fillna(0.0)
    return direction.astype(int)


def compute_ofi_signal(
    ticks: pd.DataFrame,
    window_seconds: float = ACCUMULATION_WINDOW_SECONDS,
    imbalance_threshold: float = IMBALANCE_THRESHOLD,
    flatness_threshold: float = FLATNESS_THRESHOLD,
) -> pd.Series:
    """ticks: DatetimeIndex(오름차순) + "cur_prc"(체결가) + "trde_qty"(체결량) 컬럼
    (data-agent 틱 스키마 그대로, tick_holdout_verification.py와 같은 컬럼명).

    반환: 매 틱마다 그 시점까지의 직전 window_seconds초를 기준으로 판정한
    진입신호(bool). 실제 백테스트/실거래에서는 이 신호를 EVAL_GRID_SECONDS(30초)
    그리드로만 샘플링해서 쓸 것 — 이 함수 자체는 매 틱마다 값을 내지만 그건
    참조용이고, 판단 빈도 자체를 30초로 제한하는 건 호출부(backtest-agent) 책임
    (tick_holdout_verification.py와 동일 관례).
    """
    direction = classify_tick_direction(ticks["cur_prc"])
    signed_value = direction * ticks["trde_qty"]

    window = f"{window_seconds}s"
    signed_sum = signed_value.rolling(window).sum()
    total_sum = ticks["trde_qty"].rolling(window).sum()
    imbalance = (signed_sum / total_sum).fillna(0.0)  # 창 안에 체결이 없으면(총량 0) 불균형 없음으로 취급

    rolling_high = ticks["cur_prc"].rolling(window).max()
    rolling_low = ticks["cur_prc"].rolling(window).min()
    flatness = (rolling_high - rolling_low) / ticks["cur_prc"]

    return (imbalance >= imbalance_threshold) & (flatness <= flatness_threshold)


def demo() -> None:
    """합성 데이터로 자체점검 — 실틱 데이터는 도구가 없어 못 돌린다, 로직만 증명."""
    idx = pd.date_range("2026-08-04 09:00:00", periods=12, freq="5s")
    # 앞 6틱(idx0~5): 100.0 -> 100.1(상승틱) -> 100.1(보합틱, 직전 방향 이월) ->
    # 100.2(상승틱) -> 100.2(보합틱, 이월) -> 100.3(상승틱). 가격은 거의 안 움직이는데
    # (평탄) 보합틱까지 전부 매수주도로 쌓인다(은닉 축적) -> idx5에서 신호가 떠야 한다.
    # 뒤 6틱(idx6~11): 실제 돌파(가격이 확 뜀) -> 평탄 조건이 깨져 신호가 꺼져야 한다
    # (신호는 "축적 중"에만 의미 있고 "돌파 이후"엔 이미 늦은 것임을 확인).
    prices = pd.Series(
        [100.0, 100.1, 100.1, 100.2, 100.2, 100.3, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0], index=idx
    )
    volumes = pd.Series([100] * 6 + [500] * 6, index=idx)
    ticks = pd.DataFrame({"cur_prc": prices, "trde_qty": volumes})

    direction = classify_tick_direction(prices)
    assert direction.iloc[0] == 0        # 첫틱은 비교대상 없어 중립
    assert direction.iloc[2] == 1        # 보합틱(100.1->100.1)이 직전 매수주도(+1)를 이어받아야 함
    assert direction.iloc[4] == 1        # 보합틱(100.2->100.2)도 마찬가지
    assert (direction.iloc[1:6] == 1).all()  # 이 구간 전부 매수주도(직접 상승 또는 이월)

    signal = compute_ofi_signal(ticks, window_seconds=25, imbalance_threshold=0.3, flatness_threshold=0.01)
    assert signal.iloc[5]        # 평탄+매수주도 누적 구간 끝에서 신호가 떠야 한다
    assert not signal.iloc[-1]   # 돌파(가격 급등) 이후는 flatness가 깨져 신호가 꺼져야 한다
    print("demo ok: 방향판정(보합틱 이월)/신호(평탄+매수주도 누적)/돌파 후 신호꺼짐 확인")


if __name__ == "__main__":
    demo()
