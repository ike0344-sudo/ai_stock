"""전략1 3분 거래대금 하한 40억 vs 120억 재검증(2026-09-26 lead 지시) — 2단계: 하한별 재탐지 거래(results/floor_recheck/trades_<억>.pkl)로 분석.

final_strategy.py·validate_strategy1.py 는 **수정하지 않고** 그 함수(run_no_filter_baseline·run_full_sample_baseline·compute_portfolio_metrics)와
같은 ML 필터(랜덤포레스트, MODEL_KWARGS, 임계 0.3)·슬롯 5·초기자금 1천만·비용(왕복: 슬리피지 0.1%×2 + 수수료 0.015%×2 + 매도세 0.23% — 경로 순손익률에 이미 반영)을 그대로 쓴다.
읽기 전용(data/ 안 건드림). 실행: python floor_recheck_analyze.py > results/floor_recheck/analysis.txt
"""
import datetime as dt
import sys
import warnings

import numpy as np
import pandas as pd

from backtesting import validate_strategy1 as v1
from backtesting.ml.walk_forward import split as wf_split
from backtesting.ml_entry_filter import FEATURE_COLUMNS, InsufficientTrainingDataError, predict_quality_proba, train_entry_filter_model
from backtesting.portfolio_sim import simulate_slot_portfolio

warnings.filterwarnings("ignore")
OUT = "results/floor_recheck"
GRID = [40, 60, 80, 100, 120, 140, 160, 200]
TC = v1.TRADE_COLUMNS
PROBA, SLOTS, CAP = 0.3, 5, 10_000_000
NEW_FROM = dt.date(2026, 9, 10)  # 09-09 결정 뒤 새 데이터


def load() -> dict[int, pd.DataFrame]:
    out = {}
    for f in GRID:
        try:
            out[f] = pd.read_pickle(f"{OUT}/trades_{f}.pkl").sort_values("entry_time").reset_index(drop=True)
        except FileNotFoundError:
            pass
    return out


def pf(pct: np.ndarray) -> float:
    g, l = pct[pct > 0].sum(), -pct[pct <= 0].sum()
    return g / l if l > 0 else float("inf")


def portfolio(df: pd.DataFrame, slots: int = SLOTS) -> dict:
    return v1.compute_portfolio_metrics(simulate_slot_portfolio(df[TC], CAP, slots)) if len(df) else v1.compute_portfolio_metrics(
        simulate_slot_portfolio(pd.DataFrame(columns=TC), CAP, slots))


def fmt(m: dict) -> str:
    pfv = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
    return (f"거래 {m['n_trades']:>4d} 승률 {m['win_rate_pct']:5.1f}% 손익비 {pfv:>5s} 평균R {m['avg_r_multiple']:+.3f} "
            f"총수익 {m['total_return_pct']:+7.1f}% MDD {m['mdd_pct']:5.1f}%")


def ml_filter(is_df: pd.DataFrame, oos_df: pd.DataFrame) -> pd.DataFrame | None:
    if oos_df.empty:
        return None
    try:
        trained = train_entry_filter_model(is_df[FEATURE_COLUMNS], (is_df["pct"] > 0).astype(int), model_type="random_forest", **v1.MODEL_KWARGS)
    except InsufficientTrainingDataError:
        return None
    proba = predict_quality_proba(trained, oos_df[FEATURE_COLUMNS])
    return oos_df.loc[proba[proba >= PROBA].index]


def in_range(df: pd.DataFrame, a: dt.date, b: dt.date) -> pd.DataFrame:
    return df[df["entry_time"].dt.date.between(a, b)]


def walk_forward(T, splits, chooser, slots: int = SLOTS):
    """chooser(split, T) -> 그 폴드에서 쓸 하한(억). 고정 하한이면 상수를 돌려준다. 폴드마다 IS 구간에서만 학습·선택."""
    frames, folds = [], []
    for sp in splits:
        f = chooser(sp, T)
        tr = T[f]
        is_df, oos_df = in_range(tr, sp.train_start, sp.train_end), in_range(tr, sp.test_start, sp.test_end)
        kept = ml_filter(is_df, oos_df)
        folds.append({"train": f"{sp.train_start}~{sp.train_end}", "test": f"{sp.test_start}~{sp.test_end}", "floor": f,
                      "n_is": len(is_df), "n_oos_cand": len(oos_df), "n_oos_taken_ml": 0 if kept is None else len(kept)})
        if kept is not None and len(kept):
            frames.append(kept.assign(floor=f))
    comb = pd.concat(frames) if frames else T[next(iter(T))].iloc[0:0]
    return comb, portfolio(comb, slots), folds


def is_mean_by_floor(T, sp, min_n: int = 30) -> dict[int, tuple[float, int]]:
    out = {}
    for f, tr in T.items():
        d = in_range(tr, sp.train_start, sp.train_end)
        out[f] = (float(d["pct"].mean() * 100) if len(d) >= min_n else float("nan"), len(d))
    return out


def choose_signflip(sp, T):
    """09-09 규칙 그대로 — IS 원신호 기대값이 **양수로 바뀌고 그 위로도 계속 양수인 가장 낮은 하한**. 없으면 IS 기대값 최대 하한."""
    m = is_mean_by_floor(T, sp)
    fl = sorted(m)
    for i, f in enumerate(fl):
        if all(m[g][0] > 0 for g in fl[i:] if not np.isnan(m[g][0])) and m[f][0] > 0:
            return f
    ok = {f: v[0] for f, v in m.items() if not np.isnan(v[0])}
    return max(ok, key=ok.get)


def choose_argmax(sp, T):
    m = is_mean_by_floor(T, sp)
    ok = {f: v[0] for f, v in m.items() if not np.isnan(v[0])}
    return max(ok, key=ok.get)


def boot_ci(pct: np.ndarray, n=4000, seed=7):
    if len(pct) < 5:
        return (float("nan"),) * 4
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(pct), size=(n, len(pct)))
    means = pct[idx].mean(axis=1) * 100
    pfs = np.array([pf(pct[i]) for i in idx[:500]])
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)), float(np.percentile(pfs, 2.5)), float(np.percentile(pfs, 97.5)))


def main() -> None:
    T = load()
    print(f"로드한 하한(억): {sorted(T)}  (하한별 재탐지 거래)")
    base = T[40]
    start, end = base["entry_time"].min().date(), base["entry_time"].max().date()
    print(f"기간(40억 기준): {start} ~ {end}, 거래일 수 {base['entry_time'].dt.date.nunique()}일, 종목 {base['code'].nunique()}개")

    # ------------------------------------------------------------ 0. 원신호 표
    print("\n=== 0. 원신호(ML·슬롯 전) 기대값 — 하한을 바꿔 다시 탐지 ===")
    for f in sorted(T):
        d = T[f]
        print(f"  {f:>3d}억: {len(d):>5d}건 (종목 {d['code'].nunique():>3d}) 평균 순손익률 {d['pct'].mean()*100:+.3f}% 승률 {(d['pct']>0).mean()*100:.1f}% 손익비(원신호 합) {pf(d['pct'].to_numpy()):.2f}")
    print("  (09-09 기록: 40/50/60/70/80/100/120억 = -0.188/-0.159/-0.129/-0.088/-0.057/-0.029/+0.027%)")

    # ------------------------------------------------------------ 1. 재현 — validate_strategy1 기본 인자(train 240/test 60/step 60)
    print("\n=== ① 재현: validate_strategy1 기본 인자 — 하한별 그 하한의 첫 진입일부터 폴드를 잡는 '기본 방식' ===")
    for f in (40, 120):
        if f not in T:
            continue
        nf = v1.run_no_filter_baseline(T[f], SLOTS, CAP)
        ins = v1.run_full_sample_baseline(T[f], PROBA, SLOTS, CAP)
        wf = v1.run_walk_forward(T[f], 240, 60, 60, PROBA, SLOTS, CAP)
        print(f"[{f}억] 원신호 전체표본(ML 없음): {fmt(nf)}")
        print(f"[{f}억] ML In-Sample(참고용)  : {fmt(ins)}")
        print(f"[{f}억] ML 워크포워드 OOS     : {fmt(wf['metrics'])}   폴드 {sum(1 for x in wf['folds'] if x['status']=='ok')}개 유효")
        for x in wf["folds"]:
            print(f"      {x['test_start']}~{x['test_end']} 후보 {x['n_oos_candidates']} ML채택 {x.get('n_oos_taken_after_ml','-')} {x['status']}")

    # 같은 폴드 격자(40억 기준)로 통일 — 하한마다 첫 진입일이 달라 기본 방식은 폴드 경계가 어긋난다
    splits = wf_split(start, end, 240, 60, 60)
    print(f"\n같은 폴드 격자(40억 첫 진입일 {start} 기준, 240/60/60): {len(splits)}개 폴드  " +
          " | ".join(f"{s.test_start}~{s.test_end}" for s in splits))
    print("\n=== ① 같은 폴드 격자로 40 vs 120 (공정 비교) ===")
    res = {}
    for f in sorted(T):
        comb, m, folds = walk_forward(T, splits, lambda sp, T_, f=f: f)
        res[f] = (comb, m, folds)
    for f in (40, 120):
        if f in res:
            print(f"[{f}억] ML 워크포워드 OOS(같은 폴드): {fmt(res[f][1])}")
            for x in res[f][2]:
                print(f"      {x['test']} IS {x['n_is']} 후보 {x['n_oos_cand']} ML채택 {x['n_oos_taken_ml']}")
    if 40 in res and 120 in res:
        for f in (40, 120):
            p = res[f][0]["pct"].to_numpy()
            lo, hi, plo, phi = boot_ci(p)
            print(f"   {f}억 OOS 채택 {len(p)}건 평균 {p.mean()*100:+.3f}%  95%신뢰구간 [{lo:+.3f}, {hi:+.3f}]%  손익비(건별) {pf(p):.2f} [{plo:.2f}, {phi:.2f}]")

    # ------------------------------------------------------------ 2. 문턱을 IS 에서만 고르기
    print("\n=== ② 하한을 폴드마다 IS 구간에서만 고르기(같은 폴드 격자) ===")
    for name, ch in (("규칙A: 09-09 방식(IS 원신호 기대값이 양수가 되는 가장 낮은 하한)", choose_signflip),
                     ("규칙B: IS 원신호 기대값 최대 하한", choose_argmax)):
        comb, m, folds = walk_forward(T, splits, ch)
        print(f"{name}\n   합친 OOS: {fmt(m)}")
        for sp, x in zip(splits, folds):
            im = is_mean_by_floor(T, sp)
            print(f"   폴드 test {x['test']}: 고른 하한 {x['floor']}억 (IS 원신호 기대값 " +
                  ", ".join(f"{f}:{im[f][0]:+.2f}" for f in sorted(im)) + f") ML채택 {x['n_oos_taken_ml']}")
    if 40 in T and 120 in T:
        T2 = {40: T[40], 120: T[120]}
        comb, m, folds = walk_forward(T2, splits, choose_argmax)
        print(f"규칙B'(후보를 40·120 둘로만): 합친 OOS: {fmt(m)}  폴드별 고른 하한 {[x['floor'] for x in folds]}")
    if 40 in res:
        print(f"   (비교) 고정 40억: {fmt(res[40][1])}")
    if 120 in res:
        print(f"   (비교) 고정 120억: {fmt(res[120][1])}")

    # ------------------------------------------------------------ 3. 새 데이터
    print(f"\n=== ③ 새 데이터: 09-09 결정 뒤 {NEW_FROM} ~ {end} ===")
    for f in (40, 120):
        if f not in T:
            continue
        new = T[f][T[f]["entry_time"].dt.date >= NEW_FROM]
        old = T[f][T[f]["entry_time"].dt.date < NEW_FROM]
        kept = ml_filter(old, new)
        nfm = portfolio(new)
        print(f"[{f}억] 새 구간 원신호 {len(new)}건 평균 {new['pct'].mean()*100:+.3f}% 승률 {(new['pct']>0).mean()*100:.1f}% → 슬롯5(ML 없음): {fmt(nfm)}")
        if kept is not None:
            print(f"        ML(09-09까지 학습, 임계 0.3) 채택 {len(kept)}건: {fmt(portfolio(kept))}")
    # 새 구간 거래일 수
    if 40 in T:
        nd = T[40][T[40]["entry_time"].dt.date >= NEW_FROM]["entry_time"].dt.date.nunique()
        print(f"   (새 구간에서 40억 진입이 있었던 날 {nd}일)")

    # ------------------------------------------------------------ 4. 이웃
    print("\n=== ④ 이웃 하한 전부(같은 폴드 격자 ML 워크포워드 OOS, 좋고 나쁜 것 전부) ===")
    for f in sorted(T):
        m = res[f][1]
        nfm = portfolio(T[f])
        print(f"  {f:>3d}억: OOS {fmt(m)}")
        print(f"        전체표본 원신호(ML 없음) {fmt(nfm)}")

    # ------------------------------------------------------------ 5. 분기별
    print("\n=== ⑤ 분기별 — 원신호 평균 순손익률(전체표본)과 OOS 채택 거래 ===")
    for f in (40, 80, 120, 160):
        if f not in T:
            continue
        d = T[f].assign(q=T[f]["entry_time"].dt.to_period("Q").astype(str))
        g = d.groupby("q")["pct"].agg(["count", "mean"])
        print(f"  [{f}억 원신호] " + " | ".join(f"{q} n={int(r['count'])} {r['mean']*100:+.2f}%" for q, r in g.iterrows()))
    for f in (40, 120):
        if f in res and len(res[f][0]):
            c = res[f][0].assign(q=res[f][0]["entry_time"].dt.to_period("M").astype(str))
            g = c.groupby("q")["pct"].agg(["count", "mean"])
            print(f"  [{f}억 OOS 채택, 월별] " + " | ".join(f"{q} n={int(r['count'])} {r['mean']*100:+.2f}%" for q, r in g.iterrows()))

    # ------------------------------------------------------------ 7. 120억이 없애는 거래(40~120억 띠)의 정체 + 유의성
    if 40 in T and 120 in T:
        print("\n=== ⑦ 40억에는 있고 120억엔 없는 진입(= 120억이 걸러 내는 거래)과 둘 다 있는 진입 — 원신호 전체표본 ===")
        k40 = T[40].set_index(["code", "entry_time"])
        k120 = T[120].set_index(["code", "entry_time"])
        both = k40.index.intersection(k120.index)
        only40 = k40.index.difference(k120.index)
        only120 = k120.index.difference(k40.index)
        print(f"  40억 {len(k40)}건 = 둘 다 {len(both)} + 40억만 {len(only40)} / 120억에만 있는 진입(재탐지로 새로 생긴 것) {len(only120)}건")
        for name, idx, src in (("둘 다(120억 이상 대금)", both, k40), ("40억만(120억이 거르는 띠)", only40, k40), ("120억에만(재탐지 차이)", only120, k120)):
            if len(idx) == 0:
                continue
            p_ = src.loc[idx]["pct"].to_numpy()
            lo, hi, plo, phi = boot_ci(p_)
            print(f"  {name}: {len(p_)}건 평균 {p_.mean()*100:+.3f}% 95%CI [{lo:+.3f}, {hi:+.3f}]% 승률 {(p_>0).mean()*100:.1f}% 손익비 {pf(p_):.2f}")
        ex = k40.loc[only40].reset_index()
        kp = k40.loc[both].reset_index()
        qx = ex.groupby(ex["entry_time"].dt.to_period("Q").astype(str))["pct"].mean() * 100
        qk = kp.groupby(kp["entry_time"].dt.to_period("Q").astype(str))["pct"].mean() * 100
        print("  분기별 평균(%): " + " | ".join(f"{q} 띠 {qx.get(q, float('nan')):+.2f} / 둘다 {qk.get(q, float('nan')):+.2f}" for q in sorted(set(qx.index) | set(qk.index))))
        rng = np.random.default_rng(11)
        d = [rng.choice(kp["pct"].to_numpy(), len(kp)).mean() - rng.choice(ex["pct"].to_numpy(), len(ex)).mean() for _ in range(4000)]
        print(f"  (둘 다 평균 − 띠 평균) = {(kp['pct'].mean()-ex['pct'].mean())*100:+.3f}%p, 95%CI [{np.percentile(d,2.5)*100:+.3f}, {np.percentile(d,97.5)*100:+.3f}]%p  (0 이 구간 안이면 차이가 잡음일 수 있다)")

    # ------------------------------------------------------------ 8. 띠가 시대별로도 지는가 — 첫 폴드 IS 이전(2025-07~2026-02) / OOS 구간 / 새 구간
    if 40 in T:
        print("\n=== ⑧ 40억~경계 띠(경계 미만 대금 진입) vs 경계 이상 — 시대별 평균 순손익률(%) [건수] ===")
        eras = (("IS 시대(~2026-02-28)", None, dt.date(2026, 2, 28)), ("OOS 시대(2026-03-01~08-27)", dt.date(2026, 3, 1), dt.date(2026, 8, 27)),
                ("새 구간(09-10~)", NEW_FROM, None))
        k40 = T[40].set_index(["code", "entry_time"])
        for B in (80, 100, 120, 140, 160):
            if B not in T:
                continue
            kb = T[B].set_index(["code", "entry_time"]).index
            band = k40.loc[k40.index.difference(kb)].reset_index()
            above = k40.loc[k40.index.intersection(kb)].reset_index()
            row = []
            for name, a_, b_ in eras:
                def sel(d):
                    dd = d["entry_time"].dt.date
                    m = (dd >= a_) if a_ else (dd >= dt.date(1900, 1, 1))
                    m &= (dd <= b_) if b_ else m
                    return d[m]
                bx, ab = sel(band), sel(above)
                row.append(f"{name}: 띠 {bx['pct'].mean()*100:+.2f}[{len(bx)}] / 이상 {ab['pct'].mean()*100:+.2f}[{len(ab)}]")
            print(f"  경계 {B:>3d}억: " + " | ".join(row))

    # ------------------------------------------------------------ 6. 민감도(폴드 설정)
    print("\n=== 폴드 설정을 바꿔도 방향이 유지되나(40 vs 120, 슬롯5, ML 워크포워드 OOS) ===")
    wins = tot = 0
    for tr_d in (180, 240, 300):
        for te_d in (40, 60, 90):
            sps = wf_split(start, end, tr_d, te_d, te_d)
            if not sps:
                continue
            r = {f: walk_forward(T, sps, lambda sp, T_, f=f: f)[1] for f in (40, 120) if f in T}
            if len(r) == 2:
                tot += 1
                wins += r[120]["profit_factor"] > r[40]["profit_factor"]
                print(f"  train {tr_d}/test {te_d} ({len(sps)}폴드): 40억 PF {r[40]['profit_factor']:.2f} 수익 {r[40]['total_return_pct']:+.1f}% n={r[40]['n_trades']} | "
                      f"120억 PF {r[120]['profit_factor']:.2f} 수익 {r[120]['total_return_pct']:+.1f}% n={r[120]['n_trades']}")
    print(f"  → 120억 손익비가 40억보다 높은 설정 {wins}/{tot}")


if __name__ == "__main__":
    main()
