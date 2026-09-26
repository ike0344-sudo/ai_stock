"""검증 — 분할·워크포워드·그리드·선택·판정 (설계서 §3.8). 순수 계산만.

원칙
  · **후보 선택은 IS(학습) 구간 점수로만** 한다. OOS·홀드아웃은 고른 뒤에 보는 용도다 — `select_best` 는 IS 값만 받는다.
  · 분할은 **거래일 수** 기준(달력일 아님). 거래일 목록은 호출자가 넘긴다(허브 달력 — 휴장일 제외).
  · 조합마다 최적화 구간 전체를 **한 번** 돌리고 그 평가금 곡선을 구간별로 잘라 IS/OOS/폴드 점수를 낸다.
    구간 경계에 걸친 보유는 그대로 이어진다(구간마다 새로 시작하는 방식과 숫자가 다르다).
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Sequence

import numpy as np

from .metrics import equity_stats, trade_stats

OBJECTIVE_KEY = {
    "sharpe": "sharpe", "cagr": "cagr_pct", "calmar": "calmar",
    "profit_factor": "profit_factor", "expectancy": "expectancy_pct",
}
# 낮을수록 좋은 지표 — 사전 판정 기준에서 "이하"로 본다
LOWER_IS_BETTER = {"max_drawdown_pct", "volatility_pct", "mdd_duration_bars", "max_consec_losses", "turnover",
                   "commission_total", "tax_total", "slippage_total", "avg_holding_bars"}
MAX_COMBOS = 5_000
WARN_COMBOS = 500


class ValidationConfigError(ValueError):
    """분할·워크포워드·그리드 설정이 잘못됨 (API: 422 SPEC_INVALID)."""


class GridTooLargeError(ValidationConfigError):
    """조합 수가 한도 초과 (API: 422 GRID_TOO_LARGE)."""

    def __init__(self, n: int, limit: int = MAX_COMBOS) -> None:
        super().__init__(f"그리드 조합 {n:,}개가 한도 {limit:,}개를 넘는다")
        self.n, self.limit = n, limit


# ---------------------------------------------------------------------------- 설정


@dataclass(frozen=True)
class OptimizeConfig:
    objective: str = "sharpe"
    min_trades: int = 30
    train_pct: float = 70.0  # 홀드아웃을 뺀 최적화 구간 중 IS 비율(거래일 수 기준, 나머지 = OOS)
    split_date: date | None = None  # 주면 train_pct 대신 "이 날짜까지 = IS"
    holdout_pct: float = 20.0  # 마지막 N% 거래일 — 최적화·선택·OOS 어디에도 안 쓴다
    vary: tuple[str, ...] | None = None  # 그리드로 훑을 변수(없으면 min·max·step 이 다 있는 변수 전부)
    max_combos: int = MAX_COMBOS
    criteria: Mapping[str, float] = field(default_factory=dict)  # 사전 판정 기준: 지표 이름 → 통과 기준값

    def __post_init__(self) -> None:
        if self.objective not in OBJECTIVE_KEY:
            raise ValidationConfigError(f"objective: {self.objective!r} (가능: {sorted(OBJECTIVE_KEY)})")
        if not 0 <= self.holdout_pct <= 50:
            raise ValidationConfigError("holdout_pct 는 0~50")
        if not 1 <= self.train_pct <= 99:
            raise ValidationConfigError("train_pct 는 1~99")
        if self.min_trades < 1:
            raise ValidationConfigError("min_trades >= 1")

    @classmethod
    def from_validation(cls, v: Any, **kw: Any) -> "OptimizeConfig":
        """Spec.validation(duck: holdout_pct·objective·min_trades·criteria) 에서 만든다. None 이면 기본값."""
        if v is None:
            return cls(**kw)
        return cls(objective=v.objective, min_trades=v.min_trades, holdout_pct=v.holdout_pct,
                   criteria=dict(v.criteria), **kw)


@dataclass(frozen=True)
class WalkForwardConfig:
    train_days: int
    test_days: int
    step_days: int | None = None  # None = test_days (검증 구간이 겹치지 않게 이어짐)
    mode: str = "rolling"  # rolling(학습 창이 같이 이동) | anchored(학습 시작 고정, 누적)
    base: OptimizeConfig = field(default_factory=OptimizeConfig)

    def __post_init__(self) -> None:
        if self.mode not in ("rolling", "anchored"):
            raise ValidationConfigError(f"mode: {self.mode!r} (rolling|anchored)")
        if self.train_days < 1 or self.test_days < 1:
            raise ValidationConfigError("train_days·test_days >= 1")
        if self.step_days is not None and self.step_days < self.test_days:
            raise ValidationConfigError("step_days 는 test_days 이상이어야 한다(검증 구간이 겹치면 이은 곡선이 이중 집계)")

    @property
    def step(self) -> int:
        return self.step_days or self.test_days


# ---------------------------------------------------------------------------- 분할


@dataclass(frozen=True)
class Segments:
    opt_days: list[date]  # 최적화 구간(IS+OOS) = 전체에서 홀드아웃을 뺀 앞부분
    is_days: list[date]
    oos_days: list[date]
    holdout_days: list[date]

    @property
    def n_is(self) -> int:
        return len(self.is_days)


def split_days(days: Sequence[date], holdout_pct: float = 20.0, train_pct: float = 70.0,
               split_date: date | None = None) -> Segments:
    """거래일 목록 → [IS | OOS | 홀드아웃]. 경계는 **거래일 수의 내림**(홀드아웃 floor(n×%), IS floor(opt×%)).

    홀드아웃은 뒤에서부터 잘라 최적화 구간에서 통째로 뺀다 — 최적화는 홀드아웃 날짜의 데이터를 보지 않는다.
    """
    days = list(days)
    if list(days) != sorted(set(days)):
        raise ValidationConfigError("거래일 목록이 정렬·유일하지 않다")
    n = len(days)
    n_hold = int(math.floor(n * holdout_pct / 100 + 1e-9))
    opt = days[: n - n_hold]
    hold = days[n - n_hold:]
    if len(opt) < 2:
        raise ValidationConfigError(f"거래일 {n}개로는 IS/OOS 를 나눌 수 없다")
    if split_date is not None:
        k = sum(1 for d in opt if d <= split_date)
    else:
        k = max(1, int(math.floor(len(opt) * train_pct / 100 + 1e-9)))
    if not 1 <= k <= len(opt) - 1:
        raise ValidationConfigError("IS 와 OOS 가 각각 거래일 1개 이상이어야 한다(분할 날짜·비율 확인)")
    return Segments(opt_days=opt, is_days=opt[:k], oos_days=opt[k:], holdout_days=hold)


@dataclass(frozen=True)
class Fold:
    index: int
    train: tuple[int, int]  # days 리스트 위치 [시작, 끝] (양끝 포함)
    test: tuple[int, int]


def walkforward_folds(n_days: int, train_days: int, test_days: int, step_days: int | None = None,
                      mode: str = "rolling") -> list[Fold]:
    """최적화 구간 거래일 n_days 개를 폴드로 — 위치 기반(호출자가 days[i] 로 날짜를 얻는다).

    rolling : 학습 [s, s+train) → 검증 [s+train, s+train+test), s 가 step 씩 이동
    anchored: 학습이 항상 0 부터([0, s+train)) — 검증 구간은 같다
    """
    step = step_days or test_days
    if mode not in ("rolling", "anchored"):
        raise ValidationConfigError(f"mode: {mode!r}")
    if step < test_days:
        raise ValidationConfigError("step_days 는 test_days 이상")
    folds: list[Fold] = []
    s = 0
    while s + train_days + test_days <= n_days:
        t0 = s + train_days
        folds.append(Fold(len(folds), (0 if mode == "anchored" else s, t0 - 1), (t0, t0 + test_days - 1)))
        s += step
    if not folds:
        raise ValidationConfigError(
            f"거래일 {n_days}개로는 폴드가 하나도 안 나온다(학습 {train_days} + 검증 {test_days} = {train_days + test_days} 필요)")
    return folds


# ---------------------------------------------------------------------------- 그리드


def axis_values(pr: Any) -> list[float | int]:
    """ParamRange(duck: default·min·max·step) → 훑을 값 목록. min·max·step 이 하나라도 없으면 default 하나(고정)."""
    if pr.min is None or pr.max is None or pr.step is None:
        return [_clean(pr.default, pr)]
    n = int(math.floor((pr.max - pr.min) / pr.step + 1e-9)) + 1
    return [_clean(pr.min + i * pr.step, pr) for i in range(n)]


def _clean(v: float, pr: Any) -> float | int:
    """정수 격자(min·step·default 가 다 정수)면 int, 아니면 부동소수 잡음을 줄인 float."""
    if all(x is None or float(x).is_integer() for x in (pr.min, pr.step, pr.default)):
        return int(round(v))
    return round(float(v), 10)


def grid_axes(params: Mapping[str, Any], vary: Sequence[str] | None = None) -> dict[str, list]:
    axes: dict[str, list] = {}
    for name, pr in params.items():
        axes[name] = axis_values(pr) if (vary is None or name in vary) else [_clean(pr.default, pr)]
    unknown = set(vary or ()) - set(params)
    if unknown:
        raise ValidationConfigError(f"vary 에 params 에 없는 변수: {sorted(unknown)}")
    return axes


def count_combinations(params: Mapping[str, Any], vary: Sequence[str] | None = None) -> int:
    """조합 수 — 만들지 않고 센다(화면이 5,000 초과를 미리 비활성으로 보여주는 데 쓴다)."""
    return math.prod(len(v) for v in grid_axes(params, vary).values()) if params else 0


def combinations(axes: Mapping[str, list], max_combos: int = MAX_COMBOS) -> tuple[list[dict], list[tuple[int, ...]]]:
    """(값 dict 목록, 축 위치 튜플 목록) — 순서 고정. 한도 초과는 GridTooLargeError."""
    n = math.prod(len(v) for v in axes.values()) if axes else 0
    if n > max_combos:
        raise GridTooLargeError(n, max_combos)
    names = list(axes)
    idx = list(itertools.product(*[range(len(axes[k])) for k in names]))
    return [{k: axes[k][i] for k, i in zip(names, t)} for t in idx], idx


# ---------------------------------------------------------------------------- 구간 점수


@dataclass
class TradeArrays:
    """한 조합의 거래 요약 — 청산 봉 위치 순(같으면 원래 순서)."""

    exit_idx: np.ndarray  # 청산 봉의 위치(일 index)
    net_pnl: np.ndarray
    net_pct: np.ndarray


def window_metrics(equity: np.ndarray, i0: int, i1: int, initial_capital: float, trades: TradeArrays) -> dict:
    """봉 위치 [i0, i1] 구간의 지표. 구간 직전 평가금이 시작 자본이다. 표준 지표와 같은 정의(metrics.equity_stats·trade_stats)."""
    e = equity[i0: i1 + 1]
    base = equity[i0 - 1] if i0 > 0 else initial_capital
    m = trades.exit_idx
    sel = (m >= i0) & (m <= i1)
    out = equity_stats(e, base)
    out.update(trade_stats(trades.net_pnl[sel], trades.net_pct[sel]))
    return out


def objective_value(metrics: Mapping[str, Any], objective: str, min_trades: int) -> float | None:
    """목표 지표 값 — 거래 수가 min_trades 미만이거나 계산 불가면 None(선택 후보에서 빠진다)."""
    if metrics["num_trades"] < min_trades:
        return None
    v = metrics[OBJECTIVE_KEY[objective]]
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def select_best(is_values: Sequence[float | None]) -> int | None:
    """IS 점수만으로 최고 조합 위치. 동점은 앞 조합(결정적). 후보가 없으면 None.
    시그니처가 IS 값만 받는 것이 '선택은 IS 로만' 규칙의 구조적 보장이다."""
    best, best_v = None, -math.inf
    for i, v in enumerate(is_values):
        if v is not None and v > best_v:
            best, best_v = i, v
    return best


def neighbor_stability(idx: Sequence[tuple[int, ...]], values: Sequence[float | None], best: int,
                       threshold: float = 0.5) -> dict:
    """한 칸 옆(한 변수만 ±1 칸) 조합 목표값의 중앙값 ÷ 최고값. < threshold 이면 성과 절벽(과최적화 의심) 경고.

    · 최고값이 0 이하면 비율이 뜻이 없다 → 경고.
    · 이웃 중 목표값이 None(최소 거래 미만·무효)인 것은 중앙값에서 빼되 개수를 함께 돌려준다(빼서 안정해 보이는 걸 알 수 있게).
    """
    pos = {t: i for i, t in enumerate(idx)}
    b = idx[best]
    neigh = []
    for ax in range(len(b)):
        for d in (-1, 1):
            t = b[:ax] + (b[ax] + d,) + b[ax + 1:]
            if t in pos:
                neigh.append(pos[t])
    best_v = values[best]
    vals = [values[i] for i in neigh if values[i] is not None]
    n_invalid = len(neigh) - len(vals)
    out: dict = {"best": best_v, "n_neighbors": len(neigh), "n_invalid": n_invalid,
                 "median": float(np.median(vals)) if vals else None, "ratio": None, "warn": False, "reason": None}
    if not neigh:
        out["reason"] = "이웃 조합이 없다(변수 축이 하나뿐이고 값이 하나) — 안정성 판단 불가"
    elif best_v is None or best_v <= 0:
        out.update(warn=True, reason="최고 목표값이 0 이하라 비율이 뜻이 없다")
    elif not vals:
        out.update(warn=True, reason="이웃이 전부 최소 거래 수 미만·무효 — 성과 절벽")
    else:
        out["ratio"] = out["median"] / best_v
        if out["ratio"] < threshold:
            out.update(warn=True, reason=f"이웃 중앙값이 최고값의 {out['ratio']:.2f}배(<{threshold}) — 성과 절벽, 과최적화 의심")
        elif n_invalid:
            out["reason"] = f"이웃 {n_invalid}개는 최소 거래 미만이라 중앙값에서 뺐다"
    return out


# ---------------------------------------------------------------------------- 사전 판정 기준


def evaluate_criteria(criteria: Mapping[str, float], metrics: Mapping[str, Any]) -> list[dict]:
    """지표 이름 → 통과 기준값. 높을수록 좋은 지표는 '이상', 낮을수록 좋은 지표(MDD 등)는 '이하'.

    기준은 실행 **전**에 Spec.validation.criteria 로 입력한다 — 결과와 함께 spec.json 에 저장되고 결과에서 고치지 않는다."""
    out = []
    for name, th in criteria.items():
        v = metrics.get(name)
        direction = "max" if name in LOWER_IS_BETTER else "min"
        if v is None or (isinstance(v, float) and math.isnan(v)):
            passed, note = False, "지표 없음"
        else:
            passed = bool(v <= th if direction == "max" else v >= th)  # 지표가 numpy 값이면 np.bool_ — summary.json 저장이 깨진다(실데이터에서 발견)
            note = None
        out.append({"metric": name, "threshold": th, "direction": direction, "value": v, "passed": passed,
                    "note": note})
    return out


# ---------------------------------------------------------------------------- 워크포워드 이은 곡선·WFE


def stitch_equity(windows: Sequence[tuple[np.ndarray, int, int]], initial_capital: float) -> np.ndarray:
    """검증 구간만 이은 곡선. windows = [(그 폴드에서 고른 조합의 평가금 배열, i0, i1), ...] (시간순).
    각 구간의 일별 수익률만 이어 붙여 initial_capital 에서 다시 복리 — 구간 사이(학습 구간)는 건너뛴다."""
    out: list[np.ndarray] = []
    cap = float(initial_capital)
    for e, i0, i1 in windows:
        base = e[i0 - 1] if i0 > 0 else initial_capital
        seg = cap * (e[i0: i1 + 1] / base)
        out.append(seg)
        cap = float(seg[-1])
    return np.concatenate(out)


def walk_forward_efficiency(is_cagr_pct: Sequence[float], oos_cagr_pct: float) -> float | None:
    """WFE = 이은 검증 곡선의 연환산 수익률 ÷ 폴드별 IS 연환산 수익률 평균. IS 평균이 0 이하면 None."""
    if not len(is_cagr_pct):
        return None
    m = float(np.mean(is_cagr_pct))
    return oos_cagr_pct / m if m > 0 else None


def params_drift(fold_params: Sequence[Mapping[str, Any]]) -> dict[str, dict]:
    """폴드마다 고른 변수 값이 얼마나 흔들렸나 — 값이 계속 바뀌면 '최적'이 데이터에 끌려다닌다는 신호."""
    names = list(fold_params[0]) if fold_params else []
    out = {}
    for k in names:
        vals = [p[k] for p in fold_params]
        out[k] = {"values": vals, "n_distinct": len(set(vals)), "min": min(vals), "max": max(vals)}
    return out
