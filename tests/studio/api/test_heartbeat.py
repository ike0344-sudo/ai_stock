"""8780 하트비트(워치독 생존 판정용) — 이벤트 루프 안 asyncio 작업이어야 한다(스레드면 먹통인데 살아 있음이 된다)."""
import asyncio
import json
import os
import threading
import time

from fastapi.testclient import TestClient

from studio.api.app import create_app
from studio.api.heartbeat import write_beat
from tests.studio.api.conftest import BASE


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_format_and_immediate_first_beat(root, disp):
    hb = root / "state" / "studio" / "heartbeat.json"
    threads_before = {t.name for t in threading.enumerate()}
    with TestClient(create_app(root, dispatcher=disp, heartbeat_path=hb, heartbeat_interval=0.05), base_url=BASE) as c:
        assert hb.exists()  # 기동 직후 1회 즉시 — 워치독이 첫 주기에 죽은 것으로 오판하지 않게
        d = read(hb)
        assert set(d) == {"updated_at", "pid"} and d["pid"] == os.getpid()
        assert abs(d["updated_at"] - time.time()) < 5
        first = d["updated_at"]
        time.sleep(0.3)
        assert read(hb)["updated_at"] > first  # 계속 갱신
        # 별도 스레드가 아니라 이벤트 루프 안의 asyncio 작업
        assert isinstance(c.app.state.heartbeat_task, asyncio.Task)
        assert not {t.name for t in threading.enumerate()} - threads_before - {t.name for t in threading.enumerate() if "portal" in t.name.lower() or "anyio" in t.name.lower()}, "하트비트용 스레드가 생겼다"
    assert c.app.state.heartbeat_task.cancelled() or c.app.state.heartbeat_task.done()  # 종료 때 정리
    assert not list(hb.parent.glob(".*.tmp*"))  # tmp 잔재 없음


def test_heartbeat_stops_while_event_loop_is_blocked(root, disp):
    """루프가 멈추면(=HTTP 를 못 받는 상태) 하트비트도 멈춘다 — 스레드로 썼다면 계속 갱신돼 이 테스트가 깨진다."""
    hb = root / "state" / "studio" / "heartbeat.json"
    app = create_app(root, dispatcher=disp, heartbeat_path=hb, heartbeat_interval=0.05)

    @app.get("/__block")
    async def block():
        time.sleep(1.0)  # 이벤트 루프를 붙잡는다(sync 호출을 async 핸들러에서)
        return {"ok": True}

    with TestClient(app, base_url=BASE) as c:
        time.sleep(0.2)
        samples: list[float] = []
        stop = threading.Event()

        def sample():
            while not stop.is_set():
                samples.append(read(hb)["updated_at"])
                time.sleep(0.02)

        t = threading.Thread(target=sample)
        t.start()
        time.sleep(0.1)
        assert c.get("/__block").status_code == 200
        time.sleep(0.3)  # 풀린 뒤 다시 갱신되는 것까지 표본에 담는다
        stop.set()
        t.join()
        # 갱신 시각들 사이의 가장 긴 간격: 루프가 1초 막혔으니 ≥0.8초 빈 구간이 있어야 한다. 스레드로 썼다면 간격은 내내 ~0.05초.
        # (예전엔 "막힌 동안 바뀐 횟수 ≤ 2" 로 셌는데, PC 가 바쁘면 막히기 직전·풀린 직후 박자가 하나씩 더 잡혀 가끔 깨졌다.
        #  간격 조건은 부하가 걸릴수록 간격이 늘 뿐이라 부하에 둔하다.)
        beats = sorted(set(samples))
        gap = max(b2 - b1 for b1, b2 in zip(beats, beats[1:]))
        assert gap >= 0.8, f"루프가 막혔는데 하트비트 갱신 간격이 최대 {gap:.2f}초뿐 — 막힌 동안에도 갱신됨"
        assert beats[-1] > beats[0] + 0.8  # 풀리면 다시 갱신(막힌 구간 뒤에도 값이 이어진다)


def test_write_failure_is_skipped_not_raised(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert write_beat(blocker / "sub" / "hb.json") is False  # 폴더를 못 만들면 예외 없이 이번 박자만 건너뜀
