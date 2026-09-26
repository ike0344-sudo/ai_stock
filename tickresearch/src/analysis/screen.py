"""Phase 4 — 지표 80개를 라벨에 걸어 사전등록 기각조건을 판정한다.

사전등록: docs/TICKRESEARCH_LABEL_5MIN_2PCT_PREREGISTRATION.md

## 하는 일

1. Feature(80) + Label 조인 → IS/OOS1/OOS2 분할
2. **IS에서만** 지표별 AUC(익절 여부) / 평균 순수익을 재고 상위를 고른다
3. 고른 것을 **OOS에 1회 적용**한다 (OOS 보고 다시 고르지 않는다)
4. 대조군(상시진입) 대비 비교 + 부트스트랩 CI + 온셋격리 민감도

## 다중비교 방어

지표가 80개다. 80개를 훑으면 **우연히 좋아 보이는 게 반드시 나온다**.
그래서 (a) IS에서만 고르고 (b) 이미 기각된 15개에는 표시를 붙여 더 강한 증거를 요구하고
(c) 대조군을 항상 같이 낸다.
"""
from __future__ import annotations

import numpy as np
import polars as pl

IS_RANGE = ("2026-08-04", "2026-08-20")
OOS1_RANGE = ("2026-08-21", "2026-08-28")
OOS2_RANGE = ("2026-09-01", "2026-09-18")
MIN_N = 30                      # 사전등록 기각조건 (g)


def load(feat_root: str, label_root: str, stop_tag: str = "01") -> pl.LazyFrame:
    """Feature + Label 조인. 파일 경로에서 symbol/date를 뽑아 키로 쓴다."""
    def _scan(root: str) -> pl.LazyFrame:
        return pl.scan_parquet(f"{root}/**/*.parquet", include_file_paths="__p").with_columns(
            pl.col("__p").str.extract(r"symbol=([^/\\]+)").alias("symbol"),
            pl.col("__p").str.extract(r"(\d{4}-\d{2}-\d{2})").alias("date"),
        ).drop("__p")

    lab_cols = ["symbol", "date", "t_sec", f"barrier__s{stop_tag}",
                f"net_return__s{stop_tag}", "prior_return__300s", "entry_price"]
    return _scan(feat_root).join(
        _scan(label_root).select(lab_cols), on=["symbol", "date", "t_sec"], how="inner")


def split(df: pl.DataFrame) -> dict[str, pl.DataFrame]:
    def seg(r):
        return df.filter((pl.col("date") >= r[0]) & (pl.col("date") <= r[1]))
    return {"IS": seg(IS_RANGE), "OOS1": seg(OOS1_RANGE), "OOS2": seg(OOS2_RANGE)}


def auc(score: np.ndarray, y: np.ndarray) -> float:
    """순위 기반 AUC. NaN은 제외한다."""
    ok = np.isfinite(score) & np.isfinite(y)
    s, t = score[ok], y[ok]
    n1 = t.sum()
    if n1 == 0 or n1 == len(t):
        return np.nan
    r = np.empty(len(s))
    order = np.argsort(s, kind="stable")
    r[order] = np.arange(1, len(s) + 1)
    return (r[t == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * (len(t) - n1))


def day_clustered_se(values: np.ndarray, days: np.ndarray) -> tuple[float, float]:
    """날짜를 하나의 관측으로 보는 평균과 표준오차.

    같은 날 같은 종목의 진입들은 서로 독립이 아니다 — 행 단위 SE를 쓰면
    표본이 900만이라 **무엇이든 유의하게 나온다**. 그래서 날짜로 묶는다.
    """
    ok = np.isfinite(values)
    v, d = values[ok], days[ok]
    if len(v) == 0:
        return np.nan, np.nan
    uniq = np.unique(d)
    per_day = np.array([v[d == u].mean() for u in uniq])
    if len(per_day) < 2:
        return float(per_day.mean()), np.nan
    return float(per_day.mean()), float(per_day.std(ddof=1) / np.sqrt(len(per_day)))


def bootstrap_ci(values: np.ndarray, days: np.ndarray, n: int = 2000,
                 seed: int = 0) -> tuple[float, float]:
    """날짜 단위 부트스트랩 95% CI (사전등록 기각조건 (c))."""
    ok = np.isfinite(values)
    v, d = values[ok], days[ok]
    uniq = np.unique(d)
    if len(uniq) < 2:
        return np.nan, np.nan
    per_day = np.array([v[d == u].mean() for u in uniq])
    rng = np.random.default_rng(seed)
    draws = per_day[rng.integers(0, len(per_day), size=(n, len(per_day)))].mean(axis=1)
    return float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def evaluate(df: pl.DataFrame, mask: np.ndarray, ret_col: str,
             barrier_col: str) -> dict:
    """선택된 표본의 성적. 대조군과 같은 형식으로 낸다."""
    sub = df.filter(mask)
    if sub.height == 0:
        return {"n": 0}
    r = sub[ret_col].to_numpy()
    days = sub["date"].to_numpy()
    b = sub[barrier_col].to_numpy()
    mean, se = day_clustered_se(r, days)
    lo, hi = bootstrap_ci(r, days)
    return {"n": sub.height, "days": len(np.unique(days)),
            "net_mean": mean, "net_se": se, "ci_lo": lo, "ci_hi": hi,
            "tp_rate": float((b == 1).mean()), "sl_rate": float((b == -1).mean()),
            "symbols": sub["symbol"].n_unique()}
