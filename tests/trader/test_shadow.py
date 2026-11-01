"""Jev 그림자 — 예약가 도착 판정 채점(30분 안 −1% 더 내려오면 기다림이 나음, Jev 가 말린 것의 그날 종가)."""
from datetime import datetime, timedelta

from trader import shadow


def _bars(t0: datetime, prices: list[int]) -> list[dict]:
    return [{"t": (t0 + timedelta(minutes=i + 1)).strftime("%Y%m%d%H%M%S"), "l": p, "c": p} for i, p in enumerate(prices)]


def test_graded_entry_wait_and_avoided_loss():
    t0 = datetime(2026, 10, 20, 10, 0)
    bars = {"A": _bars(t0, [1000] * 10 + [985] * 25), "B": _bars(t0, [1010] * 35)}
    shadow._bars1, shadow._eg = bars.get, {}
    rs = [{"kind": "entry", "ts": t0.isoformat(), "pid": "a", "code": "A", "price": 1000, "take": False, "parts": {"knife": 0.8}},
          {"kind": "entry", "ts": t0.isoformat(), "pid": "b", "code": "B", "price": 1000, "take": True, "parts": {"knife": 0.2}},
          {"kind": "entry", "ts": t0.isoformat(), "pid": "t", "code": "B", "price": 1000, "take": True, "test": True}]
    g = shadow.graded_entry(rs)
    assert rs[0]["wait_better"] and not rs[1]["wait_better"]        # A 는 30분 안에 −1.5% → 기다림이 나음
    assert g["n"] == 2 and g["jev"] == 2 and g["always_take"] == 1  # 시험 줄은 안 셈
    assert g["skip_n"] == 1 and g["skip_close"] < 0 and g["skip_loss_n"] == 1   # Jev 가 말린 A 는 샀으면 손실
    assert g["parts"]["knife"] == {"wait": 0.8, "take": 0.2, "n": 2}       # 작은 질문: 기다림이 나았을 때 답이 더 높음


def test_ask_entry_sends_only_today_bars(monkeypatch, tmp_path):
    """10-23 엘리스: 어젯밤 애프터 1분봉이 '최근 10분'으로 Jev 에 갔다 — 오늘 봉만 보낸다."""
    import sys, types
    sent = []
    monkeypatch.setitem(sys.modules, "jev", types.SimpleNamespace(decide=lambda t, m: sent.append(t) or m(prob=0.5, knife=0, exhausted=0, bids_strong=0, ask_wall=0, buyers_trading=0, program_support=0, near_low=0)))
    monkeypatch.setattr(shadow, "LOG", tmp_path / "s.jsonl")
    now = datetime.now().replace(second=0, microsecond=0)
    bars = [{**b, "v": 1} for b in _bars(now - timedelta(days=1), [940] * 5) + _bars(now - timedelta(minutes=3), [912, 911])]
    shadow._bars1 = {"A": bars}.get
    shadow.ask_entry(types.SimpleNamespace(client=None), {"id": "p", "code": "A", "name": "A"}, {"price": 912}, 911, test=True)
    last = next(l for l in sent[0].split("\n") if l.startswith("Last 10"))
    assert "+0.00%" in last and "+3.07%" not in last                # 어제 940(+3.07%) 은 빠지고 오늘 912·911 만


def test_parts_model_learns_and_waits_for_data():
    import random
    rnd = random.Random(0)
    rows = []
    for i in range(60):
        knife = rnd.random()
        rows.append({"kind": "entry", "ts": f"2026-10-{1 + i // 10:02d}T10:{i % 10:02d}:00", "parts": {"knife": knife, "near_low": rnd.random()},
                     "prob": 0.6, "take": True, "wait_better": knife > 0.5})   # 급락 중이면 기다림이 나았다
    assert shadow.fit(rows[:20], "entry") == {"n": 20, "need": shadow.MIN_N}   # 자료 모자라면 판단 안 함
    m = shadow.fit(rows, "entry")
    assert m["eval"]["model"] > m["eval"]["always"] and m["w"]["knife"] < 0    # 급락 답이 높을수록 '받기' 확률이 낮아진다
    assert shadow.predict("entry", {"knife": 0.9, "near_low": 0.5}) < 0.5 < shadow.predict("entry", {"knife": 0.1, "near_low": 0.5})
