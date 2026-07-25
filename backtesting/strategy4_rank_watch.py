"""전략 4번 — 거래대금 순위 4위였던 종목이 3위로 올라서는 순간을 감지해 알림만
보낸다. 주문은 절대 내지 않는다(strategy3_scalp.py와 같은 관찰전용 계열) — 사용자가
"지금 4등인 종목이 3등으로 올라설 때"로 트리거를 명시적으로 확정했다("3위 자리 자체가
바뀌는 모든 경우"가 아니라, 그 4위 종목 자체를 추적하다가 3위로 올라서는 순간만 본다).

매 사이클 top_by_trading_value(screener.py)로 순위를 다시 조회해 직전 사이클과
비교한다 — 별도 실시간 피드 없이 REST 폴링만으로 충분하다(거래대금 순위는 분 단위로도
크게 안 바뀌는 지표라 기존 전략들처럼 초 단위 실시간 체결까지는 필요 없음).

거래소 기준: 이 전략은 순위 데이터(top_by_trading_value, 통합/KRX+NXT 기준)만 쓴다 —
별도 분봉/호가 조회가 없어 KRX/통합 구분이 추가로 필요한 지점 자체가 없다.
"""
import json
import os
import time
from datetime import datetime

import pandas as pd
from kiwoom_client import KiwoomClient

from .heartbeat import write_heartbeat
from .notifier import send_telegram
from .orderbook_collector import is_extended_market_open
from .screener import top_by_trading_value
from .stop_control import clear_stop_flag, is_stop_requested

STRATEGY_NAME = "strategy_4"
DEFAULT_TOP_N = 10  # 4위/3위만 보면 되지만, 순위 데이터를 위에서부터 채우는 top_by_trading_value 특성상 여유 있게 받아둠
DEFAULT_SIGNAL_LOG_PATH = "state/strategy_4/signals.jsonl"

WATCHED_FROM_RANK = 4
WATCHED_TO_RANK = 3


def describe_strategy_4() -> dict:
    """대시보드 등 조회용 — strategy_catalog.py에 등록되어 describe_strategy_1/2/3와
    같은 패턴으로 노출된다."""
    return {
        "entry": [f"거래대금 순위 {WATCHED_FROM_RANK}위였던 종목이 {WATCHED_TO_RANK}위로 올라서는 순간 포착"],
        "exit": ["청산 로직 없음 — 신호 포착/알림 전용(주문 미실행)"],
        "operation": ["ML 게이트 없음", "매 사이클 거래대금 순위 재조회 후 직전 사이클과 비교"],
        "exchange_basis": ["순위 데이터(거래대금 상위): 통합(KRX+NXT)"],
    }


def check_rank_promotion(previous_ranks: dict, current_ranks: dict) -> str | None:
    """previous_ranks/current_ranks: {stock_code: rank}. 직전 사이클에 4위였던 종목이
    이번 사이클에 3위가 됐으면 그 종목코드를, 아니면 None을 반환.

    직전 사이클에 4위 종목이 없었으면(첫 사이클 등) 비교 자체가 불가능하므로 None."""
    prev_4th = next((code for code, rank in previous_ranks.items() if rank == WATCHED_FROM_RANK), None)
    if prev_4th is None:
        return None
    if current_ranks.get(prev_4th) == WATCHED_TO_RANK:
        return prev_4th
    return None


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Strategy 프로토콜 어댑터 — df에 이 종목의 시점별 거래대금 순위를 담은 'rank'
    컬럼이 있어야 한다(check_rank_promotion은 원래 여러 종목의 순위 dict를 비교하는
    함수라, 한 종목 OHLCV df만으로는 그 dict를 채울 수 없어 직전/현재 순위만 한 쌍씩
    감싸 그대로 호출한다). check_rank_promotion 결과가 있으면 signal=1, 없으면 0."""
    out = df.copy()
    out["signal"] = 0
    prev_rank = out["rank"].shift(1)
    for idx in out.index:
        prev, curr = prev_rank.at[idx], out.at[idx, "rank"]
        if pd.isna(prev) or pd.isna(curr):
            continue
        promoted = check_rank_promotion({"_self": int(prev)}, {"_self": int(curr)})
        if promoted is not None:
            out.at[idx, "signal"] = 1
    return out


generate_signals.name = "strategy_4"
generate_signals.params = {
    "watched_from_rank": WATCHED_FROM_RANK,
    "watched_to_rank": WATCHED_TO_RANK,
}


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
    """정규장 동안 거래대금 순위를 반복 재조회해, 4위 종목이 3위로 올라서면 텔레그램
    알림과 신호 로그만 남긴다. 주문은 절대 내지 않는다.

    stop_flag_path: 대시보드 "중지" 버튼의 우아한 종료 플래그(stop_control.py) — 다른
    전략 루프들과 동일한 규칙(미지정 시 output_path와 같은 폴더, 시작 시 자동 clear)."""
    stop_flag_path = stop_flag_path or os.path.join(os.path.dirname(output_path) or ".", "stop_requested.json")
    clear_stop_flag(stop_flag_path)
    write_heartbeat(os.path.dirname(output_path) or ".")  # 첫 조회 전에도 "실행 중"으로 즉시 보이게
    _write_rank_watch_config(output_path, top_n, poll_interval_seconds, client.is_mock)

    print(
        f"전략4(거래대금 순위 감시) 시작 — top{top_n} 재조회, {poll_interval_seconds}초 간격. "
        f"{WATCHED_FROM_RANK}위→{WATCHED_TO_RANK}위 승격 시 알림. 주문 없음. 중단하려면 Ctrl+C.",
        flush=True,
    )

    previous_ranks: dict = {}
    previous_names: dict = {}
    while is_extended_market_open(datetime.now()) and not is_stop_requested(stop_flag_path):
        try:
            df = top_by_trading_value(client, top_n=top_n)
            current_ranks = dict(zip(df["stock_code"], df["rank"]))
            current_names = dict(zip(df["stock_code"], df["name"]))
        except Exception as exc:
            print(f"순위 조회 실패 - {exc}", flush=True)
            write_heartbeat(os.path.dirname(output_path) or ".")
            time.sleep(poll_interval_seconds)
            continue

        promoted_code = check_rank_promotion(previous_ranks, current_ranks)
        if promoted_code is not None:
            name = previous_names.get(promoted_code, "")
            label = f"{name}({promoted_code})" if name else promoted_code
            entry = {
                "stock_code": promoted_code, "name": name,
                "from_rank": WATCHED_FROM_RANK, "to_rank": WATCHED_TO_RANK,
                "detected_at": datetime.now().isoformat(),
            }
            print(f"[신호] {entry}", flush=True)
            directory = os.path.dirname(output_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(output_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            send_telegram(
                f"[{STRATEGY_NAME}] [순위변동] {label} 거래대금 {WATCHED_FROM_RANK}위 → {WATCHED_TO_RANK}위",
                bot_token, chat_id,
            )

        previous_ranks = current_ranks
        previous_names = current_names
        write_heartbeat(os.path.dirname(output_path) or ".")
        time.sleep(poll_interval_seconds)
