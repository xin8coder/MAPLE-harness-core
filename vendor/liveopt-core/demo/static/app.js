/* LiveOpt chat demo — no build step, no external dependencies. */

const $ = (id) => document.getElementById(id);

let chats = [];
let currentChatId = null;
let currentMessages = [];
let busy = false;
let busyStarted = 0;
let statusTimer = null;
let viewMode = "normal";
let globalSettings = loadGlobalSettings();

/* ---------------- helpers ---------------- */

function loadGlobalSettings() {
  try { return JSON.parse(localStorage.getItem("liveopt_settings") || "{}"); }
  catch { return {}; }
}

function saveGlobalSettings() {
  const redacted = { ...globalSettings };
  delete redacted.api_key; // never persist keys, even to localStorage
  localStorage.setItem("liveopt_settings", JSON.stringify(redacted));
}

async function api(path, options) {
  const response = await fetch(path, options);
  const text = await response.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = { detail: text }; }
  if (!response.ok) {
    const detail = body && body.detail ? body.detail : response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text);
  return div.innerHTML;
}

function fmt(value) {
  if (value === null || value === undefined) return "-";
  const number = Number(value);
  return Number.isFinite(number)
    ? (Math.abs(number) >= 1000 ? number.toFixed(0) : Math.abs(number) >= 100 ? number.toFixed(1) : number.toPrecision(4))
    : String(value);
}

/* Tiny markdown: fenced code, inline code, bold, italic, headings, lists. */
function renderMarkdown(text) {
  const escaped = escapeHtml(String(text || ""));
  const blocks = escaped.split(/```(\w*)\n?([\s\S]*?)(?:```|$)/g);
  let html = "";
  for (let i = 0; i < blocks.length; i++) {
    if (i % 3 === 0) html += inlineMarkdown(blocks[i]);
    else if (i % 3 === 2) html += "<pre><code>" + blocks[i].replace(/\n$/, "") + "</code></pre>";
  }
  return html;
}

function inlineMarkdown(text) {
  let html = text
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|\W)\*([^*\n]+)\*/g, "$1<em>$2</em>");
  const lines = html.split("\n");
  const out = [];
  let inList = false;
  for (const line of lines) {
    const trimmed = line.trim();
    if (/^#{1,4}\s/.test(trimmed)) {
      if (inList) { out.push("</ul>"); inList = false; }
      out.push("<p><strong>" + trimmed.replace(/^#+\s*/, "") + "</strong></p>");
    } else if (/^[-*]\s+/.test(trimmed)) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push("<li>" + trimmed.replace(/^[-*]\s+/, "") + "</li>");
    } else {
      if (inList) { out.push("</ul>"); inList = false; }
      if (trimmed) out.push("<p>" + line + "</p>");
    }
  }
  if (inList) out.push("</ul>");
  return out.join("");
}

/* ---------------- chat list ---------------- */

async function refreshChatList() {
  const data = await api("/api/chats");
  chats = data.chats;
  const wrap = $("chat_list");
  wrap.innerHTML = "";
  for (const chat of chats) {
    const item = document.createElement("div");
    item.className = "chat-item" + (chat.chat_id === currentChatId ? " active" : "");
    const dot = chat.has_optimization ? '<span class="chat-dot">◆</span>' : "";
    item.innerHTML = `${dot}<span class="chat-title">${escapeHtml(chat.title)}</span>`;
    const del = document.createElement("button");
    del.className = "chat-del";
    del.title = "Delete chat";
    del.textContent = "✕";
    del.onclick = async (event) => {
      event.stopPropagation();
      await api(`/api/chats/${chat.chat_id}`, { method: "DELETE" });
      if (currentChatId === chat.chat_id) { currentChatId = null; currentMessages = []; renderMessages(); }
      refreshChatList();
    };
    item.appendChild(del);
    item.onclick = () => selectChat(chat.chat_id);
    wrap.appendChild(item);
  }
}

async function selectChat(chatId) {
  currentChatId = chatId;
  const data = await api(`/api/chats/${chatId}`);
  currentMessages = data.messages || [];
  $("chat_title").textContent = data.chat.title;
  $("model_badge").textContent = (data.settings && (data.settings.model || data.settings.provider)) || "default model";
  $("reinit_banner").classList.toggle("hidden", !data.chat.needs_reinit);
  setViewButtons((data.settings && data.settings.view_mode) || "normal");
  renderMessages();
  refreshChatList();
}

function setViewButtons(mode) {
  viewMode = mode === "professional" ? "professional" : "normal";
  $("view_normal").classList.toggle("active", viewMode === "normal");
  $("view_pro").classList.toggle("active", viewMode === "professional");
}

async function switchView(mode) {
  setViewButtons(mode);
  if (!currentChatId) return;
  await api(`/api/chats/${currentChatId}/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ settings: { view_mode: viewMode } }),
  });
  await selectChat(currentChatId); // server filters cards per view; re-render
}

async function newChat() {
  const data = await api("/api/chats", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ settings: globalSettings }),
  });
  await refreshChatList();
  selectChat(data.chat.chat_id);
}

/* ---------------- message rendering ---------------- */

function renderMessages() {
  const wrap = $("messages");
  wrap.innerHTML = "";
  if (!currentChatId) {
    wrap.innerHTML = '<div class="msg-row assistant"><div class="bubble">Start a new chat on the left, then just talk. Describe an optimization problem (or use ＋ to attach data) and I will build a LiveOpt Workbench for it; send natural-language updates afterwards.</div></div>';
    return;
  }
  for (const message of currentMessages) appendMessage(message);
  scrollToBottom();
}

function appendMessage(message) {
  const wrap = $("messages");
  const row = document.createElement("div");
  row.className = "msg-row " + (message.role === "user" ? "user" : "assistant");
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML = renderMarkdown(message.content || "");
  if (message.role === "user" && message.kind === "optimization" && message.optimization) {
    const tag = document.createElement("div");
    tag.className = "opt-payload";
    tag.textContent = "⚙ optimization request: " + (message.optimization.mode || "builtin") +
      (message.optimization.episode_id ? " · " + message.optimization.episode_id : "");
    bubble.appendChild(tag);
  }
  row.appendChild(bubble);
  wrap.appendChild(row);
  if (message.cards && message.cards.length) {
    const cardRow = document.createElement("div");
    cardRow.className = "msg-row assistant";
    const cardWrap = document.createElement("div");
    cardWrap.className = "cards";
    for (const card of message.cards) cardWrap.appendChild(renderCard(card));
    cardRow.appendChild(cardWrap);
    wrap.appendChild(cardRow);
  }
}

function scrollToBottom() {
  const wrap = $("messages");
  wrap.scrollTop = wrap.scrollHeight;
}

/* ---------------- artifact cards ---------------- */

function renderCard(card) {
  const el = document.createElement("div");
  const expanded = card.type === "image" || card.type === "episode_preview";
  el.className = "card" + (expanded ? "" : " collapsed");
  const header = document.createElement("div");
  header.className = "card-header";
  header.innerHTML = `<span>${cardIcon(card.type)} ${escapeHtml(card.title || card.type)}</span><span class="caret">${expanded ? "▾" : "▸"}</span>`;
  const body = document.createElement("div");
  body.className = "card-body";
  header.onclick = () => {
    el.classList.toggle("collapsed");
    header.querySelector(".caret").textContent = el.classList.contains("collapsed") ? "▸" : "▾";
    if (!el.classList.contains("collapsed") && card.type === "pareto") drawPareto(body, card.data);
  };
  el.appendChild(header);
  el.appendChild(body);
  buildCardBody(card.type, body, card.data || {});
  return el;
}

function cardIcon(type) {
  return { state: "◎", workbench: "⚒", pareto: "∴", restart: "↻", ledger: "☰", localization: "⌖", image: "🖼", episode_preview: "⧉", error: "⚠" }[type] || "▣";
}

function buildCardBody(type, body, data) {
  if (type === "image") {
    body.innerHTML = "";
    const img = document.createElement("img");
    img.className = "card-image";
    img.src = data.image || "";
    img.alt = data.caption || "result image";
    body.appendChild(img);
    if (data.caption) body.insertAdjacentHTML("beforeend", `<p class="muted">${escapeHtml(data.caption)}</p>`);
  } else if (type === "error") {
    body.innerHTML = "";
    const div = document.createElement("div");
    div.className = "card-error";
    div.textContent = data.error || "unknown error";
    body.appendChild(div);
  } else if (type === "episode_preview") {
    body.innerHTML = "";
    const tables = data.tables || {};
    for (const [name, meta] of Object.entries(tables)) {
      const div = document.createElement("div");
      div.className = "preview-table";
      div.innerHTML = `<strong>${escapeHtml(name)}</strong> · ${meta.rows} rows · <code>${escapeHtml((meta.columns || []).join(", "))}</code>`;
      body.appendChild(div);
    }
    const objective = data.objective || {};
    body.insertAdjacentHTML("beforeend",
      `<p><strong>Objective:</strong> ${escapeHtml(objective.objective_sense || "")} ${escapeHtml((objective.objective_names || []).join(", "))}` +
      (objective.scalar_formula ? ` · <code>${escapeHtml(objective.scalar_formula)}</code>` : "") + `</p>`);
    body.insertAdjacentHTML("beforeend", `<p class="muted">${escapeHtml((data.problem || "").slice(0, 600))}</p>`);
    const btn = document.createElement("button");
    btn.className = "confirm-btn";
    btn.textContent = "Confirm & start optimization";
    btn.onclick = () => {
      btn.disabled = true;
      confirmImportedEpisode(data.episode_payload);
    };
    body.appendChild(btn);
  } else if (type === "localization") {
    body.innerHTML = "";
    for (const [label, flag] of [["DATA", data.data_update], ["SETUP.PY", data.patch_setup], ["FITNESS.PY", data.patch_fitness]]) {
      const chip = document.createElement("span");
      chip.className = "chip " + (flag ? "chip-on" : "chip-off");
      chip.textContent = label + (flag ? " changed" : " unchanged");
      body.appendChild(chip);
    }
    if (data.reason) body.insertAdjacentHTML("beforeend", `<p class="muted">${escapeHtml(data.reason)}</p>`);
  } else if (type === "restart") {
    const full = (data.restart_skill || "").includes("full");
    body.innerHTML = `<span class="badge ${full ? "badge-full" : "badge-warm"}">${full ? "FULL" : "WARM"}</span>` +
      `<code>${escapeHtml(data.restart_skill || "")}</code>` +
      `<p class="muted">${escapeHtml(data.reason || "")}</p>` +
      (data.seed_count !== undefined ? `<p class="muted">history seeds: ${data.seed_count}</p>` : "");
  } else if (type === "state") {
    const best = data.best || {};
    body.innerHTML = `<p>scalar <strong>${fmt(best.scalar)}</strong> · feasible <strong>${best.feasible}</strong>` +
      (data.objective_names && data.objective_names.length ? ` · objectives: ${escapeHtml(data.objective_names.join(", "))}` : "") + `</p>`;
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(best.solution || best, null, 2);
    body.appendChild(pre);
  } else if (type === "workbench") {
    body.innerHTML = "";
    for (const slot of ["setup.py", "fitness.py"]) {
      const h = document.createElement("h4");
      const changed = (data.changed || []).includes(slot);
      h.textContent = slot + (changed ? " (patched this turn)" : "");
      body.appendChild(h);
      const diff = (data.diffs || {})[slot];
      if (changed && diff) {
        const pre = document.createElement("pre");
        for (const line of diff.split("\n")) {
          const span = document.createElement("span");
          span.className = "diff-line" +
            (line.startsWith("+") && !line.startsWith("+++") ? " diff-add"
            : line.startsWith("-") && !line.startsWith("---") ? " diff-del"
            : line.startsWith("@@") ? " diff-hunk" : "");
          span.textContent = line;
          pre.appendChild(span);
        }
        body.appendChild(pre);
      } else {
        const pre = document.createElement("pre");
        pre.textContent = data[slot] || "(empty)";
        body.appendChild(pre);
      }
    }
  } else if (type === "pareto") {
    body.innerHTML = '<canvas class="pareto-canvas" width="520" height="340"></canvas><p class="muted pareto-msg"></p>';
  } else if (type === "ledger") {
    body.innerHTML = "";
    const entries = data.entries || [];
    if (!entries.length) body.innerHTML = '<p class="muted">No events yet.</p>';
    entries.forEach((entry, index) => {
      const div = document.createElement("div");
      div.className = "ledger-entry";
      div.innerHTML = `<strong>#${index + 1} ${escapeHtml(entry.update_id || "")}</strong> ${escapeHtml(entry.natural_language_update || "")}` +
        `<span class="muted">patch: ${escapeHtml(JSON.stringify(entry.public_data_patch || {}))}</span>`;
      body.appendChild(div);
    });
  } else {
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(data, null, 2);
    body.appendChild(pre);
  }
}

function drawPareto(body, data) {
  const canvas = body.querySelector("canvas");
  const msg = body.querySelector(".pareto-msg");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const points = (data.points || []).filter((p) => Array.isArray(p.objectives) && p.objectives.length >= 2);
  if (!points.length) {
    canvas.style.display = "none";
    msg.textContent = (data.points || []).length
      ? "Accepted set has " + ((data.points[0].objectives || []).length) + " objective(s); scatter view needs exactly 2."
      : "No archive points yet.";
    return;
  }
  canvas.style.display = "block";
  const names = data.objective_names || [];
  msg.textContent = (names.length >= 2 ? names[0] + " vs " + names[1] : "objective 0 vs objective 1") + ` · ${points.length} points`;
  const xs = points.map((p) => p.objectives[0]);
  const ys = points.map((p) => p.objectives[1]);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const yMin = Math.min(...ys), yMax = Math.max(...ys);
  const pad = 38;
  const sx = (x) => pad + (xMax > xMin ? (x - xMin) / (xMax - xMin) : 0.5) * (canvas.width - 2 * pad);
  const sy = (y) => canvas.height - pad - (yMax > yMin ? (y - yMin) / (yMax - yMin) : 0.5) * (canvas.height - 2 * pad);
  ctx.strokeStyle = "#c8cdd5";
  ctx.strokeRect(pad, pad, canvas.width - 2 * pad, canvas.height - 2 * pad);
  ctx.fillStyle = "#6b7686";
  ctx.font = "11px sans-serif";
  ctx.fillText(fmt(xMin), pad, canvas.height - pad + 14);
  ctx.fillText(fmt(xMax), canvas.width - pad - 26, canvas.height - pad + 14);
  ctx.fillText(fmt(yMax), 4, pad + 4);
  ctx.fillText(fmt(yMin), 4, canvas.height - pad);
  ctx.fillStyle = "#2a9d9f";
  for (const p of points) {
    ctx.beginPath();
    ctx.arc(sx(p.objectives[0]), sy(p.objectives[1]), 4, 0, 2 * Math.PI);
    ctx.fill();
  }
}

/* ---------------- sending ---------------- */

function setBusy(flag) {
  busy = flag;
  $("send_btn").disabled = flag;
  if (flag) {
    busyStarted = Date.now();
    showTyping();
    statusTimer = setInterval(pollStatus, 1000);
  } else {
    hideTyping();
    if (statusTimer) { clearInterval(statusTimer); statusTimer = null; }
  }
}

function showTyping() {
  hideTyping();
  const wrap = $("messages");
  const row = document.createElement("div");
  row.className = "msg-row assistant";
  row.id = "typing_row";
  row.innerHTML = '<div class="bubble"><span class="typing"><span></span><span></span><span></span></span> <span class="muted" id="typing_elapsed"></span></div>';
  wrap.appendChild(row);
  scrollToBottom();
}

function hideTyping() {
  const row = $("typing_row");
  if (row) row.remove();
}

async function pollStatus() {
  if (!currentChatId) return;
  try {
    const status = await api(`/api/chats/${currentChatId}/status`);
    const el = $("typing_elapsed");
    if (el && status.busy) el.textContent = Math.round((Date.now() - busyStarted) / 1000) + "s";
  } catch { /* transient */ }
}

async function ensureChat() {
  if (currentChatId) return;
  await newChat();
}

async function sendCurrentText() {
  const text = $("input").value.trim();
  if (!text || busy) return;
  await ensureChat();
  $("input").value = "";
  autoGrow();
  appendMessage({ role: "user", content: text, kind: "text" });
  scrollToBottom();
  setBusy(true);
  try {
    const data = await api(`/api/chats/${currentChatId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    currentMessages.push({ role: "user", content: text, kind: "text" });
    currentMessages.push(data.message);
    setBusy(false);
    renderMessages();
    refreshChatList();
  } catch (err) {
    setBusy(false);
    appendMessage({ role: "assistant", content: "⚠ " + err.message, kind: "text" });
    scrollToBottom();
  }
}

/* ---------------- start-optimization modal ---------------- */

let optMode = "builtin";

function openOptModal() {
  $("opt_modal").classList.remove("hidden");
}

function closeOptModal() {
  $("opt_modal").classList.add("hidden");
}

function addTableEditor(name, csvText) {
  const wrap = document.createElement("div");
  wrap.className = "table-editor";
  wrap.innerHTML = `<input class="table-name" value="${name || ""}" placeholder="table name (e.g. items)" />` +
    `<textarea class="table-csv" rows="3">${csvText || ""}</textarea>`;
  $("opt_tables").appendChild(wrap);
}

function readFileText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

async function submitOptimization() {
  if (optMode === "import") {
    await submitImport();
    return;
  }
  const optimization = { mode: optMode };
  if (optMode === "builtin") {
    optimization.episode_id = $("opt_episode_id").value;
    if (!optimization.episode_id) return;
  } else if (optMode === "upload") {
    const jsonFile = $("opt_json_file").files[0];
    if (!jsonFile) return;
    optimization.episode_payload = JSON.parse(await readFileText(jsonFile));
    optimization.csv_files = {};
    for (const file of $("opt_csv_files").files) optimization.csv_files[file.name] = await readFileText(file);
  } else {
    optimization.problem = $("opt_problem").value.trim();
    if (!optimization.problem) return;
    optimization.tables = {};
    for (const editor of document.querySelectorAll("#opt_tables .table-editor")) {
      const name = editor.querySelector(".table-name").value.trim();
      if (name) optimization.tables[name] = editor.querySelector(".table-csv").value;
    }
  }
  closeOptModal();
  await ensureChat();
  const label = optMode === "builtin" ? "Start optimization: " + optimization.episode_id
    : optMode === "upload" ? "Start optimization from uploaded episode"
    : "Start optimization: " + optimization.problem.slice(0, 90);
  appendMessage({ role: "user", content: label, kind: "optimization", optimization });
  scrollToBottom();
  setBusy(true);
  try {
    const data = await api(`/api/chats/${currentChatId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: label, optimization }),
    });
    currentMessages.push({ role: "user", content: label, kind: "optimization", optimization });
    currentMessages.push(data.message);
    setBusy(false);
    renderMessages();
    refreshChatList();
  } catch (err) {
    setBusy(false);
    appendMessage({ role: "assistant", content: "⚠ " + err.message, kind: "text" });
    scrollToBottom();
  }
}

async function submitImport() {
  const goal = $("import_goal").value.trim();
  const pasted = $("import_pasted").value;
  const files = {};
  for (const file of $("import_files").files) files[file.name] = await readFileText(file);
  if (!goal || (!Object.keys(files).length && !pasted.trim())) return;
  closeOptModal();
  await ensureChat();
  const label = "Import data: " + goal.slice(0, 110);
  appendMessage({ role: "user", content: label, kind: "import" });
  scrollToBottom();
  setBusy(true);
  try {
    const data = await api(`/api/chats/${currentChatId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: label, import_data: { goal, files, pasted_text: pasted } }),
    });
    currentMessages.push({ role: "user", content: label, kind: "import" });
    currentMessages.push(data.message);
    setBusy(false);
    renderMessages();
    refreshChatList();
  } catch (err) {
    setBusy(false);
    appendMessage({ role: "assistant", content: "⚠ " + err.message, kind: "text" });
    scrollToBottom();
  }
}

async function confirmImportedEpisode(episodePayload) {
  if (!episodePayload || busy) return;
  await ensureChat();
  const label = "Start optimization: " + (episodePayload.episode_id || "imported episode");
  appendMessage({ role: "user", content: label, kind: "optimization", optimization: { mode: "imported" } });
  scrollToBottom();
  setBusy(true);
  try {
    const data = await api(`/api/chats/${currentChatId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: label, optimization: { mode: "imported", episode_payload: episodePayload } }),
    });
    currentMessages.push({ role: "user", content: label, kind: "optimization", optimization: { mode: "imported" } });
    currentMessages.push(data.message);
    setBusy(false);
    renderMessages();
    refreshChatList();
  } catch (err) {
    setBusy(false);
    appendMessage({ role: "assistant", content: "⚠ " + err.message, kind: "text" });
    scrollToBottom();
  }
}

/* ---------------- settings modal ---------------- */

function openSettings() {
  $("set_provider").value = globalSettings.provider || "kimi";
  $("set_model").value = globalSettings.model || "";
  $("set_api_key").value = globalSettings.api_key || "";
  $("set_base_url").value = globalSettings.base_url || "";
  $("set_population").value = globalSettings.population_size || 50;
  $("set_generations").value = globalSettings.generations || 50;
  $("settings_modal").classList.remove("hidden");
}

async function saveSettings() {
  globalSettings = {
    provider: $("set_provider").value,
    model: $("set_model").value.trim(),
    api_key: $("set_api_key").value,
    base_url: $("set_base_url").value.trim(),
    population_size: parseInt($("set_population").value, 10) || 50,
    generations: parseInt($("set_generations").value, 10) || 50,
  };
  saveGlobalSettings();
  if (currentChatId) {
    await api(`/api/chats/${currentChatId}/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ settings: globalSettings }),
    });
  }
  $("settings_modal").classList.add("hidden");
}

/* ---------------- composer ---------------- */

function autoGrow() {
  const el = $("input");
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 180) + "px";
}

/* ---------------- boot ---------------- */

async function boot() {
  document.querySelectorAll(".opt-tab").forEach((btn) => {
    btn.onclick = () => {
      optMode = btn.dataset.mode;
      document.querySelectorAll(".opt-tab").forEach((b) => b.classList.toggle("active", b === btn));
      for (const mode of ["builtin", "upload", "freeform", "import"]) {
        $("opt_" + mode).classList.toggle("hidden", mode !== optMode);
      }
      $("opt_start").textContent = optMode === "import" ? "Convert & preview" : "Start";
    };
  });
  $("new_chat_btn").onclick = newChat;
  $("view_normal").onclick = () => switchView("normal");
  $("view_pro").onclick = () => switchView("professional");
  $("settings_btn").onclick = openSettings;
  $("settings_cancel").onclick = () => $("settings_modal").classList.add("hidden");
  $("settings_save").onclick = saveSettings;
  $("plus_btn").onclick = openOptModal;
  $("opt_cancel").onclick = closeOptModal;
  $("opt_start").onclick = submitOptimization;
  $("opt_add_table").onclick = () => addTableEditor();
  $("reinit_btn").onclick = async () => {
    if (!currentChatId) return;
    setBusy(true);
    try {
      const data = await api(`/api/chats/${currentChatId}/optimization/restart`, { method: "POST" });
      currentMessages.push(data.message);
      $("reinit_banner").classList.add("hidden");
      setBusy(false);
      renderMessages();
    } catch (err) {
      setBusy(false);
      appendMessage({ role: "assistant", content: "⚠ " + err.message, kind: "text" });
      scrollToBottom();
    }
  };
  $("input").addEventListener("input", autoGrow);
  $("input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendCurrentText();
    }
  });
  $("send_btn").onclick = sendCurrentText;
  addTableEditor("items", "id,value,weight\nI1,10,4\nI2,8,5\nI3,6,3\n");
  addTableEditor("constraints", "capacity,objective_mode\n8,maximize_value\n");

  try {
    const episodes = await api("/api/episodes");
    const select = $("opt_episode_id");
    for (const ep of episodes.episodes) {
      const option = document.createElement("option");
      option.value = ep.episode_id;
      option.textContent = `${ep.episode_id} (${ep.domain}/${ep.family})`;
      select.appendChild(option);
    }
  } catch { /* episode list is best-effort */ }

  await refreshChatList();
  if (chats.length) selectChat(chats[0].chat_id);
  else renderMessages();
}

boot();
