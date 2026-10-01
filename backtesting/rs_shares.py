"""상장주식수 — RS 시가총액 필터용. lead 편지 2026-09-28 17:35 3번.

우선 로컬 `kospi-theme-engine/data/reference/universe.csv`(소피증권이 이미 ka10099 로 받아 둔 것)를 쓰고, 거기 없는
코드(**우선주 전부** — `scripts/prepare.py` 의 `is_preferred` 가 유니버스에서 원천 제외하기 때문, 그 외 소수)만
**키움 ka10099(종목정보 리스트, 배치 키)로 한 번** 채운다 — 편지는 ka10001(개별 조회)을 말했지만, 이미 이 저장소가
같은 목적(상장주식수)으로 쓰고 있는 ka10099(`kiwoom_client.get_stock_list`, `scripts/prepare.py` 가 `listCount` 로 읽음)를
코드당 한 번씩이 아니라 **시장당 한 번(2번 호출)**으로 대체했다 — 같은 값을 훨씬 적은 호출로 받는다(REST 는 계정 전체가 한도 공유).

    python -m backtesting.rs_shares          # data/cache/rs_shares.json 갱신(코드→상장주식수, "현재" 값 — 과거에도 같다고 가정)
    python -m backtesting.rs_shares --check  # 새로 안 받고 캐시 커버리지만 출력

**"한 번"만 받는다** — 이 스크립트는 RS 야간 갱신(`rs_rating.build`)에 안 물려 있다. 갱신하려면 사람이 다시 실행할 것.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

UNIVERSE_CSV = "kospi-theme-engine/data/reference/universe.csv"
OUT_PATH = "data/cache/rs_shares.json"


def from_universe_csv(path: str = UNIVERSE_CSV) -> dict[str, int]:
    if not os.path.isfile(path):
        return {}
    u = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    return {row["code"]: int(row["shares"]) for _, row in u.iterrows() if row.get("shares")}


def fetch_from_kiwoom(codes_needed: set[str]) -> dict[str, int]:
    """ka10099 시장당 1회(코스피·코스닥) — codes_needed 에 있는 코드만 결과에 남긴다. 배치 키, 주문 아님(읽기 전용 조회)."""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.getcwd(), ".env"))
    from kiwoom_client import KiwoomClient, batch_keys
    key, sec = batch_keys()
    if not key or not sec:
        raise SystemExit("KIWOOM_APPKEY/SECRETKEY(또는 배치용)가 .env 에 없습니다")
    client = KiwoomClient(key, sec, is_mock=os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true")
    out: dict[str, int] = {}
    for market_type in ("0", "10"):
        for item in client.get_stock_list(market_type):
            code = (item.get("code") or "").strip()
            if code not in codes_needed:
                continue
            try:
                out[code] = int(item.get("listCount") or 0)
            except (TypeError, ValueError):
                continue
    return out


def build(codes_needed: set[str] | None = None) -> dict[str, int]:
    shares = from_universe_csv()
    missing = (codes_needed - set(shares)) if codes_needed is not None else set()
    if missing:
        shares.update(fetch_from_kiwoom(missing))
    return shares


def save(shares: dict[str, int], path: str = OUT_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    json.dump(shares, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, path)


def load_cache(path: str = OUT_PATH) -> dict[str, int]:
    return json.loads(open(path, encoding="utf-8").read()) if os.path.isfile(path) else {}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        c = load_cache()
        print(f"캐시 {OUT_PATH}: {len(c)}종목")
        return
    from backtesting.rs_rating import excluded_codes, load_names
    import os as _os
    names = load_names()
    excl = excluded_codes(names)
    daily_codes = {f[:-4] for f in _os.listdir("data/stocks/daily")}
    needed = daily_codes - excl
    shares = build(needed)
    save(shares)
    got = len(needed & set(shares))
    print(f"저장: {OUT_PATH} — 필요 {len(needed)}종목 중 {got}개 확보({len(needed)-got}개 상장주식수 모름 → RS 모집단에서 빠짐)")


if __name__ == "__main__":
    main()
