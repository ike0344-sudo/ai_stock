"""Phase 4 실행 — 사전등록 기각조건 판정.

사전등록: docs/TICKRESEARCH_LABEL_5MIN_2PCT_PREREGISTRATION.md
**IS에서만 고르고 OOS에 1회 적용한다.** OOS를 보고 다시 고르지 않는다.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from src.analysis import screen  # noqa: E402

STOP = "01"                                   # 손절 -1%
RET = f"net_return__s{STOP}"
BAR = f"barrier__s{STOP}"
OUT = Path("reports")


def main() -> int:
    t0 = time.time()
    specs = pl.read_csv("reports/feature_specs.csv")
    feats = [f for f in specs["feature"] if f != "t_sec"]

    lf = screen.load("data/features/tick", "data/labels/tick", STOP)
    df = lf.filter(pl.col(BAR) != -9).collect()
    print(f"조인 {df.height:,}행 · {time.time()-t0:.0f}초", flush=True)

    seg = screen.split(df)
    for k, v in seg.items():
        print(f"  {k}: {v.height:,}행 · {v['date'].n_unique()}일 · {v['symbol'].n_unique()}종목")

    y_is = (seg["IS"][BAR].to_numpy() == 1).astype(float)

    # --- 1. IS에서 지표 80개 AUC (익절 여부) ---
    rows = []
    for f in feats:
        if f not in seg["IS"].columns:
            continue
        a = screen.auc(seg["IS"][f].to_numpy().astype(float), y_is)
        rows.append({"feature": f, "is_auc": a, "edge": abs(a - 0.5) if a == a else np.nan})
    ic = pl.DataFrame(rows).join(specs.select("feature", "prior_verdict",
                                              "previously_rejected"), on="feature")
    ic = ic.sort("edge", descending=True)
    ic.write_csv(OUT / "phase4_is_auc.csv")
    print("\n=== IS AUC 상위 12 (80개 중) ===")
    print(ic.head(12).to_pandas().to_string(index=False))

    # --- 2. 대조군: 아무 신호 없이 상시진입 ---
    print("\n=== 대조군(상시진입) ===")
    base = {}
    for k, v in seg.items():
        base[k] = screen.evaluate(v, pl.lit(True), RET, BAR)
        b = base[k]
        print(f"  {k}: n {b['n']:>9,} | 순수익 {b['net_mean']*100:+.4f}% "
              f"(SE {b['net_se']*100:.4f}) CI[{b['ci_lo']*100:+.3f},{b['ci_hi']*100:+.3f}] "
              f"| 익절 {b['tp_rate']*100:.2f}%")

    # --- 3. IS 최강 지표로 규칙 → OOS 1회 적용 ---
    top = ic.filter(pl.col("is_auc").is_not_null()).head(3)
    print("\n=== IS 상위 3지표로 만든 규칙을 OOS에 1회 적용 ===")
    results = []
    for r in top.iter_rows(named=True):
        f, a = r["feature"], r["is_auc"]
        hi = a > 0.5                                  # 방향은 IS에서 정한다
        q = 0.90 if hi else 0.10
        thr = float(np.nanquantile(seg["IS"][f].to_numpy().astype(float), q))
        cond = (pl.col(f) >= thr) if hi else (pl.col(f) <= thr)
        line = {"feature": f, "is_auc": a, "dir": "상위10%" if hi else "하위10%",
                "thr": thr, "prior": r["prior_verdict"]}
        for k, v in seg.items():
            e = screen.evaluate(v, cond, RET, BAR)
            line |= {f"{k}_n": e["n"], f"{k}_net": e.get("net_mean"),
                     f"{k}_lo": e.get("ci_lo"), f"{k}_hi": e.get("ci_hi"),
                     f"{k}_tp": e.get("tp_rate"), f"{k}_days": e.get("days"),
                     f"{k}_sym": e.get("symbols")}
            print(f"  {f:28s} {line['dir']} | {k}: n {e['n']:>8,} "
                  f"순수익 {e.get('net_mean',float('nan'))*100:+.4f}% "
                  f"CI[{e.get('ci_lo',float('nan'))*100:+.3f},{e.get('ci_hi',float('nan'))*100:+.3f}] "
                  f"익절 {e.get('tp_rate',float('nan'))*100:.2f}% "
                  f"vs 대조군 {base[k]['net_mean']*100:+.4f}%")
        results.append(line)
    pl.DataFrame(results).write_csv(OUT / "phase4_rules.csv")

    # --- 4. 온셋격리 민감도 (사전등록 §3-3 / 기각조건 (e)) ---
    print("\n=== 온셋격리: '이미 직전 5분간 +2% 이상 오른' 진입을 뺀다 ===")
    for r in top.head(1).iter_rows(named=True):
        f = r["feature"]
        hi = r["is_auc"] > 0.5
        thr = float(np.nanquantile(seg["IS"][f].to_numpy().astype(float), 0.90 if hi else 0.10))
        cond = (pl.col(f) >= thr) if hi else (pl.col(f) <= thr)
        onset = pl.col("prior_return__300s") < 0.02
        for k, v in seg.items():
            a_all = screen.auc(v[f].to_numpy().astype(float), (v[BAR].to_numpy() == 1).astype(float))
            vv = v.filter(onset)
            a_iso = screen.auc(vv[f].to_numpy().astype(float), (vv[BAR].to_numpy() == 1).astype(float))
            e = screen.evaluate(vv, cond, RET, BAR)
            print(f"  {k}: AUC {a_all:.4f} → 격리 후 {a_iso:.4f} "
                  f"(엣지 {abs(a_all-0.5):.4f}→{abs(a_iso-0.5):.4f}, "
                  f"{100*(1-abs(a_iso-0.5)/max(abs(a_all-0.5),1e-9)):.1f}% 감소) | "
                  f"격리 후 규칙 순수익 {e.get('net_mean',float('nan'))*100:+.4f}%")

    # --- 5. 슬리피지 1.5배 (기각조건 (f)) ---
    print("\n=== 슬리피지 1.5배 (실측 꼬리 반영) ===")
    extra = 0.001 * 0.5 * 2                        # 편도 0.05%p씩 더, 왕복
    for r in top.head(1).iter_rows(named=True):
        f = r["feature"]
        hi = r["is_auc"] > 0.5
        thr = float(np.nanquantile(seg["IS"][f].to_numpy().astype(float), 0.90 if hi else 0.10))
        cond = (pl.col(f) >= thr) if hi else (pl.col(f) <= thr)
        for k, v in seg.items():
            e = screen.evaluate(v.with_columns(pl.col(RET) - extra), cond, RET, BAR)
            print(f"  {k}: {e.get('net_mean',float('nan'))*100:+.4f}%")

    print(f"\n총 {time.time()-t0:.0f}초 · 산출물 {OUT}/phase4_is_auc.csv, phase4_rules.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
