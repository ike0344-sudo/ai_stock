"""다우이론 골짜기 탐지 — 마지막 확정 저점과 '그 이후 최고가'를 기준으로 현재 눌림을 잰다.

    python dow_structure.py [종목코드...]
    python dow_structure.py --demo

왜 이렇게 하나:
  눌림 깊이를 옛날 고점에서 재면 안 된다. 저점을 찍고 다시 오르는 중이면 기준 고점은
  '마지막 확정 저점 이후의 최고가'로 갱신돼야 한다. 고정 고점을 붙들면 -17% 눌림을
  -4% 논의에 섞게 된다(2026-08-18 고점을 쓰던 예전 버전의 실제 오류).

다우식 확정:
  고가/저가 기준으로 pct% 역행이 나와야 직전 극점이 봉우리/골짜기로 확정된다.
  확정 전까지는 '진행 중'이며 기준 고가는 계속 갱신된다. 눈금은 하나로 못 정하므로
  소·중·주추세를 함께 보고, 그 종목의 ATR에 가장 가까운 눈금을 '적정'으로 표시한다.
"""
import contextlib
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from dow_signal import load

# 판정 문구에 em dash 가 있어 cp949 콘솔·로그로는 못 쓴다(UnicodeEncodeError).
# 이 파일을 직접 돌리거나 여기서 만든 문구를 print 하는 쪽이 다 걸린다 — 출력을 고정한다.
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, ValueError):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCALES = (3, 5, 8, 12, 20)
SESSIONS = ("정규장", "통합")
CODES = {"000660": "SK하이닉스", "005930": "삼성전자"}


def load_session(code, session="정규장"):
    """정규장 = KRX 일봉. 통합 = KRX+NXT 15분봉(08:00~20:00)을 일별로 집계한 일봉.
    시간외 고·저가가 포함되면 골짜기 위치가 달라지므로 두 기준을 따로 본다."""
    if session == "정규장":
        return load(code)
    g = pd.read_csv(f"data/stocks/minute_combined/{code}_15.csv", parse_dates=["date"])
    h = g.date.dt.hour + g.date.dt.minute / 60
    g = g[(h >= 8) & (h < 20)]
    # 08:00 첫 봉에 비정상 체결이 섞인다(실측: 2026-08-06 저가 1,168,000인데 같은 봉 고가
    # 1,614,000 — 15분 안에 +38%). 얇은 호가에서 나온 데이터 잡음이라 그대로 두면 골짜기가
    # 통째로 왜곡된다. 한 봉 진폭이 15%를 넘으면 버린다.
    g = g[(g.high / g.low - 1) <= 0.15]
    d = (g.set_index("date").resample("1D")
         .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
              close=("close", "last"), volume=("volume", "sum")).dropna().reset_index())
    return d


def pivots_hl(df, pct):
    """고가/저가 기준 확정 스윙. [{i, date, kind, price}] — 미확정 극점은 넣지 않는다."""
    hi, lo, dt = df.high.values, df.low.values, df.date.values
    out, ext, ei, dirn = [], hi[0], 0, 1
    for i in range(1, len(hi)):
        if dirn > 0:
            if hi[i] > ext: ext, ei = hi[i], i
            elif (lo[i] / ext - 1) * 100 <= -pct:
                out.append(dict(i=ei, date=dt[ei], kind="H", price=ext)); ext, ei, dirn = lo[i], i, -1
        else:
            if lo[i] < ext: ext, ei = lo[i], i
            elif (hi[i] / ext - 1) * 100 >= pct:
                out.append(dict(i=ei, date=dt[ei], kind="L", price=ext)); ext, ei, dirn = hi[i], i, 1
    return out


def current_leg(df, pct):
    """마지막 확정 저점 → 그 이후 최고가(계속 갱신) → 현재 눌림."""
    piv = pivots_hl(df, pct)
    lows = [p for p in piv if p["kind"] == "L"]
    if not lows:
        return None
    tr = lows[-1]
    seg = df.iloc[tr["i"]:]
    hi_i = seg.high.idxmax()
    peak, peak_dt = df.high[hi_i], df.date[hi_i]
    cur, last_low = df.close.iloc[-1], df.low.iloc[-1]
    return dict(pct=pct, 저점=tr["price"], 저점일=pd.Timestamp(tr["date"]),
                고점=peak, 고점일=peak_dt, 상승률=(peak / tr["price"] - 1) * 100,
                종가눌림=(cur / peak - 1) * 100, 저가눌림=(last_low / peak - 1) * 100,
                미확정=bool(hi_i >= len(df) - 1 or df.low.iloc[hi_i:].min() / peak - 1 > -pct / 100),
                직전저점=lows[-2]["price"] if len(lows) > 1 else np.nan)


def retracement(low, high, cur_low):
    """다우식 되돌림 — 고정 %가 아니라 '직전 상승폭의 몇 분의 몇을 반납했나'.
    Hamilton·Rhea 기준: 1/3 미만은 소추세(노이즈), 1/3~2/3이 중간반응,
    2/3 초과면 추세 자체를 의심한다."""
    rng = high - low
    if rng <= 0:
        return None
    frac = (high - cur_low) / rng
    lv = {f: high - rng * f for f in (1/3, 1/2, 2/3)}
    grade = ("소추세(노이즈)" if frac < 1/3 else
             "중간반응(정상 조정)" if frac <= 2/3 else "2/3 초과 — 추세 의심")
    return dict(상승폭=rng, 되돌림비율=frac, 레벨=lv, 판정=grade)


def atr_pct(df, n=20):
    tr = np.maximum(df.high - df.low, np.maximum((df.high - df.close.shift()).abs(),
                                                 (df.low - df.close.shift()).abs()))
    return float((tr.rolling(n).mean() / df.close * 100).iloc[-1])


def daily_low_ladder(df, n=3):
    t = df.tail(n)
    lows = list(t.low)
    return dict(dates=list(t.date), lows=lows,
                연속상승=sum(1 for a, b in zip(lows, lows[1:]) if b > a), n=n - 1)


def pullback_volume(df, look=6):
    t = df.tail(look).reset_index(drop=True)
    p = t.high.idxmax()
    after = t.iloc[p:]
    if len(after) < 2:
        return None
    first, last = after.volume.iloc[0], after.volume.iloc[-1]
    return dict(고가일=t.date[p], 고가=t.high[p], 비율=last / first,
                판정="건전(감소)" if last < first else "주의(증가)")


def past_legs(df, pct):
    """지나간 상승 구간마다 (저점, 고점, 되돌림선, 그 구간이 유효한 창).

    현재 구간만 그리면 "지금 1/3 이 어디냐"는 보이는데 "지난번엔 1/3 에서 돌았나
    2/3 까지 갔나"는 안 보인다. 되돌림이 실제로 먹혔는지는 과거 자리를 봐야 안다.

    유효한 창은 **고점일 ~ 다음 저점일**이다. 그 뒤는 새 구간이라 옛 선을 끌고 가면
    화면이 옛 값으로 덮인다. 마지막(현재) 구간은 여기 안 넣는다 — 그건 current_leg 다.
    """
    piv = pivots_hl(df, pct)
    out = []
    for a, b in zip(piv, piv[1:]):
        if a["kind"] != "L" or b["kind"] != "H":
            continue
        nxt = next((p for p in piv if p["kind"] == "L" and p["i"] > b["i"]), None)
        if nxt is None:
            continue                       # 아직 안 끝난 구간 = 현재 구간
        out.append(dict(저점=a["price"], 저점일=pd.Timestamp(a["date"]),
                        고점=b["price"], 고점일=pd.Timestamp(b["date"]),
                        끝일=pd.Timestamp(nxt["date"]),
                        레벨=retracement(a["price"], b["price"], nxt["price"])["레벨"],
                        바닥=nxt["price"]))
    return out


def pick_leg(df, scales=SCALES, floor=10.0):
    """지금 붙어 있는 구간과 그 눈금. 작은 눈금부터 올라가며 문턱을 넘는 첫 구간을 쓴다.

    예전에는 ATR 의 1.5 배에 가까운 눈금을 고르고 거기서 키우기만 했다. ATR 이 큰
    종목은 시작이 12% 로 잡혀 최근 스윙을 통째로 건너뛴다 — SK하이닉스 8/26 기준으로
    8/25 저점에서 시작된 +11.4% 구간을 놓치고 일주일 전(8/19~8/24)을 물고 있었다.
    잔 스윙은 floor 가 걸러 준다.

    화면(dow_mobile)·알림(dow_watch)·표(report)가 **같은 눈금**을 써야 한다. 갈리면
    같은 종목을 두고 화면은 8/25, 알림은 8/19 를 말한다.
    """
    lg = best = None
    for s in sorted(scales):
        cand = current_leg(df, s)
        if cand is None:
            continue
        best, lg = s, cand
        if cand["상승률"] >= floor:
            break
    return lg, best


def report(code, name, session="정규장"):
    df = load_session(code, session)
    cur = df.close.iloc[-1]
    atr = atr_pct(df)
    best = min(SCALES, key=lambda s: abs(s - atr * 1.5))   # ATR의 1.5배에 가장 가까운 눈금
    print(f"\n{'='*86}\n{name}({code})  종가 {cur:,.0f}   ATR20 {atr:.1f}%  → 적정 눈금 {best}%\n{'='*86}")
    print(" 눈금 | 마지막 확정 저점        | 이후 최고가(기준)        | 상승률 | 현재 눌림(종가/저가)")
    legs = {}
    for pct in SCALES:
        lg = current_leg(df, pct)
        if not lg:
            continue
        legs[pct] = lg
        mark = "★" if pct == best else " "
        print(f" {mark}{pct:>3}% | {lg['저점일']:%m-%d} {lg['저점']:>10,.0f} | "
              f"{lg['고점일']:%m-%d} {lg['고점']:>10,.0f}{'*' if lg['미확정'] else ' '} | "
              f"{lg['상승률']:>+6.1f}% | {lg['종가눌림']:>+6.2f}% / {lg['저가눌림']:>+6.2f}%")
    print(" (* = 고점이 아직 미확정, 계속 갱신 중)")

    lg = legs[best]
    r = retracement(lg["저점"], lg["고점"], df.low.iloc[-1])
    print()
    print(f"[다우 되돌림]  {lg['저점일']:%m-%d} {lg['저점']:,.0f} → {lg['고점일']:%m-%d} {lg['고점']:,.0f}  상승폭 {r['상승폭']:,.0f}원")
    names = {1/3: "1/3 — 조정의 최소", 1/2: "1/2 — 절반 반납", 2/3: "2/3 — 조정의 최대"}
    for f in (1/3, 1/2, 2/3):
        pr = r["레벨"][f]
        print(f"   {names[f]:<18} {pr:>10,.0f}   고점대비 {(pr/lg['고점']-1)*100:+5.1f}%   현재가 대비 {(pr/cur-1)*100:+5.1f}%")
    print(f"   현재 되돌림 {r['되돌림비율']*100:.0f}%  →  {r['판정']}")
    print("   (참고) 고정선  " + "  ".join(f"-{lv}% {lg['고점']*(1-lv/100):,.0f}" for lv in (4, 6)))
    lvl20 = lg['저점'] * 1.2
    status = '이미 성립' if lg['상승률'] >= 20 else f"{(lvl20/cur-1)*100:+.1f}% 남음"
    print(f"   국면 20% 성립선  {lvl20:>10,.0f}  ({status})")

    d = daily_low_ladder(df)
    print(f"\n[일간 저가 사다리]")
    for dt, lv in zip(d["dates"], d["lows"]):
        print(f"   {dt:%m-%d} {lv:>10,.0f}  (고점대비 {(lv/lg['고점']-1)*100:+5.1f}%, 되돌림 {(lg['고점']-lv)/r['상승폭']*100:>3.0f}%)")
    print(f"   → {d['연속상승']}/{d['n']}회 상승 [{'계단 상승 중' if d['연속상승'] == d['n'] else '계단 흔들림'}]")
    v = pullback_volume(df)
    if v:
        print(f"\n[눌림 거래량] {v['고가일']:%m-%d} 고가 이후 {v['비율']:.2f}배 → {v['판정']}")


def demo():
    """저점을 찍고 다시 오르는 중이면 기준 고점이 '새 고점'으로 갱신돼야 한다."""
    df = pd.DataFrame({
        "date": pd.bdate_range("2026-01-01", periods=12),
        "high": [100, 120, 118, 99, 105, 112, 118, 124, 122, 121, 119, 120],
        "low":  [95,  112, 100, 90,  99, 105, 112, 118, 116, 115, 113, 116],
        "close": [98, 118, 102, 95, 104, 110, 117, 123, 120, 118, 116, 119],
        "volume": [10] * 12})
    lg = current_leg(df, 8)
    assert lg["저점"] == 90, lg          # 확정 저점
    assert lg["고점"] == 124, lg         # 옛 고점 120이 아니라 저점 이후 새 고점
    assert lg["종가눌림"] < 0
    r = retracement(90, 124, 116)                 # 상승폭 34, 8 반납 → 23.5% (1/3 미만)
    assert abs(r["되돌림비율"] - 8 / 34) < 1e-9, r
    assert r["판정"].startswith("소추세"), r
    assert abs(r["레벨"][1 / 3] - (124 - 34 / 3)) < 1e-9
    assert "의심" in retracement(90, 124, 100)["판정"]
    print("demo ok:", {k: lg[k] for k in ("저점", "고점", "상승률")})


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        only = [a for a in sys.argv[1:] if a in SESSIONS]
        for c in ([a for a in sys.argv[1:] if a.isdigit()] or list(CODES)):
            for s in (only or SESSIONS):
                try:
                    report(c, CODES.get(c, c), s)
                except FileNotFoundError:
                    print()
                    print(f"[{CODES.get(c, c)} {s}] 데이터 없음 — fetch_combined_15min.py 실행 필요")
