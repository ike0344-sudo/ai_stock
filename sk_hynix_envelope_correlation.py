"""SK하이닉스(000660) 15분봉 60이평선 엔벨로프로 과대낙폭(하단 이탈)/과열(상단 이탈)
구간을 찾고, 코스피지수·나스닥지수·마이크론·엔비디아와의 상관관계를 살펴보는
탐색적 분석 스크립트. "전략2" 검토용 사전 조사 단계라 backtesting/strategies/에는
아직 코드화하지 않는다 — 결과를 보고 실제 전략화할지 판단한 뒤 별도로 진행한다.

거래시간 처리:
- SK하이닉스 vs 코스피: 둘 다 한국 정규장(09:00~15:30)이라 15분봉을 그대로
  동시 시각 기준으로 맞춰 상관계수를 계산한다.
- SK하이닉스 vs 나스닥/마이크론/엔비디아: 미국 정규장은 한국 정규장과 거래시간이
  전혀 겹치지 않는다(미국 동부 09:30~16:00 ET ≈ 한국시간 밤 22:30~새벽 05:00,
  서머타임에 따라 ±1시간). 그래서 "전날 밤 미국장 종가 대비 오늘 SK하이닉스
  장중 움직임"으로 정의해, 미국 거래일 D의 일간수익률을 그 다음 한국 거래일
  전체 15분봉에 동일하게 매핑해 비교한다(일별 집계 버전도 별도로 함께 낸다 —
  봉 단위 버전은 미국 변수가 하루 내내 상수라 상관계수 해석에 참고용으로만 쓴다).

실행: python sk_hynix_envelope_correlation.py
출력: 콘솔 요약 + sk_hynix_envelope_zones.png (엔벨로프+구간 시각화)
"""
import os
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

plt.rcParams["font.family"] = "Malgun Gothic"  # Windows 기본 한글 폰트 — 없으면 라벨이 네모로 깨짐
plt.rcParams["axes.unicode_minus"] = False  # 위 폰트로 바꾸면 마이너스 기호가 깨지는 문제 방지

STOCK_CODE = "000660"
KOSPI_INDEX_CODE = "001"
MA_WINDOW = 60
TIER_PCTS = [9.0, 12.0, 16.0]  # 60이평 대비 괴리율(%) 다단계 임계값 — 사용자가 직접 관찰한 구간
SLOPE_WINDOW = 20  # 60이평 기울기 계산 구간(15분봉 20개 ≈ 5시간)
SLOPE_LEAD_BARS = [5, 10, 20, 40]  # 기울기가 몇 봉 뒤의 괴리율을 예측하는지 시차별로 확인
DATA_DIR = "data"
SESSION_START = "09:00"
SESSION_END = "15:30"

# 로컬 1분봉 데이터가 SK하이닉스/코스피 공통으로 커버하는 구간(양쪽 다 이보다 최근까지 있지만
# 겹치는 범위로 안전하게 자름 — 코스피 로컬 데이터가 2026-07-16까지만 있음)
ANALYSIS_START = date(2025, 7, 2)
ANALYSIS_END = date(2026, 7, 15)


def load_regular_session_15min(csv_path: str) -> pd.DataFrame:
    """로컬 1분봉 CSV를 읽어 정규장(09:00~15:30)만 남기고 15분봉으로 재표본화한다.

    data_loader._resample_minute는 날짜별 "그날 첫 봉 시각"을 리샘플 origin으로 써서,
    개장 직후 몇 분간 체결이 없으면 봉 경계가 09:00에서 밀린다(예: 09:02, 15:32).
    여기서는 정규장만 남긴 뒤 origin을 09:00으로 고정해, 장마감 15:30이 정확히
    마지막 봉의 끝이 되도록 한다 — 시간외 종가/단일가매매(15:31~18:00) 데이터 혼입을
    막는 것이 이번 재분석의 목적이라 data_loader의 공용 리샘플 로직을 그대로 쓰지 않는다.
    """
    raw = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    regular = raw.between_time(SESSION_START, SESSION_END)

    parts = []
    for day, day_df in regular.groupby(regular.index.normalize()):
        origin = day + pd.Timedelta(hours=9)
        resampled = day_df.resample("15min", origin=origin).agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        )
        parts.append(resampled.dropna(subset=["open"]))
    return pd.concat(parts).sort_index()

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}  # UA 없이 호출하면 429 — 브라우저처럼 보이게 함
US_SYMBOLS = {"nasdaq": "%5EIXIC", "micron": "MU", "nvidia": "NVDA"}


def fetch_yahoo_daily(symbol: str, range_: str = "2y") -> pd.Series:
    """Yahoo Finance 차트 API로 일별 종가 시계열을 받는다. 타임스탬프는 거래소 로컬
    시간대(미국 동부)로 변환 후 날짜만 남긴다 — 일간 수익률 계산에는 시각이 필요 없다."""
    url = YAHOO_CHART_URL.format(symbol=symbol)
    res = requests.get(url, params={"interval": "1d", "range": range_}, headers=YAHOO_HEADERS, timeout=15)
    res.raise_for_status()
    result = res.json()["chart"]["result"][0]
    timestamps = (
        pd.to_datetime(result["timestamp"], unit="s", utc=True)
        .tz_convert("America/New_York")
        .normalize()
        .tz_localize(None)
    )
    closes = result["indicators"]["quote"][0]["close"]
    return pd.Series(closes, index=timestamps, name="close").dropna()


def tier_level(deviation_magnitude_pct: pd.Series, tiers_pct: list[float]) -> pd.Series:
    """괴리율 크기(양수, %)가 tiers_pct(오름차순, 예: [9,12,16])를 몇 단계까지 넘었는지
    반환한다. 0=어느 임계값도 안 넘음, len(tiers_pct)=가장 깊은 단계까지 도달."""
    level = pd.Series(0, index=deviation_magnitude_pct.index)
    for tier_idx, threshold in enumerate(tiers_pct, start=1):
        level[deviation_magnitude_pct >= threshold] = tier_idx
    return level


def compute_envelope(df: pd.DataFrame, ma_window: int, tiers_pct: list[float]) -> pd.DataFrame:
    """close에 ma_window 이평선 대비 괴리율(%)을 계산하고, tiers_pct 다단계 임계값으로
    과대낙폭(하단)/과열(상단) 단계를 분류한다."""
    out = df.copy()
    out["ma"] = df["close"].rolling(ma_window).mean()
    out["deviation_pct"] = (df["close"] - out["ma"]) / out["ma"] * 100
    out["oversold_tier"] = tier_level((-out["deviation_pct"]).clip(lower=0), tiers_pct)
    out["overheated_tier"] = tier_level(out["deviation_pct"].clip(lower=0), tiers_pct)
    out["oversold"] = out["oversold_tier"] > 0
    out["overheated"] = out["overheated_tier"] > 0
    return out


def extract_zones(flags: pd.Series, tier: pd.Series, deviation_abs: pd.Series, label: str) -> pd.DataFrame:
    """연속된 True 구간을 하나의 zone(시작/끝/봉수/도달한 최고 단계/최대 괴리율)으로 묶는다."""
    if not flags.any():
        return pd.DataFrame(columns=["type", "start", "end", "bars", "max_tier", "max_deviation_pct"])
    block_id = (flags != flags.shift()).cumsum()
    zones = [
        {
            "type": label, "start": idx.min(), "end": idx.max(), "bars": len(idx),
            "max_tier": int(tier.loc[idx].max()), "max_deviation_pct": float(deviation_abs.loc[idx].max()),
        }
        for _, idx in flags[flags].groupby(block_id[flags]).groups.items()
    ]
    return pd.DataFrame(zones).sort_values("start").reset_index(drop=True)


def tier_label(tier: int, tiers_pct: list[float]) -> str:
    lower = tiers_pct[tier - 1]
    upper = tiers_pct[tier] if tier < len(tiers_pct) else None
    return f"{lower:.0f}%+" if upper is None else f"{lower:.0f}~{upper:.0f}%"


def backtest_tier_entries(hynix: pd.DataFrame, zones: pd.DataFrame, tier: int, exit_ma_col: str = "ma") -> pd.DataFrame:
    """지정한 tier(과대낙폭 구간이 도달한 최고 단계)의 구간 시작 시점에 매수, 이후
    종가가 exit_ma_col(기본 60이평) 이상으로 회복하는 첫 시점에 청산하는 평균회귀
    백테스트. exit_ma_col에 더 느린 이평(예: "ma120")을 넘기면 더 낮은 목표가에서
    청산하는 조건으로 재검증할 수 있다 — 진입조건(9~12% 등 tier 분류 기준은 항상
    60이평)은 그대로 두고 청산 기준선만 바꾸는 구조.

    구간이 나중에 더 깊은 단계로 진행되더라도(예: 9%에서 시작해 14%까지 감) 진입은
    구간 시작 시점(첫 -9% 이탈) 기준으로 하고, tier 필터는 "이 구간이 도달한 최고
    단계가 정확히 이 tier였다"는 사후 분류다 — 실전에서는 진입 시점에 미래의 최고
    단계를 알 수 없으므로, 이 결과는 "9~12%에서 멈추고 더 깊이 안 간 경우들"의
    평균회귀 성과를 보는 것이지 실시간 트레이딩 가능한 필터는 아니다.
    """
    tier_zones = zones[zones["max_tier"] == tier]
    close = hynix["close"]
    trades = []
    for _, zone in tier_zones.iterrows():
        entry_time = zone["start"]
        entry_price = close.loc[entry_time]
        after = hynix.loc[hynix.index > entry_time]
        recovered = after[after["close"] >= after[exit_ma_col]].dropna(subset=[exit_ma_col])
        if recovered.empty:
            exit_time, exit_price, closed = hynix.index[-1], close.iloc[-1], False
        else:
            exit_time, exit_price, closed = recovered.index[0], recovered["close"].iloc[0], True
        bars_held = hynix.index.get_loc(exit_time) - hynix.index.get_loc(entry_time)
        trades.append({
            "entry_time": entry_time, "entry_price": entry_price,
            "exit_time": exit_time, "exit_price": exit_price,
            "return_pct": (exit_price / entry_price - 1) * 100,
            "bars_held": bars_held, "closed": closed,
        })
    return pd.DataFrame(trades)


def compute_ma_slope(ma: pd.Series, window: int) -> pd.Series:
    """window봉 전 대비 이평선 변화율(%) — 60이평이 최근 얼마나 가파르게 움직이는지."""
    return (ma - ma.shift(window)) / ma.shift(window) * 100


def slope_before_series(hynix: pd.DataFrame, times: pd.Series) -> pd.Series:
    """times(구간 시작 시각들) 바로 직전 봉의 기울기 값을, times와 같은 인덱스를 유지한 채
    반환한다 — 구간이 시작된 바로 그 순간이 아니라 "시작되기 전에 기울기가 어땠는지"를
    봐야 예측 관계를 말할 수 있다. 인덱스를 유지하는 이유는 호출부에서 zones 데이터프레임에
    바로 컬럼으로 붙여(max_deviation_pct 등 다른 컬럼과 짝을 맞춰) 쓰기 위해서다."""
    values = []
    for t in times:
        pos = hynix.index.get_loc(t)
        values.append(hynix["ma_slope_pct"].iloc[pos - 1] if pos > 0 else float("nan"))
    return pd.Series(values, index=times.index, dtype=float)


def slope_just_before(hynix: pd.DataFrame, times: pd.Series) -> pd.Series:
    """slope_before_series의 값만 필요한 경우(집계용) — NaN 제거하고 인덱스는 버린다."""
    return slope_before_series(hynix, times).reset_index(drop=True).dropna()


SPLIT_TRANCHE_PCTS = [9.0, 12.0, 15.0]  # PDF 전략3 분할매수 밴드(-9/-12/-15%)
HARD_STOP_PCT = 20.0  # 평단 대비 -20%
TIME_EXIT_DAYS = 15  # 거래일 내 60선 미복귀 시 시간청산


def backtest_split_entry_strategy(
    hynix: pd.DataFrame, zones: pd.DataFrame,
    tranche_pcts: list[float] = SPLIT_TRANCHE_PCTS,
    hard_stop_pct: float = HARD_STOP_PCT,
    time_exit_days: int = TIME_EXIT_DAYS,
) -> pd.DataFrame:
    """PDF 전략3(과대낙폭 분할매수) 재현. -9% 밴드 첫 터치 시 확인 없이 즉시 1차 매수
    (1/3), 이후 가격이 -12%/-15% 밴드까지 추가로 밀리면 지정가로 2차/3차 매수(각 1/3,
    거기까지 안 가면 그만큼 비중이 작게 끝난다 — tier 사후분류로 미리 걸러냈던 앞선
    백테스트와 달리 이건 실시간에도 그대로 재현 가능한 규칙이다). 청산은 셋 중 가장
    먼저 오는 조건: 60선 터치(전량 익절) / 평단 대비 -hard_stop_pct%(하드스톱) /
    time_exit_days 거래일 내 60선 미복귀(시간청산, 그날 종가로 청산).
    """
    trading_days = hynix.index.normalize().unique()
    day_index = {d: i for i, d in enumerate(trading_days)}

    trades = []
    position_open_until = None  # 직전 포지션의 청산 시각 — 그 전까지는 "같은 에피소드"로 보고 새로 진입하지 않음
    for _, zone in zones.iterrows():
        entry_time = zone["start"]
        if position_open_until is not None and entry_time <= position_open_until:
            # 이미 보유 중인 포지션의 청산 이전에 다시 -9%를 터치한 경우 — PDF 전략은
            # 매번 새 3분할을 까는 게 아니라 하나의 지정가 스택을 유지하는 구조이므로,
            # 이런 재터치는 별개 트레이드가 아니라 같은 포지션의 연장으로 취급한다
            # (2·3차 지정가는 어차피 이후 루프에서 더 깊은 밴드에 닿을 때 알아서 체결된다).
            continue
        entry_pos = hynix.index.get_loc(entry_time)
        entry_day_idx = day_index[entry_time.normalize()]

        fills = [hynix["close"].iloc[entry_pos]]  # 1차는 확인 없이 즉시 체결
        filled_tranches = 1
        exit_price, exit_time, exit_reason = None, None, None

        for pos in range(entry_pos, len(hynix)):
            row = hynix.iloc[pos]

            if filled_tranches < 2 and row["deviation_pct"] <= -tranche_pcts[1]:
                fills.append(row["close"])
                filled_tranches = 2
            if filled_tranches < 3 and row["deviation_pct"] <= -tranche_pcts[2]:
                fills.append(row["close"])
                filled_tranches = 3

            if pos == entry_pos:
                continue  # 청산 조건은 진입 봉 다음부터 확인(앞선 백테스트들과 동일 규칙)

            avg_cost = sum(fills) / len(fills)
            days_elapsed = day_index[row.name.normalize()] - entry_day_idx

            if row["close"] <= avg_cost * (1 - hard_stop_pct / 100):
                exit_price, exit_time, exit_reason = row["close"], row.name, "하드스톱"
                break
            if row["close"] >= row["ma"]:
                exit_price, exit_time, exit_reason = row["close"], row.name, "60선터치"
                break
            if days_elapsed >= time_exit_days:
                exit_price, exit_time, exit_reason = row["close"], row.name, "시간청산"
                break

        if exit_price is None:
            exit_price, exit_time, exit_reason = hynix["close"].iloc[-1], hynix.index[-1], "미청산"

        position_open_until = exit_time
        avg_cost = sum(fills) / len(fills)
        trades.append({
            "entry_time": entry_time, "filled_tranches": filled_tranches, "avg_cost": avg_cost,
            "exit_time": exit_time, "exit_price": exit_price, "exit_reason": exit_reason,
            "return_pct": (exit_price / avg_cost - 1) * 100,
            "bars_held": hynix.index.get_loc(exit_time) - entry_pos, "closed": exit_reason != "미청산",
        })
    return pd.DataFrame(trades)


PULLBACK_WATCH_BARS = 13  # "최근 반나절" — 15분봉 13개 ≈ 3.25시간
PULLBACK_PCT = 3.0  # 감시 발동 밴드(60선 -3%)
PULLBACK_MAX_DEPTH_PCT = 4.0  # 진입 허용 최대 낙폭 — 이보다 더 깊이 빠진 조정은 걸러낸다(아래 설명)
PULLBACK_TARGET_PCT = 5.0  # 청산 밴드(60선 +5%)
PULLBACK_STOP_LOSS_PCT = 4.0  # 손절(공격형, 진입가 대비)
PULLBACK_PAUSE_AFTER_LOSSES = 2  # 연속 손절 시 중단
PULLBACK_BREAKOUT_LOOKBACK_DAYS = 10  # 중단 해제 조건(10일 신고가 돌파)


def backtest_pullback_strategy(
    hynix: pd.DataFrame,
    watch_bars: int = PULLBACK_WATCH_BARS,
    pullback_pct: float = PULLBACK_PCT,
    max_depth_pct: float = PULLBACK_MAX_DEPTH_PCT,
    target_pct: float = PULLBACK_TARGET_PCT,
    stop_loss_pct: float = PULLBACK_STOP_LOSS_PCT,
    pause_after_losses: int = PULLBACK_PAUSE_AFTER_LOSSES,
) -> pd.DataFrame:
    """PDF 전략2(60선 아래 눌림매매) 재현.

    감시 발동: 최근 watch_bars봉 내 저가가 60선 -pullback_pct% 밴드를 터치했고, 현재
    종가가 60선 아래. 매수 트리거: 그 감시 상태에서 종가가 5봉선 위로 재돌파 + 양봉.
    청산: 고가가 60선 +target_pct% 밴드에 닿으면 전량 익절, 진입가 대비 -stop_loss_pct%
    이하로 저가가 닿으면 손절. 손절이 pause_after_losses회 연속 나오면 눌림매매를 중단
    하고, 10일 신고가 돌파가 다시 나오는 날까지 신규 진입을 쉰다(PDF 원문 규칙).

    익절/손절 체결가는 종가가 아니라 실제 고가/저가가 밴드·손절가에 닿았는지로 판단한다
    (PDF가 명시한 "고가가/저가가"라는 표현 그대로 — 앞선 전략3 재검증에서 종가 기준
    근사가 실제보다 유리하게 나올 수 있다고 지적했던 것을 여기서는 고가/저가로 보완).

    max_depth_pct 필터(핵심 수정): "-3% 밴드 터치"만 조건으로 두면 실제로는 -9%까지
    깊게 빠진 급락도(중간에 -3%를 지나쳤으니) 그대로 걸려들어, 얕은 눌림과 깊은 조정을
    구분 못 하고 뒤섞여 버린다. PDF 본문이 직접 "-4~5%까지 깊어진 조정은 승률이
    35~50%로 급락한다"고 밝혔는데, 정작 이 조건이 코드화 안 돼 있으면 실제로도 승률이
    거기까지 떨어진다(우리가 처음 재현했을 때 34.6%가 나온 게 이 증거) — 최근
    watch_bars봉 내 최저 괴리율이 -max_depth_pct%보다 더 깊이 안 간 "얕은" 눌림만
    통과시키게 추가했다.
    """
    ma5 = hynix["close"].rolling(5).mean()
    lower_band = hynix["ma"] * (1 - pullback_pct / 100)
    upper_band = hynix["ma"] * (1 + target_pct / 100)
    low_deviation_pct = (hynix["low"] - hynix["ma"]) / hynix["ma"] * 100
    touched_lower = hynix["low"] <= lower_band
    recent_min_deviation = low_deviation_pct.rolling(watch_bars, min_periods=1).min()
    shallow_only = recent_min_deviation >= -max_depth_pct
    watch_active = touched_lower.rolling(watch_bars, min_periods=1).max().astype(bool) & (hynix["close"] < hynix["ma"])
    bull_candle = hynix["close"] > hynix["open"]
    buy_trigger = watch_active & shallow_only & (hynix["close"] >= ma5) & bull_candle

    daily_high = hynix["high"].resample("1D").max().dropna()
    daily_close = hynix["close"].resample("1D").last().dropna()
    rolling_high_prior = daily_high.shift(1).rolling(PULLBACK_BREAKOUT_LOOKBACK_DAYS).max()
    breakout_days = set(daily_close.index[daily_close > rolling_high_prior].normalize())

    trades = []
    in_position = False
    entry_price = entry_time = None
    consecutive_losses = 0
    paused = False

    for pos in range(len(hynix)):
        t = hynix.index[pos]
        row = hynix.iloc[pos]

        if paused:
            if t.normalize() in breakout_days:
                paused = False
                consecutive_losses = 0  # 재개 시 "연속" 손절 카운트를 다시 0부터 — 안 그러면
                # 재개 직후 손절 한 번만 나와도(2연속이 아닌데도) 곧장 다시 중단돼버린다
            continue

        if not in_position:
            if buy_trigger.iloc[pos]:
                in_position, entry_price, entry_time = True, row["close"], t
            continue

        stop_price = entry_price * (1 - stop_loss_pct / 100)
        if row["low"] <= stop_price:
            exit_price, exit_reason = stop_price, "손절"
        elif row["high"] >= upper_band.iloc[pos]:
            exit_price, exit_reason = upper_band.iloc[pos], "익절(+5%밴드)"
        else:
            continue

        trades.append({
            "entry_time": entry_time, "entry_price": entry_price, "exit_time": t,
            "exit_price": exit_price, "exit_reason": exit_reason,
            "return_pct": (exit_price / entry_price - 1) * 100,
            "bars_held": pos - hynix.index.get_loc(entry_time),
        })
        in_position = False
        if exit_reason == "손절":
            consecutive_losses += 1
            if consecutive_losses >= pause_after_losses:
                paused = True
        else:
            consecutive_losses = 0

    return pd.DataFrame(trades)


def print_backtest_summary(label: str, trades: pd.DataFrame) -> None:
    print(f"\n=== {label} ===")
    if trades.empty:
        print("해당 구간에서 발생한 거래가 없습니다.")
        return
    n = len(trades)
    win_rate = (trades["return_pct"] > 0).mean() * 100
    avg_return = trades["return_pct"].mean()
    avg_bars = trades["bars_held"].mean()
    print(f"거래 수: {n}건, 승률: {win_rate:.1f}%, 평균 수익률: {avg_return:+.2f}%, 평균 보유: {avg_bars:.1f}봉(약 {avg_bars * 15 / 60:.1f}시간)")
    if "closed" in trades.columns:
        print(f"미청산(분석기간 끝까지 목표선 미회복): {(~trades['closed']).sum()}건")
    print(f"최고 수익: {trades['return_pct'].max():+.2f}%, 최저 수익: {trades['return_pct'].min():+.2f}%")
    print(f"단순합산 수익률(복리 아님): {trades['return_pct'].sum():+.2f}%")


def main():
    print(f"SK하이닉스 15분봉(정규장 {SESSION_START}~{SESSION_END}만) 로딩 중...")
    hynix_path = os.path.join(DATA_DIR, "stocks", "minute", f"{STOCK_CODE}.csv")
    kospi_path = os.path.join(DATA_DIR, "index", "minute", f"{KOSPI_INDEX_CODE}.csv")
    hynix_raw = load_regular_session_15min(hynix_path).loc[str(ANALYSIS_START):str(ANALYSIS_END)]
    kospi_raw = load_regular_session_15min(kospi_path).loc[str(ANALYSIS_START):str(ANALYSIS_END)]

    trading_days = hynix_raw.index.normalize().unique()
    span_days = (trading_days.max() - trading_days.min()).days
    print(
        f"분석 구간: {trading_days.min().date()} ~ {trading_days.max().date()} "
        f"(거래일 {len(trading_days)}일, 약 {span_days / 30.44:.1f}개월, 15분봉 {len(hynix_raw)}개)"
    )

    hynix = compute_envelope(hynix_raw, MA_WINDOW, TIER_PCTS)
    hynix["ma120"] = hynix["close"].rolling(120).mean()  # 청산 기준선 비교용(60이평 vs 120이평)
    hynix["ma_slope_pct"] = compute_ma_slope(hynix["ma"], SLOPE_WINDOW)

    oversold_zones = extract_zones(hynix["oversold"], hynix["oversold_tier"], hynix["deviation_pct"].abs(), "과대낙폭")
    overheated_zones = extract_zones(hynix["overheated"], hynix["overheated_tier"], hynix["deviation_pct"].abs(), "과열")

    print(f"\n=== 60이평 대비 괴리율 다단계 구간 (임계값: {', '.join(f'{t:.0f}%' for t in TIER_PCTS)}) ===")
    print(f"과대낙폭(하단, 60이평보다 낮음): {len(oversold_zones)}개 구간, 총 {oversold_zones['bars'].sum() if len(oversold_zones) else 0}봉")
    print(f"과열(상단, 60이평보다 높음):     {len(overheated_zones)}개 구간, 총 {overheated_zones['bars'].sum() if len(overheated_zones) else 0}봉")

    for label, zones in (("과대낙폭", oversold_zones), ("과열", overheated_zones)):
        if not len(zones):
            continue
        print(f"\n--- {label} 단계별 구간 수 ---")
        for tier in range(1, len(TIER_PCTS) + 1):
            count = (zones["max_tier"] == tier).sum()
            print(f"  {tier_label(tier, TIER_PCTS)}: {count}개 구간")
        print(f"\n{label} 최대 괴리율 상위 5개 구간:")
        print(
            zones.sort_values("max_deviation_pct", ascending=False).head(5)
            .assign(max_deviation_pct=lambda d: d["max_deviation_pct"].round(1))
            .to_string(index=False)
        )

    # ---- 60이평 기울기가 괴리율을 예측하는지 ----
    slope_dev = hynix[["ma_slope_pct", "deviation_pct"]].dropna()
    corr_signed = slope_dev["ma_slope_pct"].corr(slope_dev["deviation_pct"])
    corr_abs = slope_dev["ma_slope_pct"].abs().corr(slope_dev["deviation_pct"].abs())
    print(f"\n=== 60이평 기울기(최근 {SLOPE_WINDOW}봉 변화율)와 괴리율의 관계 ===")
    print(f"기울기 vs 괴리율 상관계수(부호 포함, 동시): {corr_signed:.3f} (n={len(slope_dev)})")
    print(f"|기울기| vs |괴리율| 상관계수(변동폭 크기, 동시): {corr_abs:.3f}")

    print(f"\n--- 기울기(t)가 미래 |괴리율|을 예측하는지 (시차별 상관계수) ---")
    for lag in SLOPE_LEAD_BARS:
        lag_df = pd.concat(
            [hynix["ma_slope_pct"], hynix["deviation_pct"].abs().shift(-lag).rename("future_abs_dev")], axis=1
        ).dropna()
        lag_corr = lag_df["ma_slope_pct"].corr(lag_df["future_abs_dev"])
        print(f"  기울기(t) vs |괴리율|(t+{lag}봉, 약 {lag * 15 / 60:.1f}시간 후): {lag_corr:.3f} (n={len(lag_df)})")

    overall_slope_mean = hynix["ma_slope_pct"].mean()
    oversold_pre_slope = slope_just_before(hynix, oversold_zones["start"])
    overheated_pre_slope = slope_just_before(hynix, overheated_zones["start"])
    print(f"\n--- 구간 시작 직전 60이평 기울기 비교 ---")
    print(f"전체 평균 기울기: {overall_slope_mean:+.3f}%")
    if len(oversold_pre_slope):
        print(f"과대낙폭 구간 시작 직전 평균 기울기: {oversold_pre_slope.mean():+.3f}% (n={len(oversold_pre_slope)})")
    if len(overheated_pre_slope):
        print(f"과열 구간 시작 직전 평균 기울기: {overheated_pre_slope.mean():+.3f}% (n={len(overheated_pre_slope)})")

    # ---- 구간 시작 시점 기울기가 그 구간의 "최대 도달 괴리율"을 예측하는지 ----
    # 위 두 검증(동시 상관관계, 시차별 봉 단위 예측)과는 다른 질문이다: 지금까지는
    # "기울기가 괴리율 크기를 실시간으로 예측하는가"였다면, 여기서는 "구간이 막
    # 시작되는 순간의 기울기가 그 구간이 결국 얼마나 깊이(9~12%/12~16%/16%+) 갈지"를
    # 미리 알려주는지를 본다 — 실전에서 "지금 -9% 터치했는데, 진입 시점 기울기를 보면
    # 이게 9~12%에서 멈출지 16%까지 갈지 가늠할 수 있는가"에 바로 쓸 수 있는 질문이라
    # 트레이딩 관점에서 위 두 검증보다 더 실용적이다.
    oversold_zones["slope_at_start"] = slope_before_series(hynix, oversold_zones["start"])
    overheated_zones["slope_at_start"] = slope_before_series(hynix, overheated_zones["start"])

    print("\n--- 구간 시작 시점 |기울기|가 그 구간의 최대 도달 괴리율을 예측하는지 ---")
    for label, zones in (("과대낙폭", oversold_zones), ("과열", overheated_zones)):
        valid = zones[["slope_at_start", "max_deviation_pct", "max_tier"]].dropna()
        if len(valid) < 5:
            print(f"{label}: 표본 부족(n={len(valid)}) — 상관관계 계산 생략")
            continue
        corr = valid["slope_at_start"].abs().corr(valid["max_deviation_pct"])
        coef, intercept = np.polyfit(valid["slope_at_start"].abs(), valid["max_deviation_pct"], 1)
        print(f"{label} (n={len(valid)}): |시작시점 기울기| vs 최대괴리율 상관계수 = {corr:.3f}")
        print(f"  회귀식(참고용): 최대괴리율% ≈ {coef:.2f} × |기울기%| + {intercept:.2f}")
        print(f"  tier별 시작시점 |기울기| 평균: " + ", ".join(
            f"{tier_label(t, TIER_PCTS)}={valid.loc[valid['max_tier'] == t, 'slope_at_start'].abs().mean():.2f}%"
            for t in sorted(valid["max_tier"].unique())
        ))

    fig3, axes3 = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for ax, label, zones in zip(axes3, ("과대낙폭", "과열"), (oversold_zones, overheated_zones)):
        valid = zones[["slope_at_start", "max_deviation_pct"]].dropna()
        ax.scatter(valid["slope_at_start"].abs(), valid["max_deviation_pct"], s=25)
        ax.set_xlabel("구간 시작 직전 |60이평 기울기|(%)")
        ax.set_title(label)
    axes3[0].set_ylabel("구간 최대 괴리율(%)")
    fig3.suptitle("구간 시작 시점 기울기 vs 그 구간의 최대 괴리율")
    fig3.tight_layout()
    fig3.savefig("sk_hynix_slope_vs_zone_depth.png", dpi=120)
    print("\n차트 저장: sk_hynix_slope_vs_zone_depth.png")

    fig2, ax2 = plt.subplots(figsize=(8, 6))
    ax2.scatter(slope_dev["ma_slope_pct"], slope_dev["deviation_pct"], s=4, alpha=0.25)
    ax2.axhline(0, color="gray", linewidth=0.5)
    ax2.axvline(0, color="gray", linewidth=0.5)
    ax2.set_xlabel(f"60이평 기울기(최근 {SLOPE_WINDOW}봉 변화율, %)")
    ax2.set_ylabel("괴리율(%)")
    ax2.set_title(f"60이평 기울기 vs 괴리율 (상관계수 {corr_signed:.3f})")
    fig2.tight_layout()
    fig2.savefig("sk_hynix_slope_vs_deviation.png", dpi=120)
    print("\n차트 저장: sk_hynix_slope_vs_deviation.png")

    # ---- 9~12% 과대낙폭 진입 백테스트: 청산 기준선 60이평 vs 120이평 비교 ----
    tier1_trades_ma60 = backtest_tier_entries(hynix, oversold_zones, tier=1, exit_ma_col="ma")
    print_backtest_summary("진입조건 백테스트: 과대낙폭 9~12% 매수 → 60이평 터치 청산", tier1_trades_ma60)
    if not tier1_trades_ma60.empty:
        print("\n거래 내역(60이평 청산):")
        print(tier1_trades_ma60.assign(return_pct=lambda d: d["return_pct"].round(2)).to_string(index=False))

    tier1_trades_ma120 = backtest_tier_entries(hynix, oversold_zones, tier=1, exit_ma_col="ma120")
    print_backtest_summary("진입조건 백테스트: 과대낙폭 9~12% 매수 → 120이평 터치 청산", tier1_trades_ma120)
    if not tier1_trades_ma120.empty:
        print("\n거래 내역(120이평 청산):")
        print(tier1_trades_ma120.assign(return_pct=lambda d: d["return_pct"].round(2)).to_string(index=False))

    # ---- PDF 전략3(과대낙폭 분할매수) 재현 검증: -9%(즉시)/-12%/-15% 3분할, 60선 터치 익절,
    # 평단 -20% 하드스톱, 15거래일 시간청산. tier로 사후분류하지 않고 -9% 터치한 모든 구간(18개)에
    # 적용한다 — PDF의 발동조건("연 12회")과 동일하게, 진입 시점에 미래 깊이를 몰라도 되는 규칙이다.
    split_trades = backtest_split_entry_strategy(hynix, oversold_zones)
    print_backtest_summary("PDF 전략3 재현: -9% 터치 시 3분할 매수(-9/-12/-15%) → 60선 터치 전량 익절 (하드스톱/시간청산 포함)", split_trades)
    if not split_trades.empty:
        print(f"\n청산 사유별 건수: {split_trades['exit_reason'].value_counts().to_dict()}")
        print(f"평균 체결 분할 수: {split_trades['filled_tranches'].mean():.2f} / 3")
        print("\n거래 내역:")
        print(
            split_trades.assign(
                avg_cost=lambda d: d["avg_cost"].round(0), return_pct=lambda d: d["return_pct"].round(2),
            ).to_string(index=False)
        )
        print(
            "\n참고 — PDF 원본 수치: 12회 · 평균 +4.20% · 승률 92%(11승 1패) · 최악 -3.82% · "
            "누적 +50.4% · 평균 보유 1.6일 (위 결과는 우리 로컬 데이터 재계산치라 완전히 같을 필요는 없음)"
        )

    # ---- PDF 전략2(눌림매매) 재현: 60선 -3% 밴드 터치 감시 -> 5봉선 재돌파+양봉 매수 ----
    # 이 구간만 KOSPI 겹침 제약(ANALYSIS_END=07-15) 없이 로컬에 있는 최신 데이터(오늘까지)를
    # 그대로 써서, "이번달 수익률"에 이번 달 마지막 며칠(07-16~07-21)이 빠지지 않게 한다.
    hynix_latest = compute_envelope(load_regular_session_15min(hynix_path), MA_WINDOW, TIER_PCTS)
    pullback_trades = backtest_pullback_strategy(hynix_latest)
    print_backtest_summary("PDF 전략2 재현: 60선 -3% 눌림 → 5봉선 재돌파 매수, +5%밴드 익절/-4% 손절", pullback_trades)
    if not pullback_trades.empty:
        print(f"청산 사유별 건수: {pullback_trades['exit_reason'].value_counts().to_dict()}")
        print(
            "\n참고 — PDF 원본 수치: 연 32회 · 평균 +2.82% · 승률 62% · 누적 +90.2% · "
            "평균 보유 3.2일 (우리는 전체 기간 12.4개월 기준이라 "
            f"연환산하면 약 {len(pullback_trades) / 12.4 * 12:.0f}회)"
        )

        this_month_trades = pullback_trades[pullback_trades["entry_time"].dt.strftime("%Y-%m") == "2026-07"]
        print_backtest_summary("↳ 이번달(2026-07)만", this_month_trades)
        if not this_month_trades.empty:
            print(
                this_month_trades.assign(
                    entry_price=lambda d: d["entry_price"].round(0), exit_price=lambda d: d["exit_price"].round(0),
                    return_pct=lambda d: d["return_pct"].round(2),
                ).to_string(index=False)
            )
            print(f"이번달 눌림매매 단순합산 수익률(복리 아님): {this_month_trades['return_pct'].sum():+.2f}%")

    # ---- 코스피 상관관계 (15분봉 동시 시각 기준) ----
    joined = pd.concat(
        [hynix["close"].pct_change().rename("hynix"), kospi_raw["close"].pct_change().rename("kospi")], axis=1, sort=False
    ).dropna()
    kospi_corr = joined["hynix"].corr(joined["kospi"])
    print(f"\n=== SK하이닉스 vs 코스피 15분봉 수익률 상관계수 ===\n{kospi_corr:.3f} (n={len(joined)})")

    # ---- 미국장 상관관계 (전날 밤 종가 대비 당일 SK하이닉스) ----
    print("\nYahoo Finance에서 나스닥/마이크론/엔비디아 일봉 로딩 중...")
    us_daily_returns = pd.DataFrame(
        {name: fetch_yahoo_daily(symbol).pct_change() for name, symbol in US_SYMBOLS.items()}
    )

    kr_days = pd.Series(hynix.index.normalize().unique()).sort_values()
    # 미국 거래일 D의 수익률 -> 그 다음 한국 거래일에 매핑(달력상 다음날, 휴장일 등은 ffill로 흡수)
    us_aligned = us_daily_returns.reindex(kr_days - pd.Timedelta(days=1), method="ffill")
    us_aligned.index = kr_days

    hynix_daily_ret = hynix["close"].resample("1D").last().dropna().pct_change()
    daily_joined = pd.concat([hynix_daily_ret.rename("hynix_day_return"), us_aligned], axis=1).dropna()
    print("\n=== [일별] 전날 밤 미국장 수익률 vs 당일 SK하이닉스 일간 수익률 상관계수 ===")
    print(daily_joined.corr()["hynix_day_return"].drop("hynix_day_return").to_string())

    bar_join = hynix[["close"]].copy()
    bar_join["hynix_bar_return"] = hynix["close"].pct_change()
    bar_join["kr_day"] = bar_join.index.normalize()
    bar_join = bar_join.join(us_aligned, on="kr_day")
    bar_corr = bar_join[["hynix_bar_return", *US_SYMBOLS.keys()]].dropna().corr()["hynix_bar_return"].drop("hynix_bar_return")
    print("\n=== [봉 단위 참고용] 당일 모든 15분봉에 전날 밤 미국 수익률을 동일 매핑했을 때 상관계수 ===")
    print("(미국 변수가 하루 내내 상수라 봉 단위 상관계수는 일별 버전보다 해석에 주의)")
    print(bar_corr.to_string())

    # ---- 과대낙폭 구간과 전날 밤 미국장의 관계 ----
    if len(oversold_zones):
        zone_days = oversold_zones["start"].dt.normalize().unique()
        zone_us_ret = us_aligned.reindex(zone_days).mean()
        all_us_ret = us_aligned.mean()
        print("\n=== 과대낙폭 구간이 발생한 날의 '전날 밤 미국장' 평균수익률 vs 전체 평균 ===")
        print(pd.DataFrame({"과대낙폭 발생일 평균": zone_us_ret, "전체 평균": all_us_ret}).to_string())

    # ---- 갭하락 오픈(09:00 첫 봉부터 과대낙폭) vs 전날 밤 나스닥/마이크론 낙폭 ----
    opens = hynix.between_time("09:00", "09:00")
    gap_open = opens[opens["oversold"]].copy()
    gap_open["kr_day"] = gap_open.index.normalize()
    gap_open = gap_open.join(us_aligned, on="kr_day")

    print(f"\n=== 09:00 첫 봉부터 과대낙폭으로 갭하락 출발한 날 (n={len(gap_open)}) ===")
    if gap_open.empty:
        print("해당 사례가 없습니다.")
    elif len(gap_open) < 5:
        print(f"표본이 {len(gap_open)}건뿐이라 확률/구간별 통계는 의미가 없습니다 — 개별 사례만 나열합니다.")
        print(
            gap_open[["deviation_pct", "oversold_tier", "nasdaq", "micron", "nvidia"]]
            .assign(
                deviation_pct=lambda d: d["deviation_pct"].round(2),
                nasdaq=lambda d: (d["nasdaq"] * 100).round(2),
                micron=lambda d: (d["micron"] * 100).round(2),
                nvidia=lambda d: (d["nvidia"] * 100).round(2),
            )
            .rename(columns={"nasdaq": "전날밤 나스닥%", "micron": "전날밤 마이크론%", "nvidia": "전날밤 엔비디아%"})
            .to_string()
        )
    else:
        table = (
            gap_open[["deviation_pct", "oversold_tier", "nasdaq", "micron", "nvidia"]]
            .assign(
                deviation_pct=lambda d: d["deviation_pct"].round(2),
                nasdaq=lambda d: (d["nasdaq"] * 100).round(2),
                micron=lambda d: (d["micron"] * 100).round(2),
                nvidia=lambda d: (d["nvidia"] * 100).round(2),
            )
            .rename(columns={"nasdaq": "전날밤 나스닥%", "micron": "전날밤 마이크론%", "nvidia": "전날밤 엔비디아%"})
        )
        print(table.to_string())

    if len(gap_open) >= 3:
        for us_name in ("micron", "nasdaq"):
            valid = gap_open[[us_name, "deviation_pct"]].dropna()
            if len(valid) < 3:
                continue
            corr = valid[us_name].corr(valid["deviation_pct"])
            slope, intercept = np.polyfit(valid[us_name] * 100, valid["deviation_pct"], 1)
            print(f"\n전날밤 {us_name} 낙폭 vs 당일 09:00 괴리율 상관계수: {corr:.3f} (n={len(valid)})")
            print(f"회귀식(참고용, n={len(valid)}로 매우 불안정): 괴리율% ≈ {slope:.2f} × ({us_name}낙폭%) + {intercept:.2f}")
        print(
            "\n⚠️ 표본이 8건뿐입니다. \"마이크론이 -3% 빠지면 몇 % 확률로 -12%까지 간다\" 같은 "
            "구간별 확률 추정은 이 정도 표본으로는 통계적으로 신뢰할 수 없습니다 — 위 회귀식은 "
            "대략의 방향성 참고용이지, 실전 예측 모델로 쓰기엔 데이터가 턱없이 부족합니다."
        )

    # ---- 차트 저장 ----
    fig, ax = plt.subplots(figsize=(16, 6))
    ax.plot(hynix.index, hynix["close"], label="종가", linewidth=0.7)
    ax.plot(hynix.index, hynix["ma"], label=f"{MA_WINDOW}이평", linewidth=0.8, color="orange")
    for i, t in enumerate(TIER_PCTS):
        band_style = {"linewidth": 0.6, "linestyle": "--", "color": "gray", "alpha": 0.3 + 0.2 * i}
        ax.plot(hynix.index, hynix["ma"] * (1 + t / 100), label=f"+{t:.0f}%", **band_style)
        ax.plot(hynix.index, hynix["ma"] * (1 - t / 100), label=f"-{t:.0f}%", **band_style)

    tier_alpha = {1: 0.12, 2: 0.2, 3: 0.32}
    for _, row in oversold_zones.iterrows():
        ax.axvspan(row["start"], row["end"], color="blue", alpha=tier_alpha[row["max_tier"]])
    for _, row in overheated_zones.iterrows():
        ax.axvspan(row["start"], row["end"], color="red", alpha=tier_alpha[row["max_tier"]])
    ax.set_title("SK하이닉스 15분봉 60이평 괴리율 다단계(9/12/16%) — 과대낙폭(파랑) / 과열(빨강), 진할수록 깊은 단계")
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig("sk_hynix_envelope_zones.png", dpi=120)
    print("\n차트 저장: sk_hynix_envelope_zones.png")


if __name__ == "__main__":
    main()
