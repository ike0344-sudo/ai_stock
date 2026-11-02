"""호가·체결 저장 넘겨주기 — 따로 도는 수집기(trader/recorder.py)가 쓰는 동안 데스크는 안 쓴다, 수집기가 죽으면 데스크가 이어 쓴다(11-02)."""
import os
import time

from trader import rec


def test_desk_yields_only_while_recorder_alive(monkeypatch, tmp_path):
    alive = tmp_path / "rec_alive"
    monkeypatch.setattr(rec, "ALIVE", alive)
    monkeypatch.setattr(rec, "OWNER", False)
    monkeypatch.setattr(rec, "codes", {"A"})
    monkeypatch.setattr(rec, "_q", [])
    rec._chk[:] = [0.0, False]
    rec.put("0B", "A", {})                                           # 수집기 없음 → 데스크가 저장
    alive.touch()
    rec._chk[:] = [0.0, False]
    rec.put("0B", "A", {})                                           # 수집기 살아 있음 → 넘김
    old = time.time() - 60
    os.utime(alive, (old, old))
    rec._chk[:] = [0.0, False]
    rec.put("0B", "A", {})                                           # 수집기 멈춘 지 15초 넘음 → 데스크가 다시
    assert len(rec._q) == 2


def test_recorder_collects_only_while_holding_lock(monkeypatch):
    monkeypatch.setattr(rec, "OWNER", True)
    monkeypatch.setattr(rec, "codes", {"A"})
    monkeypatch.setattr(rec, "_q", [])
    monkeypatch.setitem(rec.stat, "in", False)
    rec.put("0B", "A", {})                                           # 데스크가 잠금을 잡고 쓰는 중 — 쌓지 않는다(나중에 겹쳐 쓰지 않게)
    rec.stat["in"] = True
    rec.put("0B", "A", {})
    assert len(rec._q) == 1
