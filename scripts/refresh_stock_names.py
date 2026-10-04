"""종목명 자동 갱신 — 키움 ka10099(종목정보 리스트, 코스피·코스닥 각 1회)로 data/stock_names.json 을 고친다. 사용자 2026-10-04.

    python scripts/refresh_stock_names.py          # 바뀐 이름 고치고 새 종목 추가
    python scripts/refresh_stock_names.py --dry    # 바뀔 것만 출력

8/29 뒤로 아무도 안 고쳐 세아메카닉스→HT로보틱스 등 7종목이 옛 이름으로 화면에 나왔다(10-04 사용자 지적).
- 목록에 있는 코드: 이름이 다르면 고친다 · 없던 코드면 추가한다.
- 목록에 없는 코드는 **지우지 않는다**(상장폐지 종목도 과거 데이터·백테스트에서 이름이 필요하다).
- 응답이 비정상으로 적으면(시장당 1,000개 미만) 아무것도 안 쓴다 — API 실패를 '전 종목 폐지'로 오해하지 않게.
배치 앱키(batch_keys) · 읽기 전용 조회 2회. 이 파일은 카탈로그 reference_static(잠금 없음)이라 원자적 교체로만 쓴다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PATH = os.path.join(ROOT, "data", "stock_names.json")
MIN_PER_MARKET = 1000


def merge(old: dict[str, str], fresh: dict[str, str]) -> tuple[dict[str, str], dict[str, tuple[str, str]], dict[str, str]]:
    """(새 사전, 바뀐 것 {코드: (옛, 새)}, 추가된 것 {코드: 이름}). 목록에 없는 옛 코드는 그대로 둔다."""
    changed = {c: (old[c], n) for c, n in fresh.items() if c in old and old[c] != n}
    added = {c: n for c, n in fresh.items() if c not in old}
    return {**old, **fresh}, changed, added


def fetch() -> dict[str, str]:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    from kiwoom_client import KiwoomClient, batch_keys
    client = KiwoomClient(*batch_keys(), is_mock=os.environ.get("KIWOOM_IS_MOCK", "false").lower() == "true")
    out: dict[str, str] = {}
    for market in ("0", "10"):  # 코스피(ETF·ETN 포함), 코스닥
        rows = client.get_stock_list(market)
        if len(rows) < MIN_PER_MARKET:
            raise SystemExit(f"ka10099 시장 {market} 응답이 {len(rows)}개뿐 — 비정상이라 쓰지 않는다")
        out.update({r["code"].strip(): r["name"].strip() for r in rows if r.get("code") and r.get("name")})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    old = json.load(open(PATH, encoding="utf-8"))
    new, changed, added = merge(old, fetch())
    for c, (o, n) in changed.items():
        print(f"  이름 바뀜 {c}: {o} → {n}")
    print(f"바뀜 {len(changed)} · 추가 {len(added)}" + (f" (예: {', '.join(list(added.values())[:5])})" if added else ""))
    if a.dry or not (changed or added):
        return 0
    tmp = f"{PATH}.tmp"
    json.dump(new, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, PATH)
    return 0


def demo() -> None:
    new, ch, ad = merge({"1": "세아메카닉스", "2": "폐지된곳"}, {"1": "HT로보틱스", "3": "신규"})
    assert new == {"1": "HT로보틱스", "2": "폐지된곳", "3": "신규"} and ch == {"1": ("세아메카닉스", "HT로보틱스")} and ad == {"3": "신규"}
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        sys.exit(main())
