"""틱 → 1초 격자 변환 (Phase 2의 토대).

## 왜 격자로 접는가 — 실측 근거

선행 연구에서 확인된 것:
- 그리드 지점마다 틱을 다시 훑으면 종목·일당 ~390지점 × 2,017파일 = **80만 번 재스캔**
  → 추정 40~60분
- **1초 격자로 한 번 접으면** 어떤 창이든 누적합 뺄셈 한 번 → **16초**
- 이 프로젝트에서도 파이썬 루프로 청산을 돌렸다가 20억 회 반복으로 10분을 넘겨
  중단시킨 적이 있다(벡터화 후 42초, 15배).

**따라서 창 집계는 반드시 격자+누적합으로 한다.** 이건 성능 최적화가 아니라
이 규모에서 계산을 가능하게 하는 전제다.

## 실시간 호환 (명세 §38)

격자는 **증분 갱신이 가능한 구조**다 — 새 체결이 들어오면 해당 초 버킷에 더하기만 하면
되고, 창 집계는 누적합 두 점의 차이다. 그래서 같은 코드가 실시간에서도 동작한다.
(백테스트와 실시간이 다른 방식으로 계산되면 안 된다 — 명세의 가장 중요한 원칙.)

## 미래 참조 차단

격자의 t번째 칸은 **[t, t+1)초 구간에 체결된 것**만 담는다. 창 집계는 전부 `[t-w, t)` —
**t 자신을 포함하지 않는다**. 이 규칙을 `windows.py`가 강제하고 `test_no_lookahead.py`가
검증한다.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

from ..data.schema import SIDE_BUY, SIDE_SELL

SESSION_START_SEC = 9 * 3600          # 09:00:00
SESSION_END_SEC = 15 * 3600 + 30 * 60  # 15:30:00
N_SEC = SESSION_END_SEC - SESSION_START_SEC + 1   # 23,401칸


@dataclass(frozen=True)
class SecondGrid:
    """한 종목·일의 1초 격자. 모든 배열 길이는 N_SEC.

    price: 그 초의 **마지막 체결가**(체결 없으면 직전 값 유지 → ffill, 장 시작 전은 bfill)
    high/low: 그 초의 고가/저가. 체결 없는 초는 price와 같다.
        **라벨(Phase 3)에서 "익절과 손절 중 어느 쪽을 먼저 쳤나"를 판정하는 데 쓴다.**
        마지막 체결가만 보면 초 안에서 스친 값을 놓쳐 라벨이 낙관적으로 왜곡된다.
    trades/volume/value: 그 초의 합계 (체결 없으면 0)
    buy_volume/sell_volume: tick rule 기준 (side_source를 같이 들고 다닌다)
    has_trade: 그 초에 체결이 있었는지 — 체결 간격 계산에 필요
    """
    symbol: str
    date: str
    ref_price: int | None
    price: np.ndarray
    high: np.ndarray
    low: np.ndarray
    trades: np.ndarray
    volume: np.ndarray
    value: np.ndarray
    buy_volume: np.ndarray
    sell_volume: np.ndarray
    buy_value: np.ndarray
    sell_value: np.ndarray
    has_trade: np.ndarray
    side_source: str

    def __len__(self) -> int:
        return N_SEC

    def seconds(self) -> np.ndarray:
        """격자 인덱스 → 장 시작 후 경과 초(0 = 09:00:00)."""
        return np.arange(N_SEC)


def to_grid(df: pl.DataFrame) -> SecondGrid:
    """표준 스키마 DataFrame(한 종목·일, 정규장) → 1초 격자.

    입력은 `loader.load_stock_day(..., regular_only=True)` 결과를 전제한다.
    정규장 밖이 섞여 있으면 여기서 걸러낸다(이중 안전장치 — 시간외 혼입은 실제 사고였다).
    """
    if df.is_empty():
        raise ValueError("빈 DataFrame으로 격자를 만들 수 없다")
    symbol = df["symbol"][0]
    date = df["timestamp"][0].strftime("%Y-%m-%d")
    ref = df["ref_price"][0]
    src = df["side_source"][0]

    # 주의: polars의 dt.hour()는 Int8이라 3600을 그냥 곱하면 **오버플로**한다(실측 확인).
    # 반드시 Int64로 올린 뒤 계산한다.
    ts = df["timestamp"]
    sec = (ts.dt.hour().cast(pl.Int64) * 3600
           + ts.dt.minute().cast(pl.Int64) * 60
           + ts.dt.second().cast(pl.Int64)).to_numpy() - SESSION_START_SEC
    keep = (sec >= 0) & (sec < N_SEC)
    sec = sec[keep]
    price = df["price"].to_numpy()[keep].astype(np.float64)
    vol = df["volume"].to_numpy()[keep].astype(np.float64)
    val = df["trade_value"].to_numpy()[keep].astype(np.float64)
    side = df["side"].to_numpy()[keep]
    if len(sec) == 0:
        raise ValueError(f"{symbol} {date}: 정규장 체결이 없다")

    is_buy = side == SIDE_BUY
    is_sell = side == SIDE_SELL

    trades = np.bincount(sec, minlength=N_SEC).astype(np.float64)
    volume = np.bincount(sec, weights=vol, minlength=N_SEC)
    value = np.bincount(sec, weights=val, minlength=N_SEC)
    buy_volume = np.bincount(sec, weights=np.where(is_buy, vol, 0.0), minlength=N_SEC)
    sell_volume = np.bincount(sec, weights=np.where(is_sell, vol, 0.0), minlength=N_SEC)
    buy_value = np.bincount(sec, weights=np.where(is_buy, val, 0.0), minlength=N_SEC)
    sell_value = np.bincount(sec, weights=np.where(is_sell, val, 0.0), minlength=N_SEC)

    # 그 초의 마지막 체결가 — 입력이 시간순(seq 오름차순)이므로 뒤에 쓰는 값이 남는다.
    last = np.zeros(N_SEC)
    last[sec] = price
    has = trades > 0
    # 체결 없는 초는 직전 가격을 유지(ffill), 장 시작 전 구간은 첫 체결가로 채운다(bfill).
    # **polars의 fill_null은 NaN을 안 채운다**(null과 NaN이 별개다) — 그래서 numpy로 한다.
    idx = np.where(has, np.arange(N_SEC), 0)
    np.maximum.accumulate(idx, out=idx)          # ffill: 직전 체결 인덱스를 끌고 온다
    px = last[idx]
    first = int(np.argmax(has))                  # 첫 체결 이전 구간은 첫 체결가로(bfill)
    px[:first] = last[first]

    # 초당 고가/저가. `np.maximum.at`은 버퍼를 안 써서 매우 느리다 —
    # sec는 ingest가 timestamp로 정렬해 보장하므로 `reduceat`으로 한 번에 접는다.
    hi, lo = px.copy(), px.copy()                # 체결 없는 초는 유지된 가격 그대로
    uniq, start = np.unique(sec, return_index=True)
    hi[uniq] = np.maximum.reduceat(price, start)
    lo[uniq] = np.minimum.reduceat(price, start)

    return SecondGrid(symbol=symbol, date=date, ref_price=ref, price=px, high=hi, low=lo,
                      trades=trades,
                      volume=volume, value=value, buy_volume=buy_volume,
                      sell_volume=sell_volume, buy_value=buy_value, sell_value=sell_value,
                      has_trade=has, side_source=src)
