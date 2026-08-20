"use strict";

const el = {
  files: document.querySelector("#image-files"), fileSummary: document.querySelector("#file-summary"),
  uploadZone: document.querySelector("#upload-zone"), pixelSize: document.querySelector("#pixel-size"),
  roi: document.querySelector("#roi-half-width"), stride: document.querySelector("#fit-stride"),
  smoothing: document.querySelector("#smoothing-sigma"), analyze: document.querySelector("#analyze-button"),
  status: document.querySelector("#status"), badge: document.querySelector("#runtime-badge"),
  results: document.querySelector("#results-section"), diagnostics: document.querySelector("#diagnostics-section"),
  table: document.querySelector("#summary-table"), cards: document.querySelector("#diagnostic-cards"),
  errors: document.querySelector("#error-list"), downloadCsv: document.querySelector("#download-csv"),
};
let runtimeReady = false;
let analyzing = false;
let latestRows = [];
const worker = new Worker("pyodide-worker.js?v=self-hosted-1");

function updateButton() {
  el.analyze.disabled = !runtimeReady || analyzing || el.files.files.length === 0;
}
function setStatus(message, kind = "normal") {
  el.status.textContent = message;
  el.status.className = `status status--${kind}`;
}
function fixed(value, digits = 2) { return Number(value).toFixed(digits); }
function addCell(row, text, tag = "td") {
  const cell = document.createElement(tag);
  cell.textContent = text;
  row.appendChild(cell);
}
function renderSummary(rows) {
  el.table.replaceChildren();
  const head = document.createElement("thead");
  const header = document.createElement("tr");
  ["File", "Major w (µm)", "Minor w (µm)", "Ellipticity", "Angle", "RMS residual"].forEach(
    (label) => addCell(header, label, "th")
  );
  head.appendChild(header);
  const body = document.createElement("tbody");
  rows.forEach((row) => {
    const line = document.createElement("tr");
    addCell(line, row.file);
    addCell(line, `${fixed(row["w major (um)"])} ± ${fixed(row["sigma w major (um)"])}`);
    addCell(line, `${fixed(row["w minor (um)"])} ± ${fixed(row["sigma w minor (um)"])}`);
    addCell(line, fixed(row.ellipticity, 3));
    addCell(line, `${fixed(row["angle (deg)"])}°`);
    addCell(line, `${fixed(row["RMS residual (count)"])} counts`);
    body.appendChild(line);
  });
  el.table.append(head, body);
}
function metric(label, value) {
  const box = document.createElement("div");
  box.className = "metric";
  const name = document.createElement("span");
  name.textContent = label;
  const number = document.createElement("strong");
  number.textContent = value;
  box.append(name, number);
  return box;
}
function triggerDownload(url, filename) {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}
function renderDiagnostic(result) {
  const row = result.row;
  const card = document.createElement("article");
  card.className = "diagnostic-card";
  const titleRow = document.createElement("div");
  titleRow.className = "card-title-row";
  const title = document.createElement("h3");
  title.textContent = row.file;
  const download = document.createElement("button");
  download.type = "button";
  download.className = "secondary-button compact-button";
  download.textContent = "Download plot";
  const stem = row.file.replace(/\.[^.]+$/, "").replace(/[^a-zA-Z0-9_-]+/g, "_");
  download.addEventListener("click", () => triggerDownload(`data:image/png;base64,${result.plot}`, `${stem}_beam_fit.png`));
  titleRow.append(title, download);
  const metrics = document.createElement("div");
  metrics.className = "metrics";
  metrics.append(
    metric("Major radius", `${fixed(row["w major (um)"])} µm`),
    metric("Minor radius", `${fixed(row["w minor (um)"])} µm`),
    metric("Ellipticity", fixed(row.ellipticity, 3)),
    metric("Angle", `${fixed(row["angle (deg)"])}°`)
  );
  const image = document.createElement("img");
  image.src = `data:image/png;base64,${result.plot}`;
  image.alt = `Fit diagnostics for ${row.file}`;
  image.loading = "lazy";
  card.append(titleRow, metrics, image);
  el.cards.appendChild(card);
}
function showErrors(errors) {
  el.errors.replaceChildren();
  errors.forEach((error) => {
    const item = document.createElement("p");
    item.textContent = `${error.filename}: ${error.message}`;
    el.errors.appendChild(item);
  });
}
function csvEscape(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}
function downloadCsv() {
  if (!latestRows.length) return;
  const headers = Object.keys(latestRows[0]);
  const lines = [headers.map(csvEscape).join(",")];
  latestRows.forEach((row) => lines.push(headers.map((header) => csvEscape(row[header])).join(",")));
  const url = URL.createObjectURL(new Blob([`${lines.join("\n")}\n`], { type: "text/csv;charset=utf-8" }));
  triggerDownload(url, "uv_beam_waist_results.csv");
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

el.files.addEventListener("change", () => {
  const files = Array.from(el.files.files);
  el.fileSummary.textContent = files.length
    ? `${files.length} image${files.length === 1 ? "" : "s"}: ${files.map((file) => file.name).join(", ")}`
    : "No images selected";
  el.uploadZone.classList.toggle("upload-zone--selected", files.length > 0);
  updateButton();
});
el.downloadCsv.addEventListener("click", downloadCsv);
el.analyze.addEventListener("click", async () => {
  const files = Array.from(el.files.files);
  const settings = {
    pixelSizeUm: Number(el.pixelSize.value), roiHalfWidthPixels: Number(el.roi.value),
    fitStride: Number(el.stride.value), smoothingSigmaPixels: Number(el.smoothing.value),
  };
  if (!(settings.pixelSizeUm > 0)) {
    setStatus("Pixel size must be greater than zero.", "error");
    return;
  }
  analyzing = true;
  updateButton();
  el.analyze.textContent = "Analyzing…";
  el.results.classList.add("hidden");
  el.diagnostics.classList.add("hidden");
  el.cards.replaceChildren();
  setStatus(`Reading ${files.length} image${files.length === 1 ? "" : "s"}…`, "working");
  const payload = await Promise.all(files.map(async (file) => ({ name: file.name, buffer: await file.arrayBuffer() })));
  worker.postMessage({ type: "analyze", files: payload, settings }, payload.map((file) => file.buffer));
});

worker.addEventListener("message", ({ data }) => {
  if (data.type === "status") setStatus(data.message, "working");
  if (data.type === "ready") {
    runtimeReady = true;
    el.badge.textContent = "Analysis engine ready";
    el.badge.className = "badge badge--ready";
    setStatus("Ready. Select image files and start the analysis.", "success");
    updateButton();
  }
  if (data.type === "progress") setStatus(`Analyzing ${data.filename} (${data.index} of ${data.total})…`, "working");
  if (data.type === "complete") {
    analyzing = false;
    el.analyze.textContent = "Analyze selected images";
    latestRows = data.results.map((result) => result.row);
    renderSummary(latestRows);
    el.cards.replaceChildren();
    data.results.forEach(renderDiagnostic);
    showErrors(data.errors);
    el.results.classList.remove("hidden");
    el.diagnostics.classList.toggle("hidden", data.results.length === 0);
    const suffix = data.errors.length ? ` with ${data.errors.length} error${data.errors.length === 1 ? "" : "s"}.` : ".";
    setStatus(`Finished ${data.results.length} fit${data.results.length === 1 ? "" : "s"}${suffix}`, data.errors.length ? "error" : "success");
    updateButton();
  }
  if (data.type === "fatal") {
    analyzing = false;
    el.analyze.textContent = "Analyze selected images";
    el.badge.textContent = "Analysis engine error";
    el.badge.className = "badge badge--error";
    setStatus(data.message, "error");
    updateButton();
  }
});
worker.addEventListener("error", (event) => {
  analyzing = false;
  el.badge.textContent = "Analysis engine error";
  el.badge.className = "badge badge--error";
  setStatus(`Browser analysis worker failed: ${event.message}`, "error");
  updateButton();
});
