"""RandomForest vs LightGBM — **같은 조건에서** 실제로 차이가 나는지.

지금까지 둘을 공정하게 비교한 적이 없다(RF는 importance만, LGB는 모델 OOS까지).
여기서는 **같은 데이터·같은 라벨·같은 문턱 규칙**으로 셋을 돌린다:

1. RF (NaN → -999 대체)   ← RF는 NaN을 못 다룬다
2. LGB (NaN → -999 대체)  ← 전처리를 맞춘 공정 비교
3. LGB (NaN 그대로)       ← LGB의 자연스러운 방식

비교 항목은 **판별력(AUC)이 아니라 돈(순수익)까지** 본다 — 오늘 여러 번 확인했듯
AUC가 높아도 순수익은 대조군보다 나쁠 수 있다.
"""
from __future__ import annotations

import os
import sys
import time

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtesting.precursor_master_analyze import evaluate, feature_columns, load, split  # noqa: E402

H, TG = 3, 0.02          # precursor_master_run 과 동일 (IS에서 고른 라벨)
TOPQ = 0.90              # 모델 상위10%


def _fit_eval(name, model, Xtr, ytr, Xte, yte, IS, OOS, base_net, use_nan):
    t0 = time.time()
    model.fit(Xtr, ytr)
    fit_s = time.time() - t0
    p_is = model.predict_proba(Xtr)[:, 1]
    p_oos = model.predict_proba(Xte)[:, 1]
    thr = float(np.quantile(p_is, TOPQ))          # 문턱은 **IS에서** 고정
    e = evaluate(OOS[p_oos >= thr], H, TG)
    imp = getattr(model, "feature_importances_", None)
    return {
        "model": name, "nan": "원본유지" if use_nan else "-999대체",
        "fit_sec": fit_s,
        "auc_is": roc_auc_score(ytr, p_is), "auc_oos": roc_auc_score(yte, p_oos),
        "oos_n": e["n"], "oos_net": e["net"], "oos_lo": e["lo"], "oos_hi": e["hi"],
        "oos_hit": e["hit"], "vs_base": e["net"] - base_net,
    }, imp


def main() -> int:
    d = load()
    seg = split(d)
    IS, OOS = seg["IS"], seg["OOS"]
    feats = feature_columns(d)
    y_is = (IS[f"mfe_{H}m"] >= TG).astype(int).to_numpy()
    y_oos = (OOS[f"mfe_{H}m"] >= TG).astype(int).to_numpy()
    base = evaluate(OOS, H, TG)
    print(f"IS {len(IS):,}행(양성 {y_is.mean()*100:.2f}%) / OOS {len(OOS):,}행 · 피처 {len(feats)}개")
    print(f"대조군(규칙 없음) OOS 순수익 {base['net']*100:+.4f}%\n")

    Xi = IS[feats].replace([np.inf, -np.inf], np.nan)
    Xo = OOS[feats].replace([np.inf, -np.inf], np.nan)
    Xi_f, Xo_f = Xi.fillna(-999), Xo.fillna(-999)

    rows, imps = [], {}
    rf = RandomForestClassifier(n_estimators=300, max_depth=8, min_samples_leaf=50,
                                n_jobs=-1, random_state=0, class_weight="balanced")
    r, i = _fit_eval("RandomForest", rf, Xi_f, y_is, Xo_f, y_oos, IS, OOS, base["net"], False)
    rows.append(r); imps["RandomForest"] = i

    def _lgb():
        return lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31,
                                  min_child_samples=50, subsample=0.8, subsample_freq=1,
                                  colsample_bytree=0.8, random_state=0,
                                  class_weight="balanced", n_jobs=-1, verbose=-1)

    r, i = _fit_eval("LightGBM", _lgb(), Xi_f, y_is, Xo_f, y_oos, IS, OOS, base["net"], False)
    rows.append(r); imps["LightGBM(-999)"] = i
    r, i = _fit_eval("LightGBM", _lgb(), Xi, y_is, Xo, y_oos, IS, OOS, base["net"], True)
    rows.append(r); imps["LightGBM(NaN)"] = i

    df = pd.DataFrame(rows)
    print("=== 같은 조건 비교 ===")
    print(f"{'모델':14s} {'결측처리':9s} {'학습초':>6s} {'AUC IS':>7s} {'AUC OOS':>8s} "
          f"{'OOS n':>6s} {'OOS 순수익':>10s} {'CI':>18s} {'대조군대비':>9s}")
    for _, r in df.iterrows():
        print(f"{r['model']:14s} {r['nan']:9s} {r['fit_sec']:>6.1f} {r['auc_is']:>7.4f} "
              f"{r['auc_oos']:>8.4f} {r['oos_n']:>6,} {r['oos_net']*100:>+9.4f}% "
              f"[{r['oos_lo']*100:>+6.3f},{r['oos_hi']*100:>+6.3f}] {r['vs_base']*100:>+8.4f}%p")

    # importance 순위가 얼마나 다른가 — 상위 10개 겹침 + 순위상관
    print("\n=== feature 순위 차이 ===")
    ranks = {}
    for k, v in imps.items():
        if v is None:
            continue
        ranks[k] = pd.Series(v, index=feats).rank(ascending=False)
    keys = list(ranks)
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            ka, kb = keys[a], keys[b]
            sp = ranks[ka].corr(ranks[kb], method="spearman")
            top_a = set(ranks[ka].nsmallest(10).index)
            top_b = set(ranks[kb].nsmallest(10).index)
            print(f"  {ka:16s} vs {kb:16s} 순위상관 {sp:+.3f} · 상위10 겹침 {len(top_a & top_b)}/10")
    print("\n  각 모델 상위 8개:")
    for k in keys:
        print(f"    {k:16s} {list(ranks[k].nsmallest(8).index)}")

    df.to_csv("results/precursor_master_modelcmp.csv", index=False)
    print("\n산출: results/precursor_master_modelcmp.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
