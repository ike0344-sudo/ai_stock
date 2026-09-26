"""애프터장(15:30 이후) 거래대금 상위 — 수집 전용.

## 왜 베이스라인을 빼야 하나

ka10032(거래대금상위)는 **시간외분만 따로 주지 않는다.** 15:30 이후에 쳐도 값은 항상
"오늘 지금까지의 전체 누적"이다(2026-09-21 19:58 실측: 삼성전자 통합 9.15조·33.7백만주
= 하루치 전체. trading_value_ranking.py:6-8 의 과거 조사와도 일치). 시간외 전용 순위
TR도 없다(ka10098 은 rkinfo URI 에 없음 — [1504] 응답).

그래서 **15:35 시점의 누적을 베이스라인으로 찍어두고 빼서** 시간외분을 만든다.
정규장 순위(trading_value_ranking.py)가 09:00 베이스라인으로 쓰는 것과 같은 수법이다.

## 베이스라인을 왜 하필 15:33~15:39 에 찍나 (실측으로 정한 값)

로컬 틱(data/stocks/tick_al, 168종목 x 33일)으로 15:15~16:10 을 분단위 집계한 결과:

    15:21~15:29   0억          <- 종가 동시호가, 체결이 아예 없음
    15:30    238,792억         <- 종가 동시호가 일괄 체결 (하루 중 가장 큰 1분)
    15:32     11,821억 (15틱)  <- 대량/바스켓 매매
    15:33~15:39   0억          <- 조용한 구간  ** 여기가 안전한 창 **
    15:40      3,940억         <- 시간외종가 시작
    16:00~   ~1,200억/분       <- 시간외단일가

15:30 의 종가 동시호가(238,792억)는 평범한 시간외 1분(~1,200억)의 **200배**다. 이걸
베이스라인에 못 넣으면 통째로 "시간외"로 분류돼 순위가 종가 동시호가 물량으로 도배된다
— 기능 자체가 무의미해진다. 그래서 15:30 체결이 반영된 **뒤**, 시간외종가가 시작되는
15:40 **전**에 찍는다. 이 구간은 체결이 0이라 언제 찍어도 값이 같다.

(15:32 대량매매는 이 창에서 베이스라인 쪽에 들어가 시간외에서 빠진다 — 공시·뉴스로
대금이 몰리는 현상과 대량매매는 다르다고 보고 뺐다. 넣고 싶으면 SNAPSHOT_FROM 을
15:31 로 당기면 된다.)

## 기준가는 왜 KRX 로 따로 받나

사용자 요구는 "KRX 15:30 종가 대비 등락률"이다. 통합(stex_tp=3) 응답의 cur_prc 는
**가장 최근 체결이 난 거래소를 따라가서**, NXT 가 20:00 까지 도는 탓에 15:30 이후엔
NXT 가격이 된다(실측 19:58 삼성전자: KRX 274,500 vs 통합 275,000). 그대로 쓰면 기준가가
오염되므로 베이스라인 스냅샷을 KRX(stex_tp=1)로도 한 번 찍어 그 cur_prc 를 종가로 쓴다.
15:33~15:39 는 KRX 에 체결이 없는 구간이라 이때의 KRX 현재가 = 15:30 종가다.
(응답의 flu_rt 는 **전일** 종가 대비라 못 쓴다 — 직접 계산한다.)

## 베이스라인이 없는 종목을 0으로 치면 안 된다

정규장 쪽(_apply_regular_session_baseline)은 베이스라인에 없는 종목을 0으로 친다.
장전 물량이 작아서 무해하기 때문인데, **15:30 베이스라인에서 같은 짓을 하면 그 종목의
정규장 하루치 전체가 "시간외"로 둔갑해 1위로 튀어오른다.** 그래서 여기서는 0 으로 치지
않고 **순위에서 빼고 그 수를 남긴다**(excluded_no_baseline). 베이스라인을 라이브 폴링보다
깊게 받는 이유도 이 제외를 줄이기 위해서다(하루 1회라 깊어도 싸다).

## 대시보드와의 경계

이 모듈(수집)이 state/afterhours_ranking.json 에 쓰고, 대시보드는 그 파일만 읽는다.
HTTP 요청이 API 를 트리거하지 않는다 — 요청 처리 중에 라이브 조회를 하는
/api/trading-value-ranking 과 달리 완전히 분리돼 있다.
"""
import json
import logging
import os
import threading
import time
from datetime import date, datetime
from datetime import time as clock_time

import pandas as pd

from fetch_chart import MINUTE_COLUMN_MAP, find_records, to_dataframe
from kiwoom_client import KiwoomClient

from .screener import top_by_trading_value

logger = logging.getLogger(__name__)

BASELINE_PATH = "state/afterhours_baseline.json"
STATE_PATH = "state/afterhours_ranking.json"

# 시간외 구간. 15:30 정각(종가 동시호가)은 정규장 몫이라 베이스라인에 들어간다.
AFTERHOURS_START = clock_time(15, 30)
AFTERHOURS_END = clock_time(20, 0)          # NXT 애프터마켓 종료
# 20:00 에 딱 멈추면 마지막으로 저장된 값이 19:59 폴링분이라 장 마감 직전 체결이 빠진다.
# 값은 20:00 이후 더 안 변하므로, 몇 분 더 돌며 **그날의 최종치**를 확정해 둔다
# (화면에서 "장 종료 — 최종"으로 보여주는 값이 이것이다).
REFRESH_GRACE_END = clock_time(20, 5)

# 베이스라인 스냅샷 창 — 위 docstring 의 분단위 실측으로 정한 값.
SNAPSHOT_FROM = clock_time(15, 33)
SNAPSHOT_TO = clock_time(15, 39)

# 라이브 폴링 깊이. 실측 근거: 시간외 대금 35위 값이 33일 전부 78억 이상이었고(중앙값
# 109억), 2026-09-21 기준 누적 500위 문턱이 73억이었다. "누적 >= 시간외" 이므로 누적
# top500 안에 시간외 top35 가 전부 들어온다. 마진이 7% 라 얇아 보이지만 이 78억은
# 하한선이다(표본 168종목 -> 실제 2,575종목이면 35위 값이 더 올라간다).
LIVE_TOP_N = 500
# **페이지 수로 깊이를 정한다.** 커버리지 근거(500위=73억)는 ETF/스팩을 걸러내기 **전**
# raw 순위로 쟀는데, top_n=500 으로 부르면 "필터 후 500종목"을 채우느라 8페이지(raw 800위)
# 까지 판다 — 근거보다 3페이지를 더 도는 셈이었다. 5페이지면 근거와 정확히 같은 범위다.
#   실측 2026-09-22: 8페이지 8.01초(500종목) -> 5페이지 4.59초(362종목, 최하위 누적 78억)
#   시간외 35위값(어제 102억) > 78억 이므로 커버리지 보장은 그대로 성립한다.
LIVE_MAX_PAGES = 5
# 라이브는 통짜로 안 받고 **순환**한다(_fetch_live_pool). 훑는 전체 깊이 = raw 700.
# 5페이지 통짜(raw 500)보다 오히려 깊다 — 실측에서 시간외 top35 의 최대 누적순위가
# 660위였고 기존 설정은 그걸 놓치고 있었다.
LIVE_PAGES = 7
_pool: dict[str, dict] = {}        # 종목코드 -> 마지막으로 받은 누적값(+_fetched_at)
_pool_date: str | None = None
_next_deep_page = 2
# 베이스라인은 라이브보다 깊게 — 여기 없는 종목은 순위에서 통째로 빠지기 때문이다.
# 하루 1회뿐이라 깊이의 비용이 거의 없다(2026-09-21 기준 1000위 누적 문턱 16억).
BASELINE_TOP_N = 1200

# 주기 20초. **예전 60초의 근거("KRX 시간외단일가는 10분 단위 단일가라 60초면 충분")는
# 틀렸다** — 2026-09-21 삼성전자 분봉을 거래소별로 갈라 확인한 결과:
#     KRX(접미사 없음)  16:00~18:00  체결난 분 120/120,  18:00~20:00  119/120
#     NXT(_NX)         16:00~18:00  체결난 분 120/120,  18:00~20:00  119/120
# 두 거래소 다 20:00 까지 **사실상 매 분 연속거래**다. 단일가라 느려도 된다는 전제가
# 성립하지 않아, 시간대를 나누지 않고 전 구간을 똑같이 당긴다(느려도 되는 구간이 없다).
#
# 429 예산(ka10032 는 TR당 초당 1회 수준, **계정 단위**라 앱키를 나눠도 안 나뉜다):
#     1차: (8페이지 + 토큰 1) / 60초  = 0.15 회/초
#     2차: 5페이지 / 20초             = 0.25 회/초
#     지금: 2페이지(1 + 순환 1) / 5초 = 0.40 회/초
#     같은 TR 을 쓰는 trading_value_ranking 폴러가 약 0.2 회/초
#     합계 약 0.60 회/초 — 한도(초당 1회)의 60%. 40% 를 마진으로 남긴다.
#
# 마진을 40% 나 남기는 이유: 429 가 나면 순위 갱신이 **멈춰서 화면이 얼어붙는다**.
# 느린 것보다 나쁘다. sleep 을 3초로 더 당기면 0.5 회/초(합계 0.7)가 되는데, 다른
# 프로세스(소피증권 등)가 같은 계정으로 무엇을 부르는지 내가 다 통제하지 못하므로
# 그만큼은 안 당겼다.
POLL_SECONDS = 5.0

_lock = threading.Lock()


def is_afterhours(now: datetime) -> bool:
    """평일 15:30~20:00 만. 공휴일 캘린더는 안 본다(기존 is_market_open 과 같은 한계)."""
    if now.weekday() >= 5:
        return False
    return AFTERHOURS_START <= now.time() <= AFTERHOURS_END


def should_refresh(now: datetime) -> bool:
    """지금 순위를 다시 계산해야 하나 — 시간외 구간 + 마감 직후 유예(20:05)까지.

    is_afterhours 와 일부러 분리했다: 화면의 '갱신 중' 표시(active)는 20:00 에 꺼져야
    맞지만, **저장되는 값**은 20:00 직후 한 번 더 받아야 그날 최종치가 된다."""
    if now.weekday() >= 5:
        return False
    return AFTERHOURS_START <= now.time() <= REFRESH_GRACE_END


def in_baseline_window(now: datetime) -> bool:
    """베이스라인을 찍어도 되는 조용한 구간인가 (15:33~15:39)."""
    if now.weekday() >= 5:
        return False
    return SNAPSHOT_FROM <= now.time() <= SNAPSHOT_TO


def compute_afterhours_rows(
    current_rows: list[dict], baseline: dict, top_n: int = 35
) -> tuple[list[dict], dict]:
    """현재 누적에서 베이스라인을 빼 시간외분만 남기고 **거래대금순**으로 정렬한다.

    current_rows: screener.top_by_trading_value 가 준 행들(통합 기준 누적)
    baseline: {종목코드: {"trading_value", "volume", "close_price"}} — 15:35 스냅샷

    반환: (상위 top_n 행, 통계dict)

    등락률은 "KRX 15:30 종가 대비"다. 기준가가 없거나 0이면 **None** — 0 으로 두면
    "안 움직였다"로 보여서 거짓말이 된다(진짜 보합과 구분이 안 됨).
    """
    rows, excluded_no_baseline, excluded_no_trade, missing_close = [], [], 0, 0
    for row in current_rows:
        code = row.get("stock_code")
        base = baseline.get(code)
        if base is None:
            # 0 으로 치면 정규장 하루치가 통째로 시간외로 둔갑한다(모듈 docstring).
            excluded_no_baseline.append(code)
            continue

        after_value = row.get("trading_value", 0) - base.get("trading_value", 0)
        after_volume = row.get("volume", 0) - base.get("volume", 0)
        if after_value <= 0:
            excluded_no_trade += 1      # 15:30 이후 거래가 없었던 종목
            continue

        close_price = base.get("close_price")
        current_price = row.get("current_price")
        if close_price and current_price:
            change_pct = (current_price - close_price) / close_price * 100
        else:
            change_pct = None           # 기준가 없음 — 0 이 아니라 '모름'
            missing_close += 1

        rows.append({
            "stock_code": code,
            "name": row.get("name"),
            "after_trading_value": after_value,
            "after_volume": after_volume,
            "change_vs_close_pct": change_pct,
            "current_price": current_price,
            "close_price": close_price,
            "day_trading_value": row.get("trading_value", 0),
        })

    # 순위 기준은 등락률이 아니라 **거래대금**이다(사용자 명시).
    rows.sort(key=lambda r: r["after_trading_value"], reverse=True)
    for i, row in enumerate(rows):
        row["rank"] = i + 1

    # 커버리지가 지금 실제로 성립하나 — "누적 >= 시간외" 라서 후보군(누적 상위)의
    # 최하위 누적값보다 큰 시간외 대금은 반드시 후보군 안에 있다. 뒤집으면 표의 꼴찌
    # 값이 그 문턱보다 **작으면** 후보군 밖에 더 큰 종목이 있을 수 있다는 뜻이다
    # (장 초반엔 시간외 물량이 작아 흔히 그렇다). 조용히 넘어가지 않고 화면에 알린다.
    pool_floor = min((r.get("trading_value", 0) for r in current_rows), default=0)
    tail_guaranteed = bool(rows) and rows[min(len(rows), top_n) - 1]["after_trading_value"] >= pool_floor

    stats = {
        "candidates": len(current_rows),
        "ranked": len(rows),
        "pool_floor": pool_floor,
        "tail_guaranteed": tail_guaranteed,
        "excluded_no_baseline": len(excluded_no_baseline),
        "excluded_no_baseline_codes": excluded_no_baseline[:20],
        "excluded_no_trade": excluded_no_trade,
        "missing_close_price": missing_close,
    }
    return rows[:top_n], stats


def _write_json(path: str, payload: dict) -> None:
    """임시파일 + os.replace — 대시보드가 읽는 도중 잘린 파일을 만나지 않게(원자적 교체).
    data_loader._atomic_to_csv 와 같은 이유다."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)


def _read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def load_baseline(now: datetime, path: str = BASELINE_PATH) -> dict | None:
    """오늘자 베이스라인만 돌려준다. 날짜가 다르면 None — 어제 베이스라인으로 오늘
    시간외분을 계산하면 값이 통째로 엉킨다."""
    data = _read_json(path)
    if not data or data.get("date") != now.date().isoformat():
        return None
    return data.get("baseline") or None


_client_lock = threading.Lock()
_client: KiwoomClient | None = None
_client_key: tuple | None = None


def _get_client(appkey: str, secretkey: str, is_mock: bool) -> KiwoomClient:
    """폴링마다 KiwoomClient 를 새로 만들면 `self.token=None` 이라 **매번 토큰을 새로
    발급받는다**(실측 0.22초 + 요청 1회 = 하루 수백 회 낭비). 토큰이 무효화되면
    request_tr 이 알아서 재발급하므로(`_is_invalid_token_response`) 재사용이 안전하다.

    덤이 더 크다: 인스턴스를 공유하면 **자기제한(1.1초) 상태도 공유**된다. 예전엔
    폴링마다 새 인스턴스라 `_last_request_at=None` 으로 시작해, 직전 폴링이 방금
    끝났어도 첫 요청이 간격 없이 바로 나갔다 — 429 예산 관점에서 이게 더 위험했다.
    """
    global _client, _client_key
    with _client_lock:
        if _client is None or _client_key != (appkey, secretkey, is_mock):
            _client = KiwoomClient(appkey, secretkey, is_mock=is_mock)
            _client_key = (appkey, secretkey, is_mock)
        return _client


def _fetch(appkey: str, secretkey: str, is_mock: bool, top_n: int, exchange: str,
           max_pages: int | None = None, page: int | None = None) -> list[dict]:
    client = _get_client(appkey, secretkey, is_mock)
    # **스팩 포함(exclude_spac=False).** 합병 공시가 시간외에 터지는 종목군이라 보고
    # 싶다는 사용자 요청(2026-09-22). ETF/ETN 은 그대로 제외된다 —
    # `_is_excluded_instrument` 가 스팩과 ETF/ETN 을 따로 판정하기 때문이다.
    #
    # **이 값을 여기 한 곳에서만 정하는 게 핵심이다.** 베이스라인·라이브·백필이 전부 이
    # 함수를 지나므로 기준이 갈려 "한쪽에만 있는 종목"이 생길 수 없다(구조적으로 방지).
    # 라이브만 켜면 그 스팩은 15:35 베이스라인이 없어 시간외분을 못 구한다.
    #
    # screener 기본값(exclude_spac=True)은 **안 건드린다** — 전략·백테스트가 같은 함수를
    # 쓰는데 거기까지 스팩이 섞이면 실거래 판단이 바뀐다. 그건 별개 결정이다.
    #
    # 커버리지 문턱은 안 변한다(실측 2026-09-22): 문턱은 API 가 정한 raw 500위의
    # 누적값이고, 로컬 필터는 그 창 **안에서** 행을 덜어낼 뿐 창의 끝을 못 옮긴다.
    #   5페이지 스팩제외 363종목/문턱 79억  vs  스팩포함 365종목/문턱 79억 (동일)
    # 그래서 페이지를 늘릴 필요가 없고 조회 시간도 그대로다.
    df = top_by_trading_value(
        client, top_n=top_n, max_pages=max_pages or (top_n // 100) + 5, exchange=exchange,
        exclude_spac=False, page=page,
    )
    return df.to_dict("records")


def _fetch_live_pool(appkey: str, secretkey: str, is_mock: bool, now: datetime) -> list[dict]:
    """**1페이지는 매번, 깊은 페이지는 한 사이클에 하나씩 순환**해서 받아 누적 풀을 갱신한다.

    왜 이렇게 하나 (실측 2026-09-22 16:20, 오늘 베이스라인으로 계산):
        시간외 top35 의 누적 raw 순위 분포 -> 1페이지 안에 32/35(91%), 최대 660위
        즉 **대부분은 누적 상위 100위 안에 있고**, 꼬리만 가끔 깊은 곳에서 올라온다.
    그래서 1페이지만 매 사이클 받으면 91% 가 즉시 갱신되고, 나머지는 순환으로 따라온다.

    비용: 2콜(1페이지 + 깊은 페이지 1개) = 약 1.2초. 5페이지 통짜(4.5초)의 1/4 이다.
    (1페이지는 직전 요청과 간격이 벌어져 대기가 없어 0.09초, 두 번째가 1.1초 대기.)

    커버리지는 오히려 **깊어진다**: LIVE_PAGES=7 -> raw 700 까지 훑는다. 기존 5페이지
    통짜는 raw 500 이라 위 실측의 660위 종목을 **놓치고 있었다**(34/35).

    신선도 차이는 숨기지 않는다 — 행마다 `_fetched_at` 을 남겨 화면에 나이를 표시한다.
    값이 낡으면 **과소평가 방향으로만** 틀린다(누적 거래대금은 줄지 않으므로) — 즉 낡은
    종목이 없는 자리를 차지하는 일은 없고, 늦게 올라올 뿐이다.
    """
    global _pool, _pool_date, _next_deep_page
    today = now.date().isoformat()
    if _pool_date != today:            # 날이 바뀌면 누적값 자체가 리셋된다
        _pool, _pool_date, _next_deep_page = {}, today, 2

    deep = _next_deep_page
    _next_deep_page = 2 if deep >= LIVE_PAGES else deep + 1

    stamped = time.time()
    for page in (1, deep):
        for rec in _fetch(appkey, secretkey, is_mock, 0, "3", page=page):
            rec["_fetched_at"] = stamped
            _pool[rec["stock_code"]] = rec
    return list(_pool.values())


def capture_baseline(
    appkey: str, secretkey: str, is_mock: bool, now: datetime | None = None,
    path: str = BASELINE_PATH,
) -> dict:
    """15:33~15:39 조용한 창에서 베이스라인을 한 번 찍어 저장한다.

    두 번 받는다: 통합(3)은 거래대금/거래량용, KRX(1)은 **기준가(15:30 종가)**용.
    이미 오늘자로 찍혀 있으면 아무것도 안 한다(하루 1회).

    반환: {"captured": bool, "count": int, "reason": str}
    """
    now = now or datetime.now()
    if load_baseline(now, path) is not None:
        return {"captured": False, "count": 0, "reason": "이미 오늘자 베이스라인이 있음"}
    if not in_baseline_window(now):
        return {"captured": False, "count": 0, "reason": "베이스라인 창(15:33~15:39)이 아님"}

    combined = _fetch(appkey, secretkey, is_mock, BASELINE_TOP_N, exchange="3")
    krx = _fetch(appkey, secretkey, is_mock, BASELINE_TOP_N, exchange="1")
    close_by_code = {r["stock_code"]: r.get("current_price") for r in krx}

    baseline = {
        r["stock_code"]: {
            "trading_value": r.get("trading_value", 0),
            "volume": r.get("volume", 0),
            # KRX 쪽에 없는 종목은 기준가를 모른다 -> None. 등락률이 '-'로 나올 뿐
            # 거래대금 순위 자체는 정상 동작한다.
            "close_price": close_by_code.get(r["stock_code"]),
        }
        for r in combined
    }
    _write_json(path, {
        "date": now.date().isoformat(),
        "captured_at": now.strftime("%H:%M:%S"),
        "baseline": baseline,
        "krx_close_count": sum(1 for v in baseline.values() if v["close_price"]),
    })
    logger.info("애프터장 베이스라인 확정: %d종목 (기준가 있는 종목 %d개)",
                len(baseline), sum(1 for v in baseline.values() if v["close_price"]))
    return {"captured": True, "count": len(baseline), "reason": ""}


def refresh_ranking(
    appkey: str, secretkey: str, is_mock: bool, now: datetime | None = None,
    top_n: int = 35, state_path: str = STATE_PATH, baseline_path: str = BASELINE_PATH,
) -> dict:
    """라이브 누적을 받아 시간외 순위를 만들어 상태 파일에 쓴다. 쓴 내용을 그대로 반환.

    베이스라인이 없으면 **새로 계산하지 않는다** — 누적값을 그대로 보여주면 그냥 정규장
    top35 가 되는데 사용자는 그걸 시간외 순위로 **오해**하게 된다. 다만 직전에 제대로
    만들어둔 결과가 있으면 **지우지 않고 그대로 둔다**: 날짜가 바뀌면 그날 베이스라인이
    잡히는 15:39 까지 load_baseline 이 None 을 주는데, 예전엔 그때마다 어제 최종 결과를
    빈 표로 덮어써서 "장 끝나면 종목이 사라지는" 문제가 있었다.
    """
    now = now or datetime.now()
    baseline = load_baseline(now, baseline_path)
    if baseline is None:
        note = ("오늘자 15:35 베이스라인이 아직 없습니다 — 새로 계산할 수 없습니다"
                "(15:33~15:39 에 대시보드가 떠 있어야 잡힙니다. 소급 조회는 불가).")
        prev = _read_json(state_path) or {}
        if prev.get("rows"):
            # 직전 결과 보존. date 는 prev 것을 그대로 둬야 load_ranking 이
            # "언제 자료인지"(stale_date)를 제대로 붙인다.
            payload = {**prev, "error": note, "baseline_missing": True}
        else:
            payload = {"date": now.date().isoformat(), "as_of": now.strftime("%H:%M:%S"),
                       "rows": [], "stats": {}, "error": note, "baseline_missing": True}
        _write_json(state_path, payload)
        return payload

    try:
        current = _fetch_live_pool(appkey, secretkey, is_mock, now)
    except Exception as exc:
        # 직전 스냅샷을 남겨둔다 — 화면을 비우는 것보다 낫다. 대신 사유를 같이 쓴다.
        prev = _read_json(state_path) or {}
        payload = {**prev, "error": f"조회 실패: {type(exc).__name__}: {exc}",
                   "stale_since": prev.get("as_of")}
        _write_json(state_path, payload)
        logger.warning("애프터장 순위 조회 실패: %s", exc)
        return payload

    rows, stats = compute_afterhours_rows(current, baseline, top_n=top_n)
    # 순환 수집이라 행마다 신선도가 다르다 — 표에 실린 것 중 가장 낡은 게 몇 초인지 남긴다.
    # (낡은 값은 과소평가 방향으로만 틀리므로 없는 종목이 끼어들진 않는다.)
    age_by_code = {r["stock_code"]: r.get("_fetched_at") for r in current}
    ages = [time.time() - age_by_code[r["stock_code"]]
            for r in rows if age_by_code.get(r["stock_code"])]
    stats["oldest_row_age_sec"] = round(max(ages), 1) if ages else None
    payload = {
        "date": now.date().isoformat(),
        "as_of": now.strftime("%H:%M:%S"),
        "baseline_at": (_read_json(baseline_path) or {}).get("captured_at"),
        "baseline_count": len(baseline),
        "rows": rows,
        "stats": stats,
        "error": None,
    }
    _write_json(state_path, payload)
    return payload


def _minute_bars(client, code: str, day: date) -> pd.DataFrame:
    """그 종목의 하루치 1분봉. 1페이지(900행)면 09:00~20:00(약 660행)이 다 덮인다(실측)."""
    pages = client.get_minute_chart_pages(code, tic_scope="1", max_pages=1)
    records = []
    for payload in pages:
        records.extend(find_records(payload))
    df = to_dataframe(records, MINUTE_COLUMN_MAP, "%Y%m%d%H%M%S")
    return df[df.index.normalize() == pd.Timestamp(day)]


def backfill_from_minutes(
    appkey: str, secretkey: str, is_mock: bool, day: date,
    top_n: int = 35, candidates: int = LIVE_TOP_N,
    state_path: str = STATE_PATH, progress=None,
) -> dict:
    """베이스라인을 놓친 날의 시간외 순위를 **분봉으로 되살린다**.

    ka10032 는 과거 시점 조회가 없지만 분봉(ka10080)은 그날 09:00~20:00 을 다 준다.
    그래서 15:30 이후 봉만 합치면 베이스라인 없이도 시간외 거래대금이 나온다.

    **거래소는 stex_tp 가 아니라 종목코드 접미사로 고른다** (2026-09-21 실측 —
    ka10080 은 stex_tp 를 통째로 무시했다. 1/2/3 전부 같은 KRX 값이 왔다):

        005930     -> KRX   하루 6.04조 / 시간외 1,900억
        005930_NX  -> NXT   하루 3.16조 / 시간외 7,047억
        005930_AL  -> 통합  하루 9.20조 / 시간외 8,946억   <- 이걸 쓴다

    KRX 분봉만 쓰면 시간외를 4.7배 과소평가한다. 기준가(15:30 종가)만은 KRX 라야
    하므로(NXT 가 섞이면 등락률이 흔들린다) 최종 top_n 에 대해서만 접미사 없는
    코드로 한 번 더 받는다 — 전 종목에 두 번 받지 않으려는 2단계 구성이다.

    거래대금은 봉마다 close*volume 로 근사한다(REST 과거 이력에 체결대금 컬럼이
    없다 — universe.py 와 같은 관례).
    """
    client = _get_client(appkey, secretkey, is_mock)
    # 후보군도 _fetch 를 통한다 — 스팩 포함 여부 같은 기준이 라이브/베이스라인과
    # 갈리면 안 된다(직접 top_by_trading_value 를 부르면 그 기준을 여기서 또 정하게 된다).
    # 라이브(순환)와 같은 깊이인 raw 700 까지 판다. 하루 1회 10분짜리 작업이라
    # 2페이지 더 받는 비용(약 2.2초)이 무의미하고, 실측상 시간외 top35 의 최대
    # 누적순위가 660위까지 내려간 적이 있어 5페이지로는 놓친다.
    pool = _fetch(appkey, secretkey, is_mock, candidates, exchange="3",
                  max_pages=LIVE_PAGES)
    rows, failed = [], []
    for i, rec in enumerate(pool):
        code = rec["stock_code"]
        try:
            bars = _minute_bars(client, f"{code}_AL", day)
            after = bars[bars.index.time > AFTERHOURS_START]
            if after.empty:
                continue
            rows.append({
                "stock_code": code, "name": rec.get("name"),
                "trading_value": float((after["close"] * after["volume"]).sum()),
                "volume": float(after["volume"].sum()),
                "current_price": float(after["close"].iloc[-1]),
            })
        except Exception as exc:       # 조용히 빠지면 "거래 없음"과 구분이 안 된다
            failed.append(code)
            logger.warning("백필 실패 %s: %s", code, exc)
        if progress:
            progress(i + 1, len(pool), code)

    # 2단계: 상위 top_n 만 KRX 분봉으로 15:30 종가를 정확히 받는다.
    rows.sort(key=lambda r: r["trading_value"], reverse=True)
    baseline = {}
    for rec in rows[:top_n]:
        code = rec["stock_code"]
        close = None
        try:
            bars = _minute_bars(client, code, day)          # 접미사 없음 = KRX
            at_close = bars[bars.index.time == AFTERHOURS_START]
            if not at_close.empty:
                close = float(at_close["close"].iloc[-1])
        except Exception as exc:
            logger.warning("기준가 조회 실패 %s: %s", code, exc)
        baseline[code] = {"trading_value": 0, "volume": 0, "close_price": close}

    # 베이스라인을 0으로 둔 형태로 만들어 평소 경로(compute_afterhours_rows)를 그대로 재사용
    ranked, stats = compute_afterhours_rows(rows[:top_n], baseline, top_n=top_n)
    stats["backfill_failed"] = len(failed)
    payload = {
        "date": day.isoformat(), "as_of": "장 종료 후 복원",
        "baseline_at": None, "baseline_count": 0,
        "rows": ranked, "stats": stats, "error": None,
        "backfilled": True,
    }
    _write_json(state_path, payload)
    logger.info("백필 완료: %d종목 중 %d종목 순위 산출(실패 %d)", len(pool), len(ranked), len(failed))
    return payload


def load_ranking(state_path: str = STATE_PATH, now: datetime | None = None) -> dict:
    """대시보드가 읽는 지점 — **파일만 읽는다. API 를 절대 안 친다.**"""
    now = now or datetime.now()
    data = _read_json(state_path)
    if data is None:
        # 아래 정상 경로와 같은 모양으로 돌려준다 — 화면이 필드 유무를 분기하지 않게.
        return {"rows": [], "as_of": None, "active": is_afterhours(now),
                "session_closed": False,
                "error": "아직 수집된 애프터장 순위가 없습니다 (15:30~20:00 에 갱신됩니다)."}
    data["active"] = is_afterhours(now)
    if data.get("date") != now.date().isoformat():
        data["stale_date"] = data.get("date")   # 어제 것이라는 사실을 화면이 알 수 있게
    # 장이 끝난 뒤에도 그날 결과는 계속 보여준다. "갱신이 멈춘 것"과 "그날 최종치가
    # 확정된 것"은 다르므로 화면이 구분해 말할 수 있게 표시만 해준다.
    data["session_closed"] = bool(
        not data["active"] and data.get("rows") and "stale_date" not in data
    )
    return data


def _poll_loop(appkey: str, secretkey: str, is_mock: bool, interval_seconds: float) -> None:
    while True:
        try:
            now = datetime.now()
            if in_baseline_window(now):
                capture_baseline(appkey, secretkey, is_mock, now)
            if should_refresh(now):
                refresh_ranking(appkey, secretkey, is_mock, now)
        except Exception:
            logger.warning("애프터장 폴러 한 사이클 실패", exc_info=True)
        time.sleep(interval_seconds)


def start_background_poller(
    appkey: str, secretkey: str, is_mock: bool, interval_seconds: float = POLL_SECONDS,
) -> threading.Thread:
    """대시보드 서버 프로세스 안에서 도는 수집 스레드 — 브라우저를 안 열어도 15:35
    베이스라인이 잡히게 한다(trading_value_ranking.start_background_poller 와 같은 이유).
    """
    thread = threading.Thread(
        target=_poll_loop, args=(appkey, secretkey, is_mock, interval_seconds),
        name="afterhours-ranking", daemon=True)
    thread.start()
    return thread
