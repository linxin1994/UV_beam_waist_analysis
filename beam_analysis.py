"""Numerical analysis and plotting for the UV beam-waist web app."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Ellipse
from PIL import Image
from scipy.ndimage import gaussian_filter, map_coordinates
from scipy.optimize import least_squares


@dataclass
class BeamFitResult:
    filename: str
    image: np.ndarray
    roi: np.ndarray
    fitted_roi: np.ndarray
    residual: np.ndarray
    roi_bounds: tuple[int, int, int, int]
    peak_pixel: tuple[int, int]
    center_pixel: tuple[float, float]
    parameters: np.ndarray
    uncertainties: np.ndarray
    pixel_size_um: float
    rms_residual_counts: float


def rotated_gaussian_with_plane(
    coordinates: tuple[np.ndarray, np.ndarray],
    amplitude: float,
    x0: float,
    y0: float,
    w1: float,
    w2: float,
    theta: float,
    background: float,
    slope_x: float,
    slope_y: float,
) -> np.ndarray:
    """Rotated elliptical Gaussian on a planar background."""
    x, y = coordinates
    cosine, sine = np.cos(theta), np.sin(theta)
    x_prime = cosine * (x - x0) + sine * (y - y0)
    y_prime = -sine * (x - x0) + cosine * (y - y0)
    gaussian = amplitude * np.exp(
        -2.0 * ((x_prime / w1) ** 2 + (y_prime / w2) ** 2)
    )
    return background + slope_x * x + slope_y * y + gaussian


def image_bytes_to_grayscale(image_bytes: bytes) -> np.ndarray:
    """Decode an uploaded image as a two-dimensional floating-point array."""
    with Image.open(BytesIO(image_bytes)) as source:
        return np.asarray(source.convert("L"), dtype=float)


def fit_uv_beam_image(
    image: np.ndarray,
    filename: str,
    pixel_size_um: float = 5.0,
    roi_half_width_pixels: int = 300,
    fit_stride: int = 3,
    smoothing_sigma_pixels: float = 10.0,
) -> BeamFitResult:
    """Fit one grayscale beam image to the notebook's robust Gaussian model."""
    if image.ndim != 2 or min(image.shape) < 3:
        raise ValueError("The uploaded image must contain a 2D image at least 3 pixels wide.")
    if not np.all(np.isfinite(image)):
        raise ValueError("The uploaded image contains invalid pixel values.")
    if pixel_size_um <= 0:
        raise ValueError("Pixel size must be greater than zero.")
    if roi_half_width_pixels < 2 or fit_stride < 1 or smoothing_sigma_pixels < 0:
        raise ValueError("The advanced fit settings are outside their allowed range.")

    smoothed = gaussian_filter(image, smoothing_sigma_pixels)
    peak_y, peak_x = np.unravel_index(np.argmax(smoothed), smoothed.shape)

    y_start = max(0, peak_y - roi_half_width_pixels)
    y_stop = min(image.shape[0], peak_y + roi_half_width_pixels + 1)
    x_start = max(0, peak_x - roi_half_width_pixels)
    x_stop = min(image.shape[1], peak_x + roi_half_width_pixels + 1)
    roi = image[y_start:y_stop, x_start:x_stop]

    y_pixels = np.arange(y_start, y_stop, fit_stride)
    x_pixels = np.arange(x_start, x_stop, fit_stride)
    if len(x_pixels) < 3 or len(y_pixels) < 3:
        raise ValueError("The ROI is too small for the selected fit stride.")

    y_um = (y_pixels - peak_y) * pixel_size_um
    x_um = (x_pixels - peak_x) * pixel_size_um
    x_grid, y_grid = np.meshgrid(x_um, y_um)
    fit_data = image[np.ix_(y_pixels, x_pixels)]

    edge_values = np.concatenate((roi[0], roi[-1], roi[:, 0], roi[:, -1]))
    background_guess = float(np.median(edge_values))
    amplitude_guess = max(float(np.percentile(roi, 99.9) - background_guess), 1.0)
    signal = np.clip(fit_data - background_guess, 0.0, None)
    signal = np.where(signal >= 0.08 * amplitude_guess, signal, 0.0)
    if np.sum(signal) <= 0.0:
        signal = np.clip(fit_data - background_guess, 0.0, None)
    normalization = float(np.sum(signal))
    if normalization <= 0.0:
        raise ValueError("No beam-like signal could be identified in this image.")

    x0_guess = float(np.sum(signal * x_grid) / normalization)
    y0_guess = float(np.sum(signal * y_grid) / normalization)
    dx, dy = x_grid - x0_guess, y_grid - y0_guess
    covariance = np.asarray(
        [
            [np.sum(signal * dx * dx), np.sum(signal * dx * dy)],
            [np.sum(signal * dx * dy), np.sum(signal * dy * dy)],
        ]
    ) / normalization
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues, eigenvectors = eigenvalues[order], eigenvectors[:, order]
    waist_guesses = 2.0 * np.sqrt(np.maximum(eigenvalues, pixel_size_um**2))
    theta_guess = float(np.arctan2(eigenvectors[1, 0], eigenvectors[0, 0]))

    initial = np.asarray(
        [
            amplitude_guess,
            x0_guess,
            y0_guess,
            *waist_guesses,
            theta_guess,
            background_guess,
            0.0,
            0.0,
        ]
    )
    x_extent = max(abs(x_um[0]), abs(x_um[-1]))
    y_extent = max(abs(y_um[0]), abs(y_um[-1]))
    maximum_waist = 2.0 * max(x_extent, y_extent)
    lower = np.asarray(
        [0.0, x_um[0], y_um[0], pixel_size_um, pixel_size_um, -np.pi, 0.0, -1.0, -1.0]
    )
    upper = np.asarray(
        [
            4.0 * max(amplitude_guess, 1.0),
            x_um[-1],
            y_um[-1],
            maximum_waist,
            maximum_waist,
            np.pi,
            255.0,
            1.0,
            1.0,
        ]
    )
    initial = np.clip(initial, lower + 1e-9, upper - 1e-9)

    def residual_function(parameters: np.ndarray) -> np.ndarray:
        return (
            rotated_gaussian_with_plane((x_grid, y_grid), *parameters) - fit_data
        ).ravel()

    optimization = least_squares(
        residual_function,
        initial,
        bounds=(lower, upper),
        loss="soft_l1",
        f_scale=max(1.0, 0.03 * amplitude_guess),
        x_scale="jac",
        max_nfev=3000,
    )
    if not optimization.success:
        raise RuntimeError(f"Fit failed: {optimization.message}")

    parameters = optimization.x.copy()
    swapped_axes = parameters[3] < parameters[4]
    if swapped_axes:
        parameters[3], parameters[4] = parameters[4], parameters[3]
        parameters[5] += np.pi / 2.0
    parameters[5] = (parameters[5] + np.pi / 2.0) % np.pi - np.pi / 2.0

    residuals = residual_function(optimization.x)
    degrees_of_freedom = max(residuals.size - parameters.size, 1)
    residual_variance = float(np.sum(residuals**2) / degrees_of_freedom)
    covariance_fit = residual_variance * np.linalg.pinv(
        optimization.jac.T @ optimization.jac
    )
    uncertainties = np.sqrt(np.maximum(np.diag(covariance_fit), 0.0))
    if swapped_axes:
        uncertainties[3], uncertainties[4] = uncertainties[4], uncertainties[3]

    _, x0, y0, _, _, _, _, _, _ = parameters
    center_x_pixel = peak_x + x0 / pixel_size_um
    center_y_pixel = peak_y + y0 / pixel_size_um
    y_full_um = (np.arange(y_start, y_stop) - peak_y) * pixel_size_um
    x_full_um = (np.arange(x_start, x_stop) - peak_x) * pixel_size_um
    x_full_grid, y_full_grid = np.meshgrid(x_full_um, y_full_um)
    fitted_roi = rotated_gaussian_with_plane((x_full_grid, y_full_grid), *parameters)

    return BeamFitResult(
        filename=filename,
        image=image,
        roi=roi,
        fitted_roi=fitted_roi,
        residual=roi - fitted_roi,
        roi_bounds=(x_start, x_stop, y_start, y_stop),
        peak_pixel=(int(peak_x), int(peak_y)),
        center_pixel=(float(center_x_pixel), float(center_y_pixel)),
        parameters=parameters,
        uncertainties=uncertainties,
        pixel_size_um=float(pixel_size_um),
        rms_residual_counts=float(np.sqrt(np.mean((roi - fitted_roi) ** 2))),
    )


def principal_axis_cut(
    result: BeamFitResult, axis_index: int, number_of_points: int = 401
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return measured and fitted profiles through a principal axis."""
    _, x0, y0, w1, w2, theta, _, _, _ = result.parameters
    waist = (w1, w2)[axis_index]
    distance_um = np.linspace(-1.7 * waist, 1.7 * waist, number_of_points)
    if axis_index == 0:
        direction = np.asarray([np.cos(theta), np.sin(theta)])
    else:
        direction = np.asarray([-np.sin(theta), np.cos(theta)])
    center_x_pixel, center_y_pixel = result.center_pixel
    sample_x = center_x_pixel + distance_um * direction[0] / result.pixel_size_um
    sample_y = center_y_pixel + distance_um * direction[1] / result.pixel_size_um
    measured = map_coordinates(
        result.image, [sample_y, sample_x], order=1, mode="nearest"
    )
    x_line = x0 + distance_um * direction[0]
    y_line = y0 + distance_um * direction[1]
    fitted = rotated_gaussian_with_plane((x_line, y_line), *result.parameters)
    return distance_um, measured, fitted


def result_row(result: BeamFitResult) -> dict[str, float | str]:
    """Convert a fit into a flat, downloadable summary row."""
    _, _, _, w1, w2, theta, _, _, _ = result.parameters
    return {
        "file": result.filename,
        "pixel size (um/pixel)": result.pixel_size_um,
        "center x (pixel)": result.center_pixel[0],
        "center y (pixel)": result.center_pixel[1],
        "w major (um)": w1,
        "sigma w major (um)": result.uncertainties[3],
        "w minor (um)": w2,
        "sigma w minor (um)": result.uncertainties[4],
        "ellipticity": w1 / w2,
        "angle (deg)": np.degrees(theta),
        "RMS residual (count)": result.rms_residual_counts,
    }


def diagnostic_figure(result: BeamFitResult) -> plt.Figure:
    """Build the four-panel diagnostic plot used by the notebook."""
    _, _, _, w1, w2, theta, _, _, _ = result.parameters
    x_start, x_stop, y_start, y_stop = result.roi_bounds
    center_x_pixel, center_y_pixel = result.center_pixel
    pixel_size_um = result.pixel_size_um
    extent_um = [
        (x_start - center_x_pixel) * pixel_size_um,
        (x_stop - 1 - center_x_pixel) * pixel_size_um,
        (y_stop - 1 - center_y_pixel) * pixel_size_um,
        (y_start - center_y_pixel) * pixel_size_um,
    ]
    display_min, display_max = np.percentile(result.roi, [1, 99.8])
    if display_max <= display_min:
        display_max = display_min + 1.0
    residual_limit = max(float(np.percentile(np.abs(result.residual), 99)), 1e-9)

    figure, axes = plt.subplots(2, 2, figsize=(9.0, 7.0), constrained_layout=True)
    image_artist = axes[0, 0].imshow(
        result.roi,
        origin="upper",
        extent=extent_um,
        cmap="inferno",
        vmin=display_min,
        vmax=display_max,
    )
    axes[0, 0].add_patch(
        Ellipse(
            (0.0, 0.0),
            2.0 * w1,
            2.0 * w2,
            angle=np.degrees(theta),
            fill=False,
            color="cyan",
            linewidth=1.2,
            label="1/e^2 contour",
        )
    )
    axes[0, 0].plot(0.0, 0.0, "c+", markersize=8, markeredgewidth=1.2)
    axes[0, 0].set_title("Measured ROI")
    axes[0, 0].legend(frameon=False, fontsize=8, loc="upper right")
    figure.colorbar(image_artist, ax=axes[0, 0], label="Camera counts")

    fit_artist = axes[0, 1].imshow(
        result.fitted_roi,
        origin="upper",
        extent=extent_um,
        cmap="inferno",
        vmin=display_min,
        vmax=display_max,
    )
    axes[0, 1].set_title("Robust rotated-Gaussian fit")
    figure.colorbar(fit_artist, ax=axes[0, 1], label="Camera counts")

    residual_artist = axes[1, 0].imshow(
        result.residual,
        origin="upper",
        extent=extent_um,
        cmap="RdBu_r",
        vmin=-residual_limit,
        vmax=residual_limit,
    )
    axes[1, 0].set_title(f"Residual (RMS={result.rms_residual_counts:.2f} counts)")
    figure.colorbar(residual_artist, ax=axes[1, 0], label="Data - fit (count)")

    for axis_index, color, label in ((0, "C0", "major"), (1, "C1", "minor")):
        distance_um, measured, fitted = principal_axis_cut(result, axis_index)
        axes[1, 1].plot(
            distance_um, measured, ".", color=color, markersize=2.0, alpha=0.55
        )
        axes[1, 1].plot(
            distance_um,
            fitted,
            "-",
            color=color,
            linewidth=1.2,
            label=f"{label}: w={((w1, w2)[axis_index]):.1f} um",
        )
    axes[1, 1].set_title("Principal-axis cuts")
    axes[1, 1].set_xlabel("Position from fitted center (um)")
    axes[1, 1].set_ylabel("Camera counts")
    axes[1, 1].legend(frameon=False, fontsize=8)

    for axis in axes[:, 0]:
        axis.set_xlabel("Camera x relative to center (um)")
        axis.set_ylabel("Camera y relative to center (um)")
    axes[0, 1].set_xlabel("Camera x relative to center (um)")
    axes[0, 1].set_ylabel("Camera y relative to center (um)")
    figure.suptitle(result.filename, fontsize=10)
    return figure
