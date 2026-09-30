"""그날 거래대금 상위 N 종목의 프로그램 매매 기록(ka90008, 체결 변화마다)을 받는다.

    python scripts/collect_program_al.py            # 상위 50, 초당 4회
    python scripts/collect_program_al.py --top 30 --rate 3

ka90008 은 날짜를 무시하고 **당일분만** 준다(2026-09-30 실측) — 그날 밤에 못 받으면 영영 없다.
통합(AL)이라 장전(08:00~)·장중·장후(~20:00)가 다 들어 있으니 20:00 뒤에 돌린다.

병렬: 토큰 하나를 작업자들이 나눠 쓰고, 공용 속도 제한으로 계정 전체 초당 rate 회를 지킨다.
키움 REST 한도는 계정 단위다 — 09-30 실측 초당 5회 OK·8회 429. 소피증권 몫을 남겨 기본 4회.
429 는 그 페이지만 쉬었다 다시 받는다(종목째 버리면 2배 이상 느려진 실측이 있다).
배치 앱키를 쓴다 — 소피증권 키로 토큰을 새로 받으면 소피 토큰이 [8005] 로 무효가 된다.
저장은 데이터 허브 쓰기 관문(gate.write) 안에서만 한다.
"""
import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "kospi-theme-engine"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))
from datahub import catalog, gate  # noqa: E402
from kiwoom_client import batch_keys  # noqa: E402

from app.ingest.rest import RestClient  # noqa: E402

SEOUL = ZoneInfo("Asia/Seoul")
COLS = ["tm", "cur_prc", "flu_rt", "trde_qty", "prm_sell_amt", "prm_buy_amt", "prm_netprps_amt",
        "prm_sell_qty", "prm_buy_qty", "prm_netprps_qty"]


def num(v) -> float:
    s = str(v).strip().replace("--", "-").replace("+", "")
    try:
        return float(s) if s else 0.0
    except ValueError:
        return float("nan")


class Limiter:
    """계정 전체 초당 rate 회. 작업자 몇 개든 이 하나를 거친다."""

    def __init__(self, rate: float) -> None:
        self.gap, self.next, self.lock = 1.0 / rate, time.monotonic(), threading.Lock()

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next)
            self.next = t + self.gap
        time.sleep(max(0.0, t - now))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--rate", type=float, default=4.0)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    day = datetime.now(SEOUL).strftime("%Y-%m-%d")
    key, sec = batch_keys()
    client = RestClient(key, sec)
    top = [c for c, _ in client.trading_value_top(pages=2)][:a.top]
    todo = [c for c in top if not catalog.path("program_al", code=c, date=day).exists()]
    print(f"{day} 상위 {len(top)}종목 중 받을 것 {len(todo)} · 초당 {a.rate}회 · 작업자 {a.workers}", flush=True)
    tok = {"v": client.token(), "lock": threading.Lock()}
    lim = Limiter(a.rate)
    stat = {"calls": 0, "r429": 0, "rows": 0}

    def page(code: str, cont: str, nkey: str) -> "tuple[dict, str, str]":
        for attempt in range(8):
            lim.wait()
            try:
                res = requests.post(f"{client.base_url}/api/dostk/mrkcond", timeout=10, json={
                    "amt_qty_tp": "1", "stk_cd": code + "_AL", "date": day.replace("-", "")}, headers={
                    "Content-Type": "application/json;charset=UTF-8", "authorization": f"Bearer {tok['v']}",
                    "api-id": "ka90008", "cont-yn": cont, "next-key": nkey})
            except (requests.ConnectionError, requests.Timeout):
                # 09-30 20:10 첫 수집에서 8종목이 연결 끊김(10054)으로 통째로 빠졌다 — 그 페이지만 다시.
                stat["reset"] = stat.get("reset", 0) + 1
                time.sleep(2.0 + attempt)
                continue
            stat["calls"] += 1
            if res.status_code == 429:
                stat["r429"] += 1
                time.sleep(1.0 + attempt)
                continue
            res.raise_for_status()
            p = res.json()
            if p.get("return_code") not in (0, None) and "8005" in str(p.get("return_msg")):
                with tok["lock"]:
                    tok["v"] = client.token(fresh=True)
                continue
            return p, res.headers.get("cont-yn", "N"), res.headers.get("next-key", "")
        raise RuntimeError(f"{code} 페이지를 8번 못 받았다")

    def one(code: str) -> "pd.DataFrame | None":
        rows, cont, nkey = [], "N", ""
        for _ in range(400):
            p, cont, nkey = page(code, cont, nkey)
            rows += p.get("stk_tm_prm_trde_trnsn") or []
            if cont != "Y":
                break
        if not rows:
            return None
        df = pd.DataFrame(rows)
        df = df[[c for c in COLS if c in df.columns]].copy()
        for c in df.columns[1:]:
            df[c] = df[c].map(num)
        return df.sort_values("tm").reset_index(drop=True)

    t0 = time.time()
    done = failed = 0
    with gate.write("program_al", writer="program_collect", detail={"day": day, "codes": len(todo)}) as run:
        with ThreadPoolExecutor(a.workers) as ex:
            for code, fut in [(c, ex.submit(one, c)) for c in todo]:
                try:
                    df = fut.result()
                except Exception as exc:              # noqa: BLE001 — 한 종목 실패로 나머지를 버리지 않는다
                    failed += 1
                    print(f"  실패 {code}: {exc}", flush=True)
                    continue
                if df is None:
                    continue
                path = catalog.path("program_al", code=code, date=day)
                path.parent.mkdir(parents=True, exist_ok=True)
                df.to_parquet(path, index=False)
                done += 1
                stat["rows"] += len(df)
                run.progress(done, len(todo))
    el = time.time() - t0
    size = sum(catalog.path("program_al", code=c, date=day).stat().st_size for c in top
               if catalog.path("program_al", code=c, date=day).exists())
    print(f"완료 {done} · 실패 {failed} · 조회 {stat['calls']} · 429 {stat['r429']} · 줄 {stat['rows']:,} · "
          f"{el:.0f}초({stat['calls'] / max(el, 1):.1f}회/초) · 오늘 파일 {size / 1e6:.1f}MB", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
