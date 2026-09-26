"""틱 조건(진입 신호) — 설계서 §3.7 틱 카탈로그 · §3.2 `tick.catalog` · P5·C4.

한 종목·하루(`TickDay`)의 체결만 보고 **신호 초 s** 를 낸다. 돈·체결·비용은 여기 없다(엔진 몫).

## 입력 계약 (`TickDay`)
`sec` = 정규장 09:00:00 을 0 으로 한 **격자 초**(0..23400), **시간순**(같은 초 안은 체결 순서 그대로),
`prc`/`qty` = 체결가·체결량. `_precursor_fastpath.to_grid(path)` 의 `tick_sec/tick_prc/tick_qty` 가 이미
이 모양이다(원본 역시간순 뒤집기·정규장 필터·tie 순서 수정 끝난 판) — 로더는 그걸 그대로 담으면 된다.

## 시점 규칙 (C4)
- 신호 초 s 는 **s 초까지의 체결**(그 초의 마지막 체결가 포함)만 보고 정해진다.
- **진입은 s 보다 엄격히 뒤 체결**(`entry_sec > signal_sec`) — 기존 `precursor_master.mfe_mae` 의 T0 다음 체결과 같다.
- 창은 `[s−w, s)`(s 자신 제외), 단 돌파는 "s 의 가격이 앞 w 초 최고가를 넘음"이라 s 가격을 쓴다(기존 정의 그대로).

## 정의 (기존 연구 함수와 같은 것을 재사용, 수식만 옮김 — 도메인은 backtesting 을 import 못 함)
- `breakout_min`: `precursor_master.detect_breakouts` 와 같음 — 1초 격자 종가 `px`, `px > max(px[s−w, s))`.
- `value_speed(w, ratio)`: `[s−w, s)` 체결대금 ÷ **인과적 누적 평균**(s−w 이전 누적 ÷ 그때까지 지난 w 구간 수, 1구간 이상 지나야 값 있음)
  ≥ ratio. `t0_forward_return._expanding_period_avg` 와 같은 식.
- `buy_ratio(w, min)`: `[s−w, s)` 틱룰 매수 체결량 ÷ 전체 체결량 ≥ min. 틱룰 = 상승체결 +1 / 하락 −1 / 보합은 직전 방향 계승.
- `time_from/time_to`: 신호 초의 시각이 이 범위 안(양끝 포함).

**연구 코드와 한 가지 다른 점**: `precursor_master_features._win_at` 는 주석엔 "`[t−w, t)`" 라 쓰지만 실제로는
`window_sum` 을 t−1 에서 읽어 `[t−1−w, t−1)` 을 본다(1초 지연, 보수적이라 미래참조는 아님). 여기서는 주석대로
`[s−w, s)` 를 쓴다 → **여기 s 의 값 = 연구 `compute_features` 의 t0 = s+1 값**(P5 보조 테스트가 대조).

## 쿨다운은 조건 쪽에서 한다 (결정)
`cooldown_sec` 안의 재신호는 **최종 신호(조건 전부 AND 한 뒤)** 를 시간순으로 훑으며 솎아낸다 — `detect_breakouts` 와 같은
방식(마지막으로 *채택된* 신호로부터 cooldown 이상 떨어져야 채택). 근거: ① P5 가 요구하는 "기존 함수와 동일" 이
신호 정의 안에 쿨다운이 들어 있어야 성립한다, ② 엔진에 두면 "포지션 보유·슬롯 꽉 참 때문에 못 산 신호"가
쿨다운 시계를 리셋하지 않아 신호 시각이 포트폴리오 상태에 좌우된다(신호가 돈 상태에 의존 — 계약 위반).
엔진은 신호를 받아 체결·건너뜀만 한다. 조건이 둘 이상이면 "돌파를 솎은 뒤 나머지로 거르는" 연구 파이프라인과 결과가 다를 수 있다.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

SESSION_START, SESSION_END = 32400, 55800  # 09:00:00 ~ 15:30:00 (_precursor_fastpath 와 같은 격자)
N = SESSION_END - SESSION_START + 1
GAP_OPEN_PCT = 5.0  # 갭시작 제외 기준(%) — precursor_master.GAP_OPEN_PCT(0.05)와 같은 값


@dataclass(frozen=True, eq=False)
class TickDay:
    code: str
    date: dt.date
    sec: np.ndarray  # int, 격자 초(0=09:00:00), 시간순
    prc: np.ndarray
    qty: np.ndarray
    prev_close: float | None = None

    def __post_init__(self) -> None:
        if not (len(self.sec) == len(self.prc) == len(self.qty)):
            raise ValueError("TickDay: sec·prc·qty 길이가 다름")
        s = np.asarray(self.sec)
        if len(s) and (s.min() < 0 or s.max() >= N or np.any(np.diff(s) < 0)):
            raise ValueError("TickDay: sec 는 0..23400 범위의 시간순이어야 함")


@dataclass(frozen=True, eq=False)
class TickGrid:
    px: np.ndarray   # 1초 격자 종가(같은 초 마지막 체결가, 앞뒤 채움)
    vol: np.ndarray  # 초당 체결량
    cnt: np.ndarray  # 초당 체결 건수
    val: np.ndarray  # 초당 체결대금(가격×수량)
    buy: np.ndarray  # 초당 틱룰 매수 체결량
    sell: np.ndarray | None = None  # 초당 틱룰 매도 체결량(체결강도용)
    seen: np.ndarray | None = None  # 그 초까지 체결이 한 번이라도 있었나(첫 체결 전 앞채움 가격을 신호에 못 쓰게)


@dataclass(frozen=True, eq=False)
class TickEvents:
    """신호와 그 진입 체결. 배열은 서로 같은 길이·같은 순서이며 항상 `entry_sec > signal_sec`."""
    code: str
    date: dt.date
    signal_sec: np.ndarray   # 신호 초 s (실제 시각 = 09:00:00 + s초)
    entry_idx: np.ndarray    # 진입 체결의 틱 인덱스(TickDay 배열 기준) — s 보다 엄격히 뒤 첫 체결
    entry_sec: np.ndarray
    entry_price: np.ndarray
    n_no_entry: int = 0      # 뒤에 체결이 없어 진입 못 하는 신호 수(장 끝 근처)


def tick_rule_direction(prc: np.ndarray) -> np.ndarray:
    """표준 틱룰: 상승체결 +1 / 하락 −1 / 보합은 직전 판정 계승 / 최초 틱은 0. (shooting_precursor 와 같음)"""
    if len(prc) == 0:
        return np.zeros(0, dtype=np.int8)
    d = np.sign(np.diff(prc, prepend=prc[0]))
    d[0] = 0
    return pd.Series(d).replace(0, np.nan).ffill().fillna(0).to_numpy(dtype=np.int8)


def build_grid(day: TickDay) -> TickGrid:
    sec = np.asarray(day.sec, dtype=np.int64)
    prc = np.asarray(day.prc, dtype=float)
    qty = np.asarray(day.qty, dtype=float)
    last = np.zeros(N)
    last[sec] = prc  # 같은 초 여러 체결이면 마지막이 남는다(시간순 입력 전제)
    px = pd.Series(np.where(last > 0, last, np.nan)).ffill().bfill().to_numpy()
    direction = tick_rule_direction(prc)
    return TickGrid(
        px=px,
        vol=np.bincount(sec, weights=qty, minlength=N),
        cnt=np.bincount(sec, minlength=N).astype(float),
        val=np.bincount(sec, weights=prc * qty, minlength=N),
        buy=np.bincount(sec, weights=np.where(direction > 0, qty, 0.0), minlength=N),
        sell=np.bincount(sec, weights=np.where(direction < 0, qty, 0.0), minlength=N),
        seen=np.cumsum(np.bincount(sec, minlength=N)) > 0,
    )


# ---------------------------------------------------------------- 조건 (길이 N bool)
def _window_sum(x: np.ndarray, w: int) -> np.ndarray:
    """s 초의 `[s−w, s)` 합계(s < w 이면 NaN)."""
    out = np.full(N, np.nan)
    if w >= N:
        return out
    cs = np.concatenate(([0.0], np.cumsum(x)))
    out[w:] = cs[w:N] - cs[: N - w]
    return out


def breakout_hits(grid: TickGrid, w_min: int) -> np.ndarray:
    """px[s] 가 직전 w 분 `[s−w, s)` 의 최고가를 넘은 초 — `detect_breakouts` 의 쿨다운 전 원시 신호."""
    w = int(w_min) * 60
    if N <= w:
        return np.zeros(N, dtype=bool)
    s = pd.Series(grid.px).rolling(w).max().shift(1).to_numpy()
    return (grid.px > s) & np.isfinite(s)


def value_speed_series(grid: TickGrid, w_min: int) -> np.ndarray:
    """s 초의 체결대금 속도 = `[s−w, s)` 체결대금 ÷ 인과적 누적 평균(값 없으면 NaN)."""
    w = int(w_min) * 60
    wv = _window_sum(grid.val, w)
    avg = np.full(N, np.nan)
    if w < N:
        cs = np.concatenate(([0.0], np.cumsum(grid.val)))
        k = np.arange(N) - w  # 창 시작 이전까지 누적
        ok = k >= w           # 지난 구간이 1개 이상일 때만(인과적 평균)
        avg[ok] = cs[k[ok]] / (k[ok] / w)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where((avg > 0) & np.isfinite(avg), wv / avg, np.nan)


def buy_ratio_series(grid: TickGrid, w_min: int) -> np.ndarray:
    """s 초의 매수 비중 = `[s−w, s)` 틱룰 매수 체결량 ÷ 전체 체결량(체결 없으면 NaN)."""
    w = int(w_min) * 60
    wb, wvol = _window_sum(grid.buy, w), _window_sum(grid.vol, w)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(wvol > 0, wb / wvol, np.nan)


def value_speed_hits(grid: TickGrid, w_min: int, ratio: float) -> np.ndarray:
    sp = value_speed_series(grid, w_min)
    return np.isfinite(sp) & (sp >= ratio)


def buy_ratio_hits(grid: TickGrid, w_min: int, min_ratio: float) -> np.ndarray:
    r = buy_ratio_series(grid, w_min)
    return np.isfinite(r) & (r >= min_ratio)


def trade_strength_series(grid: TickGrid, w_sec: int) -> np.ndarray:
    """s 초의 체결강도 = `[s−w, s)` 틱룰 매수량 ÷ 매도량 × 100. 매도 0·매수 있음 → inf, 둘 다 0 → NaN."""
    wb, ws = _window_sum(grid.buy, int(w_sec)), _window_sum(grid.sell, int(w_sec))
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(ws > 0, wb / ws * 100.0, np.where(wb > 0, np.inf, np.nan))
    return np.where(np.isnan(wb), np.nan, r)  # 창이 세션 시작 앞에 걸치면 값 없음


def trade_strength_hits(grid: TickGrid, w_sec: int, min_strength: float) -> np.ndarray:
    r = trade_strength_series(grid, w_sec)
    return ~np.isnan(r) & (r >= min_strength)


def value_window_series(grid: TickGrid, w_min: int) -> np.ndarray:
    """s 초의 최근 w분 체결대금 합(원) = **`(s−w, s]`**(s 초의 체결 포함, 정확한 가격×수량). 창이 세션 시작 앞에 걸치면(s < w−1) 값 없음."""
    w = int(w_min) * 60
    out = np.full(N, np.nan)
    if w > N:
        return out
    cs = np.concatenate(([0.0], np.cumsum(grid.val)))
    out[w - 1:] = cs[w:N + 1] - cs[: N - w + 1]
    return out


def value_window_hits(grid: TickGrid, w_min: int, min_eok: float) -> np.ndarray:
    v = value_window_series(grid, w_min)
    return ~np.isnan(v) & (v >= float(min_eok) * 1e8)


def block_count_series(day: TickDay, w_sec: int, min_value: float) -> np.ndarray:
    """s 초의 대량 체결 건수 = `[s−w, s)` 안에서 **한 번의 체결대금(가격×수량) ≥ min_value** 인 체결 수."""
    sec = np.asarray(day.sec, dtype=np.int64)
    big = np.asarray(day.prc, dtype=float) * np.asarray(day.qty, dtype=float) >= float(min_value)
    return _window_sum(np.bincount(sec[big], minlength=N).astype(float), int(w_sec))


def block_trades_hits(day: TickDay, w_sec: int, min_value: float, min_count: int = 1) -> np.ndarray:
    c = block_count_series(day, w_sec, min_value)
    return ~np.isnan(c) & (c >= min_count)


def prior_n_high(dates: Any, highs: Any, day: dt.date, n: int) -> float:
    """`day` 보다 **엄격히 앞선** 마지막 n 거래일 고가의 최댓값(D−1 까지). n 일이 안 되면 NaN. `dates` 는 오름차순 date 들."""
    d = np.asarray(list(dates), dtype="datetime64[D]")
    h = np.asarray(highs, dtype=float)
    k = int(np.searchsorted(d, np.datetime64(day), side="left"))  # day 미만 개수
    if k < n:
        return float("nan")
    w = h[k - n:k]
    return float(np.nanmax(w)) if np.isfinite(w).any() else float("nan")


def daily_breakout_hits(grid: TickGrid, level: float) -> np.ndarray:
    """px[s] > D−1 까지 n일 최고가(level). 첫 체결 전(앞채움 가격)엔 신호 없음. level 이 NaN 이면 전부 False."""
    if not np.isfinite(level):
        return np.zeros(N, dtype=bool)
    return grid.seen & (grid.px > level)


def _hms(s: str) -> int:
    parts = [int(x) for x in s.split(":")]
    parts += [0] * (3 - len(parts))
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def time_mask(time_from: str, time_to: str) -> np.ndarray:
    sod = SESSION_START + np.arange(N)
    return (sod >= _hms(time_from)) & (sod <= _hms(time_to))


def align_filter(end_sec: np.ndarray, ok: np.ndarray) -> np.ndarray:
    """분봉 조건 묶음(tick.filter)의 값을 틱 초 격자(길이 N)에 붙인다 — 초 s 의 값 = **끝 시각 ≤ s 인 마지막 분봉**의 값(마감된 봉만).
    end_sec = 그 날 분봉 끝 시각(09:00:00 = 0, 시간순), ok = 그 봉에서 조건이 참인가. 첫 마감 봉 전(s < 첫 끝 시각)은 값 없음 = False.
    분봉 값이 s 이후 봉·s 이후 체결에 의존하지 않는다는 것이 C8 이 검증하는 계약이다."""
    e = np.asarray(end_sec)
    k = np.searchsorted(e, np.arange(N), side="right") - 1
    v = np.asarray(ok, dtype=bool)
    return np.where(k >= 0, v[np.maximum(k, 0)], False) if len(e) else np.zeros(N, dtype=bool)


def apply_cooldown(idx: np.ndarray, cooldown_sec: int) -> np.ndarray:
    """마지막으로 **채택된** 신호로부터 cooldown_sec 이상 떨어진 것만 남김 — detect_breakouts 와 같은 루프."""
    keep, last = [], -10**9
    for i in idx:
        if i - last >= cooldown_sec:
            keep.append(i)
            last = i
    return np.array(keep, dtype=np.int64)


def _pair(v: Any, a: str, b: str) -> tuple[float, float]:
    return (getattr(v, a), getattr(v, b)) if hasattr(v, a) else (v[0], v[1])


def detect_signals(
    day: TickDay, *, breakout_min: int | None = None, value_speed: Any = None, buy_ratio: Any = None,
    trade_strength: Any = None, block_trades: Any = None, daily_breakout: Any = None, value_window: Any = None,
    time_from: str = "09:00:00", time_to: str = "15:30:00", cooldown_sec: int = 300,
    extra_mask: np.ndarray | None = None,
) -> TickEvents:
    """켜진 조건을 전부 AND → 시간 범위 → 쿨다운 → 각 신호의 진입 체결(s 보다 엄격히 뒤 첫 체결).

    value_speed = (w분, ratio) 또는 `.w/.ratio` 를 가진 객체, buy_ratio = (w분, min) 또는 `.w/.min` 객체.
    trade_strength = (w초, min강도%) / `.w/.min`, block_trades = (w초, min_value[, min_count]) / `.w/.min_value/.min_count`,
    value_window = (w분, min_eok) / `.w/.min_eok` — 최근 w분 `(s−w, s]` 체결대금 합 ≥ min_eok 억(c9).
    daily_breakout = (n, level) / `.n/.level` — level = D−1 까지 n일 최고가(`prior_n_high` 로 호출부가 계산).
    extra_mask = 길이 N bool — 분봉·일봉 조건 묶음(`align_filter` 결과)을 틱 조건과 **AND**(쿨다운 전, 최종 신호에 대해 쿨다운).
    """
    if all(c is None for c in (breakout_min, value_speed, buy_ratio, trade_strength, block_trades, daily_breakout, value_window)):
        raise ValueError("틱 조건이 하나도 없음 (breakout_min·value_speed·buy_ratio·trade_strength·block_trades·daily_breakout·value_window 중 하나 필요)")
    grid = build_grid(day)
    hit = time_mask(time_from, time_to)
    if breakout_min is not None:
        hit &= breakout_hits(grid, breakout_min)
    if value_speed is not None:
        w, ratio = _pair(value_speed, "w", "ratio")
        hit &= value_speed_hits(grid, int(w), float(ratio))
    if buy_ratio is not None:
        w, mn = _pair(buy_ratio, "w", "min")
        hit &= buy_ratio_hits(grid, int(w), float(mn))
    if trade_strength is not None:
        w, mn = _pair(trade_strength, "w", "min")
        hit &= trade_strength_hits(grid, int(w), float(mn))
    if block_trades is not None:
        if hasattr(block_trades, "w"):
            w, mv, mc = block_trades.w, block_trades.min_value, getattr(block_trades, "min_count", 1)
        else:
            w, mv, mc = block_trades[0], block_trades[1], (block_trades[2] if len(block_trades) > 2 else 1)
        hit &= block_trades_hits(day, int(w), float(mv), int(mc))
    if daily_breakout is not None:
        _, level = _pair(daily_breakout, "n", "level")
        hit &= daily_breakout_hits(grid, float(level))
    if value_window is not None:
        w, mn = _pair(value_window, "w", "min_eok")
        hit &= value_window_hits(grid, int(w), float(mn))
    if extra_mask is not None:
        hit &= np.asarray(extra_mask, dtype=bool)
    sig = apply_cooldown(np.flatnonzero(hit), int(cooldown_sec))
    j = np.searchsorted(day.sec, sig, side="right")  # s 보다 엄격히 뒤 첫 체결
    has = j < len(day.sec)
    sig, j = sig[has], j[has]
    return TickEvents(
        code=day.code, date=day.date, signal_sec=sig, entry_idx=j,
        entry_sec=np.asarray(day.sec)[j], entry_price=np.asarray(day.prc, dtype=float)[j],
        n_no_entry=int((~has).sum()),
    )


def detect_from_spec(day: TickDay, tick_cfg: Any, daily_high_level: float | None = None,
                     extra_mask: np.ndarray | None = None) -> TickEvents:
    """`spec.tick`(entry_source='catalog') → 신호. tick_cfg 는 duck typing(`.catalog`, `.cooldown_sec`).

    새 조건(trade_strength·block_trades·daily_breakout)은 칸이 없는 옛 명세도 받도록 getattr 로 읽는다.
    daily_breakout 이 켜져 있으면 `daily_high_level`(= `prior_n_high` 결과)을 반드시 줘야 한다 — 틱 하루치엔 일봉이 없다.
    """
    c = tick_cfg.catalog
    db = getattr(c, "daily_breakout", None)
    if db is not None:
        if daily_high_level is None:
            raise ValueError("daily_breakout 조건에는 D−1 까지 n일 최고가(daily_high_level)가 필요함")
        db = (db.n if hasattr(db, "n") else db[0], daily_high_level)
    return detect_signals(
        day, breakout_min=c.breakout_min, value_speed=c.value_speed, buy_ratio=c.buy_ratio,
        trade_strength=getattr(c, "trade_strength", None), block_trades=getattr(c, "block_trades", None), daily_breakout=db,
        value_window=getattr(c, "value_window", None),
        time_from=c.time_from, time_to=c.time_to, cooldown_sec=tick_cfg.cooldown_sec, extra_mask=extra_mask,
    )


def is_gap_open_day(day: TickDay, pct: float = GAP_OPEN_PCT) -> bool:
    """첫 체결가가 전일 종가 대비 +pct% 이상이면 갭시작 — `precursor_master.is_gap_open` 과 같은 규칙(엔진이 제외에 씀)."""
    pc = day.prev_close
    if not pc or not np.isfinite(pc) or pc <= 0 or len(day.prc) == 0:
        return False
    return bool(day.prc[0] / pc - 1 >= pct / 100.0)
