"""테마·업종 참조 데이터 읽기(c4) — 소피증권 대표 그룹 배정 규칙 재현 · 파일 없음은 오류."""
import pytest

from studio.infrastructure.reference_data import apply_groups, load_reference

MEMBERS = {"반도체": ["1", "2", "3"], "메모리": ["1", "4"], "2차전지": ["5", "6"], "독립": ["7"]}


def test_first_group_claims_shared_stock_and_children_are_absorbed():
    d = apply_groups(MEMBERS, {"IT": ["메모리", "반도체"], "배터리": ["2차전지"]})
    assert d["IT"] == ["1", "4", "2", "3"]      # 자식 순서대로 합집합(중복 제거)
    assert "반도체" not in d and "메모리" not in d and d["독립"] == ["7"]  # 그룹 밖 테마는 독립으로 남음


def test_stock_owner_overrides_order_and_exclusive_drops_ungrouped():
    d = apply_groups(MEMBERS, {"A": ["반도체"], "B": ["메모리"]}, owner={"1": "B"}, exclusive=True)
    assert d == {"A": ["2", "3"], "B": ["1", "4"]}  # 1번은 지정한 B 로, 독립·2차전지는 화면 제외
    # 지정한 그룹의 테마에 없는 종목 지정은 무시(순서대로)
    assert apply_groups(MEMBERS, {"A": ["반도체"], "B": ["메모리"]}, owner={"5": "B"})["A"] == ["1", "2", "3"]


def test_unknown_child_theme_ignored():
    assert apply_groups(MEMBERS, {"A": ["없는테마", "반도체"]})["A"] == ["1", "2", "3"]


def test_load_reference_from_files(tmp_path, monkeypatch):
    ref = tmp_path / "kospi-theme-engine" / "data" / "reference"
    ref.mkdir(parents=True)
    (ref / "themes.csv").write_text("code,theme\n000001,반도체\n000002,반도체\n000001,메모리\n000009,독립\n", encoding="utf-8-sig")
    (ref / "sectors.csv").write_text("stock_code,sector\n000001,전기전자\n000009,제약\n", encoding="utf-8-sig")
    cfg = tmp_path / "kospi-theme-engine" / "config"
    cfg.mkdir()
    (cfg / "theme_group.yaml").write_text("exclusive: true\ngroups:\n  IT:\n    - 메모리\n    - 반도체\n", encoding="utf-8")
    monkeypatch.setenv("DATAHUB_ROOT", str(tmp_path))
    r = load_reference()
    assert r.theme_members == {"IT": ["000001", "000002"]}  # 코드는 문자열 그대로(앞자리 0 보존), exclusive 라 독립 제외
    assert r.sector_of == {"000001": "전기전자", "000009": "제약"} and len(r.as_of) == 10


def test_missing_files_raise_not_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAHUB_ROOT", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        load_reference()
