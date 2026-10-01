"""소피 순위 기록(sophie_rank_tape) 신선도 — 날짜별 파일 하나씩이라 가장 최근 파일 이름이 최신일이다."""
from datetime import datetime

from datahub import catalog, status


def _root(tmp_path, monkeypatch, days):
    d = tmp_path / "kospi-theme-engine" / "dist" / "logs" / "rank_tape"
    d.mkdir(parents=True)
    for x in days:
        (d / f"{x}.jsonl").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(catalog, "root", lambda: tmp_path)


def test_시작_전엔_좋음_그_뒤엔_파일이_있어야(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch, [])
    assert status.dataset_status("sophie_rank_tape", now=datetime(2026, 10, 5, 9))["verdict"] == "good"
    assert status.dataset_status("sophie_rank_tape", now=datetime(2026, 10, 7, 9))["verdict"] == "bad"


def test_전_거래일_파일이_있으면_좋음(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch, ["2026-10-06"])
    r = status.dataset_status("sophie_rank_tape", now=datetime(2026, 10, 7, 9))
    assert r["verdict"] == "good" and r["reference_date"] == "2026-10-06"
