"""다우이론 기계적 매매 규칙 — 진입/청산 신호와 백테스트.

규칙 (종가 기준, 미래 정보 사용 안 함):
  스윙 확정 : 직전 극점에서 pct% 역행하면 그 극점을 고점(H)/저점(L)으로 확정
  진입      : 종가가 '확정된 직전 고점'을 넘고, 동시에 최근 두 저점이 HL(저점 상승)
  청산      : 종가가 '확정된 직전 저점'을 이탈
  (옵션) 거래량 필터 : 진입일 거래량 > 20일 평균
  (옵션) 상호확인    : 짝 종목도 같은 시점에 추세 상승 상태

    python dow_signal.py                # 000660, 005930 백테스트
    python dow_signal.py --demo         # 자체 점검
"""
import sys, glob, pandas as pd, numpy as np

def load(code):
    fs = [f".cache/backtest/{code}_day.csv", f"data/stocks/daily/{code}.csv"]
    df = pd.concat([pd.read_csv(f, parse_dates=["date"]) for f in fs if glob.glob(f)])
    return df.drop_duplicates("date").sort_values("date").reset_index(drop=True)

def dow_state(df, pct=8.0, vol_filter=False):
    """일자별 포지션(0/1)과 신호 목록. 스윙을 스트리밍으로 확정해 룩어헤드를 없앤다."""
    c = df.close.values
    vol = df.volume.values
    vma = pd.Series(vol).rolling(20).mean().values
    highs, lows = [], []                      # 확정된 스윙 값
    ext, dirn = c[0], 1                       # 진행 중인 극점
    pos = 0
    state, sigs = np.zeros(len(c), dtype=int), []
    for i in range(1, len(c)):
        if dirn > 0:
            if c[i] > ext: ext = c[i]
            elif (c[i] / ext - 1) * 100 <= -pct:
                highs.append(ext); ext, dirn = c[i], -1
        else:
            if c[i] < ext: ext = c[i]
            elif (c[i] / ext - 1) * 100 >= pct:
                lows.append(ext); ext, dirn = c[i], 1

        if pos == 0:
            if highs and len(lows) >= 2 and c[i] > highs[-1] and lows[-1] > lows[-2]:
                if not vol_filter or (not np.isnan(vma[i]) and vol[i] > vma[i]):
                    pos = 1; sigs.append((df.date[i], "BUY", c[i]))
        elif lows and c[i] < lows[-1]:
            pos = 0; sigs.append((df.date[i], "SELL", c[i]))
        state[i] = pos
    return state, sigs

def backtest(df, state, cost=0.003):
    """다음날 시가 진입 없이 종가→종가 단순 보유 수익. 왕복 거래비용 cost."""
    ret = df.close.pct_change().fillna(0).values
    pos = np.roll(state, 1); pos[0] = 0                 # 신호 다음날부터 보유
    trades = int(np.sum(np.abs(np.diff(np.r_[0, pos]))))
    eq = np.cumprod(1 + ret * pos) * (1 - cost) ** trades
    bh = np.cumprod(1 + ret)
    dd = eq / np.maximum.accumulate(eq) - 1
    bdd = bh / np.maximum.accumulate(bh) - 1
    return dict(전략=eq[-1] - 1, 보유=bh[-1] - 1, 최대낙폭=dd.min(), 보유낙폭=bdd.min(),
                거래횟수=trades // 2, 시장노출=pos.mean())

def demo():
    """상승 후 하락하는 인공 시계열에서 진입·청산이 한 번씩 나오는지."""
    # 저점 두 개(115 → 132)가 HL을 이루고, 그 뒤 직전 고점(145)을 돌파해야 진입이 난다
    up = (list(np.linspace(100, 130, 25)) + list(np.linspace(130, 115, 8)) +
          list(np.linspace(115, 145, 25)) + list(np.linspace(145, 132, 8)) +
          list(np.linspace(132, 180, 25)) + list(np.linspace(180, 100, 40)))
    df = pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=len(up)),
                       "close": up, "volume": [1e6] * len(up)})
    state, sigs = dow_state(df, pct=8)
    kinds = [s[1] for s in sigs]
    assert "BUY" in kinds and "SELL" in kinds, kinds
    assert kinds.index("BUY") < kinds.index("SELL"), kinds
    assert state[-1] == 0, "하락 종료 후에는 포지션이 없어야 한다"
    print("demo ok:", [(f"{d:%Y-%m-%d}", k, round(p, 1)) for d, k, p in sigs])

def main():
    for code, name in [("000660", "SK하이닉스"), ("005930", "삼성전자")]:
        df = load(code)
        print(f"\n===== {name}({code}) {df.date.iloc[0]:%Y-%m}~{df.date.iloc[-1]:%Y-%m} =====")
        rows = []
        for pct in (5, 8, 12, 15):
            for vf in (False, True):
                state, sigs = dow_state(df, pct, vf)
                r = backtest(df, state)
                rows.append({"임계%": pct, "거래량필터": "O" if vf else "X", **r})
        t = pd.DataFrame(rows)
        print(t.to_string(index=False, formatters={
            "전략": "{:+.0%}".format, "보유": "{:+.0%}".format, "최대낙폭": "{:.0%}".format,
            "보유낙폭": "{:.0%}".format, "시장노출": "{:.0%}".format}))
        state, sigs = dow_state(df, 8)
        print("최근 신호:", " | ".join(f"{d:%Y-%m-%d} {k} {p:,.0f}" for d, k, p in sigs[-6:]))
        print(f"현재 상태: {'보유(추세 상승)' if state[-1] else '현금(추세 하락/미확인)'}")

if __name__ == "__main__":
    demo() if "--demo" in sys.argv else main()
