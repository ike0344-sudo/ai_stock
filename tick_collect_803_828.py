"""8/03~8/28 체결(ka10079 틱) 수집 — 조회창 20거래일이 매일 밀려 8/03이 곧 범위 밖으로
나가서 급하게 지시받음. 대상: 8/03~8/28 각 거래일 top35 합집합(005930/000660 제외).

    python tick_collect_803_828.py

중단 후 재실행하면 이미 목표(8/03)까지 받은 종목은 건너뛴다(state/tick_collection/progress.json).
원본 dict를 그대로 저장한다(orderbook_collector.py와 같은 이유 — ka10079 전체 필드 스키마를
신뢰할 수 있는 문서로 확인 못 했다).

병렬화(2026-08-30): 실측으로 동시성 2/3/4/5/6 전부 30초씩 429 없이 통과, 감시봇/대시보드
하트비트·에러로그에도 영향 없음(테스트 전후 대조 확인). 6까지 시험했고 그 이상은 위험 대비
이득이 줄어 중단 — 안전 한도를 6으로 보고, 그 80%인 4를 실제 적용값으로 쓴다(사용자 지시,
여유를 둠).

작업 배분은 웨이브(4개씩 묶어 넷 다 끝나야 다음 4개 시작)가 아니라 **연속 큐**다 —
ThreadPoolExecutor(max_workers=4)에 전 종목을 한 번에 submit하면 워커가 하나 끝나는
즉시 다음 종목을 이어받는다. 처음엔 웨이브 방식으로 짰다가 종목당 페이지수 편차가
714~2036(3배 가까이)인 상황에서 느린 종목 하나 때문에 나머지 워커가 노는 걸 실측으로
잡아냈다(4배 기대, 2.8배 실측) — 그래서 큐 방식으로 바꿨다.

429(requests.HTTPError status 429)는 전역 쿨다운(공유 pause_until)으로 처리한다 — 한
워커가 맞으면 그 시각부터 60초간 **모든** 워커가 다음 요청 전에 대기하고(진행 중이던
요청까지 막지는 않음), 이후 그냥 이어서 돈다. 웨이브 단위 동시성 증감 로직은 큐
방식에선 의미가 없어져 뺐다 — ThreadPoolExecutor의 워커 수(4)는 고정, 429가 나면
전역으로 잠깐 쉬었다 다시 그 4명이 그대로 돈다.
"""
import concurrent.futures
import json
import os
import sys
import threading
import time
from datetime import datetime, time as dtime

import requests

sys.path.insert(0, "C:/Users/ike03/Desktop/code/ai_stock")
os.chdir("C:/Users/ike03/Desktop/code/ai_stock")

from dotenv import load_dotenv
import pandas as pd

from backtesting.universe import daily_top_n_from_local
from data_exclude import MEGA_CAP_EXCLUDE
from kiwoom_client import KiwoomClient, raise_if_error

START_DATE = "2026-08-03"
END_DATE = "2026-08-28"
EXCLUDE = MEGA_CAP_EXCLUDE  # 호가 저장과 공유(data_exclude.py) — 여기서 새로 정의 안 함
# daily_top_n_from_local은 D-1 확정 랭킹이라(backtesting/universe.py docstring),
# 어제까지 조용하다가 오늘 처음 터진 종목은 그날 top35에 들어도 유니버스에서
# 빠진다 — 전략1이 노리는 신고가/급등 종목이 정확히 이 패턴이라 구조적 한계다.
# 사용자 지시(2026-08-30)로 8/03~8/28 각 거래일 "당일" close*volume 상위 35위
# 합집합을 직접 계산해 D-1 합집합(115종목)과 대조 — 차집합은 정확히 032820(우리
# 기술, 8/28 day-of 31위)과 030530(8/28 day-of 18위) 두 개뿐이고(D-1에만 있고
# 당일엔 없는 종목은 0개), 사용자가 미리 계산한 115/117 수치와 정확히 일치함을
# 검증했다. 돌고 있는 수집을 죽이지 않기 위해 build_universe() 전체를 day-of
# 방식으로 새로 짜는 대신, 이미 같은 결과를 내는 이 최소 패치(차집합만 수동
# 추가)로 처리한다 — 우선순위 최하위, 다음 재시작 때 목록 끝에 붙는다. 나중에
# intraday_top_n_return_rank1_by_minute 기준으로 옮기면 이 갭 자체가 사라지고,
# 그때는 수집 대상을 다시 계산해야 한다.
EXTRA_CODES = {"032820", "030530"}
TICK_DIR = "data/stocks/tick"
DAILY_DIR = "data/stocks/daily"
PROGRESS_PATH = "state/tick_collection/progress.json"
LOG_PATH = "state/tick_collection/log.txt"
REPORT_DIR = "state/agent_reports"
PROGRESS_REPORT_PATH = f"{REPORT_DIR}/data-agent_tick_progress.md"
REPORT_EVERY_N = 20
REPORT_EVERY_SEC = 3600
# 2026-08-31 사고(tick_collect_804_828_al.py에서 실제로 겪음): 카운트조건(20개)+
# 시간조건(1시간) 둘 다 필요하면 막판에 속도가 느려져 20개를 못 채운 채 끝나버릴 수
# 있다 — 이 스크립트는 이미 완주했지만 같은 패턴이라 나중에 재사용할 때를 대비해
# 같이 고쳐둔다.
FORCE_REPORT_EVERY_SEC = 1800
MARKET_OPEN, MARKET_CLOSE = dtime(9, 0), dtime(15, 30)

MEASURED_SAFE_CONCURRENCY = 6  # 2026-08-30 실측(30초씩 429 0건, 그 이상은 미시험)
MAX_CONCURRENCY = int(MEASURED_SAFE_CONCURRENCY * 0.8)  # = 4, 여유 20%
RATE_LIMIT_COOLDOWN_SEC = 60

APPKEY = None
SECRET = None
IS_MOCK = None

_log_lock = threading.Lock()
_progress_lock = threading.Lock()
_rate_limit_lock = threading.Lock()
_rate_limit_pause_until = [0.0]  # 전역 429 쿨다운 — 모든 워커가 공유


def wait_out_rate_limit_pause() -> None:
    while True:
        with _rate_limit_lock:
            remaining = _rate_limit_pause_until[0] - time.time()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 5))


def trigger_rate_limit_pause(code: str) -> None:
    with _rate_limit_lock:
        new_until = time.time() + RATE_LIMIT_COOLDOWN_SEC
        if new_until > _rate_limit_pause_until[0]:
            _rate_limit_pause_until[0] = new_until
    log(f"{code}: 429 발생 - 전역 {RATE_LIMIT_COOLDOWN_SEC}초 쿨다운(모든 워커가 대기)")


def is_market_hours(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    if now.weekday() >= 5:  # 토/일
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


def pause_if_market_hours(log_once: list[bool]) -> None:
    """실거래(screener/감시봇)가 같은 키움 API를 쓴다 — 장중에 같이 때리면 429로
    그쪽까지 막힌다. 페이지 요청 직전마다 확인해, 종목 하나가 장 시작에 걸쳐도
    바로 그 자리에서 멈췄다가 마감 후 같은 next_key로 이어받는다."""
    while is_market_hours():
        if not log_once[0]:
            log("장중(09:00~15:30) 감지 - 실거래 API 충돌 방지를 위해 일시정지, 15:35 이후 재개")
            log_once[0] = True
        time.sleep(300)


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    with _log_lock:
        print(line, flush=True)
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def load_progress() -> dict:
    if os.path.isfile(PROGRESS_PATH):
        return json.loads(open(PROGRESS_PATH, encoding="utf-8").read())
    return {"done": [], "started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "total": 0}


def save_progress(p: dict) -> None:
    os.makedirs(os.path.dirname(PROGRESS_PATH), exist_ok=True)
    tmp = f"{PROGRESS_PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PROGRESS_PATH)


def build_universe() -> list[str]:
    """top35 등장 횟수 내림차순으로 정렬 — 자주 등장한 종목일수록 백테스트에서
    실제로 신호를 낼 가능성이 높으므로, 중간에 실패하거나 시간이 모자라도
    중요한 것부터 확보되게 한다."""
    ranked = daily_top_n_from_local(top_n=35)
    dates = [d for d in ranked if START_DATE <= d.strftime("%Y-%m-%d") <= END_DATE]
    from collections import Counter

    count: Counter[str] = Counter()
    for d in dates:
        count.update(ranked[d])
    for code in EXCLUDE:
        count.pop(code, None)
    ranked_codes = [code for code, _ in count.most_common()]
    # EXTRA_CODES는 D-1 랭킹 구조상 빠진 종목을 수동 보충한 것 — 등장 횟수 집계가
    # 없으므로 최우선순위 목록 끝에 붙여 낮은 우선순위로 둔다(사용자 지시).
    for code in EXTRA_CODES:
        if code not in count:
            ranked_codes.append(code)
    return ranked_codes


class SharedToken:
    """워커 스레드마다 독립 KiwoomClient를 쓰되 토큰은 하나만 공유한다 — 각자
    issue_token()을 부르면 같은 appkey의 토큰이 서로를 무효화해(실측 문서화됨,
    kiwoom_client.py request_tr 주석) 재발급 폭주가 난다. 8005(토큰무효)를 만난
    스레드는 이 클래스를 통해서만 재발급한다 — 이미 다른 스레드가 갱신해놨으면
    재발급하지 않고 새 값만 받아간다."""

    def __init__(self, bootstrap_client: KiwoomClient):
        self._client = bootstrap_client
        self._lock = threading.Lock()
        self.value = bootstrap_client.token

    def refresh_if_stale(self, stale_value: str) -> str:
        with self._lock:
            if self.value == stale_value:
                self._client.issue_token()
                self.value = self._client.token
                log("공유 토큰 재발급됨")
            return self.value


def make_worker_client(shared_token: SharedToken) -> KiwoomClient:
    c = KiwoomClient(APPKEY, SECRET, is_mock=IS_MOCK)
    c.token = shared_token.value
    return c


def _fetch_once(client: KiwoomClient, code: str, log_once: list[bool]) -> tuple[dict[str, list[dict]], str | None, int]:
    """한 번의 전체 페이지네이션 시도. (날짜별 원본 행, 최고(最古) 도달일, 페이지수)를 반환.
    requests.exceptions.HTTPError(429)는 여기서 안 잡고 그대로 위로 던진다 — collect_one이
    전역 쿨다운을 걸고 재시도한다."""
    body = {"stk_cd": code, "tic_scope": "1", "upd_stkpc_tp": "1"}
    cont_yn, next_key = "N", ""
    by_date: dict[str, list[dict]] = {}
    min_date_seen = None
    pages = 0
    while True:
        pause_if_market_hours(log_once)
        wait_out_rate_limit_pause()
        payload = client.request_tr("ka10079", body, path="/api/dostk/chart", cont_yn=cont_yn, next_key=next_key)
        pages += 1
        # 8/30 05:03경 이 체크가 없어서 79종목이 빈 채로 "완료" 처리된 사고가 있었다.
        raise_if_error(payload)
        chunk = payload.get("stk_tic_chart_qry", [])
        if not chunk:
            log(f"{code}: 빈 응답(return_code=0, 정상 종료로 보임) - cont_yn={client.last_cont_yn!r}, pages_so_far={pages}")
            break
        for r in chunk:
            t = r.get("cntr_tm", "")
            if len(t) < 8:
                continue
            d = f"{t[0:4]}-{t[4:6]}-{t[6:8]}"
            by_date.setdefault(d, []).append(r)
            if min_date_seen is None or d < min_date_seen:
                min_date_seen = d
        # 2026-08-30 경계일 절단 사고: <=로 잡으면 START_DATE에 "처음 닿는 순간"
        # 멈춰버린다 — 최신부터 거슬러 올라가는 방식이라 그 순간의 페이지에는
        # START_DATE의 늦은 시각(장마감 근처) 일부만 담겨 있고 이른 시각(장시작 쪽)은
        # 아직 안 받은 상태다. 실측: 109종목 전부 8/03이 09:00이 아니라 11:01~15:19
        # 사이 어딘가부터만 남았다(유동성 높을수록 페이지 하나가 짧은 시간만 담아
        # 더 심하게 잘림). START_DATE보다 "엄격히 이전" 날짜를 봐야 그날 전체를
        # 지나쳤다고 확신할 수 있다.
        if min_date_seen is not None and min_date_seen < START_DATE:
            break
        if client.last_cont_yn != "Y" or not client.last_next_key:
            break
        cont_yn, next_key = "Y", client.last_next_key
    return by_date, min_date_seen, pages


def check_price_sanity(code: str, by_date: dict[str, list[dict]]) -> str | None:
    """병렬화로 응답이 섞이면(엉뚱한 종목 파일에 쓰임) 가격대가 확 어긋난다 — 로컬
    일봉의 그 날짜 고가/저가와 틱 체결가 범위를 대조해 자릿수가 다르게 벗어나면
    잡아낸다. 문제 있으면 이유 문자열, 없으면 None."""
    daily_path = f"{DAILY_DIR}/{code}.csv"
    if not os.path.isfile(daily_path):
        return None  # 대조할 로컬 일봉이 없으면 판단 보류(막지 않음)
    daily = pd.read_csv(daily_path, parse_dates=["date"])
    daily["d"] = daily["date"].dt.strftime("%Y-%m-%d")
    tick_prices = [int(r["cur_prc"]) for rows in by_date.values() for r in rows if str(r.get("cur_prc", "")).strip()]
    if not tick_prices:
        return None
    tick_min, tick_max = min(tick_prices), max(tick_prices)
    for d in by_date:
        row = daily[daily["d"] == d]
        if row.empty:
            continue
        lo, hi = float(row["low"].iloc[0]), float(row["high"].iloc[0])
        # 배당락/이벤트 등 사소한 차이는 있을 수 있으니 넉넉하게(±50%) 잡되, 자릿수가
        # 아예 다르게 어긋나는(엉뚱한 종목) 경우만 잡는 게 목적이다.
        if tick_max < lo * 0.5 or tick_min > hi * 2.0:
            return (f"{d} 일봉 저가/고가 {lo:.0f}~{hi:.0f} vs 틱 체결가 범위 "
                    f"{tick_min}~{tick_max} - 자릿수가 다름, 응답이 섞였을 수 있음")
    return None


def collect_one(client: KiwoomClient, shared_token: SharedToken, code: str, log_once: list[bool]) -> str:
    """반환값: "complete" / "partial" / "empty" / "suspicious"(가격대 이상, 재시도 대상)."""
    by_date, min_date_seen, pages = {}, None, 0
    attempts = 0
    while attempts < 5:  # 429 재시도가 이 안에도 들어오니 여유를 좀 더 둔다
        attempts += 1
        try:
            by_date, min_date_seen, pages = _fetch_once(client, code, log_once)
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                # 워커 수를 동적으로 줄이지 않는다 — 연속 큐 방식에서는 워커 수가
                # ThreadPoolExecutor 생성 시 고정이라 줄이기 까다롭다(스레드를 강제로
                # 죽일 수 없음). 대신 이 429를 만난 워커가 전역 쿨다운을 걸어(다른
                # 워커도 같이 대기) 자기 자리에서 그냥 대기했다가 이어서 돈다 —
                # 워커 수는 그대로 4, 잠깐 다 같이 쉬는 것뿐이라 구현이 단순하다.
                trigger_rate_limit_pause(code)
                by_date = {}
            else:
                raise
        except RuntimeError as exc:
            log(f"{code}: {attempts}번째 시도 API 오류 - {exc}")
            by_date = {}
        if by_date:
            break
        log(f"{code}: {attempts}번째 시도 데이터 없음 - 토큰 강제 재발급 후 60초 뒤 재시도")
        try:
            client.token = shared_token.refresh_if_stale(client.token)
        except Exception as exc:
            log(f"{code}: 토큰 재발급 실패 - {type(exc).__name__}: {exc}")
        time.sleep(60)

    if by_date:
        sanity_issue = check_price_sanity(code, by_date)
        if sanity_issue:
            log(f"{code}: 가격대 이상 감지 - {sanity_issue} - 저장 안 하고 완료 처리 안 함")
            return "suspicious"

    out_dir = f"{TICK_DIR}/{code}"
    os.makedirs(out_dir, exist_ok=True)
    saved_dates = 0
    for d, rows in by_date.items():
        if d < START_DATE or d > END_DATE:
            continue
        df = pd.DataFrame(rows)
        path = f"{out_dir}/{d}.csv"
        tmp = f"{path}.tmp"
        df.to_csv(tmp, index=False, encoding="utf-8-sig")
        os.replace(tmp, path)
        saved_dates += 1

    if saved_dates == 0:
        status = "empty"
    elif min_date_seen is not None and min_date_seen <= START_DATE:
        status = "complete"
    else:
        status = "partial"
    log(
        f"{code}: {pages}페이지 스캔({attempts}회 시도), {saved_dates}일 저장(범위 내), "
        f"최고(最古) 도달일={min_date_seen}, 상태={status}"
    )
    return status


def process_one(code: str, shared_token: SharedToken, log_once: list[bool]) -> tuple[str, str]:
    """429는 collect_one 안에서 전역 쿨다운+재시도로 처리하고 나온다 — 여기까지
    올라오면 5번 다 실패했거나 429가 아닌 진짜 오류다."""
    client = make_worker_client(shared_token)
    status = collect_one(client, shared_token, code, log_once)
    return code, status


def main() -> None:
    global APPKEY, SECRET, IS_MOCK
    load_dotenv("C:/Users/ike03/Desktop/code/ai_stock/.env")
    APPKEY = os.environ["KIWOOM_APPKEY"]
    SECRET = os.environ["KIWOOM_SECRETKEY"]
    IS_MOCK = os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true"
    bootstrap = KiwoomClient(APPKEY, SECRET, is_mock=IS_MOCK)
    bootstrap.issue_token()
    shared_token = SharedToken(bootstrap)
    log_once = [False]

    universe = build_universe()
    progress = load_progress()
    progress["total"] = len(universe)
    save_progress(progress)
    log(f"대상 {len(universe)}종목 (8/03~8/28 top35 합집합, 005930/000660 제외)")

    done = set(progress["done"])
    partial = set(progress.get("partial", []))
    remaining = [c for c in universe if c not in done]
    log(f"이미 완료 {len(done)}종목, 남은 {len(remaining)}종목, 동시성 최대 {MAX_CONCURRENCY}(실측안전한도 {MEASURED_SAFE_CONCURRENCY}의 80%)")

    run_start = time.time()
    last_report_at = progress.get("last_report_at", run_start)
    last_report_done = progress.get("last_report_done_count", len(done))
    done_this_run = 0

    # 연속 큐(2026-08-30, 웨이브 방식 대체): 남은 종목 전체를 한 번에 submit하고
    # as_completed로 받는다 — 워커가 하나 비면 ThreadPoolExecutor가 알아서 다음
    # 종목을 채운다. 종목당 페이지수 편차(714~2036, 3배 가까이)가 웨이브 방식에서는
    # 가장 느린 종목이 나머지 워커를 붙잡는 손실로 이어졌다(4배 기대, 2.8배 실측) —
    # 큐 방식은 그 편차를 자동으로 흡수한다.
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as pool:
        futures = {pool.submit(process_one, code, shared_token, log_once): code for code in remaining}
        for fut in concurrent.futures.as_completed(futures):
            code = futures[fut]
            try:
                code, status = fut.result()
            except Exception as exc:
                log(f"{code}: 예외로 실패 - {type(exc).__name__}: {exc}")
                status = "error"

            if status in ("empty", "error", "suspicious"):
                log(f"{code}: 완료 처리 안 함(상태={status}) - 다음 실행에서 재시도")
                continue

            # 2026-08-30 사고: 예전엔(웨이브 방식) 웨이브 전체가 끝나야 딱 한 번
            # save_progress를 불렀다 — 빠르게 끝난 종목이 최대 수십 분간 파일엔
            # 있는데 progress.json엔 없는 상태로 방치됐다(예외 삼킴도, 락 없는
            # 동시쓰기 충돌도 아니고 저장 호출 위치 자체의 설계 결함이었다). 연속
            # 큐에서는 완료가 더 불규칙하게 들어오니 종목 단위 즉시저장이 더욱
            # 중요하다 — 유지한다. 단일 프로세스·여러 스레드 구조라 OS 파일락
            # (risk_manager.risk_state_lock류, 다중 프로세스용이고 지금 그 자체
            # 결함을 조사 중이기도 함)은 안 맞는다 — threading.Lock으로 충분하다.
            # 2026-08-30 000880 사고: partial(불완전 수집)도 무조건 done에 넣었더니
            # "8/25 이전 데이터 없음"이 진짜 결측인지 API/코드 버그인지 검증되기 전에
            # 완료로 굳어버렸다(아침 빈 응답 사고와 같은 계열 — 불완전을 완료로 처리).
            # partial은 파일엔 저장하되 done에는 자동으로 넣지 않는다 — 원인이 확인돼
            # (신규상장 등으로 그게 최대치임이 맞음) 사람/에이전트가 명시적으로 받아들이기
            # 전까지는 다음 실행에서 계속 재시도 대상으로 남긴다.
            with _progress_lock:
                if status == "partial":
                    partial.add(code)
                    progress["partial"] = sorted(partial)
                    save_progress(progress)
                    log(f"{code}: partial 상태 - done에 자동 편입 안 함(다음 실행에서 재시도), 원인 확인 후 수동으로 done 처리할 것")
                    continue
                done.add(code)
                done_this_run += 1
                progress["done"] = sorted(done)
                save_progress(progress)

            elapsed = time.time() - run_start
            remaining_count = len(universe) - len(done)
            if done_this_run > 0:
                avg_per_stock = elapsed / done_this_run
                eta_h = avg_per_stock * remaining_count / 3600
                log(
                    f"진행 {len(done)}/{len(universe)} (이번 실행 {done_this_run}개 처리, "
                    f"경과 {elapsed/60:.1f}분, 종목당 평균 {avg_per_stock:.0f}초, "
                    f"남은 {remaining_count}종목 예상소요 {eta_h:.1f}시간)"
                )
                now = time.time()
                if ((len(done) - last_report_done) >= REPORT_EVERY_N and (now - last_report_at) >= REPORT_EVERY_SEC) \
                        or (now - last_report_at) >= FORCE_REPORT_EVERY_SEC:
                    write_progress_report(len(done), len(universe), elapsed, avg_per_stock, remaining_count, eta_h, MAX_CONCURRENCY, partial=len(partial))
                    last_report_at, last_report_done = now, len(done)
                    with _progress_lock:
                        progress["last_report_at"] = last_report_at
                        progress["last_report_done_count"] = last_report_done
                        save_progress(progress)

    missing = [c for c in universe if c not in done and c not in partial]
    log(f"완료 - 전 종목 처리 (done={len(done)}/{len(universe)}, partial={len(partial)}, "
        f"미완료={len(missing)}{'(' + ','.join(missing[:10]) + ('...' if len(missing) > 10 else '') + ')' if missing else ''})")
    if missing or partial:
        log(f"재시작 필요 — 미완료/partial {len(missing) + len(partial)}종목이 다음 실행에서 자동으로 재시도됨")
    final_elapsed = time.time() - run_start
    final_avg = final_elapsed / done_this_run if done_this_run else 0.0
    write_progress_report(len(done), len(universe), final_elapsed, final_avg,
                           len(universe) - len(done), 0.0, MAX_CONCURRENCY, partial=len(partial), finished=True)


def write_progress_report(done_n, total_n, elapsed, avg_per_stock, remaining_count, eta_h, concurrency,
                           partial: int = 0, finished: bool = False) -> None:
    """진행률은 이력이 필요 없다 — 고정 경로 하나를 계속 덮어쓴다(사용자 지시).
    중요한 발견/결론이 뒤집히는 건은 이 함수를 안 쓰고 타임스탬프 붙은 새 파일로
    따로 쓴다(이력이 남아야 하므로) — 그건 이 스크립트가 아니라 호출부(나)가 직접 씀."""
    os.makedirs(REPORT_DIR, exist_ok=True)
    status_line = "**실행 종료됨**" if finished else "실행 중"
    body = (
        f"# data-agent 체결수집 진행률 (최신: {time.strftime('%Y-%m-%d %H:%M')}, {status_line})\n\n"
        f"- 완료 {done_n}/{total_n}종목(partial {partial}건 포함), 현재 동시성 {concurrency}(최대 {MAX_CONCURRENCY})\n"
        f"- 이번 실행 경과 {elapsed/60:.1f}분, 종목당 평균 {avg_per_stock:.0f}초\n"
        f"- 남은 {remaining_count}종목"
        + (f", 실측 페이스 기준 예상소요 {eta_h:.1f}시간\n" if not finished else " — 실행이 끝났는데 남았다면 재시작 필요\n")
        + (f"- 55시간 초과 시 재판단 필요(사용자 지시) — 현재 {'초과' if eta_h > 55 else '이내'}\n" if not finished else "")
    )
    tmp = f"{PROGRESS_REPORT_PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, PROGRESS_REPORT_PATH)
    log(f"진행률 보고 갱신 -> {PROGRESS_REPORT_PATH}")


if __name__ == "__main__":
    main()
