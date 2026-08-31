"""다우 진입 차트 (인터랙티브) — 어디서 사고 어디서 파는지를 봉차트 위에 못 박는다.

    python dow_interactive.py          # static/dashboard/dow_interactive.html 생성
    python dow_interactive.py --demo

핵심: 다우는 '봉우리 돌파'에서 산다. 그래서 아직 안 넘은 가장 가까운 확정 봉우리를
      '진입선'으로 굵게 그리고, 과거 실제 돌파 시점도 ▲로 찍는다.
"""
import pathlib, sys, numpy as np, pandas as pd
import plotly.graph_objects as go
sys.path.insert(0, ".")
from dow_signal import load, dow_state
from dow_ladder_chart import swings
from dow_structure import past_legs, pick_leg, retracement

# view: (표시명, 스윙 눈금, 표시 봉 수, 세션(시작,끝), MA기간)
TF = {
    "D":   ("일봉",            dict(gates=(5, 8, 12), exit_pct=20, base_pct=8),    90, None,          ()),
    "15R": ("15분봉 정규장",    dict(gates=(1.2, 2, 3.2), exit_pct=6, base_pct=2), 260, (9, 15.5),     (60, 120)),
    "15A": ("15분봉 통합",      dict(gates=(1.2, 2, 3.2), exit_pct=6, base_pct=2), 320, (8, 20),       (60, 120)),
}
CODES = [("000660", "SK하이닉스"), ("005930", "삼성전자")]
PAST_MAX = 6          # 화면에 겹쳐 그릴 과거 구간 수

def bars(code, view):
    """일봉 / 정규장 15분봉(KRX 전용 캐시) / 통합 15분봉(KRX+NXT)."""
    if view == "D":
        return load(code)
    if view == "15R":                                   # 정규장은 기존 KRX 전용 1분봉을 리샘플
        m = pd.read_csv(f"data/stocks/minute/{code}.csv", parse_dates=["date"])
        g = (m.set_index("date").resample("15min")
             .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                  close=("close", "last"), volume=("volume", "sum")).dropna().reset_index())
        h = g.date.dt.hour + g.date.dt.minute / 60
        return g[(h >= 9) & (h < 15.5)].reset_index(drop=True)
    g = pd.read_csv(f"data/stocks/minute_combined/{code}_15.csv", parse_dates=["date"])
    h = g.date.dt.hour + g.date.dt.minute / 60
    g = g[(h >= 8) & (h < 20)]
    g = g[(g.high / g.low - 1) <= 0.15]      # 08:00 첫 봉 비정상 체결 제거(dow_structure와 동일 기준)
    return g.reset_index(drop=True)


MINUTE_PAST_PCT = 1.5   # 분봉 과거 사다리 눈금 — 일봉 눈금은 분봉 창에 안 들어온다


def past_ladders(full, code, x0, view="D"):
    """지나간 구간의 되돌림 사다리. 각 구간의 **고점일~다음 저점일**에만 긋는다.

    현재 구간만 보면 "지난번엔 1/3 에서 돌았나 2/3 까지 갔나"를 알 수 없다.
    화면에 들어오는 구간만 그린다 — 다 그리면 옛 선이 화면을 덮는다.
    """
    # 분봉은 **그 봉 자체의 스윙**을 쓴다. 일봉 구간의 고점~다음 저점은 며칠 단위라
    # 분봉 창(현재 구간, 보통 이틀)에 하나도 안 들어온다. 현재 구간은 그대로 일봉
    # 기준이고, 과거 사다리만 화면 해상도에 맞춘다.
    if view == "D":
        src = load(code)
        _lg, pct = pick_leg(src)
    else:
        src, pct = full, MINUTE_PAST_PCT
    # 화면에 들어오는 구간만, 그중 **최근 것부터 PAST_MAX 개**. 3% 눈금이면 일봉
    # 90 봉 안에 19 개까지 나와서(실측) 다 그리면 선이 봉을 덮는다.
    inview = [g for g in past_legs(src, pct) if g["끝일"] >= x0]
    out = []
    for g in inview[-PAST_MAX:]:
        a, b = max(g["고점일"], x0), g["끝일"]
        for f, col in ((1/3, "#b98d4e"), (1/2, "#a97c3c"), (2/3, "#96682c")):
            out.append(go.Scatter(x=[a, b], y=[g["레벨"][f]] * 2, mode="lines",
                                  line=dict(color=col, width=1.3, dash="dot"),
                                  showlegend=False, hoverinfo="skip", visible=False))
        # 실제로 어디까지 되돌렸는지 — 그 바닥에 점을 찍는다
        out.append(go.Scatter(x=[b], y=[g["바닥"]], mode="markers",
                              marker=dict(color="#8a5a28", size=8, symbol="circle-open",
                                          line=dict(width=2)),
                              showlegend=False, visible=False,
                              hovertext=[f"{g['저점일']:%m-%d}~{g['고점일']:%m-%d} 구간 "
                                         f"되돌림 {(g['고점']-g['바닥'])/(g['고점']-g['저점'])*100:.0f}%"],
                              hoverinfo="text"))
    return out


def levels(full, code):
    """다우 되돌림 기준 — 마지막 확정 저점, 그 이후 최고가, 1/3·1/2·2/3 선.

    폰 화면(dow_mobile.frame)과 **같은 규칙**을 쓴다. 예전에는 여기만 달라서 같은
    종목·같은 탭인데 두 화면이 다른 구간을 말했다(사용자 지적):

    1. 구간은 **항상 일봉에서** 잡는다. 분봉에서 따로 잡으면 +4% 짜리 미니 구간이
       나와 일봉과 어긋난다.
    2. 눈금은 고정값이 아니라 pick_leg 가 고른다. 고정 2% 는 큰 구간을 못 본다.
    3. 되돌림은 마지막 봉의 저가가 아니라 **고점 이후 최저가**로 잰다. 마지막 봉을
       쓰면 같은 구간인데 일봉 36% / 15분 6% 처럼 뷰마다 값이 갈린다.
    """
    daily = load(code)
    lg, _best = pick_leg(daily)
    if lg is None:
        return None
    after = full[full.date >= pd.Timestamp(lg["고점일"]).normalize()]
    trough = after.low.min() if len(after) else full.low.iloc[-1]
    r = retracement(lg["저점"], lg["고점"], trough)
    return lg, r


def hline(x0, x1, y, color, name, width=1.4, dash="dash", show=True):
    return go.Scatter(x=[x0, x1], y=[y, y], mode="lines", name=name, visible=show,
                      line=dict(color=color, width=width, dash=dash), hoverinfo="name+y")

def build(code, name, view, show):
    label, cfg, n, _sess, mas = TF[view]
    full = bars(code, view)
    df = full.tail(n).reset_index(drop=True)
    lg, r = levels(full, code)
    cur = full.close.iloc[-1]
    x0, x1 = df.date.iloc[0], df.date.iloc[-1]
    # 현재 구간 선은 **화면 전체**로 긋는다. 구간 안에만 그으면 갓 시작된 구간에서
    # 선이 오른쪽 끝에 뭉쳐 안 보인다. "그때 그 자리"는 과거 사다리가 맡는다.
    tr = [go.Candlestick(x=df.date, open=df.open, high=df.high, low=df.low, close=df.close,
                         name=f"{name} {label}", visible=show,
                         increasing_line_color="#d92b2b", decreasing_line_color="#1f6fd0")]
    # 고점 돌파선(= 새 고점을 만들어야 하는 자리)을 가장 굵게
    tr.append(hline(x0, x1, lg["고점"], "#e67e22",
                    f"★ 고점 돌파 {lg['고점']:,.0f} ({(lg['고점']/cur-1)*100:+.1f}%)",
                    width=3.2, dash="solid", show=show))
    for f, lab, col in ((1/3, "1/3 되돌림", "#f0b27a"), (1/2, "1/2 되돌림", "#e59866"),
                        (2/3, "2/3 되돌림", "#ca6f1e")):
        v = r["레벨"][f]
        tr.append(hline(x0, x1, v, col, f"{lab} {v:,.0f} ({(v/cur-1)*100:+.1f}%)",
                        width=1.6, dash="dash", show=show))
    for _t in past_ladders(full, code, x0, view):
        _t.visible = show
        tr.append(_t)
    tr.append(hline(x0, x1, lg["저점"], "#1f7a3f",
                    f"확정 저점 {lg['저점']:,.0f} ({(lg['저점']/cur-1)*100:+.1f}%)",
                    width=2.4, dash="solid", show=show))
    # 현재가 선은 뺐다 — 마지막 봉이 이미 그 자리를 말하고, 화면을 가로지르는 선이
    # 하나 늘면 되돌림 선과 섞여 어느 게 기준인지 헷갈린다(사용자 요청).
    tr.append(go.Scatter(x=[x1], y=[lg["고점"]], mode="text", visible=show, showlegend=False,
                         text=[f"  ★ 돌파 {lg['고점']:,.0f}"], textposition="middle right",
                         textfont=dict(color="#d35400", size=13, family="Malgun Gothic")))
    for period, col in zip(mas, ("#f39c12", "#16a085")):
        ma = full.close.rolling(period).mean()
        tr.append(go.Scatter(x=full.date.tail(n), y=ma.tail(n), mode="lines", visible=show,
                             name=f"MA{period}", line=dict(color=col, width=1.8)))
    state, sigs = dow_state(full, cfg["base_pct"])
    for kind, sym, col in [("BUY", "triangle-up", "#1f7a3f"), ("SELL", "triangle-down", "#c0392b")]:
        s = [(d, p) for d, k, p in sigs if k == kind and d >= x0]
        if s:
            tr.append(go.Scatter(x=[d for d, _ in s], y=[p for _, p in s], mode="markers",
                                 marker=dict(symbol=sym, size=17, color=col,
                                             line=dict(color="white", width=1.5)),
                                 name=f"{'매수' if kind == 'BUY' else '매도'} 신호", visible=show,
                                 hovertemplate="%{x|%Y-%m-%d %H:%M}<br>%{y:,.0f}<extra></extra>"))
    title = (f"{name} [{label}]  {cur:,.0f}　|　{lg['저점']:,.0f}({lg['저점일']:%m-%d}) → "
             f"{lg['고점']:,.0f}({lg['고점일']:%m-%d}) +{lg['상승률']:.1f}%　|　"
             f"되돌림 {r['되돌림비율']*100:.0f}% → {r['판정']}")
    tr.append(go.Scatter(x=[x1 + (x1 - x0) * 0.05], y=[cur], mode="markers", visible=show,
                         marker=dict(size=1, color="rgba(0,0,0,0)"), showlegend=False,
                         hoverinfo="skip"))
    pad = (x1 - x0) * 0.06                      # 마지막 봉이 오른쪽 끝에 붙어 잘리지 않게 여백
    return tr, title, [str(x0), str(x1 + pad)]


def main():
    fig = go.Figure(); groups, titles, views, ranges = [], [], [], []
    for code, name in CODES:
        for tf in TF:
            first = not groups
            tr, title, rng = build(code, name, tf, first)
            views.append(tf); ranges.append(rng)
            groups.append((len(fig.data), len(tr))); titles.append(title)
            for t in tr: fig.add_trace(t)
    buttons = []
    for i, ((start, n), title) in enumerate(zip(groups, titles)):
        vis = [False] * len(fig.data)
        for k in range(start, start + n): vis[k] = True
        lbl = f"{CODES[i // len(TF)][1]} {TF[views[i]][0]}"
        sess = TF[views[i]][3]
        breaks = ([dict(bounds=["sat", "mon"])] if views[i] == "D" else
                  [dict(bounds=["sat", "mon"]), dict(bounds=[sess[1], sess[0]], pattern="hour")])
        buttons.append(dict(label=lbl, method="update",
                            args=[{"visible": vis},
                                  {"annotations[0].text": title, "xaxis.rangebreaks": breaks,
                                   "xaxis.autorange": True}]))
    fig.update_layout(
        title=None,
        annotations=[dict(text=titles[0], xref="paper", yref="paper", x=0, y=1.055,
                          xanchor="left", yanchor="bottom", showarrow=False,
                          font=dict(size=15, color="#111"))],
        template="plotly_white", autosize=True, height=800, hovermode="x unified",
        margin=dict(l=80, r=40, t=155, b=95),
        font=dict(family="Malgun Gothic, sans-serif", size=13),
        legend=dict(orientation="h", y=-0.30, x=0),
        xaxis=dict(rangeslider=dict(visible=True, thickness=0.07),
                   rangebreaks=[dict(bounds=["sat", "mon"])],
                   autorange=True),
        yaxis=dict(tickformat=",", separatethousands=True),
        updatemenus=[dict(type="buttons", direction="right", x=0, y=1.14,
                          xanchor="left", yanchor="bottom", buttons=buttons, active=0,
                          bgcolor="#f4f6f8", bordercolor="#ccc", pad=dict(r=6, t=4))])
    out = "static/dashboard/dow_interactive.html"
    fig.write_html(out, include_plotlyjs="inline", full_html=True,
                   config={"responsive": True, "displaylogo": False,
                           "modeBarButtonsToRemove": ["select2d", "lasso2d"]},
                   default_width="100%", default_height="800px")
    # plotly 는 head 를 자기가 쓴다. 자동 새로고침은 파일을 쓴 뒤 끼워 넣는다 —
    # 서버가 이 파일을 그대로 보내므로 여기 없으면 화면이 영영 안 바뀐다.
    html = pathlib.Path(out).read_text(encoding="utf-8")
    tag = '<meta http-equiv="refresh" content="60">'
    if tag not in html:
        pathlib.Path(out).write_text(html.replace("<head>", "<head>" + tag, 1),
                                     encoding="utf-8")
    print("saved", out)

def demo():
    tr, title, rng = build("000660", "SK하이닉스", "D", True)
    tr15, t15, rng15 = build("000660", "SK하이닉스", "15A", False)
    assert rng[1] > rng[0] and rng15[1] > rng15[0], (rng, rng15)
    assert any(getattr(x, "name", "") == "MA120" for x in tr15), "15분봉엔 MA120이 있어야 한다"
    assert any(isinstance(t, go.Candlestick) for t in tr), "봉차트 트레이스 필요"
    assert "되돌림" in title, title

    # 과거 구간의 되돌림도 그려야 한다 — 현재 것만 보면 "지난번엔 1/3 에서 돌았나"를
    # 알 수 없다. 구간당 선 3 + 바닥점 1.
    _full = bars("000660", "D")
    _lad = past_ladders(_full, "000660", _full.tail(TF["D"][2]).date.iloc[0])
    assert _lad and len(_lad) % 4 == 0, len(_lad)
    assert len(_lad) // 4 <= PAST_MAX, f"과거 구간을 {len(_lad)//4}개나 그린다"

    # 두 화면이 같은 구간을 말해야 한다. 예전에는 여기만 고정 눈금·마지막 봉 저가를
    # 써서 같은 종목·같은 탭인데 값이 갈렸다(사용자 지적).
    import dow_mobile as _m
    for _code in ("000660", "005930"):
        _dlg, _dr = levels(bars(_code, "15A"), _code)
        _, _mlg, _mr, _ = _m.frame(_code, "15", "통합", (1, 2, 3, 5, 8))
        assert (_dlg["저점"], _dlg["고점"]) == (_mlg["저점"], _mlg["고점"]),             f"{_code}: desktop {_dlg['저점']}~{_dlg['고점']} vs mobile {_mlg['저점']}~{_mlg['고점']}"
        assert abs(_dr["되돌림비율"] - _mr["되돌림비율"]) < 0.01,             f"{_code}: 되돌림 {_dr['되돌림비율']:.2f} vs {_mr['되돌림비율']:.2f}"
    print("demo ok:", title[:90])

if __name__ == "__main__":
    demo() if "--demo" in sys.argv else main()
