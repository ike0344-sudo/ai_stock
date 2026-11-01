"""텔레그램 말 명령 — 안전판(매도 없음) · 확인 버튼 · 종목 글자 맞추기."""
import time

from trader import tgcmd


class FakeDesk:
    def __init__(self):
        self.watch, self.holdings, self.pending, self.day = ["396300"], [], [], {}
        self.plans = [{"id": "p1", "code": "396300", "name": "HT로보틱스", "active": True, "status": "감시 중", "stages": [{"price": 10760}]}]
        self.cancelled, self.notes = [], []

    def name(self, c):
        return {"396300": "HT로보틱스", "010580": "에스엠벡셀"}.get(c, "")

    def cancel_plan(self, pid):
        self.cancelled.append(pid)
        return {"ok": True}

    def note(self, t):
        self.notes.append(t)


def test_slash_cancel_needs_confirm_then_runs():
    D = FakeDesk()
    reply, cid = tgcmd.handle(D, "/취소 HT로보틱스")
    assert cid and "HT로보틱스" in reply and not D.cancelled              # 버튼 누르기 전엔 아무것도 안 한다
    assert "취소했습니다" in tgcmd.confirm(D, cid, True) and D.cancelled == ["p1"]
    assert "이미 처리" in tgcmd.confirm(D, cid, True)                     # 두 번 눌러도 한 번만


def test_expired_and_rejected_do_nothing():
    D = FakeDesk()
    _, cid = tgcmd.handle(D, "/취소 396300")
    tgcmd._pending[cid] = (time.time() - 999, *tgcmd._pending[cid][1:])
    assert "무효" in tgcmd.confirm(D, cid, True) and not D.cancelled
    _, cid = tgcmd.handle(D, "/취소 396300")
    assert "안 했습니다" in tgcmd.confirm(D, cid, False) and not D.cancelled


def test_no_sell_and_unknown_stock():
    D = FakeDesk()
    assert "sell_stock" not in tgcmd.ACTIONS and "liquidate_all" not in tgcmd.ACTIONS
    assert tgcmd.handle(D, "/매도 HT로보틱스")[1] is None                  # 매도 명령은 없다
    reply, cid = tgcmd.handle(D, "/취소 삼성전자")
    assert cid is None and "못 찾았습니다" in reply
    assert tgcmd.handle(D, "/예약")[0].startswith("HT로보틱스")
