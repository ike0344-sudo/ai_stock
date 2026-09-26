"""대표 그룹이 겹치는 종목을 뽑는다 — 읽기 전용. 라이브 설정은 건드리지 않는다.

    python tools/theme_cross_check.py            # 거래대금 상위 129종목만(기본)
    python tools/theme_cross_check.py --all      # 전 종목
    python tools/theme_cross_check.py --top=300

분류기(사람이 승인하는 제안)의 **결정론적 절반**이다. 어떤 종목이 둘 이상의 대표 그룹에
걸렸고, 지금 YAML 나열 순서가 그중 어디를 골랐는지까지만 계산한다. "어디로 보내야 하는가"는
사람(또는 LLM)이 채우는 칸으로 비워 둔다 — 그 판단을 코드가 자동으로 확정하면 점수가
말없이 틀어지고, 그 점수는 실거래 판단에 쓰인다.

app/reference/theme_group.apply() 의 배정 규칙을 그대로 따라 계산한다. 그쪽을 import 하지
않고 다시 쓴 이유는 이 스크립트가 kospi-theme-engine 밖에 있고(라이브 앱과 섞이지 않게),
필요한 건 순서 배정 한 줄뿐이라서다. 규칙이 바뀌면 여기도 같이 고쳐야 한다.

주의: `stock_owner` 는 **순서가 이미 같은 답을 내는 경우에도** 적혀 있을 수 있다(무효 예외).
그 구분을 owner 칸에 active / no-op 로 찍는다.
"""
import argparse
import csv
import sys
from collections import OrderedDict
from pathlib import Path

import yaml

ENGINE = Path(__file__).resolve().parent.parent / "kospi-theme-engine"
GROUP_YAML = ENGINE / "config" / "theme_group.yaml"
THEMES_CSV = ENGINE / "data" / "reference" / "themes.csv"
UNIVERSE_CSV = ENGINE / "data" / "reference" / "universe.csv"
RANKED_CSV = ENGINE / "data" / "reference" / "ranked.csv"


def load_yaml_groups() -> tuple[OrderedDict, dict[str, str]]:
    """(그룹 -> 자식테마들, 종목코드 -> 지정그룹). 나열 순서 = 우선순위이므로 순서를 보존한다."""
    raw = yaml.safe_load(GROUP_YAML.read_text(encoding="utf-8")) or {}
    groups = OrderedDict(
        (str(label), [str(c) for c in (children or [])])
        for label, children in (raw.get("groups") or {}).items()
        if not str(label).startswith("_")
    )
    owner = {str(c): str(lab) for c, lab in (raw.get("stock_owner") or {}).items()}
    return groups, owner


def read_csv_col(path: Path, *cols: str) -> list[tuple[str, ...]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [tuple(r[c] for c in cols) for r in csv.DictReader(fh)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=129, help="거래대금 상위 N종목만 본다")
    ap.add_argument("--all", action="store_true", help="전 종목")
    args = ap.parse_args()

    groups, owner = load_yaml_groups()
    names = dict(read_csv_col(UNIVERSE_CSV, "code", "name"))
    members: dict[str, list[str]] = {}
    for code, theme in read_csv_col(THEMES_CSV, "code", "theme"):
        members.setdefault(theme, []).append(code)

    # 종목 -> 걸린 그룹들(YAML 순서 유지). 같은 그룹의 자식 여러 개에 걸려도 한 번만 센다.
    candidates: dict[str, list[str]] = {}
    for label, children in groups.items():
        for child in children:
            for code in members.get(child, ()):
                slot = candidates.setdefault(code, [])
                if label not in slot:
                    slot.append(label)

    scope = None
    if not args.all:
        scope = [c for (c,) in read_csv_col(RANKED_CSV, "code")][: args.top]

    rows = []
    for code, cands in candidates.items():
        if len(cands) < 2:
            continue
        if scope is not None and code not in scope:
            continue
        by_order = cands[0]                       # YAML 에서 가장 먼저 나온 그룹이 가져간다
        want = owner.get(code)
        if want is None:
            assigned, owner_state = by_order, ""
        elif want not in cands:
            # 지정한 그룹의 원본 테마에 이 종목이 없다 — 앱도 무시하고 순서대로 배정한다
            assigned, owner_state = by_order, f"unreachable({want})"
        else:
            assigned = want
            owner_state = "no-op" if want == by_order else "active"
        rank = scope.index(code) + 1 if scope is not None and code in scope else 0
        rows.append((rank, code, names.get(code, code), assigned, by_order, owner_state, cands))

    rows.sort(key=lambda r: (r[0] or 10**6, r[1]))
    w = csv.writer(sys.stdout, lineterminator="\n")
    w.writerow(["tv_rank", "code", "name", "assigned_now", "by_order",
                "owner", "candidates", "proposed", "reason"])
    for rank, code, name, assigned, by_order, owner_state, cands in rows:
        w.writerow([rank or "", code, name, assigned, by_order, owner_state,
                    " | ".join(cands), "", ""])

    scope_label = "전 종목" if args.all else f"거래대금 상위 {args.top}"
    dead = sum(1 for r in rows if r[5] in ("no-op",) or r[5].startswith("unreachable"))
    print(f"# {scope_label} 중 둘 이상 그룹에 걸린 종목 {len(rows)}개 "
          f"(그중 stock_owner 가 무효인 것 {dead}개)", file=sys.stderr)


if __name__ == "__main__":
    main()
