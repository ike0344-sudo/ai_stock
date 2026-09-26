"""체결데이터 기반 수익구간 자동탐색 — CLI.

Phase 1(데이터 로딩)만 구현돼 있다. 나머지 명령은 **일부러 미구현 상태로 두고** 명확히
거절한다 — Phase 1이 검증되기 전에 Feature/ML 코드를 쓰지 않는다는 개발 원칙 때문이다.

사용: python main.py ingest | check | info
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from src.data import ingest as ingest_mod          # noqa: E402
from src.data import integrity, loader             # noqa: E402

NOT_YET = {"analyze": 4, "search": 5, "backtest": 6, "report": 8, "dashboard": 9}


def _cfg(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> int:
    ap = argparse.ArgumentParser(description="체결데이터 수익구간 탐색")
    ap.add_argument("command", choices=["ingest", "check", "info", "features", "labels", *NOT_YET])
    ap.add_argument("--config", default="configs/default.yaml")
    ap.add_argument("--limit", type=int, default=None, help="파일 수 제한(시험용)")
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()

    if a.command in NOT_YET:
        print(f"'{a.command}'는 Phase {NOT_YET[a.command]} 기능이다. "
              f"Phase 1(ingest/check)이 검증되기 전에는 구현하지 않는다.")
        return 1

    c = _cfg(a.config)
    raw, proc = c["data"]["raw_root"], c["data"]["processed_root"]

    if a.command == "ingest":
        print(f"원본 {raw} → 표준 {proc}")
        files = sorted(Path(raw).glob("*/*.parquet"))
        if a.limit:
            print(f"  (시험 모드: 앞 {a.limit}개만)")
            import itertools, shutil, tempfile
            tmp = Path(tempfile.mkdtemp())
            for f in itertools.islice(files, a.limit):
                d = tmp / f.parent.name
                d.mkdir(exist_ok=True)
                shutil.copy(f, d / f.name)
            raw = tmp
        s = ingest_mod.ingest_all(raw, proc, a.overwrite)
        print(f"\n파일 {s['files']:,} | 변환 {s['ingested']:,} | 건너뜀 {s['skipped']:,}")
        print(f"행 {s['rows']:,} (정규장 {s['regular_rows']:,}, "
              f"{100*s['regular_rows']/max(s['rows'],1):.1f}%)")
        print(f"ref_price 없음 {s['no_ref_price']} | 오류 {len(s['errors'])}")
        for e in s["errors"][:5]:
            print("  오류:", e)
        return 0

    if a.command == "check":
        s = integrity.check_all(proc, a.limit)
        print(f"\n검사 파일 {s['files']:,} | 행 {s['rows']:,} (정규장 {s['regular_rows']:,})")
        tot = s["side_buy"] + s["side_sell"] + s["side_unknown"]
        if tot:
            print(f"side 분포: BUY {100*s['side_buy']/tot:.1f}% / SELL {100*s['side_sell']/tot:.1f}%"
                  f" / UNKNOWN {100*s['side_unknown']/tot:.1f}%  (전부 tick_rule 추정)")
        print(f"문제 {len(s['issues'])}건 (치명 {s['fatal']}건)")
        from collections import Counter
        for k, n in Counter(i["kind"] for i in s["issues"]).most_common():
            print(f"  {k}: {n}건")
        return 0 if s["fatal"] == 0 else 1

    if a.command == "features":
        from src.features import compute, spec_table, to_grid
        from src.features import store
        step = c.get("features", {}).get("grid_step_sec", 10)
        froot = c.get("features", {}).get("root", "data/features/tick")
        av = loader.available(proc)
        if a.limit:
            av = av.head(a.limit)
        print(f"Feature 생성: {len(av):,} 종목·일 · 격자 {step}초 간격 → {froot}")
        import time
        t0, n, specs = time.time(), 0, None
        for r in av.iter_rows(named=True):
            df = loader.load_stock_day(proc, r["symbol"], r["date"])
            if df.is_empty():
                continue
            try:
                feats, specs = compute(to_grid(df))
            except ValueError as exc:                 # 정규장 체결 0건 등 — 건너뛰되 센다
                print(f"  건너뜀 {r['symbol']} {r['date']}: {exc}")
                continue
            store.write(store.downcast(store.sample_grid(feats, step)), froot,
                        r["symbol"], r["date"])
            n += 1
            if n % 500 == 0:
                print(f"  {n}/{len(av)} · {time.time()-t0:.0f}초", flush=True)
        if specs:
            spec_table(specs).write_csv("reports/feature_specs.csv")
            print(f"Feature {len(specs)}개 · 명세 reports/feature_specs.csv")
        print(f"완료 {n:,} 종목·일 · {time.time()-t0:.1f}초")
        return 0

    if a.command == "labels":
        import time

        import numpy as np
        import polars as pl

        from src.features import to_grid
        from src.features.grid import N_SEC
        from src.labels import triple_barrier as tb
        step = c.get("features", {}).get("grid_step_sec", 10)
        lroot = c.get("label", {}).get("root", "data/labels/tick")
        stops = tuple(abs(s) for s in c["label"]["stops"])
        av = loader.available(proc)
        if a.limit:
            av = av.head(a.limit)
        print(f"라벨 생성(5분내 +2%): {len(av):,} 종목·일 · 손절 {stops} → {lroot}")
        entries = np.arange(0, N_SEC, step, dtype=np.int64)
        t0, n = time.time(), 0
        for r in av.iter_rows(named=True):
            df = loader.load_stock_day(proc, r["symbol"], r["date"])
            if df.is_empty():
                continue
            try:
                g = to_grid(df)
            except ValueError as exc:
                print(f"  건너뜀 {r['symbol']} {r['date']}: {exc}")
                continue
            cols: dict = {"t_sec": entries}
            for s in stops:
                res = tb.label(g, entries, stop=s)
                tag = f"{s:g}".replace("0.", "")
                cols |= {f"barrier__s{tag}": res.barrier.astype(np.int8),
                         f"net_return__s{tag}": res.net_return.astype(np.float32),
                         f"gross_return__s{tag}": res.gross_return.astype(np.float32),
                         f"exit_sec__s{tag}": res.exit_sec.astype(np.int32),
                         f"ambiguous__s{tag}": res.ambiguous}
            # 온셋격리용(사전등록 §3-3): **진입 직전** horizon 동안 이미 올라 있었나.
            # 선행에서 엣지의 46%가 "이미 랠리 중"이라는 자명한 정보였음이 밝혀졌다.
            h = c["label"]["horizon_sec"]
            prior = np.full(len(entries), np.nan)
            m = entries >= h
            prior[m] = g.price[entries[m]] / g.price[entries[m] - h] - 1
            cols |= {"prior_return__300s": prior.astype(np.float32),
                     "entry_price": res.entry_price.astype(np.float32),
                     "cost": res.cost.astype(np.float32),
                     "hit_2pct_300s": res.hit.astype(np.float32),
                     "fwd_return__300s": res.fwd_return.astype(np.float32)}
            out = Path(lroot) / f"symbol={r['symbol']}"
            out.mkdir(parents=True, exist_ok=True)
            pl.DataFrame(cols).write_parquet(out / f"{r['date']}.parquet")
            n += 1
            if n % 500 == 0:
                print(f"  {n}/{len(av)} · {time.time()-t0:.0f}초", flush=True)
        print(f"완료 {n:,} 종목·일 · {time.time()-t0:.1f}초")
        return 0

    if a.command == "info":
        av = loader.available(proc)
        if av.is_empty():
            print("변환된 데이터가 없다. 먼저 `python main.py ingest`를 실행해라.")
            return 1
        print(f"종목 {av['symbol'].n_unique():,} | 날짜 {av['date'].n_unique():,} "
              f"({av['date'].min()} ~ {av['date'].max()}) | 종목·일 {len(av):,}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
