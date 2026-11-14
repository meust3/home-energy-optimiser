"use strict";
const byId = id => document.getElementById(id);
function value(target, key) {
  const item = target.body[key];
  return item?.presence === "VALUE" ? String(item.value) : "Missing";
}
let archiveController;
async function readArchive(reset = false) {
  archiveController?.abort();
  const controller = new AbortController();
  archiveController = controller;
  const url = new URL("api/v1/weather", document.baseURI);
  url.searchParams.set("limit", "200");
  if (!reset && byId("weather-cycle").value) url.searchParams.set("cycle_id", byId("weather-cycle").value);
  if (byId("weather-asof").value.trim()) url.searchParams.set("as_of", byId("weather-asof").value.trim());
  try {
    const response = await fetch(url, {method: "GET", cache: "no-store", signal: controller.signal});
    const payload = await response.json();
    controller.signal.throwIfAborted();
    if (!response.ok) throw new Error(payload.error?.message || "Archive unavailable");
    byId("weather-status").textContent = `Collection: ${payload.collection.status}. Showing ${payload.cycles.length} recent cycles (up to 100), not the total archive count.`;
    const select = byId("weather-cycle"); select.replaceChildren();
    for (const cycle of payload.cycles) {
      const option = document.createElement("option"); option.value = cycle.id;
      option.textContent = `${cycle.created_at} · ${cycle.status}`;
      option.selected = cycle.id === payload.selected?.cycle_id; select.append(option);
    }
    const selected = payload.selected;
    byId("weather-coverage").textContent = selected
      ? `${selected.status} · ${selected.window_start} to ${selected.window_end} (end exclusive). Each page keeps its own receipt and content versions.`
      : "No stored weather captures are available.";
    const rows = byId("weather-targets"); rows.replaceChildren();
    for (const target of selected?.targets || []) {
      const row = document.createElement("tr");
      for (const cellValue of [target.target_at, value(target, "temperature"), value(target, "cloud_cover"), value(target, "rain_1h_rate"), target.received_at, target.page_number, target.payload_sha256]) {
        const cell = document.createElement("td"); cell.textContent = String(cellValue ?? "UNKNOWN"); row.append(cell);
      }
      rows.append(row);
    }
  } catch (error) { if (error.name === "AbortError") return; byId("weather-status").textContent = `Weather archive: ${error.message}. Previously displayed results may be stale.`; }
  finally { if (archiveController === controller) archiveController = null; }
}
byId("weather-refresh").addEventListener("click", () => readArchive(true));
byId("weather-cycle").addEventListener("change", () => readArchive());
readArchive(true);
