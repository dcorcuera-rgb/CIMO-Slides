const DATA_PATH = "./data/dashboard-data.json";

const DEFAULT_FILTERS = {
  scopeOnly: true,
  search: "",
  status: "All",
  severity: "All",
  businessUnit: "All",
  riskDomain: "All",
  issueSource: "All",
};

const state = {
  dataset: null,
  allRows: [],
  filteredRows: [],
  eventsBound: false,
  lastUpdated: "",
  filters: { ...DEFAULT_FILTERS },
};

const els = {
  pageTitle: document.getElementById("pageTitle"),
  pageSubtitle: document.getElementById("pageSubtitle"),
  storySummary: document.getElementById("storySummary"),
  updatesList: document.getElementById("updatesList"),
  scopeOnly: document.getElementById("scopeOnly"),
  search: document.getElementById("search"),
  status: document.getElementById("status"),
  severity: document.getElementById("severity"),
  businessUnit: document.getElementById("businessUnit"),
  riskDomain: document.getElementById("riskDomain"),
  issueSource: document.getElementById("issueSource"),
  reset: document.getElementById("reset"),
  copyLink: document.getElementById("copyLink"),
  downloadCsv: document.getElementById("downloadCsv"),
  downloadSlide: document.getElementById("downloadSlide"),
  copySlideNotes: document.getElementById("copySlideNotes"),
  issuesFile: document.getElementById("issuesFile"),
  hierarchyFile: document.getElementById("hierarchyFile"),
  loadCsvs: document.getElementById("loadCsvs"),
  localFile: document.getElementById("localFile"),
  kpis: document.getElementById("kpis"),
  kriGrid: document.getElementById("kriGrid"),
  statusTableBody: document.querySelector("#statusTable tbody"),
  sourceTableBody: document.querySelector("#sourceTable tbody"),
  meta: document.getElementById("meta"),
};

function safe(v) {
  return v == null || v === "" ? "-" : String(v);
}

function normalize(v) {
  return String(v || "").trim().toLowerCase();
}

function clean(v) {
  return String(v || "").trim();
}

function csvEscape(value) {
  const v = String(value ?? "");
  if (v.includes('"') || v.includes(",") || v.includes("\n")) {
    return `"${v.replace(/"/g, '""')}"`;
  }
  return v;
}

function formatPercent(value) {
  if (value == null || Number.isNaN(Number(value))) return "N/A";
  return `${Math.round(Number(value) * 100)}%`;
}

function formatMetric(value, digits = 0) {
  if (value == null || Number.isNaN(Number(value))) return "N/A";
  return Number(value).toFixed(digits);
}

function truncateText(value, maxLength) {
  const text = clean(value);
  if (text.length <= maxLength) return text;
  return `${text.slice(0, Math.max(0, maxLength - 1)).trim()}…`;
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let value = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    const next = text[i + 1];

    if (inQuotes) {
      if (c === '"' && next === '"') {
        value += '"';
        i += 1;
      } else if (c === '"') {
        inQuotes = false;
      } else {
        value += c;
      }
      continue;
    }

    if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      row.push(value.trim());
      value = "";
    } else if (c === "\n") {
      row.push(value.trim());
      rows.push(row);
      row = [];
      value = "";
    } else if (c === "\r") {
      continue;
    } else {
      value += c;
    }
  }

  if (value.length || row.length) {
    row.push(value.trim());
    rows.push(row);
  }

  if (!rows.length) return [];
  const headers = rows[0];

  return rows
    .slice(1)
    .filter((r) => r.some((cell) => cell !== ""))
    .map((r) => {
      const obj = {};
      headers.forEach((h, idx) => {
        obj[h] = r[idx] ?? "";
      });
      return obj;
    });
}

function parseDate(value) {
  const text = clean(value);
  if (!text) return null;
  const parts = [
    /^(\d{4})-(\d{2})-(\d{2})$/,
    /^(\d{2})\/(\d{2})\/(\d{4})$/,
    /^(\d{2})\/(\d{2})\/(\d{2})$/,
  ];

  for (const pattern of parts) {
    const match = text.match(pattern);
    if (!match) continue;
    if (pattern === parts[0]) return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
    if (pattern === parts[1]) return new Date(Date.UTC(Number(match[3]), Number(match[1]) - 1, Number(match[2])));
    return new Date(Date.UTC(2000 + Number(match[3]), Number(match[1]) - 1, Number(match[2])));
  }

  const parsed = new Date(text);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function isClosedStatus(status) {
  return ["closed", "resolved", "done", "complete", "completed", "cancelled", "canceled"].includes(normalize(status));
}

function isHighSeverity(severity) {
  return ["high", "critical"].includes(normalize(severity));
}

function isArchivedStatus(status) {
  return normalize(status) === "archived";
}

function isActiveStatus(status) {
  return !isClosedStatus(status) && !isArchivedStatus(status);
}

function getUrlFilters() {
  const params = new URLSearchParams(window.location.search);
  return {
    scopeOnly: params.get("scopeOnly") !== "false",
    search: params.get("search") || "",
    status: params.get("status") || "All",
    severity: params.get("severity") || "All",
    businessUnit: params.get("businessUnit") || "All",
    riskDomain: params.get("riskDomain") || "All",
    issueSource: params.get("issueSource") || "All",
  };
}

function setUrlFilters() {
  const params = new URLSearchParams();
  Object.entries(state.filters).forEach(([k, v]) => {
    if (k === "scopeOnly") {
      if (!v) params.set(k, "false");
      return;
    }
    if (v && v !== "All") params.set(k, v);
  });
  const next = `${window.location.pathname}${params.toString() ? `?${params}` : ""}`;
  window.history.replaceState({}, "", next);
}

function fillSelect(selectEl, values, selected) {
  const unique = ["All", ...new Set(values.filter(Boolean).sort((a, b) => a.localeCompare(b)))];
  selectEl.innerHTML = "";
  unique.forEach((v) => {
    const option = document.createElement("option");
    option.value = v;
    option.textContent = v;
    if (v === selected) option.selected = true;
    selectEl.appendChild(option);
  });
}

function hydrateControls() {
  els.scopeOnly.checked = Boolean(state.filters.scopeOnly);
  els.search.value = state.filters.search;
  fillSelect(els.status, state.allRows.map((r) => safe(r.status)), state.filters.status);
  fillSelect(els.severity, state.allRows.map((r) => safe(r.severity)), state.filters.severity);
  fillSelect(els.businessUnit, state.allRows.map((r) => safe(r.business_unit)), state.filters.businessUnit);
  fillSelect(els.riskDomain, state.allRows.map((r) => safe(r.risk_domain)), state.filters.riskDomain);
  fillSelect(els.issueSource, state.allRows.map((r) => safe(r.issue_source)), state.filters.issueSource);
}

function applyFilters() {
  const f = state.filters;
  state.filteredRows = state.allRows.filter((r) => {
    const searchBlob = [
      r.issue_id,
      r.issue_title,
      r.issue_owner_name,
      r.issue_owner_email,
      r.business_unit,
      r.risk_domain,
      r.issue_source,
    ]
      .map(normalize)
      .join(" ");

    if (f.scopeOnly && !r.in_cimo_intake) return false;
    if (f.search && !searchBlob.includes(normalize(f.search))) return false;
    if (f.status !== "All" && safe(r.status) !== f.status) return false;
    if (f.severity !== "All" && safe(r.severity) !== f.severity) return false;
    if (f.businessUnit !== "All" && safe(r.business_unit) !== f.businessUnit) return false;
    if (f.riskDomain !== "All" && safe(r.risk_domain) !== f.riskDomain) return false;
    if (f.issueSource !== "All" && safe(r.issue_source) !== f.issueSource) return false;
    return true;
  });
}

function summarizeRows(rows) {
  const today = new Date();
  const activeRows = rows.filter((r) => isActiveStatus(r.status));
  const overdue = activeRows.filter((r) => {
    const due = parseDate(r.due_date);
    return due && due < today;
  });
  const dueSoon = activeRows.filter((r) => {
    const due = parseDate(r.due_date);
    if (!due) return false;
    const days = Math.ceil((due - today) / (1000 * 60 * 60 * 24));
    return days >= 0 && days <= 30;
  });
  const highSeverity = activeRows.filter((r) => isHighSeverity(r.severity));
  const moderateSeverity = activeRows.filter((r) => normalize(r.severity) === "moderate").length;
  const lowSeverity = activeRows.filter((r) => normalize(r.severity) === "low").length;
  const riskAccepted = activeRows.filter((r) => normalize(r.status) === "risk accepted");
  const unresolvedAps = activeRows.reduce((sum, r) => sum + Number(r.linked_action_plans_open_count || 0), 0);

  return {
    total: rows.length,
    active: activeRows.length,
    closed: rows.filter((r) => isClosedStatus(r.status)).length,
    overdue: overdue.length,
    dueSoon: dueSoon.length,
    highSeverity: highSeverity.length,
    moderateSeverity,
    lowSeverity,
    riskAccepted: riskAccepted.length,
    unresolvedAps,
  };
}

function summarizeCimoRows(rows) {
  return summarizeRows(rows.filter((r) => r.in_cimo_intake));
}

function getBreakdownRows() {
  return state.filteredRows.filter((r) => r.in_cimo_intake);
}

function makeStory(summary, totalAvailable, scopeOnly) {
  if (!summary.total) {
    return [
      "No records match the current filter set.",
      "Broaden the filters to restore the CIMO population view.",
    ];
  }

  const share = totalAvailable ? Math.round((summary.total / totalAvailable) * 100) : 0;
  const lines = [];
  lines.push(
    `${summary.active} active issues remain${scopeOnly ? ` across the CIMO population (${share}% of all visible records).` : "."}`,
  );
  lines.push(
    `${summary.overdue} active issues are past due based on issue due date, and ${summary.dueSoon} more are due within 30 days.`,
  );
  lines.push(
    `${summary.highSeverity} active issues are high, ${summary.moderateSeverity} are moderate, ${summary.lowSeverity} are low, and ${summary.riskAccepted} sit in risk-accepted status.`,
  );
  return lines;
}

function renderStory() {
  const summary = summarizeRows(state.filteredRows);
  const lines = makeStory(summary, state.allRows.length, state.filters.scopeOnly);
  els.storySummary.innerHTML = lines.map((line) => `<p>${line}</p>`).join("");
}

function renderUpdates() {
  const updates = (state.dataset?.program?.updates || []).slice().sort((a, b) => String(b.month || "").localeCompare(String(a.month || "")));
  if (!updates.length) {
    els.updatesList.innerHTML = `<div class="update-card"><p>No monthly updates have been added yet. Add entries in <code>data/program_config.json</code> to turn this into a narrative reporting surface.</p></div>`;
    return;
  }

  els.updatesList.innerHTML = updates
    .map((update) => {
      const bullets = Array.isArray(update.bullets) ? update.bullets : [];
      return `<article class="update-card">
        <div class="update-head">
          <strong>${safe(update.month)}</strong>
          <span>${safe(update.title)}</span>
        </div>
        <p>${safe(update.summary)}</p>
        ${bullets.length ? `<ul>${bullets.map((bullet) => `<li>${safe(bullet)}</li>`).join("")}</ul>` : ""}
      </article>`;
    })
    .join("");
}

function renderKpis() {
  const summary = summarizeRows(state.filteredRows);
  const cimoSummary = summarizeCimoRows(state.filteredRows);
  const cards = [
    ["Active issues", `${summary.active} / ${cimoSummary.active}`],
    ["Overdue", `${summary.overdue} / ${cimoSummary.overdue}`],
    ["Due in 30 days", `${summary.dueSoon} / ${cimoSummary.dueSoon}`],
    ["High", `${summary.highSeverity} / ${cimoSummary.highSeverity}`],
    ["Moderate", `${summary.moderateSeverity} / ${cimoSummary.moderateSeverity}`],
    ["Low", `${summary.lowSeverity} / ${cimoSummary.lowSeverity}`],
    ["Risk accepted", `${summary.riskAccepted} / ${cimoSummary.riskAccepted}`],
  ];

  els.kpis.innerHTML = cards
    .map(
      ([label, value]) =>
        `<div class="kpi"><div class="value">${value}</div><div class="label">${label}</div><div class="kpi-note">All / CIMO</div></div>`,
    )
    .join("");
}

function buildSlideModel() {
  const summary = summarizeRows(state.filteredRows);
  const storyLines = makeStory(summary, state.allRows.length, state.filters.scopeOnly);
  const statusTop = groupCounts(state.filteredRows, "status").slice(0, 3);
  const sourceTop = groupCounts(state.filteredRows, "issue_source").slice(0, 3);
  const kri = state.dataset?.kri || {};
  const overdue = kri.compliance_issues_overdue || {};
  const selfId = kri.self_identified_vs_overall || {};
  const intake = kri.cimo_intake_detection || {};
  const filterLabels = [];

  if (state.filters.scopeOnly) filterLabels.push("CIMO only");
  ["status", "severity", "businessUnit", "riskDomain", "issueSource"].forEach((key) => {
    if (state.filters[key] && state.filters[key] !== "All") filterLabels.push(state.filters[key]);
  });
  if (state.filters.search) filterLabels.push(`Search: ${truncateText(state.filters.search, 20)}`);

  return {
    title: state.dataset?.program?.name || "Program Health Dashboard",
    subtitle: state.dataset?.program?.scope_note || "Program health snapshot",
    asOf: state.dataset?.metrics?.as_of_date || safe(state.lastUpdated),
    filters: filterLabels.length ? filterLabels.join(" | ") : "All visible records",
    storyLines: storyLines.slice(0, 3),
    kpis: [
      ["Active", String(summary.active)],
      ["Overdue", String(summary.overdue)],
      ["High", String(summary.highSeverity)],
      ["Self-ID", formatPercent(selfId.percent_self_identified)],
      ["CIMO Intake", formatPercent(intake.detection_rate)],
    ],
    highlights: [
      `Compliance overdue: ${safe(overdue.open_compliance_issues_overdue)}/${safe(overdue.open_compliance_issues)} (${formatPercent(overdue.percent_overdue)})`,
      `Self-identified issues: ${safe(selfId.self_identified_issues)}/${safe(selfId.overall_issues)} (${formatPercent(selfId.percent_self_identified)})`,
      `CIMO intake: ${safe(intake.detected_issues)}/${safe(intake.overall_issues)} (${formatPercent(intake.detection_rate)})`,
    ],
    statusTop,
    sourceTop,
  };
}

function wrapCanvasText(ctx, text, x, y, maxWidth, lineHeight, maxLines) {
  const words = clean(text).split(/\s+/).filter(Boolean);
  if (!words.length) return y;
  let line = "";
  let lines = 0;

  for (let i = 0; i < words.length; i += 1) {
    const next = line ? `${line} ${words[i]}` : words[i];
    if (ctx.measureText(next).width > maxWidth && line) {
      ctx.fillText(line, x, y);
      y += lineHeight;
      lines += 1;
      line = words[i];
      if (lines >= maxLines - 1) break;
    } else {
      line = next;
    }
  }

  if (line && lines < maxLines) {
    const finalLine = ctx.measureText(line).width > maxWidth ? truncateText(line, Math.floor(maxWidth / 8)) : line;
    ctx.fillText(finalLine, x, y);
    y += lineHeight;
  }
  return y;
}

function drawMetricChip(ctx, x, y, w, h, label, value) {
  ctx.fillStyle = "#fffaf2";
  ctx.strokeStyle = "#d5c8b3";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, 22);
  ctx.fill();
  ctx.stroke();

  ctx.fillStyle = "#9f4f2a";
  ctx.font = "700 28px Avenir Next, Segoe UI, sans-serif";
  ctx.fillText(value, x + 20, y + 42);
  ctx.fillStyle = "#655b4b";
  ctx.font = "600 14px Avenir Next, Segoe UI, sans-serif";
  ctx.fillText(label, x + 20, y + 68);
}

function drawRankedList(ctx, title, items, x, y, w) {
  ctx.fillStyle = "#1e1c18";
  ctx.font = "700 20px Avenir Next, Segoe UI, sans-serif";
  ctx.fillText(title, x, y);
  let lineY = y + 30;
  ctx.font = "500 16px Avenir Next, Segoe UI, sans-serif";
  ctx.fillStyle = "#655b4b";
  if (!items.length) {
    ctx.fillText("No values in current view", x, lineY);
    return;
  }
  items.forEach(([label, count], index) => {
    const text = `${index + 1}. ${truncateText(label, 42)} - ${count}`;
    wrapCanvasText(ctx, text, x, lineY, w, 20, 2);
    lineY += 36;
  });
}

function downloadSlidePng() {
  const model = buildSlideModel();
  const canvas = document.createElement("canvas");
  canvas.width = 1600;
  canvas.height = 900;
  const ctx = canvas.getContext("2d");

  ctx.fillStyle = "#f4f0e8";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const gradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
  gradient.addColorStop(0, "#fbf6ed");
  gradient.addColorStop(1, "#f1e7d8");
  ctx.fillStyle = gradient;
  ctx.fillRect(28, 28, canvas.width - 56, canvas.height - 56);

  ctx.fillStyle = "#9f4f2a";
  ctx.font = "700 18px Avenir Next, Segoe UI, sans-serif";
  ctx.fillText("MONTHLY REPORTING SNAPSHOT", 72, 92);

  ctx.fillStyle = "#1e1c18";
  ctx.font = "700 48px Avenir Next, Segoe UI, sans-serif";
  wrapCanvasText(ctx, model.title, 72, 148, 620, 56, 2);

  ctx.fillStyle = "#655b4b";
  ctx.font = "500 18px Avenir Next, Segoe UI, sans-serif";
  wrapCanvasText(ctx, model.subtitle, 72, 220, 620, 26, 2);
  ctx.fillText(`As of ${model.asOf}`, 72, 286);
  wrapCanvasText(ctx, `Filters: ${model.filters}`, 72, 316, 620, 24, 2);

  ctx.fillStyle = "#fffaf2";
  ctx.strokeStyle = "#d5c8b3";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.roundRect(72, 360, 620, 236, 28);
  ctx.fill();
  ctx.stroke();

  ctx.fillStyle = "#1e1c18";
  ctx.font = "700 24px Avenir Next, Segoe UI, sans-serif";
  ctx.fillText("Health Story", 104, 404);
  ctx.font = "500 19px Avenir Next, Segoe UI, sans-serif";
  ctx.fillStyle = "#655b4b";
  let storyY = 442;
  model.storyLines.forEach((line) => {
    ctx.fillStyle = "#9f4f2a";
    ctx.beginPath();
    ctx.arc(108, storyY - 7, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#655b4b";
    storyY = wrapCanvasText(ctx, line, 124, storyY, 536, 28, 2) + 8;
  });

  ctx.fillStyle = "#fffaf2";
  ctx.strokeStyle = "#d5c8b3";
  ctx.beginPath();
  ctx.roundRect(72, 624, 620, 204, 28);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#1e1c18";
  ctx.font = "700 24px Avenir Next, Segoe UI, sans-serif";
  ctx.fillText("Key Callouts", 104, 668);
  ctx.font = "500 18px Avenir Next, Segoe UI, sans-serif";
  ctx.fillStyle = "#655b4b";
  let calloutY = 706;
  model.highlights.forEach((line) => {
    calloutY = wrapCanvasText(ctx, line, 104, calloutY, 548, 24, 2) + 8;
  });

  const chipPositions = [
    [760, 92], [1030, 92], [1300, 92],
    [760, 198], [1030, 198], [1300, 198],
  ];
  model.kpis.forEach(([label, value], index) => {
    const [x, y] = chipPositions[index];
    drawMetricChip(ctx, x, y, 230, 88, label, value);
  });

  ctx.fillStyle = "#fffaf2";
  ctx.strokeStyle = "#d5c8b3";
  ctx.beginPath();
  ctx.roundRect(760, 332, 770, 242, 28);
  ctx.fill();
  ctx.stroke();
  drawRankedList(ctx, "Top Statuses", model.statusTop, 794, 378, 320);
  drawRankedList(ctx, "Top Sources", model.sourceTop, 1160, 378, 320);

  ctx.fillStyle = "#fffaf2";
  ctx.strokeStyle = "#d5c8b3";
  ctx.beginPath();
  ctx.roundRect(760, 604, 770, 224, 28);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#1e1c18";
  ctx.font = "700 24px Avenir Next, Segoe UI, sans-serif";
  ctx.fillText("Deck-Ready Summary", 794, 648);
  ctx.fillStyle = "#655b4b";
  ctx.font = "500 18px Avenir Next, Segoe UI, sans-serif";
  wrapCanvasText(
    ctx,
    `${model.kpis[0][1]} active issues, ${model.kpis[1][1]} overdue, and ${model.kpis[5][1]} of all issues classified into the CIMO population. Use this slide as the headline snapshot before the detailed KRI slides.`,
    794,
    690,
    690,
    26,
    5,
  );

  const link = document.createElement("a");
  link.href = canvas.toDataURL("image/png");
  link.download = "program-health-slide.png";
  link.click();
}

function buildSlideNotes() {
  const model = buildSlideModel();
  return [
    model.title,
    `As of ${model.asOf}`,
    `Filters: ${model.filters}`,
    "",
    "Health story:",
    ...model.storyLines.map((line) => `- ${line}`),
    "",
    "Key callouts:",
    ...model.highlights.map((line) => `- ${line}`),
    "",
    "Top statuses:",
    ...model.statusTop.map(([label, count]) => `- ${label}: ${count}`),
    "",
    "Top sources:",
    ...model.sourceTop.map(([label, count]) => `- ${label}: ${count}`),
  ].join("\n");
}

function renderKri() {
  const kri = state.dataset?.kri;
  if (!kri) {
    els.kriGrid.innerHTML = `<div class="update-card"><p>KRI metrics are not available for this dataset.</p></div>`;
    return;
  }

  const inventory = kri.issue_inventory_tracking_and_trends || {};
  const overdue = kri.compliance_issues_overdue || {};
  const selfId = kri.self_identified_vs_overall || {};
  const intake = kri.cimo_intake_detection || {};
  const remediationBySeverity = inventory.closure_sla_by_severity || {};

  const severityRows = Object.entries(remediationBySeverity)
    .map(([severity, metric]) => {
      const row = metric.closure || {};
      return `<tr><td>${safe(severity)}</td><td>${safe(row.met)}</td><td>${safe(row.eligible)}</td><td>${formatPercent(row.rate)}</td></tr>`;
    })
    .join("");

  els.kriGrid.innerHTML = `
    <article class="kri-card">
      <h3>1. Inventory Tracking and SLA Adherence</h3>
      <p>Scope: ${safe(inventory.scope_label)} (${safe(inventory.scope_size)} issues)</p>
      <p>Draft logging: avg ${formatMetric(inventory.time_to_draft_logging_days?.average, 1)} days, target ${safe(inventory.time_to_draft_logging_days?.sla_days)} calendar days, SLA ${formatPercent(inventory.time_to_draft_logging_days?.sla_adherence?.rate)}</p>
      <p>RCA completion in SOR: avg ${formatMetric(inventory.time_to_rca_completion_days?.average, 1)} days, target ${safe(inventory.time_to_rca_completion_days?.sla_days)} calendar days, SLA ${formatPercent(inventory.time_to_rca_completion_days?.sla_adherence?.rate)}</p>
      <p>Action plan documentation after Open: avg ${formatMetric(inventory.time_to_action_plan_open_days?.average, 1)} days, target ${safe(inventory.time_to_action_plan_open_days?.sla_days)} calendar days, SLA ${formatPercent(inventory.time_to_action_plan_open_days?.sla_adherence?.rate)}</p>
      <p>Issue closure from Open: avg ${formatMetric(inventory.time_to_issue_closure_days?.average, 1)} days, SLA ${formatPercent(inventory.time_to_issue_closure_days?.sla_adherence?.rate)}</p>
      <div class="table-wrap kri-table-wrap">
        <table>
          <thead>
            <tr><th>Severity</th><th>SLA Met</th><th>Eligible</th><th>Rate</th></tr>
          </thead>
          <tbody>${severityRows || `<tr><td colspan="4">No closure SLA data available.</td></tr>`}</tbody>
        </table>
      </div>
    </article>
    <article class="kri-card">
      <h3>2. Compliance Issues Overdue</h3>
      <p>${safe(overdue.open_compliance_issues_overdue)} of ${safe(overdue.open_compliance_issues)} open issues in the CIMO population are overdue based on issue due date.</p>
      <p class="kri-emphasis">${formatPercent(overdue.percent_overdue)}</p>
    </article>
    <article class="kri-card">
      <h3>3. Self-ID Compared to Overall</h3>
      <p>${safe(selfId.self_identified_issues)} of ${safe(selfId.overall_issues)} issues in the CIMO population were self-identified.</p>
      <p class="kri-emphasis">${formatPercent(selfId.percent_self_identified)}</p>
    </article>
    <article class="kri-card">
      <h3>4. CIMO Intake Detection</h3>
      <p>${safe(intake.detected_issues)} of ${safe(intake.overall_issues)} total issues fall into CIMO intake.</p>
      <p>Owner in Tyler structure: ${safe(intake.owner_in_compliance_hierarchy)} | Approver in Tyler structure: ${safe(intake.approver_in_compliance_hierarchy)} | Compliance L1 risk domain: ${safe(intake.compliance_level_1_risk_domain)}</p>
      <p class="kri-emphasis">${formatPercent(intake.detection_rate)}</p>
    </article>
  `;
}

function groupCounts(rows, key) {
  const groups = new Map();
  rows.forEach((row) => {
    const label = safe(row[key]);
    groups.set(label, (groups.get(label) || 0) + 1);
  });
  return [...groups.entries()].sort((a, b) => b[1] - a[1]);
}

function renderBreakdowns() {
  const rows = getBreakdownRows();
  els.statusTableBody.innerHTML = groupCounts(rows, "status")
    .map(([label, count]) => `<tr><td>${label}</td><td>${count}</td></tr>`)
    .join("");

  els.sourceTableBody.innerHTML = groupCounts(rows, "issue_source")
    .slice(0, 12)
    .map(([label, count]) => `<tr><td>${label}</td><td>${count}</td></tr>`)
    .join("");
}

function renderMeta(lastUpdated) {
  const filtered = state.filteredRows.length;
  const total = state.allRows.length;
  const scoped = state.allRows.filter((r) => r.in_cimo_intake).length;
  const scopeLabel = state.filters.scopeOnly ? `CIMO rows: ${filtered}/${scoped}` : `Rows: ${filtered}/${total}`;
  els.meta.textContent = `${scopeLabel} | Last updated: ${safe(lastUpdated)}`;
}

function redraw(lastUpdated = state.lastUpdated) {
  applyFilters();
  setUrlFilters();
  renderStory();
  renderUpdates();
  renderKpis();
  renderKri();
  renderBreakdowns();
  renderMeta(lastUpdated);
}

function bindEvents() {
  els.scopeOnly.addEventListener("change", (e) => {
    state.filters.scopeOnly = e.target.checked;
    redraw();
  });

  els.search.addEventListener("input", (e) => {
    state.filters.search = e.target.value;
    redraw();
  });

  ["status", "severity", "businessUnit", "riskDomain", "issueSource"].forEach((key) => {
    els[key].addEventListener("change", (e) => {
      state.filters[key] = e.target.value;
      redraw();
    });
  });

  els.reset.addEventListener("click", () => {
    state.filters = { ...DEFAULT_FILTERS };
    hydrateControls();
    redraw();
  });

  els.copyLink.addEventListener("click", async () => {
    await navigator.clipboard.writeText(window.location.href);
    els.copyLink.textContent = "Link copied";
    setTimeout(() => {
      els.copyLink.textContent = "Copy sharable link";
    }, 1000);
  });

  els.downloadCsv.addEventListener("click", () => {
    if (!state.filteredRows.length) return;

    const columns = [
      "issue_id",
      "issue_title",
      "in_program_scope",
      "status",
      "severity",
      "business_unit",
      "risk_domain",
      "issue_source",
      "issue_owner_name",
      "issue_owner_email",
      "due_date",
      "linked_action_plans_open_count",
    ];

    const header = columns.join(",");
    const lines = state.filteredRows.map((r) => columns.map((c) => csvEscape(r[c])).join(","));
    const csv = [header, ...lines].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "program-health-view.csv";
    a.click();
    URL.revokeObjectURL(url);
  });

  els.downloadSlide.addEventListener("click", () => {
    downloadSlidePng();
  });

  els.copySlideNotes.addEventListener("click", async () => {
    const notes = buildSlideNotes();
    await navigator.clipboard.writeText(notes);
    els.copySlideNotes.textContent = "Notes copied";
    setTimeout(() => {
      els.copySlideNotes.textContent = "Copy slide notes";
    }, 1000);
  });

  els.localFile.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      const text = await file.text();
      const data = JSON.parse(text);
      if (!Array.isArray(data.records)) throw new Error("Invalid format: missing records array");
      initializeData(data, true);
    } catch (err) {
      alert(`Unable to load file: ${err.message}`);
    }
  });

  els.loadCsvs.addEventListener("click", async () => {
    const issues = els.issuesFile.files?.[0];
    const hierarchy = els.hierarchyFile.files?.[0];
    if (!issues || !hierarchy) {
      alert("Select both CSV files before loading.");
      return;
    }

    try {
      const [issuesText, hierarchyText] = await Promise.all([issues.text(), hierarchy.text()]);
      const issuesRows = parseCsv(issuesText);
      const hierarchyRows = parseCsv(hierarchyText);
      const requiredIssueCols = [
        "issue_id",
        "issue_title",
        "status",
        "severity",
        "due_date",
        "issue_owner_email",
        "action_owner_email",
      ];
      const requiredHierarchyCols = [
        "employee_email",
        "employee_name",
        "manager_email",
        "manager_name",
        "org_level",
        "department",
      ];

      const missingIssueCols = requiredIssueCols.filter((c) => !(c in (issuesRows[0] || {})));
      const missingHierarchyCols = requiredHierarchyCols.filter((c) => !(c in (hierarchyRows[0] || {})));

      if (missingIssueCols.length || missingHierarchyCols.length) {
        const messages = [];
        if (missingIssueCols.length) messages.push(`raw_issues.csv missing: ${missingIssueCols.join(", ")}`);
        if (missingHierarchyCols.length) messages.push(`hierarchy.csv missing: ${missingHierarchyCols.join(", ")}`);
        throw new Error(messages.join(" | "));
      }

      const records = issuesRows.map((row) => ({
        ...row,
        in_program_scope: true,
        linked_action_plans_open_count: row.linked_action_plans_open_count || row.unresolved_action_plans_count || "0",
      }));

      initializeData(
        {
          last_updated: `${new Date().toISOString().replace("T", " ").slice(0, 16)} UTC`,
          program: { name: "Local dataset", scope_note: "", updates: [] },
          records,
          metrics: {},
        },
        true,
      );
    } catch (err) {
      alert(`Unable to process CSV files: ${err.message}`);
    }
  });
}

function initializeData(data, isLocal = false) {
  state.dataset = data;
  state.allRows = data.records || [];
  state.lastUpdated = isLocal ? `${data.last_updated || "local"} (local file)` : data.last_updated;
  state.filters = { ...DEFAULT_FILTERS, ...getUrlFilters() };

  const programName = data.program?.name || "Program Health Dashboard";
  els.pageTitle.textContent = programName;
  els.pageSubtitle.textContent = data.program?.scope_note || "Scored issue population, health indicators, and monthly narrative updates.";

  hydrateControls();
  redraw();
  if (!state.eventsBound) {
    bindEvents();
    state.eventsBound = true;
  }
}

async function boot() {
  try {
    const response = await fetch(DATA_PATH);
    const data = await response.json();
    initializeData(data);
  } catch (err) {
    document.body.innerHTML = `<main><section class="panel"><h2>Data load failed</h2><p>${err.message}</p><p>Run <code>python3 scripts/build_dashboard_data.py</code> and ensure <code>public/data/dashboard-data.json</code> exists.</p></section></main>`;
  }
}

boot();
