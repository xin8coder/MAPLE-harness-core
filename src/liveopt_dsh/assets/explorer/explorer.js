"use strict";
const $ = (id) => document.getElementById(id);
const query = new URLSearchParams(location.search);
const base = location.pathname.includes("/liveopt-api/") ? "/liveopt-api" : "";
let language = query.get("lang") === "en" ? "en" : "zh";
const words = {
  explorer: ["方案选择", "Solution explorer"],
  turn: ["优化批次", "Optimization turn"],
  refresh: ["刷新", "Refresh"],
  reset: ["重置视图", "Reset view"],
  request: ["本轮需求", "Current requirement"],
  retained: ["已保存方案", "Retained candidates"],
  feasible: ["可行方案", "Feasible"],
  pareto: ["帕累托方案", "Pareto"],
  preference: ["已保存偏好", "Saved preference"],
  distribution: ["方案分布", "Objective space"],
  x: ["横轴", "X axis"],
  y: ["纵轴", "Y axis"],
  other: ["其他可行方案", "Other feasible"],
  infeasible: ["不可行方案", "Infeasible"],
  selected: ["当前选中", "Selected"],
  candidates: ["候选方案", "Candidates"],
  search: ["搜索方案或明细", "Search candidates"],
  onlyPareto: ["仅帕累托", "Pareto only"],
  exportAll: ["导出全部方案 CSV", "Export all candidates CSV"],
  exportSelected: ["导出所选方案 JSON", "Export selected JSON"],
  previous: ["上一页", "Previous"],
  next: ["下一页", "Next"],
  detail: ["方案详情", "Selected plan"],
  choose: ["选择一个方案", "Select a candidate"],
  save: ["保存为偏好方案", "Save preference"],
  saved: [
    "已保存，不改变优化器历史状态。",
    "Saved independently of optimizer history.",
  ],
  saving: ["保存中…", "Saving…"],
  scope: [
    "展示本轮保留的最终种群与归档，不包含搜索中已丢弃的候选解。",
    "Retained final population and archive, not candidates discarded during search.",
  ],
  saveScope: [
    "偏好单独保存，不改变求解状态。",
    "Preferences do not change the solver state.",
  ],
  partial: [
    "此历史批次只保留了部分归档，最终种群不可用。",
    "This historical turn retains only an archive; the population is unavailable.",
  ],
  demo: [
    "模拟业务数据 · 本地数值求解演示，未调用语言模型",
    "Simulated business data · local numerical demo, no language-model calls",
  ],
  demoLive: [
    "模拟业务数据 · DeepSeek Flash 真实生成与求解",
    "Simulated business data · generated and solved with DeepSeek Flash",
  ],
  validationFailed: [
    "这批结果未通过业务规则核验，不能保存为偏好方案。",
    "These results failed business-rule validation and cannot be saved as preferences.",
  ],
  empty: ["本轮没有保留候选方案。", "No candidates retained for this turn."],
  missing: [
    "链接缺少会话编号。请从对话结果或“方案”打开。",
    "No session in the link. Open this window from a result or Solutions.",
  ],
  id: ["方案", "Plan"],
  status: ["状态", "Status"],
  index: ["方案序号", "Candidate index"],
  lower: ["越低越好", "Lower is better"],
  min: ["最小", "Min"],
  max: ["最大", "Max"],
  paretoExplanation: [
    "在本轮已保存的可行方案中，没有另一个方案在所有目标上都不差且至少一个目标更好。",
    "No retained feasible candidate is at least as good on every objective and better on one.",
  ],
  dominated: [
    "本轮存在同时不差且至少一个目标更好的可行方案。",
    "Another retained feasible plan is at least as good on every objective and better on one.",
  ],
  invalidExplanation: [
    "该方案违反约束，不能保存为偏好方案。",
    "This candidate violates constraints and cannot be saved as a preference.",
  ],
  near: [
    "相对本轮可行方案中的最低值",
    "Above the lowest retained feasible value",
  ],
  solution: ["方案明细", "Plan details"],
  genome: ["编码与约束", "Encoding and constraints"],
  noSolution: [
    "该记录没有保留业务方案明细。",
    "No decoded plan details were retained.",
  ],
  execution: ["所选方案执行安排", "Selected execution plan"],
  arrival_hour: ["到港（小时）", "Port arrival (h)"],
  hours: ["时间（小时）", "Time (hours)"],
  usedCapacity: ["仓区箱位占用", "Warehouse usage"],
  remaining: ["剩余箱位", "Remaining capacity"],
  cost_cny: ["总成本（元）", "Total cost (CNY)"],
  late_carton_hours: ["逾期箱小时", "Late carton-hours"],
  overtime_worker_hours: ["加班工时", "Overtime worker-hours"],
  order_plan: ["订单安排", "Order plan"],
  worker_shifts: ["工人排班", "Worker shifts"],
  warehouse_plan: ["仓储安排", "Warehouse plan"],
  order_id: ["订单", "Order"],
  customer: ["客户", "Customer"],
  team: ["班组", "Team"],
  warehouse: ["仓区", "Warehouse"],
  start_hour: ["开始（小时）", "Start (h)"],
  finish_hour: ["完成（小时）", "Finish (h)"],
  due_hour: ["截单（小时）", "Cut-off (h)"],
  late_hours: ["逾期（小时）", "Late (h)"],
  cartons: ["箱数", "Cartons"],
  overtime_hours: ["加班（小时）", "Overtime (h)"],
  workers: ["人数", "Workers"],
  capacity: ["容量", "Capacity"],
  used: ["占用", "Used"],
  shift: ["班次", "Shift"],
  total_cost_cny: ["总成本（元）", "Total cost (CNY)"],
  total_cost: ["总成本", "Total cost"],
  overdue_carton_hours: ["逾期箱小时", "Late carton-hours"],
  tardiness: ["逾期量", "Tardiness"],
  total_hours: ["总工时", "Total hours"],
  labor_cost: ["人工费", "Labor cost"],
  warehouse_cost: ["仓储与短驳费", "Storage and transfer cost"],
  storage_cost: ["仓储费", "Storage cost"],
  shipping_cost: ["短驳费", "Transfer cost"],
  regular_paid_hours: ["正常计费工时", "Regular paid hours"],
  transfer_hours: ["短驳小时数", "Transfer hours"],
  orders: ["订单", "Orders"],
  name: ["名称", "Name"],
  late_by_order: ["各订单逾期小时", "Late hours by order"],
  tardy_orders: ["逾期订单数", "Late order count"],
  cost_breakdown: ["成本明细", "Cost breakdown"],
  labor_cny: ["人工（元）", "Labor (CNY)"],
  warehouse_cny: ["仓储（元）", "Storage (CNY)"],
  shipping_cny: ["运输（元）", "Shipping (CNY)"],
  setup_cny: ["换单（元）", "Changeovers (CNY)"],
};
const tr = (key, path = "") => {
  const localized = data?.localization;
  const labels = localized?.language === language ? localized.labels || {} : {};
  return labels[`${path ? path + "." : ""}${key}`] || labels[key]
    || words[key]?.[language === "zh" ? 0 : 1] || key.replaceAll("_", " ");
};
const fmt = (value) =>
  typeof value === "number"
    ? new Intl.NumberFormat(language === "zh" ? "zh-CN" : "en-US", {
        maximumFractionDigits: 2,
      }).format(value)
    : String(value ?? "–");
const node = (tag, text, cls) => {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (cls) el.className = cls;
  return el;
};
let data,
  chosen,
  chart,
  scheduleChart,
  storageChart,
  page = 0,
  sortColumn = -1,
  sortDirection = 1,
  requestId = 0;
const pageSize = 12;
function localize() {
  document.documentElement.lang = language;
  document.title = `MAPLE | ${tr("explorer")}`;
  document
    .querySelectorAll("[data-i18n]")
    .forEach((el) => (el.textContent = tr(el.dataset.i18n)));
  document.querySelectorAll("[data-tip]").forEach((el) => {
    el.title = tr(el.dataset.tip);
    el.setAttribute("aria-label", el.title);
  });
  document
    .querySelectorAll("[data-placeholder]")
    .forEach((el) => (el.placeholder = tr(el.dataset.placeholder)));
  $("language").value = language;
  lucide.createIcons();
}
async function api(path, options) {
  const response = await fetch(base + path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
  return value;
}
function error(message) {
  $("error").hidden = !message;
  $("error").textContent = message || "";
}
async function load(turn) {
  const current = ++requestId;
  $("workspace").setAttribute("aria-busy", "true");
  error("");
  try {
    if (!query.get("session")) throw new Error(tr("missing"));
    const payload = await api(
      `/solution-options/${encodeURIComponent(query.get("session"))}${turn == null ? "" : `?turn=${turn}`}`,
    );
    if (current !== requestId) return;
    data = payload;
    chosen =
      data.candidates.find((row) => row.id === data.preference?.candidate_id) ||
      data.candidates.find((row) => row.pareto) ||
      data.candidates[0];
    page = 0;
    $("title").textContent = data.title;
    $("session").textContent = data.session_id;
    $("requirement").textContent = data.requirement || "–";
    $("turn").replaceChildren(
      ...Array.from(
        { length: data.latest_turn + 1 },
        (_, i) => new Option(`${tr("turn")} ${i}`, i),
      ),
    );
    $("turn").value = data.turn;
    $("turn").disabled = false;
    for (const id of ["x", "y"]) {
      $(id).replaceChildren(
        ...data.objective_names.map((name, i) => new Option(tr(name), i)),
      );
    }
    $("x").value = 0;
    $("y").value = data.objective_names.length > 1 ? 1 : 0;
    $("y").disabled = data.objective_names.length < 2;
    for (const key of ["total", "feasible", "pareto"])
      $(key).textContent = fmt(data.counts[key]);
    $("preferred").textContent = data.preference?.label || "–";
    $("notice").textContent = [
      data.coverage === "retained_archive_only" ? tr("partial") : "",
      data.demo?.mode === "offline_numerical" ? tr("demo") : "",
      data.demo?.mode === "real_api_simulated_business_data"
        ? tr("demoLive")
        : "",
    ]
      .filter(Boolean)
      .join(" · ");
    $("save-status").textContent = "";
    render();
    if (data.demo?.validation === "failed") error(tr("validationFailed"));
    query.set("turn", String(data.turn));
    query.set("lang", language);
    history.replaceState(null, "", `?${query}`);
    if (!data.candidates.length) error(tr("empty"));
  } catch (reason) {
    if (current === requestId) {
      error(reason.message);
      if (data) $("turn").value = data.turn;
    }
  } finally {
    if (current === requestId)
      $("workspace").setAttribute("aria-busy", "false");
  }
}
function plot() {
  if (!data) return;
  const x = Number($("x").value),
    y = Number($("y").value),
    single = data.objective_names.length < 2;
  const point = (row) => ({
    value: [
      single ? data.candidates.indexOf(row) + 1 : row.objectives[x],
      row.objectives[y],
    ],
    id: row.id,
    name: row.label,
  });
  chart.setOption(
    {
      animation: false,
      textStyle: {
        fontFamily: "Inter, Microsoft YaHei, sans-serif",
        fontSize: 12,
        color: "#62727a",
      },
      grid: { left: 16, right: 20, top: 24, bottom: 64, containLabel: true },
      tooltip: {
        trigger: "item",
        renderMode: "richText",
        formatter: (params) => {
          const row = data.candidates.find((r) => r.id === params.data.id);
          if (!row) return "";
          const overlap = data.candidates.filter(
            (r) =>
              r.plottable &&
              r.objectives[x] === row.objectives[x] &&
              r.objectives[y] === row.objectives[y],
          ).length;
          return [
            row.label,
            ...data.objective_names.map(
              (name, i) => `${tr(name)}: ${fmt(row.objectives[i])}`,
            ),
            ...(!single && overlap > 1
              ? [
                  language === "zh"
                    ? `此坐标对应 ${overlap} 个方案`
                    : `${overlap} plans share this position`,
                ]
              : []),
          ].join("\n");
        },
      },
      xAxis: {
        type: "value",
        scale: true,
        name: single ? tr("index") : tr(data.objective_names[x]),
        nameLocation: "middle",
        nameGap: 31,
        splitLine: { lineStyle: { color: "#eef1f4" } },
        axisLabel: { formatter: fmt },
      },
      yAxis: {
        type: "value",
        scale: true,
        splitLine: { lineStyle: { color: "#eef1f4" } },
        axisLabel: { formatter: fmt },
      },
      dataZoom: [
        { type: "inside", xAxisIndex: 0 },
        { type: "inside", yAxisIndex: 0 },
        {
          type: "slider",
          height: 15,
          bottom: 4,
          borderColor: "#e2e8eb",
          fillerColor: "#deede9",
          showDetail: false,
        },
      ],
      series: [
        {
          type: "scatter",
          name: tr("other"),
          symbolSize: 8,
          itemStyle: { color: "#bbc7d5", opacity: 0.8 },
          data: data.candidates
            .filter((r) => r.plottable && r.feasible && !r.pareto)
            .map(point),
        },
        {
          type: "scatter",
          name: tr("infeasible"),
          symbol: "triangle",
          symbolSize: 7,
          itemStyle: { color: "#d37871", opacity: 0.7 },
          data: data.candidates
            .filter((r) => r.plottable && !r.feasible)
            .map(point),
        },
        {
          type: "scatter",
          name: tr("pareto"),
          symbolSize: 10,
          itemStyle: { color: "#15877d", borderColor: "white", borderWidth: 1 },
          data: data.candidates.filter((r) => r.pareto).map(point),
        },
        {
          type: "scatter",
          name: tr("selected"),
          symbolSize: 18,
          z: 10,
          itemStyle: {
            color: "#d39731",
            borderColor: "#80521b",
            borderWidth: 2,
          },
          data: chosen?.plottable ? [point(chosen)] : [],
        },
      ],
    },
    true,
  );
}
function choose(id) {
  chosen = data.candidates.find((row) => row.id === id);
  $("save-status").textContent = "";
  render();
}
function filtered() {
  const term = $("search").value.toLowerCase();
  return data.candidates
    .filter(
      (row) =>
        (!$("only-pareto").checked || row.pareto) &&
        (!term ||
          `${row.label} ${JSON.stringify(row.solution)}`
            .toLowerCase()
            .includes(term)),
    )
    .sort(
      (a, b) =>
        sortDirection *
        (sortColumn < 0
          ? a.label.localeCompare(b.label)
          : (a.objectives[sortColumn] ?? Infinity) -
            (b.objectives[sortColumn] ?? Infinity)),
    );
}
function table() {
  const head = node("tr");
  [tr("id"), ...data.objective_names.map((name) => tr(name)), tr("status")].forEach(
    (name, index) => {
      const th = node("th");
      const button = node(
        "button",
        `${name}${sortColumn === index - 1 ? (sortDirection === 1 ? " ↑" : " ↓") : ""}`,
      );
      button.type = "button";
      button.onclick = () => {
        if (index > data.objective_names.length) return;
        sortDirection = sortColumn === index - 1 ? -sortDirection : 1;
        sortColumn = index - 1;
        table();
      };
      th.append(button);
      head.append(th);
    },
  );
  $("candidate-table").tHead.replaceChildren(head);
  const rows = filtered();
  page = Math.min(page, Math.max(0, Math.ceil(rows.length / pageSize) - 1));
  const body = rows.slice(page * pageSize, (page + 1) * pageSize).map((row) => {
    const el = node("tr");
    el.setAttribute("aria-selected", String(row.id === chosen?.id));
    el.dataset.id = row.id;
    el.onclick = () => choose(row.id);
    const first = node("td");
    const button = node("button", row.label);
    button.type = "button";
    button.onclick = () => choose(row.id);
    first.append(button);
    el.append(first);
    row.objectives.forEach((value) => el.append(node("td", fmt(value))));
    const status = node("td");
    status.append(
      node(
        "span",
        tr(row.pareto ? "pareto" : row.feasible ? "feasible" : "infeasible"),
        `badge${row.feasible ? "" : " invalid"}`,
      ),
    );
    el.append(status);
    return el;
  });
  $("candidate-table").tBodies[0].replaceChildren(...body);
  $("row-count").textContent =
    language === "zh" ? `${rows.length} 个方案` : `${rows.length} candidates`;
  $("page").textContent =
    `${page + 1} / ${Math.max(1, Math.ceil(rows.length / pageSize))}`;
  $("prev").disabled = page === 0;
  $("next").disabled = (page + 1) * pageSize >= rows.length;
}
function detail() {
  $("objective-values").replaceChildren();
  $("tradeoff").replaceChildren();
  $("solution-detail").replaceChildren();
  if (!chosen) {
    $("selected-label").textContent = tr("choose");
    $("save").disabled = true;
    $("download").disabled = true;
    return;
  }
  $("selected-label").textContent = chosen.label;
  $("selection-badge").textContent = tr(
    chosen.pareto ? "pareto" : chosen.feasible ? "feasible" : "infeasible",
  );
  const feasible = data.candidates.filter((row) => row.selectable);
  data.objective_names.forEach((name, i) => {
    const values = feasible.map((row) => row.objectives[i]),
      min = values.length ? Math.min(...values) : 0,
      max = values.length ? Math.max(...values) : 0;
    const item = node("div", undefined, "objective"),
      heading = node("div", undefined, "objective-head");
    heading.append(
      node("span", tr(name)),
      node("strong", fmt(chosen.objectives[i])),
    );
    item.append(heading);
    const range = node("div", undefined, "range"),
      mark = node("i");
    const pos =
      max === min ? 50 : (100 * (chosen.objectives[i] - min)) / (max - min);
    mark.style.left = `calc(${Math.min(100, Math.max(0, pos))}% - 5px)`;
    range.append(mark);
    item.append(range);
    const labels = node("div", undefined, "range-labels");
    labels.append(
      node("span", `${tr("min")} ${fmt(min)}`),
      node("span", tr("lower")),
      node("span", `${tr("max")} ${fmt(max)}`),
    );
    item.append(labels);
    $("objective-values").append(item);
  });
  $("tradeoff").append(
    node(
      "p",
      tr(
        !chosen.feasible
          ? "invalidExplanation"
          : chosen.pareto
            ? "paretoExplanation"
            : "dominated",
      ),
    ),
  );
  if (chosen.selectable && feasible.length) {
    const deltas = data.objective_names.map(
      (name, i) =>
        `${tr(name)} +${fmt(Math.max(0, chosen.objectives[i] - Math.min(...feasible.map((row) => row.objectives[i]))))}`,
    );
    $("tradeoff").append(node("p", `${tr("near")}: ${deltas.join(" / ")}`));
  }
  $("save").disabled = !chosen.selectable || data.demo?.validation === "failed";
  $("download").disabled = false;
  const solution = MAPLESolutionView.presentSolution(chosen.solution);
  if (
    Array.isArray(solution.order_plan) &&
    solution.order_plan.length &&
    solution.order_plan.every(
      (row) => Number.isFinite(row.late_hours) && row.team != null,
    )
  ) {
    const late = solution.order_plan.filter(
        (row) => Number(row.late_hours) > 0,
      ),
      teams = new Set(solution.order_plan.map((row) => row.team));
    const overtime =
      Array.isArray(solution.worker_shifts) &&
      solution.worker_shifts.every(
        (row) =>
          Number.isFinite(row.overtime_hours) && Number.isFinite(row.workers),
      )
        ? solution.worker_shifts.reduce(
            (sum, row) =>
              sum + Number(row.overtime_hours || 0) * Number(row.workers || 0),
            0,
          )
        : null;
    const summary =
      language === "zh"
        ? `${solution.order_plan.length} 批订单由 ${teams.size} 个班组执行。${late.length ? `逾期订单：${late.map((row) => row.order_id).join("、")}。` : "所有订单均可在截单前到港。"}${overtime === null ? "" : `合计加班 ${fmt(overtime)} 人时。`}`
        : `${solution.order_plan.length} orders across ${teams.size} teams. ${late.length ? `Late orders: ${late.map((row) => row.order_id).join(", ")}.` : "All orders reach port before cut-off."}${overtime === null ? "" : ` Overtime: ${fmt(overtime)} worker-hours.`}`;
    $("tradeoff").prepend(node("p", summary));
  }
  if (!Object.keys(solution).length)
    $("solution-detail").append(node("p", tr("noSolution")));
  for (const [key, value] of Object.entries(solution)) {
    const section = node("details", undefined, "detail-section");
    section.open = true;
    section.append(node("summary", tr(key)));
    if (
      Array.isArray(value) &&
      value.length &&
      value.every((v) => v && typeof v === "object" && !Array.isArray(v))
    ) {
      const preferred = [
        "order_id",
        "job_id",
        "id",
        "name",
        "customer",
        "team",
        "warehouse",
        "workers",
        "start_hour",
        "finish_hour",
        "arrival_hour",
        "due_hour",
        "late_hours",
        "cartons",
        "used",
        "capacity",
      ];
      const keys = [...new Set(value.flatMap(Object.keys))].sort(
          (a, b) =>
            (preferred.includes(a) ? preferred.indexOf(a) : 100) -
            (preferred.includes(b) ? preferred.indexOf(b) : 100),
        ),
        table = node("table"),
        thead = node("thead"),
        heading = node("tr");
      keys.forEach((k) => heading.append(node("th", tr(k, key))));
      thead.append(heading);
      table.append(thead);
      const tbody = node("tbody");
      value.forEach((record) => {
        const row = node("tr");
        keys.forEach((k) =>
          row.append(
            node(
              "td",
              typeof record[k] === "object"
                ? JSON.stringify(record[k])
                : fmt(record[k]),
            ),
          ),
        );
        tbody.append(row);
      });
      table.append(tbody);
      const scroll = node("div", undefined, "table-scroll");
      scroll.append(table);
      section.append(scroll);
    } else if (
      value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      Object.values(value).every((v) => typeof v !== "object")
    ) {
      const dl = node("dl");
      Object.entries(value).forEach(([k, v]) =>
        dl.append(node("dt", tr(k, key)), node("dd", fmt(v))),
      );
      section.append(dl);
    } else
      section.append(
        node(
          "pre",
          typeof value === "object"
            ? JSON.stringify(value, null, 2)
            : fmt(value),
        ),
      );
    $("solution-detail").append(section);
  }
  const raw = node("details", undefined, "detail-section");
  raw.append(
    node("summary", tr("genome")),
    node(
      "pre",
      JSON.stringify(
        { genome: chosen.genome, violations: chosen.violations },
        null,
        2,
      ),
    ),
  );
  $("solution-detail").append(raw);
}
function planVisuals() {
  const solution = MAPLESolutionView.presentSolution(chosen?.solution);
  const schedule = solution.order_plan,
    warehouses = solution.warehouse_plan;
  const hasSchedule =
    Array.isArray(schedule) &&
    schedule.length &&
    schedule.every(
      (row) =>
        Number.isFinite(row.start_hour) && Number.isFinite(row.finish_hour),
    );
  const hasStorage =
    Array.isArray(warehouses) &&
    warehouses.length &&
    warehouses.every(
      (row) => Number.isFinite(row.used) && Number.isFinite(row.capacity),
    );
  $("plan-visuals").hidden = !hasSchedule && !hasStorage;
  $("schedule-chart").hidden = !hasSchedule;
  $("storage-chart").hidden = !hasStorage;
  $("plan-label").textContent = chosen?.label || "";
  if (hasSchedule) {
    if (!scheduleChart) {
      scheduleChart = echarts.init($("schedule-chart"));
      new ResizeObserver(() => scheduleChart.resize()).observe(
        $("schedule-chart"),
      );
    }
    const rows = [...schedule].sort(
      (a, b) =>
        String(a.team).localeCompare(String(b.team)) ||
        a.start_hour - b.start_hour,
    );
    const teams = [...new Set(rows.map((row) => row.team))],
      colors = ["#2e8f83", "#628ab9", "#c49950", "#9470a6"];
    scheduleChart.setOption(
      {
        animation: false,
        textStyle: {
          fontFamily: "Microsoft YaHei, sans-serif",
          fontSize: 11,
          color: "#62727a",
        },
        grid: { top: 22, bottom: 45, left: 4, right: 24, containLabel: true },
        tooltip: {
          trigger: "item",
          renderMode: "richText",
          formatter: (p) => {
            const row = rows[p.dataIndex];
            return `${row.order_id} · ${tr("team")} ${row.team}\n${tr("start_hour")}: ${fmt(row.start_hour)}\n${tr("finish_hour")}: ${fmt(row.finish_hour)}\n${tr("late_hours")}: ${fmt(row.late_hours)}`;
          },
        },
        xAxis: {
          type: "value",
          name: tr("hours"),
          nameLocation: "middle",
          nameGap: 25,
          splitLine: { lineStyle: { color: "#eef1f4" } },
        },
        yAxis: {
          type: "category",
          inverse: true,
          data: rows.map((row) => `${row.order_id} / ${row.team}`),
        },
        series: [
          {
            type: "bar",
            stack: "schedule",
            silent: true,
            itemStyle: { color: "transparent" },
            data: rows.map((row) => row.start_hour),
          },
          {
            type: "bar",
            stack: "schedule",
            barWidth: 17,
            data: rows.map((row) => ({
              value: row.finish_hour - row.start_hour,
              itemStyle: {
                color: colors[teams.indexOf(row.team) % colors.length],
              },
            })),
          },
        ],
      },
      true,
    );
    scheduleChart.resize();
  }
  if (hasStorage) {
    if (!storageChart) {
      storageChart = echarts.init($("storage-chart"));
      new ResizeObserver(() => storageChart.resize()).observe(
        $("storage-chart"),
      );
    }
    storageChart.setOption(
      {
        animation: false,
        textStyle: {
          fontFamily: "Microsoft YaHei, sans-serif",
          fontSize: 11,
          color: "#62727a",
        },
        title: {
          text: tr("usedCapacity"),
          left: 0,
          top: 4,
          textStyle: { fontSize: 13, fontWeight: 500 },
        },
        grid: { top: 65, bottom: 20, left: 4, right: 24, containLabel: true },
        tooltip: { trigger: "axis", renderMode: "richText" },
        legend: { top: 30, right: 0 },
        xAxis: {
          type: "value",
          splitLine: { lineStyle: { color: "#eef1f4" } },
        },
        yAxis: {
          type: "category",
          data: warehouses.map((row) => row.warehouse),
        },
        series: [
          {
            name: tr("used"),
            type: "bar",
            stack: "capacity",
            barWidth: 20,
            itemStyle: { color: "#628ab9" },
            data: warehouses.map((row) => row.used),
          },
          {
            name: tr("remaining"),
            type: "bar",
            stack: "capacity",
            itemStyle: { color: "#e2e9ef" },
            data: warehouses.map((row) => Math.max(0, row.capacity - row.used)),
          },
        ],
      },
      true,
    );
    storageChart.resize();
  }
}
function render() {
  plot();
  table();
  detail();
  planVisuals();
}
function download(content, name, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = node("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function csvCell(value) {
  let text = String(value ?? "");
  if (/^[=+@\-\t\r]/.test(text) && typeof value !== "number") text = "'" + text;
  return '"' + text.replaceAll('"', '""') + '"';
}
$("brand").src = `${base}/brand/maple-logo.png`;
$("favicon").href = $("brand").src;
$("turn").onchange = () => load(Number($("turn").value));
$("refresh").onclick = () => load(data?.turn);
$("language").onchange = () => {
  language = $("language").value;
  localize();
  if (data) load(data.turn);
};
$("x").onchange = plot;
$("y").onchange = plot;
$("reset").onclick = plot;
$("search").oninput = () => {
  page = 0;
  if (data) table();
};
$("only-pareto").onchange = () => {
  page = 0;
  if (data) table();
};
$("prev").onclick = () => {
  page--;
  table();
};
$("next").onclick = () => {
  page++;
  table();
};
$("save").onclick = async () => {
  const row = chosen,
    turn = data.turn;
  $("save").disabled = true;
  $("save-status").textContent = tr("saving");
  try {
    const preference = await api(
      `/solution-preferences/${encodeURIComponent(data.session_id)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ turn, candidate_id: row.id }),
      },
    );
    if (data.turn === turn) {
      data.preference = preference;
      $("preferred").textContent = preference.label;
      $("save-status").textContent = tr("saved");
    }
  } catch (reason) {
    error(reason.message);
  } finally {
    $("save").disabled =
      !chosen?.selectable || data.demo?.validation === "failed";
  }
};
$("download").onclick = () => {
  if (chosen)
    download(
      JSON.stringify(
        {
          session_id: data.session_id,
          turn: data.turn,
          objective_names: data.objective_names,
          ...chosen,
        },
        null,
        2,
      ),
      `${data.session_id}-t${data.turn}-${chosen.label}.json`,
      "application/json",
    );
};
$("download-all").onclick = () => {
  if (!data) return;
  const rows = [
    [tr("id"), tr("pareto"), tr("feasible"), ...data.objective_names.map((name) => tr(name)), tr("solution")],
    ...data.candidates.map((row) => [
      row.label,
      row.pareto,
      row.feasible,
      ...row.objectives,
      JSON.stringify(data.localization?.language === language ? row.localized_solution : row.solution),
    ]),
  ];
  download(
    "\ufeff" + rows.map((row) => row.map(csvCell).join(",")).join("\r\n"),
    `${data.session_id}-t${data.turn}-candidates.csv`,
    "text/csv;charset=utf-8",
  );
};
localize();
chart = echarts.init($("chart"));
chart.on("click", (event) => {
  if (event.data?.id) choose(event.data.id);
});
new ResizeObserver(() => chart.resize()).observe($("chart"));
load(query.has("turn") ? Number(query.get("turn")) : undefined);
