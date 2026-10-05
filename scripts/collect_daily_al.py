"""통합(AL, KRX+NXT) 일봉 — 실거래대금(trde_prica) 포함. 거래대금 폭발 화면(backtesting/value_burst.py)이 읽는다.

    python scripts/collect_daily_al.py            # 오늘 KRX 대금 300억+ 종목만 증분(1페이지, 처음이면 3페이지)
    python scripts/collect_daily_al.py --all      # 전 종목

KRX 일봉(data/stocks/daily)은 NXT 거래가 빠져 2025-03 뒤로 대금이 크게 작다 — 심텍 2026-09-22 KRX 2,810억 vs 통합 5,559억
(사용자가 "역대 신고 거래대금"이라 짚었는데 KRX 로는 안 잡혔다). 그래서 대금 신고 판정은 이 통합 일봉으로만 한다.
매일 전 종목(2,500여 번 호출)은 저녁 소피증권 REST 몫을 잡아먹어, 그날 KRX 대금이 300억 이상인 종목만 받는다 —
통합 1,000억 폭발인데 KRX 300억 미만(NXT 비중 70%+)인 날은 사실상 없다. 화면에 올라 있는 종목은 대금과 무관하게 매일 받는다(가격도 통합). 1페이지 = 600거래일이라 며칠 빠져도 다음 수집에 메워진다.
배치 앱키(batch_keys)를 쓴다 — 소피증권 키로 토큰을 새로 받으면 소피 토큰이 [8005] 로 무효가 된다. 저장은 허브 쓰기 관문 안에서만.
"""
import argparse
import json
import os
import sys
import time

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))
from datahub import catalog, gate  # noqa: E402
from kiwoom_client import KiwoomClient, batch_keys  # noqa: E402

COLS = {"dt": "date", "open_pric": "open", "high_pric": "high", "low_pric": "low", "cur_prc": "close",
        "trde_qty": "volume", "trde_prica": "value_mw"}
MIN_KRX_EOK = 300
NEW_PAGES = 3  # 처음 받는 종목: 3페이지 ≈ 7년(역대·4년 판정용)


def targets(all_codes: bool) -> list[str]:
    daily = catalog.path("daily", code="X").parent
    # 거래대금 폭발 화면에 올라 있는 종목은 대금이 식어도 매일 받는다 — 화면 가격(현재가·고점)이 통합 일봉에서 나온다(10-05)
    shown = set()
    try:
        shown = {r["코드"] for r in json.load(open(os.path.join(ROOT, "static/dashboard/value_burst.json"), encoding="utf-8"))["rows"]}
    except (OSError, ValueError, KeyError):
        pass
    out = []
    for p in sorted(daily.glob("*.csv")):
        if all_codes:
            out.append(p.stem)
            continue
        try:
            last = pd.read_csv(p).iloc[-1]
        except (IndexError, pd.errors.EmptyDataError):
            continue
        if last.close * last.volume >= MIN_KRX_EOK * 1e8 or p.stem in shown:
            out.append(p.stem)
    return out


def parse(pages: list[dict]) -> pd.DataFrame | None:
    rows = [r for p in pages for r in p.get("stk_dt_pole_chart_qry", []) if r.get("dt")]
    if not rows:
        return None  # 상장폐지·ETN 등은 빈 목록이 온다
    df = pd.DataFrame(rows)[list(COLS)].rename(columns=COLS)
    for c in df.columns[1:]:
        # 가격에 등락 부호(+/-)가 붙어 온다 — 값 자체는 항상 양수
        df[c] = pd.to_numeric(df[c].astype(str).str.lstrip("+-"), errors="coerce")
    return df


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    codes = targets(a.all)
    client = KiwoomClient(*batch_keys(), is_mock=os.environ.get("KIWOOM_IS_MOCK", "false").lower() == "true",
                          min_request_interval=0.25)
    print(f"통합 일봉 {len(codes)}종목", flush=True)
    done = failed = 0
    with gate.write("daily_al", writer="collect_daily_al", detail={"codes": len(codes)}) as run:
        for n, code in enumerate(codes):
            path = catalog.path("daily_al", code=code)
            old = pd.read_csv(path, dtype={"date": str}) if path.exists() else None
            for attempt in range(3):
                try:
                    new = parse(client.get_daily_chart_pages(code + "_AL", max_pages=1 if old is not None else NEW_PAGES))
                    break
                except Exception as exc:  # noqa: BLE001 — 429·끊김은 잠깐 쉬고 그 종목만 다시
                    new = exc
                    time.sleep(2 * (attempt + 1))
            if isinstance(new, Exception):
                failed += 1
                print(f"  실패 {code}: {new}", flush=True)
                continue
            if new is None:
                continue
            df = new if old is None else pd.concat([old, new]).drop_duplicates("date", keep="last")
            path.parent.mkdir(parents=True, exist_ok=True)
            df.sort_values("date").to_csv(path, index=False)
            done += 1
            if n % 200 == 0:
                print(f"  {n}/{len(codes)}", flush=True)
        run.result(saved=done, failed=failed)
    print(f"완료: 저장 {done} · 실패 {failed}", flush=True)
    return 0 if failed <= len(codes) * 0.05 else 1


if __name__ == "__main__":
    sys.exit(main())
