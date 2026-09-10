import json
import os
import threading
import time

import pytest

from backtesting.risk_manager import (
    OpenPosition,
    OrderRequest,
    PortfolioState,
    RiskState,
    _lock_owner_alive,
    _should_reclaim_lock,
    can_open_new_position,
    check_order,
    get_position_size,
    load_state,
    record_partial_exit,
    record_position_added_to,
    record_position_closed,
    record_position_opened,
    risk_state_lock,
    roll_to_new_day_if_needed,
    save_state,
)

BASE_LIMITS = {
    "max_concurrent_positions": 5,
    "risk_pct_per_trade": 0.01,
    "max_symbol_weight_pct": None,
    "max_order_notional": None,
    "reentry_cooldown_sec": None,
    "max_consecutive_losses": None,
}


def _state_with_positions(n: int, trading_date: str = "2026-07-20") -> RiskState:
    positions = [
        OpenPosition(code=f"00000{i}", entry_time="2026-07-20T09:0" + str(i), allocated_capital=2_000_000, entry_price=100.0)
        for i in range(n)
    ]
    return RiskState(trading_date=trading_date, open_positions=positions)


def test_can_open_new_position_true_when_slot_available():
    state = _state_with_positions(3)

    assert can_open_new_position(state, max_concurrent=5) is True


def test_can_open_new_position_false_when_all_slots_full():
    state = _state_with_positions(5)

    assert can_open_new_position(state, max_concurrent=5) is False


def test_can_open_new_position_false_when_kill_switch_active_even_with_free_slots():
    state = _state_with_positions(0)
    state.kill_switch_active = True

    assert can_open_new_position(state, max_concurrent=5) is False


def test_record_position_opened_appends_position():
    state = RiskState(trading_date="2026-07-20")

    record_position_opened(state, "005930", "2026-07-20T09:05", allocated_capital=2_000_000, entry_price=70000)

    assert len(state.open_positions) == 1
    assert state.open_positions[0].code == "005930"


def test_record_position_opened_merges_duplicate_code_instead_of_creating_second_position():
    """process_entries_once가 같은 code로 두 번 매수 신호를 체결시켜
    record_position_opened를 두 번 부르는 경우(재신호 재진입) — 예전엔 OpenPosition이
    두 개 쌓여 첫 번째가 완전청산되는 순간 record_partial_exit가 "code 일치 전부"를
    지워 두 번째 물량이 손익 반영 없이 사라졌다. 이제는 두 번째 호출이
    record_position_added_to로 병합돼 포지션이 하나만 남고, 분할청산까지 정확히
    반영돼야 한다."""
    state = RiskState(trading_date="2026-07-20")
    record_position_opened(state, "005930", "t1", allocated_capital=1_000_000, entry_price=100.0, total_quantity=10)
    record_position_opened(state, "005930", "t2", allocated_capital=1_000_000, entry_price=120.0, total_quantity=10)

    assert len(state.open_positions) == 1  # 중복 포지션이 생기지 않음
    position = state.open_positions[0]
    assert position.total_quantity == 20
    assert position.allocated_capital == 2_000_000
    avg_entry = (100.0 * 10 + 120.0 * 10) / 20
    assert position.entry_price == pytest.approx(avg_entry)

    record_partial_exit(state, "005930", exit_price=121, sold_fraction=0.5, max_daily_loss_krw=10_000_000)
    assert len(state.open_positions) == 1  # 아직 슬롯 점유 중 — 조용히 사라지지 않음

    record_partial_exit(state, "005930", exit_price=121, sold_fraction=0.5, max_daily_loss_krw=10_000_000)

    assert state.open_positions == []
    expected_pnl = 2_000_000 * (121 - avg_entry) / avg_entry
    assert state.realized_pnl_krw == pytest.approx(expected_pnl)


def test_record_position_added_to_averages_entry_price_and_accumulates_quantity():
    state = RiskState(trading_date="2026-07-20")
    record_position_opened(
        state, "000660", "2026-07-20T09:05", allocated_capital=1_000_000, entry_price=100.0, total_quantity=10,
    )

    record_position_added_to(state, "000660", additional_capital=1_000_000, fill_price=88.0, additional_quantity=12)

    position = state.open_positions[0]
    assert position.total_quantity == 22
    assert position.allocated_capital == 2_000_000
    # (100*10 + 88*12) / 22
    assert position.entry_price == pytest.approx((100.0 * 10 + 88.0 * 12) / 22)


def test_record_position_added_to_raises_when_no_open_position():
    state = RiskState(trading_date="2026-07-20")

    with pytest.raises(ValueError):
        record_position_added_to(state, "000660", additional_capital=1_000_000, fill_price=88.0, additional_quantity=12)


def test_record_position_added_to_keeps_single_position_closeable_by_code():
    # 같은 code로 여러 OpenPosition을 만들지 않고 이 함수로 갱신하면, record_position_closed가
    # 평단가 전체를 한 번에 정확히 청산할 수 있다(반대로 여러 개를 만들면 첫 번째만
    # 청산되고 나머지는 손익 반영 없이 사라진다 — 이 함수가 막으려는 상황).
    state = RiskState(trading_date="2026-07-20")
    record_position_opened(
        state, "000660", "2026-07-20T09:05", allocated_capital=1_000_000, entry_price=100.0, total_quantity=10,
    )
    record_position_added_to(state, "000660", additional_capital=1_000_000, fill_price=88.0, additional_quantity=12)

    assert len(state.open_positions) == 1  # 포지션이 여전히 하나 — 청산 시 전량 정확히 처리됨
    record_position_closed(state, "000660", exit_price=95.0, max_daily_loss_krw=10_000_000)
    assert state.open_positions == []


def test_record_position_closed_updates_realized_pnl_and_removes_position():
    state = RiskState(trading_date="2026-07-20")
    record_position_opened(state, "005930", "2026-07-20T09:05", allocated_capital=2_000_000, entry_price=70000)

    record_position_closed(state, "005930", exit_price=71400, max_daily_loss_krw=1_000_000)  # +2%

    assert state.open_positions == []
    assert state.realized_pnl_krw == pytest.approx(40_000)  # 2,000,000 * 0.02
    assert state.kill_switch_active is False


def test_record_position_closed_triggers_kill_switch_when_loss_exceeds_threshold():
    state = RiskState(trading_date="2026-07-20")
    record_position_opened(state, "005930", "2026-07-20T09:05", allocated_capital=2_000_000, entry_price=70000)

    # -3% * 2,000,000 = -60,000, 한도 50,000 초과
    record_position_closed(state, "005930", exit_price=67900, max_daily_loss_krw=50_000)

    assert state.kill_switch_active is True
    assert can_open_new_position(state, max_concurrent=5) is False


def test_record_position_closed_accumulates_across_multiple_trades():
    state = RiskState(trading_date="2026-07-20")
    record_position_opened(state, "005930", "t1", allocated_capital=1_000_000, entry_price=100)
    record_position_opened(state, "000660", "t2", allocated_capital=1_000_000, entry_price=200)

    record_position_closed(state, "005930", exit_price=90, max_daily_loss_krw=1_000_000)  # -10% -> -100,000
    record_position_closed(state, "000660", exit_price=180, max_daily_loss_krw=1_000_000)  # -10% -> -100,000

    assert state.realized_pnl_krw == pytest.approx(-200_000)
    assert state.kill_switch_active is False  # 아직 한도(1,000,000) 안 넘음


def test_record_position_closed_raises_when_position_not_open():
    state = RiskState(trading_date="2026-07-20")

    with pytest.raises(ValueError):
        record_position_closed(state, "005930", exit_price=100, max_daily_loss_krw=1_000_000)


def test_record_partial_exit_keeps_slot_occupied_until_fully_closed():
    state = RiskState(trading_date="2026-07-20")
    record_position_opened(state, "005930", "t1", allocated_capital=4_000_000, entry_price=100)

    record_partial_exit(state, "005930", exit_price=103, sold_fraction=0.25, max_daily_loss_krw=1_000_000)

    assert len(state.open_positions) == 1  # 슬롯 계속 점유
    assert state.open_positions[0].remaining_fraction == pytest.approx(0.75)
    assert state.realized_pnl_krw == pytest.approx(4_000_000 * 0.25 * 0.03)
    assert can_open_new_position(state, max_concurrent=1) is False  # 슬롯 1개 다 참


def test_record_partial_exit_frees_slot_only_on_final_leg():
    state = RiskState(trading_date="2026-07-20")
    record_position_opened(state, "005930", "t1", allocated_capital=4_000_000, entry_price=100)

    record_partial_exit(state, "005930", exit_price=103, sold_fraction=0.25, max_daily_loss_krw=1_000_000)
    record_partial_exit(state, "005930", exit_price=105, sold_fraction=0.25, max_daily_loss_krw=1_000_000)
    record_partial_exit(state, "005930", exit_price=107, sold_fraction=0.25, max_daily_loss_krw=1_000_000)
    assert len(state.open_positions) == 1  # 아직 25% 남음

    record_partial_exit(state, "005930", exit_price=110, sold_fraction=0.25, max_daily_loss_krw=1_000_000)

    assert state.open_positions == []  # 마지막 leg에서 완전히 비워짐
    assert can_open_new_position(state, max_concurrent=1) is True


def test_record_partial_exit_accumulates_pnl_across_legs():
    state = RiskState(trading_date="2026-07-20")
    record_position_opened(state, "005930", "t1", allocated_capital=4_000_000, entry_price=100)

    record_partial_exit(state, "005930", exit_price=102.5, sold_fraction=0.25, max_daily_loss_krw=1_000_000)
    record_partial_exit(state, "005930", exit_price=104, sold_fraction=0.75, max_daily_loss_krw=1_000_000)

    expected = 4_000_000 * 0.25 * 0.025 + 4_000_000 * 0.75 * 0.04
    assert state.realized_pnl_krw == pytest.approx(expected)


def test_record_partial_exit_raises_when_position_not_open():
    state = RiskState(trading_date="2026-07-20")

    with pytest.raises(ValueError):
        record_partial_exit(state, "005930", exit_price=100, sold_fraction=0.25, max_daily_loss_krw=1_000_000)


def test_roll_to_new_day_if_needed_resets_pnl_and_kill_switch_but_keeps_positions():
    state = _state_with_positions(2, trading_date="2026-07-19")
    state.realized_pnl_krw = -500_000
    state.kill_switch_active = True

    rolled = roll_to_new_day_if_needed(state, today="2026-07-20")

    assert rolled.trading_date == "2026-07-20"
    assert rolled.realized_pnl_krw == 0.0
    assert rolled.kill_switch_active is False
    assert len(rolled.open_positions) == 2  # 포지션은 보존


def test_roll_to_new_day_if_needed_noop_when_same_day():
    state = _state_with_positions(1, trading_date="2026-07-20")
    state.realized_pnl_krw = -500_000

    rolled = roll_to_new_day_if_needed(state, today="2026-07-20")

    assert rolled.realized_pnl_krw == -500_000  # 변화 없음


def test_load_state_returns_fresh_state_when_file_missing(tmp_path):
    state = load_state(str(tmp_path / "nonexistent.json"))

    assert state.open_positions == []
    assert state.kill_switch_active is False


def test_save_and_load_state_round_trip_preserves_kill_switch(tmp_path):
    path = str(tmp_path / "risk_state.json")
    state = _state_with_positions(2, trading_date="2026-07-20")
    state.realized_pnl_krw = -300_000
    state.kill_switch_active = True

    save_state(state, path)
    restored = load_state(path)

    assert restored.trading_date == "2026-07-20"
    assert restored.realized_pnl_krw == pytest.approx(-300_000)
    assert restored.kill_switch_active is True
    assert len(restored.open_positions) == 2
    assert restored.open_positions[0].code == "000000"
    assert can_open_new_position(restored, max_concurrent=5) is False  # 재시작해도 여전히 차단


def test_lock_owner_alive_true_for_own_pid():
    token = f"{os.getpid()}:1:abc".encode()
    assert _lock_owner_alive(token) is True


def test_lock_owner_alive_false_for_definitely_dead_pid():
    # 실제로 존재할 가능성이 거의 없는 큰 pid 번호 — psutil.pid_exists가 False를 줘야 함.
    token = b"999999999:1:abc"
    assert _lock_owner_alive(token) is False


def test_lock_owner_alive_none_for_unparseable_token():
    assert _lock_owner_alive(b"") is None
    assert _lock_owner_alive(b"other-process-token") is None  # 콜론 없음 -> int() 실패


def test_should_reclaim_lock_false_when_owner_alive_even_if_old(tmp_path):
    """2026-08-30 정적분석으로 찾은 원래 결함의 핵심 방어 — 소유자가 확실히 살아있으면
    락이 아무리 오래돼도(LOCK_STALE_SECONDS를 훨씬 넘겨도) 훔치면 안 된다. 실제로
    600초를 기다리지 않고 mtime을 과거로 조작해 결정적으로 검증한다."""
    lock_path = str(tmp_path / "risk_state.json.lock")
    with open(lock_path, "wb") as f:
        f.write(f"{os.getpid()}:1:abc".encode())
    old = time.time() - 10_000  # LOCK_STALE_SECONDS(600초)를 훨씬 넘긴 과거
    os.utime(lock_path, (old, old))

    assert _should_reclaim_lock(lock_path) is False


def test_should_reclaim_lock_true_immediately_when_owner_dead_even_if_fresh(tmp_path):
    """소유자가 확실히 죽었으면 LOCK_STALE_SECONDS를 기다릴 필요 없이 즉시 회수한다
    (2026-08-30 PID 생존확인 승격의 핵심 이득 — 크래시 복구 속도)."""
    lock_path = str(tmp_path / "risk_state.json.lock")
    with open(lock_path, "wb") as f:
        f.write(b"999999999:1:abc")
    # mtime을 지금으로 둬도(=시간 기준으로는 전혀 stale이 아님) 죽은 pid면 즉시 회수해야 함.
    os.utime(lock_path, (time.time(), time.time()))

    assert _should_reclaim_lock(lock_path) is True


def test_should_reclaim_lock_falls_back_to_time_when_owner_unknown(tmp_path):
    """토큰을 못 읽어 생존 판단이 안 될 때만(옛 형식 등) 시간 기준 백업으로 판단한다."""
    lock_path = str(tmp_path / "risk_state.json.lock")
    with open(lock_path, "wb") as f:
        f.write(b"")  # 파싱 불가 -> None
    old = time.time() - 10_000
    os.utime(lock_path, (old, old))
    assert _should_reclaim_lock(lock_path) is True  # 시간 기준으로는 stale

    os.utime(lock_path, (time.time(), time.time()))
    assert _should_reclaim_lock(lock_path) is False  # 시간 기준으로도 아직 안 stale


def test_risk_state_lock_prevents_lost_updates_between_concurrent_writers(tmp_path):
    """두 전략 프로세스가 같은 risk_state.json을 동시에 read-modify-write하면, 락이
    없으면 나중에 저장하는 쪽이 상대가 방금 추가한 포지션을 덮어써 조용히 사라진다
    (계좌 단일화의 핵심 위험 — 실거래에서 조용히 깨지면 포지션 추적 유실로 이어짐).
    실제 프로세스 두 개 대신 스레드 두 개로 흉내낸다 — risk_state_lock은 파일 락이라
    프로세스/스레드 경계와 무관하게 같은 방식으로 상호배제해야 하므로 유효한 대체
    검증이다. 각 스레드가 load→추가→save를 N번 반복한 뒤 최종 포지션 수가 정확히
    2N이어야 한다 — 하나라도 유실되면 락이 깨진 것.

    join(timeout=30)만 쓰고 그 결과로 바로 개수를 확인했던 첫 버전은 간헐적으로
    실패했다(2026-08-30, 대규모 pytest 스위트 동시 실행 중 CPU 경합 상황에서 1회
    재현·확인) — 원인은 락이 아니라 이 테스트 자체였다: join이 타임아웃으로
    반환됐을 뿐 워커 스레드가 아직 안 끝난 상태에서 개수를 확인해, "느린 환경"과
    "유실"을 구분 못 했다. 이제 join 이후 각 스레드가 실제로 끝났는지(`is_alive()`)를
    먼저 명시적으로 확인해 두 실패 모드를 분리한다 — 타임아웃은 넉넉히 늘려
    (실제 작업량 대비 수십 배 여유) 정상 환경에서는 절대 걸리지 않게 하고, 그래도
    안 끝나면 "환경이 느려서 시간 안에 확인 못 함"이라고 명확히 실패하지, 유실
    여부를 잘못 판정하지 않는다.

    iterations는 2026-08-30에 40→12로 낮췄다 — 스레드 수 대신 반복 횟수를 줄여
    락파일 생성/삭제 총량을 줄인 것(전체 스위트와 같이 돌 때 Windows에서 파일
    생성/삭제가 잦으면 백신 실시간 검사 등으로 개별 파일 I/O가 느려지는 사례를
    관찰함 — 상호배제 검증에는 몇 회면 충분하고 굳이 80회씩 돌 필요가 없었다)."""
    path = str(tmp_path / "risk_state.json")
    save_state(RiskState(trading_date="2026-07-20"), path)

    iterations = 12
    errors: list = []

    def worker(prefix: str) -> None:
        try:
            for i in range(iterations):
                with risk_state_lock(path):
                    state = load_state(path)
                    record_position_opened(
                        state, f"{prefix}{i:03d}", "2026-07-20T09:00:00", 1_000_000, 10_000.0,
                    )
                    save_state(state, path)
        except Exception as exc:  # 스레드 안 예외는 조용히 삼켜지므로 명시적으로 수집
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(p,)) for p in ("A", "B")]
    for t in threads:
        t.start()
    # 정상 환경에서 80회 load+save 왕복은 수백 ms면 끝난다 — 300초는 교착(진짜 락 버그)
    # 감지용 안전장치일 뿐, "느린 환경이라 타임아웃" 자체가 이 값 때문에 나서는 안 된다.
    for t in threads:
        t.join(timeout=300)
    for t in threads:
        assert not t.is_alive(), (
            "워커 스레드가 300초 안에 안 끝남 — 락이 교착됐거나 이 환경이 비정상적으로 "
            "느린 것. 아래 포지션 개수 검증과는 별개 문제이니, 이 assert가 실패하면 "
            "먼저 CPU 경합/데드락부터 의심할 것(유실 판정 이전 단계)."
        )

    assert errors == []
    final = load_state(path)
    assert len(final.open_positions) == iterations * 2  # 하나도 안 사라졌어야 함
    assert len({p.code for p in final.open_positions}) == iterations * 2  # 중복 코드 없음(유실의 다른 징후)


def test_risk_state_lock_retries_on_transient_permission_error(tmp_path, monkeypatch):
    """2026-08-30 CPU 경합 부하테스트(8스레드로 GIL 다투게 해 재현)에서 실제로 잡힌
    버그: Windows(NTFS)는 락 파일이 막 삭제된 직후 같은 이름으로 다시 만들려 하면
    FileExistsError 대신 PermissionError를 던지는 경우가 있는데, risk_state_lock이
    이걸 못 잡아서 워커가 그대로 죽었다(실거래라면 run_trading_loop 전체가 죽는
    것과 같다). os.open을 모킹해 그 상황을 결정적으로 재현 — 타이밍/부하에 기대지
    않고 매번 같은 방식으로 검증한다(원래 버그는 CPU 부하가 있어야만 확률적으로
    재현됐다 — 이 테스트는 그 확률성을 없앤다)."""
    lock_path = str(tmp_path / "risk_state.json") + ".lock"
    real_open = os.open
    call_count = {"n": 0}

    def flaky_open(path, flags, *a, **k):
        if path == lock_path:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise PermissionError(13, "simulated transient Windows ACCESS_DENIED")
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(os, "open", flaky_open)

    with risk_state_lock(str(tmp_path / "risk_state.json")):
        pass  # 첫 시도는 PermissionError로 실패해야 하고, 재시도로 결국 성공해야 함

    assert call_count["n"] >= 2  # 최소 1번 실패 + 1번 성공(재시도가 실제로 일어남)
    assert not os.path.exists(lock_path)  # 정상 해제됨


def test_risk_state_lock_release_retries_on_transient_permission_error(tmp_path, monkeypatch):
    """2026-09-10 risk-agent 조사(risk-agent_20260910-182840_risk_lock_hang.md)에서 확정된
    버그: finally의 os.remove가 Windows 공유위반(WinError 32/PermissionError)으로 실패하면
    `except OSError: pass`가 조용히 삼켜 락 파일이 우리 토큰을 단 채 영구 orphan됐다 —
    이후 그 프로세스가 살아있는 한 `_should_reclaim_lock`이 절대 회수 안 해 다른 대기자가
    무한정지한다. 획득쪽 테스트(test_risk_state_lock_retries_on_transient_permission_error)와
    같은 방식으로 os.remove를 모킹해 첫 시도만 실패시켜 결정적으로 재현한다(무한대기 대신)."""
    path = str(tmp_path / "risk_state.json")
    lock_path = path + ".lock"
    real_remove = os.remove
    call_count = {"n": 0}

    def flaky_remove(p, *a, **k):
        if p == lock_path:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise PermissionError(32, "simulated transient Windows share violation")
        return real_remove(p, *a, **k)

    monkeypatch.setattr(os, "remove", flaky_remove)

    with risk_state_lock(path):
        pass  # 정상 임계구역 — 문제는 여기가 아니라 빠져나갈 때(finally)

    assert call_count["n"] >= 2  # 최소 1번 실패 + 1번 재시도로 성공
    assert not os.path.exists(lock_path)  # 재시도 끝에 정상 해제됨 — orphan 안 남음


def test_risk_state_lock_release_logs_when_retries_exhausted(tmp_path, monkeypatch, caplog):
    """재시도해도 끝내 안 풀리면(예: 소유 프로세스가 락 파일에 대해 뭔가를 계속 열어두는
    드문 상황) 조용히 넘어가지 않고 최소한 로그를 남긴다 — "조용히 사라진 릴리스"가 안
    보이는 것 자체가 이 버그를 여기까지 키운 원인이었다(risk-agent 보고서 §5)."""
    path = str(tmp_path / "risk_state.json")
    lock_path = path + ".lock"

    def always_fail_remove(p, *a, **k):
        if p == lock_path:
            raise PermissionError(32, "simulated persistent Windows share violation")
        raise AssertionError(f"unexpected os.remove call: {p}")

    monkeypatch.setattr(os, "remove", always_fail_remove)

    with caplog.at_level("ERROR", logger="backtesting.risk_manager"):
        with risk_state_lock(path):
            pass  # 여기서도 문제는 finally — 상한(LOCK_RELEASE_MAX_RETRIES)까지 재시도 후 포기해야 함

    assert os.path.exists(lock_path)  # 끝내 실패했으니 orphan으로 남는 것 자체는 맞다
    assert any("risk_state_lock 해제 실패" in rec.message for rec in caplog.records)


def test_risk_state_lock_release_treats_missing_lock_file_as_already_released(tmp_path, caplog):
    """2026-09-10 lead 지적: FileNotFoundError는 OSError의 서브클래스라 해제 재시도의
    `except OSError`에 걸린다 — 그런데 락 파일이 이미 없는 건 실패가 아니라 목적
    달성(지울 게 없음)이다. 회수 경로(risk_state_lock 획득쪽의 `_should_reclaim_lock`
    시간기준 백업)가 우리보다 먼저 지운 경우가 실제로 있을 수 있다(PID 생존확인이
    None을 주고 임계구역이 LOCK_STALE_SECONDS를 넘겨 오래 걸리는 드문 경우). 이걸
    OSError로 잡아 20회 재시도하면 (a) 최대 1초를 헛되이 태우고 (b) 사실과 반대되는
    "orphan으로 남았을 수 있음" 로그를 남기는 거짓 경보가 된다 — 재시도 전에 먼저
    잡아 즉시 성공 처리해야 한다."""
    path = str(tmp_path / "risk_state.json")
    lock_path = path + ".lock"

    with caplog.at_level("ERROR", logger="backtesting.risk_manager"):
        with risk_state_lock(path):
            # 임계구역 안에서 다른 프로세스가 회수 경로로 우리 락을 지운 상황을 흉내낸다.
            os.remove(lock_path)
            start = time.monotonic()

    elapsed = time.monotonic() - start
    assert elapsed < 0.2  # 재시도(0.05초 x 20 = 최대 1초)로 시간을 헛되이 태우면 안 됨
    assert not os.path.exists(lock_path)
    assert not any("risk_state_lock 해제 실패" in rec.message for rec in caplog.records)  # 거짓 경보 없음


def test_risk_state_lock_release_does_not_delete_foreign_lock(tmp_path):
    """2026-08-30 정적분석으로 찾은 결함: LOCK_STALE_SECONDS(원래 120초)를 넘겨 아직
    살아서 일하는 중인 보유자의 락을, 다른 대기자가 죽은 줄 알고 stale로 훔쳐 자기
    락으로 새로 만들 수 있다 — 이러면 원래 보유자가 나중에 작업을 마치고 finally에서
    "그 자리의 파일"을 무조건 지우던 예전 코드는, 사실 자기 락이 아니라 그 도둑의
    아직 진행 중인 락을 지워버려 세 번째 대기자가 끼어드는 연쇄를 만든다. 부하나
    120초 대기 없이, 우리가 락을 쥔 사이 파일 내용을 직접 남의 토큰으로 바꿔치기해
    이 훔침 직후 상태를 결정적으로 흉내낸다 — 근본 원인(120초 초과 자체)이 아니라
    그 결과(엉뚱한 락 삭제)만 검증하는 것이지만, 이게 바로 finally의 토큰 검증이
    막아야 하는 대상이다."""
    path = str(tmp_path / "risk_state.json")
    lock_path = path + ".lock"

    with risk_state_lock(path):
        # 우리가 여전히 임계구역 안에 있는 사이, 다른 프로세스가 우리 락을 stale로
        # 오판해 훔쳐서 자기 토큰으로 락 파일을 새로 만들었다고 가정.
        with open(lock_path, "wb") as f:
            f.write(b"other-process-token")

    # 우리 finally는 토큰이 안 맞으니 지우면 안 된다 — 지우면 그 "다른 프로세스"의
    # 아직 진행 중인 임계구역을 몰래 풀어버리는 것과 같다.
    assert os.path.exists(lock_path)
    with open(lock_path, "rb") as f:
        assert f.read() == b"other-process-token"


def test_roll_to_new_day_appends_previous_day_pnl_to_history(tmp_path):
    history_path = str(tmp_path / "pnl_history.jsonl")
    state = RiskState(trading_date="2026-07-19", realized_pnl_krw=35_000.0)

    roll_to_new_day_if_needed(state, today="2026-07-20", pnl_history_path=history_path)

    lines = (tmp_path / "pnl_history.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry == {"date": "2026-07-19", "realized_pnl_krw": 35_000.0}


def test_roll_to_new_day_does_not_append_when_same_day(tmp_path):
    history_path = str(tmp_path / "pnl_history.jsonl")
    state = RiskState(trading_date="2026-07-20", realized_pnl_krw=35_000.0)

    roll_to_new_day_if_needed(state, today="2026-07-20", pnl_history_path=history_path)

    assert not (tmp_path / "pnl_history.jsonl").exists()


def test_roll_to_new_day_skips_history_append_when_path_not_given(tmp_path, monkeypatch):
    """하위호환: pnl_history_path를 넘기지 않는 기존 호출부(trading_loop.py 등)가
    그대로 동작해야 함 — 이력 적재를 그냥 건너뛴다."""
    monkeypatch.chdir(tmp_path)
    state = RiskState(trading_date="2026-07-19", realized_pnl_krw=35_000.0)

    rolled = roll_to_new_day_if_needed(state, today="2026-07-20")

    assert rolled.trading_date == "2026-07-20"
    assert not (tmp_path / "pnl_history.jsonl").exists()


def test_roll_to_new_day_appends_multiple_days_across_calls(tmp_path):
    history_path = str(tmp_path / "pnl_history.jsonl")
    day1 = RiskState(trading_date="2026-07-18", realized_pnl_krw=10_000.0)
    rolled1 = roll_to_new_day_if_needed(day1, today="2026-07-19", pnl_history_path=history_path)
    rolled1.realized_pnl_krw = -5_000.0

    roll_to_new_day_if_needed(rolled1, today="2026-07-20", pnl_history_path=history_path)

    lines = (tmp_path / "pnl_history.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"date": "2026-07-18", "realized_pnl_krw": 10_000.0}
    assert json.loads(lines[1]) == {"date": "2026-07-19", "realized_pnl_krw": -5_000.0}


def test_roll_to_new_day_resets_consecutive_losses_and_last_exit():
    state = RiskState(trading_date="2026-07-19", consecutive_losses=3, last_exit={"005930": {"time": "x", "was_loss": True}})

    rolled = roll_to_new_day_if_needed(state, today="2026-07-20")

    assert rolled.consecutive_losses == 0
    assert rolled.last_exit == {}


def test_record_partial_exit_tracks_consecutive_losses_and_last_exit_only_on_final_leg():
    state = RiskState(trading_date="2026-07-20")
    record_position_opened(state, "005930", "t1", allocated_capital=1_000_000, entry_price=100)

    record_partial_exit(state, "005930", exit_price=90, sold_fraction=0.5, max_daily_loss_krw=1_000_000, exit_time="2026-07-20T09:10:00")
    assert state.consecutive_losses == 0  # 아직 전량청산 아님
    assert "005930" not in state.last_exit

    record_partial_exit(state, "005930", exit_price=90, sold_fraction=0.5, max_daily_loss_krw=1_000_000, exit_time="2026-07-20T09:11:00")
    assert state.consecutive_losses == 1
    assert state.last_exit["005930"] == {"time": "2026-07-20T09:11:00", "was_loss": True}


def test_record_position_closed_resets_consecutive_losses_on_win():
    state = RiskState(trading_date="2026-07-20", consecutive_losses=2)
    record_position_opened(state, "005930", "t1", allocated_capital=1_000_000, entry_price=100)

    record_position_closed(state, "005930", exit_price=110, max_daily_loss_krw=1_000_000, exit_time="2026-07-20T09:11:00")

    assert state.consecutive_losses == 0
    assert state.last_exit["005930"]["was_loss"] is False


def _portfolio(risk_state=None, total_capital_krw: float = 10_000_000) -> PortfolioState:
    return PortfolioState(risk_state=risk_state or RiskState(trading_date="2026-07-20"), total_capital_krw=total_capital_krw)


def test_check_order_rejects_entry_without_stop():
    order = OrderRequest(code="005930", side="buy", quantity=10, price=70000, stop=None)

    decision = check_order(order, _portfolio(), limits=BASE_LIMITS)

    assert decision.approved is False
    assert decision.rule_id == "no_stop_loss"
    assert decision.reason


def test_check_order_approves_valid_entry_with_stop():
    order = OrderRequest(code="005930", side="buy", quantity=10, price=70000, stop=68000)

    decision = check_order(order, _portfolio(), limits=BASE_LIMITS)

    assert decision.approved is True
    assert decision.rule_id == "approved"


def test_check_order_sell_always_approved_even_without_stop():
    order = OrderRequest(code="005930", side="sell", quantity=10, price=70000, stop=None)

    decision = check_order(order, _portfolio(), limits=BASE_LIMITS)

    assert decision.approved is True
    assert decision.rule_id == "sell_always_allowed"


def test_check_order_rejects_when_kill_switch_active():
    risk_state = RiskState(trading_date="2026-07-20", kill_switch_active=True)
    order = OrderRequest(code="005930", side="buy", quantity=10, price=70000, stop=68000)

    decision = check_order(order, _portfolio(risk_state), limits=BASE_LIMITS)

    assert decision.approved is False
    assert decision.rule_id == "kill_switch_active"


def test_check_order_rejects_when_max_concurrent_positions_reached():
    risk_state = _state_with_positions(5)
    order = OrderRequest(code="005930", side="buy", quantity=10, price=70000, stop=68000)

    decision = check_order(order, _portfolio(risk_state), limits=BASE_LIMITS)

    assert decision.approved is False
    assert decision.rule_id == "max_concurrent_positions"


def test_check_order_skips_limits_that_are_none():
    order = OrderRequest(code="005930", side="buy", quantity=1_000_000, price=70000, stop=68000)

    decision = check_order(order, _portfolio(), limits=BASE_LIMITS)

    assert decision.approved is True  # max_order_notional=None -> 팻핑거 체크 건너뜀


def test_check_order_rejects_when_order_notional_exceeds_limit():
    limits = {**BASE_LIMITS, "max_order_notional": 5_000_000}
    order = OrderRequest(code="005930", side="buy", quantity=100, price=70000, stop=68000)  # 7,000,000

    decision = check_order(order, _portfolio(), limits=limits)

    assert decision.approved is False
    assert decision.rule_id == "max_order_notional"


def test_check_order_rejects_when_symbol_weight_exceeds_limit():
    limits = {**BASE_LIMITS, "max_symbol_weight_pct": 0.2}
    order = OrderRequest(code="005930", side="buy", quantity=100, price=70000, stop=68000)  # 7,000,000 / 10,000,000 = 70%

    decision = check_order(order, _portfolio(), limits=limits)

    assert decision.approved is False
    assert decision.rule_id == "max_symbol_weight_pct"


def test_check_order_default_limits_reject_symbol_weight_above_25_percent():
    """risk_limits.yaml의 실제 max_symbol_weight_pct=0.25(2026-08-30 사용자 결정)가
    limits를 안 넘길 때(check_order 기본 경로, 실거래와 동일)도 강제되는지 확인 —
    limits=BASE_LIMITS로 덮어쓰지 않고 모듈 기본값(_LIMITS, risk_limits.yaml에서 로드)을
    그대로 쓴다."""
    order = OrderRequest(code="005930", side="buy", quantity=100, price=26000, stop=25000)  # 2,600,000/10,000,000=26%

    decision = check_order(order, _portfolio())

    assert decision.approved is False
    assert decision.rule_id == "max_symbol_weight_pct"


def test_check_order_default_limits_approve_symbol_weight_at_25_percent():
    order = OrderRequest(code="005930", side="buy", quantity=100, price=25000, stop=24000)  # 2,500,000/10,000,000=25%

    decision = check_order(order, _portfolio())

    assert decision.approved is True


def test_check_order_combines_existing_position_capital_with_new_order_for_symbol_weight():
    """계좌 단일화 이전엔 각 전략 프로세스가 자기 risk_state만 봐서, 다른 프로세스가
    이미 담아둔 같은 종목 물량을 몰랐다. 이제 risk_state가 계좌 공유 파일에서 로드되므로
    "이미 보유한 포지션"이 어느 프로세스가 열었든 existing_capital에 합산돼 새 주문
    승인/거부에 반영돼야 한다(그 값이 전략1이든 전략2든 이 함수 입장에서는 구분 안 함
    — risk_state.open_positions 하나만 본다)."""
    state = RiskState(trading_date="2026-07-20", open_positions=[
        OpenPosition(code="005930", entry_time="t1", allocated_capital=2_000_000, entry_price=70000),  # 기존 20%
    ])
    order = OrderRequest(code="005930", side="buy", quantity=10, price=70000, stop=68000)  # +700,000 -> 27%

    decision = check_order(order, _portfolio(risk_state=state))

    assert decision.approved is False
    assert decision.rule_id == "max_symbol_weight_pct"


def test_check_order_allows_addition_when_combined_symbol_weight_stays_within_limit():
    """25% 한도 밑이면 기존 포지션이 있어도 추가 매수가 승인된다 — 5슬롯 균등분할(20%)
    범위 안의 정상 흐름까지 막지 않는지 확인(과잉 차단 방지 회귀)."""
    state = RiskState(trading_date="2026-07-20", open_positions=[
        OpenPosition(code="005930", entry_time="t1", allocated_capital=2_000_000, entry_price=70000),  # 기존 20%
    ])
    order = OrderRequest(code="005930", side="buy", quantity=5, price=70000, stop=68000)  # +350,000 -> 23.5%

    decision = check_order(order, _portfolio(risk_state=state))

    assert decision.approved is True


def test_check_order_rejects_when_consecutive_losses_reach_limit():
    limits = {**BASE_LIMITS, "max_consecutive_losses": 3}
    risk_state = RiskState(trading_date="2026-07-20", consecutive_losses=3)
    order = OrderRequest(code="005930", side="buy", quantity=10, price=70000, stop=68000)

    decision = check_order(order, _portfolio(risk_state), limits=limits)

    assert decision.approved is False
    assert decision.rule_id == "max_consecutive_losses"


def test_check_order_rejects_reentry_within_cooldown_after_loss():
    limits = {**BASE_LIMITS, "reentry_cooldown_sec": 600}
    risk_state = RiskState(
        trading_date="2026-07-20",
        last_exit={"005930": {"time": "2026-07-20T09:00:00", "was_loss": True}},
    )
    order = OrderRequest(code="005930", side="buy", quantity=10, price=70000, stop=68000)

    decision = check_order(order, _portfolio(risk_state), limits=limits, now="2026-07-20T09:05:00")

    assert decision.approved is False
    assert decision.rule_id == "reentry_cooldown"


def test_check_order_allows_reentry_after_cooldown_elapsed():
    limits = {**BASE_LIMITS, "reentry_cooldown_sec": 600}
    risk_state = RiskState(
        trading_date="2026-07-20",
        last_exit={"005930": {"time": "2026-07-20T09:00:00", "was_loss": True}},
    )
    order = OrderRequest(code="005930", side="buy", quantity=10, price=70000, stop=68000)

    decision = check_order(order, _portfolio(risk_state), limits=limits, now="2026-07-20T09:15:00")

    assert decision.approved is True


def test_check_order_allows_reentry_after_a_win_regardless_of_cooldown():
    limits = {**BASE_LIMITS, "reentry_cooldown_sec": 600}
    risk_state = RiskState(
        trading_date="2026-07-20",
        last_exit={"005930": {"time": "2026-07-20T09:00:00", "was_loss": False}},
    )
    order = OrderRequest(code="005930", side="buy", quantity=10, price=70000, stop=68000)

    decision = check_order(order, _portfolio(risk_state), limits=limits, now="2026-07-20T09:00:01")

    assert decision.approved is True


def test_get_position_size_uses_fixed_risk_amount():
    portfolio = _portfolio(total_capital_krw=10_000_000)
    limits = {**BASE_LIMITS, "risk_pct_per_trade": 0.01}  # 리스크금액 100,000

    quantity = get_position_size("005930", entry=70000, stop=68000, portfolio=portfolio, limits=limits)

    assert quantity == 50  # 100,000 / 2,000


def test_get_position_size_returns_zero_when_stop_equals_entry():
    portfolio = _portfolio(total_capital_krw=10_000_000)

    quantity = get_position_size("005930", entry=70000, stop=70000, portfolio=portfolio, limits=BASE_LIMITS)

    assert quantity == 0
