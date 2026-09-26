"""상승전조 마스터 — 단계 5~7 실행기.

사용: python -m backtesting.precursor_master_run
산출: results/precursor_master_*.csv, 콘솔 로그 전문

지시 §7 그대로: 모델은 importance를 얻는 수단이고, 판정은 **단순규칙을 IS에서 골라
OOS에 1회 적용**해서 한다. lightgbm이 없어 RandomForest를 쓴다(선행 precursor_final_model과
같은 선택, 새 의존성 추가 안 함).
"""
from __future__ import annotations

import os
import sys
import time

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtesting.precursor_master_analyze import (  # noqa: E402
    MIN_SUCCESS, evaluate, feature_columns, load, net_return, split, day_mean_ci)

HORIZONS = (1, 3, 5, 10, 15, 30, 60)
TARGETS = (0.005, 0.01, 0.02)
OUT = "results"


def main() -> int:
    t0 = time.time()
    d = load()
    seg = split(d)
    print(f"필터 통과 신호 {len(d):,}건")
    for k, v in seg.items():
        print(f"  {k:6s} {len(v):>7,}건 · {v['date'].nunique():>2}일 · {v['symbol'].nunique():>3}종목")

    feats = feature_columns(d)
    print(f"피처 {len(feats)}개")

    IS, OOS = seg["IS"], seg["OOS"]

    # ---------- ① 라벨 격자: 어느 horizon·target이 신호 대 잡음비가 좋은가 (IS에서만) ----------
    print("\n=== ① 라벨 격자 (IS) — 고정 목표를 미리 정하지 않았다(스펙 §13·14) ===")
    print(f"{'h':>3s} {'target':>7s} {'도달률':>7s} {'순수익':>9s} {'CI':>20s}")
    grid = []
    for h in HORIZONS:
        for tg in TARGETS:
            e = evaluate(IS, h, tg)
            grid.append({"horizon": h, "target": tg, **e})
            print(f"{h:>3d} {tg*100:>6.1f}% {e['hit']*100:>6.2f}% {e['net']*100:>+8.4f}% "
                  f"[{e['lo']*100:>+7.3f},{e['hi']*100:>+7.3f}]")
    gdf = pd.DataFrame(grid)
    gdf.to_csv(f"{OUT}/precursor_master_label_grid.csv", index=False)
    best = gdf.loc[gdf["net"].idxmax()]
    H, TG = int(best["horizon"]), float(best["target"])
    print(f"\nIS 최선 조합: +{H}분 / 목표 {TG*100:.1f}% (순수익 {best['net']*100:+.4f}%)")
    print("  ※ 이건 '고른 것'이지 '검증된 것'이 아니다 — OOS 1회로만 판정한다.")

    # ---------- ② 대조군 ----------
    print("\n=== ② 대조군: 규칙 없이 필터통과 T0 전부 ===")
    base = {}
    for k in ("IS", "OOS", "제외구간"):
        base[k] = evaluate(seg[k], H, TG)
        b = base[k]
        print(f"  {k:6s} n {b['n']:>7,} | 도달 {b['hit']*100:5.2f}% | 순수익 {b['net']*100:>+8.4f}% "
              f"[{b['lo']*100:+.3f},{b['hi']*100:+.3f}]")

    # ---------- ③ ML importance + SHAP (목적은 정확도가 아니라 순위) ----------
    print("\n=== ③ LightGBM feature importance + SHAP (IS 학습) ===")
    X = IS[feats].replace([np.inf, -np.inf], np.nan)      # LightGBM은 NaN을 그대로 다룬다
    y = (IS[f"mfe_{H}m"] >= TG).astype(int).to_numpy()
    print(f"  학습 {len(X):,}행 · 양성 {y.mean()*100:.2f}%")
    model = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31,
                               min_child_samples=50, subsample=0.8, subsample_freq=1,
                               colsample_bytree=0.8, random_state=0,
                               class_weight="balanced", n_jobs=-1, verbose=-1)
    model.fit(X, y)

    # gain importance — split 횟수보다 "실제로 얼마나 손실을 줄였나"가 해석에 맞다
    gain = model.booster_.feature_importance(importance_type="gain")
    imp = pd.DataFrame({"feature": feats, "importance": gain / max(gain.sum(), 1e-9)})

    # SHAP — importance는 "얼마나 쓰였나"만 말하고 **방향**을 안 말한다.
    # 평균 |SHAP|으로 크기를, 평균 SHAP 부호로 방향을 같이 본다.
    try:
        import shap
        sample = X.sample(min(5000, len(X)), random_state=0)
        sv = shap.TreeExplainer(model).shap_values(sample)
        if isinstance(sv, list):          # 이진분류에서 클래스별 리스트로 오는 버전 대응
            sv = sv[1]
        if sv.ndim == 3:                  # (n, feat, class) 형태 대응
            sv = sv[:, :, 1]
        imp["shap_abs"] = np.abs(sv).mean(axis=0)
        imp["shap_dir"] = np.sign(np.nanmean(sv * (sample.rank(pct=True) - 0.5).to_numpy(), axis=0))
    except Exception as exc:              # SHAP 실패해도 본 분석은 계속한다
        print(f"  (SHAP 생략: {exc})")
        imp["shap_abs"] = np.nan
        imp["shap_dir"] = np.nan

    imp = imp.sort_values("shap_abs" if imp["shap_abs"].notna().any() else "importance",
                          ascending=False)
    imp.to_csv(f"{OUT}/precursor_master_importance.csv", index=False)
    print(imp.head(15).to_string(index=False))
    print("  shap_dir: +1 = 값이 클수록 성공확률↑ / -1 = 클수록 ↓")
    print("  ※ importance 상위 = 채택이 아니다. 오늘 측정에서 tick_speed는 AUC 0.798인데")
    print("     순수익은 대조군보다 나빴다(손절률이 같이 올라 상쇄). 판정은 순수익으로 한다.")

    # ---------- ③-b 모델 자체를 OOS에 1회 적용 (해석규칙과 따로 비교) ----------
    from sklearn.metrics import roc_auc_score
    print("\n=== ③-b 모델 성능과 모델 상위10% 신호의 실제 손익 ===")
    p_is = model.predict_proba(X)[:, 1]
    X_oos = OOS[feats].replace([np.inf, -np.inf], np.nan)
    y_oos = (OOS[f"mfe_{H}m"] >= TG).astype(int).to_numpy()
    p_oos = model.predict_proba(X_oos)[:, 1]
    auc_is = roc_auc_score(y, p_is) if 0 < y.mean() < 1 else np.nan
    auc_oos = roc_auc_score(y_oos, p_oos) if 0 < y_oos.mean() < 1 else np.nan
    print(f"  AUC: IS {auc_is:.4f} / OOS {auc_oos:.4f}")
    print("   (IS AUC는 학습 적합도라 원래 높다 — 일반화 성능으로 읽지 않는다)")
    thr_p = float(np.quantile(p_is, 0.90))        # 문턱은 **IS에서** 고정
    e_m = evaluate(OOS[p_oos >= thr_p], H, TG)
    print(f"  모델 상위10%(문턱 IS고정 {thr_p:.4f}): OOS n {e_m['n']:,} "
          f"순수익 {e_m['net']*100:+.4f}% [{e_m['lo']*100:+.3f},{e_m['hi']*100:+.3f}] "
          f"| 대조군 {base['OOS']['net']*100:+.4f}%")
    rng0 = np.random.default_rng(0)
    rnd = [evaluate(OOS.sample(e_m["n"], random_state=int(s)), H, TG)["net"]
           for s in rng0.integers(0, 10**6, 30)]
    print(f"  무작위 같은 건수 30회: 평균 {np.mean(rnd)*100:+.4f}% "
          f"(표준편차 {np.std(rnd)*100:.4f}%p)")

    # ---------- ④ 단순규칙: IS 상위 피처 → 문턱 → OOS 1회 ----------
    print("\n=== ④ 단순규칙 (IS에서 선정 → OOS 1회 적용) ===")
    rules = []
    for f in imp["feature"].head(5):
        v_is = IS[f].replace([np.inf, -np.inf], np.nan)
        if v_is.notna().sum() < 100:
            continue
        # 방향은 IS에서 정한다: 상위10%와 하위10% 중 순수익이 나은 쪽
        cand = []
        for q, side in ((0.90, "상위10%"), (0.10, "하위10%")):
            thr = float(v_is.quantile(q))
            m = (IS[f] >= thr) if side == "상위10%" else (IS[f] <= thr)
            e = evaluate(IS[m], H, TG)
            cand.append((e.get("net", -9) if e["n"] else -9, side, thr, e))
        cand.sort(reverse=True)
        net_is, side, thr, e_is = cand[0]
        if e_is["n"] == 0 or e_is["hit"] * e_is["n"] < MIN_SUCCESS:
            print(f"  {f:26s} 판정불가(성공사례 <{MIN_SUCCESS})")
            continue
        m_oos = (OOS[f] >= thr) if side == "상위10%" else (OOS[f] <= thr)
        e_oos = evaluate(OOS[m_oos], H, TG)
        e_slip = evaluate(OOS[m_oos], H, TG, slip_mult=1.5)
        rules.append({"feature": f, "side": side, "thr": thr,
                      "IS_net": e_is["net"], "IS_n": e_is["n"],
                      "OOS_net": e_oos.get("net"), "OOS_n": e_oos["n"],
                      "OOS_lo": e_oos.get("lo"), "OOS_hi": e_oos.get("hi"),
                      "OOS_hit": e_oos.get("hit"), "OOS_slip15": e_slip.get("net"),
                      "OOS_symbols": e_oos.get("symbols")})
        print(f"  {f:26s} {side} thr={thr:>10.4g} | IS {e_is['net']*100:+.4f}% "
              f"→ OOS {e_oos.get('net', float('nan'))*100:+.4f}% "
              f"[{e_oos.get('lo', float('nan'))*100:+.3f},{e_oos.get('hi', float('nan'))*100:+.3f}] "
              f"n={e_oos['n']:,} | 대조군 {base['OOS']['net']*100:+.4f}% "
              f"| 슬립1.5x {e_slip.get('net', float('nan'))*100:+.4f}%")
    rdf = pd.DataFrame(rules)
    rdf.to_csv(f"{OUT}/precursor_master_rules.csv", index=False)

    # ---------- ⑤ 온셋격리 (기각조건 d) ----------
    print("\n=== ⑤ 온셋격리: T0 직전 5분에 이미 +2% 이상 오른 신호를 뺀다 ===")
    if "pb_already_rising" in d.columns:
        for k in ("IS", "OOS"):
            v = seg[k]
            iso = v[v["pb_already_rising"] != True]  # noqa: E712
            a, b = evaluate(v, H, TG), evaluate(iso, H, TG)
            print(f"  {k}: 전체 n {a['n']:,} 순수익 {a['net']*100:+.4f}% → "
                  f"격리 n {b['n']:,} {b['net']*100:+.4f}% "
                  f"(제외 {100*(1-b['n']/max(a['n'],1)):.1f}%)")

    # ---------- ⑥ 종목 일반화 (기각조건 e) ----------
    print("\n=== ⑥ 종목 일반화: 상위 기여 종목 1~2개를 빼면 결론이 바뀌나 ===")
    v = OOS.copy()
    v["_net"] = net_return(v, H, TG)
    contrib = v.groupby("symbol")["_net"].sum().sort_values(ascending=False)
    print(f"  상위 기여 3종목: {list(contrib.head(3).index)}")
    for drop in (1, 2):
        rest = v[~v["symbol"].isin(contrib.head(drop).index)]
        m, lo, hi, n = day_mean_ci(rest["_net"].to_numpy(), rest["date"].to_numpy())
        print(f"  상위 {drop}종목 제외: n {n:,} 순수익 {m*100:+.4f}% [{lo*100:+.3f},{hi*100:+.3f}]")

    # ---------- ⑦ 시간대 / 거래대금 구간 (지시 §8) ----------
    print("\n=== ⑦ 시간대별 (OOS) ===")
    v = OOS.copy(); v["_net"] = net_return(v, H, TG)
    for name, grp in v.groupby("time_bucket"):
        m, lo, hi, n = day_mean_ci(grp["_net"].to_numpy(), grp["date"].to_numpy())
        print(f"  {str(name):13s} n {n:>6,} | 순수익 {m*100:>+8.4f}% [{lo*100:+.3f},{hi*100:+.3f}]")

    print("\n=== ⑧ 진입시점 누적거래대금 구간별 (OOS) ===")
    q = v["cum_value"].quantile([0, .25, .5, .75, 1.0]).to_numpy()
    v["_bin"] = pd.cut(v["cum_value"], bins=np.unique(q), include_lowest=True)
    for name, grp in v.groupby("_bin", observed=True):
        m, lo, hi, n = day_mean_ci(grp["_net"].to_numpy(), grp["date"].to_numpy())
        print(f"  {str(name):32s} n {n:>6,} | {m*100:>+8.4f}% [{lo*100:+.3f},{hi*100:+.3f}]")

    print(f"\n총 {time.time()-t0:.0f}초")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
