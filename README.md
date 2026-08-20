# UV beam-waist browser app

This static webpage reproduces the robust rotated-Gaussian analysis in
`data_analysis/UV_beam_waist_analysis.ipynb`. It accepts one or more camera
images, uses a configurable pixel calibration (default: 5.0 µm/pixel), displays
fit diagnostics, and exports a CSV summary.

All image decoding, SciPy fitting, and Matplotlib rendering run locally in the
visitor's browser through Pyodide/WebAssembly. The static host only serves the
app files; images are not transmitted to an analysis server.

## Test locally

Browsers do not allow the worker to load its files from a `file://` URL. Serve
the folder with any static file server, then open the printed local URL:

```bash
cd apps/uv_beam_waist
python -m http.server 8000
```

Open `http://localhost:8000`. The first visit downloads Pyodide and the NumPy,
SciPy, Pillow, and Matplotlib browser packages from jsDelivr. A modern browser
and an internet connection are therefore required on first load.

## Publish it as a URL

The folder can be deployed unchanged to any static host. This repository's
GitHub Actions workflow publishes it to GitHub Pages after Pages is configured
to use **GitHub Actions** under repository Settings → Pages. No Python server or
build step is required.

## Default analysis settings

- Pixel size: 5.0 µm/pixel
- ROI half-width: 300 pixels
- Fit stride: 3 pixels
- Peak-detection smoothing: 10 pixels

Large images and multiple fits can take longer in WebAssembly than native
Python. The computation runs in a Web Worker so the page remains responsive.
