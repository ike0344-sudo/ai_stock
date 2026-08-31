"""폰에서 보는 다우 추세 화면 — 라이브러리 없이 인라인 SVG로 그린다.

    python dow_mobile.py          # static/dashboard/dow_mobile.html
    python dow_mobile.py --demo

plotly 인라인은 4.9MB라 폰/터널에서 무겁다. 캔들 40개 + 수평선 6개면 SVG로 충분하다.
읽기 전용이고 서버가 필요 없다 — 파일만 열면 된다.
"""
import sys, html, pandas as pd
sys.path.insert(0, ".")
from dow_structure import (SCALES, current_leg, load_session, past_legs,
                           pick_leg, retracement)

CODES = [("000660", "SK하이닉스"), ("005930", "삼성전자")]
# (탭이름, 봉, 세션, 스윙 눈금 후보) — 15분봉은 하루 26~48봉이라 눈금을 잘게 쓴다
VIEWS = [("일봉 정규", "D", "정규장", SCALES),
         ("일봉 통합", "D", "통합", SCALES),
         ("15분 정규", "15", "정규장", (1, 2, 3, 5, 8)),
         ("15분 통합", "15", "통합", (1, 2, 3, 5, 8))]
BARS = 40
PAST_MAX = 5         # 화면에 겹쳐 그릴 과거 구간 수
MINUTE_PAST_PCT = 1.5   # 분봉 과거 사다리 눈금 — 일봉 눈금은 분봉 창에 안 들어온다
RELOAD_SEC = 60      # 페이지가 스스로 다시 부른다 — 서버가 요청마다 새로 그린다


def load_view(code, tf, session):
    """일봉은 dow_structure와 같은 소스. 15분봉은 정규장(KRX 1분봉 리샘플) /
    통합(KRX+NXT 15분봉)을 각각 읽고 세션 시간대로 자른다."""
    if tf == "D":
        return load_session(code, session)
    if session == "정규장":
        m = pd.read_csv(f"data/stocks/minute/{code}.csv", parse_dates=["date"])
        g = (m.set_index("date").resample("15min")
             .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                  close=("close", "last"), volume=("volume", "sum")).dropna().reset_index())
        h = g.date.dt.hour + g.date.dt.minute / 60
        return g[(h >= 9) & (h < 15.5)].reset_index(drop=True)
    g = pd.read_csv(f"data/stocks/minute_combined/{code}_15.csv", parse_dates=["date"])
    h = g.date.dt.hour + g.date.dt.minute / 60
    g = g[(h >= 8) & (h < 20)]
    g = g[(g.high / g.low - 1) <= 0.15]        # 08:00 첫 봉 비정상 체결 제거
    return g.reset_index(drop=True)


def frame(code, tf, session, scales):
    """추세 구간(저점·고점·되돌림선)은 **항상 일봉에서 정한다**. 15분봉은 그 구간을
    더 자세히 보는 화면일 뿐이다 — 분봉에서 따로 구간을 잡으면 +4%짜리 미니 구간이
    나와 일봉과 값이 어긋난다(사용자 지적, 실측 확인)."""
    df = load_view(code, tf, session)
    daily = df if tf == "D" else load_view(code, "D", session)
    lg, best = pick_leg(daily, SCALES)
    # 되돌림은 '마지막 봉의 저가'가 아니라 **고점 이후 최저가**로 잰다. 마지막 봉을 쓰면
    # 같은 구간인데도 일봉 36% / 15분 6%처럼 뷰마다 값이 갈린다(실측).
    after = df[df.date >= pd.Timestamp(lg["고점일"]).normalize()]
    trough = after.low.min() if len(after) else df.low.iloc[-1]
    r = retracement(lg["저점"], lg["고점"], trough)
    return df, lg, r, best


def window(df, lg, bars=BARS):
    """현재 구간(확정 저점 ~ 지금)이 화면을 채우도록 자른다. 무조건 tail(40)을 쓰면
    한참 전 고점까지 y축에 들어와 되돌림선이 한 줄로 뭉친다(실측)."""
    if df.date.dt.hour.nunique() > 1:            # 분봉: 일봉 구간 저점일부터 보여준다
        d = df[df.date >= pd.Timestamp(lg["저점일"]).normalize()]
        return (d.tail(120) if len(d) > 120 else d).reset_index(drop=True)
    i = df.index[df.date == lg["저점일"]]
    # 저점 앞 여유 6봉은 두되, 최소 20봉은 보이게(9봉만 남으면 맥락이 안 보인다)
    start = min(int(i[0]) - 6, len(df) - 20) if len(i) else len(df) - bars
    start = max(start, 0)
    d = df.iloc[start:]
    return (d.tail(bars) if len(d) > bars else d).reset_index(drop=True)


def svg(df, lg, r, w=360, h=210, pad=4, past=()):
    """현재 구간 봉 + 되돌림선. 좌표 계산만 하는 순수 함수.

    past 는 지나간 구간의 되돌림 사다리다 — 현재 것만 보면 "지난번엔 1/3 에서
    돌았나 2/3 까지 갔나"를 알 수 없다. 각 구간의 고점~다음 저점 자리에만 긋는다.
    """
    d = window(df, lg)
    lines = [(lg["고점"], "#e8890c", "돌파"), (r["레벨"][1/3], "#c97b1e", "1/3"),
             (r["레벨"][1/2], "#a86a24", "1/2"), (r["레벨"][2/3], "#8a5a28", "2/3"),
             (lg["저점"], "#2aa36b", "저점")]
    lo = min(d.low.min(), min(v for v, _, _ in lines))
    hi = max(d.high.max(), max(v for v, _, _ in lines))
    rng = hi - lo or 1
    y = lambda v: pad + (hi - v) / rng * (h - 2 * pad)
    bw = (w - 8) / max(len(d), 1)

    intraday = d.date.dt.hour.nunique() > 1

    def x_at(day, default=0.0):
        """그 시각의 봉 x. 화면 밖(왼쪽)이면 0 — 선이 왼쪽 끝부터 나온다.

        **분봉에서는 normalize 하면 안 된다.** 시각을 자정으로 자르면 같은 날 안의
        구간이 시작·끝 모두 그날 첫 봉으로 뭉쳐 폭 0 이 되고, 선이 통째로 사라진다
        (실측: 15분 탭에 과거 사다리가 하나도 안 나왔다).
        """
        t = pd.Timestamp(day)
        hit = d.index[d.date >= (t if intraday else t.normalize())]
        return 4 + int(hit[0]) * bw if len(hit) else default

    # 현재 구간 선은 **화면 전체**로 긋는다. "지금 1/3 이 어디냐"는 한눈에 읽혀야
    # 하는 값인데, 구간 안에만 그으면 갓 시작된 구간에서는 오른쪽 끝 몇십 px 로
    # 뭉쳐 안 보인다(실측: 고점일부터 22px, 저점일부터도 39px).
    # "그때 그 자리"는 아래 과거 사다리가 맡는다 — 역할을 나눈다.
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="none">']
    # 과거 사다리를 **먼저** 그린다 — 현재 선과 봉이 그 위에 와야 눈이 안 헷갈린다.
    for g in past:
        a, b = x_at(g["고점일"]), x_at(g["끝일"], default=w)
        if b <= a:
            continue
        for f in (1/3, 1/2, 2/3):
            v = g["레벨"][f]
            if not lo <= v <= hi:
                continue                   # 화면 밖 값은 y 축을 안 늘리고 그냥 뺀다
            # 차트 배경이 #0e1015 라 어두운 색은 안 보인다. 현재 선(주황)보다는
            # 흐리되 배경과는 확실히 갈리는 회갈색으로, 점선도 촘촘하게.
            out.append(f'<line x1="{a:.1f}" y1="{y(v):.1f}" x2="{b:.1f}" y2="{y(v):.1f}" '
                       f'stroke="#d8b878" stroke-width="1.3" stroke-dasharray="3 2"/>')
        if lo <= g["바닥"] <= hi:
            out.append(f'<circle cx="{b:.1f}" cy="{y(g["바닥"]):.1f}" r="2.6" '
                       f'fill="none" stroke="#f0a94a" stroke-width="1.6"/>')
    for v, col, lab in lines:
        x_from = 0.0
        out.append(f'<line x1="{x_from:.1f}" y1="{y(v):.1f}" x2="{w}" y2="{y(v):.1f}" '
                   f'stroke="{col}" stroke-width="1" stroke-dasharray="{"" if lab in ("돌파","저점") else "4 3"}"/>')
    for i, b in enumerate(d.itertuples()):
        x = 4 + i * bw + bw / 2
        col = "#e2504a" if b.close >= b.open else "#3b82e0"
        out.append(f'<line x1="{x:.1f}" y1="{y(b.high):.1f}" x2="{x:.1f}" y2="{y(b.low):.1f}" stroke="{col}" stroke-width="1"/>')
        top, bot = y(max(b.open, b.close)), y(min(b.open, b.close))
        out.append(f'<rect x="{x-bw*0.32:.1f}" y="{top:.1f}" width="{bw*0.64:.1f}" '
                   f'height="{max(bot-top,1):.1f}" fill="{col}"/>')
    out.append("</svg>")
    return "".join(out)


def card(code, name, label, tf, session, scales):
    df, lg, r, best = frame(code, tf, session, scales)
    # 과거 사다리는 화면에 들어오는 것만, 최근 것부터.
    #
    # **분봉은 그 봉 자체의 스윙을 쓴다.** 일봉 구간의 고점~다음 저점은 며칠 단위라
    # 15분 창(현재 구간, 보통 이틀)에 하나도 안 들어온다. 창을 그만큼 넓히면 봉이
    # 수백 개가 돼 캔들이 실선처럼 뭉갠다. 현재 구간은 그대로 일봉 기준이고,
    # 과거 사다리만 화면 해상도에 맞춘다.
    seen = window(df, lg)
    src = load_session(code, session) if tf == "D" else df
    # 눈금도 봉에 맞춘다. 15분에 3% 를 쓰면 이틀 안에 스윙이 한 번밖에 안 잡힌다
    # (실측: 3% → 1개, 1.5% → 5~6개). 잔 눈금은 PAST_MAX 가 잘라 준다.
    _pl, ppct = pick_leg(src, scales) if tf == "D" else (None, MINUTE_PAST_PCT)
    past = [g for g in past_legs(src, ppct)
            if g["끝일"] >= seen.date.iloc[0]][-PAST_MAX:]
    cur = df.close.iloc[-1]
    pct = lambda v: (v / lg["고점"] - 1) * 100        # 고점 대비(현재가 대비 아님)
    dfmt = "%m/%d" if tf == "D" else "%m/%d %H:%M"
    rows = [("★ 고점 돌파", lg["고점"], "#e8890c", ""), ("1/3 되돌림", r["레벨"][1/3], "#c97b1e", ""),
            ("1/2 되돌림", r["레벨"][1/2], "#a86a24", ""), ("2/3 되돌림", r["레벨"][2/3], "#8a5a28", ""),
            ("확정 저점", lg["저점"], "#2aa36b", ""),
            ("▶ 현재 종가", cur, "#5aa9e6", "now")]        # 어느 선 사이에 있는지 보이게 끼워 넣는다
    rows.sort(key=lambda x: -x[1])
    grade = r["판정"]
    gcol = "#2aa36b" if grade.startswith("소추세") else "#e8890c" if "중간" in grade else "#e2504a"
    lis = "".join(
        f'<li class="{cls}"><span class="lab" style="color:{c}">{html.escape(lab)}</span>'
        f'<span class="val">{v:,.0f}</span><span class="pc">{pct(v):+.1f}%</span></li>'
        for lab, v, c, cls in rows)
    return f'''<section class="card">
  <div class="hd"><b>{html.escape(name)}</b><span class="sess">{html.escape(label)}</span>
    <span class="cur">{cur:,.0f}<i>{pct(cur):+.1f}%</i></span></div>
  <div class="leg">{lg['저점']:,.0f} <i>{lg['저점일']:{dfmt}}</i> → {lg['고점']:,.0f} <i>{lg['고점일']:{dfmt}}</i>
    &nbsp;+{lg['상승률']:.1f}% &nbsp;<i>눈금 {best}%</i></div>
  <div class="grade" style="background:{gcol}22;color:{gcol};border-color:{gcol}66">
    되돌림 {r['되돌림비율']*100:.0f}% · {html.escape(grade)}</div>
  {svg(df, lg, r, past=past)}
  <div class="lvhd">가격<span>고점 대비</span></div>
  <ul class="lv">{lis}</ul>
</section>'''


HELP = """<details class="help"><summary>이 숫자들이 무슨 뜻인가요?</summary>
<p><b>다우이론은 "몇 % 빠졌나"로 안 봅니다.</b> 대신 <b>직전에 오른 폭을 얼마나 반납했나</b>로 봅니다.
같은 -5%라도 30% 오른 뒤면 가볍고, 8% 오른 뒤면 무겁기 때문입니다.</p>
<table>
<tr><td class="k" style="color:#2aa36b">확정 저점</td><td>이 구간이 시작된 바닥. 여기까지 내려오면 <b>오른 걸 100% 반납</b>한 것 — 구간이 무효가 됩니다.</td></tr>
<tr><td class="k" style="color:#8a5a28">2/3 되돌림</td><td>오른 폭의 <b>3분의 2를 반납</b>. 다우가 말하는 정상 조정의 <b>한계선</b>입니다. 이 아래로 내려가면 <b>추세 자체를 의심</b>합니다.</td></tr>
<tr><td class="k" style="color:#a86a24">1/2 되돌림</td><td><b>절반 반납</b>. 조정 중에서도 깊은 편이지만 아직 정상 범위입니다.</td></tr>
<tr><td class="k" style="color:#c97b1e">1/3 되돌림</td><td>오른 폭의 <b>3분의 1 반납</b>. 여기부터가 다우가 인정하는 <b>조정의 시작</b>입니다.</td></tr>
<tr><td class="k" style="color:#e8890c">★ 고점 돌파</td><td>이 구간의 꼭대기. <b>여기를 넘어야 새 고점</b>이 되고 상승이 이어졌다고 확인됩니다.</td></tr>
</table>
<p class="grades"><b>등급 읽는 법</b><br>
<span style="color:#2aa36b">■ 소추세(노이즈)</span> — 되돌림 33% 미만. 잠깐 쉬는 것이고 추세는 그대로입니다.<br>
<span style="color:#e8890c">■ 중간반응(정상 조정)</span> — 되돌림 33~67%. 흔히 나오는 조정이고 추세는 아직 살아있습니다.<br>
<span style="color:#e2504a">■ 2/3 초과(추세 의심)</span> — 되돌림 67% 초과. 오른 걸 대부분 토해냈습니다. 상승 구조가 깨질 수 있습니다.</p>
<p class="tip"><b>눈금 %</b>는 "이만큼 되돌려야 봉우리·골짜기로 인정한다"는 기준입니다. 변동성이 큰 종목일수록 커집니다.
<br><b>기준 고점</b>은 마지막 확정 저점 이후의 최고가입니다 — 저점을 찍고 다시 오르면 기준도 따라 올라갑니다.</p>
</details>"""


def build():
    tabs, panes = [], []
    for code, name in CODES:
        short = name.replace("하이닉스", "하닉").replace("삼성전자", "삼전")
        for j, (label, tf, session, scales) in enumerate(VIEWS):
            tid = f"{code}v{j}"
            tabs.append(f'<button class="tab{" on" if not tabs else ""}" data-t="{tid}">'
                        f'{html.escape(short)} {html.escape(label)}</button>')
            panes.append(f'<div class="pane{" on" if not panes else ""}" id="{tid}">'
                         f'{card(code, name, label, tf, session, scales)}</div>')
    now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta http-equiv="refresh" content="{RELOAD_SEC}">
<title>다우 추세</title><style>
 :root{{--bg:#12141a;--fg:#e8eaf0;--dim:#8b93a7;--line:#252a35}}
 *{{box-sizing:border-box}}
 body{{margin:0 auto;max-width:460px;background:var(--bg);color:var(--fg);
   font:15px/1.45 -apple-system,BlinkMacSystemFont,"Malgun Gothic",sans-serif;padding-bottom:24px}}
 header{{padding:12px 14px 8px;display:flex;align-items:baseline;gap:8px;border-bottom:1px solid var(--line)}}
 header b{{font-size:17px}} header span{{color:var(--dim);font-size:12px;margin-left:auto}}
 .tabs{{display:flex;gap:6px;padding:10px 10px 4px;overflow-x:auto;-webkit-overflow-scrolling:touch}}
 .tab{{flex:0 0 auto;background:#1b1f28;color:var(--dim);border:1px solid var(--line);
   border-radius:16px;padding:7px 13px;font-size:13px}}
 .tab.on{{background:#2a3140;color:#fff;border-color:#3a4152}}
 .pane{{display:none;padding:8px 10px}} .pane.on{{display:block}}
 .card{{background:#171a22;border:1px solid var(--line);border-radius:12px;padding:12px}}
 .hd{{display:flex;align-items:baseline;gap:8px}} .hd b{{font-size:17px}}
 .sess{{font-size:11px;color:var(--dim);border:1px solid var(--line);border-radius:8px;padding:1px 6px}}
 .cur{{margin-left:auto;font-size:20px;font-weight:700;text-align:right;line-height:1.15}}
 .cur i{{display:block;font-style:normal;font-size:12px;font-weight:600;color:#5aa9e6}}
 .leg{{color:var(--dim);font-size:12px;margin:6px 0 8px}} .leg i{{font-style:normal;opacity:.7}}
 .grade{{display:inline-block;border:1px solid;border-radius:8px;padding:4px 10px;
   font-size:13px;font-weight:700;margin-bottom:10px}}
 svg{{display:block;height:210px;background:#0e1015;border-radius:8px;margin-bottom:10px}}
 .lv{{list-style:none;margin:0;padding:0}}
 .lvhd{{display:flex;color:var(--dim);font-size:11px;padding:2px 2px 4px}}
 .lvhd span{{margin-left:auto}}
 .lv li{{display:flex;align-items:center;gap:8px;padding:7px 2px;border-top:1px solid var(--line);font-size:14px}}
 .lv li.now{{background:#1d2836;border-radius:6px;font-weight:700}}
 .lv li.now .val,.lv li.now .pc{{color:#8fc6f2}}
 .lv .lab{{flex:0 0 96px;font-size:13px}} .lv .val{{margin-left:auto;font-variant-numeric:tabular-nums}}
 .lv .pc{{flex:0 0 60px;text-align:right;color:var(--dim);font-variant-numeric:tabular-nums}}
 .help{{margin:14px 10px 0;background:#171a22;border:1px solid var(--line);border-radius:12px;padding:2px 12px}}
 .help summary{{padding:11px 0;font-size:14px;font-weight:700;cursor:pointer;color:#c9d1e3}}
 .help p{{color:#b6bdcc;font-size:13px;line-height:1.6;margin:8px 0}}
 .help b{{color:#e8eaf0}}
 .help table{{width:100%;border-collapse:collapse;margin:6px 0 10px}}
 .help td{{padding:7px 0;border-top:1px solid var(--line);font-size:13px;color:#b6bdcc;line-height:1.55;vertical-align:top}}
 .help td.k{{width:88px;font-weight:700;padding-right:10px}}
 .help .grades{{background:#12141a;border-radius:8px;padding:10px}}
 .help .tip{{color:var(--dim);font-size:12px;border-top:1px solid var(--line);padding-top:9px}}
</style></head><body>
<header><b>다우 추세</b><span>{now}</span></header>
<div class="tabs">{''.join(tabs)}</div>
{''.join(panes)}
{HELP}
<script>
document.querySelectorAll('.tab').forEach(function(t){{t.onclick=function(){{
  document.querySelectorAll('.tab').forEach(function(x){{x.classList.remove('on')}});
  document.querySelectorAll('.pane').forEach(function(x){{x.classList.remove('on')}});
  t.classList.add('on'); document.getElementById(t.dataset.t).classList.add('on');
}}}});
</script></body></html>'''


def demo():
    df, lg, r, best = frame("000660", "D", "정규장", SCALES)
    d15, l15, r15, b15 = frame("000660", "15", "정규장", (1, 2, 3, 5, 8))
    assert d15.date.dt.hour.max() >= 14, "15분봉이어야 한다"
    assert (d15.date.dt.minute % 15 == 0).all(), "15분 격자여야 한다"
    assert (l15["저점"], l15["고점"]) == (lg["저점"], lg["고점"]),         f"15분봉도 일봉과 같은 구간을 써야 한다: {l15['저점']} vs {lg['저점']}"
    assert abs(r15["되돌림비율"] - r["되돌림비율"]) < 0.05,         f"같은 구간이면 되돌림도 비슷해야 한다: 일봉 {r['되돌림비율']:.2f} vs 15분 {r15['되돌림비율']:.2f}"
    s = svg(df, lg, r)
    assert s.startswith("<svg") and s.endswith("</svg>")
    # 되돌림 선은 고점 자리에서 시작해야 한다 — 왼쪽 끝(x1="0.0")부터 그으면
    # 구간이 생기기도 전 자리에 선이 걸린다.
    import re as _re
    # 역할이 둘로 갈린다: 현재 구간 선은 화면 전체(지금 1/3 이 어디냐), 과거 사다리는
    # 그 구간 자리에만(지난번엔 1/3 에서 돌았나). 둘이 섞이면 하나가 안 보인다.
    starts = [float(x) for x in _re.findall(r'<line x1="([\d.]+)" y1=', s)]
    assert starts[:5] == [0.0] * 5, f"현재 구간 선은 화면 전체여야 한다: {starts[:5]}"

    # 분봉 탭에도 과거 사다리가 나와야 한다. x_at 이 normalize 하면 같은 날 구간이
    # 폭 0 으로 뭉쳐 통째로 사라진다(실측: 15분 탭 0개).
    for _tf, _sess, _sc in (("D", "정규장", SCALES), ("15", "통합", (1, 2, 3, 5, 8))):
        _c = card("000660", "SK하이닉스", "x", _tf, _sess, _sc)
        assert _c.count("<circle") > 0, f"{_tf} 탭에 과거 되돌림 바닥점이 없다"
    n = len(window(df, lg))
    assert s.count("<rect") == n and n <= BARS, (s.count("<rect"), n)
    assert window(df, lg).low.min() <= lg["저점"] * 1.001, "확정 저점이 화면에 들어와야 한다"
    # 눈금은 **지금 붙어 있는 구간**을 잡아야 한다. 예전 pick_leg 는 ATR 로 시작
    # 눈금을 고르고 키우기만 해서, 큰 눈금이 최근 스윙을 통째로 건너뛰었다.
    import pandas as _pd
    bars = [(1000, 1000, 1000), (900, 880, 890), (1200, 1180, 1190),   # +36% 큰 구간
            (1000, 980, 990), (1150, 1100, 1140)]                      # 되밀렸다 다시 +17%
    fake = _pd.DataFrame({"date": _pd.date_range("2026-08-01", periods=len(bars)),
                          "high": [b[0] for b in bars], "low": [b[1] for b in bars],
                          "close": [b[2] for b in bars],
                          "open": [b[2] for b in bars], "volume": [1] * len(bars)})
    _lg, _best = pick_leg(fake, SCALES)
    assert _lg["저점일"] == fake.date.iloc[3],         f"최근 저점을 잡아야 한다: {_lg['저점일']}"

    h = build()
    assert h.count('class="pane') == len(CODES) * len(VIEWS), h.count('class="pane')
    assert "plotly" not in h.lower(), "모바일 화면엔 무거운 라이브러리를 넣지 않는다"
    assert "<details" in h and "되돌림 33% 미만" in h, "하단 설명이 있어야 한다"
    assert "고점 대비" in h, "레벨 표는 고점 대비로 표시한다"
    assert h.count('class="now"') == len(CODES) * len(VIEWS), "뷰마다 현재가 행이 있어야 한다"
    # 고점 행은 0.0%, 저점 행은 (저점/고점-1) 이어야 한다
    hp, lp = lg["고점"], lg["저점"]
    assert f"{(hp/hp-1)*100:+.1f}%" == "+0.0%"
    assert f"{(lp/hp-1)*100:+.1f}%" in h, f"{(lp/hp-1)*100:+.1f}%"
    print(f"demo ok: 캔들 {n}개, 탭 {len(CODES)*len(VIEWS)}개, 크기 {len(h)/1024:.0f}KB")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        out = "static/dashboard/dow_mobile.html"
        open(out, "w", encoding="utf-8").write(build())
        import os
        print(f"saved {out} ({os.path.getsize(out)/1024:.0f}KB)")
