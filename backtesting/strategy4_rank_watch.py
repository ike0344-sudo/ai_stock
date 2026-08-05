"""전략 4번 — 거래대금 순위 4→3위, 5→4위, 6→5위로 올라서는 종목을 감지해 알림만
보낸다. 주문은 절대 내지 않는다(strategy3_scalp.py와 같은 관찰전용 계열) — 사용자가
"지금 N등인 종목이 N-1등으로 올라설 때"로 트리거를 명시적으로 확정했다(해당 자리
자체가 바뀌는 모든 경우가 아니라, 감시 대상 종목 자체를 추적하다가 한 칸 올라서는
순간만 본다).

매 사이클 trading_value_ranking.get_ranking(window="regular")로 순위를 다시 조회해
직전 사이클과 비교한다 — 별도 실시간 피드 없이 REST 폴링만으로 충분하다(거래대금
순위는 분 단위로도 크게 안 바뀌는 지표라 기존 전략들처럼 초 단위 실시간 체결까지는
필요 없음).

screener.top_by_trading_value를 직접 쓰지 않는 이유: 그건 하루 전체(장전 포함) 누적
거래대금 기준 순위라, 대시보드 ranking.html의 "장중" 버튼이 보여주는 "09:00 이후
순수 증가분" 기준 순위와 다르다(둘 다 "장중"이라 부르지만 계산이 다름 — 사용자가
실측으로 확인). trading_value_ranking.get_ranking(window="regular")은 09:00 베이스라인을
빼 순증가분으로 다시 정렬·재번호(1위부터 빈틈없이)한 순위라 대시보드와 동일한
숫자를 본다.

거래소 기준: 이 전략은 순위 데이터(get_ranking → screener.top_by_trading_value,
통합/KRX+NXT 기준)만 쓴다 — 별도 분봉/호가 조회가 없어 KRX/통합 구분이 추가로
필요한 지점 자체가 없다.
"""
import json
import os
import time
from datetime import datetime

import pandas as pd
from kiwoom_client import KiwoomClient

from .heartbeat import write_heartbeat
from .notifier import send_telegram
from .orderbook_collector import is_market_open
from .stop_control import clear_stop_flag, is_stop_requested
from .trading_value_ranking import get_ranking as get_trading_value_ranking

STRATEGY_NAME = "strategy_4"
DEFAULT_TOP_N = 10  # 4~6위만 보면 되지만, 순위 데이터를 위에서부터 채우는 get_ranking 특성상 여유 있게 받아둠
DEFAULT_SIGNAL_LOG_PATH = "state/strategy_4/signals.jsonl"

WATCHED_RANK_PAIRS = [(4, 3), (5, 4), (6, 5)]  # (from_rank, to_rank) 감시 목록


def describe_strategy_4() -> dict:
    """대시보드 등 조회용 — strategy_catalog.py에 등록되어 describe_strategy_1/2/3와
    같은 패턴으로 노출된다."""
    pairs_text = ", ".join(f"{f}위→{t}위" for f, t in WATCHED_RANK_PAIRS)
    return {
        "entry": [f"거래대금 순위 {pairs_text}로 올라서는 순간 포착"],
        "exit": ["청산 로직 없음 — 신호 포착/알림 전용(주문 미실행)"],
        "operation": ["ML 게이트 없음", "매 사이클 거래대금 순위 재조회 후 직전 사이클과 비교"],
        "exchange_basis": ["순위 데이터(거래대금 상위): 통합(KRX+NXT)"],
    }


def check_rank_promotions(previous_ranks: dict, current_ranks: dict) -> list[tuple[str, int, int]]:
    """previous_ranks/current_ranks: {stock_code: rank}. WATCHED_RANK_PAIRS 각각에 대해
    직전 사이클에 from_rank였던 종목이 이번 사이클에 to_rank가 됐으면
    (종목코드, from_rank, to_rank)를 모아 반환한다 — 같은 사이클에 여러 건이 동시에
    감지될 수 있다(예: 4→3위와 5→4위가 동시에 일어남).

    직전 사이클에 해당 순위 종목이 없었으면(첫 사이클 등) 그 쌍은 건너뛴다."""
    promotions = []
    for from_rank, to_rank in WATCHED_RANK_PAIRS:
        code = next((c for c, rank in previous_ranks.items() if rank == from_rank), None)
        if code is not None and current_ranks.get(code) == to_rank:
            promotions.append((code, from_rank, to_rank))
    return promotions


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Strategy 프로토콜 어댑터 — df에 이 종목의 시점별 거래대금 순위를 담은 'rank'
    컬럼이 있어야 한다. 직전 순위/현재 순위 쌍이 WATCHED_RANK_PAIRS 중 하나와 일치하면
    signal=1, 아니면 0."""
    out = df.copy()
    out["signal"] = 0
    prev_rank = out["rank"].shift(1)
    for idx in out.index:
        prev, curr = prev_rank.at[idx], out.at[idx, "rank"]
        if pd.isna(prev) or pd.isna(curr):
            continue
        if (int(prev), int(curr)) in WATCHED_RANK_PAIRS:
            out.at[idx, "signal"] = 1
    return out


generate_signals.name = "strategy_4"
generate_signals.params = {"watched_rank_pairs": WATCHED_RANK_PAIRS}


def _write_rank_watch_config(output_path: str, top_n: int, poll_interval_seconds: float, is_mock: bool) -> None:
    """strategy3_scalp._write_scalp_config과 같은 이유 — 신호가 한 번도 안 뜨면
    state/strategy_4/ 폴더 자체가 안 생겨서 대시보드 전략 목록에 안 보이는 문제를
    막기 위해 시작하자마자 config.json을 쓴다."""
    directory = os.path.dirname(output_path) or "."
    os.makedirs(directory, exist_ok=True)
    config = {
        "strategy": STRATEGY_NAME,
        "top_n": top_n,
        "interval_seconds": poll_interval_seconds,
        "is_mock": is_mock,
        "mode": "signal_only",
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    with open(os.path.join(directory, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def run_rank_watch_loop(
    client: KiwoomClient,
    bot_token: str,
    chat_id: str,
    output_path: str = DEFAULT_SIGNAL_LOG_PATH,
    top_n: int = DEFAULT_TOP_N,
    poll_interval_seconds: float = 10.0,
    stop_flag_path: str | None = None,
) -> None:
    """정규장 동안 거래대금 순위를 반복 재조회해, 4→3위/5→4위/6→5위로 올라서는 종목이
    있으면 각각 텔레그램 알림과 신호 로그만 남긴다. 주문은 절대 내지 않는다.

    stop_flag_path: 대시보드 "중지" 버튼의 우아한 종료 플래그(stop_control.py) — 다른
    전략 루프들과 동일한 규칙(미지정 시 output_path와 같은 폴더, 시작 시 자동 clear)."""
    stop_flag_path = stop_flag_path or os.path.join(os.path.dirname(output_path) or ".", "stop_requested.json")
    clear_stop_flag(stop_flag_path)
    write_heartbeat(os.path.dirname(output_path) or ".")  # 첫 조회 전에도 "실행 중"으로 즉시 보이게
    _write_rank_watch_config(output_path, top_n, poll_interval_seconds, client.is_mock)

    pairs_text = ", ".join(f"{f}위→{t}위" for f, t in WATCHED_RANK_PAIRS)
    print(
        f"전략4(거래대금 순위 감시) 시작 — top{top_n} 재조회, {poll_interval_seconds}초 간격. "
        f"{pairs_text} 승격 시 알림. 주문 없음. 중단하려면 Ctrl+C.",
        flush=True,
    )

    previous_ranks: dict = {}
    previous_names: dict = {}
    while is_market_open(datetime.now()) and not is_stop_requested(stop_flag_path):
        try:
            rows = get_trading_value_ranking(client.appkey, client.secretkey, client.is_mock, "regular", top_n=top_n)["rows"]
            current_ranks = {row["stock_code"]: row["rank"] for row in rows}
            current_names = {row["stock_code"]: row["name"] for row in rows}
        except Exception as exc:
            print(f"순위 조회 실패 - {exc}", flush=True)
            write_heartbeat(os.path.dirname(output_path) or ".")
            time.sleep(poll_interval_seconds)
            continue

        for promoted_code, from_rank, to_rank in check_rank_promotions(previous_ranks, current_ranks):
            name = previous_names.get(promoted_code, "")
            label = f"{name}({promoted_code})" if name else promoted_code
            entry = {
                "stock_code": promoted_code, "name": name,
                "from_rank": from_rank, "to_rank": to_rank,
                "detected_at": datetime.now().isoformat(),
            }
            print(f"[신호] {entry}", flush=True)
            directory = os.path.dirname(output_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(output_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            send_telegram(
                f"[{STRATEGY_NAME}] [순위변동] {label} 거래대금 {from_rank}위 → {to_rank}위",
                bot_token, chat_id,
            )

        previous_ranks = current_ranks
        previous_names = current_names
        write_heartbeat(os.path.dirname(output_path) or ".")
        time.sleep(poll_interval_seconds)
