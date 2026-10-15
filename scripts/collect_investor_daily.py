"""종목별 일별 투자자 수급(외국인·기관·개인 등 순매수 금액)을 받는다 — 키움 ka10059.

    python scripts/collect_investor_daily.py                 # 신고대금 장부 종목 전부, 2019-06-01~
    python scripts/collect_investor_daily.py --codes 222800  # 몇 종목만
    python scripts/collect_investor_daily.py --rate 2        # 계정 전체 중 이 수집기 몫(초당)

- 한 번 부르면 100거래일씩 최신→과거로 온다. 연속조회로 상장일까지 다 나온다(10-15 심텍: 2015-08~ 2,742일·28페이지).
- 수급 칸은 KRX 집계다 — `_AL` 로 불러도 투자자 칸은 같고 가격·거래량만 통합으로 바뀐다(10-15 실측). 그래서 KRX 로 부른다.
- 배치 앱키 하나·토큰 하나(KiwoomClient 가 처음 한 번 받고 [8005] 때만 다시). 소피증권은 다른 앱키라 건드리지 않는다.
- REST 한도는 계정 단위(초당 5회 OK·8회 429, 09-30) — 소피·야간 갱신 몫을 남겨 기본 초당 2회. 429·연결 끊김은 그 페이지만 다시.
- 이미 파일이 있는 종목은 건너뛴다(덮어쓰지 않는다). 오늘 줄은 장 마감 뒤 잠정치일 수 있어 뺀다.
- 저장은 데이터 허브 쓰기 관문(gate.write) 안에서만, 파일마다 임시파일→교체(원자적).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))
from datahub import catalog, gate  # noqa: E402
from kiwoom_client import KiwoomClient, batch_keys  # noqa: E402

LEDGER = "static/dashboard/value_ledger.json"
SINCE = "20190601"
# 응답 필드 → 저장 열. 금액은 전부 백만원(amt_qty_tp=1). acc_trde_prica 도 백만원.
FIELDS = {"cur_prc": "close", "flu_rt": "chg_pct", "acc_trde_qty": "volume", "acc_trde_prica": "value_mw",
          "ind_invsr": "ind", "frgnr_invsr": "frgn", "orgn": "orgn", "fnnc_invt": "fnnc_invt", "insrnc": "insrnc",
          "invtrt": "invtrt", "etc_fnnc": "etc_fnnc", "bank": "bank", "penfnd_etc": "penfnd", "samo_fund": "samo",
          "natn": "natn", "etc_corp": "etc_corp", "natfor": "natfor"}


def num(v) -> float:
    s = str(v).strip().replace("+", "").replace("--", "-")
    try:
        return float(s) if s else float("nan")
    except ValueError:
        return float("nan")


def to_frame(rows: list[dict], today: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df = df[df["dt"].astype(str).str.len() == 8]
    df = df[(df["dt"] >= SINCE) & (df["dt"] < today)].drop_duplicates("dt")
    out = pd.DataFrame({"date": df["dt"].astype(str)})
    for src, dst in FIELDS.items():
        out[dst] = df[src].map(num) if src in df else float("nan")
    out["close"] = out["close"].abs()            # 앞 부호는 전일 대비 방향 표시다(값 아님)
    out["chg_pct"] = out["chg_pct"] / 100        # '-1362' = -13.62%
    return out.sort_values("date").reset_index(drop=True)


def fetch(client: KiwoomClient, code: str, stat: dict) -> list[dict]:
    body = {"dt": datetime.now().strftime("%Y%m%d"), "stk_cd": code, "amt_qty_tp": "1", "trde_tp": "0", "unit_tp": "1"}
    rows, cont, nk = [], "N", ""
    for _ in range(60):                           # 2019-06~ 은 20페이지 남짓 — 넉넉히
        for attempt in range(8):
            try:
                p = client.request_tr("ka10059", body, path="/api/dostk/stkinfo", cont_yn=cont, next_key=nk)
                break
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 429:
                    stat["r429"] += 1
                    time.sleep(1.5 + attempt)
                    continue
                raise
            except (requests.ConnectionError, requests.Timeout):
                stat["reset"] += 1
                time.sleep(2.0 + attempt)
                continue
        else:
            raise RuntimeError(f"{code} 페이지를 8번 못 받았다")
        stat["calls"] += 1
        if p.get("return_code") not in (0, None):
            raise RuntimeError(f"{code} API 오류 {p.get('return_code')}: {p.get('return_msg')}")
        got = [r for r in (p.get("stk_invsr_orgn") or []) if r.get("dt")]
        rows += got
        if not got or min(r["dt"] for r in got) < SINCE or client.last_cont_yn != "Y" or not client.last_next_key:
            break
        cont, nk = "Y", client.last_next_key
    return rows


def write_atomic(df: pd.DataFrame, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    df.to_csv(tmp, index=False, encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default="")
    ap.add_argument("--rate", type=float, default=2.0)
    a = ap.parse_args()
    codes = [c for c in a.codes.split(",") if c] or sorted({r[1] for r in json.load(open(LEDGER, encoding="utf-8"))["rows"]})
    todo = [c for c in codes if not catalog.path("investor_daily", code=c).exists()]
    today = datetime.now().strftime("%Y%m%d")
    print(f"{datetime.now():%H:%M:%S} 대상 {len(codes)}종목 중 받을 것 {len(todo)} · 초당 {a.rate}회", flush=True)
    client = KiwoomClient(*batch_keys(), is_mock=False, min_request_interval=1.0 / a.rate)
    stat = {"calls": 0, "r429": 0, "reset": 0, "rows": 0}
    done, failed, empty, t0 = 0, [], [], time.time()
    with gate.write("investor_daily", writer="collect_investor_daily", detail={"codes": len(todo), "since": SINCE}) as run:
        for i, code in enumerate(todo, 1):
            try:
                rows = fetch(client, code, stat)
            except Exception as exc:              # noqa: BLE001 — 한 종목 실패로 나머지를 버리지 않는다
                failed.append(code)
                print(f"  실패 {code}: {exc}", flush=True)
                continue
            df = to_frame(rows, today) if rows else pd.DataFrame()
            if df.empty:
                empty.append(code)
            else:
                write_atomic(df, catalog.path("investor_daily", code=code))
                done += 1
                stat["rows"] += len(df)
            run.progress(i, len(todo))
            if i % 50 == 0:
                el = time.time() - t0
                print(f"{datetime.now():%H:%M:%S} {i}/{len(todo)} · 조회 {stat['calls']} · 429 {stat['r429']} · "
                      f"남은 예상 {el / i * (len(todo) - i) / 60:.0f}분", flush=True)
        run.result(done=done, failed=failed, empty=empty, **stat)
        run.ok = not failed
    print(f"완료 {done} · 빈 {len(empty)} {empty[:20]} · 실패 {len(failed)} {failed[:20]} · 조회 {stat['calls']} · "
          f"429 {stat['r429']} · 끊김 {stat['reset']} · 줄 {stat['rows']:,} · {(time.time() - t0) / 60:.0f}분", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
