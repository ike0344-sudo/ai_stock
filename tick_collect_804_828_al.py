"""8/04~8/28 통합(KRX+NXT, `_AL` 접미사) 체결(ka10079 틱) 재수집 — 2026-08-30.

`tick_collect_803_828.py`(KRX 전용, 이미 완료)의 최소 변형이다. 로직은 거의 동일,
바뀐 것은 아래 네 가지뿐:
1. 종목코드에 `_AL` 접미사를 붙여 요청한다(`_request_code`) — 실측으로 확인:
   접미사 없음=KRX 전용(09:00~15:30만), `_AL`=KRX+NXT 통합(08:00~20:00, NXT는
   정규장 시간에도 별도 체결이 있다). 스키마·페이지네이션(cont_yn/next_key)
   방식은 접미사 유무와 무관하게 동일함을 ka10079·ka10080 양쪽에서 확인했다.
2. 저장 경로를 분리한다(`data/stocks/tick_al`) — 기존 KRX전용 데이터(`data/stocks/tick`)
   를 덮어쓰지 않는다. 이유: (a) 기존 데이터로 낸 백테스트 결과를 나중에도
   재현할 수 있어야 하고, (b) 통합 데이터에 문제가 생기면 되돌아갈 곳이 있어야
   한다.
3. START_DATE를 8/04로 옮긴다 — 8/03은 이미 별도 사고(경계일 절단)로 폐기 확정됨
   (`data/stocks/tick/KNOWN_ISSUES.md` 참고). 경계일 절단 버그 자체는 이미 고쳐져
   있다(`min_date_seen < START_DATE`) — 8/04를 온전히 받으려면 8/03까지 페이지를
   넘겨야 하는데, 그 로직 그대로 재사용한다.
4. 시간대를 거르지 않는다 — 정규장/시간외를 나눠 저장하거나 컬럼을 추가하지
   않는다(사용자 결정, 2026-08-30: "time 컬럼에 시각이 이미 있으니 그것으로
   충분하다, 구조를 복잡하게 만들면 규칙을 잊었을 때 더 위험하다"). 대신
   `data/stocks/tick_al/README.md`에 사용 규칙을 명시한다 — 백테스트는
   09:00~15:30만 걸러 써야 한다.

측정 근거(NXT 비중·ka10032 기준 판정·재수집 비용 추정)는
state/agent_reports/data-agent_20260830-xxxxxx.md 참고.

    python tick_collect_804_828_al.py
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

START_DATE = "2026-08-04"
END_DATE = "2026-08-28"
EXCLUDE = MEGA_CAP_EXCLUDE  # 호가 저장과 공유(data_exclude.py) — 여기서 새로 정의 안 함
CODE_SUFFIX = "_AL"  # 이것만 원본과 다르면 KRX전용 -> 통합(NXT포함)이 된다
EXTRA_CODES = {"032820", "030530"}  # 원본 수집 때와 동일 유니버스(day-of top35 보충분)
TICK_DIR = "data/stocks/tick_al"
DAILY_DIR = "data/stocks/daily"  # 가격 대조용(KRX 기준) — 통합이어도 가격은 KRX와 거의 같아 유효
PROGRESS_PATH = "state/tick_collection/progress_al.json"
LOG_PATH = "state/tick_collection/log_al.txt"
REPORT_DIR = "state/agent_reports"
PROGRESS_REPORT_PATH = f"{REPORT_DIR}/data-agent_tick_al_progress.md"
REPORT_EVERY_N = 20
REPORT_EVERY_SEC = 3600
# 2026-08-31 사고: 01:16 완료 후 08:16까지 7시간 동안 진행파일이 안 갱신돼 아무도
# 몰랐다 — 위 20개+1시간 조건이 둘 다 있어야 갱신되는데, 막판엔 완료 속도가 느려져
# 20개를 못 채운 채 실행이 끝나버렸다(끝날 때 강제 갱신도 없었음). 카운트 조건과
# 무관하게 이 시간이 지나면 무조건 갱신한다 — 사용자가 아무 때나 파일만 봐도
# 최신 상태를 알 수 있어야 한다.
FORCE_REPORT_EVERY_SEC = 1800
MARKET_OPEN, MARKET_CLOSE = dtime(9, 0), dtime(15, 30)

MEASURED_SAFE_CONCURRENCY = 6
MAX_CONCURRENCY = int(MEASURED_SAFE_CONCURRENCY * 0.8)  # = 4
RATE_LIMIT_COOLDOWN_SEC = 60

APPKEY = None
SECRET = None
IS_MOCK = None

_log_lock = threading.Lock()
_progress_lock = threading.Lock()
_rate_limit_lock = threading.Lock()
_rate_limit_pause_until = [0.0]


def _request_code(code: str) -> str:
    return f"{code}{CODE_SUFFIX}"


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
    if now.weekday() >= 5:
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


def pause_if_market_hours(log_once: list[bool]) -> None:
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
    ranked = daily_top_n_from_local(top_n=35)
    dates = [d for d in ranked if START_DATE <= d.strftime("%Y-%m-%d") <= END_DATE]
    from collections import Counter

    count: Counter[str] = Counter()
    for d in dates:
        count.update(ranked[d])
    for code in EXCLUDE:
        count.pop(code, None)
    ranked_codes = [code for code, _ in count.most_common()]
    for code in EXTRA_CODES:
        if code not in count:
            ranked_codes.append(code)
    return ranked_codes


class SharedToken:
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
    """code는 순수 6자리(저장용) — 실제 API 요청에는 _request_code(code)로 접미사를 붙인다."""
    body = {"stk_cd": _request_code(code), "tic_scope": "1", "upd_stkpc_tp": "1"}
    cont_yn, next_key = "N", ""
    by_date: dict[str, list[dict]] = {}
    min_date_seen = None
    pages = 0
    while True:
        pause_if_market_hours(log_once)
        wait_out_rate_limit_pause()
        payload = client.request_tr("ka10079", body, path="/api/dostk/chart", cont_yn=cont_yn, next_key=next_key)
        pages += 1
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
        # 경계일 절단 방지 — 원본 사고(8/03 전체 절단) 이후 수정된 로직 그대로 재사용.
        # START_DATE(8/04)보다 엄격히 이전 날짜(8/03)를 봐야 8/04 전체를 지나쳤다고
        # 확신할 수 있다.
        if min_date_seen is not None and min_date_seen < START_DATE:
            break
        if client.last_cont_yn != "Y" or not client.last_next_key:
            break
        cont_yn, next_key = "Y", client.last_next_key
    return by_date, min_date_seen, pages


def check_price_sanity(code: str, by_date: dict[str, list[dict]]) -> str | None:
    """가격 범위만 대조 — 통합(KRX+NXT)이어도 두 시장 가격은 재정거래로 거의
    같이 움직이므로 KRX 기준 로컬 일봉과 대조해도 유효하다(거래량은 대조하지
    않음 — 통합이 KRX전용보다 많은 게 당연하므로)."""
    daily_path = f"{DAILY_DIR}/{code}.csv"
    if not os.path.isfile(daily_path):
        return None
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
        if tick_max < lo * 0.5 or tick_min > hi * 2.0:
            return (f"{d} 일봉 저가/고가 {lo:.0f}~{hi:.0f} vs 틱 체결가 범위 "
                    f"{tick_min}~{tick_max} - 자릿수가 다름, 응답이 섞였을 수 있음")
    return None


def collect_one(client: KiwoomClient, shared_token: SharedToken, code: str, log_once: list[bool]) -> str:
    by_date, min_date_seen, pages = {}, None, 0
    attempts = 0
    while attempts < 5:
        attempts += 1
        try:
            by_date, min_date_seen, pages = _fetch_once(client, code, log_once)
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429:
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
    log(f"대상 {len(universe)}종목 (8/04~8/28 top35 합집합 + 032820/030530, 005930/000660 제외, 통합 _AL)")

    done = set(progress["done"])
    partial = set(progress.get("partial", []))
    remaining = [c for c in universe if c not in done]
    log(f"이미 완료 {len(done)}종목, 남은 {len(remaining)}종목, 동시성 최대 {MAX_CONCURRENCY}(실측안전한도 {MEASURED_SAFE_CONCURRENCY}의 80%)")

    run_start = time.time()
    last_report_at = progress.get("last_report_at", run_start)
    last_report_done = progress.get("last_report_done_count", len(done))
    done_this_run = 0

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
                # 2026-08-31: 카운트조건(20개)만 있으면 막판에 속도가 느려져 20개를
                # 못 채운 채 실행이 끝나버릴 수 있다(실제로 겪음) — 시간조건만으로도
                # 갱신되게 OR로 추가한다.
                if ((len(done) - last_report_done) >= REPORT_EVERY_N and (now - last_report_at) >= REPORT_EVERY_SEC) \
                        or (now - last_report_at) >= FORCE_REPORT_EVERY_SEC:
                    write_progress_report(len(done), len(universe), elapsed, avg_per_stock, remaining_count, eta_h, MAX_CONCURRENCY, partial=len(partial))
                    last_report_at, last_report_done = now, len(done)
                    with _progress_lock:
                        progress["last_report_at"] = last_report_at
                        progress["last_report_done_count"] = last_report_done
                        save_progress(progress)

    # 2026-08-31 사고: "완료 - 전 종목 처리"만 찍고 실제 done 수를 안 밝혀서, 117개
    # 대상 중 103개만 done인 채(14개는 partial+미완료) 끝난 걸 7시간 동안 아무도
    # 못 알아챘다. 이 줄만 봐도 재시작이 필요한지 바로 알 수 있게 항상 세 숫자를
    # 같이 찍고, 이 시점에 진행 보고 파일도 조건과 무관하게 즉시 강제 갱신한다.
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
    os.makedirs(REPORT_DIR, exist_ok=True)
    status_line = "**실행 종료됨**" if finished else "실행 중"
    body = (
        f"# data-agent 체결(통합_AL)수집 진행률 (최신: {time.strftime('%Y-%m-%d %H:%M')}, {status_line})\n\n"
        f"- 완료 {done_n}/{total_n}종목(partial {partial}건 포함), 현재 동시성 {concurrency}(최대 {MAX_CONCURRENCY})\n"
        f"- 이번 실행 경과 {elapsed/60:.1f}분, 종목당 평균 {avg_per_stock:.0f}초\n"
        f"- 남은 {remaining_count}종목"
        + (f", 실측 페이스 기준 예상소요 {eta_h:.1f}시간\n" if not finished else " — 실행이 끝났는데 남았다면 재시작 필요\n")
    )
    tmp = f"{PROGRESS_REPORT_PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, PROGRESS_REPORT_PATH)
    log(f"진행률 보고 갱신 -> {PROGRESS_REPORT_PATH}")


if __name__ == "__main__":
    main()
