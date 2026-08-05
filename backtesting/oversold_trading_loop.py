"""전략 2번(과대낙폭 분할매수, oversold_strategy.py) 실주문 진입점 — trading_loop.py와
같은 조합(신호감지+리스크승인+주문실행+알림)이지만, SK하이닉스 단일 종목을 60선
밴드 3분할로 매매하는 이 전략 고유의 진입/청산 로직이 완전히 달라 별도 루프로
분리했다. risk_manager.py(포지션/손익/킬스위치)와 notifier.py는 trading_loop.py와
그대로 공유하고, 주문 로그 경로/기록 함수(_log_order)와 REST 호가 파싱(_parse_quote_price)도
그대로 가져다 쓴다.
"""
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from datetime import time as clock_time

import pandas as pd
from kiwoom_client import KiwoomClient

from .data_loader import _resample_minute, load_history
from .heartbeat import write_heartbeat
from .kill_switch_control import DEFAULT_OVERRIDE_PATH as DEFAULT_KILL_SWITCH_OVERRIDE_PATH
from .kill_switch_control import is_kill_switch_requested
from .notifier import notify_error, notify_kill_switch, notify_order_filled, notify_signal_detected
from .orderbook_collector import (
    MARKET_CLOSE_HOUR,
    MARKET_CLOSE_MINUTE,
    MARKET_OPEN_HOUR,
    MARKET_OPEN_MINUTE,
    is_extended_market_open,
)
from .oversold_strategy import (
    BAR_INTERVAL_MINUTES,
    HARD_STOP_PCT,
    MA_WINDOW,
    STOCK_CODE,
    TIER_FRACTION,
    compute_ma,
    next_entry_tier,
    should_exit_by_hard_stop,
    should_exit_by_time,
    should_exit_by_touch,
)
from .realtime_feed import RealtimeFeed
from .risk_manager import (
    OrderRequest,
    PortfolioState,
    RiskState,
    check_order,
    load_state,
    record_position_added_to,
    record_position_closed,
    record_position_opened,
    roll_to_new_day_if_needed,
    save_state,
)
from .stop_control import clear_stop_flag, is_stop_requested
from .trading_loop import DEFAULT_ORDER_LOG_PATH, DEFAULT_PNL_HISTORY_PATH, _log_order, _order_rejected, _parse_quote_price

HISTORY_BACKFILL_DAYS = 20  # 60기간 15분봉 이평선 계산에 충분한 여유(약 10거래일 이상 확보)
STRATEGY_NAME = "strategy_2"  # 이 모듈은 항상 전략2 전용이라 trading_loop.py처럼 파라미터로 받지 않고 고정값을 씀 — 텔레그램 알림 구분용

MARKET_OPEN_TIME = clock_time(MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE)
MARKET_CLOSE_TIME = clock_time(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE)


@dataclass
class OversoldEpisodeState:
    """지금 진행 중인 분할매수 에피소드의 진행 상태 — risk_manager.OpenPosition은
    평단/수량만 알고 "몇 단까지 체결됐는지"는 모르므로 이 작은 상태를 별도로 관리한다.
    포지션이 완전히 청산되면 새 OversoldEpisodeState()로 리셋해 다음 에피소드를 준비한다."""
    filled_tier_count: int = 0
    entry_date: str | None = None  # 최초 체결일(YYYY-MM-DD), 시간청산 계산용


def _episode_state_path(risk_state_path: str) -> str:
    return os.path.join(os.path.dirname(risk_state_path) or ".", "oversold_episode.json")


def load_episode_state(risk_state_path: str) -> OversoldEpisodeState:
    path = _episode_state_path(risk_state_path)
    if not os.path.exists(path):
        return OversoldEpisodeState()
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return OversoldEpisodeState(**raw)


def save_episode_state(episode: OversoldEpisodeState, risk_state_path: str) -> None:
    path = _episode_state_path(risk_state_path)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(episode), f, ensure_ascii=False, indent=2)


def _filter_regular_session(df: pd.DataFrame) -> pd.DataFrame:
    """정규장(09:00~15:30, 양끝 포함 — is_market_open과 동일 경계) 시간대의 봉만
    남긴다. 키움 분봉 데이터는 시간외 체결도 섞여서 온다(실측: data/stocks/minute/
    000660.csv에 15:31~16:35 사이 313행 포함, 대부분 15:35 시간외단일가 체결 —
    걸러내지 않으면 60선이 PDF가 의도한 "정규장 15분봉" 기준과 어긋난다)."""
    if df.empty:
        return df
    times = df.index.time
    return df[(times >= MARKET_OPEN_TIME) & (times <= MARKET_CLOSE_TIME)]


def compute_current_ma(historical_1min: pd.DataFrame, today_1min: pd.DataFrame) -> float | None:
    """어제까지의 1분봉(historical_1min, 고정)과 오늘자 1분봉(today_1min, 실시간
    갱신)을 각각 정규장 시간대로 거른 뒤 15분봉으로 리샘플해 합치고, 60기간
    이평선의 최신값을 계산한다. 60개 미만이면 None(아직 계산 불가).

    historical/오늘자 둘 다 1분봉으로 받아 이 함수 안에서 직접 리샘플하는 이유 —
    키움 서버가 만드는 15분봉(tic_scope="15")과 이 함수가 실시간 1분봉으로 직접
    조립하는 15분봉이 버킷 경계 관례(어느 시각을 그 봉의 라벨로 쓰는지)가 다를 수
    있어서, 두 출처를 섞으면 경계가 안 맞을 위험이 있다. 항상 1분봉만 받아 같은
    방식(_resample_minute)으로 리샘플하면 경계가 항상 일치한다."""
    historical_15min = _resample_minute(_filter_regular_session(historical_1min), BAR_INTERVAL_MINUTES)
    today_15min = _resample_minute(_filter_regular_session(today_1min), BAR_INTERVAL_MINUTES)
    combined = pd.concat([historical_15min, today_15min]) if not today_15min.empty else historical_15min
    if combined.empty:
        return None
    ma_series = compute_ma(combined, window=MA_WINDOW)
    latest = ma_series.iloc[-1] if len(ma_series) > 0 else None
    return float(latest) if latest is not None and not pd.isna(latest) else None


def process_oversold_entry_once(
    client: KiwoomClient,
    risk_state: RiskState,
    episode: OversoldEpisodeState,
    ma_value: float,
    current_price: float,
    tier_capital_krw: float,
    bot_token: str,
    chat_id: str,
    total_capital_krw: float,
    order_log_path: str = DEFAULT_ORDER_LOG_PATH,
    now: datetime | None = None,
) -> OversoldEpisodeState:
    """현재가가 다음 미체결 밴드를 건드렸으면 그 티어만큼 지정가로 매수한다.

    total_capital_krw로 risk_manager.check_order를 통과해야 실제로 주문을 낸다
    (2026-07-26 risk-agent 감사 지적 — trading_loop.py와 동일한 갭이 이 전략에도
    있었음). 손절가는 이 티어 체결가 기준 하드스톱(HARD_STOP_PCT) 근사치를 쓴다 —
    2차/3차 분할매수는 실제 평단이 체결 후에야 갱신되므로, 그 시점엔 아직 모르는
    최종 평단 대신 이번 체결가 자체를 기준으로 보수적으로 추정한다."""
    now = now or datetime.now()
    tier = next_entry_tier(episode.filled_tier_count, current_price, ma_value)
    if tier is None:
        return episode

    quantity = int(tier_capital_krw // current_price)
    if quantity < 1:
        # 배정된 티어 자금으로 1주도 못 사면(고가 급등 등) 강제로 1주를 사서 티어 예산을
        # 초과하는 대신, 신호만 알리고 매수는 건너뛴다.
        notify_signal_detected(STRATEGY_NAME, STOCK_CODE, "", current_price, None, bot_token, chat_id)
        return episode

    stop_price = current_price * (1 - HARD_STOP_PCT)
    decision = check_order(
        OrderRequest(code=STOCK_CODE, side="buy", quantity=quantity, price=current_price, stop=stop_price),
        PortfolioState(risk_state=risk_state, total_capital_krw=total_capital_krw),
    )
    if not decision.approved:
        notify_error(STRATEGY_NAME, f"{STOCK_CODE} {tier}차 매수 리스크 심사 거부({decision.rule_id})", RuntimeError(decision.reason), bot_token, chat_id)
        return episode
    if decision.adjusted_qty is not None:
        quantity = decision.adjusted_qty

    try:
        order_response = client.place_order(
            STOCK_CODE, side="buy", quantity=quantity, price=current_price, order_type="0",
        )
    except Exception as exc:
        notify_error(STRATEGY_NAME, f"{STOCK_CODE} {tier}차 매수 주문 실패", exc, bot_token, chat_id)
        return episode
    rejected = _order_rejected(order_response)
    if rejected is not None:
        notify_error(STRATEGY_NAME, f"{STOCK_CODE} {tier}차 매수 주문 거부", rejected, bot_token, chat_id)
        return episode

    if episode.filled_tier_count == 0:
        record_position_opened(
            risk_state, STOCK_CODE, now.isoformat(), tier_capital_krw, current_price, total_quantity=quantity,
        )
        episode.entry_date = now.date().isoformat()
    else:
        record_position_added_to(risk_state, STOCK_CODE, tier_capital_krw, current_price, quantity)
    episode.filled_tier_count += 1

    notify_order_filled(STRATEGY_NAME, "buy", STOCK_CODE, quantity, current_price, bot_token, chat_id)
    _log_order(order_log_path, "buy", STOCK_CODE, quantity, current_price, f"oversold_tier_{tier}")
    return episode


def process_oversold_exit_once(
    client: KiwoomClient,
    risk_state: RiskState,
    episode: OversoldEpisodeState,
    ma_value: float,
    current_price: float,
    max_daily_loss_krw: float,
    bot_token: str,
    chat_id: str,
    order_log_path: str = DEFAULT_ORDER_LOG_PATH,
    today: date | None = None,
) -> OversoldEpisodeState:
    """열려있는 포지션의 청산 조건(터치익절/하드스톱/시간청산)을 확인해 전량 매도한다."""
    position = next((p for p in risk_state.open_positions if p.code == STOCK_CODE), None)
    if position is None:
        return episode
    today = today or date.today()

    reason = None
    if should_exit_by_touch(current_price, ma_value):
        reason = "touch_ma"
    elif should_exit_by_hard_stop(current_price, position.entry_price):
        reason = "hard_stop"
    elif episode.entry_date and should_exit_by_time(date.fromisoformat(episode.entry_date), today):
        reason = "time_exit"

    if reason is None:
        return episode

    quantity = position.total_quantity
    try:
        # 시장가(order_type="3") — trading_loop.py와 같은 이유(2026-07-26 execution-agent
        # 감사 지적): 지정가는 미체결로 남을 수 있는데 체결확인/미체결관리 인프라가 아직
        # 없어, 손절/청산은 확실한 체결이 슬리피지 통제보다 우선이라 되돌린다.
        order_response = client.place_order(
            STOCK_CODE, side="sell", quantity=quantity, price=current_price, order_type="3",
        )
    except Exception as exc:
        notify_error(STRATEGY_NAME, f"{STOCK_CODE} 매도 주문 실패({reason})", exc, bot_token, chat_id)
        return episode
    rejected = _order_rejected(order_response)
    if rejected is not None:
        notify_error(STRATEGY_NAME, f"{STOCK_CODE} 매도 주문 거부({reason})", rejected, bot_token, chat_id)
        return episode

    record_position_closed(risk_state, STOCK_CODE, current_price, max_daily_loss_krw)
    notify_order_filled(STRATEGY_NAME, "sell", STOCK_CODE, quantity, current_price, bot_token, chat_id)
    _log_order(order_log_path, "sell", STOCK_CODE, quantity, current_price, reason)

    if risk_state.kill_switch_active:
        notify_kill_switch(STRATEGY_NAME, risk_state.realized_pnl_krw, max_daily_loss_krw, bot_token, chat_id)

    return OversoldEpisodeState()  # 청산 완료 — 다음 에피소드를 위해 리셋


def run_oversold_trading_loop(
    client: KiwoomClient,
    bot_token: str,
    chat_id: str,
    max_daily_loss_krw: float,
    risk_state_path: str = "state/strategy_2/risk_state.json",
    total_capital_krw: float = 10_000_000,
    poll_interval_seconds: float = 30.0,
    order_log_path: str = DEFAULT_ORDER_LOG_PATH,
    pnl_history_path: str = DEFAULT_PNL_HISTORY_PATH,
    kill_switch_override_path: str = DEFAULT_KILL_SWITCH_OVERRIDE_PATH,
    use_realtime_feed: bool = True,
    stop_flag_path: str | None = None,
) -> None:
    """정규장 동안 반복: kill switch 확인 → 60선/현재가 갱신 → 청산 조건 확인(항상,
    킬스위치와 무관) → 신규/추가 분할매수 확인(킬스위치 아닐 때만) → 상태 저장.

    total_capital_krw는 이 전략에 배정한 자금 전체(계좌 총자산이 아니라 전략2 몫만)
    — PDF 권장 배정비중(20~30%)에 맞게 run-trading 실행 시 총자산의 20~30%만 넣는다.
    3단 분할이므로 티어 1회당 total_capital_krw/3만큼 매수한다.

    stop_flag_path: 대시보드 "중지" 버튼의 우아한 종료 플래그(stop_control.py) — trading_loop.
    run_trading_loop과 동일한 규칙(미지정 시 risk_state_path와 같은 폴더, 시작 시 자동 clear)."""
    stop_flag_path = stop_flag_path or os.path.join(os.path.dirname(risk_state_path), "stop_requested.json")
    clear_stop_flag(stop_flag_path)
    write_heartbeat(os.path.dirname(risk_state_path))  # 백필 완료 전에도 "실행 중"으로 즉시 보이게(trading_loop.py와 동일 이유)

    risk_state = roll_to_new_day_if_needed(load_state(risk_state_path), pnl_history_path=pnl_history_path)
    episode = load_episode_state(risk_state_path)
    if not risk_state.open_positions:
        episode = OversoldEpisodeState()  # 재시작 시 포지션 없이 에피소드 상태만 남아있으면 정합성 보정
    tier_capital_krw = total_capital_krw * TIER_FRACTION

    today = date.today()
    # 1분봉으로 백필하고 compute_current_ma 안에서 정규장 필터+15분 리샘플을 직접
    # 한다 — 키움 서버가 만드는 15분봉(tic_scope="15")을 그대로 받으면 시간외 체결이
    # 섞여 있는 데다, 실시간 1분봉을 직접 조립해 만드는 15분봉과 버킷 경계 관례가
    # 다를 수 있어서(어느 시각을 그 봉의 라벨로 쓰는지) 둘을 그냥 이어붙이면 안 된다.
    # exchange="1"(KRX)을 명시한다 — 이 전략의 60선은 원래 KRX 정규장 가격 기준으로
    # 확정된 규칙이라, 통합(NXT 포함) 분봉을 섞으면 같은 분봉의 종가/거래량이 달라져
    # 이평선이 백테스트 때와 어긋난다(라이브로 확인: stex_tp="3"이면 거래량이 더 크고
    # 종가도 다르게 나옴).
    historical_1min = load_history(
        client, STOCK_CODE, start=today - timedelta(days=HISTORY_BACKFILL_DAYS), end=today - timedelta(days=1),
        interval="1", exchange="1",
    )
    print(
        f"전략2(과대낙폭) 시작 — SK하이닉스 백필 완료({len(historical_1min)}분봉), "
        f"배정자금 {total_capital_krw:,.0f}원, 일일손실한도 {max_daily_loss_krw:,.0f}원",
        flush=True,
    )

    feed = None
    if use_realtime_feed:
        feed = RealtimeFeed(client.appkey, client.secretkey, client.is_mock, [STOCK_CODE])
        try:
            today_1min = load_history(client, STOCK_CODE, start=today, end=today, interval="1", exchange="1")
            feed.seed_from_dataframe(STOCK_CODE, today_1min)
        except Exception as exc:
            print(f"{STOCK_CODE}: 오늘자 백필 실패(실시간 구독 후 자동 회복) - {exc}", flush=True)
        connected = feed.start()
        print("실시간 시세 구독 " + ("성공" if connected else "실패 — REST 폴백으로 동작합니다"), flush=True)

    try:
        while is_extended_market_open(datetime.now()) and not is_stop_requested(stop_flag_path):
            risk_state = roll_to_new_day_if_needed(risk_state, pnl_history_path=pnl_history_path)
            if is_kill_switch_requested(kill_switch_override_path):
                risk_state.kill_switch_active = True

            today_1min = feed.get_minute_df(STOCK_CODE) if feed is not None else pd.DataFrame()
            ma_value = compute_current_ma(historical_1min, today_1min)
            current_price = feed.get_latest_price(STOCK_CODE) if feed is not None else None
            if current_price is None:
                try:
                    # exchange 미지정 → client 기본값(실전="3"=통합) 적용. 60이평선(ma_value)은
                    # 위에서 KRX 기준으로 계산하지만, 이 호가는 실제 매도 주문(place_order,
                    # 실전 기본값도 통합/SOR)이 체결될 거래소 기준으로 맞춘 것 — MA는 "추세
                    # 판단" 기준, 호가는 "실제 체결 가능 가격" 기준이라 서로 다른 결정이다.
                    quote = client.get_stock_quote(STOCK_CODE)
                    current_price = _parse_quote_price(quote["buy_fpr_bid"])
                except Exception as exc:
                    notify_error(STRATEGY_NAME, f"{STOCK_CODE} 현재가 조회 실패", exc, bot_token, chat_id)
                    write_heartbeat(os.path.dirname(risk_state_path))
                    time.sleep(poll_interval_seconds)
                    continue

            if ma_value is not None:
                was_open = episode.filled_tier_count > 0
                episode = process_oversold_exit_once(
                    client, risk_state, episode, ma_value, current_price, max_daily_loss_krw,
                    bot_token, chat_id, order_log_path=order_log_path, today=today,
                )
                just_closed = was_open and episode.filled_tier_count == 0
                # 하드스톱 발동가(평단*0.8)는 항상 다음 미체결 밴드가(60선*0.91 이상)보다
                # 낮아, 방금 청산과 같은 current_price로 진입을 확인하면 그 자리에서 곧바로
                # 재매수(휩쏘)돼버린다 — 이번 폴링에서 막 청산됐으면 진입 확인을 건너뛰고
                # 다음 폴링(새 가격)부터 다시 신규 진입을 본다.
                if not risk_state.kill_switch_active and not just_closed:
                    episode = process_oversold_entry_once(
                        client, risk_state, episode, ma_value, current_price, tier_capital_krw,
                        bot_token, chat_id, total_capital_krw, order_log_path=order_log_path,
                    )

            save_state(risk_state, risk_state_path)
            save_episode_state(episode, risk_state_path)
            write_heartbeat(os.path.dirname(risk_state_path))
            time.sleep(poll_interval_seconds)
    finally:
        if feed is not None:
            feed.stop()

    save_state(risk_state, risk_state_path)
    save_episode_state(episode, risk_state_path)
