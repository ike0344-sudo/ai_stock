// trading-dashboard 프론트엔드 — 빌드 도구 없는 바닐라 JS.
// XSS 방지를 위해 DOM에 값을 넣을 때 항상 textContent를 쓰고 innerHTML은 쓰지 않는다
// (Design §7 Security Considerations — 원본 데이터가 신뢰할 수 있는 자체 프로세스의
// 출력이라도 방어적으로 처리한다).

const POLL_INTERVAL_MS = 5000;
const TOP35_POLL_INTERVAL_MS = 2000;

let currentStrategy = null;

function strategyQuery() {
  return currentStrategy ? "?strategy=" + encodeURIComponent(currentStrategy) : "";
}

async function loadStrategies() {
  try {
    const res = await fetch("/api/strategies");
    if (!res.ok) return;
    const data = await res.json();
    const select = document.getElementById("strategy-select");
    const previous = currentStrategy;
    clearChildren(select);
    const options = data.strategies.length > 0 ? data.strategies : [data.selected];
    for (const name of options) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      select.appendChild(option);
    }
    // 목록이 갱신돼도(전략2가 새로 나타나는 등) 사용자가 이미 골라둔 전략은 유지한다 —
    // 없어진 경우에만 서버가 알려준 selected로 되돌아간다.
    currentStrategy = options.includes(previous) ? previous : data.selected;
    select.value = currentStrategy;
  } catch (err) {
    // 다음 폴링에서 자연히 재시도됨.
  }
}

function formatKrw(value) {
  return Math.round(value).toLocaleString("ko-KR") + "원";
}

function clearChildren(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
}

const MARKET_INDEX_LABELS = [
  ["kospi", "코스피"],
  ["kosdaq", "코스닥"],
  ["nasdaq", "나스닥"],
];

function formatIndexValue(value) {
  return value.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function renderMarketTicker(snapshot) {
  const container = document.getElementById("market-ticker");
  clearChildren(container);

  for (const [key, label] of MARKET_INDEX_LABELS) {
    const data = snapshot[key];
    const span = document.createElement("span");
    span.classList.add("badge");

    if (data) {
      const changePct = data.change_pct;
      const changeText = changePct === null || changePct === undefined
        ? ""
        : ` (${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%)`;
      span.textContent = `${label} ${formatIndexValue(data.value)}${changeText}`;
      span.classList.add(changePct >= 0 ? "badge-positive" : "badge-negative");
    } else {
      span.textContent = `${label} -`;
      span.classList.add("badge-ok");
    }
    container.appendChild(span);
  }
}

async function pollMarketSnapshot() {
  try {
    const res = await fetch("/api/market-snapshot");
    if (res.ok) renderMarketTicker(await res.json());
  } catch (err) {
    // 메인 연결경고와 별개로 조용히 재시도.
  }
}

const DEPOSIT_FIELD_LABELS = [
  ["deposit_krw", "예수금"],
  ["order_available_krw", "주문가능금액"],
  ["withdrawable_krw", "출금가능금액"],
  ["d2_deposit_krw", "D+2 예수금"],
];

function renderDeposit(deposit) {
  const tbody = document.getElementById("deposit-tbody");
  clearChildren(tbody);
  const hasDeposit = Boolean(deposit);

  document.getElementById("deposit-table").classList.toggle("hidden", !hasDeposit);
  document.getElementById("deposit-empty").classList.toggle("hidden", hasDeposit);
  if (!hasDeposit) return;

  for (const [key, label] of DEPOSIT_FIELD_LABELS) {
    const row = document.createElement("tr");
    const th = document.createElement("th");
    th.textContent = label;
    const td = document.createElement("td");
    td.textContent = formatKrw(deposit[key]);
    row.appendChild(th);
    row.appendChild(td);
    tbody.appendChild(row);
  }
}

const RANKING_WINDOWS = ["regular", "extended"];

function renderRanking(windowKey, data) {
  const tbody = document.getElementById(`ranking-${windowKey}-tbody`);
  const table = document.getElementById(`ranking-${windowKey}-table`);
  const empty = document.getElementById(`ranking-${windowKey}-empty`);
  const asOf = document.getElementById(`ranking-${windowKey}-as-of`);
  const rows = data.rows || [];

  asOf.textContent = data.as_of ? `${data.as_of} 기준` : "-";

  if (!data.active && rows.length === 0) {
    table.classList.add("hidden");
    empty.classList.remove("hidden");
    return;
  }

  empty.classList.add("hidden");
  table.classList.remove("hidden");
  clearChildren(tbody);
  for (const item of rows) {
    const row = document.createElement("tr");
    const cells = [item.rank, item.stock_code, item.name, formatKrw(item.trading_value)];
    for (const value of cells) {
      const td = document.createElement("td");
      td.textContent = value;
      row.appendChild(td);
    }
    tbody.appendChild(row);
  }
}

async function pollRanking(windowKey) {
  try {
    const res = await fetch(`/api/trading-value-ranking?window=${windowKey}`);
    if (res.ok) renderRanking(windowKey, await res.json());
  } catch (err) {
    // 메인 연결경고와 별개로 조용히 재시도.
  }
}

function pollAllRankings() {
  for (const windowKey of RANKING_WINDOWS) pollRanking(windowKey);
}

function renderHoldings(holdings) {
  const tbody = document.getElementById("holdings-tbody");
  clearChildren(tbody);
  const list = holdings || [];

  document.getElementById("holdings-empty").classList.toggle("hidden", list.length > 0);
  document.getElementById("holdings-table").classList.toggle("hidden", list.length === 0);

  for (const holding of list) {
    const row = document.createElement("tr");
    const cells = [
      holding.code,
      holding.name,
      holding.quantity,
      formatKrw(holding.avg_price),
      formatKrw(holding.current_price),
      formatKrw(holding.eval_amount),
      `${formatKrw(holding.pl_amount)} (${holding.pl_pct >= 0 ? "+" : ""}${holding.pl_pct.toFixed(2)}%)`,
    ];
    for (const value of cells) {
      const td = document.createElement("td");
      td.textContent = value;
      row.appendChild(td);
    }

    const sellTd = document.createElement("td");
    const sellButton = document.createElement("button");
    sellButton.type = "button";
    sellButton.textContent = "매도";
    sellButton.classList.add("sell-one-button");
    sellButton.addEventListener("click", () => triggerSellOne(holding.code, holding.name, holding.quantity));
    sellTd.appendChild(sellButton);
    row.appendChild(sellTd);

    row.classList.add(holding.pl_amount >= 0 ? "holding-row-positive" : "holding-row-negative");
    tbody.appendChild(row);
  }
}

async function pollAccountSnapshot() {
  try {
    const res = await fetch("/api/account-snapshot");
    if (!res.ok) return;
    const data = await res.json();
    renderDeposit(data.deposit);
    renderHoldings(data.holdings);
  } catch (err) {
    // 메인 연결경고와 별개로 조용히 재시도.
  }
}

async function triggerSellOne(code, name, quantity) {
  const confirmed = window.confirm(`${name}(${code}) ${quantity}주를 시장가로 매도합니다. 되돌릴 수 없습니다. 진행할까요?`);
  if (!confirmed) return;
  try {
    const res = await fetch(`/api/sell?code=${encodeURIComponent(code)}&quantity=${encodeURIComponent(quantity)}`, { method: "POST" });
    const data = await res.json();
    if (!data.ok) window.alert(`매도 실패: ${data.message}`);
    pollAccountSnapshot();  // 캐시는 sell_order.py가 이미 무효화해둬서 바로 최신 상태를 받아온다
  } catch (err) {
    window.alert("매도 요청이 서버에 도달하지 못했습니다. 계좌 상태를 다시 확인해주세요.");
  }
}

function renderState(state) {
  const pnlBadge = document.getElementById("pnl-badge");
  pnlBadge.textContent = "당일손익: " + formatKrw(state.realized_pnl_krw);
  pnlBadge.classList.toggle("badge-negative", state.realized_pnl_krw < 0);
  pnlBadge.classList.toggle("badge-positive", state.realized_pnl_krw >= 0);

  const killSwitchBadge = document.getElementById("kill-switch-badge");
  if (state.kill_switch_active) {
    killSwitchBadge.textContent = "거래 중단 (kill switch)";
    killSwitchBadge.classList.remove("badge-ok");
    killSwitchBadge.classList.add("badge-danger");
  } else {
    killSwitchBadge.textContent = "정상 운영";
    killSwitchBadge.classList.remove("badge-danger");
    killSwitchBadge.classList.add("badge-ok");
  }

  const tbody = document.getElementById("positions-tbody");
  clearChildren(tbody);
  const positions = state.open_positions || [];
  document.getElementById("positions-empty").classList.toggle("hidden", positions.length > 0);
  document.getElementById("positions-table").classList.toggle("hidden", positions.length === 0);

  for (const pos of positions) {
    const row = document.createElement("tr");
    const cells = [
      pos.code,
      pos.entry_time,
      formatKrw(pos.allocated_capital),
      Math.round((pos.remaining_fraction ?? 1) * 100) + "%",
      formatKrw(pos.entry_price),
    ];
    for (const value of cells) {
      const td = document.createElement("td");
      td.textContent = value;
      row.appendChild(td);
    }
    tbody.appendChild(row);
  }
}

const CONFIG_FIELD_LABELS = [
  ["strategy", "전략"],
  ["model_path", "모델 경로"],
  ["top_n", "top N"],
  ["proba_threshold", "확률 임계값"],
  ["max_concurrent_positions", "동시보유 슬롯"],
  ["total_capital_krw", "총 투자금"],
  ["interval_seconds", "폴링 간격(초)"],
  ["max_daily_loss_krw", "일일손실한도"],
  ["is_mock", "모의투자 여부"],
  ["started_at", "시작시각"],
];

function formatConfigValue(key, value) {
  if (key === "total_capital_krw" || key === "max_daily_loss_krw") return formatKrw(value);
  if (key === "is_mock") return value ? "모의투자" : "실계좌";
  return String(value);
}

function renderConfig(config) {
  const tbody = document.getElementById("config-tbody");
  clearChildren(tbody);
  const entries = CONFIG_FIELD_LABELS.filter(([key]) => config[key] !== undefined);

  document.getElementById("config-empty").classList.toggle("hidden", entries.length > 0);
  document.getElementById("config-table").classList.toggle("hidden", entries.length === 0);

  for (const [key, label] of entries) {
    const row = document.createElement("tr");
    const th = document.createElement("th");
    th.textContent = label;
    const td = document.createElement("td");
    td.textContent = formatConfigValue(key, config[key]);
    row.appendChild(th);
    row.appendChild(td);
    tbody.appendChild(row);
  }
}

function renderStrategyInfoList(elementId, items) {
  const list = document.getElementById(elementId);
  clearChildren(list);
  for (const item of items || []) {
    const li = document.createElement("li");
    li.textContent = item;
    list.appendChild(li);
  }
}

function renderStrategyInfo(info) {
  const hasInfo = Boolean(info && (info.entry || info.exit || info.operation));
  document.getElementById("strategy-info").classList.toggle("hidden", !hasInfo);
  document.getElementById("strategy-info-empty").classList.toggle("hidden", hasInfo);
  renderStrategyInfoList("strategy-info-entry", info.entry);
  renderStrategyInfoList("strategy-info-exit", info.exit);
  renderStrategyInfoList("strategy-info-operation", info.operation);
}

function renderSignals(signals) {
  const tbody = document.getElementById("signals-tbody");
  clearChildren(tbody);
  document.getElementById("signals-empty").classList.toggle("hidden", signals.length > 0);
  document.getElementById("signals-table").classList.toggle("hidden", signals.length === 0);

  for (const signal of signals) {
    const row = document.createElement("tr");
    const cells = [
      signal.stock_code,
      signal.signal_time,
      formatKrw(signal.price),
      signal.proba.toFixed(2),
    ];
    for (const value of cells) {
      const td = document.createElement("td");
      td.textContent = value;
      row.appendChild(td);
    }
    tbody.appendChild(row);
  }
}

function renderOrders(orders) {
  const tbody = document.getElementById("orders-tbody");
  clearChildren(tbody);
  document.getElementById("orders-empty").classList.toggle("hidden", orders.length > 0);
  document.getElementById("orders-table").classList.toggle("hidden", orders.length === 0);

  for (const order of orders) {
    const row = document.createElement("tr");
    const cells = [
      order.code,
      order.side === "buy" ? "매수" : "매도",
      order.quantity,
      formatKrw(order.price),
      order.reason,
      order.order_time,
    ];
    for (const value of cells) {
      const td = document.createElement("td");
      td.textContent = value;
      row.appendChild(td);
    }
    tbody.appendChild(row);
  }
}

let pnlHistoryData = [];
let pnlViewMode = "daily";

function aggregateWeekly(entries) {
  // 일요일 시작 기준으로 주 단위 합산 — 정밀한 ISO 주차 계산 대신 단순 그룹핑으로 충분.
  const weeks = new Map();
  for (const e of entries) {
    const d = new Date(e.date + "T00:00:00");
    const weekStart = new Date(d);
    weekStart.setDate(d.getDate() - d.getDay());
    const key = weekStart.toISOString().slice(0, 10);
    weeks.set(key, (weeks.get(key) || 0) + e.realized_pnl_krw);
  }
  return Array.from(weeks.entries())
    .map(([date, realized_pnl_krw]) => ({ date, realized_pnl_krw }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

function aggregateMonthly(entries) {
  // YYYY-MM 단위로 합산 — 주간 집계와 동일한 패턴, 월 경계만 다르게 자른다.
  const months = new Map();
  for (const e of entries) {
    const key = e.date.slice(0, 7);
    months.set(key, (months.get(key) || 0) + e.realized_pnl_krw);
  }
  return Array.from(months.entries())
    .map(([date, realized_pnl_krw]) => ({ date, realized_pnl_krw }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

function aggregatedPnlEntries() {
  if (pnlViewMode === "weekly") return aggregateWeekly(pnlHistoryData);
  if (pnlViewMode === "monthly") return aggregateMonthly(pnlHistoryData);
  return pnlHistoryData;
}

function renderPnlChart() {
  const entries = aggregatedPnlEntries();
  const canvas = document.getElementById("pnl-chart");
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  document.getElementById("pnl-history-empty").classList.toggle("hidden", entries.length > 0);
  canvas.classList.toggle("hidden", entries.length === 0);
  if (entries.length === 0) return;

  const values = entries.map((e) => e.realized_pnl_krw);
  const maxAbs = Math.max(1, ...values.map((v) => Math.abs(v)));
  const midY = canvas.height / 2;
  const barWidth = canvas.width / entries.length;

  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i];
    const barHeight = (Math.abs(entry.realized_pnl_krw) / maxAbs) * (canvas.height / 2 - 10);
    const x = i * barWidth + barWidth * 0.15;
    const w = barWidth * 0.7;
    ctx.fillStyle = entry.realized_pnl_krw >= 0 ? "#6eb8e7" : "#e76e6e";
    if (entry.realized_pnl_krw >= 0) {
      ctx.fillRect(x, midY - barHeight, w, barHeight);
    } else {
      ctx.fillRect(x, midY, w, barHeight);
    }
  }

  ctx.strokeStyle = "#444";
  ctx.beginPath();
  ctx.moveTo(0, midY);
  ctx.lineTo(canvas.width, midY);
  ctx.stroke();
}

function setPnlViewMode(mode) {
  pnlViewMode = mode;
  document.getElementById("pnl-view-daily-button").classList.toggle("toggle-active", mode === "daily");
  document.getElementById("pnl-view-weekly-button").classList.toggle("toggle-active", mode === "weekly");
  document.getElementById("pnl-view-monthly-button").classList.toggle("toggle-active", mode === "monthly");
  renderPnlChart();
}

function renderKillSwitchOverride(status) {
  const activateButton = document.getElementById("kill-switch-activate-button");
  const clearButton = document.getElementById("kill-switch-clear-button");
  const statusText = document.getElementById("kill-switch-override-status");

  activateButton.classList.toggle("hidden", status.requested);
  clearButton.classList.toggle("hidden", !status.requested);
  statusText.classList.toggle("hidden", !status.requested);
  if (status.requested) {
    const time = status.requested_at ? new Date(status.requested_at).toLocaleTimeString("ko-KR") : "";
    statusText.textContent = `수동 중단 요청됨 (${time})`;
  }
}

async function pollKillSwitchOverrideStatus() {
  try {
    const res = await fetch("/api/kill-switch/status" + strategyQuery());
    if (res.ok) renderKillSwitchOverride(await res.json());
  } catch (err) {
    // 메인 연결경고와 별개로 조용히 재시도.
  }
}

async function triggerKillSwitchActivate() {
  try {
    await fetch("/api/kill-switch/activate" + strategyQuery(), { method: "POST" });
    pollKillSwitchOverrideStatus();
  } catch (err) {
    // 실패해도 다음 상태 폴링에서 자연히 복구됨.
  }
}

async function triggerKillSwitchClear() {
  try {
    await fetch("/api/kill-switch/clear" + strategyQuery(), { method: "POST" });
    pollKillSwitchOverrideStatus();
  } catch (err) {
    // 실패해도 다음 상태 폴링에서 자연히 복구됨.
  }
}

function renderResults(results) {
  const tbody = document.getElementById("results-tbody");
  clearChildren(tbody);
  document.getElementById("results-empty").classList.toggle("hidden", results.length > 0);
  document.getElementById("results-table").classList.toggle("hidden", results.length === 0);

  for (const item of results) {
    const row = document.createElement("tr");
    row.style.cursor = "pointer";
    const cells = [item.filename, item.created_at];
    for (const value of cells) {
      const td = document.createElement("td");
      td.textContent = value;
      row.appendChild(td);
    }
    row.addEventListener("click", () => loadResultDetail(item.filename));
    tbody.appendChild(row);
  }
}

async function loadResultDetail(filename) {
  try {
    const res = await fetch("/api/results/" + encodeURIComponent(filename));
    if (!res.ok) throw new Error("bad response");
    renderResultDetail(await res.json());
  } catch (err) {
    // 상세 조회 실패는 목록 화면 자체에는 영향 주지 않음 — 조용히 무시.
  }
}

function renderResultDetail(detail) {
  const table = document.getElementById("result-detail-table");
  const head = document.getElementById("result-detail-head");
  const tbody = document.getElementById("result-detail-tbody");
  clearChildren(head);
  clearChildren(tbody);

  for (const col of detail.columns) {
    const th = document.createElement("th");
    th.textContent = col;
    head.appendChild(th);
  }
  for (const row of detail.rows) {
    const tr = document.createElement("tr");
    for (const col of detail.columns) {
      const td = document.createElement("td");
      td.textContent = row[col];
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.classList.remove("hidden");
}

function renderTop35Status(status) {
  const button = document.getElementById("top35-update-button");
  const progress = document.getElementById("top35-progress");
  const summary = document.getElementById("top35-summary");
  const error = document.getElementById("top35-error");

  button.disabled = status.status === "running";
  button.textContent = status.status === "running" ? "업데이트 중..." : "top35 업데이트";

  progress.classList.toggle("hidden", status.status !== "running");
  if (status.status === "running") {
    progress.textContent = `${status.processed}/${status.total} 처리중 (현재: ${status.current_code})`;
  }

  summary.classList.toggle("hidden", status.status !== "done");
  if (status.status === "done") {
    summary.textContent = `완료 — 성공 ${status.success_count}종목, 실패 ${status.fail_count}종목`;
  }

  error.classList.toggle("hidden", status.status !== "error");
  if (status.status === "error") {
    error.textContent = "갱신 실패: " + status.error_message;
  }

  renderTop35Results(status.status === "done" ? status.results || [] : []);
}

function renderTop35Results(results) {
  const table = document.getElementById("top35-results-table");
  const tbody = document.getElementById("top35-results-tbody");
  clearChildren(tbody);
  table.classList.toggle("hidden", results.length === 0);

  for (const item of results) {
    const row = document.createElement("tr");
    const isSuccess = item.status === "ok";
    const cells = [item.stock_code, item.name, isSuccess ? "성공" : item.status];
    for (const value of cells) {
      const td = document.createElement("td");
      td.textContent = value;
      row.appendChild(td);
    }
    row.classList.add(isSuccess ? "top35-row-ok" : "top35-row-fail");
    tbody.appendChild(row);
  }
}

async function pollTop35Status() {
  try {
    const res = await fetch("/api/top35-status");
    if (res.ok) renderTop35Status(await res.json());
  } catch (err) {
    // 이 폴링은 메인 연결경고와 별개로 조용히 재시도한다.
  }
}

async function triggerTop35Update() {
  try {
    await fetch("/api/top35-update", { method: "POST" });
    // 409(이미 실행 중)든 200이든, 다음 pollTop35Status()가 실제 상태를 반영한다.
    pollTop35Status();
  } catch (err) {
    // 트리거 요청 자체가 실패해도 버튼은 다음 상태 폴링에서 자연히 복구된다.
  }
}

function renderSellAllStatus(status) {
  const button = document.getElementById("sell-all-button");
  const progress = document.getElementById("sell-all-progress");
  const table = document.getElementById("sell-all-result-table");
  const tbody = document.getElementById("sell-all-result-tbody");

  button.disabled = status.status === "running";
  button.textContent = status.status === "running" ? "매도 중..." : "일괄 매도";
  progress.classList.toggle("hidden", status.status !== "running");

  const hasResults = status.status === "done" && (status.results || []).length > 0;
  const hasError = status.status === "error";
  table.classList.toggle("hidden", !hasResults && !hasError);
  clearChildren(tbody);

  if (hasError) {
    const row = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 4;
    td.textContent = "일괄 매도 실패: " + status.error_message;
    row.appendChild(td);
    row.classList.add("sell-all-row-error");
    tbody.appendChild(row);
    return;
  }

  if (!hasResults) return;
  for (const item of status.results) {
    const row = document.createElement("tr");
    const isOk = item.status === "ok";
    const cells = [item.code, item.name, item.quantity, isOk ? (item.message || "매도완료") : item.message];
    for (const value of cells) {
      const td = document.createElement("td");
      td.textContent = value;
      row.appendChild(td);
    }
    if (!isOk) row.classList.add("sell-all-row-error");
    tbody.appendChild(row);
  }
}

async function pollSellAllStatus() {
  try {
    const res = await fetch("/api/sell-all-status");
    if (res.ok) renderSellAllStatus(await res.json());
  } catch (err) {
    // 이 폴링은 메인 연결경고와 별개로 조용히 재시도한다.
  }
}

async function triggerSellAll() {
  const holdingCount = document.querySelectorAll("#holdings-tbody tr").length;
  const confirmed = window.confirm(
    holdingCount > 0
      ? `보유 중인 ${holdingCount}개 종목을 전부 시장가로 매도합니다. 되돌릴 수 없습니다. 진행할까요?`
      : "보유 종목이 없어 보이지만, 계좌 기준으로 다시 한 번 조회해 매도를 시도합니다. 진행할까요?"
  );
  if (!confirmed) return;
  try {
    await fetch("/api/sell-all", { method: "POST" });
    pollSellAllStatus();
  } catch (err) {
    // 트리거 요청 자체가 실패해도 버튼은 다음 상태 폴링에서 자연히 복구된다.
  }
}

async function pollOnce() {
  try {
    await loadStrategies();
    const q = strategyQuery();
    const [stateRes, configRes, strategyInfoRes, signalsRes, resultsRes, ordersRes, pnlHistoryRes] = await Promise.all([
      fetch("/api/state" + q),
      fetch("/api/config" + q),
      fetch("/api/strategy-info" + q),
      fetch("/api/signals" + q),
      fetch("/api/results"),
      fetch("/api/orders" + q),
      fetch("/api/pnl-history" + q),
    ]);
    if (!stateRes.ok || !configRes.ok || !strategyInfoRes.ok || !signalsRes.ok || !resultsRes.ok || !ordersRes.ok || !pnlHistoryRes.ok) {
      throw new Error("bad response");
    }

    renderState(await stateRes.json());
    renderConfig(await configRes.json());
    renderStrategyInfo(await strategyInfoRes.json());
    renderSignals(await signalsRes.json());
    renderResults(await resultsRes.json());
    renderOrders(await ordersRes.json());
    pnlHistoryData = await pnlHistoryRes.json();
    renderPnlChart();

    document.getElementById("connection-warning").classList.add("hidden");
    document.getElementById("last-updated").textContent =
      "마지막 갱신: " + new Date().toLocaleTimeString("ko-KR");
  } catch (err) {
    // 폴링 실패 시 마지막으로 성공한 화면은 그대로 두고 경고만 표시한다
    // (Design §6.1 — 서버 다운 시 화면을 비우지 않음).
    document.getElementById("connection-warning").classList.remove("hidden");
  }
}

document.getElementById("top35-update-button").addEventListener("click", triggerTop35Update);
document.getElementById("sell-all-button").addEventListener("click", triggerSellAll);
document.getElementById("kill-switch-activate-button").addEventListener("click", triggerKillSwitchActivate);
document.getElementById("kill-switch-clear-button").addEventListener("click", triggerKillSwitchClear);
document.getElementById("pnl-view-daily-button").addEventListener("click", () => setPnlViewMode("daily"));
document.getElementById("pnl-view-weekly-button").addEventListener("click", () => setPnlViewMode("weekly"));
document.getElementById("pnl-view-monthly-button").addEventListener("click", () => setPnlViewMode("monthly"));
document.getElementById("strategy-select").addEventListener("change", (event) => {
  currentStrategy = event.target.value;
  pollOnce();
  pollKillSwitchOverrideStatus();
});

pollOnce();
pollTop35Status();
pollKillSwitchOverrideStatus();
pollMarketSnapshot();
pollAccountSnapshot();
pollSellAllStatus();
pollAllRankings();
setInterval(pollOnce, POLL_INTERVAL_MS);
setInterval(pollTop35Status, TOP35_POLL_INTERVAL_MS);
setInterval(pollKillSwitchOverrideStatus, TOP35_POLL_INTERVAL_MS);
setInterval(pollMarketSnapshot, POLL_INTERVAL_MS);
setInterval(pollAccountSnapshot, POLL_INTERVAL_MS);
setInterval(pollSellAllStatus, TOP35_POLL_INTERVAL_MS);
setInterval(pollAllRankings, POLL_INTERVAL_MS);
