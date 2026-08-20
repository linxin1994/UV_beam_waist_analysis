"use strict";

const PYODIDE_VERSION = "314.0.3";
const PYODIDE_BASE = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
let pyodide;

async function initialize() {
  self.postMessage({ type: "status", message: "Downloading the browser Python runtime…" });
  importScripts(`${PYODIDE_BASE}pyodide.js`);
  pyodide = await loadPyodide({ indexURL: PYODIDE_BASE });
  self.postMessage({ type: "status", message: "Loading NumPy, SciPy, Pillow, and Matplotlib…" });
  await pyodide.loadPackage(["numpy", "scipy", "Pillow", "matplotlib"]);
  const [analysisResponse, apiResponse] = await Promise.all([fetch("beam_analysis.py"), fetch("web_api.py")]);
  if (!analysisResponse.ok || !apiResponse.ok) throw new Error("Could not load the local analysis code.");
  pyodide.FS.writeFile("/home/pyodide/beam_analysis.py", await analysisResponse.text(), { encoding: "utf8" });
  pyodide.FS.writeFile("/home/pyodide/web_api.py", await apiResponse.text(), { encoding: "utf8" });
  pyodide.runPython("import web_api");
  self.postMessage({ type: "ready" });
}

const readyPromise = initialize().catch((error) => {
  self.postMessage({ type: "fatal", message: `Could not start the analysis engine: ${error.message}` });
  throw error;
});

self.addEventListener("message", async ({ data }) => {
  if (data.type !== "analyze") return;
  try {
    await readyPromise;
    const results = [];
    const errors = [];
    for (let index = 0; index < data.files.length; index += 1) {
      const file = data.files[index];
      self.postMessage({ type: "progress", filename: file.name, index: index + 1, total: data.files.length });
      const path = `/tmp/uv_beam_upload_${index}`;
      try {
        pyodide.FS.writeFile(path, new Uint8Array(file.buffer));
        pyodide.globals.set("web_path", path);
        pyodide.globals.set("web_filename", file.name);
        pyodide.globals.set("web_pixel_size", data.settings.pixelSizeUm);
        pyodide.globals.set("web_roi_half_width", data.settings.roiHalfWidthPixels);
        pyodide.globals.set("web_fit_stride", data.settings.fitStride);
        pyodide.globals.set("web_smoothing_sigma", data.settings.smoothingSigmaPixels);
        const resultJson = pyodide.runPython(`web_api.analyze_file(
            web_path, web_filename, web_pixel_size, web_roi_half_width,
            web_fit_stride, web_smoothing_sigma)`);
        results.push(JSON.parse(resultJson));
      } catch (error) {
        errors.push({ filename: file.name, message: String(error.message || error) });
      } finally {
        try { pyodide.FS.unlink(path); } catch (_) { /* Nothing to remove. */ }
      }
    }
    self.postMessage({ type: "complete", results, errors });
  } catch (error) {
    self.postMessage({ type: "fatal", message: `Analysis failed: ${error.message}` });
  }
});
