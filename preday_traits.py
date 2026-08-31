"""급등 "전날까지"의 일봉 특징으로 클린 20 케이스의 공통점 찾기.

기존 분석(clean20_*)은 전부 당일 09:00~10:00 장중 지표였다. 여기선 D-1까지의
일봉만 쓴다 — 전날 밤에 관심종목을 추릴 수 있는지가 목적이다.

모집단: 대금 top10 종목-일자. 타깃: 경로 최대낙폭 <=5%로 +20% 도달(갭 직행 제외).
모든 피처는 daily.shift(1) 이후 값만 참조해 당일 정보가 새지 않게 한다.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import auc, load, wilson

DAILY_DIR = "data/stocks/daily"
MAX_DD = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--dd=")), 5))
OUT = "results/preday_features.csv"

FEATURES = [
    ("ret_1d", "전일 등락률"),
    ("ret_5d", "5일 수익률"),
    ("ret_20d", "20일 수익률"),
    ("ret_60d", "60일 수익률"),
    ("dev_ma5", "MA5 이격도"),
    ("dev_ma20", "MA20 이격도"),
    ("dev_ma60", "MA60 이격도"),
    ("pos_20d", "20일 레인지 내 위치"),
    ("vs_high20", "20일 고가 대비"),
    ("vs_high60", "60일 고가 대비"),
    ("vs_high240", "52주 고가 대비"),
    ("days_since_high20", "20일 고가 이후 경과일"),
    ("val_5_20", "5일대금/20일대금"),
    ("val_20_60", "20일대금/60일대금"),
    ("range_contract", "변동성 수축(10일/60일)"),
    ("atr20_pct", "20일 ATR%"),
    ("up_days_5", "최근 5일 양봉 수"),
]


def daily_features(code: str) -> pd.DataFrame | None:
    path = os.path.join(DAILY_DIR, f"{code}.csv")
    if not os.path.exists(path):
        return None
    d = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
    if len(d) < 70:
        return None
    c, h, l = d["close"], d["high"], d["low"]
    value = c * d["volume"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    rng = (h - l) / c * 100

    f = pd.DataFrame(index=d.index)
    for n in (1, 5, 20, 60):
        f[f"ret_{n}d"] = (c / c.shift(n) - 1) * 100
    for n in (5, 20, 60):
        f[f"dev_ma{n}"] = (c / c.rolling(n).mean() - 1) * 100
    lo20, hi20 = l.rolling(20).min(), h.rolling(20).max()
    f["pos_20d"] = (c - lo20) / (hi20 - lo20)
    f["vs_high20"] = (c / hi20 - 1) * 100
    f["vs_high60"] = (c / h.rolling(60).max() - 1) * 100
    f["vs_high240"] = (c / h.rolling(240, min_periods=60).max() - 1) * 100
    # 20일 고가가 며칠 전인지 — 0이면 어제가 20일 신고가
    f["days_since_high20"] = h.rolling(20).apply(lambda x: len(x) - 1 - int(np.argmax(x)), raw=True)
    f["val_5_20"] = value.rolling(5).mean() / value.rolling(20).mean()
    f["val_20_60"] = value.rolling(20).mean() / value.rolling(60).mean()
    f["range_contract"] = rng.rolling(10).mean() / rng.rolling(60).mean()
    f["atr20_pct"] = tr.rolling(20).mean() / c * 100
    f["up_days_5"] = (c > c.shift(1)).rolling(5).sum()
    return f.shift(1)  # D-1까지의 정보만 쓴다


def build(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    codes = sorted(df["stock_code"].unique())
    for i, code in enumerate(codes, 1):
        print(f"\r[{i}/{len(codes)}] {code}", end="", file=sys.stderr)
        f = daily_features(code)
        if f is None:
            continue
        g = df[df["stock_code"] == code]
        hit = g["date"][g["date"].isin(f.index)]
        if hit.empty:
            continue
        sub = f.loc[hit].copy()
        sub.insert(0, "stock_code", code)
        sub.insert(0, "date", hit.values)
        out.append(sub)
    print(file=sys.stderr)
    return pd.concat(out, ignore_index=True)


def compare(a: pd.DataFrame, b: pd.DataFrame, an: str, bn: str) -> None:
    rows = sorted(FEATURES, key=lambda x: -abs(auc(a[x[0]], b[x[0]]) - 0.5))
    print(f"{'피처':>22}{'AUC':>7}{an+' 25%':>10}{an+' 중앙':>10}{an+' 75%':>10}  |{bn+' 중앙':>10}")
    for col, name in rows:
        s, c = a[col].dropna(), b[col].dropna()
        if s.empty or c.empty:
            continue
        au = auc(s, c)
        star = " ***" if abs(au - 0.5) >= 0.10 else (" *" if abs(au - 0.5) >= 0.05 else "")
        print(f"{name:>22}{au:>7.3f}{s.quantile(.25):>10.2f}{s.median():>10.2f}"
              f"{s.quantile(.75):>10.2f}  |{c.median():>10.2f}{star}")


def rate_table(df: pd.DataFrame, col: str, name: str, target: str) -> None:
    q = pd.qcut(df[col], 5, duplicates="drop")
    base = df[target].mean() * 100
    print(f"\n{name}  (기준선 {base:.1f}%)")
    for b, g in df.groupby(q, observed=True):
        k = int(g[target].sum())
        lo, hi = wilson(k, len(g))
        bar = "█" * round(k / len(g) * 100 / base * 4)
        print(f"{f'{b.left:g} ~ {b.right:g}':>22}{len(g):>7}{k:>6}{k/len(g)*100:>7.1f}%"
              f"{f'[{lo:.0f}-{hi:.0f}]':>13}  {bar}")


def main() -> None:
    base = load()
    base["target"] = (base["reached"] & (base["max_dd_pct"] <= MAX_DD)
                      & (base["minutes_to_20"] > 3))
    if "--reuse" in sys.argv and os.path.exists(OUT):
        pre = pd.read_csv(OUT, parse_dates=["date"], dtype={"stock_code": str})
    else:
        pre = build(base)
        pre.to_csv(OUT, index=False, encoding="utf-8-sig")
    df = base.merge(pre, on=["date", "stock_code"], how="inner", suffixes=("", "_pre"))

    tgt = df[df["target"]]
    dirty = df[df["reached"] & ~df["target"]]
    miss = df[~df["reached"]]
    print("=" * 100)
    print(f"급등 전날(D-1)까지의 일봉 공통점 — 낙폭 <= {MAX_DD:g}%로 +20% 도달한 케이스")
    print("=" * 100)
    print(f"대상 {len(tgt)}건 / 지저분·갭직행 도달 {len(dirty)}건 / 미도달 {len(miss):,}건"
          f"  (일봉 60일 이상 확보된 {len(df):,}건 기준)")

    print("\n" + "-" * 100)
    print("[1] vs 미도달 — 그날 +20%를 갈 종목은 전날부터 달랐나")
    print("-" * 100)
    compare(tgt, miss, "대상", "미도달")

    print("\n" + "-" * 100)
    print("[2] vs 지저분 도달 — 같은 +20%인데 안 흔들린 종목은 전날부터 달랐나")
    print("-" * 100)
    compare(tgt, dirty, "대상", "지저분")

    print("\n" + "-" * 100)
    print("[3] 상위 판별 피처의 5분위별 대상 발생률 (막대 = 기준선 대비 배수)")
    print("-" * 100)
    top = sorted(FEATURES, key=lambda x: -abs(auc(tgt[x[0]], miss[x[0]]) - 0.5))[:5]
    for col, name in top:
        rate_table(df, col, name, "target")

    print("\n" + "-" * 100)
    print("[4] 전날 밤 스크리닝 조건 (D-1 종가 기준)")
    print("-" * 100)
    rules = {
        "20일 고가 -10% 이내": df["vs_high20"] >= -10,
        "MA20 위": df["dev_ma20"] >= 0,
        "MA5 이격 +8% 이내": df["dev_ma5"] <= 8,
        "5일대금/20일대금 >= 1.2": df["val_5_20"] >= 1.2,
        "20일대금/60일대금 >= 1.0": df["val_20_60"] >= 1.0,
        "20일 레인지 상단 60%+": df["pos_20d"] >= 0.6,
    }
    b = df["target"].mean()
    print(f"{'조건':>28}{'n':>7}{'대상':>7}{'비율':>8}{'배수':>8}{'95% CI':>15}")
    for label, m in rules.items():
        k, tot = int(df.loc[m, "target"].sum()), int(m.sum())
        lo, hi = wilson(k, tot)
        print(f"{label:>28}{tot:>7}{k:>7}{k/tot*100:>7.1f}%{k/tot/b:>7.2f}x{f'[{lo:.1f}-{hi:.1f}]':>15}")
    print()
    combo = pd.Series(True, index=df.index)
    for label, m in rules.items():
        combo &= m
        k, tot = int(df.loc[combo, "target"].sum()), int(combo.sum())
        if tot < 20:
            print(f"{('누적 + ' + label):>28}{tot:>7}   (표본 부족, 중단)")
            break
        lo, hi = wilson(k, tot)
        print(f"{('누적 + ' + label):>28}{tot:>7}{k:>7}{k/tot*100:>7.1f}%{k/tot/b:>7.2f}x{f'[{lo:.1f}-{hi:.1f}]':>15}")


def demo() -> None:
    """일봉 피처 계산·룩어헤드 차단 자체검증."""
    idx = pd.date_range("2026-01-01", periods=80, freq="D")
    c = pd.Series(np.linspace(100, 180, 80), index=idx)
    d = pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                      "volume": np.full(80, 1000.0)}, index=idx)
    os.makedirs("results", exist_ok=True)
    tmp = os.path.join(DAILY_DIR, "_demo.csv")
    d.to_csv(tmp)
    try:
        f = daily_features("_demo")
        assert f is not None
        last = f.iloc[-1]
        # shift(1) 이므로 마지막 행은 D-1까지의 값 — 직전일 종가 기준이어야 한다
        prev = d["close"].iloc[-2]
        assert abs(last["dev_ma5"] - (prev / d["close"].iloc[-6:-1].mean() - 1) * 100) < 1e-9
        assert last["ret_1d"] > 0 and last["up_days_5"] == 5  # 단조 상승
        assert abs(last["days_since_high20"] - 0) < 1e-9      # 어제가 20일 신고가
        assert last["vs_high20"] < 0 and last["pos_20d"] > 0.9
    finally:
        os.remove(tmp)
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()
    main()
