"""다우이론 매매 도우미 — 되돌림 기준 상태표, 상태가 바뀌면 텔레그램.

    python dow_watch.py              # 현재 상태
    python dow_watch.py --notify     # 등급이 바뀌면 텔레그램 발송
    python dow_watch.py --refresh    # 키움 일봉 갱신 후 판정
    python dow_watch.py --demo       # 자체 점검

판정 기준은 dow_structure와 같다 — 고정 %가 아니라 직전 상승폭의 1/3·1/2·2/3 되돌림.
"""
import contextlib, json, os, sys, pandas as pd
from dotenv import load_dotenv
from dow_signal import load
from dow_structure import current_leg, pick_leg, retracement, SCALES, CODES

STATE_PATH = "state/dow_watch.json"

# 판정 문구에 em dash 가 들어간다("2/3 초과 — 추세 의심"). cp949 콘솔·로그로 내보내면
# UnicodeEncodeError 로 죽는데, 그 문구는 **경고가 필요한 상태에서만** 나온다.
# 매일 도는 dow_watch_daily.ps1 이 로그로 파이프하므로 정작 알려야 할 날 텔레그램이
# 안 나갔다. 출력은 UTF-8 로 고정한다.
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, ValueError):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def snapshot(code):
    df = load(code)
    cur = df.close.iloc[-1]
    # 화면(dow_mobile)과 **같은 눈금**을 쓴다 — 갈리면 알림과 차트가 다른 구간을 말한다.
    _lg, best = pick_leg(df)
    rows = []
    for pct in SCALES:
        lg = current_leg(df, pct)
        if not lg:
            continue
        r = retracement(lg["저점"], lg["고점"], df.low.iloc[-1])
        rows.append({"눈금": f"{'★' if pct == best else ''}{pct}%", "저점": lg["저점"],
                     "고점": lg["고점"], "상승률": lg["상승률"],
                     "되돌림%": r["되돌림비율"] * 100 if r else float("nan"),
                     "판정": r["판정"] if r else "-",
                     "1/3": r["레벨"][1/3] if r else float("nan"),
                     "2/3": r["레벨"][2/3] if r else float("nan")})
    lg = current_leg(df, best)
    r = retracement(lg["저점"], lg["고점"], df.low.iloc[-1])
    return df, cur, pd.DataFrame(rows), lg, r, best


def main():
    if "--refresh" in sys.argv:
        os.system(f"{sys.executable} short_check.py " + " ".join(CODES))
    prev = json.load(open(STATE_PATH, encoding="utf-8")) if os.path.exists(STATE_PATH) else {}
    now, msgs = {}, []
    for code, name in CODES.items():
        df, cur, t, lg, r, best = snapshot(code)
        print(f"\n=== {name}({code})  {df.date.iloc[-1]:%Y-%m-%d} 종가 {cur:,.0f}  (적정눈금 {best}%) ===")
        print(t.to_string(index=False, formatters={
            "저점": "{:,.0f}".format, "고점": "{:,.0f}".format, "1/3": "{:,.0f}".format,
            "2/3": "{:,.0f}".format, "상승률": "{:+.1f}".format, "되돌림%": "{:.0f}".format}))
        print(f"기준 {lg['저점']:,.0f}({lg['저점일']:%m-%d}) → {lg['고점']:,.0f}({lg['고점일']:%m-%d}) "
              f"| 되돌림 {r['되돌림비율']*100:.0f}% → {r['판정']}")
        print(f"  1/3 {r['레벨'][1/3]:,.0f} ({(r['레벨'][1/3]/cur-1)*100:+.1f}%) | "
              f"1/2 {r['레벨'][1/2]:,.0f} ({(r['레벨'][1/2]/cur-1)*100:+.1f}%) | "
              f"2/3 {r['레벨'][2/3]:,.0f} ({(r['레벨'][2/3]/cur-1)*100:+.1f}%) | "
              f"고점돌파 {lg['고점']:,.0f} ({(lg['고점']/cur-1)*100:+.1f}%)")
        key = r["판정"]
        now[code] = key
        if prev.get(code) and prev[code] != key:
            msgs.append(f"[다우] {name} {prev[code]} → {key}\n종가 {cur:,.0f} | 되돌림 {r['되돌림비율']*100:.0f}%\n"
                        f"1/3 {r['레벨'][1/3]:,.0f} · 2/3 {r['레벨'][2/3]:,.0f} · 고점 {lg['고점']:,.0f}")
    os.makedirs("state", exist_ok=True)
    json.dump(now, open(STATE_PATH, "w", encoding="utf-8"), ensure_ascii=False)
    if msgs:
        print("\n" + "\n\n".join(msgs))
        if "--notify" in sys.argv:
            load_dotenv(".env")
            from backtesting.notifier import send_telegram, WARNING
            ok = send_telegram("\n\n".join(msgs), os.environ.get("TELEGRAM_BOT_TOKEN", ""),
                               os.environ.get("TELEGRAM_CHAT_ID", ""), level=WARNING)
            print("텔레그램", "발송" if ok else "실패")
    elif prev:
        print("\n등급 변화 없음")


def demo():
    """등급이 바뀌는 지점에서만 알림 키가 달라져야 한다."""
    a = retracement(100, 130, 125)      # 16.7% → 소추세
    b = retracement(100, 130, 118)      # 40%   → 중간반응
    c = retracement(100, 130, 105)      # 83%   → 의심
    assert a["판정"] != b["판정"] != c["판정"], (a["판정"], b["판정"], c["판정"])
    assert a["판정"].startswith("소추세") and "의심" in c["판정"]
    print("demo ok:", a["판정"], "/", b["판정"], "/", c["판정"])


if __name__ == "__main__":
    demo() if "--demo" in sys.argv else main()
