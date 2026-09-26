"""테마·업종 참조 데이터 읽기 — 설계 studio-conditions §3.3·§9. 도메인(`ind_group`)에는 `Reference` dict 로 **주입**한다.

출처 = 소피증권 기준 데이터(카탈로그 `sophie_reference`: `themes.csv`(code,theme)·`sectors.csv`(stock_code,sector)) + 대표 그룹 설정
`kospi-theme-engine/config/theme_group.yaml`. 그룹 배정은 소피증권 `theme_group.apply` 와 같은 규칙을 다시 적은 것이다
(소피증권 앱 코드는 import 하지 않는다 — exe 전용 모듈):
- 그룹에 든 원본 테마는 대표명으로 묶고, 종목은 **먼저 적힌 그룹 하나**에만 속한다(`stock_owner` 예외 우선),
- 그룹에 없는 테마는 독립 테마로 남는다(`exclusive: true` 면 화면에서 뺀다 = 여기서도 뺀다).

**구성은 현재 기준** — 과거 날짜에 그대로 적용된다(결과 경고: `ind_group.GROUP_WARNING_KO`).
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Mapping, Sequence

import yaml

from datahub import catalog
from studio.domain.conditions.ind_group import Reference

GROUP_YAML = Path("kospi-theme-engine") / "config" / "theme_group.yaml"


def _read_csv(path: Path, key: str, val: str) -> list[tuple[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [(r[key].strip(), r[val].strip()) for r in csv.DictReader(f) if r.get(key) and r.get(val)]


def apply_groups(
    members: Mapping[str, Sequence[str]], groups: Mapping[str, Sequence[str]], owner: Mapping[str, str] | None = None,
    exclusive: bool = False,
) -> dict[str, list[str]]:
    """원본 테마 구성 → 표시 테마 구성(소피증권 `theme_group.apply` 와 같은 규칙, 순서·예외 배정 포함)."""
    display = {t: list(c) for t, c in members.items()}
    present = {lab: [c for c in ch if c in members] for lab, ch in groups.items()}
    present = {lab: ch for lab, ch in present.items() if ch}
    if exclusive:
        keep = {c for ch in present.values() for c in ch}
        display = {t: c for t, c in display.items() if t in keep}
    reachable = {lab: {code for ch in children for code in members[ch]} for lab, children in present.items()}
    owner = {c: lab for c, lab in (owner or {}).items() if c in reachable.get(lab, ())}  # 못 가져갈 지정은 무시
    claimed: set[str] = set()
    for lab, children in present.items():
        union: list[str] = []
        for child in children:
            for code in members[child]:
                if owner.get(code, lab) != lab or code in union or code in claimed:
                    continue
                union.append(code)
        for child in children:
            display.pop(child, None)  # 자식은 흡수 — 비어도 독립 테마로 되살리지 않는다
        if union:
            claimed.update(union)
            display[lab] = union
    return display


def load_reference(root: Path | None = None) -> Reference:
    """파일에서 읽어 `Reference` 를 만든다. 파일이 없으면 FileNotFoundError(조용히 빈 값으로 통과시키지 않음)."""
    root = Path(root) if root else catalog.root()
    ref_dir = root / catalog.dataset("sophie_reference").path
    members: dict[str, list[str]] = {}
    for code, theme in _read_csv(ref_dir / "themes.csv", "code", "theme"):
        members.setdefault(theme, []).append(code)
    raw = yaml.safe_load((root / GROUP_YAML).read_text(encoding="utf-8")) or {} if (root / GROUP_YAML).is_file() else {}
    groups = {str(k): [str(c) for c in (v or [])] for k, v in (raw.get("groups") or {}).items() if not str(k).startswith("_")}
    owner = {str(c): str(lab) for c, lab in (raw.get("stock_owner") or {}).items()}
    theme_members = apply_groups(members, groups, owner, bool(raw.get("exclusive", False)))
    sector_of = dict(_read_csv(ref_dir / "sectors.csv", "stock_code", "sector"))
    stamp = max(p.stat().st_mtime for p in (ref_dir / "themes.csv", ref_dir / "sectors.csv"))
    return Reference(theme_members=theme_members, sector_of=sector_of, as_of=dt.date.fromtimestamp(stamp).isoformat())
