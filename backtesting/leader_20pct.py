"""당일 +20% 종목을 +10%(T0)에서 미리 사기 — A군(+20% 달성) vs B군(못 감) 대조 측정.

사전등록: docs/LEADER_20PCT_PREREGISTRATION.md (표본 중단규칙·기각조건이 거기 있다).

## 재사용 (중복 구현 금지)
`_precursor_fastpath.to_grid`(정규장 필터 + 1초격자 + tie-break 수정본)/`window_sum`,
`shooting_precursor._tick_rule_direction`/`_shift_window_sum`/`TRAIN_DATES`/`TEST_DATES`,
`t0_forward_return._expanding_period_avg`/`round_trip_cost_pct`.
새로 짠 것은 이 측정 고유의 T0 탐지·A/B 분류·순위 계산·효과크기 집계뿐이다.

## 핵심 정의
- T0 = 정규장 첫 틱부터 훑어 체결가가 prev_close*1.10 이상이 된 **첫 틱**(그 가격이 진입가).
- A군 = T0 이후(포함) prev_close*1.20 이상에 닿음 / B군 = 못 닿음.
- 피처·순위·누적대금은 전부 **[.., T0초) 구간**만 본다(T0가 속한 초 자체도 제외) —
  T0 이후 정보 금지.
- 순위는 **117종목 유니버스 내 순위**다(시장 전체 아님 — 사전등록 §0 참고).

실행: python -m backtesting.leader_20pct
"""
import glob
import os
import time

import numpy as np
import pandas as pd

from _precursor_fastpath import N, SESSION_START, to_grid, window_sum
from backtesting.shooting_precursor import TEST_DATES, TRAIN_DATES, _shift_window_sum, _tick_rule_direction
from backtesting.t0_forward_return import _expanding_period_avg, round_trip_cost_pct

TICK_DIR = "data/stocks/tick_al"
DAILY_DIR = "data/stocks/daily"

ENTRY_MULT = 1.10   # +10% - 진입(결정) 문턱
TARGET_MULT = 1.20  # +20% - A군 판정 문턱

# 부동소수 경계 보정: 100.0*1.10 == 110.00000000000001 이라 "정확히 +10%인 체결"이
# 조용히 탈락한다. KRX 체결가는 정수(원)이고 전일종가가 10의 배수인 경우가 흔해
# (호가단위 10/50/100/500/1000) 문턱이 합법 호가에 정확히 떨어지는 일이 드물지 않다 —
# 유닛테스트로 실제 재현해 잡은 버그. 가격 간격이 최소 1원이므로 1e-6원 여유면 안전하다.
PRICE_EPS = 1e-6


def threshold(prev_close: float, mult: float) -> float:
    return prev_close * mult - PRICE_EPS

FEATURE_WINDOWS = {"w10": 10, "w20": 20, "w30": 30, "w60": 60}    # 초
VALUE_SURGE_WINDOWS = {"vs1": 1, "vs3": 3, "vs5": 5, "vs10": 10}  # 초

# 큐(1)에서 살아남은 것 + 죽었던 것(이 라벨에서 한 번은 재측정하라는 지시)
FEATURE_COLUMNS = (
    [f"{k}_tick_speed" for k in FEATURE_WINDOWS]
    + [f"{k}_value_surge" for k in VALUE_SURGE_WINDOWS]
    + [f"{k}_buy_sell_gap" for k in FEATURE_WINDOWS]
    + [f"{k}_intensity_change" for k in FEATURE_WINDOWS]
    + [f"{k}_buy_ratio" for k in FEATURE_WINDOWS]
)
DESCRIPTIVE_COLUMNS = ["value_rank", "cum_value_eok", "t0_hour"]

CLOSE_MISMATCH_TOL = 0.01  # 일봉 종가 vs 틱 마지막 체결가 괴리 1% 초과면 제외(수정주가 등)


def prev_close_map(codes: list[str]) -> dict:
    """{code: Series(date -> close)} - 전일종가 조회용 일봉 캐시."""
    out = {}
    for code in codes:
        path = os.path.join(DAILY_DIR, f"{code}.csv")
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        out[code] = df["close"].sort_index()
    return out


def lookup_prev_close(close_series: pd.Series, date_str: str) -> float | None:
    """date_str 직전 거래일의 종가. 없으면 None."""
    day = pd.Timestamp(date_str)
    past = close_series[close_series.index < day]
    return float(past.iloc[-1]) if len(past) else None


def stock_day_scan(path: str, code: str, date_str: str, prev_close: float | None) -> dict | None:
    """한 종목·일 → 이벤트 dict(+ 순위 계산용 누적대금 곡선). T0가 없어도 곡선은 낸다."""
    g = to_grid(path)
    if g is None:
        return None
    tick_sec, tick_prc, tick_qty = g["tick_sec"], g["tick_prc"], g["tick_qty"]
    if len(tick_sec) == 0:
        return None

    value_per_sec = np.bincount(tick_sec, weights=tick_prc * tick_qty, minlength=N)
    cs_value = np.concatenate(([0.0], np.cumsum(value_per_sec)))  # cs_value[k] = [0,k) 합

    last_price = float(tick_prc[-1])
    rec = {
        "code": code, "date": date_str, "cs_value": cs_value,
        "last_price": last_price, "prev_close": prev_close,
        "raw_rows": g["raw_rows"], "kept_rows": g["kept_rows"],
        "has_t0": False,
    }
    if prev_close is None or prev_close <= 0:
        rec["skip_reason"] = "전일종가없음"
        return rec

    entry_thr, target_thr = threshold(prev_close, ENTRY_MULT), threshold(prev_close, TARGET_MULT)
    hits = np.flatnonzero(tick_prc >= entry_thr)
    if len(hits) == 0:
        return rec  # +10% 미통과 (순위 계산엔 여전히 참여)

    i0 = int(hits[0])
    t0_sec, t0_price = int(tick_sec[i0]), float(tick_prc[i0])
    rec.update({
        "has_t0": True, "t0_sec": t0_sec, "t0_price": t0_price,
        "t0_hour": (t0_sec + SESSION_START) // 3600,
        "t0_pct": t0_price / prev_close - 1,
        "reached_20": bool(tick_prc[i0:].max() >= target_thr),
        "gap_open_over_10": bool(tick_prc[0] >= entry_thr),
        "gap_open_over_20": bool(tick_prc[0] >= target_thr),
        "cum_value_eok": cs_value[t0_sec] / 1e8,  # T0 직전까지 누적 거래대금(억원)
    })

    # --- T0 직전 관측창 피처 (큐(1) 정의 그대로, 창은 [T0-w, T0)) ---
    vol_per_sec = g["vol"]
    cnt_per_sec = g["cnt"]
    direction = _tick_rule_direction(tick_prc)
    buy_qty_per_sec = np.bincount(tick_sec, weights=np.where(direction > 0, tick_qty, 0.0), minlength=N)
    sell_qty_per_sec = np.bincount(tick_sec, weights=np.where(direction < 0, tick_qty, 0.0), minlength=N)

    np.seterr(divide="ignore", invalid="ignore")
    for key, w in FEATURE_WINDOWS.items():
        win_cnt = window_sum(cnt_per_sec, w)
        win_vol = window_sum(vol_per_sec, w)
        win_buy = window_sum(buy_qty_per_sec, w)
        win_sell = window_sum(sell_qty_per_sec, w)

        rec[f"{key}_tick_speed"] = win_cnt[t0_sec] / w
        gap = (win_buy[t0_sec] - win_sell[t0_sec]) / win_vol[t0_sec] if win_vol[t0_sec] else np.nan
        rec[f"{key}_buy_sell_gap"] = gap
        rec[f"{key}_buy_ratio"] = win_buy[t0_sec] / win_vol[t0_sec] if win_vol[t0_sec] else np.nan

        intensity = win_buy / win_sell * 100
        intensity[win_sell == 0] = np.nan
        prev_intensity = _shift_window_sum(intensity, w)
        ic = intensity[t0_sec] / prev_intensity[t0_sec] - 1
        rec[f"{key}_intensity_change"] = np.nan if not np.isfinite(ic) else ic

    grid = np.array([t0_sec])
    for key, w in VALUE_SURGE_WINDOWS.items():
        win_value = window_sum(value_per_sec, w)
        avg_value = _expanding_period_avg(cs_value, grid, w)
        vs = win_value[t0_sec] / avg_value[t0_sec] if avg_value[t0_sec] else np.nan
        rec[f"{key}_value_surge"] = np.nan if not np.isfinite(vs) else vs

    return rec


def scan_all(tick_dir: str = TICK_DIR) -> tuple[pd.DataFrame, dict]:
    """날짜별로 묶어 스캔한다 - 순위는 같은 날짜·같은 초의 종목 간 비교라 날짜 단위가 필요."""
    codes = sorted(d for d in os.listdir(tick_dir) if os.path.isdir(os.path.join(tick_dir, d)))
    closes = prev_close_map(codes)
    dates = sorted({os.path.splitext(os.path.basename(p))[0]
                    for p in glob.glob(os.path.join(tick_dir, "*", "*.parquet"))})

    rows, audit = [], {"stock_days": 0, "raw_rows": 0, "kept_rows": 0, "no_prev_close": 0,
                        "close_mismatch": 0, "no_t0": 0}
    for date_str in dates:
        recs = []
        for code in codes:
            path = os.path.join(tick_dir, code, f"{date_str}.parquet")
            if not os.path.exists(path):
                continue
            pc = lookup_prev_close(closes[code], date_str) if code in closes else None
            rec = stock_day_scan(path, code, date_str, pc)
            if rec is None:
                continue
            audit["stock_days"] += 1
            audit["raw_rows"] += rec["raw_rows"]
            audit["kept_rows"] += rec["kept_rows"]
            if rec.get("prev_close") is None:
                audit["no_prev_close"] += 1
                continue
            recs.append(rec)

        # 데이터 검증: 일봉 종가 vs 틱 마지막 체결가 (수정주가/분할 미반영 탐지)
        kept = []
        for rec in recs:
            today_close = closes[rec["code"]].get(pd.Timestamp(date_str))
            rec["close_gap"] = (abs(rec["last_price"] / float(today_close) - 1)
                                 if today_close and today_close > 0 else np.nan)
            if np.isfinite(rec["close_gap"]) and rec["close_gap"] > CLOSE_MISMATCH_TOL:
                audit["close_mismatch"] += 1
                continue
            kept.append(rec)

        curves = {r["code"]: r["cs_value"] for r in kept}
        for rec in kept:
            if not rec["has_t0"]:
                audit["no_t0"] += 1
                continue
            t0_sec = rec["t0_sec"]
            mine = rec["cs_value"][t0_sec]
            rec["value_rank"] = 1 + sum(1 for c, cv in curves.items()
                                        if c != rec["code"] and cv[t0_sec] > mine)
            rec["universe_size"] = len(curves)
            rows.append({k: v for k, v in rec.items() if k != "cs_value"})

    return pd.DataFrame(rows), audit


def add_trade_returns(df: pd.DataFrame) -> pd.DataFrame:
    """V1(+20% 지정가 매도, 못 닿으면 종가) / V2(전원 종가청산) 총수익·순수익."""
    out = df.copy()
    target_px = out["prev_close"] * TARGET_MULT
    close_ret = out["last_price"] / out["t0_price"] - 1
    out["gross_v1"] = np.where(out["reached_20"], target_px / out["t0_price"] - 1, close_ret)
    out["gross_v2"] = close_ret
    cost = round_trip_cost_pct(out["t0_price"].to_numpy())
    out["cost_pct"] = cost
    out["net_v1"] = out["gross_v1"] - cost
    out["net_v2"] = out["gross_v2"] - cost
    return out


def cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < 2 or len(b) < 2:
        return np.nan
    pooled = np.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(a) + len(b) - 2))
    return float((a.mean() - b.mean()) / pooled) if pooled else np.nan


def group_compare(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """A군 vs B군: 중앙값·사분위 + 효과크기(Cohen's d, AUC) + Mann-Whitney U p."""
    from scipy.stats import mannwhitneyu
    from sklearn.metrics import roc_auc_score

    a_mask = df["reached_20"].astype(bool)
    rows = []
    for col in columns:
        a = df.loc[a_mask, col].to_numpy(dtype=float)
        b = df.loc[~a_mask, col].to_numpy(dtype=float)
        a_f, b_f = a[np.isfinite(a)], b[np.isfinite(b)]
        row = {"feature": col, "n_A": len(a_f), "n_B": len(b_f),
               "A_median": np.median(a_f) if len(a_f) else np.nan,
               "A_q1": np.percentile(a_f, 25) if len(a_f) else np.nan,
               "A_q3": np.percentile(a_f, 75) if len(a_f) else np.nan,
               "B_median": np.median(b_f) if len(b_f) else np.nan,
               "B_q1": np.percentile(b_f, 25) if len(b_f) else np.nan,
               "B_q3": np.percentile(b_f, 75) if len(b_f) else np.nan,
               "cohens_d": cohens_d(a, b)}
        if len(a_f) >= 2 and len(b_f) >= 2:
            y = np.r_[np.ones(len(a_f)), np.zeros(len(b_f))]
            row["auc"] = roc_auc_score(y, np.r_[a_f, b_f])
            row["auc_abs"] = max(row["auc"], 1 - row["auc"])
            row["mwu_p"] = mannwhitneyu(a_f, b_f, alternative="two-sided").pvalue
        else:
            row["auc"] = row["auc_abs"] = row["mwu_p"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows).sort_values("auc_abs", ascending=False, na_position="last")


def prev_day_turnover_eok(closes: dict, code: str, date_str: str, volumes: dict) -> float:
    """전일 거래대금(억원) = 전일종가 x 전일거래량. **교란 점검용 진단 지표**(사전등록
    피처 목록 밖 - 새 예측피처로 쓰는 게 아니라 "T0 누적대금이 적다"는 신호가 그냥
    '원래 작은 종목'인지 '오늘 아직 안 터진 상태'인지 가르기 위해 추가했음을 명시).
    전일 정보만 쓰므로 미래참조는 없다."""
    if code not in closes or code not in volumes:
        return np.nan
    day = pd.Timestamp(date_str)
    c = closes[code][closes[code].index < day]
    v = volumes[code][volumes[code].index < day]
    if not len(c) or not len(v):
        return np.nan
    return float(c.iloc[-1]) * float(v.iloc[-1]) / 1e8


def evaluate_rule(df: pd.DataFrame, conditions: dict, label: str, cost_mult: float = 1.0) -> dict:
    """conditions: {feature: (direction, threshold)} (direction '>=' 또는 '<=').
    cost_mult는 슬리피지 민감도용 - 왕복비용 전체에 곱한다(보수적으로 키우는 용도)."""
    mask = pd.Series(True, index=df.index)
    for feat, (direction, thr) in conditions.items():
        col = df[feat]
        mask &= (col >= thr) if direction == ">=" else (col <= thr)
        mask &= col.notna()
    sub = df[mask]
    if sub.empty:
        return {"group": label, "n": 0, "base_rate_pct": np.nan, "net_v1_pct": np.nan}
    cost = sub["cost_pct"] * cost_mult
    out = {
        "group": label, "n": len(sub),
        "n_A": int(sub["reached_20"].sum()),
        "base_rate_pct": 100 * sub["reached_20"].mean(),
        "gross_v1_pct": 100 * sub["gross_v1"].mean(),
        "net_v1_pct": 100 * (sub["gross_v1"] - cost).mean(),
        "net_v1_median_pct": 100 * (sub["gross_v1"] - cost).median(),
        "net_v2_pct": 100 * (sub["gross_v2"] - cost).mean(),
        "trades_per_day": len(sub) / sub["date"].nunique(),
    }
    lo, hi = bootstrap_net_ci(100 * (sub["gross_v1"] - cost).to_numpy())
    out["net_v1_ci95"] = f"[{lo:.2f}, {hi:.2f}]"
    return out


def bootstrap_net_ci(values: np.ndarray, n_draws: int = 5000, seed: int = 42) -> tuple[float, float]:
    """표본이 작아(OOS 20건대) 평균 하나로 판단하면 안 된다 - 부트스트랩 95% 구간."""
    v = values[np.isfinite(values)]
    if len(v) < 3:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    means = v[rng.integers(0, len(v), size=(n_draws, len(v)))].mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def expected_value(df: pd.DataFrame, label: str) -> dict:
    """+10% 통과 표본 전체의 평균 손익 = 기저율 x A군 + (1-기저율) x B군."""
    a = df[df["reached_20"]]
    b = df[~df["reached_20"]]
    return {
        "group": label, "n": len(df), "base_rate_pct": 100 * len(a) / len(df) if len(df) else np.nan,
        "gross_v1_pct": 100 * df["gross_v1"].mean(), "net_v1_pct": 100 * df["net_v1"].mean(),
        "gross_v2_pct": 100 * df["gross_v2"].mean(), "net_v2_pct": 100 * df["net_v2"].mean(),
        "A_net_v1_pct": 100 * a["net_v1"].mean() if len(a) else np.nan,
        "B_net_v1_pct": 100 * b["net_v1"].mean() if len(b) else np.nan,
        "B_net_v2_pct": 100 * b["net_v2"].mean() if len(b) else np.nan,
        "cost_pct": 100 * df["cost_pct"].mean(),
    }


def main():
    t0 = time.time()
    n_files = len(glob.glob(os.path.join(TICK_DIR, "*", "*.parquet")))
    print(f"스캔 시작 ({n_files}개 종목·일, T0 한 점만 계산 + 날짜별 순위)", flush=True)
    print("ETA 추정: 60~120초 (큐(6)이 같은 파일 전량 10초격자 피처까지 66초였음)", flush=True)

    events, audit = scan_all()
    dt = time.time() - t0
    print(f"스캔 {dt:.1f}초", flush=True)
    print(f"검증: 종목·일 {audit['stock_days']:,} | 원본 {audit['raw_rows']:,}행 → "
          f"정규장 {audit['kept_rows']:,}행 (시간외 {100*(1-audit['kept_rows']/audit['raw_rows']):.1f}% 제거) | "
          f"전일종가없음 {audit['no_prev_close']} | 종가불일치 제외 {audit['close_mismatch']} | "
          f"+10% 미통과 {audit['no_t0']:,}", flush=True)

    if events.empty:
        print("+10% 통과 사례 0건 — 여기서 중단")
        return {"events": events, "audit": audit}

    events = add_trade_returns(events)
    os.makedirs("results", exist_ok=True)
    events.to_csv("results/leader_20pct_events.csv", index=False, encoding="utf-8-sig")

    # --- 0단계: 표본 ---
    n_a = int(events["reached_20"].sum())
    n_b = int((~events["reached_20"]).sum())
    is_ev = events[events["date"].isin(TRAIN_DATES)]
    oos_ev = events[events["date"].isin(TEST_DATES)]
    print("=== 0단계 표본 ===")
    print(f"+10% 통과(T0 있음) {len(events)}건 | A군(+20% 달성) {n_a}건 | B군 {n_b}건 | "
          f"기저율 {100*n_a/len(events):.1f}%")
    print(f"IS(12일): 전체 {len(is_ev)} / A {int(is_ev['reached_20'].sum())} | "
          f"OOS(6일): 전체 {len(oos_ev)} / A {int(oos_ev['reached_20'].sum())}")
    print(f"갭시작 +10%이상 {int(events['gap_open_over_10'].sum())}건 "
          f"(그중 +20%이상 시작 {int(events['gap_open_over_20'].sum())}건 — ≤+10% 진입 불가)")
    print("A군 날짜분포:", events[events["reached_20"]]["date"].value_counts().sort_index().to_dict())
    print("A군 종목분포:", events[events["reached_20"]]["code"].value_counts().to_dict())

    if n_a < 20:
        print(f"\n[중단] 사전등록 §2 규칙: A군 {n_a}건 < 20건 — 1~3단계 진행하지 않는다.")
        return {"events": events, "audit": audit, "n_a": n_a, "n_b": n_b, "stopped": True}

    # 사전등록 §1: 갭시작(첫 틱이 이미 +10% 이상)은 "≤+10%에 산다"는 전제가 성립하지
    # 않는다(진입가가 이미 한참 위) - 별도 집계하고 본 분석에서는 뺀다.
    gap = events[events["gap_open_over_10"].astype(bool)]
    events = events[~events["gap_open_over_10"].astype(bool)].reset_index(drop=True)
    print(f"\n=== 갭시작 {len(gap)}건 별도 집계 (본 분석에서 제외) ===")
    print(f"A군 {int(gap['reached_20'].sum())}건 기저율 {100*gap['reached_20'].mean():.1f}% "
          f"| 진입가 중앙값 +{100*gap['t0_pct'].median():.2f}% | net_v1 평균 {100*gap['net_v1'].mean():.2f}%")
    print(f"→ 남은 매매가능 표본 {len(events)}건 (A {int(events['reached_20'].sum())} / "
          f"B {int((~events['reached_20']).sum())}, 기저율 {100*events['reached_20'].mean():.1f}%)")
    is_ev = events[events["date"].isin(TRAIN_DATES)]
    oos_ev = events[events["date"].isin(TEST_DATES)]
    print(f"IS A {int(is_ev['reached_20'].sum())} / OOS A {int(oos_ev['reached_20'].sum())}")

    # --- 1·2단계: 기술통계 + 효과크기 (A/B 나란히) ---
    desc = group_compare(events, DESCRIPTIVE_COLUMNS)
    feat = group_compare(events, FEATURE_COLUMNS)
    desc.to_csv("results/leader_20pct_descriptive.csv", index=False, encoding="utf-8-sig")
    feat.to_csv("results/leader_20pct_features.csv", index=False, encoding="utf-8-sig")
    print("\n=== 1·2단계: T0 시점 기술통계 + 효과크기 (A vs B) ===")
    print(desc.to_string(index=False))
    print("\n=== 3단계: T0 이전 관측창 피처 (큐(1) 재사용, 죽었던 것 포함) ===")
    print(feat.to_string(index=False))

    print("\n=== T0 시각 분포 (시간대별 A/B) ===")
    print(pd.crosstab(events["t0_hour"], events["reached_20"]).to_string())

    # --- 기대값 ---
    print("\n=== 기대값 (비용 반영) ===")
    ev_rows = [expected_value(events, "전체"), expected_value(is_ev, "IS"), expected_value(oos_ev, "OOS")]
    ev_df = pd.DataFrame(ev_rows)
    ev_df.to_csv("results/leader_20pct_expected_value.csv", index=False, encoding="utf-8-sig")
    print(ev_df.to_string(index=False))

    # --- IS/OOS 따로 본 효과크기 (선택은 IS에서만, 재현 여부 확인용) ---
    all_cols = DESCRIPTIVE_COLUMNS + FEATURE_COLUMNS
    is_tbl = group_compare(is_ev, all_cols).assign(split="IS")
    oos_tbl = group_compare(oos_ev, all_cols).assign(split="OOS")
    pd.concat([is_tbl, oos_tbl]).to_csv("results/leader_20pct_is_oos_effects.csv",
                                         index=False, encoding="utf-8-sig")
    print("\n=== IS 효과크기 상위 8 (문턱은 여기서만 고른다) ===")
    print(is_tbl.head(8)[["feature", "n_A", "n_B", "A_median", "B_median", "cohens_d", "auc", "auc_abs", "mwu_p"]].to_string(index=False))
    print("=== 같은 피처의 OOS 재현 ===")
    top_feats = is_tbl.head(8)["feature"].tolist()
    print(oos_tbl[oos_tbl["feature"].isin(top_feats)][["feature", "n_A", "n_B", "A_median", "B_median", "cohens_d", "auc", "auc_abs", "mwu_p"]].to_string(index=False))

    # --- 교란 점검 1: 시간대 통제 (T0가 이를수록 누적대금이 적은 건 당연하다) ---
    print("\n=== 교란점검1: 09시대 T0만 (누적대금 신호가 '이른 시각' 때문인가) ===")
    morning = events[events["t0_hour"] == 9]
    print(f"n={len(morning)} (A {int(morning['reached_20'].sum())})")
    print(group_compare(morning, ["cum_value_eok", "value_rank", "vs10_value_surge"]).to_string(index=False))

    # --- 교란 점검 2: 전일 거래대금 (그냥 '원래 작은 종목'인가) ---
    codes = sorted({c for c in events["code"]})
    closes, volumes = {}, {}
    for code in codes:
        p = os.path.join(DAILY_DIR, f"{code}.csv")
        if os.path.exists(p):
            d = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()
            closes[code], volumes[code] = d["close"], d["volume"]
    events["prev_turnover_eok"] = [prev_day_turnover_eok(closes, r.code, r.date, volumes)
                                    for r in events.itertuples()]
    print("\n=== 교란점검2: 전일 거래대금(억) — '원래 작은 종목'인지 ===")
    print(group_compare(events, ["prev_turnover_eok"]).to_string(index=False))

    # --- 문턱: IS에서만 고르고 OOS에 1회 적용 (사전등록 §3) ---
    best = is_tbl.iloc[0]["feature"]
    direction = "<=" if is_tbl.iloc[0]["auc"] < 0.5 else ">="
    q = 0.25 if direction == "<=" else 0.75
    cand = {f"{best} {direction} IS-Q({q})": {best: (direction, is_ev[best].quantile(q))},
            f"{best} {direction} IS-median": {best: (direction, is_ev[best].median())}}
    print(f"\n=== 문턱 후보 (IS 선택, 피처={best}, 방향={direction}) ===")
    is_rule_rows = [evaluate_rule(is_ev, c, name) for name, c in cand.items()]
    print(pd.DataFrame(is_rule_rows).to_string(index=False))
    winner_name = max(is_rule_rows, key=lambda r: (r["net_v1_pct"] if r["n"] else -9e9))["group"]
    winner = cand[winner_name]
    print(f"IS 1등: {winner_name} -> OOS에 그대로 1회 적용")

    rule_rows = [evaluate_rule(is_ev, winner, "IS"), evaluate_rule(oos_ev, winner, "OOS"),
                 evaluate_rule(events, winner, "전체")]
    # 비용 민감도: 실측 슬리피지가 가정보다 컸고(중앙값 0.109%), 이 규칙이 고르는 쪽이
    # 하필 대금이 적은 종목이라 비용이 더 비쌀 개연성이 있다 -> 1.5배/2배로 눌러본다.
    for m in (1.5, 2.0):
        rule_rows.append(evaluate_rule(oos_ev, winner, f"OOS(비용x{m})", cost_mult=m))
    rule_df = pd.DataFrame(rule_rows)
    rule_df.to_csv("results/leader_20pct_rule.csv", index=False, encoding="utf-8-sig")
    print("\n=== 선택 규칙 성과 (기각조건 (b) 판정용) ===")
    print(rule_df.to_string(index=False))

    events.to_csv("results/leader_20pct_events.csv", index=False, encoding="utf-8-sig")
    print(f"\n전체 파이프라인 {time.time()-t0:.1f}초", flush=True)
    return {"events": events, "audit": audit, "descriptive": desc, "features": feat, "ev": ev_df,
            "is_tbl": is_tbl, "oos_tbl": oos_tbl, "rule": rule_df}


if __name__ == "__main__":
    main()
