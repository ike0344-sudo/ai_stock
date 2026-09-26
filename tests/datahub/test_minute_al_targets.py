"""통합 분봉 판정 — 수집기가 일부러 안 받는 저대금 종목은 판정에서 뺀다(2026-09-26: 288종목만 받았는데 나머지 1,674개 옛 파일 때문에 '나쁨'이 떴다)."""
import re
from datetime import date
from pathlib import Path

from datahub import catalog, status

TODAY = date(2026, 9, 26)


def test_only_targets_count_old_files_of_excluded_stocks_do_not():
    dates = {f"{i:06d}": "2026-09-18" for i in range(50)} | {f"9{i:05d}": "2026-09-04" for i in range(500)}  # 500개는 저대금(대상 아님)
    r = status.verdict_minute_al(dates, {f"{i:06d}" for i in range(50)}, TODAY, 14, 21)
    assert r["verdict"] == "good" and r["n_targets"] == 50 and r["n_stale"] == 0
    # 같은 데이터를 예전 방식(전부)으로 보면 나쁨 — 이 변경이 없애려던 오탐
    assert status.verdict_max_age(dates, TODAY, 14, 21)["verdict"] == "bad"


def test_stale_targets_downgrade_good_to_warn_and_are_listed():
    dates = {f"{i:06d}": "2026-09-18" for i in range(97)} | {"000097": "2026-09-04", "000098": "2026-09-01"}
    targets = {f"{i:06d}" for i in range(100)}  # 000099 는 파일 자체가 없다
    r = status.verdict_minute_al(dates, targets, TODAY, 14, 21)
    assert r["verdict"] == "warn" and r["n_stale"] == 3 and r["stale_codes"] == ["000097", "000098", "000099"]
    assert "3종목 낡음" in r["reason"]


def test_few_stale_targets_keep_good_but_still_listed():
    dates = {f"{i:06d}": "2026-09-18" for i in range(199)} | {"000199": "2026-09-04"}  # 0.5% < 2%
    r = status.verdict_minute_al(dates, {f"{i:06d}" for i in range(200)}, TODAY, 14, 21)
    assert r["verdict"] == "good" and r["stale_codes"] == ["000199"]


def test_old_mode_date_is_still_bad_and_no_target_files_is_bad():
    r = status.verdict_minute_al({"000001": "2026-08-01"}, {"000001"}, TODAY, 14, 21)
    assert r["verdict"] == "bad"
    assert status.verdict_minute_al({}, {"000001"}, TODAY, 14, 21)["verdict"] == "bad"


def test_threshold_in_catalog_equals_fetch_minute_default():
    """P9: 판정의 대상 하한(catalog min_value_eok)이 수집기 기본값(--min-tv)과 같아야 한다 — 다르면 판정이 엉뚱한 종목을 본다."""
    src = (Path(__file__).resolve().parents[2] / "kospi-theme-engine/scripts/fetch_minute.py").read_text(encoding="utf-8")
    m = re.search(r'"--min-tv",\s*type=int,\s*default=(\d+)', src)
    assert m and int(m.group(1)) == catalog.dataset("minute_al").freshness["min_value_eok"]


def test_minute_al_targets_follow_universe_themes_and_value(hub_root):
    ref = hub_root / "kospi-theme-engine/data/reference"
    ref.mkdir(parents=True)
    (ref / "universe.csv").write_text("code,name\nAAA111,a\nBBB222,b\nCCC333,c\nDDD444,d\n", encoding="utf-8-sig")
    (hub_root / "data").mkdir()
    (hub_root / "data/themes.csv").write_text("stock_code,theme\nAAA111,t\nBBB222,t\nCCC333,t\n", encoding="utf-8-sig")  # DDD444 는 테마 없음
    d = hub_root / "data/stocks/daily"
    d.mkdir(parents=True)
    (d / "AAA111.csv").write_text("date,close,volume\n2026-09-01,1000,20000000\n", encoding="utf-8")  # 200억
    (d / "BBB222.csv").write_text("date,close,volume\n2026-09-01,1000,1000000\n", encoding="utf-8")   # 10억 → 제외
    # CCC333 는 일봉 없음 → 판단 근거가 없으니 남긴다(수집기와 같음)
    assert status.minute_al_targets(100) == {"AAA111", "CCC333"}
