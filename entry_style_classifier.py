"""오늘은 돌파의 날인가 눌림의 날인가 — 10:00에 진입 방식을 정하는 분류기.

    python entry_style_classifier.py            # 검증 (인샘플 + 워크포워드)
    python entry_style_classifier.py --today    # 지금 시세로 오늘 판정

규칙은 코스피 15분봉 두 축으로 정한다(둘 다 10:00 이전에 닫힌 봉만 사용).
  정배열 = 60봉 이평 > 120봉 이평 / 60선 위 = 지수 > 60봉 이평

entry_style_regime.py에서 국면별 최적 방식이 갈렸다. 다만 그건 인샘플 선택이라
여기서 분기별 앵커드 워크포워드로 다시 확인한다 - 과거 구간에서 방식을 '고르고'
다음 분기에서만 성과를 잰다.
"""
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import wilson
from entry_style_regime import PLANS, TRAILS, trades

# 국면 -> (방식, 트레일). 워크포워드에서 살아남은 것만 남겼다.
# 4칸을 전부 국면별 최적으로 배정하면 인샘플 169%로 좋아 보이지만 OOS에서 고정
# 전략에 진다(0.34% vs 0.48%) - 분기마다 선택이 뒤집히는 과최적화였다. 유일하게
# 3개 분기 연속 재현된 "역배열 + 60선 아래 -> 돌파" 한 칸만 바꾼다(126% -> 150%).
RULE = {
    ("정배열", "위"):   ("전량 시장가", 5.0, "평소대로 — 기다리면 안 온다"),
    ("정배열", "아래"): ("전량 시장가", 5.0, "평소대로"),
    ("역배열", "위"):   ("전량 시장가", 5.0, "평소대로 — 반등 초기"),
    ("역배열", "아래"): ("돌파 1회만", 5.0, "둘 다 약세 — 2% 눌린 뒤 고점 회복만 매수. 미체결이 정상"),
}
MIN_TRAIN = 12          # 이보다 적은 칸은 학습 구간에서 못 고른다


def classify(align_up: bool, above60: bool) -> dict:
    trend = "정배열" if align_up else "역배열"
    mood = "위" if above60 else "아래"
    style, trail, why = RULE[(trend, mood)]
    return {"trend": trend, "mood": mood, "style": style, "trail": trail, "reason": why}


def cols(t: pd.DataFrame) -> pd.DataFrame:
    t = t.copy()
    t["mood"] = t["below60"].map({True: "아래", False: "위"})
    return t.dropna(subset=["trend"])


def apply_rule(t: pd.DataFrame, rule: dict) -> pd.Series:
    """행마다 그 국면에 배정된 (방식, 트레일)의 수익률을 뽑아온다."""
    out = []
    for _, r in t.iterrows():
        style, trail = rule.get((r["trend"], r["mood"]), ("전량 시장가", 5.0))[:2]
        out.append(r[f"{style}|{trail:g}"])
    return pd.Series(out, index=t.index)


def show(label: str, r: pd.Series) -> None:
    lo, hi = wilson(int((r > 0).sum()), len(r))
    print(f"{label:>26}{len(r):>6}{r.mean():>8.2f}%{(r > 0).mean()*100:>7.0f}%"
          f"{r.sum():>8.0f}%{f'[{lo:.0f}-{hi:.0f}]':>11}")


def best_rule(train: pd.DataFrame) -> dict:
    """학습 구간에서 국면별 누적 최대 조합. 표본이 얇은 칸은 전량 시장가로 남긴다."""
    rule = {}
    for trend in ("정배열", "역배열"):
        for mood in ("위", "아래"):
            g = train[(train["trend"] == trend) & (train["mood"] == mood)]
            if len(g) < MIN_TRAIN:
                rule[(trend, mood)] = ("전량 시장가", 5.0)
                continue
            best = max(((g[f"{n}|{tr:g}"].sum(), n, tr) for n in PLANS for tr in TRAILS))
            rule[(trend, mood)] = (best[1], best[2])
    return rule


def main() -> None:
    t = cols(trades())
    print("=" * 76)
    print(f"진입 방식 분류기 검증  |  후보 {len(t)}건")
    print("=" * 76)
    print(f"\n{'':>26}{'건수':>6}{'건당':>8}{'승률':>7}{'누적':>8}{'승률CI':>11}")
    show("고정: 전량 시장가 -5%", t["전량 시장가|5"])
    show("고정: 전량 시장가 -4%", t["전량 시장가|4"])
    show("고정: 눌림 -2% -5%", t["눌림 -2% 1회|5"])
    show("고정: 돌파 1회만 -5%", t["돌파 1회만|5"])
    show("분류기(인샘플 규칙)", apply_rule(t, {k: v[:2] for k, v in RULE.items()}))

    print("\n" + "-" * 76)
    print("분기별 앵커드 워크포워드 — 과거에서 고르고 다음 분기에서만 잰다")
    print("-" * 76)
    t = t.sort_values("date")
    q = t["date"].dt.to_period("Q")
    quarters = sorted(q.unique())
    sel, fix = [], []
    print(f"{'검증분기':>9}{'학습':>6}{'검증':>6}{'선택된 규칙(정위/정아래/역위/역아래)':>40}{'건당':>8}{'고정-5%':>9}")
    for i in range(1, len(quarters)):
        train, test = t[q < quarters[i]], t[q == quarters[i]]
        if len(train) < 40 or len(test) == 0:
            continue
        rule = best_rule(train)
        r = apply_rule(test, rule)
        sel.append(r)
        fix.append(test["전량 시장가|5"])
        tag = " / ".join(rule[(a, b)][0][:4] for a in ("정배열", "역배열") for b in ("위", "아래"))
        print(f"{str(quarters[i]):>9}{len(train):>6}{len(test):>6}{tag:>40}"
              f"{r.mean():>7.2f}%{test['전량 시장가|5'].mean():>8.2f}%")
    if sel:
        print()
        show("OOS 합산: 분류기", pd.concat(sel))
        show("OOS 합산: 고정 -5%", pd.concat(fix))


def today() -> None:
    import os
    from dotenv import load_dotenv
    from backtesting.regime_signal import get_regime_signal
    load_dotenv()
    s = get_regime_signal(os.environ["KIWOOM_APPKEY"], os.environ["KIWOOM_SECRETKEY"],
                          os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true")
    if not s.get("ok"):
        print("국면 판정 실패:", s.get("error"))
        return
    c = classify(s["trend"] == "정배열", s["mood"] == "60선 위")
    print(f"기준 {s['as_of']} · 코스피 {s['index']} · 60선 {s['ma60']} · 120선 {s['ma120']}")
    print(f"국면  : {c['trend']} · 60선 {c['mood']}")
    print(f"진입  : {c['style']}   트레일 -{c['trail']:g}%")
    print(f"이유  : {c['reason']}")


def demo() -> None:
    """딱 한 칸(역배열+60선 아래)만 갈라져야 한다 - 더 갈리면 과최적화 버전으로 되돌아간 것."""
    got = {(a, b): classify(a, b)["style"] for a in (True, False) for b in (True, False)}
    assert got[(False, False)] == "돌파 1회만", got      # 역배열 + 60선 아래
    assert len({v for k, v in got.items() if k != (False, False)}) == 1, got
    assert got[(True, True)] == "전량 시장가", got
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    elif "--today" in sys.argv:
        today()
    else:
        main()
