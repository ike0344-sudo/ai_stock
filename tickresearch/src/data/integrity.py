"""데이터 무결성 검사 (Phase 1).

"조용히 틀린 결과"를 막는 것이 목적이다. 이 프로젝트의 선행 연구에서 실제로 겪은 사고를
그대로 검사 항목으로 만들었다:

- 같은 초 안의 체결 순서가 뒤집혀 45.7%가 틀렸던 사고 → `seq` 단조성 + 시간 단조성 검사
- 시간외 데이터가 섞여 지표가 조용히 틀어진 사고 → session 분포 검사
- 전일종가가 없어 등락률이 통째로 어긋난 사고 → ref_price 결측 검사
- 부동소수 경계로 "정확히 +10%"인 체결이 탈락한 사고 → 가격/수량 양수 검사

검사는 **실패를 세어 보고**하고 예외로 죽이지 않는다(한 종목 때문에 전체 리포트가
안 나오면 오히려 확인이 늦어진다). 다만 치명적 항목은 `fatal`로 분류한다.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

from .schema import SESSION_REGULAR, SIDE_BUY, SIDE_SELL, SIDE_UNKNOWN


def check_frame(df: pl.DataFrame, symbol: str, date: str) -> list[dict]:
    """한 종목·일 검사. 문제가 있으면 dict 리스트로 반환(없으면 빈 리스트)."""
    issues: list[dict] = []

    def bad(kind: str, detail: str, fatal: bool = False) -> None:
        issues.append({"symbol": symbol, "date": date, "kind": kind, "detail": detail, "fatal": fatal})

    if df.is_empty():
        bad("empty", "행이 0개", fatal=True)
        return issues

    # 1) 시간 단조성 — 시간순 저장이 깨지면 이후 모든 창 집계가 틀어진다
    ts = df["timestamp"]
    if not ts.is_sorted():
        bad("timestamp_not_sorted", "timestamp가 오름차순이 아니다", fatal=True)
    if not df["seq"].is_sorted():
        bad("seq_not_sorted", "seq가 오름차순이 아니다", fatal=True)

    # 2) 가격·수량 유효성
    if (df["price"] <= 0).any():
        bad("nonpositive_price", f"price<=0 {int((df['price'] <= 0).sum())}건", fatal=True)
    if (df["volume"] <= 0).any():
        bad("nonpositive_volume", f"volume<=0 {int((df['volume'] <= 0).sum())}건")

    # 3) trade_value 일관성 (price*volume과 일치해야 한다)
    mism = int((df["trade_value"] != df["price"] * df["volume"]).sum())
    if mism:
        bad("trade_value_mismatch", f"{mism}건", fatal=True)

    # 4) 날짜 일치 — 파일명 날짜와 실제 timestamp 날짜가 다르면 경계일 절단 사고다
    days = ts.dt.strftime("%Y-%m-%d").unique().to_list()
    if days != [date]:
        bad("date_mismatch", f"파일 {date} vs 데이터 {days}", fatal=True)

    # 5) 정규장 존재 여부 — 0이면 그 날은 분석에 못 쓴다
    n_reg = int((df["session"] == SESSION_REGULAR).sum())
    if n_reg == 0:
        bad("no_regular_session", "정규장 체결 0건")

    # 6) ref_price(전일 종가) 결측 — 등락률 기준이 없다
    if df["ref_price"].null_count() == len(df):
        bad("missing_ref_price", "ref_price 없음")

    # 7) side 분포 — 전부 UNKNOWN이면 tick rule이 동작하지 않은 것
    sides = set(df["side"].unique().to_list())
    if sides == {SIDE_UNKNOWN}:
        bad("side_all_unknown", "side가 전부 UNKNOWN")
    if not sides <= {SIDE_BUY, SIDE_SELL, SIDE_UNKNOWN}:
        bad("side_invalid", f"허용되지 않은 side 값: {sides - {SIDE_BUY, SIDE_SELL, SIDE_UNKNOWN}}", fatal=True)

    return issues


def check_all(root: str | Path, limit: int | None = None, progress_every: int = 500) -> dict:
    paths = sorted(Path(root).glob("symbol=*/*.parquet"))
    if limit:
        paths = paths[:limit]
    issues: list[dict] = []
    stats = {"files": len(paths), "rows": 0, "regular_rows": 0,
             "side_buy": 0, "side_sell": 0, "side_unknown": 0}
    for i, p in enumerate(paths, 1):
        symbol, date = p.parent.name.split("=", 1)[1], p.stem
        df = pl.read_parquet(p)
        issues += check_frame(df, symbol, date)
        stats["rows"] += len(df)
        stats["regular_rows"] += int((df["session"] == SESSION_REGULAR).sum())
        vc = df["side"].value_counts()
        for r in vc.iter_rows(named=True):
            key = {SIDE_BUY: "side_buy", SIDE_SELL: "side_sell", SIDE_UNKNOWN: "side_unknown"}.get(r["side"])
            if key:
                stats[key] += r["count"]
        if progress_every and i % progress_every == 0:
            print(f"  검사 {i}/{len(paths)} · 문제 {len(issues)}건", flush=True)
    stats["issues"] = issues
    stats["fatal"] = sum(1 for x in issues if x["fatal"])
    return stats
