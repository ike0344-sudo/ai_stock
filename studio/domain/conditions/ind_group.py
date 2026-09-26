"""테마·업종 지표 — 설계서 studio-conditions §3.3 「테마·업종·시장」. 순수 계산(numpy/pandas)만 — 파일을 읽지 않는다.

## 참조 데이터는 주입받는다 (§9: domain 은 IO 금지)
구성(테마→종목, 종목→업종)은 `studio.infrastructure.reference_data` 가 파일에서 읽어 `Reference` 로 만든다. 전달 경로 두 가지:
1. Panel 에 `reference` 속성으로 달기(권장 — 실행마다 명시),
2. `set_default_reference(ref)` — 앱 시작 때 한 번(Panel 에 못 다는 호출부용). Panel 속성이 우선.
둘 다 없으면 `ValueError`("참조 데이터가 없음") — 조용히 빈 값으로 통과시키지 않는다.

## ⚠ 구성은 "현재 기준" (결과에 경고 문구를 붙일 것)
소피증권 테마 그룹·업종은 **지금 시점의 구성**이다. 5년 전 그날의 구성이 아니다 → 과거 구간에서 "그 테마 소속"이라는 정보가
그날엔 몰랐을 수 있다(후견 편향). 조건이 이 지표를 쓰면 `warnings_for(names)` 가 돌려주는 문구를 결과에 그대로 싣는다.

## 정의
- 한 종목이 여러 그룹에 속하면(그룹 밖 독립 테마 등) **가장 좋은 그룹 값**을 쓴다(등락·대금·개수는 최대, 순위는 최소).
- 그룹 통계는 그날 값이 있는 구성 종목이 `min_members` 개 이상일 때만(소피증권 게이트 `theme.min_stocks` 와 같은 취지, 기본 3).
- 등락률 = (종가 ÷ 전일 종가 − 1)×100 (Panel.prev_close). 일봉 표 전용 — 분봉에서는 `tf=daily_prev`(D−1)로 쓴다.
- `theme_top_count` 는 사용자의 테마 점수 1순위 기준("대금 상위 m 에 그 테마 종목이 **몇 개**")과 같은 셈법이다 —
  단 소피증권은 장중 실시간 대금 순위, 여기는 **그날 종가 기준 대금 순위**(일봉)라 장중 값과 다를 수 있다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from .catalog import CROSS_SECTIONAL, IndicatorDef, ParamDef, register_indicators
from .intraday import is_intraday

Frame = pd.DataFrame

GROUP_WARNING_KO = (
    "테마·업종 구성은 현재 기준입니다 — 과거 구간에서도 오늘의 소속을 그대로 씁니다(그날엔 몰랐을 수 있는 정보). "
    "결과는 실제보다 좋게 나올 수 있습니다."
)


@dataclass(frozen=True)
class Reference:
    """`theme_members`: 표시 테마(그룹)명 → 종목코드들. `sector_of`: 종목코드 → 업종명. `as_of`: 읽은 시각/기준(표시용)."""
    theme_members: Mapping[str, Sequence[str]] = field(default_factory=dict)
    sector_of: Mapping[str, str] = field(default_factory=dict)
    as_of: str = ""


_default: Reference | None = None


def set_default_reference(ref: Reference | None) -> None:
    global _default
    _default = ref


def get_reference(panel: Any) -> Reference:
    ref = getattr(panel, "reference", None) or _default
    if ref is None:
        raise ValueError("테마·업종 참조 데이터가 없음 — Panel.reference 를 달거나 set_default_reference() 로 주입하세요")
    return ref


# ---------------------------------------------------------------- 그룹 통계
def _members(codes: Sequence[str], groups: Mapping[str, Iterable[str]]) -> list[tuple[str, np.ndarray]]:
    pos = {c: i for i, c in enumerate(codes)}
    out = []
    for g, cs in groups.items():
        idx = np.array(sorted({pos[c] for c in cs if c in pos}), dtype=np.int64)
        if len(idx):
            out.append((g, idx))
    return out


def _day_change(panel: Any) -> np.ndarray:
    return ((panel.close / panel.prev_close - 1) * 100).to_numpy(dtype=float)


def _group_table(x: np.ndarray, members: list[tuple[str, np.ndarray]], min_members: int, how: str) -> np.ndarray:
    """(T × 그룹 수) — how = 'mean' | 'sum'. 값 있는 구성 종목이 min_members 미만인 날은 NaN."""
    out = np.full((x.shape[0], len(members)), np.nan)
    for k, (_, idx) in enumerate(members):
        sub = x[:, idx]
        ok = np.isfinite(sub)
        cnt = ok.sum(axis=1)
        s = np.where(ok, sub, 0.0).sum(axis=1)
        val = s / np.maximum(cnt, 1) if how == "mean" else s
        out[:, k] = np.where(cnt >= min_members, val, np.nan)
    return out


def _to_stocks(shape: tuple[int, int], members: list[tuple[str, np.ndarray]], g: np.ndarray, best: str) -> np.ndarray:
    """그룹 값(T × G) → 종목 값(T × C). 여러 그룹이면 best('max'|'min') — NaN 은 무시."""
    out = np.full(shape, np.nan)
    f = np.fmax if best == "max" else np.fmin
    for k, (_, idx) in enumerate(members):
        out[:, idx] = f(out[:, idx], g[:, [k]])
    return out


def _frame(panel: Any, a: np.ndarray) -> Frame:
    return pd.DataFrame(a, index=panel.close.index, columns=panel.close.columns)


def _rank_rows(a: np.ndarray) -> np.ndarray:
    return pd.DataFrame(a).rank(axis=1, ascending=False, method="min").to_numpy()


def _need_daily(panel: Any, name: str) -> None:
    if is_intraday(panel):
        raise ValueError(f"'{name}' 은 일봉 표 지표 — 분봉에서는 시간 단위를 daily_prev(D−1)로 쓰세요")


def _by(panel: Any, by: str) -> np.ndarray:
    return _day_change(panel) if by == "change" else panel.value.to_numpy(dtype=float)


def _group_indicator(panel: Any, groups: Mapping[str, Iterable[str]], kind: str, p: dict[str, Any]) -> Frame:
    codes = list(panel.close.columns)
    members = _members(codes, groups)
    shape = panel.close.shape
    mm = int(p.get("min_members", 3))
    chg = _day_change(panel)
    val = panel.value.to_numpy(dtype=float)
    if kind == "change":
        return _frame(panel, _to_stocks(shape, members, _group_table(chg, members, mm, "mean"), "max"))
    if kind == "value":
        return _frame(panel, _to_stocks(shape, members, _group_table(val, members, mm, "sum"), "max"))
    if kind == "rank":  # 그룹끼리 순위 — 그룹 값(등락 평균 또는 대금 합)이 없는 날은 순위 없음
        g = _group_table(chg if p["by"] == "change" else val, members, mm, "mean" if p["by"] == "change" else "sum")
        return _frame(panel, _to_stocks(shape, members, _rank_rows(g), "min"))
    if kind == "top_count":  # 그날 대금 상위 m 안 + 등락률 ≥ min_change_pct 인 구성 종목 수 (소피증권 value_rank 개수 셈법)
        top = (_rank_rows(val) <= int(p["m"])) & (chg >= float(p["min_change_pct"]))
        cnt = _group_table(top.astype(float), members, 0, "sum")
        have = _group_table(np.where(np.isfinite(chg) & np.isfinite(val), 1.0, np.nan), members, mm, "sum")
        return _frame(panel, _to_stocks(shape, members, np.where(np.isfinite(have), cnt, np.nan), "max"))
    if kind == "rank_in":  # 그룹 안 종목 순위
        x = _by(panel, p["by"])
        out = np.full(shape, np.nan)
        for _, idx in members:
            sub = x[:, idx]
            r = _rank_rows(sub).copy()
            r[np.isfinite(sub).sum(axis=1) < mm] = np.nan
            out[:, idx] = np.fmin(out[:, idx], r)
        return _frame(panel, out)
    raise NotImplementedError(kind)  # pragma: no cover


def _theme(kind: str):
    def fn(panel: Any, p: dict[str, Any]) -> Frame:
        _need_daily(panel, "theme_" + kind)
        return _group_indicator(panel, get_reference(panel).theme_members, kind, p)
    return fn


def _sector(kind: str):
    def fn(panel: Any, p: dict[str, Any]) -> Frame:
        _need_daily(panel, "sector_" + kind)
        by_sector: dict[str, list[str]] = {}
        for c, s in get_reference(panel).sector_of.items():
            by_sector.setdefault(s, []).append(c)
        return _group_indicator(panel, by_sector, kind, p)
    return fn


def _rank_in_theme(panel: Any, p: dict[str, Any]) -> Frame:
    _need_daily(panel, "rank_in_theme")
    return _group_indicator(panel, get_reference(panel).theme_members, "rank_in", p)


_MIN = ParamDef("min_members", "int", 3, 1, 50, label_ko="최소 종목 수")
_BY = ParamDef("by", "enum", "value", choices=("value", "change"), label_ko="기준(대금/등락률)")
_DAILY = ("daily_single", "daily_portfolio")


def _d(name: str, label: str, desc: str, params: tuple, definition: str, example: str, vb: bool = False) -> IndicatorDef:
    return IndicatorDef(
        name, label, desc + " (구성은 현재 기준)", params, _DAILY, "t 종가 · 구성은 현재",
        category="group", definition=definition, example=example, volume_based=vb,
    )


DEFS = (
    _d("theme_change", "테마 평균 등락률(%)", "종목이 속한 소피증권 테마 그룹 구성 종목의 그날 평균 등락률(여러 그룹이면 가장 높은 값)", (_MIN,),
       "mean_{j∈그룹}((C_j ÷ 전일 C_j − 1)×100)", "내 테마 평균 등락률 ≥ 3%"),
    _d("theme_value", "테마 거래대금 합", "종목이 속한 테마 그룹 구성 종목의 그날 거래대금 합(여러 그룹이면 가장 큰 값)", (_MIN,),
       "Σ_{j∈그룹} 대금_j", "내 테마 거래대금 합 ≥ 1000억", True),
    _d("theme_rank", "테마 순위", "테마 그룹끼리의 그날 순위(1=최고, 여러 그룹이면 가장 좋은 순위)", (_BY, _MIN),
       "rank_desc(그룹 대금 합 또는 평균 등락률)", "내 테마가 대금 순위 3위 이내", True),
    _d("theme_top_count", "테마 안 대금 상위 종목 수",
       "그날 전체 대금 순위 m 이내이고 등락률 ≥ min_change_pct 인 테마 구성 종목 수(여러 그룹이면 가장 큰 값)",
       (ParamDef("m", "int", 20, 1, 500, label_ko="상위 순위"),
        ParamDef("min_change_pct", "float", 0.0, -30.0, 30.0, label_ko="최소 등락률(%)"), _MIN),
       "Σ_{j∈그룹}[ 대금순위_j ≤ m and 등락률_j ≥ 기준 ]", "내 테마에서 대금 상위 20위가 3개 이상", True),
    _d("rank_in_theme", "테마 안 순위", "테마 그룹 안에서 이 종목의 그날 순위(1=최고, 여러 그룹이면 가장 좋은 순위)", (_BY, _MIN),
       "rank_desc_{그룹 안}(대금 또는 등락률)", "내 테마 안에서 대금 1위(대장)", True),
    _d("sector_change", "업종 평균 등락률(%)", "종목이 속한 업종 구성 종목의 그날 평균 등락률", (_MIN,),
       "mean_{j∈업종}((C_j ÷ 전일 C_j − 1)×100)", "내 업종 평균 등락률 ≥ 2%"),
    _d("sector_rank", "업종 순위", "업종끼리의 그날 순위(1=최고)", (_BY, _MIN),
       "rank_desc(업종 대금 합 또는 평균 등락률)", "내 업종이 대금 순위 3위 이내", True),
)
COMPUTE = {
    "theme_change": _theme("change"), "theme_value": _theme("value"), "theme_rank": _theme("rank"),
    "theme_top_count": _theme("top_count"), "rank_in_theme": _rank_in_theme,
    "sector_change": _sector("change"), "sector_rank": _sector("rank"),
}
GROUP_INDICATORS = frozenset(COMPUTE)
CROSS_SECTIONAL.update(COMPUTE)
register_indicators(DEFS, COMPUTE)


def warnings_for(names: Iterable[str]) -> list[str]:
    """쓰인 지표 이름들 중 현재 구성 기준인 것이 있으면 결과에 붙일 경고 문구(없으면 빈 목록)."""
    return [GROUP_WARNING_KO] if any(n in GROUP_INDICATORS for n in names) else []
