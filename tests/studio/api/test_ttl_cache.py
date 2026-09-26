"""route 캐시(_ttl) — 첫 한 번만 기다리고, 낡으면 낡은 값을 바로 주며 뒤에서 한 번만 갱신한다(19:22 데이터 범위 3.4초 대기 제거)."""
import threading
import time
from types import SimpleNamespace

from studio.api.routes import catalog


def test_first_call_computes_then_stale_value_is_served_instantly_while_one_background_refresh_runs(monkeypatch):
    monkeypatch.setattr(catalog, "TTL_SECONDS", 0.05)
    svc = SimpleNamespace()
    calls, gate = [], threading.Event()

    def slow():
        calls.append(1)
        if len(calls) > 1:
            gate.wait(5)  # 갱신은 일부러 느리게
        return len(calls)

    assert catalog._ttl(svc, "k", slow) == 1  # 처음은 동기 계산
    assert catalog._ttl(svc, "k", slow) == 1  # TTL 안 — 재사용
    time.sleep(0.08)
    t0 = time.perf_counter()
    assert catalog._ttl(svc, "k", slow) == 1  # 낡았지만 바로 돌아온다(갱신을 안 기다림)
    assert catalog._ttl(svc, "k", slow) == 1  # 갱신 중 또 불러도 스레드를 더 만들지 않는다
    assert time.perf_counter() - t0 < 0.5
    gate.set()
    for _ in range(100):
        if catalog._ttl(svc, "k", slow) == 2:
            break
        time.sleep(0.02)
    assert catalog._ttl(svc, "k", slow) == 2 and len(calls) == 2  # 갱신은 딱 한 번


def test_failed_background_refresh_keeps_the_old_value_and_retries_next_time(monkeypatch, caplog):
    monkeypatch.setattr(catalog, "TTL_SECONDS", 0.05)
    svc = SimpleNamespace()
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] == 2:
            raise OSError("디스크")
        return state["n"]

    assert catalog._ttl(svc, "k", flaky) == 1
    time.sleep(0.08)
    assert catalog._ttl(svc, "k", flaky) == 1  # 낡은 값
    for _ in range(100):
        if not svc._ttl_busy:
            break
        time.sleep(0.02)
    assert "캐시 갱신 실패" in caplog.text  # 조용히 삼키지 않는다
    time.sleep(0.08)
    catalog._ttl(svc, "k", flaky)  # 다음 요청이 다시 시도
    for _ in range(100):
        if catalog._ttl(svc, "k", flaky) == 3:
            break
        time.sleep(0.02)
    assert catalog._ttl(svc, "k", flaky) == 3


def test_warm_caches_fills_ranges_and_never_raises():
    class MD:
        n = 0

        def data_ranges(self):
            MD.n += 1
            return {"daily": ("a", "b")}

    svc = SimpleNamespace(market_data=lambda: MD())
    catalog.warm_caches(svc)
    catalog.warm_caches(svc)
    assert MD.n == 1  # 두 번째는 캐시
    catalog.warm_caches(SimpleNamespace(market_data=lambda: (_ for _ in ()).throw(RuntimeError("x"))))  # 실패해도 예외 없음
