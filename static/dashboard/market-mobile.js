// 휴대폰 카드 보기 도우미(10-05 사용자 "반응형 웹으로") — 5개 시장 화면 공용.
// 열이 5개 이상인 표에 class="cards" 를 달고, 칸마다 그 열 이름을 data-label 로 적는다. 표는 각 화면이 다시 그리므로
// 바뀔 때마다(MutationObserver) 다시 단다. 실제 모양 전환은 market.css 의 좁은 화면 규칙이 한다(넓은 화면은 그대로).
(function () {
  function label(table) {
    const heads = [...table.querySelectorAll("thead th")].map((th) => th.textContent.trim());
    if (heads.length < 5 || table.closest("details.legend")) return;
    table.classList.add("cards");
    for (const tr of table.querySelectorAll("tbody tr")) {
      [...tr.children].forEach((td, i) => {
        if (td.dataset.label === undefined) td.dataset.label = heads[i] || "";
        if (td.querySelector(".name-main")) td.classList.add("card-title");   // 종목명 칸을 카드 맨 위 제목으로
      });
    }
  }
  let queued = false;
  function run() { queued = false; document.querySelectorAll("table").forEach(label); }
  new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(run); } })
    .observe(document.body, { childList: true, subtree: true });
  run();
})();
