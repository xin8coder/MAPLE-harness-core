"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const colors = { teal: "#087f83", coral: "#f07b61", gray: "#c9d5d9", ink: "#183a43", muted: "#809299" };
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const number = (value, digits = 1) => new Intl.NumberFormat("zh-CN", { maximumFractionDigits: digits }).format(value);
  let data, chart, timer, turnIndex = 0, selectedIndex = 0, view = "front", ticks = 0, playing = !reducedMotion;

  function icon(button, name) {
    const marker = document.createElement("i");
    marker.dataset.lucide = name;
    marker.setAttribute("aria-hidden", "true");
    button.replaceChildren(marker);
    window.lucide?.createIcons();
  }

  function playback(value) {
    playing = value;
    clearInterval(timer);
    const button = $("playback");
    button.setAttribute("aria-pressed", String(!playing));
    button.setAttribute("aria-label", playing ? "暂停回放" : "播放回放");
    button.title = button.getAttribute("aria-label");
    icon(button, playing ? "pause" : "play");
    if (playing && data) timer = setInterval(() => {
      if (document.hidden) return;
      ticks += 1;
      if (ticks % 3 === 0) setTurn((turnIndex + 1) % data.turns.length);
      else { selectedIndex = (selectedIndex + 1) % currentFront().length; render(); }
    }, 4200);
  }

  function currentTurn() { return data.turns[turnIndex]; }
  function currentFront() { return [...currentTurn().front].sort((a, b) => a.objectives[0] - b.objectives[0]); }

  function tooltip(params) {
    const list = Array.isArray(params) ? params : [params];
    const container = document.createElement("div");
    for (const item of list) {
      const row = document.createElement("div");
      row.style.fontSize = "11px";
      const values = Array.isArray(item.value) ? item.value.slice(0, 2).map(value => number(value, 2)).join(" / ") : number(item.value, 2);
      row.textContent = `${item.seriesName}: ${values}`;
      container.appendChild(row);
    }
    return container;
  }

  function axis(name) {
    return {
      type: "value", name, scale: true, nameGap: 15,
      nameTextStyle: { fontSize: 10, color: colors.muted },
      axisLabel: { color: colors.muted, fontSize: 10, hideOverlap: true },
      axisLine: { lineStyle: { color: "#dce5e7" } }, axisTick: { show: false },
      splitLine: { lineStyle: { color: "#f0f3f4", type: "dashed" } },
    };
  }

  function distribution() {
    const turn = currentTurn(), front = currentFront();
    return {
      grid: { left: 60, right: 24, top: 50, bottom: 48 },
      legend: { top: 13, right: 18, itemWidth: 8, itemHeight: 8, textStyle: { color: colors.muted, fontSize: 10 }, data: ["其他可行方案", "帕累托方案", "选中方案"] },
      xAxis: { ...axis("延期惩罚 ↓"), nameLocation: "middle", nameGap: 28, splitNumber: 4 },
      yAxis: { ...axis("能耗与负载 ↓"), splitNumber: 3 },
      tooltip: { trigger: "item", confine: true, formatter: tooltip },
      series: [
        { name: "其他可行方案", type: "scatter", symbolSize: 5, data: turn.population.filter(row => row.feasible).map(row => row.objectives), itemStyle: { color: colors.gray, opacity: 0.7 } },
        { name: "帕累托方案", type: "line", symbol: "circle", symbolSize: 7, data: front.map(row => row.objectives), lineStyle: { width: 1.5, color: colors.teal }, itemStyle: { color: colors.teal }, z: 3 },
        { name: "选中方案", type: "scatter", symbolSize: 13, data: [front[selectedIndex].objectives], itemStyle: { color: colors.coral, borderColor: "#fff", borderWidth: 2, opacity: 1 }, z: 5 },
      ],
    };
  }

  function history() {
    const rows = currentTurn().history;
    return {
      grid: { left: 60, right: 60, top: 54, bottom: 48 },
      legend: { top: 12, itemWidth: 13, itemHeight: 7, textStyle: { color: colors.muted, fontSize: 10 }, data: ["延期惩罚（最优）", "能耗与负载（最优）"] },
      xAxis: { type: "category", data: rows.map(row => row.generation), name: "迭代代数", nameLocation: "middle", nameGap: 28, axisLabel: { color: colors.muted, fontSize: 10 }, axisLine: { lineStyle: { color: "#dce5e7" } }, axisTick: { show: false } },
      yAxis: [{ ...axis("延期惩罚"), splitNumber: 3 }, { ...axis("能耗与负载"), splitNumber: 3, splitLine: { show: false } }],
      tooltip: { trigger: "axis", confine: true, formatter: tooltip },
      series: [
        { name: "延期惩罚（最优）", type: "line", data: rows.map(row => row.min_f1), yAxisIndex: 0, symbolSize: 4, lineStyle: { color: colors.teal, width: 2 }, itemStyle: { color: colors.teal } },
        { name: "能耗与负载（最优）", type: "line", data: rows.map(row => row.min_f2), yAxisIndex: 1, symbolSize: 4, lineStyle: { color: colors.coral, width: 2 }, itemStyle: { color: colors.coral } },
      ],
    };
  }

  function schedule(plan) {
    const container = $("schedule");
    container.replaceChildren();
    const caption = document.createElement("p");
    caption.className = "schedule-caption";
    caption.textContent = "各机台的任务加工顺序";
    container.appendChild(caption);
    for (const [machine, jobs] of Object.entries(plan.sequences).sort()) {
      const row = document.createElement("div");
      row.className = "machine-row";
      const label = document.createElement("span");
      label.className = "machine-name";
      label.textContent = machine.toUpperCase();
      const sequence = document.createElement("div");
      sequence.className = "job-sequence";
      for (const job of jobs) {
        const item = document.createElement("span");
        item.className = "job";
        item.textContent = job;
        sequence.appendChild(item);
      }
      row.append(label, sequence);
      container.appendChild(row);
    }
  }

  function render() {
    const turn = currentTurn(), front = currentFront(), plan = front[selectedIndex];
    $("selected-plan").textContent = `方案 ${String(selectedIndex + 1).padStart(2, "0")}`;
    $("selected-f1").textContent = number(plan.objectives[0], 2);
    $("selected-f2").textContent = number(plan.objectives[1], 2);
    $("front-count").textContent = `${front.length} 个帕累托方案`;
    $("generation-count").textContent = `${turn.generations} 代迭代`;
    $("restart-label").textContent = turnIndex ? `热启动 · 复用 ${turn.restart.reused} 个候选解` : "类型化初始化";
    $("request-text").textContent = turn.request_summary;
    for (const button of document.querySelectorAll("[data-turn]")) button.setAttribute("aria-pressed", String(Number(button.dataset.turn) === turnIndex));
    for (const button of document.querySelectorAll("[data-view]")) {
      const active = button.dataset.view === view;
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
    }
    $("result-panel").setAttribute("aria-labelledby", `tab-${view}`);
    $("result-chart").hidden = view === "schedule";
    $("schedule").hidden = view !== "schedule";
    if (view === "schedule") schedule(plan);
    else {
      chart.resize();
      chart.setOption({ animation: !reducedMotion, animationDuration: 500, animationDurationUpdate: 500,
        textStyle: { fontFamily: "sans-serif" }, ... (view === "history" ? history() : distribution()) }, true);
      $("result-chart").setAttribute("aria-label", view === "history" ? "两个目标的历史最优值随迭代代数变化" : "候选方案与帕累托方案分布");
    }
  }

  function setTurn(value) {
    turnIndex = value;
    selectedIndex = Math.floor(currentFront().length / 2);
    render();
  }

  for (const button of document.querySelectorAll("[data-turn]")) button.addEventListener("click", () => {
    if (!data) return;
    playback(false); setTurn(Number(button.dataset.turn));
  });
  for (const button of document.querySelectorAll("[data-view]")) {
    button.addEventListener("click", () => { if (data) { playback(false); view = button.dataset.view; render(); } });
    button.addEventListener("keydown", event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const tabs = Array.from(document.querySelectorAll("[data-view]"));
      const current = tabs.indexOf(button);
      const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      tabs[next].focus(); tabs[next].click();
    });
  }
  $("playback").addEventListener("click", () => playback(!playing));
  $("toggle-password").addEventListener("click", () => {
    const visible = $("password").type === "password";
    $("password").type = visible ? "text" : "password";
    const button = $("toggle-password");
    button.setAttribute("aria-pressed", String(visible));
    button.setAttribute("aria-label", visible ? "隐藏密码" : "显示密码");
    button.title = button.getAttribute("aria-label");
    icon(button, visible ? "eye-off" : "eye");
  });
  $("login-form").addEventListener("focusin", () => playback(false));
  $("login-form").addEventListener("submit", () => {
    const button = $("login-submit");
    button.disabled = true;
    button.querySelector("span").textContent = "正在登录…";
  });
  window.addEventListener("pageshow", () => {
    $("login-submit").disabled = false;
    $("login-submit").querySelector("span").textContent = "登录并进入工作台";
  });
  window.addEventListener("pagehide", () => clearInterval(timer));
  window.lucide?.createIcons();

  fetch("/maple-login/assets/case-demo.json?v=0.2.4").then(response => {
    if (!response.ok) throw new Error("Demo unavailable");
    return response.json();
  }).then(value => {
    if (!value.turns?.length || value.turns.some(turn => !turn.front?.length)) throw new Error("Empty demo");
    data = value;
    chart = window.echarts.init($("result-chart"), null, { renderer: "canvas" });
    chart.on("click", event => {
      if (view !== "front" || event.seriesName !== "帕累托方案") return;
      playback(false); selectedIndex = event.dataIndex; render();
    });
    new ResizeObserver(() => chart.resize()).observe($("result-chart"));
    setTurn(0); playback(playing);
  }).catch(() => {
    playback(false);
    $("chart-error").hidden = false;
    $("playback").disabled = true;
  });
})();
