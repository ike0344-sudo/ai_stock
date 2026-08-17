"""상한 3.0 vs 2.0 비교 페이지 — 날짜를 눌러 그날 60분 기록을 좌우로 본다.

    python build_cap_page.py

kospi-theme-engine/results/aug_cap_compare.json 을 읽어 한 파일로 묶는다.
날짜별 페이지를 따로 만들면 링크를 찾아다녀야 한다.
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "kospi-theme-engine" / "results" / "aug_cap_compare.json"
OUT = ROOT / "results" / "cap_compare.html"
ALERT = 69.0

HEAD = """<title>상한 3.0 vs 2.0</title>
<style>
:root{
  color-scheme: light;
  --ground:#F5F6F7; --panel:#FFFFFF; --sunk:#EBEEF0; --line:#DDE2E5; --line-2:#C3CBD0;
  --ink:#12181C; --ink-2:#4A565E; --ink-3:#6E7C85;
  --accent:#2E6382; --hot:#B3382C; --hot-soft:#FBEDEB; --cool:#2E6382;
  --shadow:0 1px 2px rgba(18,24,28,.05),0 14px 30px -24px rgba(18,24,28,.5);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme: dark;
    --ground:#0F1316; --panel:#161B1F; --sunk:#12171A; --line:#232A2E; --line-2:#333D42;
    --ink:#E7ECEE; --ink-2:#A3B0B6; --ink-3:#77858C;
    --accent:#6FA8C7; --hot:#E07A68; --hot-soft:#26150F; --cool:#6FA8C7;
    --shadow:0 1px 2px rgba(0,0,0,.5),0 14px 30px -24px rgba(0,0,0,.9);
  }
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --ground:#0F1316; --panel:#161B1F; --sunk:#12171A; --line:#232A2E; --line-2:#333D42;
  --ink:#E7ECEE; --ink-2:#A3B0B6; --ink-3:#77858C;
  --accent:#6FA8C7; --hot:#E07A68; --hot-soft:#26150F; --cool:#6FA8C7;
  --shadow:0 1px 2px rgba(0,0,0,.5),0 14px 30px -24px rgba(0,0,0,.9);
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
  font-family:"Pretendard",system-ui,-apple-system,"Segoe UI","Malgun Gothic",sans-serif;
  font-size:15px;line-height:1.65;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:40px 20px 80px;
  display:flex;flex-direction:column;gap:26px}
.eyebrow{font-family:ui-monospace,Consolas,monospace;font-size:11px;letter-spacing:.2em;
  text-transform:uppercase;color:var(--ink-3);margin:0 0 10px}
h1{font-size:clamp(25px,3.4vw,34px);margin:0;font-weight:700;letter-spacing:-.025em}
.lede{margin:14px 0 0;color:var(--ink-2);max-width:62ch}
.days{display:flex;flex-wrap:wrap;gap:6px}
.days button{font-family:ui-monospace,Consolas,monospace;font-size:13px;
  border:1px solid var(--line-2);background:var(--panel);color:var(--ink-2);
  border-radius:8px;padding:7px 13px;cursor:pointer;font-variant-numeric:tabular-nums}
.days button:hover{border-color:var(--ink-3);color:var(--ink)}
.days button[aria-pressed="true"]{background:var(--ink);color:var(--ground);
  border-color:var(--ink);font-weight:700}
.days button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;
  background:var(--line);border:1px solid var(--line);border-radius:10px;
  overflow:hidden;box-shadow:var(--shadow)}
.tile{background:var(--panel);padding:14px 16px;display:flex;flex-direction:column;gap:2px}
.tile span{font-family:ui-monospace,Consolas,monospace;font-size:10.5px;letter-spacing:.11em;
  text-transform:uppercase;color:var(--ink-3)}
.tile b{font-family:ui-monospace,Consolas,monospace;font-size:25px;font-weight:600;
  line-height:1.15;font-variant-numeric:tabular-nums}
.tile b small{font-size:13px;color:var(--ink-2);font-weight:500;margin-left:2px}
.tile em{font-style:normal;font-size:12px;color:var(--ink-2)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  box-shadow:var(--shadow);padding:18px 20px;display:flex;flex-direction:column;gap:12px}
.card h2{margin:0;font-size:15px;font-weight:660}
.card h2 em{font-style:normal;font-weight:400;color:var(--ink-3);font-size:12.5px;margin-left:8px}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:9px}
table{border-collapse:collapse;width:100%;font-size:13px;
  font-family:ui-monospace,Consolas,"D2Coding",monospace;font-variant-numeric:tabular-nums}
th,td{padding:5px 10px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--line)}
thead th{background:var(--sunk);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--ink-3);font-weight:600;position:sticky;top:0}
th.l,td.l{text-align:left}
td.t{color:var(--ink-3)}
tbody tr:last-child td{border-bottom:0}
td.hot{color:var(--hot);font-weight:700}
tr.split td{border-left:1px solid var(--line-2)}
.note{font-size:13px;color:var(--ink-2)}
.note b{color:var(--ink)}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
"""

BODY = """
<div class="wrap">
  <header>
    <p class="eyebrow">대금 상위20 만점 기준 · 2026년 8월 10거래일</p>
    <h1>상한 3.0 vs 2.0</h1>
    <p class="lede">같은 데이터를 만점 기준만 바꿔 채점했다. 상한이 낮으면 자리합이 조금만
      높아도 만점이 되어, 삼성전자·SK하이닉스를 담은 테마가 매일 상위권에 붙는다.
      알림 문턱 69점을 넘긴 시간이 두 기준에서 얼마나 달라지는지가 핵심이다.</p>
  </header>

  <div class="days" id="days"></div>
  <div class="tiles" id="tiles"></div>

  <section class="card">
    <h2>1분 단위 기록 <em>각 기준의 1위와 2위 · 붉은 값은 69점 초과</em></h2>
    <div class="tablewrap"><table id="tbl"></table></div>
  </section>

  <p class="note">두 기준의 차이는 <b>대금 상위20 항목 하나</b>뿐이다. 나머지 7개 항목은
    같은 값이므로, 점수 차이는 전부 이 항목에서 나온다.</p>
</div>

<script id="payload" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById("payload").textContent);
const ALERT = 69.0;
const days = Object.keys(DATA).sort();
let cur = days[days.length - 1];

const ymd = d => `${d.slice(4,6)}/${d.slice(6)}`;
const dwell = (frames, key) => {
  const h = {};
  frames.forEach(f => { const t = f[key][0][0]; h[t] = (h[t] || 0) + 1; });
  return Object.entries(h).sort((a,b) => b[1]-a[1]);
};
const over = (frames, key) => frames.filter(f => f[key][0][1] >= ALERT).length;

function render() {
  const frames = DATA[cur];
  document.querySelectorAll("#days button").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.day === cur)));

  const d3 = dwell(frames, "a"), d2 = dwell(frames, "b");
  const best3 = Math.max(...frames.map(f => f.a[0][1]));
  const best2 = Math.max(...frames.map(f => f.b[0][1]));
  document.getElementById("tiles").innerHTML = `
    <div class="tile"><span>주도 테마</span><b>${d3[0][0]}</b>
      <em>${d3[0][1]}/${frames.length}분 1위 · 상한 3.0 기준</em></div>
    <div class="tile"><span>69점 초과 · 3.0</span><b>${over(frames,"a")}<small>분</small></b>
      <em>최고 ${best3.toFixed(1)}점</em></div>
    <div class="tile"><span>69점 초과 · 2.0</span><b>${over(frames,"b")}<small>분</small></b>
      <em>최고 ${best2.toFixed(1)}점</em></div>
    <div class="tile"><span>1위 교체</span><b>${
      frames.filter((f,i) => i && f.a[0][0] !== frames[i-1].a[0][0]).length}<small>회</small></b>
      <em>${d3.length}개 테마가 1위를 거쳐감</em></div>`;

  const cell = p => {
    const hot = p[1] >= ALERT ? ' class="hot"' : "";
    return `<td class="l">${p[0]}</td><td${hot}>${p[1].toFixed(1)}</td>`;
  };
  document.getElementById("tbl").innerHTML =
    `<thead><tr><th class="l">시각</th>
       <th class="l" colspan="2">3.0 · 1위</th><th class="l" colspan="2">3.0 · 2위</th>
       <th class="l" colspan="2">2.0 · 1위</th><th class="l" colspan="2">2.0 · 2위</th></tr></thead>
     <tbody>${frames.map(f =>
       `<tr><td class="l t">${f.t}</td>${cell(f.a[0])}${cell(f.a[1])}${cell(f.b[0])}${cell(f.b[1])}</tr>`
     ).join("")}</tbody>`;
}

document.getElementById("days").innerHTML = days.map(d =>
  `<button data-day="${d}" aria-pressed="false">${ymd(d)}</button>`).join("");
document.getElementById("days").addEventListener("click", ev => {
  const b = ev.target.closest("button");
  if (b) { cur = b.dataset.day; render(); }
});
render();
</script>
"""


def main() -> None:
    data = json.loads(RAW.read_text(encoding="utf-8"))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(HEAD + BODY.replace("__DATA__", json.dumps(data, ensure_ascii=False)),
                   encoding="utf-8")
    print(f"{OUT.name}  {OUT.stat().st_size // 1024}KB · {len(data)}일")


if __name__ == "__main__":
    main()
