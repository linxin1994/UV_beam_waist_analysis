"""JSON boundary between the browser worker and numerical analysis."""

from __future__ import annotations

import base64
from io import BytesIO
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from beam_analysis import diagnostic_figure, fit_uv_beam_image, image_bytes_to_grayscale, result_row


def analyze_file(path, filename, pixel_size_um, roi_half_width_pixels, fit_stride, smoothing_sigma_pixels):
    """Analyze one browser-uploaded file and return JSON-safe results."""
    with open(path, "rb") as image_file:
        image = image_bytes_to_grayscale(image_file.read())
    result = fit_uv_beam_image(
        image=image,
        filename=filename,
        pixel_size_um=float(pixel_size_um),
        roi_half_width_pixels=int(roi_half_width_pixels),
        fit_stride=int(fit_stride),
        smoothing_sigma_pixels=float(smoothing_sigma_pixels),
    )
    figure = diagnostic_figure(result)
    plot_buffer = BytesIO()
    figure.savefig(plot_buffer, format="png", dpi=150, bbox_inches="tight")
    plt.close(figure)
    return json.dumps({
        "row": result_row(result),
        "plot": base64.b64encode(plot_buffer.getvalue()).decode("ascii"),
    }, allow_nan=False)
