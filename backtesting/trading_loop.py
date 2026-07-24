"""신호감지(live_monitor)+리스크승인(risk_manager)+주문실행(kiwoom_client)+알림(notifier)을
조합하는 실주문 진입점. live_monitor.py(관찰전용, 주문 없음)는 그대로 두고 이 모듈이
실제 매수/매도 주문을 낸다. CLI: run-trading (Do 단계에서 wiring 예정).

live_monitor.py는 진입 신호만 감지했지만, 실거래에서는 보유 포지션의 청산
조건(손절/분할매도/본전청산)도 실시간으로 감시해야 한다 — 이 모듈이 새로 추가하는
부분이다(Design §2.2).
"""
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime

from kiwoom_client import KiwoomClient
from .final_strategy import RECOMMENDED_MAX_CONCURRENT_POSITIONS, RECOMMENDED_PROBA_THRESHOLD, STOP_LOSS_PCT, TIERS
from .heartbeat import write_heartbeat
from .kill_switch_control import DEFAULT_OVERRIDE_PATH as DEFAULT_KILL_SWITCH_OVERRIDE_PATH
from .kill_switch_control import is_kill_switch_requested
from .live_monitor import fetch_today_candles, fetch_today_regime, scan_watchlist_once
from .ml_entry_filter import TrainedEntryFilterModel
from .notifier import notify_error, notify_kill_switch, notify_order_filled, notify_signal_detected
from .orderbook_collector import is_extended_market_open
from .realtime_feed import RealtimeFeed
from .risk_manager import (
    RiskState,
    can_open_new_position,
    load_state,
    record_partial_exit,
    record_position_opened,
    roll_to_new_day_if_needed,
    save_state,
)
from .screener import top_by_trading_value
from .stop_control import clear_stop_flag, is_stop_requested

DEFAULT_ORDER_LOG_PATH = "state/orders.jsonl"
DEFAULT_PNL_HISTORY_PATH = "state/pnl_history.jsonl"


def _log_order(order_log_path: str, side: str, code: str, quantity: int, price: float, reason: str) -> None:
    """주문 성공 이후의 부가 기록(trading-dashboard Cycle #2, Design §12.3). 기록
    실패는 조용히 무시한다 — 이미 주문은 체결됐고 알림도 나갔으므로, 로그 누락이
    거래 흐름 자체를 막으면 안 된다(Design §12.7)."""
    try:
        directory = os.path.dirname(order_log_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(order_log_path, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "side": side, "code": code, "quantity": quantity, "price": price,
                        "reason": reason, "order_time": datetime.now().isoformat(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except OSError:
        pass


@dataclass
class ExitTrackingState:
    """포지션별 청산 진행 상태(어느 tier까지 발동했는지) — risk_manager.OpenPosition의
    remaining_fraction/total_quantity와 짝을 이루지만, tier 임계값 진행 상황(전략
    고유 로직)은 여기서 별도로 관리한다."""
    armed: bool = False
    tiers_remaining: list = field(default_factory=lambda: list(TIERS))


def _order_rejected(response: dict) -> RuntimeError | None:
    """place_order 응답이 거부(return_code!=0)면 RuntimeError로, 정상 체결이면
    None을 반환한다. request_tr()은 HTTP 레벨 오류만 예외로 던지고, 주문 거부는
    HTTP 200 + return_code!=0으로 응답에 실려 온다 — 이 체크 없이 응답을 무조건
    성공으로 취급하면 실제로는 거부된 주문이 risk_state에 "체결"로 기록되는
    phantom position이 생긴다."""
    return_code = response.get("return_code")
    if return_code == 0:
        return None
    return RuntimeError(f"return_code={return_code} {response.get('return_msg', '')}".strip())


def evaluate_exit(
    tracking: ExitTrackingState, net_pct: float, stop_loss_pct: float = STOP_LOSS_PCT, tiers: tuple = TIERS
):
    """지금 이 순간의 net_pct(진입가 대비 순수익률) 하나만 보고 "지금 팔아야 할
    비중"을 판단한다. breakout_reversal의 tiered exit 로직과 같은 규칙을, 과거
    경로 전체가 아니라 매 폴링 시점마다 상태(tracking)를 누적 갱신하며 적용하는
    실시간 버전이다.

    반환: (exit_reason, 지금 팔 비중[0~1]) 또는 아무 것도 안 팔면 None.
    """
    tier_fraction = 1.0 / len(tiers)

    if not tracking.armed and net_pct <= -stop_loss_pct:
        return "stop_loss", 1.0

    triggered_now = 0.0
    while tracking.tiers_remaining and net_pct >= tracking.tiers_remaining[0]:
        tracking.tiers_remaining.pop(0)
        tracking.armed = True
        triggered_now += tier_fraction
    if triggered_now > 0:
        return "take_profit_tier", triggered_now

    tiers_fired = len(tiers) - len(tracking.tiers_remaining)
    remaining = 1.0 - tiers_fired * tier_fraction
    if tracking.armed and remaining > 1e-9 and net_pct <= 0:
        return "breakeven", remaining

    return None


def compute_sell_quantity(position, sell_fraction: float) -> int:
    """분할매도 시 실제 정수 주문수량을 계산. 반올림 오차가 누적돼 마지막 leg에
    잔량이 남지 않도록, "이번에 팔면 완전히 청산되는지"를 먼저 판단해 그 경우엔
    남은 실제 수량 전부를 반환한다."""
    is_final_leg = (position.remaining_fraction - sell_fraction) <= 1e-9
    already_sold = round(position.total_quantity * (1.0 - position.remaining_fraction))
    if is_final_leg:
        return position.total_quantity - already_sold
    return round(position.total_quantity * sell_fraction)


def process_entries_once(
    client: KiwoomClient,
    trained: TrainedEntryFilterModel,
    today_top35: set,
    regime_ok: bool,
    risk_state: RiskState,
    exit_tracking: dict,
    data_dir: str,
    proba_threshold: float,
    max_concurrent_positions: int,
    position_capital_krw: float,
    bot_token: str,
    chat_id: str,
    seen_signals: set,
    order_log_path: str = DEFAULT_ORDER_LOG_PATH,
    feed: RealtimeFeed | None = None,
    code_to_name: dict | None = None,
    strategy: str = "strategy_1",
    exchange: str = "3",
) -> list:
    """신규 진입 신호를 감지해, 리스크 승인되는 만큼 매수 주문을 실행한다.
    실행된 주문 목록을 반환(테스트/로깅용).

    code_to_name: run_trading_loop이 top_by_trading_value로 받아온 watchlist_df의
    stock_code->name 매핑 — 포착 알림에 종목코드만이 아니라 종목명도 같이 보여주기
    위함(추가 API 호출 없이 이미 갖고 있던 값을 재사용). 없는 코드는 이름 없이 표시.

    strategy: 전략1/2/3이 같은 텔레그램 채팅방으로 동시에 알림을 보내면 어느 전략이
    보낸 건지 구분이 안 되는 문제가 있었다 — 모든 notify_* 호출 맨 앞에 붙는다.

    exchange: 진입 조건용 분봉의 거래소 기준. 전략1은 "3"(통합, KRX+NXT)이 기본값 —
    전략3(strategy3_scalp.py)는 별도로 KRX 기준을 유지한다."""
    code_to_name = code_to_name or {}
    new_signals = scan_watchlist_once(
        client, trained, today_top35, regime_ok, data_dir, proba_threshold, seen_signals, feed=feed, exchange=exchange
    )
    executed = []
    for signal in new_signals:
        code = signal["stock_code"]
        notify_signal_detected(strategy, code, code_to_name.get(code, ""), signal["price"], signal["proba"], bot_token, chat_id)
        if not can_open_new_position(risk_state, max_concurrent_positions):
            continue

        quantity = max(1, int(position_capital_krw // signal["price"]))
        try:
            order_response = client.place_order(code, side="buy", quantity=quantity)
        except Exception as exc:
            notify_error(strategy, f"{code} 매수 주문 실패", exc, bot_token, chat_id)
            continue
        rejected = _order_rejected(order_response)
        if rejected is not None:
            notify_error(strategy, f"{code} 매수 주문 거부", rejected, bot_token, chat_id)
            continue

        record_position_opened(
            risk_state, code, signal["signal_time"], position_capital_krw, signal["price"], total_quantity=quantity
        )
        exit_tracking[code] = ExitTrackingState()
        notify_order_filled(strategy, "buy", code, quantity, signal["price"], bot_token, chat_id)
        _log_order(order_log_path, "buy", code, quantity, signal["price"], "entry")
        executed.append({"code": code, "quantity": quantity, "price": signal["price"]})

    return executed


def _parse_quote_price(raw) -> float:
    """ka10004 호가 응답의 가격 필드는 "+"/"-" 부호가 전일종가 대비 방향(상승/하락)을
    나타낼 뿐 실제 가격의 부호가 아니다(fetch_chart.to_dataframe이 차트 데이터에
    적용하는 것과 동일한 키움 API 관례 — 실계좌 ka10004 호출로 직접 확인함:
    매도/매수 최우선호가 필드명은 sel_fpr_bid/buy_fpr_bid이고 "-255000"처럼 부호가
    붙어 온다). 그대로 float()하면 하락 종목에서 가격이 음수로 잘못 파싱된다."""
    return abs(float(raw))


def process_exits_once(
    client: KiwoomClient,
    risk_state: RiskState,
    exit_tracking: dict,
    max_daily_loss_krw: float,
    bot_token: str,
    chat_id: str,
    order_log_path: str = DEFAULT_ORDER_LOG_PATH,
    feed: RealtimeFeed | None = None,
    strategy: str = "strategy_1",
) -> list:
    """보유 포지션 전부의 청산 조건을 확인해 필요한 매도 주문을 실행한다.

    feed가 주어지고 해당 종목의 최근 틱이 있으면 실시간체결의 매수최우선호가(field
    28)를 쓴다 — REST 호가조회(ka10004)보다 빠르고, 무엇보다 보유종목마다 매번 REST
    왕복이 필요 없어진다. 아직 그 종목의 틱을 못 받았으면(막 진입 직후 등) 기존처럼
    REST로 폴백한다.
    """
    executed = []
    for position in list(risk_state.open_positions):
        feed_bid = feed.get_latest_bid(position.code) if feed is not None else None
        if feed_bid is not None:
            current_price = feed_bid
        else:
            try:
                # exchange 미지정 → client 기본값(모의="1"=KRX, 실전="3"=통합) 적용.
                # 매도 주문 자체도 place_order 기본값으로 실전에서는 통합(SOR)으로 나가므로
                # 호가 조회 기준을 주문 체결 기준과 맞춘 것 — 청산 판단이 실제로 주문이
                # 체결될 거래소의 호가를 보게 된다.
                quote = client.get_stock_quote(position.code)
                # 매도 주문은 매수호가(buy_fpr_bid, 매수측 최우선호가)에 체결되므로
                # 매도호가(sel_fpr_bid, 매도측 최우선호가)보다 이 값이 실제 청산가에 더 가깝다.
                current_price = _parse_quote_price(quote["buy_fpr_bid"])
            except Exception as exc:
                notify_error(strategy, f"{position.code} 현재가 조회 실패", exc, bot_token, chat_id)
                continue

        tracking = exit_tracking.setdefault(position.code, ExitTrackingState())
        net_pct = (current_price - position.entry_price) / position.entry_price
        outcome = evaluate_exit(tracking, net_pct)
        if outcome is None:
            continue

        exit_reason, sell_fraction = outcome
        quantity_to_sell = compute_sell_quantity(position, sell_fraction)
        if quantity_to_sell <= 0:
            continue

        try:
            order_response = client.place_order(position.code, side="sell", quantity=quantity_to_sell)
        except Exception as exc:
            notify_error(strategy, f"{position.code} 매도 주문 실패({exit_reason})", exc, bot_token, chat_id)
            continue
        rejected = _order_rejected(order_response)
        if rejected is not None:
            notify_error(strategy, f"{position.code} 매도 주문 거부({exit_reason})", rejected, bot_token, chat_id)
            continue

        record_partial_exit(risk_state, position.code, current_price, sell_fraction, max_daily_loss_krw)
        notify_order_filled(strategy, "sell", position.code, quantity_to_sell, current_price, bot_token, chat_id)
        _log_order(order_log_path, "sell", position.code, quantity_to_sell, current_price, exit_reason)
        executed.append({"code": position.code, "quantity": quantity_to_sell, "price": current_price, "reason": exit_reason})

        if risk_state.kill_switch_active:
            notify_kill_switch(strategy, risk_state.realized_pnl_krw, max_daily_loss_krw, bot_token, chat_id)

        if position.code not in [p.code for p in risk_state.open_positions]:
            exit_tracking.pop(position.code, None)

    return executed


def run_trading_loop(
    client: KiwoomClient,
    trained: TrainedEntryFilterModel,
    bot_token: str,
    chat_id: str,
    max_daily_loss_krw: float,
    risk_state_path: str = "state/risk_state.json",
    data_dir: str = "data",
    top_n: int = 35,
    proba_threshold: float = RECOMMENDED_PROBA_THRESHOLD,
    max_concurrent_positions: int = RECOMMENDED_MAX_CONCURRENT_POSITIONS,
    total_capital_krw: float = 10_000_000,
    poll_interval_seconds: float = 30.0,
    order_log_path: str = DEFAULT_ORDER_LOG_PATH,
    pnl_history_path: str = DEFAULT_PNL_HISTORY_PATH,
    kill_switch_override_path: str = DEFAULT_KILL_SWITCH_OVERRIDE_PATH,
    use_realtime_feed: bool = True,
    stop_flag_path: str | None = None,
    strategy: str = "strategy_1",
) -> None:
    """정규장 동안 반복: kill switch 수동 요청 확인 → 보유 포지션 청산 감시 →
    신규 진입 신호 처리 → 상태 저장.

    strategy: 텔레그램 알림 맨 앞에 붙는 전략 식별자(예: "strategy_1") — 여러 전략이
    같은 채팅방으로 동시에 알림을 보낼 때 구분하기 위함.

    stop_flag_path: 대시보드의 "중지" 버튼이 요청하는 우아한 종료 플래그(stop_control.py)
    — 매 사이클 확인해 요청이 있으면 while 루프를 빠져나간다. 미지정 시 risk_state_path와
    같은 폴더의 stop_requested.json을 쓴다. 시작 시 이전 실행이 남긴 요청을 스스로
    지운다(새로 시작하는데 과거 정지 요청 때문에 즉시 끝나면 안 됨).

    실제 매수/매도 주문이 나가는 유일한 진입점이다 — 관찰 전용으로만 확인하고
    싶다면 live_monitor.run_monitor_loop(CLI monitor-signals)를 대신 쓸 것.

    kill_switch_override_path는 trading-dashboard(Cycle #2)의 수동 중단/재개 버튼이
    쓰는 파일이다 — risk_state.json 읽기/쓰기 경로는 전혀 건드리지 않고, 이 파일
    하나만 매 사이클 확인해 risk_state.kill_switch_active 필드에 반영한다
    (Design §12.2 — dashboard→trading_loop 방향의 유일한 쓰기 통로).

    use_realtime_feed=True(기본)면 감시종목을 키움 WebSocket 실시간체결(0B)로 구독해
    매 사이클 REST 왕복 없이 분봉/호가를 조립한다(realtime_feed.py) — 35종목 REST
    스캔이 키움 rate limit 때문에 40초 가까이 걸리던 게 사실상 사라진다. 시작 시
    한 번만 REST로 오늘자 분봉을 백필(watchlist_df 만들 때와 같은 REST 예산 안에서)한
    뒤 WebSocket을 연결한다 — 연결에 실패해도 조용히 REST 폴백 동작으로 돌아간다
    (live_monitor.fetch_today_candles가 feed 비어있으면 알아서 REST를 쓰므로 이 함수
    쪽에서 별도 예외 처리가 필요 없다).
    """
    stop_flag_path = stop_flag_path or os.path.join(os.path.dirname(risk_state_path), "stop_requested.json")
    clear_stop_flag(stop_flag_path)
    # 백필(35종목 REST, 최대 40초 가까이)이 끝나기 전에도 "지금 이 전략이 실행 중"이라고
    # 대시보드가 바로 판단할 수 있도록 루프 진입 전에 먼저 한 번 하트비트를 찍는다 —
    # 이게 없으면 첫 사이클 전까지의 창(=백필 시간)에 오래된 하트비트가 임계값을
    # 넘겨버린 순간 "중지됨"으로 잘못 보여, 그 틈에 대시보드 "시작" 버튼이 똑같은
    # 전략을 중복 실행시키는 사고가 날 수 있다(실측: 전략1 실계좌에서 실제로 발생).
    write_heartbeat(os.path.dirname(risk_state_path))

    risk_state = roll_to_new_day_if_needed(load_state(risk_state_path), pnl_history_path=pnl_history_path)
    exit_tracking: dict = {}
    position_capital_krw = total_capital_krw / max_concurrent_positions

    # top_by_trading_value(워치리스트 선정)와 fetch_today_candles(진입 신호 계산용 분봉)
    # 모두 통합(KRX+NXT, stex_tp="3") 기준 — 전략1은 두 기준을 통합으로 통일했다.
    # (전략3은 여전히 fetch_today_candles의 기본값인 KRX 단독 기준을 쓴다.)
    watchlist_df = top_by_trading_value(client, top_n=top_n)
    today_top35 = set(watchlist_df["stock_code"])
    code_to_name = dict(zip(watchlist_df["stock_code"], watchlist_df["name"]))
    regime_ok = fetch_today_regime(client, data_dir)
    print(
        f"실주문 매매 시작 — 감시 {len(today_top35)}종목, 코스피 레짐={'상승' if regime_ok else '하락'}, "
        f"일일손실한도 {max_daily_loss_krw:,.0f}원, 슬롯 {max_concurrent_positions}개",
        flush=True,
    )

    feed = None
    if use_realtime_feed:
        feed = RealtimeFeed(client.appkey, client.secretkey, client.is_mock, sorted(today_top35))
        print(f"실시간 시세 백필 중... ({len(today_top35)}종목, REST 1회씩)", flush=True)
        for code in today_top35:
            try:
                feed.seed_from_dataframe(code, fetch_today_candles(client, code, exchange="3"))
            except Exception as exc:
                print(f"{code}: 백필 실패(실시간 구독 후 자동 회복) - {exc}", flush=True)
        connected = feed.start()
        print(
            "실시간 시세 구독 " + ("성공 — 이후 REST 없이 실시간으로 스캔합니다" if connected else "실패 — REST 폴백으로 동작합니다"),
            flush=True,
        )

    try:
        seen_signals: set = set()
        while is_extended_market_open(datetime.now()) and not is_stop_requested(stop_flag_path):
            risk_state = roll_to_new_day_if_needed(risk_state, pnl_history_path=pnl_history_path)

            if is_kill_switch_requested(kill_switch_override_path):
                risk_state.kill_switch_active = True

            # 워치리스트를 매 사이클마다 다시 뽑는다 — 시작 시 한 번만 고정해두면 장중에
            # 새로 거래대금 top_n 안으로 들어온 종목은 재시작 전까지 영영 감시 대상이
            # 아니게 되는 문제가 strategy3_scalp에서 실측으로 확인됐다(같은 구조라 전략1도
            # 동일하게 겪음). 새로 들어온 종목은 실시간피드 구독 목록엔 없어도
            # fetch_today_candles가 자동으로 REST 폴백하므로 이 갱신만으로 바로 감시
            # 대상에 들어간다.
            try:
                watchlist_df = top_by_trading_value(client, top_n=top_n)
                today_top35 = set(watchlist_df["stock_code"])
                code_to_name = dict(zip(watchlist_df["stock_code"], watchlist_df["name"]))
            except Exception as exc:
                print(f"워치리스트 갱신 실패(기존 목록 유지) - {exc}", flush=True)

            process_exits_once(
                client, risk_state, exit_tracking, max_daily_loss_krw, bot_token, chat_id,
                order_log_path=order_log_path, feed=feed, strategy=strategy,
            )
            if not risk_state.kill_switch_active:
                process_entries_once(
                    client, trained, today_top35, regime_ok, risk_state, exit_tracking,
                    data_dir, proba_threshold, max_concurrent_positions, position_capital_krw,
                    bot_token, chat_id, seen_signals, order_log_path=order_log_path, feed=feed,
                    code_to_name=code_to_name, strategy=strategy,
                )

            save_state(risk_state, risk_state_path)
            write_heartbeat(os.path.dirname(risk_state_path))
            time.sleep(poll_interval_seconds)
    finally:
        if feed is not None:
            feed.stop()

    save_state(risk_state, risk_state_path)
