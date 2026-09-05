const state = { loaded: new Set(), controllers: new Map(), timers: new Map() };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const svgNS = "http://www.w3.org/2000/svg";
const missingDirectionalFlowMessage = "Detailed directional flow breakdown is unavailable for this slot.";
const unconfiguredPowerSignsMessage = "Power sign conventions are not configured, so normalized import/export and charge/discharge values are unavailable.";

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
function money(value) { return value == null ? "Unavailable" : `${number(value, 3)} AUD`; }
function percent(value) { return value == null ? "Unavailable" : `${number(value, 1)}%`; }
function age(seconds) { if (seconds == null) return "Unavailable"; if (seconds < 60) return `${Math.round(seconds)} sec`; return `${Math.round(seconds / 60)} min`; }
function yesNoUnknown(value, yes, no) { return value == null ? "Unknown" : value ? yes : no; }
function safeText(value) {
  const text = value == null || value === "" ? "Unavailable" : String(value);
  return text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function isNumeric(value) { return typeof value === "number" && Number.isFinite(value); }
function absolute(value) { return isNumeric(value) ? Math.abs(value) : null; }

function availabilityLabel(state) {
  const labels = {
    "not-stored": "Not stored",
    unavailable: "Unavailable in this run",
    "not-calculated": "Not calculated",
  };
  return `<span class="availability availability-${state}">${labels[state]}</span>`;
}

function setState(selector, message, kind = "") {
  const node = $(selector); if (!node) return;
  node.textContent = message; node.className = `state-message ${kind}`.trim();
}

function definition(entries) {
  return `<dl class="definition-grid">${entries.map(([term, value, state]) => `<dt>${safeText(term)}</dt><dd>${state && state !== "available" ? availabilityLabel(state) : safeText(value)}</dd>`).join("")}</dl>`;
}

function reserveRow(term, value, formatter = String) {
  return value == null || value === "" ? [term, null, "unavailable"] : [term, formatter(value), "available"];
}

function notStoredRow(term) { return [term, null, "not-stored"]; }

function directionalState(importValue, exportValue, importLabel, exportLabel) {
  if (!isNumeric(importValue) && !isNumeric(exportValue)) return "Unavailable";
  if (importValue > 0) return `${importLabel} ${power(importValue)}`;
  if (exportValue > 0) return `${exportLabel} ${power(exportValue)}`;
  return "Idle";
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
    if (!data.available) {
      setState("#overview-state", "No stored observation is available.");
      $("#kpis").innerHTML = '<div class="empty-state">Waiting for the first persisted observation.</div>';
      $("#energy-flow").innerHTML = '<div class="empty-state flow-empty">Waiting for normalized flow data.</div>';
      $("#flow-note").textContent = missingDirectionalFlowMessage;
      $("#overview-ev").querySelector(".loading-block")?.replaceWith(Object.assign(document.createElement("div"), { className: "empty-state", textContent: "Waiting for the first persisted observation." }));
      return;
    }
    setState("#overview-state", `Stored slot ${localTime(data.slot_utc)}`);
    $("#latest-data").textContent = `Latest stored slot ${localTime(data.slot_utc)}`;
    const gridState = directionalState(data.grid_import_power_w, data.grid_export_power_w, "Import", "Export");
    const batteryState = directionalState(data.battery_charge_power_w, data.battery_discharge_power_w, "Charge", "Discharge");
    const unavailableMetric = '<span class="metric-unavailable">Not available</span>';
    $("#kpis").innerHTML = [
      kpi("Battery SOC", percent(data.battery_soc_percent), energy(data.battery_energy_estimate_kwh)),
      kpi("Solar generation", power(data.pv_power_w), "Latest persisted PV power"),
      kpi("House load", power(data.house_consumption_w), `Baseline ${power(data.baseline_house_consumption_w)}`),
      kpi("Grid", gridState === "Unavailable" ? unavailableMetric : gridState, `Raw ${power(data.grid_power_w)}`),
      kpi("Battery flow", batteryState === "Unavailable" ? unavailableMetric : batteryState, safeText(data.battery_mode)),
      kpi("Amber buy", price(data.amber_buy_price_aud_per_kwh), "Import price"),
      kpi("Amber sell", price(data.amber_sell_price_aud_per_kwh), "Export price"),
      kpi("Balance residual", data.energy_balance_residual_w == null ? unavailableMetric : power(data.energy_balance_residual_w), data.energy_balance_residual_w == null ? "Not available for this slot" : data.flow_health?.healthy == null ? "Flow health not available" : `Flow health ${data.flow_health.healthy ? "healthy" : "unhealthy"}`),
    ].join("");
    const confidence = data.sign_convention_confidence;
    const confidenceUnconfirmed = confidence == null || ["unknown", "unconfirmed"].includes(String(confidence).toLowerCase());
    $("#flow-confidence").textContent = confidenceUnconfirmed ? "Signs unconfirmed" : `Signs ${confidence}`;
    $("#flow-confidence").className = `badge ${confidenceUnconfirmed ? "badge-muted" : "badge-safe"}`;
    const flows = [
      ["Grid → Home", data.grid_import_power_w],
      ["Home → Grid", data.grid_export_power_w],
      ["Grid → Battery", data.battery_charge_power_w],
      ["Battery → Home/Grid", data.battery_discharge_power_w],
    ];
    const availableFlows = flows.filter(([, value]) => isNumeric(value));
    const missingFlowCount = flows.length - availableFlows.length;
    $("#energy-flow").innerHTML = `
      <div class="flow-node solar"><strong>${power(data.pv_power_w)}</strong><span>Solar</span></div>
      <div class="flow-node battery"><strong>${percent(data.battery_soc_percent)}</strong><span>Battery</span></div>
      <div class="flow-node home"><strong>${power(data.house_consumption_w)}</strong><span>Home</span></div>
      <div class="flow-node grid"><strong>${gridState === "Unavailable" ? "—" : gridState}</strong><span>Grid</span></div>
      ${availableFlows.length ? `<div class="flow-labels">${availableFlows.map(([label, value]) => `<span class="flow-label ${value > 0 ? "" : "inactive"}">${label} · ${power(value)}</span>`).join("")}</div>` : ""}`;
    $("#flow-note").textContent = missingFlowCount === flows.length
      ? data.sign_convention_status === "unconfirmed" ? unconfiguredPowerSignsMessage : missingDirectionalFlowMessage
      : missingFlowCount
        ? "Some detailed directional flow values are unavailable for this slot."
        : "Directions use persisted normalized flow fields.";
    const evCard = $("#overview-ev");
    evCard.querySelector(".loading-block")?.remove(); evCard.querySelector("dl")?.remove(); evCard.querySelector(".empty-state")?.remove(); evCard.querySelector(".ev-help")?.remove();
    const freshness = $("#ev-freshness");
    if (!data.ev_vehicle_configured) {
      freshness.textContent = "Disabled"; freshness.className = "badge badge-muted";
      evCard.insertAdjacentHTML("beforeend", '<div class="empty-state">Vehicle telemetry is disabled or not configured.</div>');
    } else {
      freshness.textContent = data.ev_telemetry_fresh ? "Fresh" : data.ev_vehicle_status === "stale" ? "Stale" : "Unavailable";
      freshness.className = `badge ${data.ev_telemetry_fresh ? "badge-safe" : "badge-muted"}`;
      evCard.insertAdjacentHTML("beforeend", definition([
        ["Vehicle SOC", percent(data.ev_vehicle_soc_percent)],
        ["Location", yesNoUnknown(data.ev_at_home, "At home", "Away")],
        ["Connection", yesNoUnknown(data.ev_plugged_in, "Plugged in", "Unplugged")],
        ["Charging", yesNoUnknown(data.ev_charging_active, "Charging", "Not charging")],
        ["Vehicle cloud", yesNoUnknown(data.ev_vehicle_online, "Online", "Offline")],
        ["Telemetry age", age(data.ev_telemetry_age_seconds)],
        ["Vehicle battery power (raw)", power(data.ev_vehicle_battery_power_w_raw)],
      ]));
      evCard.insertAdjacentHTML("beforeend", '<p class="ev-help">Vehicle battery power is vehicle-side/raw telemetry and is not treated as charger AC demand.</p>');
    }
  } catch (error) { setState("#overview-state", error.message, "error-state"); }
}

async function loadReserve() {
  try {
    const data = await request("reserve", "reserve/latest");
    const summary = $("#overview-reserve"); const content = $("#reserve-content");
    summary.querySelector(".loading-block")?.remove(); summary.querySelector("dl")?.remove(); summary.querySelector(".empty-state")?.remove();
    if (!data.available) {
      summary.querySelector(".advisory").insertAdjacentHTML("beforebegin", `<div class="empty-state">${safeText(data.message)}</div>`);
      setState("#reserve-state", data.message); content.innerHTML = '<div class="panel empty-state schema-notice">No persisted reserve result exists. The dashboard did not run the estimator.</div>'; return;
    }
    const confidence = data.confidence?.rating || data.confidence?.level || data.confidence?.confidence;
    const completeAudit = (data.persisted_fields || []).includes("recommended_reserve_kwh");
    const tierUsage = Object.entries(data.forecast_tier_counts || {}).map(([key, value]) => `${key}: ${value}`).join(", ");
    const storedFields = (data.persisted_fields || []).map(field => field.replaceAll("_", " ")).join(", ");
    const summaryBody = definition([
      reserveRow("Calculated", data.calculation_timestamp_utc, localTime),
      reserveRow("Capacity-capped reserve", data.capacity_capped_reserve_kwh, energy),
      reserveRow("Confidence", confidence),
      reserveRow("Next boundary", data.horizon_end_utc, localTime),
    ]);
    summary.querySelector(".advisory").insertAdjacentHTML("beforebegin", summaryBody);
    setState("#reserve-state", completeAudit ? `Complete advisory reserve audit associated with forecast run ${data.forecast_run_id}.` : `Legacy partial reserve forecast run ${data.forecast_run_id}.`);
    const sections = completeAudit ? [
      ["Battery", "Stored battery state at the evaluation timestamp.", [reserveRow("SOC", data.battery_soc_percent, percent), reserveRow("Estimated energy", data.battery_energy_estimate_kwh, energy), reserveRow("Tradable energy", data.potentially_tradable_energy_kwh, energy)]],
      ["Demand", "Existing estimator demand components.", [reserveRow("Expected household", data.expected_household_demand_kwh, energy), reserveRow("Expected EV", data.expected_ev_demand_kwh, energy), reserveRow("State source", data.state_source)]],
      ["Reserve", "Complete advisory requirement and readiness.", [reserveRow("Technical minimum", data.technical_reserve_kwh, energy), reserveRow("Emergency", data.emergency_reserve_kwh, energy), reserveRow("Uncertainty", data.uncertainty_buffer_kwh, energy), reserveRow("Gross requirement", data.gross_reserve_requirement_kwh, energy), reserveRow("Recommended", data.recommended_reserve_kwh, energy), reserveRow("Current shortfall", data.current_reserve_shortfall_kwh, energy), ["Ready for manual review", data.readiness ? "Yes" : "No", "available"]]],
      ["Opportunity", "Persisted candidate and effective reserve boundary.", [reserveRow("State", data.opportunity_state), reserveRow("First candidate", data.first_candidate?.expected_start_local, localTime), reserveRow("Effective boundary", data.effective_boundary?.expected_start_local, localTime), reserveRow("Horizon end", data.horizon_end_utc, localTime)]],
      ["Confidence", "Calibration evidence is diagnostic only and does not alter reserve arithmetic.", [reserveRow("Overall", confidence), reserveRow("Vehicle SOC (context only)", data.ev_vehicle_soc_percent, percent), reserveRow("Forecast calibration", data.forecast_calibration_status), reserveRow("Linked identity matches", data.linked_forecast_identity_matches_calibration ? "Yes" : "No"), reserveRow("WAPE", data.calibration_wape_percent, percent), reserveRow("Signed energy error", data.calibration_signed_energy_error_kwh, energy), reserveRow("P90 / P95 underforecast", `${energy(data.empirical_underforecast_p90_kwh)} / ${energy(data.empirical_underforecast_p95_kwh)}`), reserveRow("Tradable calibration reason", data.tradable_calibration_reason)]],
      ["Persistence", "Complete v0.5.0 audit record.", [["Command issued", "No", "available"], ["Complete estimate", "Stored", "available"]]],
    ] : [
      ["Battery", "Battery state was not part of the persisted reserve-result record.", [notStoredRow("SOC"), notStoredRow("Estimated energy"), notStoredRow("Tradable energy")]],
      ["Demand", "Only demand values recorded with this forecast run can be shown.", [reserveRow("Expected household", data.expected_household_demand_kwh, energy), notStoredRow("Expected EV"), reserveRow("State source", data.state_source)]],
      ["Reserve", "Stored reserve requirements remain advisory.", [reserveRow("Gross requirement", data.gross_reserve_requirement_kwh, energy), reserveRow("Capacity-capped", data.capacity_capped_reserve_kwh, energy), notStoredRow("Readiness")]],
      ["Opportunity", "Opportunity reasoning is not stored by the current schema.", [reserveRow("Horizon start", data.horizon_start_utc, localTime), reserveRow("Effective boundary", data.horizon_end_utc, localTime), notStoredRow("Opportunity details")]],
      ["Confidence", "Vehicle SOC is context only and does not change the reserve algorithm.", [reserveRow("Overall", confidence), reserveRow("Tier usage", tierUsage), reserveRow("Vehicle SOC (context only)", data.ev_vehicle_soc_percent, percent)]],
      ["Persistence", "The complete ReserveEstimate output is not stored by the current schema.", [reserveRow("Stored fields", storedFields), ["Command issued", "No", "available"], ["Full estimate", null, "not-stored"]]],
    ];
    const calibrationWarning = data.calibration_warning ? `<aside class="panel schema-notice" role="note"><strong>Forecast calibration: ${safeText(data.forecast_calibration_status)}</strong><p>${safeText(data.calibration_warning)}</p></aside>` : "";
    content.innerHTML = `${calibrationWarning}<aside class="panel schema-notice" role="note"><strong>${completeAudit ? "Complete advisory audit" : "Legacy stored result coverage"}</strong><p>${completeAudit ? "The complete typed estimator output is persisted separately from immutable forecast values." : "Missing stored values are labelled separately from fields the legacy schema did not store."}</p></aside>${sections.map(([title, help, rows]) => `<article class="panel reserve-card"><h3>${title}</h3><p class="section-help">${help}</p>${definition(rows)}</article>`).join("")}`;
  } catch (error) { setState("#reserve-state", error.message, "error-state"); }
}

async function loadShadowOverview() {
  const target = $("#overview-shadow");
  try {
    const data = await request("shadow-overview", "decisions/latest");
    target.querySelector(".loading-block")?.remove(); target.querySelector(".shadow-body")?.remove();
    const body = document.createElement("div"); body.className = "shadow-body";
    if (!data.available) {
      body.innerHTML = `<div class="empty-state">${safeText(data.message)}</div><div class="no-command-banner">Shadow only &mdash; no command issued</div>`;
    } else {
      const decision = data.decision; const selected = (decision.candidates || []).find(item => item.action === decision.selected_action);
      body.innerHTML = `<div class="decision-action">${safeText(decision.selected_action || "No recommendation")}</div>${definition([
        ["Decision time", localTime(decision.created_at_utc)],
        ["Action window", decision.selected_start_utc ? `${localTime(decision.selected_start_utc)} - ${localTime(decision.selected_end_utc)}` : "Unavailable"],
        ["Expected energy", energy(absolute(decision.selected_battery_energy_kwh))],
        ["Expected gross value", money(decision.expected_gross_value_aud)],
        ["Reserve margin after", energy(selected?.reserve_margin_after_kwh)],
        ["Confidence", decision.confidence_rating],
        ["Reason", (decision.reason_codes_json || []).join(", ")],
      ])}<div class="no-command-banner">Shadow only &mdash; no command issued</div>${decision.non_hold_selection_enabled ? "" : '<p class="muted">Candidate analysis is active. Selected recommendation is forced to HOLD.</p>'}`;
    }
    target.append(body);
  } catch (error) {
    target.querySelector(".loading-block")?.remove();
    target.insertAdjacentHTML("beforeend", `<div class="error-state">${safeText(error.message)}</div>`);
  }
}

async function loadForecastActualCard() {
  const modeSelect = $("#forecast-card-mode");
  const target = $("#forecast-card-content");
  const mode = modeSelect.value || "live";
  target.className = "loading-block"; target.textContent = "Loading forecast comparison...";
  try {
    const data = await request("forecast-card", "forecast-comparison-card", { mode });
    target.className = "forecast-card-body"; target.innerHTML = "";
    if (data.empty_state) {
      target.innerHTML = `<div class="empty-state chart-empty"><strong>${safeText(data.empty_state.message)}</strong><span>The dashboard does not generate or select a different run.</span></div>`;
      return;
    }
    const metric = data.metrics; const coverage = data.coverage; const identity = data.identity;
    target.insertAdjacentHTML("beforeend", `${definition([
      ["Forecast run created", localTime(data.created_at_utc)],
      ["Forecast horizon", `${localTime(data.period_start_utc)} - ${localTime(data.period_end_utc)}`],
      ["Model version", identity.model_version], ["Alignment version", identity.alignment_version], ["Training policy", identity.training_policy],
      ["Elapsed actual coverage", percent(coverage.matured_actual_coverage_percent)],
      ["Forecast energy", energy(metric.forecast_energy_kwh)], ["Actual energy", energy(metric.actual_energy_kwh)],
      ["Signed energy error", energy(metric.signed_energy_error_kwh)], ["Error sign", "Actual minus forecast"],
      ["MAE", power(metric.mae_w)], ["Bias", power(metric.bias_w)], ["WAPE", percent(metric.wape_percent)], ["Calibration", data.calibration_status],
    ])}<p class="muted">${safeText(metric.period_label)}. Future actuals remain missing.</p>`);
    const points = data.points.map(point => ({
      timestamp_utc: point.period_start_utc, has_observation: true,
      expected: point.forecast_w, actual: point.actual_w, lower: point.lower_w, upper: point.upper_w,
      actual_missing_reason: point.actual_missing_reason,
      series_available: { expected: true, actual: point.actual_eligible, lower: point.lower_w != null, upper: point.upper_w != null },
    }));
    const start = new Date(data.period_start_utc).getTime(); const end = new Date(data.period_end_utc).getTime(); const now = new Date(data.now_utc).getTime();
    const nowPercent = end > start ? (now - start) / (end - start) * 100 : null;
    const chart = makeChart("Forecast expected and actual household demand", "kW", [["Forecast expected", "expected"], ["Actual household demand", "actual"], ["Forecast lower", "lower"], ["Forecast upper", "upper"]], points, value => value / 1000, "No comparable forecast and actual intervals are available.", { band: ["lower", "upper"], nowPercent: mode === "live" ? nowPercent : null });
    target.append(chart);
  } catch (error) {
    target.className = "error-state"; target.textContent = error.message;
  }
}

async function loadDecisions() {
  setState("#decisions-state", "Loading immutable shadow decisions and outcomes...");
  try {
    const [latest, history, outcomes] = await Promise.all([
      request("decision-latest", "decisions/latest"),
      request("decision-history", "decisions", { limit: 50 }),
      request("decision-outcomes", "decision-outcomes", { limit: 100 }),
    ]);
    if (!latest.available) {
      setState("#decisions-state", latest.message);
      $("#decision-current").innerHTML = `<article class="panel empty-state">${safeText(latest.message)}</article>`;
      $("#decision-candidates").innerHTML = '<div class="empty-state">No candidate analysis is stored.</div>';
      $("#decision-provenance").innerHTML = "";
    } else {
      const decision = latest.decision; const selected = (decision.candidates || []).find(item => item.action === decision.selected_action);
      setState("#decisions-state", `${safeText(decision.status)} decision at ${localTime(decision.decision_boundary_utc)}. No command was issued.`);
      $("#decision-current").innerHTML = [
        ["Current recommendation", decision.selected_action || "No recommendation", (decision.reason_codes_json || []).join(", ") || "No reason available"],
        ["Expected gross value", money(decision.expected_gross_value_aud), `Energy ${energy(absolute(decision.selected_battery_energy_kwh))}`],
        ["Reserve margin", energy(selected?.reserve_margin_after_kwh), `Confidence ${decision.confidence_rating || "Unavailable"}`],
        ["Action window", decision.selected_start_utc ? `${localTime(decision.selected_start_utc)} - ${localTime(decision.selected_end_utc)}` : "Unavailable", "Advisory interval only"],
        ["Data and price", localTime(decision.input_snapshot_json?.observation_collected_at_utc), `Price horizon ${localTime(decision.price_horizon_end_utc)}`],
        ["Policy", decision.policy_version, `Assumptions ${decision.assumption_set_version}`],
      ].map(([label, value, detail]) => `<article class="panel"><p class="eyebrow">${safeText(label)}</p><div class="quality-metric decision-action">${safeText(value)}</div><p class="muted">${safeText(detail)}</p>${label === "Current recommendation" ? '<div class="no-command-banner">Shadow only &mdash; no command issued</div>' : ""}</article>`).join("");
      $("#decision-candidates").innerHTML = `<div class="table-wrap"><table><thead><tr><th>Action</th><th>Feasible</th><th>Rank</th><th>Expected gross value</th><th>Battery energy</th><th>Reserve margin</th><th>Blocking reason</th><th>Warnings</th></tr></thead><tbody>${decision.candidates.map(item => `<tr><td>${safeText(item.action)}</td><td class="${item.feasible ? "candidate-feasible" : "candidate-blocked"}">${item.feasible ? "Yes" : "No"}</td><td>${item.candidate_rank ?? "&mdash;"}</td><td>${money(item.gross_incremental_value_aud)}</td><td>${energy(item.battery_energy_delta_kwh)}</td><td>${energy(item.reserve_margin_after_kwh)}</td><td>${safeText((item.blocking_constraints_json || []).join(", ") || item.feasibility_reason)}</td><td>${safeText((item.warning_constraints_json || []).join(", ") || "None")}</td></tr>`).join("")}</tbody></table></div>`;
      const input = decision.input_snapshot_json || {}; const solar = input.solar || {}; const calibration = input.calibration || {};
      $("#decision-provenance").innerHTML = [
        ["Linked records", `Observation ${safeText(input.observation_slot_utc)}`, `Forecast ${decision.forecast_run_id}; reserve ${decision.reserve_run_id}`],
        ["Calibration identity", `${safeText(decision.model_version)} / ${safeText(decision.alignment_version)}`, `Policy ${decision.training_policy}; tradable ${decision.tradable_calibrated ? "yes" : "no"}`],
        ["Calibration gate", calibration.status || "Unavailable", (calibration.quality_blocks || []).join(", ") || "No quality block"],
        ["Price horizon", localTime(decision.price_horizon_end_utc), `Input hash ${String(decision.input_hash).slice(0, 12)}...`],
        ["Solcast context", `${energy(solar.p10_kwh)} / ${energy(solar.p50_kwh)} / ${energy(solar.p90_kwh)}`, `${solar.constraint_context || "Unavailable"}; confidence capped ${solar.confidence_limit || "low"}`],
        ["Assumptions", decision.assumption_set_version, `${decision.assumption_snapshot_json?.items?.length || 0} unit-explicit items`],
      ].map(([label, value, detail]) => `<article class="panel"><p class="eyebrow">${safeText(label)}</p><div class="quality-metric">${safeText(value)}</div><p class="muted">${safeText(detail)}</p></article>`).join("");
    }
    $("#decision-history").innerHTML = history.empty ? '<div class="empty-state">No shadow decision history is available.</div>' : `<div class="table-wrap"><table><thead><tr><th>Boundary</th><th>Selected</th><th>Expected gross value</th><th>Confidence</th><th>Status</th><th>Outcome</th></tr></thead><tbody>${history.decisions.map(item => `<tr><td>${localTime(item.decision_boundary_utc)}</td><td>${safeText(item.selected_action || "None")}</td><td>${money(item.expected_gross_value_aud)}</td><td>${safeText(item.confidence_rating)}</td><td>${safeText(item.status)}</td><td>${item.latest_outcome_scored_at_utc ? `Scored ${localTime(item.latest_outcome_scored_at_utc)}` : "Unscored"}</td></tr>`).join("")}</tbody></table></div>`;
    $("#decision-outcomes").innerHTML = outcomes.empty ? '<div class="empty-state">No decision interval has matured for outcome scoring yet.</div>' : `<div class="table-wrap"><table><thead><tr><th>Scored</th><th>Selected vs HOLD</th><th>Hindsight</th><th>Regret</th><th>Reserve breach</th><th>Coverage</th><th>Confidence</th><th>Intervention</th></tr></thead><tbody>${outcomes.outcomes.map(item => `<tr><td>${localTime(item.scored_at_utc)}</td><td>${money(item.selected_vs_hold_value_aud)}</td><td>${safeText(item.hindsight_best_action)} &middot; ${money(item.hindsight_best_value_aud)}</td><td>${money(item.regret_aud)}</td><td>${item.simulated_reserve_breach == null ? "Unavailable" : item.simulated_reserve_breach ? "Possible" : "No"}</td><td>${percent(item.actual_coverage_percent)}</td><td>${safeText(item.counterfactual_confidence)}</td><td>${item.operator_intervention_possible ? `Possible (${safeText(item.operator_intervention_confidence)})` : "Not detected"}</td></tr>`).join("")}</tbody></table></div><p class="muted">All counterfactual values are simulated and are not definitive physical outcomes.</p>`;
  } catch (error) {
    setState("#decisions-state", error.message, "error-state");
  }
}

const chartDefinitions = [
  ["House and baseline", "Power (kW)", [["House", "house_consumption_w"], ["Baseline", "baseline_house_consumption_w"]], v => v / 1000],
  ["Solar generation", "Power (kW)", [["PV", "pv_power_w"]], v => v / 1000],
  ["Grid import / export", "Power (kW)", [["Import", "grid_import_power_w"], ["Export", "grid_export_power_w"]], v => v / 1000, "No grid import/export data is available for this period."],
  ["Battery charge / discharge", "Power (kW)", [["Charge", "battery_charge_power_w"], ["Discharge", "battery_discharge_power_w"]], v => v / 1000, "No battery charge/discharge data is available for this period."],
  ["Battery state of charge", "Percent", [["SOC", "battery_soc_percent"]], v => v],
  ["EV state of charge", "Percent", [["Vehicle SOC", "ev_vehicle_soc_percent"]], v => v, "No vehicle SOC data is available for this period."],
  ["Amber prices", "AUD/kWh", [["Buy", "amber_buy_price_aud_per_kwh"], ["Sell", "amber_sell_price_aud_per_kwh"]], v => v],
];

function chartAxisTime(value) {
  return value ? new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZone: "Australia/Brisbane" }).format(new Date(value)) : "";
}

function makeChart(title, unit, series, points, transform = value => value, emptyMessage = "No chartable data is available for this period.", options = {}) {
  const article = document.createElement("article"); article.className = "panel chart-panel";
  const plottedValue = (point, field) => {
    const available = point.series_available ? point.series_available[field] !== false : point.has_observation;
    return available && isNumeric(point[field]) ? transform(point[field]) : null;
  };
  const chartableSeries = series.map(([name, field], index) => ({ name, field, index })).filter(item => points.some(point => isNumeric(plottedValue(point, item.field))));
  article.innerHTML = `<h3>${safeText(title)}</h3><p class="muted">${safeText(unit)} · gaps are not interpolated</p>`;
  const details = document.createElement("details"); details.className = "table-fallback"; details.innerHTML = `<summary>Accessible data table</summary><div class="table-wrap"><table><thead><tr><th>Time</th>${series.map(([name]) => `<th>${safeText(name)}</th>`).join("")}</tr></thead><tbody>${points.length ? points.map(point => `<tr><td>${localTime(point.timestamp_utc)}</td>${series.map(([, field]) => `<td>${plottedValue(point, field) == null ? "Missing" : number(transform(point[field]), 3)}</td>`).join("")}</tr>`).join("") : `<tr><td colspan="${series.length + 1}">No stored rows for this period</td></tr>`}</tbody></table></div>`;
  if (!chartableSeries.length) {
    article.classList.add("chart-panel-empty");
    article.insertAdjacentHTML("beforeend", `<div class="empty-state chart-empty" role="status"><strong>${safeText(emptyMessage)}</strong><span>Historical collection gaps and unavailable normalized flow values are shown as missing.</span></div>`);
    article.append(details);
    return article;
  }
  article.insertAdjacentHTML("beforeend", `<div class="legend">${chartableSeries.map(item => `<span class="series-${item.index}">${safeText(item.name)}</span>`).join("")}</div>`);
  const svg = document.createElementNS(svgNS, "svg"); svg.setAttribute("class", "chart"); svg.setAttribute("viewBox", "0 0 760 250"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", `${title} chart with missing observations shown as gaps`);
  svg.setAttribute("tabindex", "0");
  const all = chartableSeries.flatMap(item => points.map(point => plottedValue(point, item.field)).filter(isNumeric));
  let min = Math.min(...all), max = Math.max(...all); if (min === max) { min -= 1; max += 1; }
  const x = index => 35 + (index / Math.max(points.length - 1, 1)) * 700; const y = value => 220 - ((value - min) / (max - min)) * 190;
  [[35, 20, 35, 220], [35, 220, 735, 220]].forEach(coords => { const line = document.createElementNS(svgNS, "line"); ["x1", "y1", "x2", "y2"].forEach((name, index) => line.setAttribute(name, coords[index])); line.setAttribute("class", "axis"); svg.append(line); });
  if (options.band && points.some(point => isNumeric(plottedValue(point, options.band[0])) && isNumeric(plottedValue(point, options.band[1])))) {
    let bandSegment = [];
    const drawBand = () => {
      if (bandSegment.length > 1) {
        const polygon = document.createElementNS(svgNS, "polygon");
        const upper = bandSegment.map(item => `${item.x},${y(item.upper)}`);
        const lower = [...bandSegment].reverse().map(item => `${item.x},${y(item.lower)}`);
        polygon.setAttribute("points", [...upper, ...lower].join(" "));
        polygon.setAttribute("class", "uncertainty-band"); svg.append(polygon);
      }
      bandSegment = [];
    };
    points.forEach((point, pointIndex) => {
      const lower = plottedValue(point, options.band[0]); const upper = plottedValue(point, options.band[1]);
      if (!isNumeric(lower) || !isNumeric(upper)) { drawBand(); return; }
      bandSegment.push({ x: x(pointIndex), lower, upper });
    }); drawBand();
  }
  chartableSeries.forEach(({ field, index }) => {
    let segment = [];
    const draw = () => {
      if (segment.length > 1) {
        const poly = document.createElementNS(svgNS, "polyline"); poly.setAttribute("points", segment.join(" ")); poly.setAttribute("class", `series-${index}`); svg.append(poly);
      } else if (segment.length === 1) {
        const [cx, cy] = segment[0].split(","); const point = document.createElementNS(svgNS, "circle"); point.setAttribute("cx", cx); point.setAttribute("cy", cy); point.setAttribute("r", "3.5"); point.setAttribute("class", `series-${index}`); svg.append(point);
      }
      segment = [];
    };
    points.forEach((point, pointIndex) => { const value = plottedValue(point, field); if (!isNumeric(value)) { draw(); return; } segment.push(`${x(pointIndex)},${y(value)}`); }); draw();
  });
  if (isNumeric(options.nowPercent)) {
    const marker = document.createElementNS(svgNS, "line"); const markerX = 35 + Math.max(0, Math.min(100, options.nowPercent)) / 100 * 700;
    marker.setAttribute("x1", markerX); marker.setAttribute("x2", markerX); marker.setAttribute("y1", "20"); marker.setAttribute("y2", "220"); marker.setAttribute("class", "now-marker"); svg.append(marker);
  }
  [0, Math.floor((points.length - 1) / 2), points.length - 1].filter((value, index, values) => value >= 0 && values.indexOf(value) === index).forEach(pointIndex => {
    const label = document.createElementNS(svgNS, "text"); label.setAttribute("x", x(pointIndex)); label.setAttribute("y", "240"); label.setAttribute("text-anchor", pointIndex === 0 ? "start" : pointIndex === points.length - 1 ? "end" : "middle"); label.setAttribute("class", "chart-axis-label"); label.textContent = chartAxisTime(points[pointIndex]?.timestamp_utc); svg.append(label);
  });
  const chartWrap = document.createElement("div"); chartWrap.className = "chart-wrap";
  const tooltip = document.createElement("div"); tooltip.className = "chart-tooltip"; tooltip.setAttribute("role", "status");
  chartWrap.append(svg, tooltip); article.append(chartWrap);
  let keyboardIndex = 0;
  const showTooltip = (index, left, top) => {
    keyboardIndex = index;
    const point = points[index];
    tooltip.innerHTML = `<strong>${localTime(point.timestamp_utc)}</strong><br>${chartableSeries.map(({ name, field }) => `${safeText(name)}: ${plottedValue(point, field) == null ? "Missing" : `${number(plottedValue(point, field), 3)} ${safeText(unit)}`}`).join("<br>")}${point.actual_missing_reason ? `<br>Actual eligibility: ${safeText(point.actual_missing_reason)}` : ""}`;
    tooltip.style.display = "block"; tooltip.style.left = `${left}px`; tooltip.style.top = `${top}px`;
  };
  svg.addEventListener("pointermove", event => {
    const rect = svg.getBoundingClientRect();
    const index = Math.max(0, Math.min(points.length - 1, Math.round(((event.clientX - rect.left) / rect.width) * (points.length - 1))));
    showTooltip(index, Math.min(event.clientX - rect.left + 12, rect.width - 180), Math.max(event.clientY - rect.top - 20, 0));
  });
  svg.addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    keyboardIndex = event.key === "Home" ? 0 : event.key === "End" ? points.length - 1 : Math.max(0, Math.min(points.length - 1, keyboardIndex + (event.key === "ArrowLeft" ? -1 : 1)));
    showTooltip(keyboardIndex, Math.min(x(keyboardIndex) + 8, 560), 20);
  });
  svg.addEventListener("pointerleave", () => { tooltip.style.display = "none"; });
  article.append(details);
  return article;
}

function makeEVTimeline(points) {
  const article = document.createElement("article"); article.className = "panel chart-panel";
  article.innerHTML = '<h3>EV connection history</h3><p class="muted">Fresh vehicle-reported charging and plugged states only. Missing states remain unknown.</p>';
  const marked = points.filter(point => point.ev_charging_active === true || point.ev_plugged_in === true);
  if (!marked.length) {
    article.insertAdjacentHTML("beforeend", '<div class="empty-state chart-empty" role="status"><strong>No EV state markers</strong><span>No fresh plugged or charging state is stored for this period.</span></div>');
    return article;
  }
  article.insertAdjacentHTML("beforeend", `<div class="ev-timeline">${marked.map(point => `<span class="ev-marker ${point.ev_charging_active ? "charging" : "plugged"}">${safeText(localTime(point.timestamp_utc))} · ${point.ev_charging_active ? "Charging" : "Plugged idle"}</span>`).join("")}</div>`);
  return article;
}

async function loadHistory() {
  const range = $("#history-range").value; setState("#history-state", "Loading bounded history…"); $("#history-charts").innerHTML = "";
  try {
    const data = await request("history", "timeseries", { range, resolution: "auto" });
    setState("#history-state", `Stored observations from ${localTime(data.requested_start_utc)} to ${localTime(data.requested_end_utc)}.`);
    $("#history-summary").innerHTML = `<span>${data.actual_resolution} resolution</span><span>${data.point_count} chart points</span><span>${number(data.coverage_percent, 1)}% coverage</span><span>${data.missing_slot_count} missing five-minute slots</span>`;
    const root = $("#history-charts"); chartDefinitions.forEach(def => {
      const normalizedFlowChart = def[0] === "Grid import / export" || def[0] === "Battery charge / discharge";
      const emptyMessage = normalizedFlowChart && data.normalized_flow_unavailable_due_to_unconfigured_signs ? unconfiguredPowerSignsMessage : def[4];
      root.append(makeChart(def[0], def[1], def[2], data.points, def[3], emptyMessage));
    }); root.append(makeEVTimeline(data.points));
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

function metricCard(label, metric) {
  return `<article class="panel"><p class="eyebrow">${safeText(label)}</p>${definition([
    ["MAE", metric.mae == null ? "Unavailable" : power(metric.mae)],
    ["Bias", metric.bias == null ? "Unavailable" : power(metric.bias)],
    ["RMSE", metric.rmse == null ? "Unavailable" : power(metric.rmse)],
    ["Coverage", `${number(metric.coverage_percent, 1)}%`],
    ["Samples", `${metric.sample_count} / ${metric.total_count}`],
  ])}</article>`;
}

async function loadForecastOperations() {
  setState("#operations-state", "Loading scheduler audit and scored points...");
  try {
    const selectedRun = $("#accuracy-run").value || null;
    const [operations, accuracy, runs] = await Promise.all([
      request("operations-status", "forecast-operations/status"),
      request("forecast-accuracy", "forecast-accuracy", { range: $("#accuracy-range").value, forecast_run_id: selectedRun }),
      request("accuracy-runs", "forecast-runs", { forecast_type: "baseline_household_load", limit: 100 }),
    ]);
    const runSelect = $("#accuracy-run");
    runSelect.innerHTML = `<option value="">All scheduled runs</option>${runs.runs.map(run => `<option value="${run.forecast_run_id}">${localTime(run.created_at_utc)} | ${safeText(run.model_version)}</option>`).join("")}`;
    runSelect.value = selectedRun || "";
    const last = operations.last_attempt;
    $("#operations-status").innerHTML = [
      ["Coordinator", operations.enabled ? operations.scheduler_status : "Disabled", operations.enabled ? "One in-process coordinator" : "Opt-in option is off"],
      ["Last attempt", last ? localTime(last.started_at_utc) : "No attempts", last ? `${last.status} - ${number(last.duration_seconds, 1)} sec` : "Waiting for first aligned boundary"],
      ["Last success", operations.last_successful_run ? localTime(operations.last_successful_run.finished_at_utc) : "None", operations.last_successful_run ? `${operations.last_successful_run.forecast_point_count} points` : "No successful scheduled run"],
      ["Next run", operations.next_scheduled_run_utc ? localTime(operations.next_scheduled_run_utc) : "Not scheduled", "Collector receives a 20-second boundary grace period"],
      ["Reserve", operations.reserve_scheduler_status, "Advisory snapshot only"],
      ["Failure", last?.failure_summary || "None", "Secret-safe bounded summary"],
    ].map(([label, value, detail]) => `<article class="panel"><p class="eyebrow">${safeText(label)}</p><div class="quality-metric">${safeText(value)}</div><p class="muted">${safeText(detail)}</p></article>`).join("");
    if (!accuracy.available) {
      setState("#operations-state", `${operations.enabled ? "Scheduler enabled." : "Scheduler disabled."} ${accuracy.message}`);
      $("#accuracy-summary").innerHTML = "";
      $("#accuracy-content").innerHTML = `<div class="panel empty-state">${safeText(accuracy.message)}</div>`;
      return;
    }
    setState("#operations-state", "Completed points are scored after the configured delay; missing and unhealthy actuals are excluded from errors.");
    $("#accuracy-summary").innerHTML = `<span>MAE ${power(accuracy.metrics.mae)}</span><span>Bias ${power(accuracy.metrics.bias)}</span><span>RMSE ${power(accuracy.metrics.rmse)}</span><span>Coverage ${number(accuracy.metrics.coverage_percent, 1)}%</span>`;
    const points = accuracy.points.map(point => ({ timestamp_utc: point.period_start_utc, has_observation: point.health_eligible === true, expected: point.expected_value, actual: point.actual_value }));
    const chart = makeChart("Scheduled expected versus eligible actual", "kW", [["Expected", "expected"], ["Actual", "actual"]], points, value => value / 1000, "Scored points are not yet available for this range.");
    const groups = [
      ["Horizon", accuracy.by_horizon], ["Local hour", accuracy.by_local_hour],
      ["Day type", accuracy.by_day_type], ["Model", accuracy.by_model_version],
      ["Forecast type", accuracy.by_forecast_type],
    ].flatMap(([title, values]) => Object.entries(values).map(([label, metric]) => metricCard(`${title}: ${label}`, metric)));
    const target = $("#accuracy-content"); target.innerHTML = ""; target.append(chart); target.insertAdjacentHTML("beforeend", groups.join(""));
  } catch (error) { setState("#operations-state", error.message, "error-state"); }
}

async function loadReserveHistory() {
  const target = $("#reserve-history");
  try {
    const data = await request("reserve-history", "reserve-history", { range: "30d" });
    if (!data.available) { target.innerHTML = `<div class="empty-state">${safeText(data.message)}</div>`; return; }
    target.innerHTML = `<div class="table-wrap"><table><thead><tr><th>Evaluation</th><th>Recommended</th><th>Gross</th><th>Battery</th><th>Demand</th><th>Uncertainty</th><th>Tradable</th><th>Confidence</th><th>Ready</th></tr></thead><tbody>${data.runs.map(run => `<tr><td>${localTime(run.evaluation_timestamp_utc)}</td><td>${energy(run.recommended_reserve_kwh)}</td><td>${energy(run.gross_reserve_requirement_kwh)}</td><td>${energy(run.battery_energy_kwh)}</td><td>${energy(run.expected_demand_kwh)}</td><td>${energy(run.uncertainty_buffer_kwh)}</td><td>${energy(run.potentially_tradable_kwh)}</td><td>${safeText(run.confidence)}</td><td>${run.readiness ? "Yes" : "No"}</td></tr>`).join("")}</tbody></table></div><p class="advisory">Advisory only. Every stored run records command_issued = false.</p>`;
  } catch (error) { target.innerHTML = `<div class="error-state">${safeText(error.message)}</div>`; }
}

async function loadQuality() {
  setState("#quality-state", "Loading bounded collection and health summary…");
  try {
    const [data, storage] = await Promise.all([request("quality", "data-quality", { range: "30d" }), request("storage", "forecast-storage")]); setState("#quality-state", `Quality from ${localTime(data.range_start_utc)} to ${localTime(data.range_end_utc)}.`);
    const cards = [
      ["Coverage", `${number(data.coverage_percent, 1)}%`, `${data.collected_slots} of ${data.expected_five_minute_slots} slots`],
      ["Missing slots", data.missing_slots, `Longest gap ${data.longest_gap_minutes} min`],
      ["Current collection", data.current_collection_healthy ? "Healthy" : "Needs attention", `Recent 24h coverage ${number(data.current_24h_coverage_percent, 1)}%; historic window missing ${data.historic_missing_slots}`],
      ["Complete days", data.complete_calendar_days, `${data.complete_overnight_periods} complete overnights`],
      ["Baseline training", data.eligible_baseline_rows, `${Object.values(data.ineligible_baseline_rows_by_reason).reduce((a,b) => a+b,0)} ineligible rows`],
      ["EV telemetry", data.ev_integration_configured ? data.ev_telemetry_fresh ? "Fresh" : "Needs attention" : "Disabled", data.ev_telemetry_available ? "Vehicle telemetry available" : "Vehicle telemetry unavailable"],
      ["Charger AC power", data.independent_ac_charger_power_available ? "Available" : "No", `${data.known_charging_rows_excluded} known charging rows excluded`],
      ["Power signs", `${data.configured_grid_power_sign} / ${data.configured_battery_power_sign}`, `${data.configured_sign_confidence} confidence; ${data.configured_sign_supporting_samples} samples; ${number(data.configured_balance_tolerance_w, 1)} W tolerance`],
      ["Balance residual", `P95 ${power(data.residual_p95_w)}`, `Median ${power(data.residual_median_w)}; max ${power(data.residual_max_w)}; ${data.rows_above_tolerance} above tolerance`],
      ["Weather features", data.weather_features, "Temperature model adjustment disabled / not implemented"],
      ["Forecast storage", `${storage.tables.reduce((sum, item) => sum + item.row_count, 0)} rows`, `${storage.retention_health}; detail ${storage.point_retention_days}d, runs ${storage.run_retention_days}d`],
      ["Training history", `${percent(data.verified_share * 100)} EV-verified`, `${percent(data.unverified_share * 100)} unverified; policy ${data.training_policy}`],
      ["Tier 1 readiness", `${data.exact_slots_currently_qualified} / ${data.exact_slots_total}`, `${number(data.exact_slot_coverage_percent, 2)}% exact weekday/five-minute buckets qualified`],
    ];
    const domains = Object.entries(data.domain_health).map(([name, value]) => `<article class="panel"><h3>${safeText(name[0].toUpperCase()+name.slice(1))}</h3>${definition([["Healthy", value.healthy_count], ["Unhealthy", value.unhealthy_count], ["Average score", percent(value.average_score)], ["Warnings", value.warning_count], ["Errors", value.error_count]])}<ul class="issue-list">${value.most_common_issues.slice(0,3).map(issue => `<li>${safeText(issue.code)} · ${issue.count}</li>`).join("") || "<li>No persisted issues</li>"}</ul></article>`).join("");
    const evWarning = data.ev_contamination_warning ? '<aside class="panel schema-notice" role="note"><strong>EV contamination warning</strong><p>Confirmed fresh charging rows are excluded, but EV energy separation is incomplete until independent charger AC power is measured and validated.</p></aside>' : "";
    $("#quality-content").innerHTML = `<div class="quality-grid">${cards.map(([label,value,detail]) => `<article class="panel"><p class="eyebrow">${safeText(label)}</p><div class="quality-metric">${safeText(value)}</div><p class="muted">${safeText(detail)}</p></article>`).join("")}${evWarning}</div><h3>Domain health</h3><div class="quality-grid">${domains}</div>`;
  } catch (error) { setState("#quality-state", error.message, "error-state"); }
}

async function loadCalibration() {
  setState("#calibration-state", "Loading aligned scheduled-run calibration...");
  try {
    const data = await request("calibration", "forecast-calibration", { range: "30d" });
    const metric = data.metrics;
    setState("#calibration-state", data.status_reason);
    const baseline = data.baseline_reference;
    const legacy = data.legacy_baseline_metrics;
    const identity = data.current_identity;
    const cards = [
      ["Current model status", data.status, `${data.complete_date_count} complete independent local date(s); ${data.complete_weekday_count} weekday and ${data.complete_weekend_count} weekend`],
      ["Raw rolling predictions", number(data.raw_prediction_row_count, 0), `${number(data.eligible_score_row_count, 0)} eligible score row(s); overlaps retained as operational volume`],
      ["Unique actual targets", number(data.unique_actual_target_slot_count, 0), `${number(data.eligible_actual_target_slot_count, 0)} eligible target slot(s); ${number(data.independent_target_horizon_slot_count, 0)} target/horizon cell(s)`],
      ["Durable rollup coverage", percent(data.rollup_completeness_percent), `${number(data.calculated_rollup_row_count, 0)} of ${number(data.expected_rollup_row_count, 0)} expected date/horizon rollup(s); ${data.truncated ? "explicitly truncated" : "not truncated"}`],
      ["Current model bias", power(metric.bias_w), "Positive means forecast above actual"],
      ["Current model MAE", power(metric.mae_w), `RMSE ${power(metric.rmse_w)}; WAPE ${percent(metric.wape_percent)}`],
      ["Current model coverage", percent(metric.coverage), `${metric.eligible_points} of ${metric.total_points} points`],
      ["Cumulative underforecast", energy(data.cumulative_underforecast_kwh), `P90 ${energy(data.p90_cumulative_underforecast_kwh)}; P95 ${energy(data.p95_cumulative_underforecast_kwh)}`],
      ["Pre-v0.5.1 / legacy baseline", legacy.eligible_points ? `Bias ${power(legacy.bias_w)}` : `Bias ${power(baseline.bias_w)}`, legacy.eligible_points ? `MAE ${power(legacy.mae_w)} from ${data.legacy_baseline_run_count} legacy run(s)` : `Measured reference MAE ${power(baseline.mae_w)}; 46.9 kWh forecast vs 27.8 kWh actual`],
      ["Current cohort", identity.alignment_version, `Policy ${identity.training_policy}; model ${identity.model_version}`],
    ];
    const horizons = Object.entries(data.metrics_by_horizon).map(([name, value]) => `<article class="panel"><h3>${safeText(name)}</h3>${definition([["Bias", power(value.bias_w)], ["MAE", power(value.mae_w)], ["RMSE", power(value.rmse_w)], ["Coverage", percent(value.coverage)]])}</article>`).join("");
    $("#calibration-content").innerHTML = `${cards.map(([label, value, detail]) => `<article class="panel"><p class="eyebrow">${safeText(label)}</p><div class="quality-metric">${safeText(value)}</div><p class="muted">${safeText(detail)}</p></article>`).join("")}${horizons}`;
  } catch (error) { setState("#calibration-state", error.message, "error-state"); }
}

async function loadSolarDiagnostics() {
  setState("#solar-state", "Loading daily Solcast and realised-PV evidence...");
  try {
    const data = await request("solar", "solar-forecast-diagnostics", { range: "30d" });
    setState("#solar-state", data.truncated ? "The bounded result was explicitly truncated." : "Daily diagnostics loaded; no automatic derating is applied.");
    $("#solar-content").innerHTML = data.days.map(day => `<article class="panel"><h3>${safeText(day.local_date)}</h3>${definition([["Evidence label", day.classification], ["Coverage", percent(day.coverage_percent)], ["Actual PV", energy(day.actual_pv_kwh)], ["Solcast P10 / P50 / P90", `${energy(day.solcast_p10_kwh)} / ${energy(day.solcast_p50_kwh)} / ${energy(day.solcast_p90_kwh)}`], ["Actual minus P50", energy(day.actual_minus_p50_kwh)], ["P50 percentage error", percent(day.p50_percentage_error)], ["Inside Solcast range", day.actual_in_solcast_range == null ? "Unavailable" : (day.actual_in_solcast_range ? "Yes" : "No")], ["Minimum battery headroom", percent(day.minimum_battery_headroom_percent)], ["Battery charge / discharge", `${number(day.battery_charge_minutes, 0)} / ${number(day.battery_discharge_minutes, 0)} min`], ["Near-full battery", `${number(day.near_full_battery_minutes, 0)} min`], ["Possible clipping context", `${number(day.possible_inverter_clipping_minutes, 0)} min`], ["Export context", `${number(day.export_minutes, 0)} min`], ["Observed work modes", (day.observed_work_modes || []).join(", ") || "Unavailable"]])}<p class="muted">${safeText(day.interpretation)}</p></article>`).join("") || '<article class="panel"><p>No sufficiently bounded daily data is available.</p></article>';
  } catch (error) { setState("#solar-state", error.message, "error-state"); }
}

function activateTab() {
  const name = location.hash.slice(1) || "overview"; const valid = $("#" + CSS.escape(name)) ? name : "overview";
  $$(".page").forEach(page => page.hidden = page.id !== valid); $$(".tabs a").forEach(link => link.setAttribute("aria-current", link.dataset.tab === valid ? "page" : "false"));
  if (valid === "history" && !state.loaded.has("history")) { state.loaded.add("history"); loadHistory(); }
  if (valid === "forecasts" && !state.loaded.has("forecasts")) { state.loaded.add("forecasts"); loadForecastRuns(); }
  if (valid === "forecast-operations" && !state.loaded.has("operations")) { state.loaded.add("operations"); loadForecastOperations(); }
  if (valid === "calibration" && !state.loaded.has("calibration")) { state.loaded.add("calibration"); loadCalibration(); }
  if (valid === "solar-diagnostics" && !state.loaded.has("solar")) { state.loaded.add("solar"); loadSolarDiagnostics(); }
  if (valid === "reserve" && !state.loaded.has("reserve")) { state.loaded.add("reserve"); loadReserve(); loadReserveHistory(); }
  if (valid === "decisions" && !state.loaded.has("decisions")) { state.loaded.add("decisions"); loadDecisions(); }
  if (valid === "data-quality" && !state.loaded.has("quality")) { state.loaded.add("quality"); loadQuality(); }
}

function schedule(key, callback, milliseconds) { clearInterval(state.timers.get(key)); state.timers.set(key, setInterval(() => { if (!document.hidden) callback(); }, milliseconds)); }
document.addEventListener("visibilitychange", () => { if (document.hidden) state.controllers.forEach(controller => controller.abort()); else { loadStatus(); loadLive(); } });
window.addEventListener("hashchange", activateTab);
$("#history-range").addEventListener("change", loadHistory);
$("#forecast-run").addEventListener("change", loadForecastComparison);
$("#accuracy-range").addEventListener("change", loadForecastOperations);
$("#accuracy-run").addEventListener("change", loadForecastOperations);
const storedForecastCardMode = localStorage.getItem("forecast-card-mode");
if (["live", "latest_complete"].includes(storedForecastCardMode)) $("#forecast-card-mode").value = storedForecastCardMode;
$("#forecast-card-mode").addEventListener("change", () => {
  localStorage.setItem("forecast-card-mode", $("#forecast-card-mode").value);
  loadForecastActualCard();
});

loadStatus(); loadLive(); loadShadowOverview(); loadForecastActualCard(); loadReserve(); loadReserveHistory(); state.loaded.add("reserve"); activateTab();
schedule("status", loadStatus, 30000); schedule("live", loadLive, 30000);
schedule("slow", () => { if (!document.hidden) { loadShadowOverview(); loadForecastActualCard(); if (state.loaded.has("history")) loadHistory(); if (state.loaded.has("forecasts")) loadForecastRuns(); if (state.loaded.has("operations")) loadForecastOperations(); if (state.loaded.has("calibration")) loadCalibration(); if (state.loaded.has("solar")) loadSolarDiagnostics(); if (state.loaded.has("reserve")) { loadReserve(); loadReserveHistory(); } if (state.loaded.has("decisions")) loadDecisions(); if (state.loaded.has("quality")) loadQuality(); } }, 300000);
