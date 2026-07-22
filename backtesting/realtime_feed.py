"""키움 WebSocket 실시간체결(0B) 구독으로 감시종목 1분봉을 실시간으로 조립한다.

REST 분봉 조회(data_loader.load_history)는 종목 하나당 최소 1회 요청이 필요하고,
키움 REST rate limit(TR당 초당 약 1회, 버스트 2 — 커뮤니티 실측 보고 기준.
kiwoom_client.py의 min_request_interval 참고)에 걸려 35종목을 매 사이클 순회하면
전체 스캔에만 40초 가까이 걸린다. WebSocket은 한 번 구독해두면 이후로는 서버가
체결마다 알아서 밀어주므로(실측: LOGIN→REG 후 2종목만으로 15초에 90건 이상 push),
시작할 때 REST로 오늘자 지금까지의 분봉을 한 번만 백필(backfill)하고 그 이후는
이 모듈이 실시간으로 이어붙이면 매 사이클 REST 호출이 사라진다.

프로토콜은 공식 문서가 SPA라 자동 수집이 안 돼서 모의투자 엔드포인트에 직접 연결해
실측으로 확인했다(2026-07-22, README 아님 — 이 주석이 유일한 기록):
- 연결: wss://{mockapi|api}.kiwoom.com:10000/api/dostk/websocket
- 로그인: {"trnm":"LOGIN","token":<REST OAuth 토큰>} -> {"trnm":"LOGIN","return_code":0,...}
- 구독: {"trnm":"REG","grp_no":"1","refresh":"1","data":[{"item":[종목코드,...],"type":["0B"]}]}
  -> {"trnm":"REG","return_code":0,...}
- 이후 틱마다 {"data":[{"item":"005930","values":{...FID 코드: 값...}}]} 형태로 푸시.
  실측으로 값의 존재/형식만 확인한 주요 FID(레거시 OpenAPI+와 동일 체계로 추정):
    10=현재가, 13=누적거래량(당일), 20=체결시각(HHMMSS), 27=매도최우선호가, 28=매수최우선호가
  가격류 필드는 "+"/"-" 부호가 기준가 대비 방향을 나타내는 키움 관례를 그대로 따른다
  (kiwoom_client.py 파일 상단 docstring 참고) — abs()로 벗겨서 쓴다.
- 서버가 주기적으로 {"trnm":"PING"}을 보내는데, 그대로 되돌려 보내지 않으면(PONG이
  아니라 같은 PING 메시지를 그대로 echo) 연결이 끊긴다(실측 확인).

이 모듈은 종목코드가 데이터에 어느 필드로 오는지 실측하지 못한 경우(예: item이 최상위
레벨에 없고 REG 요청 순서로만 유추해야 하는 경우)에 대비해, REG를 종목별로 한 번씩
따로 보내고 각 구독 그룹(grp_no)을 종목 하나에 매핑하는 방식은 쓰지 않는다 — 대신
푸시 메시지의 "item" 필드를 신뢰하고, 없으면 그 틱은 버린다(신뢰 못 할 데이터로 잘못된
종목의 캔들을 오염시키는 것보다 안전).
"""
import json
import threading
import time
from collections import OrderedDict
from datetime import datetime

import pandas as pd
import websocket

from kiwoom_client import KiwoomClient

RECONNECT_DELAY_SECONDS = 5.0
MAX_BUFFERED_MINUTES = 400  # 정규장 하루(약 391분)치 여유


def _parse_signed(raw) -> float:
    """키움 관례: 가격/등락 필드는 "+"/"-" 부호가 방향을 나타낼 뿐이라 abs()로 벗긴다
    (kiwoom_client.py 파일 상단 docstring과 동일 근거)."""
    try:
        return abs(float(raw))
    except (TypeError, ValueError):
        return 0.0


def parse_tick(values: dict) -> dict | None:
    """0B 푸시의 "values" 딕셔너리에서 캔들 조립에 필요한 필드만 뽑는다.
    가격(10)이나 시각(20)이 없으면(다른 타입의 푸시가 섞여 온 경우 등) None."""
    if "10" not in values or "20" not in values:
        return None
    time_raw = values["20"]
    if len(time_raw) != 6 or not time_raw.isdigit():
        return None
    bid_raw = values.get("28", "")
    return {
        "price": _parse_signed(values["10"]),
        "cum_volume": int(values["13"]) if values.get("13", "").lstrip("-").isdigit() else None,
        "time_hms": time_raw,
        "bid": _parse_signed(bid_raw) if bid_raw else None,
    }


class CandleAggregator:
    """종목 하나의 체결 틱을 누적해 1분봉 OHLCV를 조립하는 순수 상태 머신 — 네트워크와
    무관해 단위 테스트가 쉽다. RealtimeFeed가 종목마다 하나씩 들고 있는다."""

    def __init__(self):
        self.candles: "OrderedDict[str, dict]" = OrderedDict()  # "HHMM" -> {open,high,low,close,volume}
        self._last_cum_volume: int | None = None

    def add_tick(self, tick: dict, trading_date: str) -> None:
        minute_key = tick["time_hms"][:4]  # "HHMM" — 초 단위는 버리고 분봉으로 묶음
        price = tick["price"]
        if price <= 0:
            return

        volume_delta = 0
        if tick["cum_volume"] is not None:
            if self._last_cum_volume is not None:
                volume_delta = max(0, tick["cum_volume"] - self._last_cum_volume)
            self._last_cum_volume = tick["cum_volume"]

        candle = self.candles.get(minute_key)
        if candle is None:
            self.candles[minute_key] = {
                "open": price, "high": price, "low": price, "close": price,
                "volume": volume_delta, "trading_date": trading_date,
            }
            if len(self.candles) > MAX_BUFFERED_MINUTES:
                self.candles.popitem(last=False)
        else:
            candle["high"] = max(candle["high"], price)
            candle["low"] = min(candle["low"], price)
            candle["close"] = price
            candle["volume"] += volume_delta

    def to_dataframe(self) -> pd.DataFrame:
        if not self.candles:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        rows = []
        index = []
        for minute_key, candle in self.candles.items():
            index.append(pd.Timestamp(f"{candle['trading_date']} {minute_key[:2]}:{minute_key[2:]}:00"))
            rows.append({k: candle[k] for k in ("open", "high", "low", "close", "volume")})
        return pd.DataFrame(rows, index=index).sort_index()


class RealtimeFeed:
    """감시종목 리스트를 실시간체결(0B)로 구독하고, 종목별 1분봉을 메모리에 조립해둔다.
    백그라운드 스레드에서 WebSocketApp.run_forever()를 돌리며, 연결이 끊기면 자동
    재연결+재구독한다."""

    def __init__(self, appkey: str, secretkey: str, is_mock: bool, stock_codes: list[str]):
        self.appkey = appkey
        self.secretkey = secretkey
        self.is_mock = is_mock
        self.stock_codes = list(stock_codes)
        self._lock = threading.Lock()
        self._aggregators: dict[str, CandleAggregator] = {code: CandleAggregator() for code in self.stock_codes}
        self._latest: dict[str, dict] = {}  # code -> {"price": float, "bid": float | None} — 청산 감시용 최신 시세
        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._stop = False
        self._connected = threading.Event()

    def _ws_url(self) -> str:
        host = "mockapi.kiwoom.com" if self.is_mock else "api.kiwoom.com"
        return f"wss://{host}:10000/api/dostk/websocket"

    def _on_open(self, ws) -> None:
        client = KiwoomClient(self.appkey, self.secretkey, is_mock=self.is_mock)
        token = client.issue_token()
        ws.send(json.dumps({"trnm": "LOGIN", "token": token}))

    def _on_message(self, ws, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return

        trnm = payload.get("trnm")
        if trnm == "PING":
            ws.send(message)  # 받은 그대로 echo — PONG 필드가 아니라 이 방식이어야 유지됨(실측)
            return
        if trnm == "LOGIN":
            if payload.get("return_code") == 0:
                ws.send(json.dumps({
                    "trnm": "REG", "grp_no": "1", "refresh": "1",
                    "data": [{"item": self.stock_codes, "type": ["0B"]}],
                }))
            return
        if trnm == "REG":
            if payload.get("return_code") == 0:
                self._connected.set()
            return

        for entry in payload.get("data", []):
            code = entry.get("item", "").strip()
            values = entry.get("values")
            if not code or code not in self._aggregators or not values:
                continue
            tick = parse_tick(values)
            if tick is None:
                continue
            with self._lock:
                self._aggregators[code].add_tick(tick, datetime.now().strftime("%Y-%m-%d"))
                self._latest[code] = {"price": tick["price"], "bid": tick["bid"]}

    def _run_forever_with_reconnect(self) -> None:
        while not self._stop:
            self._connected.clear()
            self._ws = websocket.WebSocketApp(
                self._ws_url(), on_open=self._on_open, on_message=self._on_message,
            )
            self._ws.run_forever()
            if self._stop:
                break
            time.sleep(RECONNECT_DELAY_SECONDS)  # 재연결 전 대기 — 즉시 재시도하면 서버 부담

    def start(self, wait_connected_seconds: float = 10.0) -> bool:
        """백그라운드 스레드로 연결을 시작한다. REG 승인까지 wait_connected_seconds
        안에 확인되면 True — 호출부가 "구독이 실제로 됐는지" 확인하고 싶을 때 쓴다."""
        self._thread = threading.Thread(target=self._run_forever_with_reconnect, daemon=True)
        self._thread.start()
        return self._connected.wait(timeout=wait_connected_seconds)

    def stop(self) -> None:
        self._stop = True
        if self._ws is not None:
            self._ws.close()

    def get_minute_df(self, code: str) -> pd.DataFrame:
        with self._lock:
            aggregator = self._aggregators.get(code)
            if aggregator is None:
                return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
            return aggregator.to_dataframe()

    def get_latest_bid(self, code: str) -> float | None:
        """청산 감시용 최우선매수호가(field 28) — 아직 틱을 못 받았으면 None(호출부가
        REST get_stock_quote로 폴백해야 함을 알리는 신호)."""
        with self._lock:
            entry = self._latest.get(code)
            return entry["bid"] if entry else None

    def seed_from_dataframe(self, code: str, df: pd.DataFrame) -> None:
        """REST로 백필한 오늘자 분봉을 실시간 조립 버퍼에 미리 채워 넣는다 — 이렇게 안
        하면 피드가 구독을 시작한 시점 이후 캔들만 남아서, 장 시작부터 필요한 조건
        (당일 신고가, 장중고점 대비 하락폭 등)을 제대로 평가할 수 없다. 백필 분봉엔
        누적거래량 기준선이 없어서, 백필 마지막 분봉과 실시간 첫 틱이 겹치는 구간의
        거래량은 다소 부정확할 수 있다(가격 OHLC는 영향 없음 — detect_entries의 거래대금
        조건에만 미미하게 영향, 그것도 봉 하나에 한정된 부팅 시점의 일회성 오차)."""
        with self._lock:
            aggregator = self._aggregators.get(code)
            if aggregator is None or df.empty:
                return
            for ts, row in df.iterrows():
                minute_key = ts.strftime("%H%M")
                aggregator.candles[minute_key] = {
                    "open": float(row["open"]), "high": float(row["high"]),
                    "low": float(row["low"]), "close": float(row["close"]),
                    "volume": float(row["volume"]), "trading_date": ts.strftime("%Y-%m-%d"),
                }
