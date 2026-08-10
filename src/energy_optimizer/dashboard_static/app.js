const state = { loaded: new Set(), controllers: new Map(), timers: new Map() };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const svgNS = "http://www.w3.org/2000/svg";

function apiUrl(path, params = {}) {
  const url = new URL(`api/v1/${path}`, document.baseURI);
  Object.entries(params).forEach(([key, value]) => value != null && url.searchParams.set(key, value));
  return url;
}

async function request(key, path, params = {}) {
  state.controllers.get(key)?.abort();
  const controller = new AbortController();
  state.controllers.set(key, controller);
  const response = await fetch(apiUrl(path, params), { signal: controller.signal, cache: "no-store" });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload?.error?.message || "Dashboard data is unavailable.");
  return payload;
}

function localTime(value) {
  return value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: "Australia/Brisbane" }).format(new Date(value)) : "Unavailable";
}

function number(value, digits = 1) { return value == null ? "Unavailable" : Number(value).toLocaleString(undefined, { maximumFractionDigits: digits }); }
function power(value) { return value == null ? "Unavailable" : `${number(value / 1000, 2)} kW`; }
function energy(value) { return value == null ? "Unavailable" : `${number(value, 2)} kWh`; }
function price(value) { return value == null ? "Unavailable" : `${number(value, 3)} AUD/kWh`; }
function percent(value) { return value == null ? "Unavailable" : `${number(value, 1)}%`; }
function age(seconds) { if (seconds == null) return "Unavailable"; if (seconds < 60) return `${Math.round(seconds)} sec`; return `${Math.round(seconds / 60)} min`; }
function safeText(value) {
  const text = value == null || value === "" ? "Unavailable" : String(value);
  return text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function setState(selector, message, kind = "") {
  const node = $(selector); if (!node) return;
  node.textContent = message; node.className = `state-message ${kind}`.trim();
}

function definition(entries) {
  return `<dl class="definition-grid">${entries.map(([term, value]) => `<dt>${term}</dt><dd>${safeText(value)}</dd>`).join("")}</dl>`;
}

async function loadStatus() {
  try {
    const data = await request("status", "status");
    const values = { collector: data.collector_status, database: data.database_status, home_assistant: data.home_assistant_status };
    Object.entries(values).forEach(([key, value]) => {
      const node = $(`[data-status="${key}"]`); const label = key === "home_assistant" ? "Home Assistant" : key === "database" ? "PostgreSQL" : "Collector";
      node.textContent = `${label} · ${value}`; node.className = value === "healthy" ? "ok" : "bad";
    });
    const ageNode = $('[data-status="age"]'); ageNode.textContent = `Last update · ${age(data.observation_age_seconds)} ago`; ageNode.className = data.observation_age_seconds != null && data.observation_age_seconds <= 900 ? "ok" : "bad";
  } catch (error) { setState("#overview-state", error.message, "error-state"); }
}

function kpi(label, value, detail) { return `<article class="kpi"><p class="label">${label}</p><div class="value">${value}</div><p class="detail">${detail}</p></article>`; }

async function loadLive() {
  try {
    const data = await request("live", "live");
    if (!data.available) { setState("#overview-state", "No stored observation is available."); $("#kpis").innerHTML = '<div class="empty-state">Waiting for the first persisted observation.</div>'; return; }
    setState("#overview-state", `Stored slot ${localTime(data.slot_utc)}`);
    $("#latest-data").textContent = `Latest stored slot ${localTime(data.slot_utc)}`;
    $("#kpis").innerHTML = [
      kpi("Battery SOC", percent(data.battery_soc_percent), energy(data.battery_energy_estimate_kwh)),
      kpi("Solar generation", power(data.pv_power_w), "Latest persisted PV power"),
      kpi("House load", power(data.house_consumption_w), `Baseline ${power(data.baseline_house_consumption_w)}`),
      kpi("Grid", data.grid_import_power_w > 0 ? `Import ${power(data.grid_import_power_w)}` : data.grid_export_power_w > 0 ? `Export ${power(data.grid_export_power_w)}` : "Idle", `Raw ${power(data.grid_power_w)}`),
      kpi("Battery flow", data.battery_charge_power_w > 0 ? `Charge ${power(data.battery_charge_power_w)}` : data.battery_discharge_power_w > 0 ? `Discharge ${power(data.battery_discharge_power_w)}` : "Idle", safeText(data.battery_mode)),
      kpi("Amber buy", price(data.amber_buy_price_aud_per_kwh), "Import price"),
      kpi("Amber sell", price(data.amber_sell_price_aud_per_kwh), "Export price"),
      kpi("Balance residual", power(data.energy_balance_residual_w), `Flow health ${data.flow_health?.healthy ? "healthy" : "unhealthy"}`),
    ].join("");
    $("#flow-confidence").textContent = `Signs ${safeText(data.sign_convention_confidence)}`;
    const flows = [
      ["Grid → Home", data.grid_import_power_w], ["Home → Grid", data.grid_export_power_w],
      ["Grid → Battery", data.battery_charge_power_w], ["Battery → Home/Grid", data.battery_discharge_power_w],
    ];
    $("#energy-flow").innerHTML = `
      <div class="flow-node solar"><strong>${power(data.pv_power_w)}</strong><span>Solar</span></div>
      <div class="flow-node battery"><strong>${percent(data.battery_soc_percent)}</strong><span>Battery</span></div>
      <div class="flow-node home"><strong>${power(data.house_consumption_w)}</strong><span>Home</span></div>
      <div class="flow-node grid"><strong>${data.grid_import_power_w > 0 ? "Import" : data.grid_export_power_w > 0 ? "Export" : "Idle"}</strong><span>Grid</span></div>
      <div class="flow-labels">${flows.map(([label, value]) => `<span class="flow-label ${value > 0 ? "" : "inactive"}">${label} · ${power(value)}</span>`).join("")}</div>`;
  } catch (error) { setState("#overview-state", error.message, "error-state"); }
}

async function loadReserve() {
  try {
    const data = await request("reserve", "reserve/latest");
    const summary = $("#overview-reserve"); const content = $("#reserve-content");
    if (!data.available) {
      summary.querySelector(".loading-block")?.remove(); summary.insertAdjacentHTML("beforeend", `<div class="empty-state">${safeText(data.message)}</div>`);
      setState("#reserve-state", data.message); content.innerHTML = '<div class="panel empty-state">No persisted reserve result exists. The dashboard did not run the estimator.</div>'; return;
    }
    const confidence = data.confidence?.level || data.confidence?.confidence || "Unavailable";
    const summaryBody = definition([["Calculated", localTime(data.calculation_timestamp_utc)], ["Capacity-capped reserve", energy(data.capacity_capped_reserve_kwh)], ["Confidence", confidence], ["Next boundary", localTime(data.horizon_end_utc)]]);
    summary.querySelector(".loading-block")?.remove(); summary.querySelector("dl")?.remove(); summary.querySelector(".advisory").insertAdjacentHTML("beforebegin", summaryBody);
    setState("#reserve-state", `Persisted reserve forecast run ${data.forecast_run_id}. Only fields stored by the current schema are shown.`);
    const sections = [
      ["Battery", [["SOC", percent(data.battery_soc_percent)], ["Estimated energy", energy(data.battery_energy_estimate_kwh)], ["Tradable energy", energy(data.potentially_tradable_energy_kwh)]]],
      ["Demand", [["Expected household", energy(data.expected_household_demand_kwh)], ["Expected EV", energy(data.expected_ev_demand_kwh)], ["State source", data.state_source]]],
      ["Reserve", [["Gross requirement", energy(data.gross_reserve_requirement_kwh)], ["Capacity-capped", energy(data.capacity_capped_reserve_kwh)], ["Readiness", data.readiness == null ? "Not persisted" : String(data.readiness)]]],
      ["Opportunity", [["Horizon start", localTime(data.horizon_start_utc)], ["Effective boundary", localTime(data.horizon_end_utc)], ["Opportunity details", "Not persisted"]]],
      ["Confidence", [["Overall", confidence], ["Tier usage", Object.entries(data.forecast_tier_counts).map(([k,v]) => `${k}: ${v}`).join(", ") || "Unavailable"], ["EV warning", "Independent EV telemetry is not persisted with the reserve result"]]],
      ["Persistence", [["Stored fields", data.persisted_fields.join(", ")], ["Command issued", "False"], ["Limitation", "Full ReserveEstimate output is not stored in v0.2.x schema"]]],
    ];
    content.innerHTML = sections.map(([title, rows]) => `<article class="panel"><h3>${title}</h3>${definition(rows)}</article>`).join("");
  } catch (error) { setState("#reserve-state", error.message, "error-state"); }
}

const chartDefinitions = [
  ["House and baseline", "Power (kW)", [["House", "house_consumption_w"], ["Baseline", "baseline_house_consumption_w"]], v => v / 1000],
  ["Solar generation", "Power (kW)", [["PV", "pv_power_w"]], v => v / 1000],
  ["Grid import / export", "Power (kW)", [["Import", "grid_import_power_w"], ["Export", "grid_export_power_w"]], v => v / 1000],
  ["Battery charge / discharge", "Power (kW)", [["Charge", "battery_charge_power_w"], ["Discharge", "battery_discharge_power_w"]], v => v / 1000],
  ["Battery state of charge", "Percent", [["SOC", "battery_soc_percent"]], v => v],
  ["Amber prices", "AUD/kWh", [["Buy", "amber_buy_price_aud_per_kwh"], ["Sell", "amber_sell_price_aud_per_kwh"]], v => v],
];

function makeChart(title, unit, series, points, transform = v => v) {
  const article = document.createElement("article"); article.className = "panel chart-panel";
  article.innerHTML = `<h3>${safeText(title)}</h3><p class="muted">${safeText(unit)} · gaps are not interpolated</p><div class="legend">${series.map(([name], i) => `<span class="series-${i}">${safeText(name)}</span>`).join("")}</div>`;
  const svg = document.createElementNS(svgNS, "svg"); svg.setAttribute("class", "chart"); svg.setAttribute("viewBox", "0 0 760 250"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", `${title} chart with missing observations shown as gaps`);
  const all = series.flatMap(([, field]) => points.map(p => p[field]).filter(v => v != null).map(transform));
  if (!all.length) { article.insertAdjacentHTML("beforeend", '<div class="empty-state">No stored series is available for this period.</div>'); return article; }
  let min = Math.min(...all), max = Math.max(...all); if (min === max) { min -= 1; max += 1; }
  const x = i => 35 + (i / Math.max(points.length - 1, 1)) * 700; const y = v => 220 - ((transform(v) - min) / (max - min)) * 190;
  [[35, 20, 35, 220], [35, 220, 735, 220]].forEach(coords => { const line = document.createElementNS(svgNS, "line"); ["x1","y1","x2","y2"].forEach((name, i) => line.setAttribute(name, coords[i])); line.setAttribute("class", "axis"); svg.append(line); });
  series.forEach(([, field], si) => {
    let segment = [];
    const draw = () => { if (segment.length > 1) { const poly = document.createElementNS(svgNS, "polyline"); poly.setAttribute("points", segment.join(" ")); poly.setAttribute("class", `series-${si}`); svg.append(poly); } segment = []; };
    points.forEach((point, i) => { const value = point[field]; if (!point.has_observation || value == null) { draw(); return; } segment.push(`${x(i)},${y(value)}`); }); draw();
  });
  const chartWrap = document.createElement("div"); chartWrap.className = "chart-wrap";
  const tooltip = document.createElement("div"); tooltip.className = "chart-tooltip"; tooltip.setAttribute("role", "status");
  chartWrap.append(svg, tooltip); article.append(chartWrap);
  svg.addEventListener("pointermove", event => {
    const rect = svg.getBoundingClientRect();
    const index = Math.max(0, Math.min(points.length - 1, Math.round(((event.clientX - rect.left) / rect.width) * (points.length - 1))));
    const point = points[index];
    tooltip.innerHTML = `<strong>${localTime(point.timestamp_utc)}</strong><br>${series.map(([name, field]) => `${safeText(name)}: ${point[field] == null ? "Missing" : `${number(transform(point[field]), 3)} ${safeText(unit)}`}`).join("<br>")}`;
    tooltip.style.display = "block"; tooltip.style.left = `${Math.min(event.clientX - rect.left + 12, rect.width - 180)}px`; tooltip.style.top = `${Math.max(event.clientY - rect.top - 20, 0)}px`;
  });
  svg.addEventListener("pointerleave", () => { tooltip.style.display = "none"; });
  const details = document.createElement("details"); details.className = "table-fallback"; details.innerHTML = `<summary>Accessible data table</summary><div class="table-wrap"><table><thead><tr><th>Time</th>${series.map(([name]) => `<th>${name}</th>`).join("")}</tr></thead><tbody>${points.map(p => `<tr><td>${localTime(p.timestamp_utc)}</td>${series.map(([,field]) => `<td>${p[field] == null ? "Missing" : number(transform(p[field]), 3)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`; article.append(details);
  return article;
}

async function loadHistory() {
  const range = $("#history-range").value; setState("#history-state", "Loading bounded history…"); $("#history-charts").innerHTML = "";
  try {
    const data = await request("history", "timeseries", { range, resolution: "auto" });
    setState("#history-state", `Stored observations from ${localTime(data.requested_start_utc)} to ${localTime(data.requested_end_utc)}.`);
    $("#history-summary").innerHTML = `<span>${data.actual_resolution} resolution</span><span>${data.point_count} chart points</span><span>${number(data.coverage_percent, 1)}% coverage</span><span>${data.missing_slot_count} missing five-minute slots</span>`;
    const root = $("#history-charts"); chartDefinitions.forEach(def => root.append(makeChart(...def.slice(0, 3), data.points, def[3])));
  } catch (error) { setState("#history-state", error.message, "error-state"); $("#history-charts").innerHTML = `<div class="panel error-state">${safeText(error.message)}</div>`; }
}

async function loadForecastRuns() {
  setState("#forecast-state", "Loading existing persisted forecast runs…");
  try {
    const data = await request("forecast-runs", "forecast-runs", { limit: 50 }); const select = $("#forecast-run");
    if (data.empty) { select.innerHTML = '<option value="">No persisted runs</option>'; setState("#forecast-state", "No persisted forecast series is available for this period."); $("#forecast-comparison").innerHTML = '<div class="empty-state">The dashboard did not generate a forecast.</div>'; return; }
    select.innerHTML = data.runs.map(run => `<option value="${run.forecast_run_id}">${safeText(run.forecast_type)} · ${localTime(run.created_at_utc)}</option>`).join("");
    select.dataset.runs = JSON.stringify(data.runs); await loadForecastComparison();
  } catch (error) { setState("#forecast-state", error.message, "error-state"); }
}

async function loadForecastComparison() {
  const id = $("#forecast-run").value; if (!id) return;
  setState("#forecast-state", "Comparing stored forecast points with stored observations (no database write)…");
  try {
    const data = await request("forecast-comparison", "forecast-comparison", { forecast_run_id: id });
    if (!data.available) { setState("#forecast-state", data.message); $("#forecast-comparison").innerHTML = `<div class="empty-state">${safeText(data.message)}</div>`; return; }
    setState("#forecast-state", `${data.sample_count} actual samples; ${data.missing_actual_count} missing actual points.`);
    $("#forecast-run-meta").innerHTML = definition([["Created", localTime(data.created_at_utc)], ["Model", data.model_version], ["Horizon", `${localTime(data.horizon_start_utc)} – ${localTime(data.horizon_end_utc)}`], ["MAE", number(data.mae, 3)], ["Bias", number(data.bias, 3)], ["Unit", data.unit]]);
    const points = data.points.map(p => ({ timestamp_utc: p.period_start_utc, has_observation: p.actual_value != null, expected: p.expected_value, actual: p.actual_value, lower: p.lower_value, upper: p.upper_value }));
    const panel = makeChart("Expected versus actual", data.unit || "Stored unit", [["Expected", "expected"], ["Actual", "actual"], ["Lower bound", "lower"], ["Upper bound", "upper"]], points);
    const target = $("#forecast-comparison"); target.replaceWith(panel); panel.id = "forecast-comparison";
  } catch (error) { setState("#forecast-state", error.message, "error-state"); }
}

async function loadQuality() {
  setState("#quality-state", "Loading bounded collection and health summary…");
  try {
    const data = await request("quality", "data-quality", { range: "30d" }); setState("#quality-state", `Quality from ${localTime(data.range_start_utc)} to ${localTime(data.range_end_utc)}.`);
    const cards = [
      ["Coverage", `${number(data.coverage_percent, 1)}%`, `${data.collected_slots} of ${data.expected_five_minute_slots} slots`],
      ["Missing slots", data.missing_slots, `Longest gap ${data.longest_gap_minutes} min`],
      ["Complete days", data.complete_calendar_days, `${data.complete_overnight_periods} complete overnights`],
      ["Baseline training", data.eligible_baseline_rows, `${Object.values(data.ineligible_baseline_rows_by_reason).reduce((a,b) => a+b,0)} ineligible rows`],
      ["EV telemetry", data.independent_ev_telemetry_available ? "Available" : "Unavailable", data.ev_contamination_warning ? "House load may include EV charging" : "Independent charger power present"],
      ["Balance residual", power(data.average_absolute_balance_residual_w), `Signs: ${Object.entries(data.sign_convention_confidence).map(([k,v]) => `${k} ${v}`).join(", ")}`],
    ];
    const domains = Object.entries(data.domain_health).map(([name, value]) => `<article class="panel"><h3>${safeText(name[0].toUpperCase()+name.slice(1))}</h3>${definition([["Healthy", value.healthy_count], ["Unhealthy", value.unhealthy_count], ["Average score", percent(value.average_score)], ["Warnings", value.warning_count], ["Errors", value.error_count]])}<ul class="issue-list">${value.most_common_issues.slice(0,3).map(issue => `<li>${safeText(issue.code)} · ${issue.count}</li>`).join("") || "<li>No persisted issues</li>"}</ul></article>`).join("");
    $("#quality-content").innerHTML = `<div class="quality-grid">${cards.map(([label,value,detail]) => `<article class="panel"><p class="eyebrow">${safeText(label)}</p><div class="quality-metric">${safeText(value)}</div><p class="muted">${safeText(detail)}</p></article>`).join("")}</div><h3>Domain health</h3><div class="quality-grid">${domains}</div>`;
  } catch (error) { setState("#quality-state", error.message, "error-state"); }
}

function activateTab() {
  const name = location.hash.slice(1) || "overview"; const valid = $("#" + CSS.escape(name)) ? name : "overview";
  $$(".page").forEach(page => page.hidden = page.id !== valid); $$(".tabs a").forEach(link => link.setAttribute("aria-current", link.dataset.tab === valid ? "page" : "false"));
  if (valid === "history" && !state.loaded.has("history")) { state.loaded.add("history"); loadHistory(); }
  if (valid === "forecasts" && !state.loaded.has("forecasts")) { state.loaded.add("forecasts"); loadForecastRuns(); }
  if (valid === "reserve" && !state.loaded.has("reserve")) { state.loaded.add("reserve"); loadReserve(); }
  if (valid === "data-quality" && !state.loaded.has("quality")) { state.loaded.add("quality"); loadQuality(); }
}

function schedule(key, callback, milliseconds) { clearInterval(state.timers.get(key)); state.timers.set(key, setInterval(() => { if (!document.hidden) callback(); }, milliseconds)); }
document.addEventListener("visibilitychange", () => { if (document.hidden) state.controllers.forEach(controller => controller.abort()); else { loadStatus(); loadLive(); } });
window.addEventListener("hashchange", activateTab);
$("#history-range").addEventListener("change", loadHistory);
$("#forecast-run").addEventListener("change", loadForecastComparison);

loadStatus(); loadLive(); loadReserve(); state.loaded.add("reserve"); activateTab();
schedule("status", loadStatus, 30000); schedule("live", loadLive, 30000);
schedule("slow", () => { if (!document.hidden) { if (state.loaded.has("history")) loadHistory(); if (state.loaded.has("forecasts")) loadForecastRuns(); if (state.loaded.has("reserve")) loadReserve(); if (state.loaded.has("quality")) loadQuality(); } }, 300000);
